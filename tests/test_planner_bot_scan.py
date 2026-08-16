"""ap_planner_bot.scan: corpus extraction + in-process gate rerun + override-row parsing."""

from __future__ import annotations

from _planner_bot_corpus import DRIFT_SCENARIOS, build_clean_corpus, build_drift_corpus

from ap_planner_bot.scan import scan_corpus


def test_scan_corpus_covers_every_approved_package(tmp_path):
    store = build_drift_corpus(tmp_path)
    scan = scan_corpus(store)

    assert len(scan) == len(DRIFT_SCENARIOS)
    assert {p.package_id for p in scan.packages} == {r.package_id for r in _all_records(store)}


def test_package_scan_carries_outcomes_and_override_rows(tmp_path):
    store = build_drift_corpus(tmp_path)
    scan = scan_corpus(store)

    for pkg in scan.packages:
        assert pkg.outcomes  # every registered check_id ran
        assert "must_fields" in pkg.outcomes
        assert len(pkg.override_rows) == 1
        row = pkg.override_rows[0]
        assert row.field_path
        assert row.reason_code


def test_only_approved_packages_are_scanned(tmp_path):
    """A package that never left draft must not show up in the scan."""
    from ap_agent_tools.tools import package_create
    from ap_auth.identity import Identity
    from ap_auth.roles import Role
    from ap_store.store import PackageStore

    store = build_clean_corpus(tmp_path)
    analyst = Identity(id="planner.draft-only", roles=frozenset({Role.ANALYST}))
    pkg_dir = package_create(tmp_path / "draft-pkg", title="never reviewed", analyst_id=analyst.id)
    record = store.publish(pkg_dir, actor=analyst)
    assert record.status == "draft"

    scan = scan_corpus(store)
    assert record.package_id not in {p.package_id for p in scan.packages}


def _all_records(store):
    from ap_store.store import ListFilter

    return store.list(ListFilter(status="approved", page_size=100)).items
