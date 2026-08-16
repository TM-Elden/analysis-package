"""Interface layer (design doc section 15): the endpoints the phase-3 console will call, now behind
real C11 auth (session cookies + service-account bearer tokens) - see ap_api/deps.py and
ap_api/auth_routes.py. `base_url="https://testserver"` is required: login sets a `Secure` cookie,
which httpx's cookie jar (TestClient's transport) only stores/replays over an https:// origin - see
ap_auth.store / ap_api.auth_routes module docstrings.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import ap_api.deps as deps
from ap_agent_tools.tools import package_create
from ap_api.app import app
from ap_auth.roles import Role
from ap_auth.store import AuthStore
from ap_store.store import PackageStore


@pytest.fixture()
def client_and_store(tmp_path):
    store = PackageStore(tmp_path / "store")
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    app.dependency_overrides[deps.get_store] = lambda: store
    app.dependency_overrides[deps.get_auth_store] = lambda: auth_store

    auth_store.create_user("tom.analyst", display_name="Tom", roles=frozenset({Role.ANALYST}), password="pw-tom")
    auth_store.create_user("jane.lead", display_name="Jane", roles=frozenset({Role.REVIEWER}), password="pw-jane")
    auth_store.create_user("ro.reader", display_name="Reader", roles=frozenset({Role.TEAM_READER}), password="pw-ro")

    client = TestClient(app, base_url="https://testserver")
    try:
        yield client, store, auth_store, tmp_path
    finally:
        app.dependency_overrides.clear()
        store.close()
        auth_store.close()


def _login(client: TestClient, user_id: str, password: str) -> dict:
    r = client.post("/login", json={"user_id": user_id, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _csrf_headers(login_body: dict) -> dict:
    return {"X-Csrf": login_body["csrf_token"]}


def test_login_wrong_password_is_401(client_and_store):
    client, *_ = client_and_store
    r = client.post("/login", json={"user_id": "tom.analyst", "password": "wrong"})
    assert r.status_code == 401
    assert "ap_session" not in r.cookies


def test_login_sets_session_cookie_and_returns_csrf_token(client_and_store):
    client, *_ = client_and_store
    body = _login(client, "tom.analyst", "pw-tom")
    assert body["user_id"] == "tom.analyst"
    assert body["roles"] == ["analyst"]
    assert body["csrf_token"]
    assert "ap_session" in client.cookies


def test_no_session_no_bearer_is_401(client_and_store):
    client, _store, _auth, tmp_path = client_and_store
    pkg_dir = package_create(tmp_path / "pkg", title="API pack", analyst_id="tom.analyst")

    r = client.post("/packages/validate", json={"package_dir": str(pkg_dir)})
    assert r.status_code == 401


def test_expired_session_is_401(client_and_store):
    client, _store, auth_store, tmp_path = client_and_store
    import datetime as dt

    raw = auth_store.create_session("tom.analyst", ttl=dt.timedelta(seconds=-1))
    client.cookies.set("ap_session", raw, domain="testserver.local")
    pkg_dir = package_create(tmp_path / "pkg", title="API pack", analyst_id="tom.analyst")
    r = client.post("/packages/validate", json={"package_dir": str(pkg_dir)}, headers={"X-Csrf": "irrelevant"})
    assert r.status_code == 401


def test_state_changing_request_without_csrf_header_is_403(client_and_store):
    client, _store, _auth, tmp_path = client_and_store
    _login(client, "tom.analyst", "pw-tom")
    pkg_dir = package_create(tmp_path / "pkg", title="API pack", analyst_id="tom.analyst")

    r = client.post("/packages", json={"package_dir": str(pkg_dir)})
    assert r.status_code == 403


def test_reader_cannot_publish(client_and_store):
    client, _store, _auth, tmp_path = client_and_store
    body = _login(client, "ro.reader", "pw-ro")
    pkg_dir = package_create(tmp_path / "pkg", title="API pack", analyst_id="tom.analyst")

    r = client.post("/packages", json={"package_dir": str(pkg_dir)}, headers=_csrf_headers(body))
    assert r.status_code == 403


def test_full_publish_review_flow_via_session_cookies(client_and_store):
    client, _store, _auth, tmp_path = client_and_store
    pkg_dir = package_create(tmp_path / "pkg", title="API pack", analyst_id="tom.analyst")

    analyst_login = _login(client, "tom.analyst", "pw-tom")
    r = client.post("/packages", json={"package_dir": str(pkg_dir)}, headers=_csrf_headers(analyst_login))
    assert r.status_code == 201, r.text
    pkg = r.json()
    assert pkg["status"] == "draft"

    r = client.get(f"/packages/{pkg['package_id']}")
    assert r.status_code == 200
    assert r.json()["package_version"] == pkg["package_version"]

    r = client.get("/packages", params={"page": 1, "page_size": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["items"][0]["package_id"] == pkg["package_id"]

    r = client.post(
        f"/packages/{pkg['package_id']}/review",
        json={"package_version": pkg["package_version"], "to_status": "in_review"},
        headers=_csrf_headers(analyst_login),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "in_review"

    client.post("/logout", headers=_csrf_headers(analyst_login))

    reviewer_login = _login(client, "jane.lead", "pw-jane")

    # reject without a reason -> policy error (403)
    r = client.post(
        f"/packages/{pkg['package_id']}/review",
        json={"package_version": pkg["package_version"], "to_status": "rejected"},
        headers=_csrf_headers(reviewer_login),
    )
    assert r.status_code == 403

    # reject with a reason succeeds
    r = client.post(
        f"/packages/{pkg['package_id']}/review",
        json={"package_version": pkg["package_version"], "to_status": "rejected", "reason": "needs work"},
        headers=_csrf_headers(reviewer_login),
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"

    r = client.get(f"/packages/{pkg['package_id']}/audit", params={"version": pkg["package_version"]})
    assert r.status_code == 200
    entries = r.json()
    assert [e["to_status"] for e in entries] == ["draft", "in_review", "rejected"]
    assert entries[-1]["reason"] == "needs work"


def test_logout_revokes_the_session(client_and_store):
    client, _store, _auth, tmp_path = client_and_store
    login_body = _login(client, "tom.analyst", "pw-tom")

    r = client.post("/logout", headers=_csrf_headers(login_body))
    assert r.status_code == 200

    pkg_dir = package_create(tmp_path / "pkg", title="API pack", analyst_id="tom.analyst")
    r = client.post("/packages/validate", json={"package_dir": str(pkg_dir)}, headers=_csrf_headers(login_body))
    assert r.status_code == 401


def test_analyst_cannot_approve_own_package_unless_policy_allows(client_and_store):
    client, _store, auth_store, tmp_path = client_and_store
    # Dual-hat user (both analyst and reviewer roles) isolates the self-review *policy* check
    # (ReviewPolicy.allow_self_review) from the plain "requires reviewer role" check already
    # covered by test_reader_cannot_publish/test_full_publish_review_flow_via_session_cookies.
    auth_store.create_user(
        "dual.hat", display_name="Dual Hat", roles=frozenset({Role.ANALYST, Role.REVIEWER}), password="pw-dual"
    )
    pkg_dir = package_create(tmp_path / "pkg", title="API pack", analyst_id="dual.hat")

    login_body = _login(client, "dual.hat", "pw-dual")
    r = client.post("/packages", json={"package_dir": str(pkg_dir)}, headers=_csrf_headers(login_body))
    pkg = r.json()

    client.post(
        f"/packages/{pkg['package_id']}/review",
        json={"package_version": pkg["package_version"], "to_status": "in_review"},
        headers=_csrf_headers(login_body),
    )

    # allow_self_review defaults to False - a distinct reviewer identity is required even though
    # dual.hat holds the reviewer role.
    r = client.post(
        f"/packages/{pkg['package_id']}/review",
        json={"package_version": pkg["package_version"], "to_status": "approved"},
        headers=_csrf_headers(login_body),
    )
    assert r.status_code == 403


def test_service_bearer_token_works_for_ci_style_callers(client_and_store):
    client, _store, auth_store, tmp_path = client_and_store
    auth_store.create_user("ci.bot", display_name="CI bot", roles=frozenset({Role.ANALYST}), password=None)
    raw_token = auth_store.create_service_token("ci.bot")

    pkg_dir = package_create(tmp_path / "pkg", title="API pack", analyst_id="ci.bot")
    # No CSRF header needed for bearer-token callers - see ap_api/deps.py::identity_from_request.
    r = client.post(
        "/packages",
        json={"package_dir": str(pkg_dir)},
        headers={"Authorization": f"Bearer {raw_token}"},
    )
    assert r.status_code == 201, r.text
    assert r.json()["published_by_id"] == "ci.bot"


def test_invalid_bearer_token_is_401(client_and_store):
    client, _store, _auth, tmp_path = client_and_store
    pkg_dir = package_create(tmp_path / "pkg", title="API pack", analyst_id="tom.analyst")
    r = client.post(
        "/packages",
        json={"package_dir": str(pkg_dir)},
        headers={"Authorization": "Bearer not-a-real-token"},
    )
    assert r.status_code == 401


def test_get_unknown_package_is_404(client_and_store):
    client, _store, _auth, _tmp_path = client_and_store
    _login(client, "ro.reader", "pw-ro")
    r = client.get("/packages/pkg_does_not_exist")
    assert r.status_code == 404


def test_list_filters_by_status(client_and_store):
    client, _store, _auth, tmp_path = client_and_store
    pkg_dir = package_create(tmp_path / "pkg", title="API pack", analyst_id="tom.analyst")
    login_body = _login(client, "tom.analyst", "pw-tom")
    client.post("/packages", json={"package_dir": str(pkg_dir)}, headers=_csrf_headers(login_body))

    r = client.get("/packages", params={"status": "approved"})
    assert r.status_code == 200
    assert r.json()["total"] == 0

    r = client.get("/packages", params={"status": "draft"})
    assert r.status_code == 200
    assert r.json()["total"] == 1
