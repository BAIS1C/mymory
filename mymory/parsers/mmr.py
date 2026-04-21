"""MyMory portable snapshot (.mmr) parser.

.mmr is MyMory's own portable memory-rack format: a single JSON file that
bundles N vault notes for cross-vault import/export. One vault can emit a
.mmr, another can ingest it, preserving frontmatter, body, wing, and
entities across installs.

Format (v1):

{
  "mymory_mmr_version": "1.0",
  "created_at":  "2026-04-21T08:00:00+08:00",
  "source_vault": "C:/Users/.../Project Mymory",
  "source_agent": "mymory-export",
  "notes": [
    {
      "path":         "strands/2026-04-21_session_note.md",
      "wing":         "strands",
      "title":        "Session note title",
      "frontmatter":  { ... },
      "body":         "full markdown body after the frontmatter block"
    },
    ...
  ],
  "entities": [ { "slug": "...", "name": "...", "aliases": [...] }, ... ]
}

One ParsedDocument per embedded note. Entity bundle is preserved in the
first note's extra_frontmatter for downstream reconstruction.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Iterable

from mymory.parsers.base import ParsedDocument, Parser, register


MMR_VERSION = "1.0"


class MmrParser(Parser):
    name = "mmr"
    ext = (".mmr", ".mmr.json")

    def handles(self, path: str) -> bool:
        pl = path.lower()
        return pl.endswith(".mmr") or pl.endswith(".mmr.json")

    def parse(self, path: str) -> Iterable[ParsedDocument]:
        try:
            data = self.read_json(path)
        except Exception:
            return

        if not isinstance(data, dict):
            return
        if not _looks_like_mmr(data):
            return

        notes = data.get("notes") or []
        if not isinstance(notes, list):
            return

        source_vault = data.get("source_vault") or ""
        source_agent = data.get("source_agent") or "mymory-export"
        entities_bundle = data.get("entities") or []

        for idx, note in enumerate(notes):
            if not isinstance(note, dict):
                continue
            doc = _note_to_doc(
                note,
                source_path=path,
                source_vault=source_vault,
                source_agent=source_agent,
                entities_bundle=entities_bundle if idx == 0 else None,
            )
            if doc:
                yield doc


# ----------------------------------------------------------------------
# Detection + conversion
# ----------------------------------------------------------------------


def _looks_like_mmr(data: dict) -> bool:
    if "mymory_mmr_version" in data:
        return True
    if isinstance(data.get("notes"), list) and any(
        isinstance(n, dict) and ("wing" in n or "frontmatter" in n) for n in data["notes"][:5]
    ):
        return True
    return False


def _note_to_doc(
    note: dict,
    source_path: str,
    source_vault: str,
    source_agent: str,
    entities_bundle: list | None,
) -> ParsedDocument | None:
    fm = note.get("frontmatter") or {}
    if not isinstance(fm, dict):
        fm = {}

    title = note.get("title") or fm.get("title") or _title_from_path(note.get("path", ""))
    wing = note.get("wing") or fm.get("wing") or ""
    created = fm.get("created") or note.get("created") or datetime.now().strftime("%Y-%m-%d")

    body = note.get("body") or ""
    if not isinstance(body, str):
        return None

    tags = _as_list(fm.get("tags")) + ["mmr-import"]
    entities = _as_list(fm.get("entities"))
    referenced = _as_list(fm.get("referenced"))

    extra: dict[str, Any] = {}
    for k, v in fm.items():
        if k in {"title", "wing", "created", "tags", "entities", "referenced",
                 "imported", "source_file", "source_format", "source_agent",
                 "source_model", "confidence"}:
            continue
        extra[k] = v

    if referenced:
        extra["referenced"] = referenced
    if source_vault:
        extra["mmr_source_vault"] = source_vault
    if entities_bundle:
        extra["mmr_entities_bundle"] = entities_bundle

    return ParsedDocument(
        title=str(title),
        body=body if body.endswith("\n") else body + "\n",
        created=str(created),
        source_file=source_path,
        source_format="mmr",
        source_agent=source_agent,
        source_model=fm.get("source_model") or "",
        confidence=fm.get("confidence") or "VERBATIM",
        tags=tags,
        entities=entities,
        extra_frontmatter=extra,
        slug_hint=_slug(str(title)),
    )


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _as_list(v: Any) -> list[str]:
    if isinstance(v, list):
        return [str(x) for x in v]
    if isinstance(v, str) and v.strip():
        return [v]
    return []


def _title_from_path(path: str) -> str:
    stem = os.path.splitext(os.path.basename(path))[0]
    return stem.replace("_", " ").strip() or "MMR note"


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9\s\-]", "", title.lower())
    return re.sub(r"[\s\-]+", "_", s).strip("_")[:60]


# ----------------------------------------------------------------------
# Writer (export side, used by CLI `mymory export-mmr`)
# ----------------------------------------------------------------------


def write_mmr(
    out_path: str,
    notes: list[dict],
    source_vault: str,
    entities: list[dict] | None = None,
) -> str:
    """Write a list of note payloads to a .mmr file.

    Each note dict must contain: path, wing, title, frontmatter, body.
    """
    import json

    payload = {
        "mymory_mmr_version": MMR_VERSION,
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "source_vault": source_vault,
        "source_agent": "mymory-export",
        "notes": notes,
        "entities": entities or [],
    }

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return out_path


register(MmrParser())
