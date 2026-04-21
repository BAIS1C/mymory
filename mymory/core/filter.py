"""Ingest-time noise filter.

Reads the `ingest_filter:` block from the vault manifest and decides whether
a given source path should be admitted into the ingest pipeline. The filter
runs BEFORE SHA256 + dedup + parser dispatch so it never touches disk beyond
a path stat.

Rule taxonomy (all optional, all combined with OR at decision time):

- deny_source_extension       : list of extensions to reject outright
                                (e.g. code files that must be synthesised at
                                repo level by graphify, not per-file stubs)
- deny_filename_regex         : filename-only regex denylist
- deny_filename_substring     : filename-only substring denylist
- deny_source_path_substring  : substring match on the full source path
- deny_source_path_regex      : regex match on the full source path
- deny_vendor_doc_clusters    : named clusters resolved against hard-coded
                                prefix groups below (extend as needed)

Returns (skip: bool, rule: str). `rule` is the specific rule name that
matched, so callers can report which rule triggered the skip.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Iterable


# Known vendor-doc clusters. Extend by adding more keys; the value is a list
# of filename-prefix patterns (case-insensitive).
VENDOR_CLUSTERS: dict[str, list[str]] = {
    "paperclip": [
        "board-operator_",
        "agent-developer_",
        "adapters_overview",
        "commands_setup",
        "commands_adversarial-review",
        "commands_rescue",
        "commands_result",
        "commands_review",
        "commands_status",
    ],
}


@dataclass
class IngestFilter:
    deny_source_extension: set[str] = field(default_factory=set)
    deny_filename_regex: list[re.Pattern] = field(default_factory=list)
    deny_filename_substring: list[str] = field(default_factory=list)
    deny_source_path_substring: list[str] = field(default_factory=list)
    deny_source_path_regex: list[re.Pattern] = field(default_factory=list)
    deny_vendor_prefixes: list[tuple[str, str]] = field(default_factory=list)

    @classmethod
    def from_manifest_block(cls, block: dict[str, Any] | None) -> "IngestFilter":
        block = block or {}
        f = cls()

        for e in (block.get("deny_source_extension") or []):
            if not e:
                continue
            f.deny_source_extension.add(e.lower() if e.startswith(".") else "." + e.lower())

        for pat in (block.get("deny_filename_regex") or []):
            f.deny_filename_regex.append(re.compile(pat))

        for s in (block.get("deny_filename_substring") or []):
            if s:
                f.deny_filename_substring.append(s.lower())

        for s in (block.get("deny_source_path_substring") or []):
            if s:
                f.deny_source_path_substring.append(s)

        for pat in (block.get("deny_source_path_regex") or []):
            f.deny_source_path_regex.append(re.compile(pat))

        for cluster in (block.get("deny_vendor_doc_clusters") or []):
            prefixes = VENDOR_CLUSTERS.get(cluster, [])
            for p in prefixes:
                f.deny_vendor_prefixes.append((cluster, p.lower()))

        return f

    def is_empty(self) -> bool:
        return not any([
            self.deny_source_extension,
            self.deny_filename_regex,
            self.deny_filename_substring,
            self.deny_source_path_substring,
            self.deny_source_path_regex,
            self.deny_vendor_prefixes,
        ])

    def should_skip(self, path: str) -> tuple[bool, str]:
        """Return (skip, rule_name). rule_name is '' when not skipping."""
        if self.is_empty():
            return False, ""

        name = os.path.basename(path)
        name_lower = name.lower()
        ext = os.path.splitext(name)[1].lower()
        # Normalise path separators for substring checks so Windows-style
        # paths (C:\foo\bar) also match rules written with forward slashes.
        path_norm = path.replace("\\", "/")

        if ext and ext in self.deny_source_extension:
            return True, f"deny_source_extension:{ext}"

        for pat in self.deny_filename_regex:
            if pat.search(name):
                return True, f"deny_filename_regex:{pat.pattern}"

        for s in self.deny_filename_substring:
            if s in name_lower:
                return True, f"deny_filename_substring:{s}"

        for s in self.deny_source_path_substring:
            if s in path_norm:
                return True, f"deny_source_path_substring:{s}"

        for pat in self.deny_source_path_regex:
            if pat.search(path_norm):
                return True, f"deny_source_path_regex:{pat.pattern}"

        for cluster, prefix in self.deny_vendor_prefixes:
            if name_lower.startswith(prefix):
                return True, f"deny_vendor_cluster:{cluster}"

        return False, ""
