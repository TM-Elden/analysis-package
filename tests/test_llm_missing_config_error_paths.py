"""D5 acceptance test (`data/fathm-mvp-review/report.md` section 5 item 5, must-fix): a server
started with ANTHROPIC_API_KEY (or AP_MANAGER_BOT_MODEL, D6) unset must not turn every LLM-backed
route into a raw 500 out of FastAPI dependency resolution. All three call sites that depend on
`ap_api.deps.get_llm_client` are exercised here against a *real* `AnthropicHTTPClient` (not a fake),
constructed exactly the way `get_llm_client` constructs it - so this proves the fix at the actual
dependency-injection seam, not just at the `AnthropicHTTPClient`/`LLMClient` unit level
(`test_manager_bot_llm_client.py` covers that separately):

- `GET /chat/manager/stream` (the Ask panel's SSE route) - must emit the existing clean `error`
  SSE event, not hang or 500.
- `POST /chat/manager` (the JSON chat route) - must return a clean 4xx/5xx JSON body via
  `HTTPException`, not an unhandled exception.
- `POST /console/standard/sweep` (the "Run planner sweep" button) - must re-render the queue
  partial with an inline `.flash` error, the same pattern every other policy rejection on that
  route already uses, not a raw 500.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

import ap_api.deps as deps
from ap_api.app import app
from ap_auth.roles import Role
from ap_auth.store import AuthStore
from ap_index.index_store import IndexStore
from ap_manager_bot.llm_client import AnthropicHTTPClient
from ap_proposals.store import ProposalStore
from ap_store.store import PackageStore

from _manager_bot_corpus import build_corpus


@pytest.fixture()
def client_and_corpus(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("AP_MANAGER_BOT_MODEL", raising=False)

    corpus = build_corpus(tmp_path)
    proposal_store = ProposalStore(corpus.store.root)
    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    auth_store.create_user("planner.api", display_name="Planner", roles=frozenset({Role.ANALYST}), password="pw")

    app.dependency_overrides[deps.get_store] = lambda: corpus.store
    app.dependency_overrides[deps.get_index] = lambda: corpus.index
    app.dependency_overrides[deps.get_auth_store] = lambda: auth_store
    app.dependency_overrides[deps.get_proposal_store] = lambda: proposal_store
    # The real construction path `get_llm_client` uses - no api_key/model kwargs, so it falls back
    # to the (unset, per the fixture's monkeypatch above) env vars, exactly like a misconfigured
    # deployment would.
    app.dependency_overrides[deps.get_llm_client] = lambda: AnthropicHTTPClient()

    client = TestClient(app, base_url="https://testserver")
    try:
        yield client, corpus
    finally:
        app.dependency_overrides.clear()
        auth_store.close()
        proposal_store.close()


def _login(client: TestClient) -> str:
    r = client.post("/login", json={"user_id": "planner.api", "password": "pw"})
    assert r.status_code == 200, r.text
    return r.json()["csrf_token"]


def test_sse_stream_emits_a_clean_error_event_not_a_500(client_and_corpus):
    client, _corpus = client_and_corpus
    _login(client)

    r = client.get("/chat/manager/stream", params={"question": "Why did we hold ACME BBU-100?"})
    assert r.status_code == 200  # the response itself starts fine; the failure is in-stream
    assert "event: error\n" in r.text
    assert "ANTHROPIC_API_KEY" in r.text
    assert "event: done\n" in r.text
    assert "event: message" not in r.text


def test_json_chat_route_returns_a_clean_502_not_a_500(client_and_corpus):
    client, _corpus = client_and_corpus
    csrf = _login(client)

    r = client.post(
        "/chat/manager", json={"question": "Why did we hold ACME BBU-100?"}, headers={"X-Csrf": csrf}
    )
    assert r.status_code == 502
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_sweep_button_renders_an_inline_flash_error_not_a_500(client_and_corpus):
    client, _corpus = client_and_corpus
    csrf = _login(client)

    r = client.post("/console/standard/sweep", data={"status": "pending_hitl"}, headers={"X-Csrf": csrf})
    assert r.status_code == 200
    assert "flash" in r.text
    assert "ANTHROPIC_API_KEY" in r.text
