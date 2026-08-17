"""`TelegramProposalNotifier`: the concrete `ap_proposals.notify.ProposalNotifier` for the §5.8
notify-agents-v0 slice - reuses `TelegramBotClient` directly (the same client
`ap_chat.telegram.adapter.TelegramPlatform` uses to answer chat questions), not a second Telegram
integration.

Unlike `TelegramPlatform.send_reply` (which replies in-thread to an inbound message), a proposal
lifecycle event has no inbound message to reply to - these are proactive posts to one configured
chat (`chat_id`, resolved from `AP_CHAT_NOTIFY_CHAT_ID`; see `notifier_from_env` below), so
`send_message` is called with no `reply_to_message_id`.

Messages are deliberately short and factual (proposal id, kind, one-line summary/outcome) - this
is a courtesy notification, not the proposal detail; a reader clicks through to the console's
"Standard" tab for that (§5.8, §11's "notify agents" acceptance line). `ProposalWorkflow` already
swallows any exception a notifier raises (see `ap_proposals.notify`'s module docstring), so this
module does not need its own retry/backoff - out of scope per the report's "don't build C16".
"""

from __future__ import annotations

import os

from ap_chat.telegram.client import TelegramBotClient
from ap_proposals.models import ProposalRecord

_HTML_ESCAPES = (("&", "&amp;"), ("<", "&lt;"), (">", "&gt;"))


def _escape(text: str) -> str:
    for char, escaped in _HTML_ESCAPES:
        text = text.replace(char, escaped)
    return text


def _one_line(text: str, *, limit: int = 160) -> str:
    """Collapse to one line and cap length - a notification is a courtesy summary, not the full
    `summary`/`rationale` field (which can run to a paragraph)."""
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1].rstrip() + "…"


class TelegramProposalNotifier:
    """Structurally satisfies `ap_proposals.notify.ProposalNotifier` (a Protocol - no base class
    needed). `chat_id` is the one configured notification chat, distinct from any planner's own
    conversation - see `notifier_from_env`."""

    def __init__(self, client: TelegramBotClient, *, chat_id: int):
        self._client = client
        self._chat_id = chat_id

    def _send(self, text: str) -> None:
        self._client.send_message(chat_id=self._chat_id, text=_escape(text))

    def notify_created(self, record: ProposalRecord) -> None:
        self._send(
            f"🆕 <b>Proposal {record.proposal_id}</b> created ({record.kind})\n"
            f"{_one_line(record.summary)}"
        )

    def notify_decision(self, record: ProposalRecord, *, from_status: str) -> None:
        icon = {"approved": "✅", "rejected": "❌", "withdrawn": "↩️"}.get(record.status, "•")
        outcome = f"{record.status} by {record.decided_by_id}"
        if record.status == "rejected" and record.decision_reason:
            outcome += f": {_one_line(record.decision_reason)}"
        elif record.status == "approved" and record.edited_diff_json is not None:
            outcome += " (with edits)"
        self._send(f"{icon} <b>Proposal {record.proposal_id}</b> {outcome} ({record.kind})")

    def notify_version_released(self, record: ProposalRecord, *, profile_name: str, version: str) -> None:
        self._send(
            f"📦 Profile <b>{_escape(profile_name)}</b> released as v{version} "
            f"(via proposal {record.proposal_id})"
        )


def notifier_from_env() -> TelegramProposalNotifier | None:
    """Builds a notifier from the same `TELEGRAM_BOT_TOKEN` the chat bot uses, plus a new
    `AP_CHAT_NOTIFY_CHAT_ID` env var (the chat proposal lifecycle events post to - typically a
    fathm-team group chat, not any one planner's DM). Returns `None` when either is unset: no
    notifier configured is a valid, courtesy-feature-off state, not a startup error - callers
    (`ap_api/deps.py`, `ap_planner_bot/sweep.py::main`) pass the result straight through as
    `ProposalWorkflow(notifier=...)`."""
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id_raw = os.environ.get("AP_CHAT_NOTIFY_CHAT_ID")
    if not token or not chat_id_raw:
        return None
    return TelegramProposalNotifier(TelegramBotClient(token=token), chat_id=int(chat_id_raw))
