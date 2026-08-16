"""POST /chat/manager wired through the real FastAPI app (identity_from_request, get_index,
get_store, get_llm_client) - see test_api.py's module docstring for why base_url must be https.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import ap_api.deps as deps
from ap_api.app import app
from ap_auth.roles import Role
from ap_auth.store import AuthStore

from _manager_bot_corpus import build_corpus
from _manager_bot_fake_llm import ScriptedLLMClient


@pytest.fixture()
def client_and_corpus(tmp_path):
    corpus = build_corpus(tmp_path)
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    auth_store.create_user("planner.api", display_name="Planner", roles=frozenset({Role.TEAM_READER}), password="pw")

    app.dependency_overrides[deps.get_store] = lambda: corpus.store
    app.dependency_overrides[deps.get_index] = lambda: corpus.index
    app.dependency_overrides[deps.get_auth_store] = lambda: auth_store
    app.dependency_overrides[deps.get_llm_client] = lambda: ScriptedLLMClient()

    client = TestClient(app, base_url="https://testserver")
    try:
        yield client, corpus
    finally:
        app.dependency_overrides.clear()
        auth_store.close()


def _login(client: TestClient) -> dict:
    r = client.post("/login", json={"user_id": "planner.api", "password": "pw"})
    assert r.status_code == 200, r.text
    return {"X-Csrf": r.json()["csrf_token"]}


def test_chat_manager_requires_auth(client_and_corpus):
    client, _corpus = client_and_corpus
    r = client.post("/chat/manager", json={"question": "Why did we hold ACME BBU-100?"})
    assert r.status_code == 401


def test_chat_manager_returns_a_grounded_answer_with_citations(client_and_corpus):
    client, corpus = client_and_corpus
    headers = _login(client)

    r = client.post("/chat/manager", json={"question": "Why did we hold ACME BBU-100?"}, headers=headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refused"] is False
    assert body["citations"]
    assert body["citations"][0]["package_id"] == corpus.package_ids["acme_bbu"]


def test_chat_manager_refuses_when_nothing_matches(client_and_corpus):
    client, _corpus = client_and_corpus
    headers = _login(client)

    r = client.post(
        "/chat/manager", json={"question": "What override applies to SPACELY SPROCKETS COG-9000?"}, headers=headers
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["refused"] is True
    assert body["citations"] == []
