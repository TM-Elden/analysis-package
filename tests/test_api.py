"""Interface layer (design doc section 15): the endpoints the phase-3 console will call."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import ap_api.deps as deps
from ap_agent_tools.tools import package_create
from ap_api.app import app
from ap_store.store import PackageStore


@pytest.fixture()
def client_and_store(tmp_path):
    store = PackageStore(tmp_path / "store")
    app.dependency_overrides[deps.get_store] = lambda: store
    client = TestClient(app)
    try:
        yield client, store, tmp_path
    finally:
        app.dependency_overrides.clear()
        store.close()


ANALYST_HEADERS = {"X-Ap-Actor-Id": "tom.analyst", "X-Ap-Actor-Roles": "analyst"}
REVIEWER_HEADERS = {"X-Ap-Actor-Id": "jane.lead", "X-Ap-Actor-Roles": "reviewer"}


def test_validate_does_not_require_identity(client_and_store):
    client, _store, tmp_path = client_and_store
    pkg_dir = package_create(tmp_path / "pkg", title="API pack", analyst_id="tom.analyst")

    r = client.post("/packages/validate", json={"package_dir": str(pkg_dir)})
    assert r.status_code == 200
    assert r.json()["overall"] == "pass"


def test_publish_requires_identity(client_and_store):
    client, _store, tmp_path = client_and_store
    pkg_dir = package_create(tmp_path / "pkg", title="API pack", analyst_id="tom.analyst")

    r = client.post("/packages", json={"package_dir": str(pkg_dir)})
    assert r.status_code == 401


def test_full_publish_review_flow(client_and_store):
    client, _store, tmp_path = client_and_store
    pkg_dir = package_create(tmp_path / "pkg", title="API pack", analyst_id="tom.analyst")

    r = client.post("/packages", json={"package_dir": str(pkg_dir)}, headers=ANALYST_HEADERS)
    assert r.status_code == 201
    pkg = r.json()
    assert pkg["status"] == "draft"

    r = client.get(f"/packages/{pkg['package_id']}")
    assert r.status_code == 200
    assert r.json()["package_version"] == pkg["package_version"]

    r = client.get("/packages", params={"page": 1, "page_size": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["page_size"] == 10
    assert body["items"][0]["package_id"] == pkg["package_id"]

    r = client.post(
        f"/packages/{pkg['package_id']}/review",
        json={"package_version": pkg["package_version"], "to_status": "in_review"},
        headers=ANALYST_HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "in_review"

    # reject without a reason -> policy error (403)
    r = client.post(
        f"/packages/{pkg['package_id']}/review",
        json={"package_version": pkg["package_version"], "to_status": "rejected"},
        headers=REVIEWER_HEADERS,
    )
    assert r.status_code == 403

    # reject with a reason succeeds
    r = client.post(
        f"/packages/{pkg['package_id']}/review",
        json={"package_version": pkg["package_version"], "to_status": "rejected", "reason": "needs work"},
        headers=REVIEWER_HEADERS,
    )
    assert r.status_code == 200
    assert r.json()["status"] == "rejected"

    r = client.get(f"/packages/{pkg['package_id']}/audit", params={"version": pkg["package_version"]})
    assert r.status_code == 200
    entries = r.json()
    assert [e["to_status"] for e in entries] == ["draft", "in_review", "rejected"]
    assert entries[-1]["reason"] == "needs work"


def test_self_review_blocked_over_api(client_and_store):
    client, _store, tmp_path = client_and_store
    pkg_dir = package_create(tmp_path / "pkg", title="API pack", analyst_id="tom.analyst")
    r = client.post("/packages", json={"package_dir": str(pkg_dir)}, headers=ANALYST_HEADERS)
    pkg = r.json()

    client.post(
        f"/packages/{pkg['package_id']}/review",
        json={"package_version": pkg["package_version"], "to_status": "in_review"},
        headers=ANALYST_HEADERS,
    )
    r = client.post(
        f"/packages/{pkg['package_id']}/review",
        json={"package_version": pkg["package_version"], "to_status": "approved"},
        headers={"X-Ap-Actor-Id": "tom.analyst", "X-Ap-Actor-Roles": "reviewer"},
    )
    assert r.status_code == 403


def test_get_unknown_package_is_404(client_and_store):
    client, _store, _tmp_path = client_and_store
    r = client.get("/packages/pkg_does_not_exist")
    assert r.status_code == 404


def test_list_filters_by_status(client_and_store):
    client, _store, tmp_path = client_and_store
    pkg_dir = package_create(tmp_path / "pkg", title="API pack", analyst_id="tom.analyst")
    client.post("/packages", json={"package_dir": str(pkg_dir)}, headers=ANALYST_HEADERS)

    r = client.get("/packages", params={"status": "approved"})
    assert r.status_code == 200
    assert r.json()["total"] == 0

    r = client.get("/packages", params={"status": "draft"})
    assert r.status_code == 200
    assert r.json()["total"] == 1
