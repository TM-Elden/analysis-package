"""Manager console "Dashboard" tab (P5.2): tier-1 store stats, tier-2 fresh-scan analytics behind
the "Recompute now" button, tier-3 snapshot trend, and the no-author-aggregation invariant applied
to the rendered page itself - `data/fathm-phase5-readiness/report.md` section 5.2 in the firstmate
repo. `base_url="https://testserver"` is required for the same reason test_console.py needs it:
`POST /login` sets a `Secure` cookie.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import ap_api.deps as deps
from ap_api.app import app
from ap_auth.roles import Role
from ap_auth.store import AuthStore
from ap_planner_bot.snapshot_store import read_snapshots
from ap_proposals.store import ProposalStore
from ap_store.store import PackageStore

from _planner_bot_corpus import ANALYST, REVIEWER, build_clean_corpus, build_drift_corpus


@pytest.fixture()
def client_and_store(tmp_path):
    package_store = PackageStore(tmp_path / "store")
    proposal_store = ProposalStore(tmp_path / "store")
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    app.dependency_overrides[deps.get_store] = lambda: package_store
    app.dependency_overrides[deps.get_proposal_store] = lambda: proposal_store
    app.dependency_overrides[deps.get_auth_store] = lambda: auth_store

    auth_store.create_user("cap.tan", display_name="Captain", roles=frozenset({Role.STANDARD_APPROVER}), password="pw-cap")

    client = TestClient(app, base_url="https://testserver")
    try:
        yield client, package_store, proposal_store
    finally:
        app.dependency_overrides.clear()
        package_store.close()
        proposal_store.close()
        auth_store.close()


def _login(client: TestClient) -> str:
    r = client.post("/login", json={"user_id": "cap.tan", "password": "pw-cap"})
    assert r.status_code == 200, r.text
    return r.json()["csrf_token"]


def _swap_in_drift_store(tmp_path):
    store = build_drift_corpus(tmp_path)
    app.dependency_overrides[deps.get_store] = lambda: store
    return store


def test_logged_out_dashboard_redirects_to_login(client_and_store):
    client, _store, _prop_store = client_and_store
    r = client.get("/console/dashboard", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/console/login")


def test_nav_includes_dashboard_tab(client_and_store):
    client, _store, _prop_store = client_and_store
    _login(client)
    r = client.get("/console/packages")
    assert 'href="/console/dashboard"' in r.text


def test_dashboard_renders_tier1_store_stats_on_empty_store(client_and_store):
    client, _store, _prop_store = client_and_store
    _login(client)
    r = client.get("/console/dashboard")
    assert r.status_code == 200
    assert "No packages published yet." in r.text
    assert "No scan has ever run yet" in r.text


def test_dashboard_renders_real_tier1_counts_against_seeded_corpus(client_and_store, tmp_path):
    client, _store, _prop_store = client_and_store
    store = _swap_in_drift_store(tmp_path)
    _login(client)

    r = client.get("/console/dashboard")
    assert r.status_code == 200
    assert store.stats().total == 9
    # tier 1 is live SQL, no scan needed - the real approved count must show up immediately.
    assert ">9<" in r.text or "9\n" in r.text or "9 " in r.text
    assert "commodity_commit_forecast/9.9" in r.text or "commodity_commit_forecast" in r.text


def test_recompute_button_runs_live_scan_and_shows_real_check_stats(client_and_store, tmp_path):
    client, _store, _prop_store = client_and_store
    _swap_in_drift_store(tmp_path)
    csrf = _login(client)

    r = client.post("/console/dashboard/recompute", headers={"X-Csrf": csrf})
    assert r.status_code == 200
    assert "engines_pinned" in r.text
    assert "guideline_exists" in r.text
    # drift signals should now be populated (live=True) rather than the "click Recompute" note.
    assert "repeated_waivers" in r.text or "gate_failure_hotspot" in r.text
    assert "No drift signals in this scan." not in r.text


def test_recompute_button_appends_a_snapshot_row(client_and_store, tmp_path):
    client, _store, _prop_store = client_and_store
    store = _swap_in_drift_store(tmp_path)
    csrf = _login(client)

    assert read_snapshots(store.root) == []
    client.post("/console/dashboard/recompute", headers={"X-Csrf": csrf})
    rows = read_snapshots(store.root)
    assert len(rows) == 1
    assert rows[0]["package_count"] == 9

    client.post("/console/dashboard/recompute", headers={"X-Csrf": csrf})
    assert len(read_snapshots(store.root)) == 2  # every click appends, never overwrites


def test_dashboard_after_recompute_shows_the_snapshot_in_the_trend_table(client_and_store, tmp_path):
    client, _store, _prop_store = client_and_store
    _swap_in_drift_store(tmp_path)
    csrf = _login(client)

    client.post("/console/dashboard/recompute", headers={"X-Csrf": csrf})
    r = client.get("/console/dashboard")
    assert r.status_code == 200
    assert "No snapshots recorded yet" not in r.text


def test_sweep_entry_point_also_appends_a_snapshot(tmp_path):
    """Not a console test - the weekly sweep (ap_planner_bot.sweep.run_sweep) is the other
    caller of the same trend-recorder write; covered here (rather than test_planner_bot_sweep.py)
    to keep the dashboard's whole snapshot-writing contract in one file."""
    from ap_auth.identity import Identity
    from ap_index.index_store import IndexStore
    from ap_planner_bot.sweep import run_sweep
    from _planner_bot_fake_llm import ScriptedDraftingLLMClient

    store = build_clean_corpus(tmp_path)
    index = IndexStore(tmp_path / "index")
    proposal_store = ProposalStore(tmp_path / "proposals")
    identity = Identity(id="svc.planner-sweep", roles=frozenset({Role.STANDARD_APPROVER}))

    assert read_snapshots(store.root) == []
    run_sweep(store=store, index=index, proposal_store=proposal_store, llm_client=ScriptedDraftingLLMClient(), identity=identity)
    rows = read_snapshots(store.root)
    assert len(rows) == 1
    assert rows[0]["package_count"] == 3


def test_snapshot_file_has_no_person_identifiers(client_and_store, tmp_path):
    """Task acceptance criterion: "snapshot file content has no person identifiers." Checks the
    real on-disk file the recompute button wrote, against both the fixture's known author/reviewer
    ids and the generic forbidden-key vocabulary."""
    client, _store, _prop_store = client_and_store
    store = _swap_in_drift_store(tmp_path)
    csrf = _login(client)
    client.post("/console/dashboard/recompute", headers={"X-Csrf": csrf})

    raw = (store.root / "analytics" / "snapshots.jsonl").read_text(encoding="utf-8")
    assert ANALYST.id not in raw
    assert REVIEWER.id not in raw
    for forbidden_key in ("author", "analyst_id", "reviewer_id", "owners", "owner"):
        assert f'"{forbidden_key}"' not in raw


def test_dashboard_rendered_html_has_no_person_identifiers(client_and_store, tmp_path):
    client, _store, _prop_store = client_and_store
    _swap_in_drift_store(tmp_path)
    csrf = _login(client)
    r = client.post("/console/dashboard/recompute", headers={"X-Csrf": csrf})
    assert ANALYST.id not in r.text
    assert REVIEWER.id not in r.text


def test_recompute_csrf_failure_preserves_the_latest_snapshot(client_and_store, tmp_path):
    """Regression for the CSRF-failure fragment discarding an already-recorded snapshot: a bad
    X-Csrf on a later click must not make the fragment render as if nothing had ever been
    scanned - it should keep showing the last successful recompute's numbers alongside the error
    flash, and must not append a second snapshot row."""
    client, _store, _prop_store = client_and_store
    store = _swap_in_drift_store(tmp_path)
    csrf = _login(client)

    ok = client.post("/console/dashboard/recompute", headers={"X-Csrf": csrf})
    assert ok.status_code == 200
    assert "No scan has ever run yet" not in ok.text
    assert len(read_snapshots(store.root)) == 1

    bad = client.post("/console/dashboard/recompute", headers={"X-Csrf": "wrong-token"})
    assert bad.status_code == 200
    assert "Security token expired or missing" in bad.text
    # the prior scan's tier-2 numbers must still render, not the "never scanned" empty state.
    assert "No scan has ever run yet" not in bad.text
    assert "engines_pinned" in bad.text
    # a rejected recompute must not itself append a new (unrecorded-scan) snapshot row.
    assert len(read_snapshots(store.root)) == 1
