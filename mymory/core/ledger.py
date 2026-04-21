"""Ingest ledger: SQLite-backed dedup + provenance record.

Ported from Sean Uddin's MKV converter module. Generalized for any vault.
"""

from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS conversions (
    sha256 TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    dest_path TEXT NOT NULL,
    wing TEXT NOT NULL,
    source_format TEXT NOT NULL,
    word_count INTEGER DEFAULT 0,
    converted_at TEXT NOT NULL,
    extra_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_conversions_wing ON conversions(wing);
CREATE INDEX IF NOT EXISTS idx_conversions_format ON conversions(source_format);
"""


class IngestLedger:
    """Dedup ledger: SHA256 -> conversion record."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.executescript(SCHEMA)
        self.conn.commit()

    # ------------------------------------------------------------------

    def is_converted(self, sha256: str) -> bool:
        cur = self.conn.execute("SELECT 1 FROM conversions WHERE sha256 = ?", (sha256,))
        return cur.fetchone() is not None

    def get(self, sha256: str) -> dict[str, Any] | None:
        cur = self.conn.execute(
            "SELECT sha256, source_path, dest_path, wing, source_format, word_count, converted_at "
            "FROM conversions WHERE sha256 = ?",
            (sha256,),
        )
        row = cur.fetchone()
        if not row:
            return None
        keys = ["sha256", "source_path", "dest_path", "wing", "source_format", "word_count", "converted_at"]
        return dict(zip(keys, row))

    def record(
        self,
        sha256: str,
        source_path: str,
        dest_path: str,
        wing: str,
        source_format: str,
        word_count: int,
    ) -> None:
        self.conn.execute(
            """INSERT OR REPLACE INTO conversions
               (sha256, source_path, dest_path, wing, source_format, word_count, converted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (sha256, source_path, dest_path, wing, source_format, word_count, datetime.now().isoformat()),
        )
        self.conn.commit()

    # ------------------------------------------------------------------

    def stats(self) -> list[dict[str, Any]]:
        cur = self.conn.execute(
            "SELECT wing, source_format, COUNT(*), SUM(word_count) "
            "FROM conversions GROUP BY wing, source_format ORDER BY wing, source_format"
        )
        return [
            {"wing": w, "format": f, "count": c, "words": (wc or 0)}
            for (w, f, c, wc) in cur.fetchall()
        ]

    def total_count(self) -> int:
        cur = self.conn.execute("SELECT COUNT(*) FROM conversions")
        return cur.fetchone()[0]

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "IngestLedger":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


def default_ledger_path(vault_root: str) -> str:
    return os.path.join(vault_root, ".embed_cache", "ingest_ledger.db")
