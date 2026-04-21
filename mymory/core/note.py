"""Note: in-memory representation of a vault markdown note.

Handles YAML frontmatter parsing and serialization. Keeps the body untouched so
round-tripping does not mangle content.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import yaml


FRONTMATTER_RE = re.compile(
    r"^---\s*\n(.*?)\n---\s*\n?(.*)$",
    re.DOTALL,
)


@dataclass
class Note:
    path: str
    frontmatter: dict[str, Any] = field(default_factory=dict)
    body: str = ""

    # Convenience accessors for common fields.
    @property
    def title(self) -> str:
        return str(self.frontmatter.get("title", ""))

    @property
    def wing(self) -> str:
        return str(self.frontmatter.get("wing", ""))

    @property
    def project(self) -> str:
        return str(self.frontmatter.get("project", ""))

    @property
    def created(self) -> str:
        return str(self.frontmatter.get("created", ""))

    @property
    def tags(self) -> list[str]:
        t = self.frontmatter.get("tags") or []
        return list(t) if isinstance(t, list) else []

    @property
    def entities(self) -> list[str]:
        e = self.frontmatter.get("entities") or []
        return list(e) if isinstance(e, list) else []

    @property
    def referenced(self) -> list[str]:
        r = self.frontmatter.get("referenced") or []
        return list(r) if isinstance(r, list) else []

    @property
    def confidence(self) -> str:
        return str(self.frontmatter.get("confidence", "DERIVED"))

    @property
    def source_agent(self) -> str:
        return str(self.frontmatter.get("source_agent", "unknown"))

    @property
    def stem(self) -> str:
        return os.path.splitext(os.path.basename(self.path))[0]


def parse_note(path: str, content: str | None = None) -> Note:
    """Parse a markdown file into a Note. Missing frontmatter yields empty dict."""
    if content is None:
        with open(path, "r", encoding="utf-8") as f:
            content = f.read()

    m = FRONTMATTER_RE.match(content)
    if m:
        try:
            fm = yaml.safe_load(m.group(1)) or {}
        except yaml.YAMLError:
            fm = {}
        body = m.group(2)
    else:
        fm = {}
        body = content

    if not isinstance(fm, dict):
        fm = {}

    return Note(path=path, frontmatter=fm, body=body)


def serialize_note(note: Note) -> str:
    """Serialize a Note back to a markdown string with frontmatter."""
    if note.frontmatter:
        fm_str = yaml.safe_dump(
            note.frontmatter,
            default_flow_style=False,
            allow_unicode=True,
            sort_keys=False,
        ).rstrip()
        return f"---\n{fm_str}\n---\n{note.body}"
    return note.body


def write_note(note: Note) -> None:
    """Write note back to disk. Creates parent dirs if needed."""
    os.makedirs(os.path.dirname(note.path), exist_ok=True)
    with open(note.path, "w", encoding="utf-8") as f:
        f.write(serialize_note(note))


def new_note(
    vault_root: str,
    wing: str,
    title: str,
    slug: str,
    date: str | None = None,
    body: str = "",
    extra_frontmatter: dict[str, Any] | None = None,
    room: str | None = None,
) -> Note:
    """Build a new Note object at the canonical path."""
    date = date or datetime.now().strftime("%Y-%m-%d")
    filename = f"{date}_{slug}.md"

    parts = [vault_root, wing]
    if room:
        parts.append(f"room_{room}" if not room.startswith("room_") else room)
    parts.append(filename)
    path = os.path.join(*parts)

    fm: dict[str, Any] = {
        "title": title,
        "wing": wing,
        "created": date,
    }
    if extra_frontmatter:
        fm.update(extra_frontmatter)

    return Note(path=path, frontmatter=fm, body=body)


def make_slug(text: str, max_len: int = 60) -> str:
    s = re.sub(r"[^a-z0-9\s\-]", "", text.lower())
    return re.sub(r"[\s\-]+", "_", s).strip("_")[:max_len]
