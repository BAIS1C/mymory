"""ChatGPT conversations.json export parser.

Reads a ChatGPT data export (conversations.json). The file is a JSON array
of conversation objects. Each conversation has:
  - title
  - create_time / update_time (epoch seconds)
  - mapping: dict[node_id -> node]
      node = {id, parent, children: [...], message: {...} | None}
      message = {
          id, author: {role, name, metadata},
          content: {content_type: "text"|"code"|..., parts: [...]},
          create_time, update_time, ...
      }

We reconstruct the conversation by walking the mapping tree from the root
to the deepest child chain, ordered by create_time when available, falling
back to the children order.

One ParsedDocument per conversation.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Iterable

from mymory.parsers.base import ParsedDocument, Parser, register


class ChatGptExportParser(Parser):
    name = "chatgpt_export"
    ext = (".json",)

    def handles(self, path: str) -> bool:
        if not super().handles(path):
            return False
        # Heuristic: file is named conversations.json or path hints chatgpt.
        base = os.path.basename(path).lower()
        p = path.lower().replace("\\", "/")
        if base == "conversations.json":
            return True
        return "chatgpt" in p or "openai" in p

    def parse(self, path: str) -> Iterable[ParsedDocument]:
        try:
            data = self.read_json(path)
        except Exception:
            return

        if not isinstance(data, list):
            # Some exports wrap in {"conversations": [...]}
            if isinstance(data, dict) and isinstance(data.get("conversations"), list):
                data = data["conversations"]
            else:
                return

        for conv in data:
            if not isinstance(conv, dict):
                continue
            doc = _conversation_to_doc(conv, path)
            if doc:
                yield doc


# ----------------------------------------------------------------------
# Conversation walker
# ----------------------------------------------------------------------


def _conversation_to_doc(conv: dict, source_path: str) -> ParsedDocument | None:
    title = (conv.get("title") or "").strip() or "Untitled ChatGPT conversation"
    conv_id = conv.get("id") or conv.get("conversation_id") or ""
    create_ts = conv.get("create_time")
    update_ts = conv.get("update_time")
    model_slug = conv.get("default_model_slug") or ""

    mapping = conv.get("mapping")
    if not isinstance(mapping, dict):
        return None

    ordered_messages = _walk_mapping(mapping)
    if not ordered_messages:
        return None

    created_date = _epoch_to_date(create_ts) or _epoch_to_date(update_ts) or datetime.now().strftime("%Y-%m-%d")

    body_lines: list[str] = []
    body_lines.append(f"> Conversation from {os.path.basename(source_path)}")
    body_lines.append("")
    if conv_id:
        body_lines.append(f"**Conversation ID:** `{conv_id}`")
    if create_ts:
        body_lines.append(f"**Created:** {_epoch_to_iso(create_ts)}")
    if update_ts:
        body_lines.append(f"**Updated:** {_epoch_to_iso(update_ts)}")
    if model_slug:
        body_lines.append(f"**Model:** {model_slug}")
    body_lines.append("")
    body_lines.append("## Transcript")
    body_lines.append("")

    for msg in ordered_messages:
        rendered = _render_message(msg)
        if rendered:
            body_lines.append(rendered)
            body_lines.append("")

    return ParsedDocument(
        title=f"ChatGPT: {title[:80]}",
        body="\n".join(body_lines),
        created=created_date,
        source_file=source_path,
        source_format="chatgpt_export",
        source_agent="chatgpt-web",
        source_model=_detect_model(ordered_messages) or model_slug,
        confidence="VERBATIM",
        tags=["session-log", "transcript", "chatgpt"],
        slug_hint=_slug(title),
        extra_frontmatter={
            "conversation_id": conv_id,
            "message_count": len(ordered_messages),
        },
    )


def _walk_mapping(mapping: dict) -> list[dict]:
    """Walk the ChatGPT mapping tree and return messages in chronological order.

    Strategy: find the root (node with no parent), then DFS along children
    preferring the child with the earliest create_time. Messages with no
    content (e.g. system/branch nodes) are skipped.
    """
    # Index by id for quick lookup.
    nodes_by_id = {nid: n for nid, n in mapping.items() if isinstance(n, dict)}

    # Find root(s).
    roots = [n for n in nodes_by_id.values() if not n.get("parent")]
    if not roots:
        # Fallback: pick the node whose id does not appear as a parent anywhere.
        child_ids = {n.get("parent") for n in nodes_by_id.values() if n.get("parent")}
        roots = [n for n in nodes_by_id.values() if n.get("id") not in child_ids]
    if not roots:
        return []

    ordered: list[dict] = []
    visited: set[str] = set()

    def dfs(node: dict) -> None:
        nid = node.get("id") or ""
        if nid and nid in visited:
            return
        visited.add(nid)

        msg = node.get("message")
        if isinstance(msg, dict):
            ordered.append(msg)

        child_ids = node.get("children") or []
        children = [nodes_by_id[c] for c in child_ids if c in nodes_by_id]
        # Sort by create_time on message when available.
        children.sort(key=_child_sort_key)
        for child in children:
            dfs(child)

    for root in roots:
        dfs(root)

    return ordered


def _child_sort_key(node: dict) -> float:
    msg = node.get("message") or {}
    ct = msg.get("create_time") if isinstance(msg, dict) else None
    try:
        return float(ct) if ct is not None else float("inf")
    except (TypeError, ValueError):
        return float("inf")


# ----------------------------------------------------------------------
# Message rendering
# ----------------------------------------------------------------------


def _render_message(msg: dict) -> str:
    author = msg.get("author") or {}
    role = author.get("role") if isinstance(author, dict) else None
    role = (role or "").lower()
    if role not in ("user", "assistant", "system", "tool"):
        role = role or "turn"

    text = _extract_message_text(msg).strip()
    if not text:
        return ""

    prefix = {
        "user": "### User",
        "assistant": "### Assistant",
        "system": "### System",
        "tool": "### Tool",
    }.get(role, f"### {role.title()}")

    return f"{prefix}\n\n{text}"


def _extract_message_text(msg: dict) -> str:
    content = msg.get("content")
    if not isinstance(content, dict):
        return ""

    ctype = content.get("content_type") or ""
    parts = content.get("parts")

    if isinstance(parts, list):
        out: list[str] = []
        for p in parts:
            if isinstance(p, str):
                out.append(p)
            elif isinstance(p, dict):
                # Multimodal parts: {content_type, asset_pointer, text, ...}
                if p.get("text"):
                    out.append(str(p["text"]))
                elif p.get("asset_pointer"):
                    out.append(f"_[asset: {p.get('asset_pointer')}]_")
        joined = "\n\n".join(s for s in out if s)
        if ctype == "code":
            lang = content.get("language") or ""
            return f"```{lang}\n{joined}\n```"
        return joined

    # Some content_types use different keys (e.g. code -> text, thoughts -> thoughts).
    if isinstance(content.get("text"), str):
        return content["text"]
    if isinstance(content.get("result"), str):
        return content["result"]

    return ""


def _detect_model(messages: list[dict]) -> str:
    for msg in messages:
        meta = msg.get("metadata") or {}
        if isinstance(meta, dict):
            slug = meta.get("model_slug") or meta.get("default_model_slug")
            if slug:
                return str(slug)
    return ""


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------


def _epoch_to_date(ts: Any) -> str | None:
    try:
        return datetime.fromtimestamp(float(ts)).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return None


def _epoch_to_iso(ts: Any) -> str:
    try:
        return datetime.fromtimestamp(float(ts)).isoformat(timespec="seconds")
    except (TypeError, ValueError):
        return str(ts)


def _slug(title: str) -> str:
    s = re.sub(r"[^a-z0-9\s\-]", "", title.lower())
    return re.sub(r"[\s\-]+", "_", s).strip("_")[:60]


register(ChatGptExportParser())
