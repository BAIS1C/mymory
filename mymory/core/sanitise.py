"""Inline-hash sanitiser.

Obsidian parses any bare `#foo` token in note body as a tag. Our converters
pass `#` tokens through verbatim from source documents (design specs, pitch
decks, Singapore address blocks), so hex color codes (`#FAFAF9`), unit
numbers (`#07-01`), and inline content hashtags (`#ERP`, `#SaaS`) all end up
as real graph tags, polluting retrieval.

Our canonical tag semantics live in YAML frontmatter exclusively. Any
inline `#token` in body text is pollution.

Strategy (chosen 2026-04-21): wrap offending tokens in inline backticks so
they render verbatim and do not register as tags. Preserves document
fidelity, reversible, and idempotent because the backtick lookbehind
prevents double-wrapping.

Preserved contexts (not sanitised):
  - Fenced code blocks (```...```)
  - Indented code blocks (4-space indent, handled implicitly by placeholder)
  - Existing inline backtick spans
  - Wikilinks: [[...]]
  - Markdown links: [text](url)
  - URL tokens (http://, https://)
  - MD heading lines (lines starting with `# `, `## `, etc.)
"""

from __future__ import annotations

import re
from typing import Callable


# ----------------------------------------------------------------------
# Placeholder protection: token regex that captures everything that must
# not be touched by the hash rewriters.
# ----------------------------------------------------------------------

_PROTECT_RE = re.compile(
    r"""
    (?P<code>`[^`\n]*`)                             # inline code span
    | (?P<wikilink>\[\[[^\]\n]*\]\])                # [[wikilink]]
    | (?P<mdlink>\[[^\]\n]*\]\([^\)\n]*\))          # [text](url)
    | (?P<url>https?://\S+)                         # bare URL
    """,
    re.VERBOSE,
)

# Order matters: hex first (narrowest), then address, then bare hashtag.
_HEX_RE = re.compile(
    r"(?<![\w`\[/])(#[0-9A-Fa-f]{3,8})(?![\w-])"
)

_ADDR_RE = re.compile(
    r"(?<![\w`\[/])(#\d{2}-\d{2,4})(?![\w-])"
)

# Bare inline hashtag: starts with letter, then word chars / dashes.
# The lookbehind prevents matching inside backticks, wikilinks,
# word fragments, URL fragments, or markdown anchor fragments.
_HASHTAG_RE = re.compile(
    r"(?<![\w`\[/\(])(#[A-Za-z][A-Za-z0-9_-]*)(?![\w-])"
)

# Fenced code fence line (``` or ~~~ optionally followed by lang).
_FENCE_RE = re.compile(r"^(\s*)(```+|~~~+)")


def _wrap(match: re.Match) -> str:
    return f"`{match.group(1)}`"


def _sanitise_text(text: str) -> str:
    """Apply hex/addr/hashtag wrappers to a fragment with protected tokens
    already masked out. Caller handles placeholder restore."""
    text = _HEX_RE.sub(_wrap, text)
    text = _ADDR_RE.sub(_wrap, text)
    text = _HASHTAG_RE.sub(_wrap, text)
    return text


def _sanitise_line(line: str) -> str:
    """Sanitise a single non-code-block line, preserving MD heading prefix
    and masking protected spans."""
    # MD heading: "# title" or "## title" etc. Keep the hash prefix intact;
    # only sanitise the body after the first space.
    m = re.match(r"^(\s*#+\s+)(.*)$", line)
    if m:
        return m.group(1) + _sanitise_body_fragment(m.group(2))
    return _sanitise_body_fragment(line)


def _sanitise_body_fragment(frag: str) -> str:
    """Mask protected tokens, rewrite unprotected hashes, restore tokens."""
    placeholders: list[str] = []

    def _stash(m: re.Match) -> str:
        placeholders.append(m.group(0))
        return f"\x00PH{len(placeholders) - 1}\x00"

    masked = _PROTECT_RE.sub(_stash, frag)
    rewritten = _sanitise_text(masked)

    def _restore(m: re.Match) -> str:
        idx = int(m.group(1))
        return placeholders[idx]

    return re.sub(r"\x00PH(\d+)\x00", _restore, rewritten)


def sanitise_hashes(body: str) -> str:
    """Wrap pollution `#...` tokens in a markdown body with inline backticks.

    Idempotent. Safe to call on already-sanitised text because the lookbehind
    excludes backtick contexts.
    """
    if not body or "#" not in body:
        return body

    out_lines: list[str] = []
    in_fence = False
    fence_marker: str | None = None

    for line in body.splitlines(keepends=True):
        stripped_nl = line.rstrip("\n\r")
        nl = line[len(stripped_nl):]

        m = _FENCE_RE.match(stripped_nl)
        if m:
            marker = m.group(2)[:3]  # normalise to fence type
            if not in_fence:
                in_fence = True
                fence_marker = marker
            elif fence_marker and marker == fence_marker:
                in_fence = False
                fence_marker = None
            out_lines.append(stripped_nl + nl)
            continue

        if in_fence:
            out_lines.append(stripped_nl + nl)
            continue

        out_lines.append(_sanitise_line(stripped_nl) + nl)

    return "".join(out_lines)


def sanitise_stats(before: str, after: str) -> dict[str, int]:
    """Count how many of each pattern got wrapped. Coarse: looks at diff."""
    def _count(pat: re.Pattern, text: str) -> int:
        return len(pat.findall(text))

    return {
        "hex_wrapped":     _count(_HEX_RE,     before) - _count(_HEX_RE,     after),
        "addr_wrapped":    _count(_ADDR_RE,    before) - _count(_ADDR_RE,    after),
        "hashtag_wrapped": _count(_HASHTAG_RE, before) - _count(_HASHTAG_RE, after),
    }
