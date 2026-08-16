"""Read-model dataclasses returned by IndexStore. See ap_index.db for the schema they mirror."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ChunkRecord:
    chunk_id: str
    package_id: str
    package_version: str
    as_of: str
    profile: str
    chunk_type: str
    field_path: str
    confidentiality: str
    text: str


@dataclass(frozen=True)
class SearchFilters:
    """Scoping filters, computed by the caller before `search()` (per-caller identity ->
    filters, per C4's double-check pattern in the report) - `IndexStore` applies them, it does not
    derive them. `confidentiality_in` is how role-based retrieval filtering plugs in: pass the set
    of `confidentiality` values the caller's role may see."""

    package_id: str | None = None
    profile: str | None = None
    chunk_type: str | None = None
    confidentiality_in: tuple[str, ...] | None = None


@dataclass(frozen=True)
class SearchResult:
    chunk: ChunkRecord
    score: float  # bm25(); lower is more relevant (sqlite FTS5 convention). 0.0 for filter-only, no-query searches.
