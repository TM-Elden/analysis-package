"""§5.8 notify-agents-v0, end to end through the real FastAPI dependency wiring
(`ap_api.deps.get_proposal_workflow` -> `get_proposal_notifier`) rather than a workflow object
constructed by hand - proves `POST /proposals` and `POST /proposals/{id}/decision` actually reach
a configured notifier, not just that `ProposalWorkflow` itself calls its hooks (see
test_proposal_notify.py for that unit-level coverage). `deps.get_proposal_workflow` is
deliberately left un-overridden (mirroring `test_proposal_apply.py`'s dry-run-route test) so this
exercises the production dependency graph, not a hand-built workflow. Dry-run is run for real via
`POST /proposals/{id}/dry-run` ahead of approve (default policy keeps it required), same as the
real console/API flow."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

import ap_api.deps as deps
from ap_api.app import app
from ap_auth.roles import Role
from ap_auth.store import AuthStore
from ap_chat.telegram.client import TelegramBotClient
from ap_chat.telegram.notify import TelegramProposalNotifier
from ap_proposals.store import ProposalStore

from _planner_bot_corpus import build_clean_corpus

PROFILE = "commodity_commit_forecast"


def _diff(code: str = "API_NOTIFY_TEST_CODE") -> dict:
    return {"profile": PROFILE, "code": code, "description": "seen repeatedly in override evidence"}


@pytest.fixture()
def sent_messages():
    return []


@pytest.fixture()
def client_and_store(tmp_path, sent_messages):
    package_store = build_clean_corpus(tmp_path)
    proposal_store = ProposalStore(package_store.root)
    auth_store = AuthStore(tmp_path / "auth.sqlite3")

    def handler(request: httpx.Request) -> httpx.Response:
        sent_messages.append(dict(request.url.params))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(sent_messages)}})

    telegram_client = TelegramBotClient(token="123:test-token", transport=httpx.MockTransport(handler))
    notifier = TelegramProposalNotifier(telegram_client, chat_id=-100777)

    app.dependency_overrides[deps.get_proposal_store] = lambda: proposal_store
    app.dependency_overrides[deps.get_store] = lambda: package_store
    app.dependency_overrides[deps.get_auth_store] = lambda: auth_store
    app.dependency_overrides[deps.get_proposal_notifier] = lambda: notifier
    # get_proposal_workflow itself is NOT overridden - it must resolve get_proposal_notifier
    # through FastAPI's own dependency graph, exactly as production does.

    auth_store.create_user("sweep.bot", display_name="Sweep", roles=frozenset({Role.ANALYST}), password="pw-sweep")
    auth_store.create_user(
        "cap.tan", display_name="Captain", roles=frozenset({Role.STANDARD_APPROVER}), password="pw-cap"
    )

    client = TestClient(app, base_url="https://testserver")
    try:
        yield client, proposal_store
    finally:
        app.dependency_overrides.clear()
        proposal_store.close()
        package_store.close()
        auth_store.close()


def _login(client: TestClient, user_id: str, password: str) -> dict:
    r = client.post("/login", json={"user_id": user_id, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def _csrf_headers(login_body: dict) -> dict:
    return {"X-Csrf": login_body["csrf_token"]}


def test_post_proposals_triggers_a_real_telegram_created_message(client_and_store, sent_messages):
    client, _ = client_and_store
    creator = _login(client, "sweep.bot", "pw-sweep")

    r = client.post(
        "/proposals",
        json={"kind": "reason_code_add", "summary": "Add a reason code", "rationale": "r", "diff": _diff(), "evidence": {}},
        headers=_csrf_headers(creator),
    )
    assert r.status_code == 201, r.text
    proposal_id = r.json()["proposal_id"]

    assert len(sent_messages) == 1
    assert sent_messages[0]["chat_id"] == "-100777"
    assert proposal_id in sent_messages[0]["text"]


def test_decision_endpoint_triggers_decision_and_version_released_messages(client_and_store, sent_messages):
    client, _ = client_and_store
    creator = _login(client, "sweep.bot", "pw-sweep")
    r = client.post(
        "/proposals",
        json={"kind": "reason_code_add", "summary": "Add a reason code", "rationale": "r", "diff": _diff(), "evidence": {}},
        headers=_csrf_headers(creator),
    )
    assert r.status_code == 201, r.text
    proposal_id = r.json()["proposal_id"]
    sent_messages.clear()

    approver = _login(client, "cap.tan", "pw-cap")
    r = client.post(f"/proposals/{proposal_id}/dry-run", headers=_csrf_headers(approver))
    assert r.status_code == 200, r.text
    # Running the dry-run itself is not decision-relevant and must not notify - only create/decide do.
    assert sent_messages == []

    r = client.post(
        f"/proposals/{proposal_id}/decision",
        json={"to_status": "approved"},
        headers=_csrf_headers(approver),
    )
    assert r.status_code == 200, r.text

    assert len(sent_messages) == 2
    decision_text, version_text = sent_messages[0]["text"], sent_messages[1]["text"]
    assert proposal_id in decision_text and "approved" in decision_text
    assert PROFILE in version_text
