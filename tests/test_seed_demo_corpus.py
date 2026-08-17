"""Acceptance tests for `scripts/seed_demo_corpus.py` - the fathm core demo's background-corpus
seeding script (design context: `data/fathm-core-demo/report.md` in the firstmate repo)."""

from __future__ import annotations

from seed_demo_corpus import SCENARIOS, seed_demo_corpus

from ap_auth.store import AuthStore
from ap_index.index_store import IndexStore
from ap_store.store import PackageStore


def _seed(tmp_path):
    return seed_demo_corpus(
        store_root=tmp_path / "store",
        index_root=tmp_path / "index",
        auth_db=tmp_path / "auth.sqlite3",
    )


def test_seed_produces_seven_approved_gate_passing_indexed_packages(tmp_path):
    package_ids = _seed(tmp_path)
    assert len(package_ids) == 7
    assert len(set(package_ids)) == 7  # all distinct

    store = PackageStore(tmp_path / "store")
    index = IndexStore(tmp_path / "index")

    analysts = set()
    weeks = set()
    suppliers = set()
    reason_codes = set()

    for scenario, package_id in zip(SCENARIOS, package_ids):
        record = store.get(package_id)
        assert record is not None
        assert record.status == "approved"
        assert record.gate_overall == "pass"

        hits = index.search(scenario.part, filters=None)
        assert any(h.chunk.package_id == package_id for h in hits), (
            f"{package_id} not discoverable in the FTS5 index"
        )

        analysts.add(scenario.analyst.id)
        weeks.add(scenario.week)
        suppliers.add(scenario.supplier)
        reason_codes.add(scenario.reason_code)

    # Variety asserted programmatically, not eyeballed - matches the task's acceptance criteria.
    assert analysts == {"tom.planner", "priya.planner"}
    assert len(weeks) == 7
    assert len(suppliers) == 7
    assert len(reason_codes) >= 4

    # None of the seeded content collides with the live demo's own ACME/BBU-100 story.
    assert "ACME" not in suppliers
    assert "BBU-100" not in {scenario.part for scenario in SCENARIOS}


def test_seed_populates_real_audit_trail_and_reviewer(tmp_path):
    package_ids = _seed(tmp_path)
    store = PackageStore(tmp_path / "store")

    for package_id in package_ids:
        record = store.get(package_id)
        trail = store.audit_trail(package_id, record.package_version)
        statuses = [row.to_status for row in trail]
        # draft -> in_review -> approved, driven through the real ReviewWorkflow (not hand-inserted
        # rows) - all three transitions must appear in the audit trail.
        assert "draft" in statuses
        assert "in_review" in statuses
        assert "approved" in statuses
        approve_row = next(row for row in trail if row.to_status == "approved")
        assert approve_row.actor_id == "mia.manager"


def test_seed_provisions_the_three_demo_identities(tmp_path):
    _seed(tmp_path)
    with AuthStore(tmp_path / "auth.sqlite3") as auth:
        users = {u.id for u in auth.list_users()}
    assert {"tom.planner", "priya.planner", "mia.manager"} <= users


def test_rerun_against_same_roots_is_a_no_op_not_a_duplicate_or_error(tmp_path):
    first = _seed(tmp_path)
    second = _seed(tmp_path)
    assert first == second

    store = PackageStore(tmp_path / "store")
    for package_id in second:
        record = store.get(package_id)
        assert record is not None
        assert record.status == "approved"

    # No extra packages materialized - store.list() page over a generous size still shows 7.
    from ap_store.store import ListFilter

    page = store.list(ListFilter(page_size=50))
    assert len([p for p in page.items if p.package_id in set(second)]) == 7


def test_gold_pack_fixture_is_untouched(tmp_path):
    import subprocess

    before = subprocess.run(["git", "status", "--porcelain", "examples/commodity-commit-v1"], capture_output=True, text=True)
    _seed(tmp_path)
    after = subprocess.run(["git", "status", "--porcelain", "examples/commodity-commit-v1"], capture_output=True, text=True)
    assert before.stdout == after.stdout == ""
