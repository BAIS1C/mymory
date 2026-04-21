"""Claude Code session JSONL parser.

Claude Code writes one JSON object per line per event to
~/.claude/projects/<project>/<session-uuid>.jsonl. The shape is very close
to the Cowork JSONL format handled elsewhere, but with a few differences
worth isolating so both formats can coexist and be tuned independently:

  - Top-level fields: type, message, uuid, parentUuid, sessionId, cwd,
    gitBranch, version, userType, timestamp, isSidechain, isMeta, ...
  - type values: "user", "assistant", "summary", "system"
  - message.content: list of content blocks
      {type: "text", text: "..."}
      {type: "tool_use", name, input}
      {type: "tool_result", tool_use_id, content, is_error}
      {type: "thinking", thinking, signature}
  - tool_result.content may be a string or a list of {type: "text"|"image", ...}

One ParsedDocument per JSONL file (session).
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Iterable

from mymory.parsers.base import ParsedDocument, Parser, register


class ClaudeCodeJsonlParser(Parser):
    name = "claude_code_jsonl"
    ext = (".jsonl",)

    def handles(self, path: str) -> bool:
        if not super().handles(path):
            return False
        p = path.lower().replace("\\", "/")
        hints = (".claude/projects", "claude-code", "/claude/projects")
        return any(h in p for h in hints)

    def parse(self, path: str) -> Iterable[ParsedDocument]:
        turns: list[dict] = []
        session_id = ""
        cwd = ""
        branch = ""
        version = ""
        first_ts: str | None = None
        last_ts: str | None = None

        for rec in self.read_jsonl(path):
            if not isinstance(rec, dict):
                continue
            turns.append(rec)
            if not session_id:
                session_id = rec.get("sessionId") or rec.get("uuid") or ""
            if not cwd:
                cwd = rec.get("cwd") or ""
            if not branch:
                branch = rec.get("gitBranch") or ""
            if not version:
                version = rec.get("version") or ""
            ts = rec.get("timestamp")
            if ts:
                if first_ts is None:
                    first_ts = str(ts)
                last_ts = str(ts)

        if not turns:
            return

        created_date = _normalize_date(first_ts) or self.file_mtime_date(path)
        title = _derive_title(turns, path)

        body_lines: list[str] = [
            f"> Claude Code session from {os.path.basename(path)}",
            "",
        ]
        if session_id:
            body_lines.append(f"**Session ID:** `{session_id}`")
        if cwd:
            body_lines.append(f"**CWD:** `{cwd}`")
        if branch:
            body_lines.append(f"**Branch:** `{branch}`")
        if version:
            body_lines.append(f"**Claude Code version:** {version}")
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

        yield ParsedDocument(
            title=title,
            body="\n".join(body_lines),
            created=created_date,
            source_file=path,
            source_format="claude_code_jsonl",
            source_agent="claude-code",
            source_model=_detect_model(turns),
            confidence="VERBATIM",
            tags=["session-log", "transcript", "claude-code"],
            slug_hint=_slug(title),
            extra_frontmatter={
                "session_id": session_id,
                "cwd": cwd,
                "git_branch": branch,
                "claude_code_version": version,
                "turn_count": len(turns),
            },
        )


# ----------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------


def _render_turn(rec: dict) -> str:
    rtype = rec.get("type") or ""
    msg = rec.get("message")

    # Summary turns: single-line recap Claude Code inserts.
    if rtype == "summary":
        summary = rec.get("summary") or ""
        if summary:
            return f"### Summary\n\n{summary}"
        return ""

    # System turns: meta-messages, usually skippable unless explicit text.
    if rtype == "system":
        text = rec.get("content")
        if isinstance(text, str) and text.strip():
            return f"### System\n\n{text.strip()}"
        return ""

    if not isinstance(msg, dict):
        return ""

    role = msg.get("role") or rtype or "turn"
    blocks = msg.get("content")

    # String content (rare for assistant, common for user).
    if isinstance(blocks, str):
        text = blocks.strip()
        if not text:
            return ""
        return f"### {role.title()}\n\n{text}"

    if not isinstance(blocks, list):
        return ""

    parts: list[str] = []
    for block in blocks:
        if not isinstance(block, dict):
            continue
        btype = block.get("type")
        if btype == "text":
            t = block.get("text") or ""
            if t.strip():
                parts.append(t.strip())
        elif btype == "thinking":
            t = block.get("thinking") or ""
            if t.strip():
                parts.append(f"_[thinking]_\n\n{t.strip()}")
        elif btype == "tool_use":
            name = block.get("name") or "tool"
            parts.append(f"_[tool_use: {name}]_")
        elif btype == "tool_result":
            parts.append(_render_tool_result(block))

    if not parts:
        return ""

    return f"### {role.title()}\n\n" + "\n\n".join(parts)


def _render_tool_result(block: dict) -> str:
    is_error = bool(block.get("is_error"))
    tag = "tool_result_error" if is_error else "tool_result"
    content = block.get("content")
    if isinstance(content, str):
        snippet = content.strip()
        if len(snippet) > 800:
            snippet = snippet[:800] + "..."
        return f"_[{tag}]_\n\n{snippet}"
    if isinstance(content, list):
        texts: list[str] = []
        for c in content:
            if isinstance(c, dict) and c.get("type") == "text":
                texts.append(c.get("text") or "")
            elif isinstance(c, dict) and c.get("type") == "image":
                texts.append("_[image]_")
        joined = "\n".join(t for t in texts if t)
        if len(joined) > 800:
            joined = joined[:800] + "..."
        return f"_[{tag}]_\n\n{joined}" if joined else f"_[{tag}]_"
    return f"_[{tag}]_"


# ----------------------------------------------------------------------
# Metadata
# ----------------------------------------------------------------------


def _derive_title(turns: list[dict], path: str) -> str:
    # Prefer a summary event if present.
    for rec in turns:
        if rec.get("type") == "summary" and rec.get("summary"):
            return f"Claude Code: {str(rec['summary'])[:80]}"
    # Fall back to the first user text.
    for rec in turns:
        if rec.get("type") != "user":
            continue
        msg = rec.get("message") or {}
        content = msg.get("content")
        text = ""
        if isinstance(content, str):
            text = content
        elif isinstance(content, list):
            for b in content:
                if isinstance(b, dict) and b.get("type") == "text":
                    text = b.get("text") or ""
                    break
        first_line = (text or "").strip().split("\n", 1)[0]
        first_line = re.sub(r"\s+", " ", first_line)[:80]
        if first_line:
            return f"Claude Code: {first_line}"
    stem = os.path.splitext(os.path.basename(path))[0]
    return f"Claude Code session {stem[:40]}"


def _detect_model(turns: list[dict]) -> str:
    for rec in turns:
        msg = rec.get("message") or {}
        if isinstance(msg, dict) and msg.get("model"):
            return str(msg["model"])
    return ""


def _normalize_date(ts: str | None) -> str | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9\s\-]", "", title.lower())
    return re.sub(r"[\s\-]+", "_", s).strip("_")[:60]


register(ClaudeCodeJsonlParser())
