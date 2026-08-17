"""C7 notify-agents v0 seam (design report §5.8): `ProposalWorkflow`'s notification hook.

Deliberately a `Protocol`, not an import of `ap_chat` - `ap_proposals` stays a storage/workflow
module with no chat-platform dependency, same layering discipline as `ap_review` not importing
`ap_index` (see CLAUDE.md). The concrete Telegram implementation lives in
`ap_chat.telegram.notify.TelegramProposalNotifier` and is wired in by callers (`ap_api/deps.py`,
`ap_planner_bot/sweep.py`) that already sit above both modules.

This is a courtesy channel, not the contract - §5.8: "the gate's version pinning is the actual
enforcement, notification is a courtesy." `ProposalWorkflow` calls these hooks *after* the real
state change has already committed (`ProposalStore.create`/`set_status` succeeded) and swallows
any exception a notifier raises (logged, not propagated) - a Telegram outage must never fail a
proposal decision.
"""

from __future__ import annotations

from typing import Protocol

from ap_proposals.models import ProposalRecord


class ProposalNotifier(Protocol):
    """Structural interface - a concrete notifier need not import this module, just implement the
    same three methods. `ProposalWorkflow.notifier` is typed against this Protocol."""

    def notify_created(self, record: ProposalRecord) -> None:
        """A new proposal was drafted (`proposal.created`, §5.8) - called once, right after
        `ProposalStore.create` returns."""
        ...

    def notify_decision(self, record: ProposalRecord, *, from_status: str) -> None:
        """A human decided a proposal - approved (with or without edits), rejected, or withdrawn
        (`proposal.decision`, §5.8) - called once, right after `ProposalStore.set_status`
        returns."""
        ...

    def notify_version_released(self, record: ProposalRecord, *, profile_name: str, version: str) -> None:
        """Apply-on-approve actually bumped a profile version (§5.8's "version-released message")
        - called only for a declarative-kind approval whose `apply_declarative` call succeeded,
        right after the same `set_status` call `notify_decision` fires for."""
        ...
