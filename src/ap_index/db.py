"""SQLite FTS5 schema for the C4 retrieval index.

FTS5, not a vector database - see CLAUDE.md and report section 5.3 for the sizing evidence (the
entire pilot corpus is on the order of tens of thousands of tokens/year). Tags (`package_id`,
`package_version`, `as_of`, `profile`, `chunk_type`, `field_path`, `confidentiality`) are declared
`UNINDEXED` in the FTS5 table: they are not part of the full-text index, but remain ordinary
filterable columns usable in a `WHERE` clause alongside `MATCH` - exactly what `IndexStore.search`
needs for the approved-only / confidentiality-by-role scoping filters.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
CREATE VIRTUAL TABLE IF NOT EXISTS chunks USING fts5(
    chunk_id UNINDEXED,
    package_id UNINDEXED,
    package_version UNINDEXED,
    as_of UNINDEXED,
    profile UNINDEXED,
    chunk_type UNINDEXED,
    field_path UNINDEXED,
    confidentiality UNINDEXED,
    text
);
"""


def connect(db_path: Path) -> sqlite3.Connection:
    """Open the FTS5 index DB. `check_same_thread=False` for the same reason as
    `ap_store.db.connect` - a future API layer's threadpool worker threads share one connection,
    serialized by `IndexStore`'s own lock."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
