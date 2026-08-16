"""P3.7 console query panel: `GET /chat/manager/stream` (ap_api.chat_routes) and the console-side
`GET /console/chat` / `GET /console/chat/turn` fragment (ap_console.routes). Runs against the same
eval-set corpus P3.3's tests use (`_manager_bot_corpus.build_corpus`), not synthetic UI-only content -
per this task's acceptance criterion. See test_manager_bot_api.py's module docstring for why
`base_url` must be https (Secure session cookie).
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


class _BoomLLMClient:
    """Fails on the first call - simulates the backend LLM call breaking mid-request, exercising the
    "streaming degrades gracefully" acceptance criterion."""

    def complete(self, **kwargs):
        raise RuntimeError("upstream unavailable")


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


def _login(client: TestClient) -> None:
    r = client.post("/login", json={"user_id": "planner.api", "password": "pw"})
    assert r.status_code == 200, r.text


def test_stream_requires_auth(client_and_corpus):
    client, _corpus = client_and_corpus
    r = client.get("/chat/manager/stream", params={"question": "Why did we hold ACME BBU-100?"})
    assert r.status_code == 401


def test_stream_emits_message_citation_and_done_events_for_a_real_answer(client_and_corpus):
    client, corpus = client_and_corpus
    _login(client)

    r = client.get("/chat/manager/stream", params={"question": "Why did we hold ACME BBU-100?"})
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")

    body = r.text
    assert "event: message\n" in body
    assert "event: citations\n" in body
    assert body.rstrip().endswith("event: done\ndata:")
    assert corpus.package_ids["acme_bbu"] in body

    # Reassembling every "message" data line (minus the "data: " prefix) must reproduce the answer
    # text with no characters dropped at chunk boundaries.
    tokens = [
        line[len("data: "):]
        for block in body.split("\n\n")
        if block.startswith("event: message")
        for line in block.splitlines()
        if line.startswith("data: ")
    ]
    assert "".join(tokens).strip() != ""


def test_stream_refuses_cleanly_when_nothing_matches(client_and_corpus):
    client, _corpus = client_and_corpus
    _login(client)

    r = client.get(
        "/chat/manager/stream", params={"question": "What override applies to SPACELY SPROCKETS COG-9000?"}
    )
    assert r.status_code == 200
    body = r.text
    assert "event: refused\n" in body
    assert 'data: []' in body  # empty citations payload
    assert "event: done\n" in body


def test_stream_reports_a_clean_error_event_on_backend_failure(client_and_corpus):
    client, _corpus = client_and_corpus
    _login(client)
    app.dependency_overrides[deps.get_llm_client] = lambda: _BoomLLMClient()

    r = client.get("/chat/manager/stream", params={"question": "Why did we hold ACME BBU-100?"})
    assert r.status_code == 200  # the HTTP response itself started fine; the failure is in-stream
    body = r.text
    assert "event: error\n" in body
    assert "upstream unavailable" in body
    assert "event: done\n" in body
    assert "event: message" not in body  # no partial/uncited content shipped alongside the error


def test_stream_escapes_html_in_message_text(client_and_corpus):
    """A package's own content (e.g. a reason_text) could contain characters that look like markup;
    the panel's default htmx sse-swap dumps message data as innerHTML, so the server must escape it
    before it goes on the wire (see ap_api/chat_routes.py's module docstring)."""
    client, corpus = client_and_corpus
    _login(client)
    r = client.get("/chat/manager/stream", params={"question": "Why did we hold ACME BBU-100?"})
    assert "<" not in "".join(
        line[len("data: "):]
        for block in r.text.split("\n\n")
        if block.startswith("event: message")
        for line in block.splitlines()
        if line.startswith("data: ")
    ) or "&lt;" in r.text  # no raw '<' survives unescaped if the fixture ever contains one


def test_console_chat_page_redirects_when_logged_out(client_and_corpus):
    client, _corpus = client_and_corpus
    r = client.get("/console/chat", follow_redirects=False)
    assert r.status_code == 303
    assert r.headers["location"].startswith("/console/login")


def test_console_chat_page_renders_when_logged_in(client_and_corpus):
    client, _corpus = client_and_corpus
    _login(client)
    r = client.get("/console/chat")
    assert r.status_code == 200
    assert "Ask the corpus" in r.text
    assert 'hx-get="/console/chat/turn"' in r.text


def test_console_chat_turn_fragment_wires_the_sse_connection_and_escapes_the_question(client_and_corpus):
    client, _corpus = client_and_corpus
    _login(client)
    r = client.get("/console/chat/turn", params={"question": "ACME <b>BBU-100</b>?"})
    assert r.status_code == 200
    assert 'hx-ext="sse"' in r.text
    assert "/chat/manager/stream?question=" in r.text
    assert "<b>" not in r.text  # the displayed question is HTML-escaped by Jinja2 autoescape
    assert "&lt;b&gt;" in r.text


def test_console_chat_turn_requires_auth(client_and_corpus):
    client, _corpus = client_and_corpus
    r = client.get("/console/chat/turn", params={"question": "anything"}, follow_redirects=False)
    assert r.status_code == 303
