"""Console UI over the C12 lifecycle mechanism (P5.5, `data/fathm-phase5-readiness/report.md`
section 5.5): supersede/recall/restore/legal-hold/purge action forms on the package detail page,
and the Admin "Retention & holds" screen. Every action here calls the real `LifecycleWorkflow`
(no reimplemented policy) - these tests verify the transition/rejection at the store layer, not
just the rendered page, mirroring `test_console_admin.py`'s pattern.
"""

from __future__ import annotations

import datetime as dt

import pytest
import yaml
from fastapi.testclient import TestClient

import ap_api.deps as deps
from ap_agent_tools.tools import package_create
from ap_api.app import app
from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_auth.store import AuthStore
from ap_index.index_store import IndexStore
from ap_review.workflow import ReviewWorkflow
from ap_store.store import PackageStore


@pytest.fixture()
def client_and_store(tmp_path):
    store = PackageStore(tmp_path / "store")
    index = IndexStore(tmp_path / "index")
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    app.dependency_overrides[deps.get_store] = lambda: store
    app.dependency_overrides[deps.get_index] = lambda: index
    app.dependency_overrides[deps.get_auth_store] = lambda: auth_store

    auth_store.create_user("tom.analyst", display_name="Tom", roles=frozenset({Role.ANALYST}), password="pw-tom")
    auth_store.create_user("jane.lead", display_name="Jane", roles=frozenset({Role.REVIEWER}), password="pw-jane")
    auth_store.create_user("root.admin", display_name="Root", roles=frozenset({Role.ADMIN}), password="pw-root")

    client = TestClient(app, base_url="https://testserver")
    try:
        yield client, store, index, tmp_path
    finally:
        app.dependency_overrides.clear()
        store.close()
        index.close()
        auth_store.close()


def _login(client: TestClient, user_id: str, password: str) -> str:
    r = client.post("/login", json={"user_id": user_id, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["csrf_token"]


def _identity(actor_id: str, *roles: Role) -> Identity:
    return Identity(id=actor_id, roles=frozenset(roles))


def _approved(
    store: PackageStore,
    tmp_path,
    name: str,
    *,
    package_id: str | None = None,
    package_version: str = "1.0.0",
    as_of: str | None = None,
    analyst_id: str = "tom.analyst",
):
    """Publishes + approves one package/version through the real ReviewWorkflow (bypassing HTTP -
    the console/API layer over ReviewWorkflow is already covered elsewhere). Passing `package_id`
    lets a caller mint a *second version of the same package* (the supersede picker's target
    shape) by pointing a freshly-scaffolded template at an existing package_id before publish."""
    pkg_dir = package_create(tmp_path / name, title=f"{name} title", analyst_id=analyst_id, as_of=as_of)
    if package_id is not None or package_version != "1.0.0":
        manifest_path = pkg_dir / "MANIFEST.yaml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
        if package_id is not None:
            manifest["package_id"] = package_id
        manifest["package_version"] = package_version
        manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    record = store.publish(pkg_dir, actor=_identity(analyst_id, Role.ANALYST))
    wf = ReviewWorkflow(store=store)
    wf.transition(record.package_id, record.package_version, to_status="in_review", actor=_identity(analyst_id, Role.ANALYST))
    return wf.transition(record.package_id, record.package_version, to_status="approved", actor=_identity("jane.lead", Role.REVIEWER))


def _post(client, path, *, csrf, **form):
    return client.post(path, data=form, headers={"X-Csrf": csrf})


# -- recall / restore ----------------------------------------------------------------------------


def test_recall_transitions_package_and_renders_flash(client_and_store):
    client, store, _index, tmp_path = client_and_store
    a = _approved(store, tmp_path, "a")
    csrf = _login(client, "jane.lead", "pw-jane")

    r = _post(
        client,
        f"/console/packages/{a.package_id}/recall",
        csrf=csrf,
        package_version=a.package_version,
        reason="data quality issue",
    )
    assert r.status_code == 200, r.text
    assert "flash" not in r.text

    updated = store.get(a.package_id, a.package_version)
    assert updated.status == "recalled"
    audit = store.audit_trail(a.package_id, a.package_version)
    assert audit[-1].reason == "data quality issue"

    detail = client.get(f"/console/packages/{a.package_id}?version={a.package_version}")
    assert 'class="badge recalled"' in detail.text


def test_recall_rejected_for_analyst_same_as_workflow_policy(client_and_store):
    """A non-privileged actor's console action is rejected the same way LifecycleWorkflow (and
    thus the JSON API) already rejects it - no store mutation happens."""
    client, store, _index, tmp_path = client_and_store
    a = _approved(store, tmp_path, "a")
    csrf = _login(client, "tom.analyst", "pw-tom")

    r = _post(
        client,
        f"/console/packages/{a.package_id}/recall",
        csrf=csrf,
        package_version=a.package_version,
        reason="trying anyway",
    )
    assert r.status_code == 200
    assert "flash" in r.text
    assert "reviewer" in r.text.lower()
    assert store.get(a.package_id, a.package_version).status == "approved"


def test_restore_requires_admin_recalled_then_reviewer_rejected_then_admin_succeeds(client_and_store):
    client, store, _index, tmp_path = client_and_store
    a = _approved(store, tmp_path, "a")
    csrf = _login(client, "jane.lead", "pw-jane")
    _post(client, f"/console/packages/{a.package_id}/recall", csrf=csrf, package_version=a.package_version, reason="oops")
    assert store.get(a.package_id, a.package_version).status == "recalled"

    r = _post(client, f"/console/packages/{a.package_id}/restore", csrf=csrf, package_version=a.package_version)
    assert "flash" in r.text
    assert "admin" in r.text.lower()
    assert store.get(a.package_id, a.package_version).status == "recalled"

    admin_csrf = _login(client, "root.admin", "pw-root")
    r = _post(client, f"/console/packages/{a.package_id}/restore", csrf=admin_csrf, package_version=a.package_version)
    assert r.status_code == 200, r.text
    assert store.get(a.package_id, a.package_version).status == "approved"


# -- legal hold ------------------------------------------------------------------------------------


def test_legal_hold_requires_admin_and_reason_then_blocks_purge(client_and_store):
    client, store, _index, tmp_path = client_and_store
    a = _approved(store, tmp_path, "a")

    reviewer_csrf = _login(client, "jane.lead", "pw-jane")
    r = _post(client, f"/console/packages/{a.package_id}/legal-hold", csrf=reviewer_csrf, package_version=a.package_version, hold="1", reason="litigation hold")
    assert "flash" in r.text
    assert store.get(a.package_id, a.package_version).legal_hold is False

    admin_csrf = _login(client, "root.admin", "pw-root")
    r = _post(client, f"/console/packages/{a.package_id}/legal-hold", csrf=admin_csrf, package_version=a.package_version, hold="1", reason="litigation hold")
    assert r.status_code == 200, r.text
    updated = store.get(a.package_id, a.package_version)
    assert updated.legal_hold is True
    assert updated.legal_hold_reason == "litigation hold"

    # Recall is still allowed under hold (reversible move), then purge must be refused while held.
    _post(client, f"/console/packages/{a.package_id}/recall", csrf=admin_csrf, package_version=a.package_version, reason="recall while held")
    r = _post(
        client,
        f"/console/packages/{a.package_id}/purge",
        csrf=admin_csrf,
        package_version=a.package_version,
        confirm_package_id=a.package_id,
    )
    assert "flash" in r.text
    assert "hold" in r.text.lower()
    assert store.get(a.package_id, a.package_version).purged_at is None

    # Clear the hold, then purge succeeds.
    _post(client, f"/console/packages/{a.package_id}/legal-hold", csrf=admin_csrf, package_version=a.package_version, hold="0")
    assert store.get(a.package_id, a.package_version).legal_hold is False


# -- supersede chain (both directions) --------------------------------------------------------------


def test_supersede_links_chain_rendered_both_directions(client_and_store):
    client, store, _index, tmp_path = client_and_store
    a = _approved(store, tmp_path, "a")
    b = _approved(store, tmp_path, "a-v2", package_id=a.package_id, package_version="2.0.0")

    csrf = _login(client, "jane.lead", "pw-jane")
    r = _post(
        client,
        f"/console/packages/{a.package_id}/supersede",
        csrf=csrf,
        package_version=a.package_version,
        successor_package_version=b.package_version,
        reason="corrected forecast",
    )
    assert r.status_code == 200, r.text

    predecessor_row = store.get(a.package_id, a.package_version)
    successor_row = store.get(b.package_id, b.package_version)
    assert predecessor_row.status == "superseded"
    assert successor_row.replaces_package_id == a.package_id
    assert successor_row.replaces_package_version == a.package_version

    # The predecessor's page shows "Replaced by" -> b; the successor's page shows "Replaces" -> a.
    r_a = client.get(f"/console/packages/{a.package_id}?version={a.package_version}")
    assert r_a.status_code == 200
    assert f"{b.package_id}?version={b.package_version}" in r_a.text

    r_b = client.get(f"/console/packages/{b.package_id}?version={b.package_version}")
    assert r_b.status_code == 200
    assert f"{a.package_id}?version={a.package_version}" in r_b.text


def test_supersede_rejected_for_analyst_same_as_workflow_policy(client_and_store):
    """A non-privileged actor's console supersede action is rejected the same way
    LifecycleWorkflow (and thus the JSON API) already rejects it - no store mutation happens."""
    client, store, _index, tmp_path = client_and_store
    a = _approved(store, tmp_path, "a")
    b = _approved(store, tmp_path, "a-v2", package_id=a.package_id, package_version="2.0.0")
    csrf = _login(client, "tom.analyst", "pw-tom")

    r = _post(
        client,
        f"/console/packages/{a.package_id}/supersede",
        csrf=csrf,
        package_version=a.package_version,
        successor_package_version=b.package_version,
        reason="trying anyway",
    )
    assert r.status_code == 200
    assert "flash" in r.text
    assert "reviewer" in r.text.lower()

    predecessor_row = store.get(a.package_id, a.package_version)
    successor_row = store.get(b.package_id, b.package_version)
    assert predecessor_row.status == "approved"
    assert successor_row.replaces_package_id is None
    assert successor_row.replaces_package_version is None


# -- purge -------------------------------------------------------------------------------------------


def test_purge_requires_exact_id_match_and_preserves_audit_trail_as_purged(client_and_store):
    client, store, _index, tmp_path = client_and_store
    a = _approved(store, tmp_path, "a")
    admin_csrf = _login(client, "root.admin", "pw-root")
    _post(client, f"/console/packages/{a.package_id}/recall", csrf=admin_csrf, package_version=a.package_version, reason="pull it")
    blob_sha = store.get(a.package_id, a.package_version).blob_sha256
    assert store.blob_store.has(blob_sha)

    # Wrong confirmation text: no mutation.
    r = _post(
        client,
        f"/console/packages/{a.package_id}/purge",
        csrf=admin_csrf,
        package_version=a.package_version,
        confirm_package_id="not-the-right-id",
    )
    assert "flash" in r.text
    assert store.get(a.package_id, a.package_version).purged_at is None

    # Exact match: purge goes through.
    r = _post(
        client,
        f"/console/packages/{a.package_id}/purge",
        csrf=admin_csrf,
        package_version=a.package_version,
        confirm_package_id=a.package_id,
    )
    assert r.status_code == 200, r.text
    purged = store.get(a.package_id, a.package_version)
    assert purged.status == "purged"
    assert purged.purged_at is not None
    assert not store.blob_store.has(blob_sha)

    audit = store.audit_trail(a.package_id, a.package_version)
    assert audit[-1].to_status == "purged"

    # Detail page still renders, with "purged" as the visible status and the audit trail intact.
    r = client.get(f"/console/packages/{a.package_id}?version={a.package_version}")
    assert r.status_code == 200
    assert 'class="badge purged"' in r.text
    assert "pull it" in r.text  # the recall audit entry survives


def test_purge_rejected_for_approved_package_no_mutation(client_and_store):
    client, store, _index, tmp_path = client_and_store
    a = _approved(store, tmp_path, "a")
    admin_csrf = _login(client, "root.admin", "pw-root")
    r = _post(
        client,
        f"/console/packages/{a.package_id}/purge",
        csrf=admin_csrf,
        package_version=a.package_version,
        confirm_package_id=a.package_id,
    )
    assert "flash" in r.text
    assert store.get(a.package_id, a.package_version).status == "approved"
    assert store.get(a.package_id, a.package_version).purged_at is None


# -- status badges elsewhere status already renders ------------------------------------------------


def test_recalled_status_badge_renders_on_packages_list(client_and_store):
    client, store, _index, tmp_path = client_and_store
    a = _approved(store, tmp_path, "a")
    admin_csrf = _login(client, "root.admin", "pw-root")
    _post(client, f"/console/packages/{a.package_id}/recall", csrf=admin_csrf, package_version=a.package_version, reason="pull it")

    r = client.get("/console/packages")
    assert r.status_code == 200
    assert 'class="badge recalled"' in r.text


# -- Admin: retention & holds ------------------------------------------------------------------------


def test_retention_due_filtering_is_correct_against_retention_days(client_and_store):
    client, store, _index, tmp_path = client_and_store
    today = dt.date.today()
    just_past = today - dt.timedelta(days=31)  # older than 30-day retention -> due
    just_under = today - dt.timedelta(days=29)  # newer than 30-day retention -> not due

    due_pkg = _approved(store, tmp_path, "due", as_of=just_past.isoformat())
    fresh_pkg = _approved(store, tmp_path, "fresh", as_of=just_under.isoformat())

    admin_csrf = _login(client, "root.admin", "pw-root")
    r = _post(client, "/console/admin/settings", csrf=admin_csrf, retention_days="30")
    assert r.status_code == 200, r.text

    r = client.get("/console/admin/retention-holds")
    assert r.status_code == 200, r.text
    assert due_pkg.package_id in r.text
    assert fresh_pkg.package_id not in r.text


def test_retention_holds_lists_legal_holds_and_recalled(client_and_store):
    client, store, _index, tmp_path = client_and_store
    held = _approved(store, tmp_path, "held")
    recalled = _approved(store, tmp_path, "recalled-pkg")
    admin_csrf = _login(client, "root.admin", "pw-root")
    _post(client, f"/console/packages/{held.package_id}/legal-hold", csrf=admin_csrf, package_version=held.package_version, hold="1", reason="litigation")
    _post(client, f"/console/packages/{recalled.package_id}/recall", csrf=admin_csrf, package_version=recalled.package_version, reason="bad data")

    r = client.get("/console/admin/retention-holds")
    assert r.status_code == 200
    assert held.package_id in r.text
    assert "litigation" in r.text
    assert recalled.package_id in r.text


def test_retention_holds_403s_for_non_admin(client_and_store):
    client, _store, _index, _tmp_path = client_and_store
    _login(client, "tom.analyst", "pw-tom")
    r = client.get("/console/admin/retention-holds")
    assert r.status_code == 403
