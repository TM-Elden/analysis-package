"""ap_index: the C4 retrieval layer - SQLite FTS5 index over `ap_redact`'s redacted chunk stream.

See `index_store.IndexStore` for the query surface (`search`, `get_chunk`) and `reindex.reindex_package`
for the one-package reindex hook. No vector database, no embeddings - see CLAUDE.md.
"""

from __future__ import annotations

from ap_index.index_store import IndexStore
from ap_index.models import ChunkRecord, SearchFilters, SearchResult
from ap_index.reindex import reindex_package

__all__ = ["ChunkRecord", "IndexStore", "SearchFilters", "SearchResult", "reindex_package"]
