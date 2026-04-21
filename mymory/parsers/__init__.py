"""Parser registry bootstrap.

Importing this package triggers registration of every shipped parser via
the side-effect `register(...)` call at the bottom of each parser module.
Downstream code then uses `parser_for(path)` or `enabled_parsers(names)`
to dispatch.
"""

from __future__ import annotations

from mymory.parsers.base import (
    ParsedDocument,
    Parser,
    all_parsers,
    enabled_parsers,
    get,
    parser_for,
    register,
)

# Side-effect imports: each module registers its parser class on import.
from mymory.parsers import cowork_jsonl  # noqa: F401
from mymory.parsers import claude_code_jsonl  # noqa: F401
from mymory.parsers import chatgpt_export  # noqa: F401
from mymory.parsers import grok_export  # noqa: F401
from mymory.parsers import mmr  # noqa: F401

__all__ = [
    "ParsedDocument",
    "Parser",
    "all_parsers",
    "enabled_parsers",
    "get",
    "parser_for",
    "register",
]
