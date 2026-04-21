"""Grok export parser.

Grok's export format is not publicly documented and has shifted over time.
This parser is defensive: it tries several shapes and produces one
ParsedDocument per detected conversation. Shapes handled:

  1. {"conversations": [ {title, messages: [...]}, ... ]}
  2. {"chats":         [ {title, turns:    [...]}, ... ]}
  3. [ {title, messages: [...]}, ... ]               (flat list)
  4. {messages: [...]}                                (single conversation)

Message records are inspected for role/author and text content via a
handful of common field names.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Iterable

from mymory.parsers.base import ParsedDocument, Parser, register


class GrokExportParser(Parser):
    name = "grok_export"
    ext = (".json",)

    def handles(self, path: str) -> bool:
        if not super().handles(path):
            return False
        p = path.lower().replace("\\", "/")
        base = os.path.basename(path).lower()
        return "grok" in p or "xai" in p or base.startswith("grok")

    def parse(self, path: str) -> Iterable[ParsedDocument]:
        try:
            data = self.read_json(path)
        except Exception:
            return

        conversations = _extract_conversations(data)
        for idx, conv in enumerate(conversations):
            doc = _conv_to_doc(conv, path, idx)
            if doc:
                yield doc


# ----------------------------------------------------------------------
# Shape detection
# ----------------------------------------------------------------------


def _extract_conversations(data: Any) -> list[dict]:
    if isinstance(data, list):
        return [c for c in data if isinstance(c, dict)]
    if isinstance(data, dict):
        for key in ("conversations", "chats", "threads", "sessions"):
            v = data.get(key)
            if isinstance(v, list):
                return [c for c in v if isinstance(c, dict)]
        # Single-conversation fallback.
        for key in ("messages", "turns", "events"):
            if isinstance(data.get(key), list):
                return [data]
    return []


def _extract_messages(conv: dict) -> list[dict]:
    for key in ("messages", "turns", "events", "items"):
        v = conv.get(key)
        if isinstance(v, list):
            return [m for m in v if isinstance(m, dict)]
    return []


# ----------------------------------------------------------------------
# Doc synthesis
# ----------------------------------------------------------------------


def _conv_to_doc(conv: dict, source_path: str, idx: int) -> ParsedDocument | None:
    messages = _extract_messages(conv)
    if not messages:
        return None

    title = (conv.get("title") or conv.get("name") or f"Grok conversation {idx+1}").strip()
    conv_id = conv.get("id") or conv.get("conversation_id") or ""
    created = conv.get("created_at") or conv.get("create_time") or conv.get("timestamp")
    created_date = _normalize_date(created) or datetime.now().strftime("%Y-%m-%d")

    body_lines: list[str] = [
        f"> Grok conversation from {os.path.basename(source_path)}",
        "",
    ]
    if conv_id:
        body_lines.append(f"**Conversation ID:** `{conv_id}`")
    if created:
        body_lines.append(f"**Created:** {created}")
    body_lines.append("")
    body_lines.append("## Transcript")
    body_lines.append("")

    for msg in messages:
        rendered = _render_message(msg)
        if rendered:
            body_lines.append(rendered)
            body_lines.append("")

    return ParsedDocument(
        title=f"Grok: {title[:80]}",
        body="\n".join(body_lines),
        created=created_date,
        source_file=source_path,
        source_format="grok_export",
        source_agent="grok",
        source_model=_detect_model(messages) or conv.get("model") or "",
        confidence="VERBATIM",
        tags=["session-log", "transcript", "grok"],
        slug_hint=_slug(title),
        extra_frontmatter={
            "conversation_id": conv_id,
            "message_count": len(messages),
        },
    )


def _render_message(msg: dict) -> str:
    role = _role(msg)
    text = _text(msg).strip()
    if not text:
        return ""

    prefix = {
        "user": "### User",
        "assistant": "### Assistant",
        "system": "### System",
        "tool": "### Tool",
    }.get(role, f"### {role.title() if role else 'Turn'}")

    return f"{prefix}\n\n{text}"


def _role(msg: dict) -> str:
    for key in ("role", "author_role", "sender", "from"):
        v = msg.get(key)
        if isinstance(v, str):
            return v.lower()
    author = msg.get("author")
    if isinstance(author, dict):
        r = author.get("role") or author.get("name")
        if isinstance(r, str):
            return r.lower()
    return ""


def _text(msg: dict) -> str:
    # Direct string fields.
    for key in ("content", "text", "body", "message"):
        v = msg.get(key)
        if isinstance(v, str):
            return v
    # Parts list (OpenAI-style).
    content = msg.get("content")
    if isinstance(content, dict):
        parts = content.get("parts")
        if isinstance(parts, list):
            return "\n\n".join(str(p) for p in parts if isinstance(p, (str, int, float)))
        if isinstance(content.get("text"), str):
            return content["text"]
    if isinstance(content, list):
        out: list[str] = []
        for block in content:
            if isinstance(block, str):
                out.append(block)
            elif isinstance(block, dict):
                if block.get("text"):
                    out.append(str(block["text"]))
        return "\n\n".join(out)
    return ""


def _detect_model(messages: list[dict]) -> str:
    for msg in messages:
        for key in ("model", "model_slug"):
            v = msg.get(key)
            if isinstance(v, str):
                return v
    return ""


def _normalize_date(ts: Any) -> str | None:
    if ts is None:
        return None
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d")
        except (OSError, ValueError):
            return None
    s = str(ts)
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        pass
    try:
        return datetime.fromtimestamp(float(s)).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9\s\-]", "", title.lower())
    return re.sub(r"[\s\-]+", "_", s).strip("_")[:60]


register(GrokExportParser())
