"""C4 retrieval layer: FTS5 index over ap_redact's chunk stream, reindex-on-status-change hook,
and the commodity-commit-v1 reference case end to end (redact -> index -> query)."""

from __future__ import annotations

import shutil

from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_gate.load_manifest import load_manifest
from ap_index.index_store import IndexStore
from ap_index.models import SearchFilters
from ap_index.reindex import reindex_package
from ap_redact.redact import redact_package
from ap_review.policy import ReviewPolicy
from ap_review.workflow import ReviewWorkflow
from ap_store.store import PackageStore

from conftest import EXAMPLE_PACKAGE


def _identity(actor_id: str, role: Role) -> Identity:
    return Identity(id=actor_id, roles=frozenset({role}))


def _copy_example(tmp_path, name: str = "pkg"):
    dest = tmp_path / name
    shutil.copytree(EXAMPLE_PACKAGE, dest)
    return dest


def _publish_and_approve(tmp_path, pkg_dir):
    manifest = load_manifest(pkg_dir)
    analyst_id = manifest["owners"]["analyst"]["id"]
    reviewer_id = manifest["owners"]["reviewer"]["id"]

    store = PackageStore(tmp_path / "store")
    record = store.publish(pkg_dir, actor=_identity(analyst_id, Role.ANALYST))
    wf = ReviewWorkflow(store=store)
    wf.transition(record.package_id, record.package_version, to_status="in_review", actor=_identity(analyst_id, Role.ANALYST))
    record = wf.transition(
        record.package_id, record.package_version, to_status="approved", actor=_identity(reviewer_id, Role.REVIEWER)
    )
    return store, record


def test_index_package_and_search_round_trip(tmp_path):
    pkg_dir = _copy_example(tmp_path)
    manifest = load_manifest(pkg_dir)
    chunks, report = redact_package(
        pkg_dir, manifest, package_id=manifest["package_id"], package_version=manifest["package_version"]
    )
    assert not report.blocked

    index = IndexStore(tmp_path / "index")
    index.index_package(chunks)

    results = index.search("ACME")
    assert results
    assert all(r.chunk.package_id == manifest["package_id"] for r in results)

    one = results[0]
    fetched = index.get_chunk(one.chunk.chunk_id)
    assert fetched == one.chunk
    index.close()


def test_search_filters_and_get_chunk_missing(tmp_path):
    pkg_dir = _copy_example(tmp_path)
    manifest = load_manifest(pkg_dir)
    chunks, _report = redact_package(
        pkg_dir, manifest, package_id=manifest["package_id"], package_version=manifest["package_version"]
    )
    index = IndexStore(tmp_path / "index")
    index.index_package(chunks)

    filtered = index.search("ACME", filters=SearchFilters(chunk_type="override"))
    assert filtered
    assert all(r.chunk.chunk_type == "override" for r in filtered)

    none_match = index.search("ACME", filters=SearchFilters(package_id="pkg_nonexistent"))
    assert none_match == []

    assert index.get_chunk("does-not-exist") is None

    # Filters-only search (no query text) still works - "everything for this package".
    by_type = index.search(None, filters=SearchFilters(chunk_type="exception"))
    assert {r.chunk.chunk_type for r in by_type} == {"exception"}
    index.close()


def test_index_package_reindex_is_idempotent_replace(tmp_path):
    pkg_dir = _copy_example(tmp_path)
    manifest = load_manifest(pkg_dir)
    chunks, _report = redact_package(
        pkg_dir, manifest, package_id=manifest["package_id"], package_version=manifest["package_version"]
    )
    index = IndexStore(tmp_path / "index")
    index.index_package(chunks)
    index.index_package(chunks)  # re-index the same version twice

    results = index.search(None, filters=SearchFilters(package_id=manifest["package_id"]))
    assert len(results) == len(chunks)  # no duplicate rows
    index.close()


def test_reindex_hook_only_indexes_approved_packages(tmp_path):
    pkg_dir = _copy_example(tmp_path)
    manifest = load_manifest(pkg_dir)
    analyst_id = manifest["owners"]["analyst"]["id"]

    store = PackageStore(tmp_path / "store")
    record = store.publish(pkg_dir, actor=_identity(analyst_id, Role.ANALYST))
    index = IndexStore(tmp_path / "index")

    # draft -> not indexed
    report = reindex_package(
        store=store, index=index, store_root=tmp_path / "store",
        package_id=record.package_id, package_version=record.package_version,
    )
    assert report is None
    assert index.search(None, filters=SearchFilters(package_id=record.package_id)) == []

    wf = ReviewWorkflow(store=store)
    wf.transition(record.package_id, record.package_version, to_status="in_review", actor=_identity(analyst_id, Role.ANALYST))
    reviewer_id = manifest["owners"]["reviewer"]["id"]
    wf.transition(record.package_id, record.package_version, to_status="approved", actor=_identity(reviewer_id, Role.REVIEWER))

    report = reindex_package(
        store=store, index=index, store_root=tmp_path / "store",
        package_id=record.package_id, package_version=record.package_version,
    )
    assert report is not None
    assert not report.blocked
    approved_results = index.search(None, filters=SearchFilters(package_id=record.package_id))
    assert len(approved_results) == report.chunk_count

    store.close()
    index.close()


def test_reindex_hook_removes_a_rejected_package(tmp_path):
    """A package that never reaches (or leaves) `approved` must never sit in the index - exercises
    the hook's generic "anything else -> remove" branch."""
    pkg_dir = _copy_example(tmp_path)
    manifest = load_manifest(pkg_dir)
    analyst_id = manifest["owners"]["analyst"]["id"]
    reviewer_id = manifest["owners"]["reviewer"]["id"]

    store = PackageStore(tmp_path / "store")
    record = store.publish(pkg_dir, actor=_identity(analyst_id, Role.ANALYST))
    wf = ReviewWorkflow(store=store)
    wf.transition(record.package_id, record.package_version, to_status="in_review", actor=_identity(analyst_id, Role.ANALYST))
    wf.transition(
        record.package_id, record.package_version, to_status="rejected",
        actor=_identity(reviewer_id, Role.REVIEWER), reason="not ready",
    )

    index = IndexStore(tmp_path / "index")
    report = reindex_package(
        store=store, index=index, store_root=tmp_path / "store",
        package_id=record.package_id, package_version=record.package_version,
    )
    assert report is None
    assert index.search(None, filters=SearchFilters(package_id=record.package_id)) == []
    store.close()
    index.close()


def test_secret_salted_package_never_reaches_index(tmp_path):
    pkg_dir = _copy_example(tmp_path)
    (pkg_dir / "code" / "leaked_creds.py").write_text("AWS_KEY = 'AKIAABCDEFGHIJKLMNOP'\n", encoding="utf-8")
    manifest = load_manifest(pkg_dir)
    analyst_id = manifest["owners"]["analyst"]["id"]
    reviewer_id = manifest["owners"]["reviewer"]["id"]

    store = PackageStore(tmp_path / "store")
    record = store.publish(pkg_dir, actor=_identity(analyst_id, Role.ANALYST))
    wf = ReviewWorkflow(store=store, policy=ReviewPolicy(gate_before_review=False))
    wf.transition(record.package_id, record.package_version, to_status="in_review", actor=_identity(analyst_id, Role.ANALYST))
    wf.transition(record.package_id, record.package_version, to_status="approved", actor=_identity(reviewer_id, Role.REVIEWER))

    index = IndexStore(tmp_path / "index")
    report = reindex_package(
        store=store, index=index, store_root=tmp_path / "store",
        package_id=record.package_id, package_version=record.package_version,
    )
    assert report.blocked is True
    assert index.search(None, filters=SearchFilters(package_id=record.package_id)) == []
    for word in ["AKIAABCDEFGHIJKLMNOP"]:
        for r in index.search(word):
            assert word not in r.chunk.text
    store.close()
    index.close()


def test_commodity_commit_v1_indexes_cleanly_end_to_end(tmp_path):
    """The reference case: redact -> index -> query, once approved through the real review workflow."""
    pkg_dir = _copy_example(tmp_path)
    store, record = _publish_and_approve(tmp_path, pkg_dir)
    assert record.status == "approved"

    index = IndexStore(tmp_path / "index")
    report = reindex_package(
        store=store, index=index, store_root=tmp_path / "store",
        package_id=record.package_id, package_version=record.package_version,
    )
    assert report is not None
    assert not report.blocked
    assert report.chunk_count > 0

    results = index.search("ACME BBU-100")
    assert results
    assert results[0].chunk.package_id == record.package_id

    chunk_id = results[0].chunk.chunk_id
    assert index.get_chunk(chunk_id) is not None

    # Role-scoped confidentiality filter is ready to apply at query time.
    scoped = index.search("ACME", filters=SearchFilters(confidentiality_in=("public",)))
    assert scoped == []  # this package is internal_restricted, not public
    scoped_ok = index.search("ACME", filters=SearchFilters(confidentiality_in=("internal_restricted",)))
    assert scoped_ok

    store.close()
    index.close()
