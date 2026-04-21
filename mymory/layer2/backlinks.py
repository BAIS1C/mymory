"""Bidirectional backlink enrichment.

When a session note is written, this module amends:
  - each explicit source note listed in `referenced` frontmatter
  - each existing _graph/_entity_<slug>.md corridor for detected entities

Rules:
  - Never creates new files. Entity corridors must pre-exist.
  - Append-only. Idempotent: re-running does not duplicate.
  - Creates the '## Referenced By' section if missing on an existing note.

Ported from Sean Uddin's MKV scripts/backlinks.py, generalized for any vault.
"""

from __future__ import annotations

import os
import re


def append_referenced_by(
    target_path: str,
    session_note_path: str,
    session_title: str,
    session_date_str: str,
    vault_root: str,
    verbose: bool = True,
) -> bool:
    """Append a backlink to target_path under '## Referenced By'. Return True if modified."""
    if not os.path.exists(target_path):
        if verbose:
            print(f"  WARN referenced note not found: {target_path}")
        return False

    note_stem = os.path.splitext(os.path.basename(session_note_path))[0]
    link_text = f"- [[{note_stem}|{session_title}]] ({session_date_str})"

    with open(target_path, "r", encoding="utf-8") as f:
        content = f.read()

    if f"[[{note_stem}" in content:
        if verbose:
            print(f"  SKIP already linked: {os.path.relpath(target_path, vault_root)}")
        return False

    if "## Referenced By" in content:
        new_content = re.sub(
            r"(## Referenced By[^\n]*\n+)",
            lambda m: m.group(1) + link_text + "\n",
            content,
            count=1,
        )
    else:
        new_content = content.rstrip() + "\n\n## Referenced By\n\n" + link_text + "\n"

    with open(target_path, "w", encoding="utf-8") as f:
        f.write(new_content)

    if verbose:
        print(f"  BACKLINK -> {os.path.relpath(target_path, vault_root)}")
    return True


def backlink_pass(
    session_note_path: str,
    session_title: str,
    session_date_str: str,
    entities: list[str],
    referenced: list[str] | None,
    vault_root: str,
    entity_slug_fn,
    graph_dir: str = "_graph",
    verbose: bool = True,
) -> dict:
    """Run the explicit-reference + entity-corridor backlink pass.

    Returns a dict: {updated: int, missing_corridors: list[str]}.
    """
    updated = 0
    missing_corridors: list[str] = []

    if verbose:
        print("\n  Backlink pass:")

    for ref in referenced or []:
        path = ref if os.path.isabs(ref) else os.path.join(vault_root, ref)
        if append_referenced_by(
            path, session_note_path, session_title, session_date_str, vault_root, verbose
        ):
            updated += 1

    for ent in entities:
        slug = entity_slug_fn(ent)
        corridor = os.path.join(vault_root, graph_dir, f"_entity_{slug}.md")
        if os.path.exists(corridor):
            if append_referenced_by(
                corridor, session_note_path, session_title, session_date_str, vault_root, verbose
            ):
                updated += 1
        else:
            missing_corridors.append(slug)

    if verbose:
        print(f"  Backlinks added: {updated}")
        if missing_corridors:
            print(f"  Corridor gaps (no auto-create): {', '.join(missing_corridors)}")

    return {"updated": updated, "missing_corridors": missing_corridors}
