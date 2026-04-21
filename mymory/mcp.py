"""MyMory MCP server.

Stdio JSON-RPC server exposing vault_query, vault_context, vault_entities,
vault_wings, vault_file. Consumed by Claude Cowork, Claude Code, and any
MCP-capable client.

Implements the minimum-viable MCP protocol surface: initialize, tools/list,
tools/call. No dependency on the `mcp` Python SDK to keep install light;
downstream integrators can swap in the SDK later by wrapping `handle_request`.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any

from mymory import __version__
from mymory.core.manifest import Manifest, load_manifest
from mymory.core.note import Note, new_note, make_slug, parse_note, write_note
from mymory.core.vault import Vault
from mymory.layer2.backlinks import backlink_pass


# ----------------------------------------------------------------------
# Tool implementations
# ----------------------------------------------------------------------


def tool_vault_query(vault: Vault, args: dict) -> dict:
    query = str(args.get("query", ""))
    k = int(args.get("k", 10))
    wing = args.get("wing")
    mode = args.get("mode", "auto")  # auto | semantic | grep | both

    results: list[dict] = []

    if mode in ("auto", "semantic", "both"):
        try:
            from mymory.layer3.embed import semantic_search

            sem = semantic_search(vault, query, k=k, wing=wing)
            for p, s in sem:
                results.append({
                    "path": os.path.relpath(p, vault.root),
                    "score": s,
                    "source": "semantic",
                })
        except ImportError:
            pass

    if mode in ("grep", "both") or (mode == "auto" and not results):
        from mymory.layer3.grep_fallback import grep as grep_fn

        seen = {r["path"] for r in results}
        for h in grep_fn(vault, query, wing=wing, max_hits=k * 3):
            rel = os.path.relpath(h.path, vault.root)
            if rel in seen:
                continue
            results.append({
                "path": rel,
                "line_no": h.line_no,
                "line": h.line,
                "source": "grep",
            })
            seen.add(rel)

    return {"results": results[:k], "total": len(results)}


def tool_vault_context(vault: Vault, args: dict) -> dict:
    path = args.get("path")
    hops = int(args.get("hops", 1))
    if not path:
        return {"error": "path required"}
    note = vault.get_note(path)
    if not note:
        return {"error": f"note not found: {path}"}

    payload = {
        "path": os.path.relpath(note.path, vault.root),
        "title": note.title,
        "frontmatter": note.frontmatter,
        "body": note.body,
        "neighbors": [],
    }

    if hops > 0:
        # Simple wikilink walk (1 hop). Graph walk arrives in Phase C.
        import re
        link_re = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]+)?\]\]")
        seen: set[str] = set()
        for link in link_re.findall(note.body):
            stem = link.strip().split("/")[-1]
            if stem in seen:
                continue
            seen.add(stem)
            target = vault.resolve_wikilink(stem)
            if target:
                t = vault.get_note(target)
                if t:
                    payload["neighbors"].append({
                        "stem": stem,
                        "path": os.path.relpath(target, vault.root),
                        "title": t.title,
                        "snippet": t.body[:400],
                    })

    return payload


def tool_vault_entities(vault: Vault, args: dict) -> dict:
    name = args.get("name")
    ents = vault.manifest.entities()
    if name:
        for e in ents:
            if e.name.lower() == name.lower() or e.slug == name.lower():
                corridor = vault.corridor_path(e.slug)
                exists = os.path.isfile(corridor)
                return {
                    "name": e.name,
                    "slug": e.slug,
                    "aliases": e.aliases,
                    "corridor_exists": exists,
                    "corridor_path": os.path.relpath(corridor, vault.root) if exists else None,
                }
        return {"error": f"entity not found: {name}"}

    return {
        "entities": [
            {
                "name": e.name,
                "slug": e.slug,
                "corridor_exists": vault.corridor_exists(e.slug),
            }
            for e in ents
        ]
    }


def tool_vault_wings(vault: Vault, args: dict) -> dict:
    out = []
    for w in vault.manifest.wings():
        out.append({
            "name": w.name,
            "label": w.label,
            "exists": vault.wing_exists(w.name),
            "note_count": vault.note_count(w.name) if vault.wing_exists(w.name) else 0,
            "rooms": w.rooms,
        })
    return {"wings": out}


def tool_vault_file(vault: Vault, args: dict) -> dict:
    title = args.get("title")
    wing = args.get("wing")
    if not title or not wing:
        return {"error": "title and wing are required"}

    body = args.get("body", "")
    slug = args.get("slug") or make_slug(title)
    date = args.get("date")
    tags = args.get("tags") or []
    entities = args.get("entities") or []
    referenced = args.get("referenced") or []
    room = args.get("room")
    confidence = args.get("confidence", "DERIVED")
    source_agent = args.get("source_agent", "mcp-client")

    fm_extra: dict[str, Any] = {
        "source_agent": source_agent,
        "confidence": confidence,
    }
    if tags:
        fm_extra["tags"] = list(tags)
    if entities:
        fm_extra["entities"] = list(entities)
    if referenced:
        fm_extra["referenced"] = list(referenced)

    note = new_note(
        vault_root=vault.root,
        wing=wing,
        title=title,
        slug=slug,
        date=date,
        body=("\n" + body.strip() + "\n") if body else "\n",
        extra_frontmatter=fm_extra,
        room=room,
    )

    if os.path.exists(note.path) and not args.get("force"):
        return {"error": f"note exists: {os.path.relpath(note.path, vault.root)}",
                "exists": True}

    write_note(note)

    bl_result = {"updated": 0, "missing_corridors": []}
    if entities or referenced:
        bl_result = backlink_pass(
            session_note_path=note.path,
            session_title=title,
            session_date_str=note.created,
            entities=list(entities),
            referenced=list(referenced),
            vault_root=vault.root,
            entity_slug_fn=Manifest._default_slug,
            graph_dir=vault.manifest.graph_dir(),
            verbose=False,
        )

    return {
        "path": os.path.relpath(note.path, vault.root),
        "backlinks_updated": bl_result["updated"],
        "corridor_gaps": bl_result["missing_corridors"],
    }


TOOLS = {
    "vault_query": {
        "fn": tool_vault_query,
        "description": "Search the vault by semantic + grep. Returns ranked note paths.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "k": {"type": "integer", "default": 10},
                "wing": {"type": "string"},
                "mode": {"type": "string", "enum": ["auto", "semantic", "grep", "both"]},
            },
            "required": ["query"],
        },
    },
    "vault_context": {
        "fn": tool_vault_context,
        "description": "Fetch a note plus N-hop wikilink neighborhood.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "hops": {"type": "integer", "default": 1},
            },
            "required": ["path"],
        },
    },
    "vault_entities": {
        "fn": tool_vault_entities,
        "description": "List canonical entities or look one up.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": {"type": "string"}},
        },
    },
    "vault_wings": {
        "fn": tool_vault_wings,
        "description": "List configured wings with note counts.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    "vault_file": {
        "fn": tool_vault_file,
        "description": "Create a new note with frontmatter and bidirectional backlinks.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "wing": {"type": "string"},
                "body": {"type": "string"},
                "slug": {"type": "string"},
                "date": {"type": "string"},
                "room": {"type": "string"},
                "tags": {"type": "array", "items": {"type": "string"}},
                "entities": {"type": "array", "items": {"type": "string"}},
                "referenced": {"type": "array", "items": {"type": "string"}},
                "confidence": {"type": "string"},
                "source_agent": {"type": "string"},
                "force": {"type": "boolean"},
            },
            "required": ["title", "wing"],
        },
    },
}


# ----------------------------------------------------------------------
# JSON-RPC wire handling
# ----------------------------------------------------------------------


def handle_request(vault: Vault, req: dict) -> dict | None:
    method = req.get("method")
    req_id = req.get("id")

    if method == "initialize":
        return _ok(req_id, {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "mymory-vault", "version": __version__},
        })

    if method == "tools/list":
        return _ok(req_id, {
            "tools": [
                {"name": n, "description": t["description"], "inputSchema": t["inputSchema"]}
                for n, t in TOOLS.items()
            ]
        })

    if method == "tools/call":
        params = req.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {})
        tool = TOOLS.get(name)
        if not tool:
            return _err(req_id, -32601, f"unknown tool: {name}")
        try:
            result = tool["fn"](vault, args)
        except Exception as e:
            return _err(req_id, -32000, f"{type(e).__name__}: {e}")
        return _ok(req_id, {
            "content": [{"type": "text", "text": json.dumps(result, ensure_ascii=False, indent=2)}]
        })

    if method in ("notifications/initialized", "notifications/cancelled"):
        return None

    return _err(req_id, -32601, f"method not found: {method}")


def _ok(req_id, result):
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _err(req_id, code, message):
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


# ----------------------------------------------------------------------
# Stdio loop
# ----------------------------------------------------------------------


def serve_stdio(vault: Vault):
    """Blocking stdio JSON-RPC loop."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        resp = handle_request(vault, req)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


def main():
    p = argparse.ArgumentParser(description="MyMory MCP server (stdio).")
    p.add_argument("--manifest", default=None, help="Path to kks_manifest.yaml")
    p.add_argument("--vault", default=None, help="Path to vault root")
    args = p.parse_args()

    manifest = load_manifest(path=args.manifest, vault_root=args.vault)
    vault = Vault(manifest=manifest)

    print(
        f"mymory-mcp v{__version__} ready; vault={vault.root}",
        file=sys.stderr,
        flush=True,
    )
    serve_stdio(vault)


if __name__ == "__main__":
    main()
