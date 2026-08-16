"""The three retrieval tools the C4 loop gets (`search_packages`, `get_package_summary`,
`get_gate_report`) plus the `provide_answer` tool that closes the loop - see `service.py`.

Every tool here is scoped to one `Identity` for its whole lifetime (`ManagerBotTools` is
constructed once per `/chat/manager` request, never shared across callers). Each read applies the
identity's `confidentiality_in` filter *before* querying `ap_index` (`scoping.confidentiality_filter_for`)
and re-checks every returned chunk *after* the query (`scoping.chunk_in_scope`) before it is ever
turned into tool-result JSON the LLM can see - the double-check the report calls for. A chunk (or a
gate report) that fails either check is simply absent from the tool result, indistinguishable from a
chunk that was never indexed - the caller never sees a "which package would answer this if you had
access" oracle.

`_citable` is the citation ground-truth registry for one request: every ref_id this instance hands
back to the model is recorded here with the `Citation` it actually corresponds to, so
`service.py` can reject any citation the model's final answer references that this instance never
actually retrieved (a hallucinated citation, or a chunk that failed the post-check) - see
`ManagerBotTools.resolve_citation`.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from ap_auth.identity import Identity
from ap_gate.checks.context import CheckContext
from ap_gate.checks.registry import run_all
from ap_gate.load_manifest import load_manifest
from ap_gate.report.model import build_report
from ap_index.index_store import IndexStore
from ap_index.models import ChunkRecord, SearchFilters
from ap_manager_bot.models import Citation
from ap_manager_bot.scoping import chunk_in_scope, confidentiality_filter_for
from ap_store.store import PackageStore

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "search_packages": {
        "description": (
            "Full-text + filtered search over the approved, redacted package corpus this caller "
            "may see. Query is free text (entity-heavy terms like supplier/part codes work best, "
            "e.g. 'ACME BBU-100'); omit it to list every chunk matching the filters. Returns chunks "
            "with a ref_id, package_id, field_path and text - cite ref_id in provide_answer."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Free-text search terms; omit for a filters-only lookup"},
                "package_id": {"type": "string"},
                "chunk_type": {
                    "type": "string",
                    "enum": ["manifest_summary", "override", "judgment", "truth", "run_summary", "exception"],
                },
                "limit": {"type": "integer", "default": 10},
            },
        },
    },
    "get_package_summary": {
        "description": "Fetch one package's manifest summary (title, profile, purpose, confidentiality) by package_id.",
        "input_schema": {
            "type": "object",
            "required": ["package_id"],
            "properties": {"package_id": {"type": "string"}},
        },
    },
    "get_gate_report": {
        "description": "Fetch the ap-gate structural validation report (pass/fail per check) for one package_id.",
        "input_schema": {
            "type": "object",
            "required": ["package_id"],
            "properties": {"package_id": {"type": "string"}},
        },
    },
    "provide_answer": {
        "description": (
            "End the conversation with your final answer. Every factual claim must be backed by a "
            "ref_id returned by an earlier search_packages/get_package_summary/get_gate_report call "
            "in THIS conversation - citing anything else is rejected. If nothing retrieved is "
            "actually relevant to the question, set no_evidence=true and leave citations empty "
            "rather than guessing."
        ),
        "input_schema": {
            "type": "object",
            "required": ["answer", "citations", "no_evidence"],
            "properties": {
                "answer": {"type": "string"},
                "no_evidence": {"type": "boolean"},
                "citations": {
                    "type": "array",
                    "items": {"type": "object", "required": ["ref_id"], "properties": {"ref_id": {"type": "string"}}},
                },
            },
        },
    },
}


class ManagerBotTools:
    def __init__(self, *, index: IndexStore, store: PackageStore, identity: Identity):
        self._index = index
        self._store = store
        self._identity = identity
        self._confidentiality = confidentiality_filter_for(identity)
        self._citable: dict[str, Citation] = {}

    def resolve_citation(self, ref_id: str) -> Citation | None:
        """A citation is only real if this exact instance handed its ref_id to the model earlier -
        see the module docstring."""
        return self._citable.get(ref_id)

    # -- tools, dispatched by name from service.py's tool loop --------------

    def search_packages(
        self, *, query: str | None = None, package_id: str | None = None, chunk_type: str | None = None, limit: int = 10
    ) -> dict[str, Any]:
        filters = SearchFilters(package_id=package_id, chunk_type=chunk_type, confidentiality_in=self._confidentiality)
        results = self._index.search(query, filters=filters, limit=limit)
        chunks = [r.chunk for r in results if chunk_in_scope(self._identity, r.chunk)]
        return {"results": [self._register_chunk(c) for c in chunks]}

    def get_package_summary(self, *, package_id: str) -> dict[str, Any]:
        filters = SearchFilters(package_id=package_id, chunk_type="manifest_summary", confidentiality_in=self._confidentiality)
        results = self._index.search(None, filters=filters, limit=1)
        if not results or not chunk_in_scope(self._identity, results[0].chunk):
            return {"error": f"no such package, or not accessible to this caller: {package_id}"}
        return self._register_chunk(results[0].chunk)

    def get_gate_report(self, *, package_id: str) -> dict[str, Any]:
        # Same visibility gate as get_package_summary - a gate report is never returned for a
        # package this caller couldn't otherwise see a summary of.
        filters = SearchFilters(package_id=package_id, chunk_type="manifest_summary", confidentiality_in=self._confidentiality)
        results = self._index.search(None, filters=filters, limit=1)
        if not results or not chunk_in_scope(self._identity, results[0].chunk):
            return {"error": f"no such package, or not accessible to this caller: {package_id}"}
        package_version = results[0].chunk.package_version

        with tempfile.TemporaryDirectory(prefix="ap-manager-bot-gate-") as tmp:
            pkg_dir = self._store.extract(package_id, package_version, Path(tmp) / "pkg")
            manifest = load_manifest(pkg_dir)
            ctx = CheckContext(package_path=pkg_dir, manifest=manifest)
            outcomes = run_all(ctx)
            report = build_report(
                package_id=package_id,
                title=str(manifest.get("title", "")),
                as_of=str(manifest.get("as_of", "")),
                qa_status=str((manifest.get("qa") or {}).get("status", "")),
                profile=str(manifest.get("profile", "")),
                outcomes=outcomes,
            )

        ref_id = f"{package_id}:gate"
        self._citable[ref_id] = Citation(
            ref_id=ref_id,
            package_id=package_id,
            package_version=package_version,
            field_path="gate_report#overall",
            chunk_type="gate_report",
        )
        return {"ref_id": ref_id, "package_id": package_id, "package_version": package_version, **report}

    # -- internals ------------------------------------------------------

    def _register_chunk(self, chunk: ChunkRecord) -> dict[str, Any]:
        self._citable[chunk.chunk_id] = Citation(
            ref_id=chunk.chunk_id,
            package_id=chunk.package_id,
            package_version=chunk.package_version,
            field_path=chunk.field_path,
            chunk_type=chunk.chunk_type,
        )
        return {
            "ref_id": chunk.chunk_id,
            "package_id": chunk.package_id,
            "package_version": chunk.package_version,
            "chunk_type": chunk.chunk_type,
            "field_path": chunk.field_path,
            "text": chunk.text,
        }
