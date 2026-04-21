"""Ingest orchestrator.

Walks a source directory, dispatches each file to the converter (for
structured document formats) or a parser (for transcript/export formats),
writes the resulting markdown into the vault, records SHA256 in the ledger
to dedup future re-runs, and returns a report.

Staging vs. direct:
  - staging mode (default): output goes under <vault>/_staging/<wing>/...
    so the user can review before moving notes into permanent wing folders.
  - direct mode: output goes straight to <vault>/<wing>/... .

Format routing:
  1. If the path matches a registered Parser's heuristics, use it (produces
     N ParsedDocuments, one per contained conversation/session).
  2. Else if converter has a handler for the extension, run it.
  3. Else skip and record in the unhandled list.

Deduplication is keyed by SHA256 of the source file. If a file has already
been ingested, subsequent runs skip it unless `--force` is passed.
"""

from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable

from mymory.core.converter import CONVERTERS, convert_file
from mymory.core.ledger import IngestLedger, default_ledger_path
from mymory.core.note import make_slug, new_note, write_note
from mymory.core.vault import Vault
from mymory.parsers import all_parsers, parser_for
from mymory.parsers.base import ParsedDocument, Parser


# ----------------------------------------------------------------------
# Report datatypes
# ----------------------------------------------------------------------


@dataclass
class IngestItem:
    source_path: str
    status: str                  # "converted" | "parsed" | "skipped_dedup" | "unhandled" | "error"
    dest_paths: list[str] = field(default_factory=list)
    parser: str = ""
    source_format: str = ""
    message: str = ""
    sha256: str = ""


@dataclass
class IngestReport:
    root: str
    wing: str
    staging: bool
    started_at: str
    finished_at: str = ""
    items: list[IngestItem] = field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for it in self.items:
            out[it.status] = out.get(it.status, 0) + 1
        return out

    def render_summary(self) -> str:
        lines = [
            f"# Ingest report",
            f"- root: `{self.root}`",
            f"- wing: `{self.wing}`",
            f"- mode: {'staging' if self.staging else 'direct'}",
            f"- started:  {self.started_at}",
            f"- finished: {self.finished_at}",
            "",
            "## Counts",
        ]
        for k, v in sorted(self.counts.items()):
            lines.append(f"- {k}: {v}")
        errors = [it for it in self.items if it.status == "error"]
        if errors:
            lines.append("")
            lines.append("## Errors")
            for it in errors[:25]:
                lines.append(f"- `{it.source_path}` -> {it.message}")
        unhandled = [it for it in self.items if it.status == "unhandled"]
        if unhandled:
            lines.append("")
            lines.append(f"## Unhandled ({len(unhandled)})")
            for it in unhandled[:25]:
                lines.append(f"- `{it.source_path}`")
        return "\n".join(lines)


# ----------------------------------------------------------------------
# File walking
# ----------------------------------------------------------------------


DEFAULT_IGNORE = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", ".embed_cache",
    "_staging", ".DS_Store",
}


def _iter_files(root: str, extensions: set[str] | None = None) -> Iterable[str]:
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in DEFAULT_IGNORE]
        for name in filenames:
            if name.startswith("."):
                continue
            path = os.path.join(dirpath, name)
            if extensions is not None:
                ext = os.path.splitext(name)[1].lower()
                if ext not in extensions:
                    continue
            yield path


def _sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


# ----------------------------------------------------------------------
# Dispatch
# ----------------------------------------------------------------------


def _select_parser(path: str) -> Parser | None:
    # All parsers that claim the extension get a shot at heuristics.
    candidates = [p for p in all_parsers() if p.handles(path)]
    return candidates[0] if candidates else None


def _ext_supported_by_converter(path: str) -> bool:
    ext = os.path.splitext(path)[1].lower()
    return ext in CONVERTERS


# ----------------------------------------------------------------------
# Write helpers
# ----------------------------------------------------------------------


def _write_parsed_document(
    doc: ParsedDocument,
    vault: Vault,
    wing: str,
    staging: bool,
) -> str:
    slug = doc.slug_hint or make_slug(doc.title)

    extra = dict(doc.extra_frontmatter or {})
    extra.setdefault("source_file", doc.source_file)
    extra.setdefault("source_format", doc.source_format)
    extra.setdefault("source_agent", doc.source_agent or "unknown")
    extra.setdefault("confidence", doc.confidence or "VERBATIM")
    if doc.source_model:
        extra.setdefault("source_model", doc.source_model)
    if doc.tags:
        extra.setdefault("tags", list(doc.tags))
    if doc.entities:
        extra.setdefault("entities", list(doc.entities))

    date = doc.created or datetime.now().strftime("%Y-%m-%d")

    if staging:
        # Flat _staging/<wing>/YYYY-MM-DD_slug.md so the user can promote
        # easily. Keep the true wing in the frontmatter under `pending_wing`.
        staging_dir = os.path.join(vault.root, "_staging", wing)
        os.makedirs(staging_dir, exist_ok=True)
        fm: dict = {"title": doc.title, "wing": wing, "created": date,
                    "pending_wing": wing, **extra}
        final_path = os.path.join(staging_dir, f"{date}_{slug}.md")
        n = 2
        while os.path.exists(final_path):
            final_path = os.path.join(staging_dir, f"{date}_{slug}-{n}.md")
            n += 1
        from mymory.core.note import Note
        note = Note(path=final_path, frontmatter=fm,
                    body=("\n" + doc.body.strip() + "\n"))
    else:
        note = new_note(
            vault_root=vault.root,
            wing=wing,
            title=doc.title,
            slug=slug,
            date=date,
            body=("\n" + doc.body.strip() + "\n"),
            extra_frontmatter=extra,
            room=None,
        )
        final_path = note.path
        n = 2
        while os.path.exists(final_path):
            base, ext = os.path.splitext(note.path)
            final_path = f"{base}-{n}{ext}"
            n += 1
        note.path = final_path

    write_note(note)
    return note.path


# ----------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------


def _read_path_list(list_path: str) -> list[str]:
    """Read absolute paths from a plain-text list file (one per line).

    Lines starting with # are treated as comments. Blank lines are skipped.
    """
    out: list[str] = []
    with open(list_path, "r", encoding="utf-8", errors="replace") as f:
        for raw in f:
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            out.append(line)
    return out


def ingest_directory(
    vault: Vault,
    source_dir: str | None,
    wing: str,
    staging: bool = True,
    force: bool = False,
    dry_run: bool = False,
    extensions: list[str] | None = None,
    tags: list[str] | None = None,
    from_list: str | None = None,
    ledger_db: str | None = None,
) -> IngestReport:
    """Walk source_dir OR process an explicit path list and ingest into the vault.

    Exactly one of `source_dir` or `from_list` should be supplied.

    Args:
        vault: loaded Vault
        source_dir: directory to recurse (if from_list is None)
        wing: destination wing
        staging: True writes to `<vault>/_staging/<wing>/`; False writes direct
        force:   ignore ledger dedup and re-convert
        dry_run: walk + dispatch but do not write files or record ledger
        extensions: optional ["pdf","docx",...] to restrict which exts are
                    considered (applies to both walk and list modes)
        tags: extra tags added to every ingested note
        from_list: path to a plain-text file listing absolute paths (one per
                   line, # comments supported). When set, `source_dir` is
                   ignored.
        ledger_db: override path to the SHA256 dedup ledger (default:
                   `<vault>/.embed_cache/ingest_ledger.db`).
    """
    started = datetime.now().isoformat(timespec="seconds")
    root_label = from_list or source_dir or "(unspecified)"
    report = IngestReport(root=root_label, wing=wing, staging=staging, started_at=started)

    ext_filter: set[str] | None = None
    if extensions:
        ext_filter = {("." + e.lstrip(".")).lower() for e in extensions}

    ledger_path = ledger_db or default_ledger_path(vault.root)
    ledger = IngestLedger(ledger_path)

    # Build the iterator of input files.
    if from_list:
        def _source_iter():
            for p in _read_path_list(from_list):
                if not os.path.isfile(p):
                    # Record as error and skip.
                    err_item = IngestItem(
                        source_path=p,
                        status="error",
                        message="file not found",
                    )
                    report.items.append(err_item)
                    continue
                if ext_filter is not None:
                    ext = os.path.splitext(p)[1].lower()
                    if ext not in ext_filter:
                        continue
                yield p
    else:
        if not source_dir or not os.path.isdir(source_dir):
            raise ValueError(f"source_dir not a directory: {source_dir!r}")

        def _source_iter():
            yield from _iter_files(source_dir, extensions=ext_filter)

    try:
        for path in _source_iter():
            item = IngestItem(source_path=path, status="unhandled")
            try:
                sha = _sha256(path)
                item.sha256 = sha
                if not force and ledger.is_converted(sha):
                    item.status = "skipped_dedup"
                    report.items.append(item)
                    continue

                parser = _select_parser(path)
                if parser:
                    item.parser = parser.name
                    item.source_format = parser.name
                    if dry_run:
                        item.status = "parsed"
                        item.message = "dry-run"
                    else:
                        written: list[str] = []
                        for doc in parser.parse(path):
                            if tags:
                                doc.tags = list(doc.tags) + list(tags)
                            out = _write_parsed_document(doc, vault, wing, staging)
                            written.append(out)
                        if written:
                            item.status = "parsed"
                            item.dest_paths = written
                            ledger.record(
                                sha256=sha,
                                source_path=path,
                                dest_path=written[0],
                                wing=wing,
                                source_format=parser.name,
                                word_count=sum(_word_count(p) for p in written),
                            )
                        else:
                            item.status = "unhandled"
                            item.message = "parser yielded no documents"
                    report.items.append(item)
                    continue

                if _ext_supported_by_converter(path):
                    item.source_format = os.path.splitext(path)[1].lstrip(".").lower()
                    if dry_run:
                        item.status = "converted"
                        item.message = "dry-run"
                    else:
                        # Staging: write under `_staging/<wing>/...`.
                        # Direct: write into `<wing>/...`.
                        if staging:
                            staging_dir = os.path.join(vault.root, "_staging", wing)
                            os.makedirs(staging_dir, exist_ok=True)
                            stem = os.path.splitext(os.path.basename(path))[0]
                            out_path = os.path.join(staging_dir, f"{stem}.md")
                            # Uniquify to avoid collision.
                            n = 2
                            while os.path.exists(out_path):
                                out_path = os.path.join(staging_dir, f"{stem}-{n}.md")
                                n += 1
                            result = convert_file(
                                filepath=path,
                                vault_root=vault.root,
                                wing=wing,
                                ledger=ledger,
                                tags=(tags or []) + ["ingested", "staging"],
                                out_path=out_path,
                                confidence="VERBATIM",
                            )
                        else:
                            result = convert_file(
                                filepath=path,
                                vault_root=vault.root,
                                wing=wing,
                                ledger=ledger,
                                tags=(tags or []) + ["ingested"],
                                confidence="VERBATIM",
                            )
                        if result.success:
                            item.status = "converted"
                            item.dest_paths = [result.dest_path] if result.dest_path else []
                        elif result.skipped:
                            item.status = "skipped_dedup"
                        else:
                            item.status = "error"
                            item.message = result.error or "convert failed"
                    report.items.append(item)
                    continue

                # Nothing handled it.
                report.items.append(item)

            except Exception as e:  # isolate per-file errors
                item.status = "error"
                item.message = f"{type(e).__name__}: {e}"
                report.items.append(item)

    finally:
        report.finished_at = datetime.now().isoformat(timespec="seconds")
        ledger.close()

    return report


def _word_count(path: str) -> int:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return len(f.read().split())
    except OSError:
        return 0
