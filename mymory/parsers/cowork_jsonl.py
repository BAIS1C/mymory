"""Cowork session JSONL parser.

Reads a Claude Cowork/Claude Code session transcript (one JSON object per
line, each representing a turn or event). Emits one ParsedDocument per
session, synthesizing a clean markdown transcript.

The Cowork/Claude Code JSONL schema varies but typically includes:
  - type: "user" | "assistant" | "tool_use" | "tool_result" | "system"
  - message.role: "user" | "assistant"
  - message.content: string or list of content blocks
  - timestamp / ts / created_at
  - uuid / session_id

This parser is defensive: it ignores unknown fields and keeps going on
malformed lines.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Iterable

from mymory.parsers.base import ParsedDocument, Parser, register


class CoworkJsonlParser(Parser):
    name = "cowork_jsonl"
    ext = (".jsonl",)

    def handles(self, path: str) -> bool:
        if not super().handles(path):
            return False
        # Heuristic: Cowork transcripts typically live under a path with
        # "claude" or "cowork" or "local-agent-mode-sessions" in it.
        p = path.lower().replace("\\", "/")
        hints = ("claude", "cowork", "local-agent-mode", "projects")
        return any(h in p for h in hints)

    def parse(self, path: str) -> Iterable[ParsedDocument]:
        turns: list[dict] = []
        session_id = ""
        first_ts: str | None = None
        last_ts: str | None = None

        for rec in self.read_jsonl(path):
            if not isinstance(rec, dict):
                continue
            turns.append(rec)
            if not session_id:
                session_id = rec.get("sessionId") or rec.get("session_id") or rec.get("uuid") or ""
            ts = rec.get("timestamp") or rec.get("ts") or rec.get("created_at")
            if ts:
                if first_ts is None:
                    first_ts = str(ts)
                last_ts = str(ts)

        if not turns:
            return

        created_date = _normalize_date(first_ts) or self.file_mtime_date(path)
        title = _derive_title(turns, path)

        body_lines: list[str] = [f"> Session from {os.path.basename(path)}", ""]
        if session_id:
            body_lines.append(f"**Session ID:** `{session_id}`")
        if first_ts and last_ts:
            body_lines.append(f"**Span:** {first_ts} -> {last_ts}")
        body_lines.append("")
        body_lines.append("## Transcript")
        body_lines.append("")

        for rec in turns:
            rendered = _render_turn(rec)
            if rendered:
                body_lines.append(rendered)
                body_lines.append("")

        doc = ParsedDocument(
            title=title,
            body="\n".join(body_lines),
            created=created_date,
            source_file=path,
            source_format="cowork_jsonl",
            source_agent="claude-cowork",
            source_model=_detect_model(turns),
            confidence="VERBATIM",
            tags=["session-log", "transcript"],
            slug_hint=_slug_from_title(title),
            extra_frontmatter={
                "session_id": session_id,
                "turn_count": len(turns),
            },
        )
        yield doc


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _normalize_date(ts: str | None) -> str | None:
    if not ts:
        return None
    # Try ISO 8601, epoch, and common variants.
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _derive_title(turns: list[dict], path: str) -> str:
    # Prefer the first user message as title hint.
    for rec in turns:
        content = _extract_text(rec)
        if content and _role(rec) == "user":
            first_line = content.strip().split("\n", 1)[0]
            first_line = re.sub(r"\s+", " ", first_line)[:80]
            if first_line:
                return f"Session: {first_line}"
    stem = os.path.splitext(os.path.basename(path))[0]
    return f"Session {stem[:40]}"


def _role(rec: dict) -> str:
    t = rec.get("type") or ""
    if t in ("user", "assistant", "tool_use", "tool_result", "system"):
        return t
    msg = rec.get("message") or {}
    if isinstance(msg, dict):
        return msg.get("role", "")
    return ""


def _extract_text(rec: dict) -> str:
    """Pull text content from a JSONL record across the common schemas."""
    # Direct content field.
    if isinstance(rec.get("content"), str):
        return rec["content"]

    # Message wrapper (Claude Code format).
    msg = rec.get("message")
    if isinstance(msg, dict):
        content = msg.get("content")
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    name = block.get("name", "")
                    parts.append(f"_[tool_use: {name}]_")
                elif block.get("type") == "tool_result":
                    parts.append("_[tool_result]_")
            return "\n\n".join(p for p in parts if p)

    return ""


def _render_turn(rec: dict) -> str:
    role = _role(rec)
    text = _extract_text(rec).strip()
    if not text:
        return ""
    prefix = {
        "user": "### User",
        "assistant": "### Assistant",
        "system": "### System",
        "tool_use": "### Tool Use",
        "tool_result": "### Tool Result",
    }.get(role, f"### {role or 'Turn'}")
    return f"{prefix}\n\n{text}"


def _detect_model(turns: list[dict]) -> str:
    for rec in turns:
        msg = rec.get("message") or {}
        if isinstance(msg, dict) and msg.get("model"):
            return str(msg["model"])
    return ""


def _slug_from_title(title: str) -> str:
    s = re.sub(r"[^a-z0-9\s\-]", "", title.lower())
    return re.sub(r"[\s\-]+", "_", s).strip("_")[:60]


register(CoworkJsonlParser())
