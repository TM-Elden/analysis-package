"""IndexStore: the C4 retrieval layer's query surface - `search(query, filters)` and `get_chunk`.

Consumes only `ap_redact.Chunk` objects - never a package directory or manifest - so nothing
unredacted can structurally end up indexed (see CLAUDE.md). Indexing is whole-package
replace-on-write: `index_package` deletes any existing rows for `(package_id, package_version)`
before inserting, so re-indexing the same package version is idempotent and there is no separate
"update a chunk" API. At this corpus scale (see report section 5.3) a full package re-index is
sub-second, so that is the only granularity this module offers - see `ap_index.reindex` for the
one-package-at-a-time hook this enables.
"""

from __future__ import annotations

import re
import threading
from pathlib import Path
from typing import Any

from ap_index.db import connect
from ap_index.models import ChunkRecord, SearchFilters, SearchResult
from ap_redact.chunk import Chunk

_QUERY_TOKEN = re.compile(r"[\w][\w.-]*", re.UNICODE)


def _sanitize_fts_query(query: str) -> str:
    """Turn free text into an FTS5 MATCH expression that treats every token as a literal phrase.

    Bare FTS5 query syntax reads `-`, `"`, `*`, and column-name-like tokens as operators (e.g.
    `BBU-100` parses as `BBU NOT 100`), which fathm queries are full of (part numbers, ids). Since
    callers here are C4's tool-loop and tests, not a hand-typed FTS5 query language, every token is
    quoted so it always matches literally, implicit-ANDed together.
    """
    tokens = _QUERY_TOKEN.findall(query)
    if not tokens:
        return '""'
    return " ".join('"' + t.replace('"', '""') + '"' for t in tokens)


class IndexStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.conn = connect(self.root / "index.sqlite3")
        self._lock = threading.RLock()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "IndexStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- writes -------------------------------------------------------

    def index_package(self, chunks: list[Chunk]) -> None:
        """Replace every indexed chunk for this package version with `chunks`. All chunks must
        share one `(package_id, package_version)` - that's the unit `ap_redact.redact_package`
        produces."""
        if not chunks:
            return
        package_id = chunks[0].package_id
        package_version = chunks[0].package_version
        if any(c.package_id != package_id or c.package_version != package_version for c in chunks):
            raise ValueError("index_package requires all chunks to share one (package_id, package_version)")
        with self._lock, self.conn:
            self.conn.execute(
                "DELETE FROM chunks WHERE package_id=? AND package_version=?", (package_id, package_version)
            )
            self.conn.executemany(
                """INSERT INTO chunks
                   (chunk_id, package_id, package_version, as_of, profile, chunk_type, field_path,
                    confidentiality, text)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                [
                    (
                        c.chunk_id,
                        c.package_id,
                        c.package_version,
                        c.as_of,
                        c.profile,
                        c.chunk_type,
                        c.field_path,
                        c.confidentiality,
                        c.text,
                    )
                    for c in chunks
                ],
            )

    def remove_package(self, package_id: str, package_version: str) -> None:
        """Idempotent: removing a package version that isn't indexed is a no-op. Called whenever a
        package leaves `approved` status, or was blocked by the redaction fail-closed policy."""
        with self._lock, self.conn:
            self.conn.execute(
                "DELETE FROM chunks WHERE package_id=? AND package_version=?", (package_id, package_version)
            )

    # -- reads ----------------------------------------------------------

    def get_chunk(self, chunk_id: str) -> ChunkRecord | None:
        with self._lock:
            row = self.conn.execute("SELECT * FROM chunks WHERE chunk_id=?", (chunk_id,)).fetchone()
        return self._row_to_chunk(row) if row else None

    def search(self, query: str | None, *, filters: SearchFilters | None = None, limit: int = 20) -> list[SearchResult]:
        """FTS5 BM25 full-text search, optionally combined with tag filters. `query` may be None
        or empty to run a filters-only lookup (e.g. "every chunk for this package_id") - C4's
        structured-metadata-answers-half-the-prompts case from the report."""
        filters = filters or SearchFilters()
        clauses: list[str] = []
        params: list[Any] = []
        if query:
            clauses.append("chunks MATCH ?")
            params.append(_sanitize_fts_query(query))
        if filters.package_id:
            clauses.append("package_id = ?")
            params.append(filters.package_id)
        if filters.profile:
            clauses.append("profile = ?")
            params.append(filters.profile)
        if filters.chunk_type:
            clauses.append("chunk_type = ?")
            params.append(filters.chunk_type)
        if filters.confidentiality_in:
            placeholders = ",".join("?" * len(filters.confidentiality_in))
            clauses.append(f"confidentiality IN ({placeholders})")
            params.extend(filters.confidentiality_in)

        where = " AND ".join(clauses) if clauses else "1=1"
        if query:
            order_by, score_expr = "bm25(chunks) ASC", "bm25(chunks) AS score"
        else:
            order_by, score_expr = "rowid ASC", "0.0 AS score"

        with self._lock:
            rows = self.conn.execute(
                f"SELECT *, {score_expr} FROM chunks WHERE {where} ORDER BY {order_by} LIMIT ?",
                [*params, limit],
            ).fetchall()
        return [SearchResult(chunk=self._row_to_chunk(r), score=r["score"]) for r in rows]

    # -- internals --------------------------------------------------------

    @staticmethod
    def _row_to_chunk(row) -> ChunkRecord:
        return ChunkRecord(
            chunk_id=row["chunk_id"],
            package_id=row["package_id"],
            package_version=row["package_version"],
            as_of=row["as_of"],
            profile=row["profile"],
            chunk_type=row["chunk_type"],
            field_path=row["field_path"],
            confidentiality=row["confidentiality"],
            text=row["text"],
        )
