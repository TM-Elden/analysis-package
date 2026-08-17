"""§5.8 notify-agents-v0: `ProposalWorkflow`'s notifier hook fires `proposal.created`,
`proposal.decision`, and `proposal.version_released` at the right points, never blocks the
workflow on a failing notifier, and the concrete `TelegramProposalNotifier` sends the right
Telegram Bot API calls (real request shaping against `httpx.MockTransport`, same seam pattern as
`test_chat_telegram_client.py`). See CLAUDE.md's notify-v0 note and
`data/fathm-phase4-readiness/report.md` §5.8 in the firstmate repo for the design."""

from __future__ import annotations

import httpx
import pytest

from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_chat.telegram.client import TelegramBotClient
from ap_chat.telegram.notify import TelegramProposalNotifier, notifier_from_env
from ap_proposals.policy import ProposalPolicy
from ap_proposals.store import ProposalStore
from ap_proposals.workflow import ProposalWorkflow

SWEEP = Identity(id="sweep.bot", roles=frozenset({Role.ANALYST}))
CAPTAIN = Identity(id="cap.tan", roles=frozenset({Role.STANDARD_APPROVER}))

_NO_DRY_RUN_REQUIRED = ProposalPolicy(require_dry_run_for_declarative=False)


class _RecordingNotifier:
    def __init__(self):
        self.calls: list[tuple] = []

    def notify_created(self, record):
        self.calls.append(("created", record.proposal_id))

    def notify_decision(self, record, *, from_status):
        self.calls.append(("decision", record.proposal_id, from_status, record.status))

    def notify_version_released(self, record, *, profile_name, version):
        self.calls.append(("version_released", record.proposal_id, profile_name, version))


class _BlowingUpNotifier:
    def notify_created(self, record):
        raise RuntimeError("telegram is down")

    def notify_decision(self, record, *, from_status):
        raise RuntimeError("telegram is down")

    def notify_version_released(self, record, *, profile_name, version):
        raise RuntimeError("telegram is down")


def _profile_change_diff(code: str = "SUPPLIER_CHANGE") -> dict:
    return {
        "profile": "commodity",
        "file": "reason_codes.json",
        "before": {"codes": []},
        "after": {"codes": [code]},
    }


def _standard_change_diff() -> dict:
    return {"target": "STANDARD.md", "description": "clarify wording that's ambiguous today"}


def _workflow(tmp_path, notifier=None) -> tuple[ProposalStore, ProposalWorkflow]:
    store = ProposalStore(tmp_path / "store")
    return store, ProposalWorkflow(store=store, policy=_NO_DRY_RUN_REQUIRED, notifier=notifier)


def test_create_fires_proposal_created(tmp_path):
    notifier = _RecordingNotifier()
    _, wf = _workflow(tmp_path, notifier)
    record = wf.create(
        kind="profile_change",
        summary="Add SUPPLIER_CHANGE reason code",
        rationale="seen repeatedly",
        diff=_profile_change_diff(),
        evidence={"package_ids": ["pkg-1"]},
        actor=SWEEP,
    )
    assert notifier.calls == [("created", record.proposal_id)]


def test_decide_reject_fires_decision_only(tmp_path):
    notifier = _RecordingNotifier()
    _, wf = _workflow(tmp_path, notifier)
    record = wf.create(
        kind="profile_change",
        summary="Add SUPPLIER_CHANGE",
        rationale="seen repeatedly",
        diff=_profile_change_diff(),
        evidence={"package_ids": ["pkg-1"]},
        actor=SWEEP,
    )
    notifier.calls.clear()

    wf.decide(record.proposal_id, to_status="rejected", actor=CAPTAIN, reason="not needed")

    assert len(notifier.calls) == 1
    kind, proposal_id, from_status, status = notifier.calls[0]
    assert (kind, from_status, status) == ("decision", "pending_hitl", "rejected")
    assert proposal_id == record.proposal_id


def test_decide_approve_declarative_fires_decision_then_version_released(tmp_path):
    notifier = _RecordingNotifier()
    _, wf = _workflow(tmp_path, notifier)
    record = wf.create(
        kind="profile_change",
        summary="Add SUPPLIER_CHANGE",
        rationale="seen repeatedly",
        diff=_profile_change_diff(),
        evidence={"package_ids": ["pkg-1"]},
        actor=SWEEP,
    )
    notifier.calls.clear()

    approved = wf.decide(record.proposal_id, to_status="approved", actor=CAPTAIN)

    assert [c[0] for c in notifier.calls] == ["decision", "version_released"]
    decision_call, version_call = notifier.calls
    assert decision_call[1:] == (record.proposal_id, "pending_hitl", "approved")
    assert version_call == ("version_released", record.proposal_id, "commodity", approved.applied_version)


def test_decide_approve_code_kind_fires_decision_only_no_version_released(tmp_path):
    notifier = _RecordingNotifier()
    _, wf = _workflow(tmp_path, notifier)
    record = wf.create(
        kind="standard_change",
        summary="Clarify wording",
        rationale="ambiguous",
        diff=_standard_change_diff(),
        evidence={"package_ids": ["pkg-1"]},
        actor=SWEEP,
    )
    notifier.calls.clear()

    wf.decide(record.proposal_id, to_status="approved", actor=CAPTAIN)

    assert [c[0] for c in notifier.calls] == ["decision"]


def test_notifier_failure_never_blocks_the_decision(tmp_path):
    """§5.8: "notification is a courtesy, not the contract" - a notifier raising must not stop the
    real state transition or propagate out of decide/create."""
    _, wf = _workflow(tmp_path, _BlowingUpNotifier())
    record = wf.create(
        kind="profile_change",
        summary="Add SUPPLIER_CHANGE",
        rationale="seen repeatedly",
        diff=_profile_change_diff(),
        evidence={"package_ids": ["pkg-1"]},
        actor=SWEEP,
    )
    approved = wf.decide(record.proposal_id, to_status="approved", actor=CAPTAIN)
    assert approved.status == "approved"
    assert approved.applied_version is not None


def test_no_notifier_configured_is_a_silent_no_op(tmp_path):
    _, wf = _workflow(tmp_path, notifier=None)
    record = wf.create(
        kind="profile_change",
        summary="Add SUPPLIER_CHANGE",
        rationale="seen repeatedly",
        diff=_profile_change_diff(),
        evidence={"package_ids": ["pkg-1"]},
        actor=SWEEP,
    )
    approved = wf.decide(record.proposal_id, to_status="approved", actor=CAPTAIN)
    assert approved.status == "approved"


# --- TelegramProposalNotifier: real Telegram Bot API request shaping ------------------------


def _telegram(handler) -> TelegramBotClient:
    return TelegramBotClient(token="123:test-token", transport=httpx.MockTransport(handler))


def test_telegram_notifier_sends_proposal_created_to_the_configured_chat(tmp_path):
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    store, wf = _workflow(tmp_path)
    telegram_notifier = TelegramProposalNotifier(_telegram(handler), chat_id=-100123)
    wf.notifier = telegram_notifier

    record = wf.create(
        kind="profile_change",
        summary="Add SUPPLIER_CHANGE reason code after repeated overrides",
        rationale="seen repeatedly",
        diff=_profile_change_diff(),
        evidence={"package_ids": ["pkg-1"]},
        actor=SWEEP,
    )

    assert "sendMessage" in captured["url"]
    assert captured["params"]["chat_id"] == "-100123"
    assert record.proposal_id in captured["params"]["text"]
    assert "profile_change" in captured["params"]["text"]


def test_telegram_notifier_sends_decision_and_version_released_messages(tmp_path):
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(dict(request.url.params))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(sent)}})

    store, wf = _workflow(tmp_path)
    wf.notifier = TelegramProposalNotifier(_telegram(handler), chat_id=42)

    record = wf.create(
        kind="profile_change",
        summary="Add SUPPLIER_CHANGE",
        rationale="seen repeatedly",
        diff=_profile_change_diff(),
        evidence={"package_ids": ["pkg-1"]},
        actor=SWEEP,
    )
    sent.clear()

    approved = wf.decide(record.proposal_id, to_status="approved", actor=CAPTAIN)

    assert len(sent) == 2
    decision_text, version_text = sent[0]["text"], sent[1]["text"]
    assert record.proposal_id in decision_text
    assert "approved" in decision_text
    assert "cap.tan" in decision_text
    assert "commodity" in version_text
    assert approved.applied_version in version_text
    assert all(p["chat_id"] == "42" for p in sent)


def test_telegram_notifier_rejection_message_includes_reason(tmp_path):
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(dict(request.url.params))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": len(sent)}})

    _, wf = _workflow(tmp_path)
    wf.notifier = TelegramProposalNotifier(_telegram(handler), chat_id=42)
    record = wf.create(
        kind="profile_change",
        summary="Add SUPPLIER_CHANGE",
        rationale="seen repeatedly",
        diff=_profile_change_diff(),
        evidence={"package_ids": ["pkg-1"]},
        actor=SWEEP,
    )
    sent.clear()

    wf.decide(record.proposal_id, to_status="rejected", actor=CAPTAIN, reason="too niche to codify")

    assert len(sent) == 1
    assert "too niche to codify" in sent[0]["text"]
    assert "rejected" in sent[0]["text"]


def test_notifier_from_env_returns_none_when_unconfigured(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("AP_CHAT_NOTIFY_CHAT_ID", raising=False)
    assert notifier_from_env() is None


def test_notifier_from_env_returns_none_when_only_token_set(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.delenv("AP_CHAT_NOTIFY_CHAT_ID", raising=False)
    assert notifier_from_env() is None


def test_notifier_from_env_builds_a_real_notifier_when_both_set(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("AP_CHAT_NOTIFY_CHAT_ID", "-100999")
    notifier = notifier_from_env()
    assert isinstance(notifier, TelegramProposalNotifier)
    assert notifier._chat_id == -100999
