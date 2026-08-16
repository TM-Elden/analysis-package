"""Manager console (P3.4): login redirect enforcement, filterable package list, package detail,
and the embedded gate report - rendered for at least the gold-pack example package (per the task's
acceptance bar). `base_url="https://testserver"` is required for the same reason test_api.py needs
it: `POST /login` sets a `Secure` cookie.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import ap_api.deps as deps
from ap_api.app import app
from ap_auth.roles import Role
from ap_auth.store import AuthStore
from ap_store.store import PackageStore
from conftest import EXAMPLE_PACKAGE


@pytest.fixture()
def client_and_store(tmp_path):
    store = PackageStore(tmp_path / "store")
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    app.dependency_overrides[deps.get_store] = lambda: store
    app.dependency_overrides[deps.get_auth_store] = lambda: auth_store

    auth_store.create_user("tom.analyst", display_name="Tom", roles=frozenset({Role.ANALYST}), password="pw-tom")

    client = TestClient(app, base_url="https://testserver")
    try:
        yield client, store, auth_store
    finally:
        app.dependency_overrides.clear()
        store.close()
        auth_store.close()


def _login(client: TestClient) -> None:
    r = client.post("/login", json={"user_id": "tom.analyst", "password": "pw-tom"})
    assert r.status_code == 200, r.text


def _publish_example(store: PackageStore):
    from ap_auth.identity import Identity

    actor = Identity(id="tom.analyst", roles=frozenset({Role.ANALYST}))
    return store.publish(EXAMPLE_PACKAGE, actor=actor)


@pytest.mark.parametrize(
    "path",
    ["/console/packages", "/console/packages/commodity-commit-v1"],
)
def test_logged_out_console_page_redirects_to_login(client_and_store, path):
    client, _store, _auth = client_and_store
    r = client.get(path, follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/console/login")


def test_login_page_renders_without_auth(client_and_store):
    client, _store, _auth = client_and_store
    r = client.get("/console/login")
    assert r.status_code == 200
    assert "Log in" in r.text


def test_package_list_renders_published_package(client_and_store):
    client, store, _auth = client_and_store
    record = _publish_example(store)
    _login(client)

    r = client.get("/console/packages")
    assert r.status_code == 200
    assert record.package_id in r.text
    assert record.title in r.text
    assert "wordmark" in r.text  # brand wordmark present


def test_package_list_filter_partial_respects_status(client_and_store):
    client, store, _auth = client_and_store
    record = _publish_example(store)
    _login(client)

    r = client.get("/console/packages/table", params={"status": "draft"})
    assert r.status_code == 200
    assert record.package_id in r.text

    r = client.get("/console/packages/table", params={"status": "approved"})
    assert r.status_code == 200
    assert record.package_id not in r.text
    assert "No packages match" in r.text


def test_package_detail_renders_manifest_summary_and_owners(client_and_store):
    client, store, _auth = client_and_store
    record = _publish_example(store)
    _login(client)

    r = client.get(f"/console/packages/{record.package_id}")
    assert r.status_code == 200
    assert record.package_id in r.text
    assert record.title in r.text
    assert record.status in r.text
    assert (record.analyst_id or "") in r.text


def test_package_detail_missing_package_is_404(client_and_store):
    client, _store, _auth = client_and_store
    _login(client)
    r = client.get("/console/packages/does-not-exist")
    assert r.status_code == 404


def test_gate_report_embeds_real_check_results(client_and_store):
    client, store, _auth = client_and_store
    record = _publish_example(store)
    _login(client)

    r = client.get(f"/console/packages/{record.package_id}/gate-report", params={"version": record.package_version})
    assert r.status_code == 200
    assert "fathm L1 report" in r.text
    assert "PASS" in r.text or "FAIL" in r.text


def test_logout_link_target_revokes_session(client_and_store):
    client, store, auth_store = client_and_store
    _publish_example(store)
    body_r = client.post("/login", json={"user_id": "tom.analyst", "password": "pw-tom"})
    csrf = body_r.json()["csrf_token"]

    r = client.post("/logout", headers={"X-Csrf": csrf})
    assert r.status_code == 200

    r = client.get("/console/packages", follow_redirects=False)
    assert r.status_code == 303
