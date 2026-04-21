"""Manifest loader. Reads kks_manifest.yaml and exposes typed accessors."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any

import yaml


DEFAULT_MANIFEST_NAME = "kks_manifest.yaml"


@dataclass
class WingConfig:
    name: str
    label: str = ""
    description: str = ""
    rooms: list[str] = field(default_factory=list)
    stub_only: bool = False


@dataclass
class EntityConfig:
    name: str
    slug: str
    aliases: list[str] = field(default_factory=list)


@dataclass
class Manifest:
    raw: dict[str, Any]
    vault_root: str

    def wings(self) -> list[WingConfig]:
        out = []
        for name, cfg in (self.raw.get("wings") or {}).items():
            cfg = cfg or {}
            out.append(WingConfig(
                name=name,
                label=cfg.get("label", name.title()),
                description=cfg.get("description", ""),
                rooms=cfg.get("rooms") or [],
                stub_only=bool(cfg.get("stub_only", False)),
            ))
        return out

    def wing_names(self) -> list[str]:
        return [w.name for w in self.wings()]

    def entities(self) -> list[EntityConfig]:
        out = []
        for e in self.raw.get("entities") or []:
            out.append(EntityConfig(
                name=e["name"],
                slug=e.get("slug") or self._default_slug(e["name"]),
                aliases=e.get("aliases") or [],
            ))
        return out

    def entity_aliases(self) -> dict[str, str]:
        return {k: v for k, v in (self.raw.get("entity_aliases") or {}).items()}

    def parsers_enabled(self) -> list[str]:
        return list((self.raw.get("parsers") or {}).get("enabled") or [])

    def embedding(self) -> dict[str, Any]:
        return self.raw.get("embedding") or {
            "model": "sentence-transformers/all-MiniLM-L6-v2",
            "dim": 384,
            "store": "pickle",
            "threshold": 0.35,
            "top_k": 10,
        }

    def hygiene(self) -> dict[str, Any]:
        return self.raw.get("hygiene") or {}

    def graph_dir(self) -> str:
        return self.raw.get("vault", {}).get("graph_dir", "_graph")

    def kks_dir(self) -> str:
        return self.raw.get("vault", {}).get("kks_dir", "_kks")

    def identity_dir(self) -> str:
        return self.raw.get("vault", {}).get("identity_dir", "_identity")

    def staging_dir(self) -> str:
        return (self.raw.get("ingest") or {}).get("staging_dir", "_staging")

    def ignore_patterns(self) -> list[str]:
        return list(self.raw.get("ignore_patterns") or [])

    def confidence_default(self, source_agent: str) -> str:
        return (self.raw.get("confidence_defaults") or {}).get(source_agent, "DERIVED")

    @staticmethod
    def _default_slug(name: str) -> str:
        return (
            name.lower()
            .replace(" ", "_")
            .replace("-", "_")
            .replace(".", "")
        )


def find_manifest(start: str) -> str | None:
    """Walk up from `start` looking for kks_manifest.yaml. Return path or None."""
    cur = os.path.abspath(start)
    while True:
        candidate = os.path.join(cur, DEFAULT_MANIFEST_NAME)
        if os.path.isfile(candidate):
            return candidate
        parent = os.path.dirname(cur)
        if parent == cur:
            return None
        cur = parent


def load_manifest(path: str | None = None, vault_root: str | None = None) -> Manifest:
    """Load a manifest. `path` takes precedence; else search from `vault_root`
    or cwd. Falls back to a default manifest shipped with the package."""
    if path is None:
        search_start = vault_root or os.getcwd()
        path = find_manifest(search_start)

    if path is None:
        # Use the packaged default as the last resort.
        default = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "..", "config", "default_manifest.yaml",
        )
        default = os.path.normpath(default)
        if os.path.isfile(default):
            path = default

    if path is None:
        raise FileNotFoundError(
            f"No {DEFAULT_MANIFEST_NAME} found. Pass --manifest or run from a vault."
        )

    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    resolved_vault = vault_root or raw.get("vault", {}).get("root") or os.path.dirname(path)
    resolved_vault = os.path.abspath(
        resolved_vault if os.path.isabs(resolved_vault) else os.path.join(os.path.dirname(path), resolved_vault)
    )

    return Manifest(raw=raw, vault_root=resolved_vault)
