"""Parser base class.

A Parser consumes a source file (or directory) and emits one or more
ParsedDocuments. Each ParsedDocument becomes a vault note after filing.

This is separate from converter.py because parsers handle structured
conversational/session formats (JSONL, export dumps) while the converter
handles unstructured document formats.
"""

from __future__ import annotations

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable


@dataclass
class ParsedDocument:
    """One extracted document ready to be written as a vault note."""

    title: str
    body: str
    created: str = ""                      # YYYY-MM-DD
    source_file: str = ""
    source_format: str = ""                # e.g. "cowork_jsonl", "chatgpt"
    source_agent: str = ""                 # e.g. "claude-cowork", "chatgpt-web"
    source_model: str = ""                 # e.g. "claude-opus-4", "gpt-4o"
    confidence: str = "VERBATIM"
    tags: list[str] = field(default_factory=list)
    entities: list[str] = field(default_factory=list)
    extra_frontmatter: dict[str, Any] = field(default_factory=dict)
    slug_hint: str = ""                    # optional override for filename slug

    def to_frontmatter(self, wing: str) -> dict[str, Any]:
        fm: dict[str, Any] = {
            "title": self.title,
            "wing": wing,
            "created": self.created or datetime.now().strftime("%Y-%m-%d"),
            "imported": datetime.now().strftime("%Y-%m-%d"),
            "source_file": self.source_file,
            "source_format": self.source_format,
            "source_agent": self.source_agent or "unknown",
            "confidence": self.confidence,
        }
        if self.source_model:
            fm["source_model"] = self.source_model
        if self.tags:
            fm["tags"] = self.tags
        if self.entities:
            fm["entities"] = self.entities
        fm.update(self.extra_frontmatter)
        return fm


class Parser(ABC):
    """Parser abstract base. Subclasses declare `ext` and implement `parse`."""

    ext: tuple[str, ...] = ()              # file extensions this parser claims
    name: str = ""                         # parser identifier (match manifest.parsers.enabled)

    @abstractmethod
    def parse(self, path: str) -> Iterable[ParsedDocument]:
        """Yield zero or more ParsedDocuments from the source path."""

    def handles(self, path: str) -> bool:
        return path.lower().endswith(tuple(e.lower() for e in self.ext))

    # ------------------------------------------------------------------

    @staticmethod
    def read_text(path: str) -> str:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return f.read()

    @staticmethod
    def read_jsonl(path: str) -> Iterable[dict]:
        import json

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError:
                    continue

    @staticmethod
    def read_json(path: str) -> Any:
        import json

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return json.load(f)

    @staticmethod
    def file_mtime_date(path: str) -> str:
        try:
            ts = os.path.getmtime(path)
            return datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        except OSError:
            return datetime.now().strftime("%Y-%m-%d")


# ----------------------------------------------------------------------
# Registry: populated by __init__.py
# ----------------------------------------------------------------------


_REGISTRY: dict[str, Parser] = {}


def register(parser: Parser) -> None:
    _REGISTRY[parser.name] = parser


def get(name: str) -> Parser | None:
    return _REGISTRY.get(name)


def all_parsers() -> list[Parser]:
    return list(_REGISTRY.values())


def enabled_parsers(manifest_enabled: list[str]) -> list[Parser]:
    return [p for p in _REGISTRY.values() if p.name in manifest_enabled]


def parser_for(path: str, enabled: list[str] | None = None) -> Parser | None:
    """Return the first registered parser that handles the given path."""
    candidates = _REGISTRY.values() if enabled is None else (p for p in _REGISTRY.values() if p.name in enabled)
    for p in candidates:
        if p.handles(path):
            return p
    return None
