"""Grep fallback: ripgrep wrapper + pure-Python fallback when rg is absent.

Used when semantic search misses exact tokens (code symbols, error strings).
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from dataclasses import dataclass

from mymory.core.vault import Vault


@dataclass
class GrepHit:
    path: str
    line_no: int
    line: str


def has_ripgrep() -> bool:
    return shutil.which("rg") is not None


def grep(
    vault: Vault,
    pattern: str,
    wing: str | None = None,
    case_insensitive: bool = True,
    max_hits: int = 200,
) -> list[GrepHit]:
    """Grep the vault (or a single wing). Use ripgrep if available, else Python re."""
    search_root = os.path.join(vault.root, wing) if wing else vault.root
    if not os.path.isdir(search_root):
        return []

    if has_ripgrep():
        return _rg_search(search_root, pattern, case_insensitive, max_hits)
    return _python_search(vault, search_root, pattern, case_insensitive, max_hits)


def _rg_search(root: str, pattern: str, ci: bool, max_hits: int) -> list[GrepHit]:
    cmd = ["rg", "--type", "md", "--no-heading", "--line-number", "--color", "never"]
    if ci:
        cmd.append("-i")
    cmd += [pattern, root]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=30, check=False)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return []
    hits: list[GrepHit] = []
    for line in out.stdout.splitlines():
        parts = line.split(":", 2)
        if len(parts) < 3:
            continue
        path, ln, body = parts
        try:
            hits.append(GrepHit(path=path, line_no=int(ln), line=body))
        except ValueError:
            continue
        if len(hits) >= max_hits:
            break
    return hits


def _python_search(vault: Vault, root: str, pattern: str, ci: bool, max_hits: int) -> list[GrepHit]:
    flags = re.IGNORECASE if ci else 0
    try:
        regex = re.compile(pattern, flags)
    except re.error:
        regex = re.compile(re.escape(pattern), flags)

    hits: list[GrepHit] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for fn in filenames:
            if not fn.endswith(".md"):
                continue
            full = os.path.join(dirpath, fn)
            try:
                with open(full, "r", encoding="utf-8", errors="replace") as f:
                    for i, line in enumerate(f, start=1):
                        if regex.search(line):
                            hits.append(GrepHit(path=full, line_no=i, line=line.rstrip("\n")))
                            if len(hits) >= max_hits:
                                return hits
            except OSError:
                continue
    return hits
