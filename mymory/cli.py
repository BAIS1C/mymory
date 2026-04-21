"""MyMory CLI.

Entry point for the `mymory` command. Thin dispatcher over the core modules.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import click

from mymory import __version__
from mymory.core.manifest import Manifest, load_manifest
from mymory.core.note import Note, new_note, make_slug, write_note
from mymory.core.vault import Vault


# ----------------------------------------------------------------------
# Common helpers
# ----------------------------------------------------------------------


def _get_vault(manifest_path: str | None, vault: str | None) -> Vault:
    try:
        m = load_manifest(path=manifest_path, vault_root=vault)
    except FileNotFoundError as e:
        click.echo(f"ERROR: {e}", err=True)
        sys.exit(2)
    return Vault(manifest=m)


# ----------------------------------------------------------------------
# Main group
# ----------------------------------------------------------------------


@click.group(help="MyMory: governed memory vault substrate.")
@click.version_option(__version__, prog_name="mymory")
@click.option("--manifest", "manifest_path", type=click.Path(), default=None,
              help="Path to kks_manifest.yaml")
@click.option("--vault", type=click.Path(), default=None,
              help="Path to vault root (overrides manifest vault.root)")
@click.pass_context
def main(ctx, manifest_path, vault):
    ctx.ensure_object(dict)
    ctx.obj["manifest_path"] = manifest_path
    ctx.obj["vault"] = vault


# ----------------------------------------------------------------------
# init: scaffold a new vault
# ----------------------------------------------------------------------


@main.command()
@click.argument("path", type=click.Path(), default=".")
@click.option("--copy-default-manifest/--no-copy-default-manifest", default=True)
def init(path, copy_default_manifest):
    """Scaffold a new MyMory vault at PATH."""
    path = Path(path).resolve()
    path.mkdir(parents=True, exist_ok=True)

    skeleton = [
        "_identity", "_graph", "_kks", "_staging",
        "personal", "work", "research", "sessions",
    ]
    for d in skeleton:
        (path / d).mkdir(exist_ok=True)

    home = path / "HOME.md"
    if not home.exists():
        home.write_text(
            "# Vault Home\n\nWelcome to your MyMory vault. See `CONTEXT.md` for the session log.\n",
            encoding="utf-8",
        )

    context = path / "CONTEXT.md"
    if not context.exists():
        context.write_text(
            "# Vault Context\n\nAppend-only session log. See `docs/TAXONOMY.md` for conventions.\n\n---\n",
            encoding="utf-8",
        )

    if copy_default_manifest:
        from importlib.resources import files

        try:
            default = (files("mymory") / ".." / "config" / "default_manifest.yaml").resolve()
        except Exception:
            default = None

        if default and default.is_file():
            target = path / "kks_manifest.yaml"
            if not target.exists():
                target.write_text(default.read_text(encoding="utf-8"), encoding="utf-8")

    click.echo(f"Initialized vault at {path}")


# ----------------------------------------------------------------------
# stats
# ----------------------------------------------------------------------


@main.command()
@click.pass_context
def stats(ctx):
    """Print vault statistics."""
    v = _get_vault(ctx.obj["manifest_path"], ctx.obj["vault"])
    click.echo(f"Vault root: {v.root}")
    total = 0
    for wing in v.wings():
        if not v.wing_exists(wing):
            continue
        n = v.note_count(wing=wing)
        click.echo(f"  {wing}: {n} notes")
        total += n
    click.echo(f"Total wings: {len(v.wings())}, notes: {total}")


# ----------------------------------------------------------------------
# wings
# ----------------------------------------------------------------------


@main.command()
@click.pass_context
def wings(ctx):
    """List configured wings and their current state."""
    v = _get_vault(ctx.obj["manifest_path"], ctx.obj["vault"])
    for w in v.manifest.wings():
        present = "ok" if v.wing_exists(w.name) else "missing"
        rooms = f", rooms: {', '.join(w.rooms)}" if w.rooms else ""
        click.echo(f"  [{present}] {w.name}: {w.label}{rooms}")


# ----------------------------------------------------------------------
# recall: search
# ----------------------------------------------------------------------


@main.command()
@click.argument("query")
@click.option("-k", "top_k", type=int, default=10, help="Top K results")
@click.option("--wing", "wing", type=str, default=None, help="Restrict to a wing")
@click.option("--grep/--no-grep", default=False, help="Grep-only (skip semantic)")
@click.option("--both/--no-both", default=False, help="Union of semantic + grep")
@click.pass_context
def recall(ctx, query, top_k, wing, grep, both):
    """Search the vault by semantic + grep."""
    v = _get_vault(ctx.obj["manifest_path"], ctx.obj["vault"])

    results: list[tuple[str, float, str]] = []

    if not grep:
        try:
            from mymory.layer3.embed import semantic_search

            sem = semantic_search(v, query, k=top_k, wing=wing)
            for p, s in sem:
                results.append((p, s, "semantic"))
        except ImportError:
            click.echo("WARN: sentence-transformers not installed, falling back to grep.", err=True)
            grep = True
            both = False

    if grep or both:
        from mymory.layer3.grep_fallback import grep as grep_fn

        hits = grep_fn(v, query, wing=wing, max_hits=top_k * 3)
        seen: set[str] = {p for p, _, _ in results}
        for h in hits[:top_k]:
            if h.path in seen:
                continue
            results.append((h.path, 0.0, f"grep:L{h.line_no}"))
            seen.add(h.path)

    if not results:
        click.echo("(no matches)")
        return

    for p, score, src in results[:top_k]:
        rel = os.path.relpath(p, v.root)
        score_s = f"{score:.3f}" if score > 0 else "   --"
        click.echo(f"  [{score_s}] {src:12s}  {rel}")


# ----------------------------------------------------------------------
# embed: rebuild embeddings
# ----------------------------------------------------------------------


@main.command()
@click.option("--batch-size", type=int, default=32)
@click.pass_context
def embed(ctx, batch_size):
    """Re-embed drifted notes (run on every hygiene pass)."""
    v = _get_vault(ctx.obj["manifest_path"], ctx.obj["vault"])
    try:
        from mymory.layer3.embed import reembed_drift
    except ImportError:
        click.echo("ERROR: sentence-transformers not installed. `pip install sentence-transformers`",
                   err=True)
        sys.exit(3)
    stats = reembed_drift(v, batch_size=batch_size, verbose=True)
    click.echo(
        f"Embedded: {stats['embedded']}, removed: {stats['removed']}, total: {stats['total']}"
    )


# ----------------------------------------------------------------------
# remember: create a new note
# ----------------------------------------------------------------------


@main.command()
@click.option("--title", required=True, help="Note title")
@click.option("--wing", required=True, help="Target wing")
@click.option("--body", default="", help="Note body (or '-' to read stdin)")
@click.option("--slug", default=None, help="Filename slug (auto from title if omitted)")
@click.option("--date", default=None, help="YYYY-MM-DD (defaults to today)")
@click.option("--tag", "tags", multiple=True, help="Tag (repeatable)")
@click.option("--entity", "entities", multiple=True, help="Entity (repeatable)")
@click.option("--reference", "referenced", multiple=True,
              help="Referenced vault path (repeatable, triggers backlink)")
@click.option("--room", default=None, help="Room subfolder")
@click.option("--confidence", default="DERIVED",
              type=click.Choice(["VERBATIM", "DERIVED", "SPECULATIVE", "CANONICAL"]))
@click.pass_context
def remember(ctx, title, wing, body, slug, date, tags, entities, referenced, room, confidence):
    """Create a new note and run the backlink pass."""
    v = _get_vault(ctx.obj["manifest_path"], ctx.obj["vault"])

    if body == "-":
        body = sys.stdin.read()

    slug = slug or make_slug(title)
    fm_extra = {
        "source_agent": "mymory-cli",
        "confidence": confidence,
    }
    if tags:
        fm_extra["tags"] = list(tags)
    if entities:
        fm_extra["entities"] = list(entities)
    if referenced:
        fm_extra["referenced"] = list(referenced)

    note = new_note(
        vault_root=v.root,
        wing=wing,
        title=title,
        slug=slug,
        date=date,
        body=("\n" + body.strip() + "\n") if body else "\n",
        extra_frontmatter=fm_extra,
        room=room,
    )

    if os.path.exists(note.path):
        click.echo(f"EXISTS: {note.path} (no overwrite)", err=True)
        sys.exit(4)

    write_note(note)
    click.echo(f"Wrote: {note.path}")

    if referenced or entities:
        from mymory.core.manifest import Manifest as _M
        from mymory.layer2.backlinks import backlink_pass

        backlink_pass(
            session_note_path=note.path,
            session_title=title,
            session_date_str=note.created,
            entities=list(entities),
            referenced=list(referenced),
            vault_root=v.root,
            entity_slug_fn=_M._default_slug,
            graph_dir=v.manifest.graph_dir(),
            verbose=True,
        )


# ----------------------------------------------------------------------
# convert: single-file document -> markdown
# ----------------------------------------------------------------------


@main.command()
@click.argument("path", type=click.Path(exists=True))
@click.option("--wing", required=True, help="Destination wing")
@click.option("--tag", "tags", multiple=True, help="Extra tag (repeatable)")
@click.option("--confidence", default="VERBATIM",
              type=click.Choice(["VERBATIM", "DERIVED", "SPECULATIVE", "CANONICAL"]))
@click.option("-o", "--out", type=click.Path(), default=None,
              help="Override output path (otherwise vault-managed)")
@click.pass_context
def convert(ctx, path, wing, tags, confidence, out):
    """Convert a single source file (PDF / DOCX / PPTX / XLSX / HTML / CSV / TXT / MD) to a vault note."""
    v = _get_vault(ctx.obj["manifest_path"], ctx.obj["vault"])

    from mymory.core.converter import convert_file, CONVERTERS
    from mymory.core.ledger import IngestLedger, default_ledger_path

    ext = os.path.splitext(path)[1].lower()
    if ext not in CONVERTERS:
        click.echo(f"ERROR: no converter for extension `{ext}`. "
                   f"Supported: {', '.join(sorted(CONVERTERS))}", err=True)
        sys.exit(5)

    ledger = IngestLedger(default_ledger_path(v.root))
    try:
        result = convert_file(
            filepath=path,
            vault_root=v.root,
            wing=wing,
            ledger=ledger,
            tags=list(tags),
            out_path=out,
            confidence=confidence,
        )
    finally:
        ledger.close()

    if result.success:
        click.echo(f"Converted: {path}")
        click.echo(f"  -> {result.dest_path}")
        if result.word_count:
            click.echo(f"  words: {result.word_count}")
    elif result.skipped:
        click.echo(f"Skipped (dedup): {path}")
        if result.sha256:
            click.echo(f"  sha256: {result.sha256}")
    else:
        click.echo(f"ERROR: {result.error or 'unknown failure'}", err=True)
        sys.exit(6)


# ----------------------------------------------------------------------
# ingest: walk a directory and bulk-convert/parse
# ----------------------------------------------------------------------


@main.command()
@click.argument("path", type=click.Path(exists=True, file_okay=False), required=False)
@click.option("--from-list", "from_list", type=click.Path(exists=True, dir_okay=False),
              default=None, help="File listing absolute paths to ingest (one per line)")
@click.option("--wing", required=True, help="Destination wing")
@click.option("--staging/--direct", default=True,
              help="staging writes under _staging/<wing>/ for review; direct writes to <wing>/")
@click.option("--dry-run", is_flag=True, help="Walk + dispatch without writing")
@click.option("--force", is_flag=True, help="Ignore SHA256 dedup ledger")
@click.option("--ext", "extensions", multiple=True,
              help="Restrict to extensions, e.g. --ext pdf --ext docx")
@click.option("--tag", "tags", multiple=True, help="Extra tag (repeatable)")
@click.option("--ledger-db", "ledger_db", type=click.Path(), default=None,
              help="Override SHA256 dedup ledger path")
@click.option("--report", "report_path", type=click.Path(), default=None,
              help="Write a markdown ingest report to this path")
@click.pass_context
def ingest(ctx, path, from_list, wing, staging, dry_run, force, extensions, tags,
           ledger_db, report_path):
    """Bulk-ingest. Either a directory (positional arg) or an explicit path list via --from-list."""
    v = _get_vault(ctx.obj["manifest_path"], ctx.obj["vault"])

    if not path and not from_list:
        click.echo("ERROR: provide a directory PATH or --from-list", err=True)
        sys.exit(2)
    if path and from_list:
        click.echo("ERROR: supply either PATH or --from-list, not both", err=True)
        sys.exit(2)

    from mymory.core.ingest import ingest_directory

    src_label = path or from_list
    click.echo(f"Ingesting: {src_label}")
    click.echo(f"  wing={wing}  mode={'staging' if staging else 'direct'}  "
               f"dry_run={dry_run}  force={force}  ledger={ledger_db or '(default)'}")

    report = ingest_directory(
        vault=v,
        source_dir=path,
        wing=wing,
        staging=staging,
        force=force,
        dry_run=dry_run,
        extensions=list(extensions) if extensions else None,
        tags=list(tags),
        from_list=from_list,
        ledger_db=ledger_db,
    )

    counts = report.counts
    for k in sorted(counts):
        click.echo(f"  {k}: {counts[k]}")

    if report_path:
        os.makedirs(os.path.dirname(os.path.abspath(report_path)) or ".", exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as f:
            f.write(report.render_summary())
        click.echo(f"Report: {report_path}")


# ----------------------------------------------------------------------
# export-mmr: bundle vault notes into a .mmr file
# ----------------------------------------------------------------------


@main.command("export-mmr")
@click.argument("out", type=click.Path())
@click.option("--wing", "wing", default=None, help="Restrict to a wing")
@click.option("--limit", type=int, default=0, help="Cap on notes exported (0 = all)")
@click.pass_context
def export_mmr(ctx, out, wing, limit):
    """Export vault notes to a portable .mmr bundle."""
    v = _get_vault(ctx.obj["manifest_path"], ctx.obj["vault"])

    from mymory.parsers.mmr import write_mmr

    notes: list[dict] = []
    for note in v.iter_notes(wing=wing):
        rel = os.path.relpath(note.path, v.root).replace("\\", "/")
        notes.append({
            "path": rel,
            "wing": note.wing or wing or "",
            "title": note.title,
            "frontmatter": note.frontmatter,
            "body": note.body,
        })
        if limit and len(notes) >= limit:
            break

    entities = []
    for e in v.manifest.entities():
        entities.append({"slug": e.slug, "name": e.name, "aliases": e.aliases})

    dest = write_mmr(out, notes=notes, source_vault=v.root, entities=entities)
    click.echo(f"Wrote {len(notes)} notes to {dest}")


# ----------------------------------------------------------------------
# graphify / hygiene / brief (Phase C)
# ----------------------------------------------------------------------


@main.command()
@click.argument("repo", type=click.Path(exists=True))
@click.option("--wing", required=True)
def graphify(repo, wing):
    """Run graphify on a repo, file the graph report. (Phase C)"""
    click.echo(f"graphify stub: would run graphify on {repo} -> wing={wing}")
    click.echo("Graphify integration arrives in Phase C.")


@main.command()
@click.pass_context
def hygiene(ctx):
    """Run daily hygiene pipeline. Phase B: embed. Phase C: full pipeline."""
    v = _get_vault(ctx.obj["manifest_path"], ctx.obj["vault"])
    click.echo("Running embed step...")
    try:
        from mymory.layer3.embed import reembed_drift
    except ImportError:
        click.echo("WARN: sentence-transformers missing; hygiene cannot run embed step.")
        return
    s = reembed_drift(v, verbose=True)
    click.echo(f"Embed: {s}")
    click.echo("Corridors / supersession / dedup / brief arrive in Phase C.")


@main.command()
@click.pass_context
def brief(ctx):
    """Print today's morning brief. (Phase C)"""
    v = _get_vault(ctx.obj["manifest_path"], ctx.obj["vault"])
    kks_dir = os.path.join(v.root, v.manifest.kks_dir())
    if not os.path.isdir(kks_dir):
        click.echo("(no _kks directory)")
        return
    briefs = sorted(
        [f for f in os.listdir(kks_dir) if "brief" in f and f.endswith(".md")],
        reverse=True,
    )
    if not briefs:
        click.echo("(no briefs found)")
        return
    click.echo(f"Latest: {briefs[0]}")


if __name__ == "__main__":
    main()
