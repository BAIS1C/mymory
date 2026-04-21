"""Vault: high-level operations over a markdown vault directory tree."""

from __future__ import annotations

import fnmatch
import os
from dataclasses import dataclass
from typing import Iterator

from mymory.core.manifest import Manifest
from mymory.core.note import Note, parse_note


@dataclass
class Vault:
    manifest: Manifest

    @property
    def root(self) -> str:
        return self.manifest.vault_root

    # ------------------------------------------------------------------
    # Iteration
    # ------------------------------------------------------------------

    def iter_notes(
        self,
        wing: str | None = None,
        include_kks: bool = False,
        include_graph: bool = True,
        include_identity: bool = True,
    ) -> Iterator[Note]:
        """Yield every markdown note in the vault (optionally scoped to a wing)."""
        ignore = self.manifest.ignore_patterns()
        kks = self.manifest.kks_dir()
        graph = self.manifest.graph_dir()
        identity = self.manifest.identity_dir()

        if wing:
            start = os.path.join(self.root, wing)
            if not os.path.isdir(start):
                return
            yield from self._walk(start, ignore)
            return

        for entry in sorted(os.listdir(self.root)):
            full = os.path.join(self.root, entry)
            if not os.path.isdir(full):
                continue
            if entry == kks and not include_kks:
                continue
            if entry == graph and not include_graph:
                continue
            if entry == identity and not include_identity:
                continue
            if entry.startswith(".") or entry.startswith("_embed"):
                continue
            yield from self._walk(full, ignore)

    def _walk(self, start: str, ignore: list[str]) -> Iterator[Note]:
        for dirpath, dirnames, filenames in os.walk(start):
            dirnames[:] = [d for d in dirnames if not _matches_any(d, ignore)]
            for fn in filenames:
                if not fn.endswith(".md"):
                    continue
                if _matches_any(fn, ignore):
                    continue
                full = os.path.join(dirpath, fn)
                try:
                    yield parse_note(full)
                except Exception:
                    # Skip unreadable notes; surfaced separately via CLI if needed.
                    continue

    # ------------------------------------------------------------------
    # Lookups
    # ------------------------------------------------------------------

    def wings(self) -> list[str]:
        return self.manifest.wing_names()

    def wing_exists(self, wing: str) -> bool:
        return os.path.isdir(os.path.join(self.root, wing))

    def note_count(self, wing: str | None = None) -> int:
        return sum(1 for _ in self.iter_notes(wing=wing))

    def get_note(self, rel_or_abs_path: str) -> Note | None:
        path = rel_or_abs_path
        if not os.path.isabs(path):
            path = os.path.join(self.root, path)
        if not os.path.isfile(path):
            return None
        return parse_note(path)

    def resolve_wikilink(self, stem: str) -> str | None:
        """Find the absolute path of a note by its filename stem."""
        target = stem + ".md"
        for note in self.iter_notes():
            if os.path.basename(note.path) == target:
                return note.path
        return None

    # ------------------------------------------------------------------
    # Entity corridors
    # ------------------------------------------------------------------

    def corridor_path(self, entity_slug: str) -> str:
        return os.path.join(self.root, self.manifest.graph_dir(), f"_entity_{entity_slug}.md")

    def corridor_exists(self, entity_slug: str) -> bool:
        return os.path.isfile(self.corridor_path(entity_slug))


def _matches_any(name: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatch(name, p.rstrip("/*")) or fnmatch.fnmatch(name, p) for p in patterns)
