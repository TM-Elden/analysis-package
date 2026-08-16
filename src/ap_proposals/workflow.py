"""ProposalWorkflow: the C7 proposal decision state machine.

`pending_hitl -> approved | rejected | withdrawn` (§10's own set - see
`data/fathm-phase4-readiness/report.md` §5.4 in the firstmate repo). Approve-with-edits is
`approved` with `edited_diff_json` populated, not a fifth state - the edited diff is stored
*beside* the original (`ProposalStore.set_status`'s `edited_diff` param), never overwriting it.
There is no separate `applied` state: for declarative kinds a later apply-mechanism task performs
the actual registry write in the same `set_status` transaction as the approve decision (see that
method's docstring for the extension point) - this workflow's job is only to support that
transactional contract, not to implement the write.

Policy/mechanism split mirrors `ap_review.ReviewWorkflow` exactly: this module owns policy (roles,
reject-requires-reason); `ProposalStore.set_status` owns mechanism (compare-and-swap + audit row).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_proposals.kinds import validate_diff
from ap_proposals.models import ProposalRecord
from ap_proposals.policy import ProposalPolicy
from ap_proposals.store import ProposalStore, ProposalStoreError

# Allowed (from_status, to_status) pairs.
TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("pending_hitl", "approved"),
        ("pending_hitl", "rejected"),
        ("pending_hitl", "withdrawn"),
    }
)


class ProposalPolicyError(ProposalStoreError):
    """A decision was attempted but role/reason policy forbids it.

    Distinct from the plain ProposalStoreError ProposalStore.set_status raises on a concurrency
    conflict - an API layer can map this to 403 (policy) vs 409 (conflict), same convention as
    ap_review.workflow.ReviewPolicyError vs. StoreError.
    """


@dataclass
class ProposalWorkflow:
    store: ProposalStore
    policy: ProposalPolicy = field(default_factory=ProposalPolicy)

    def create(
        self,
        *,
        kind: str,
        summary: str,
        rationale: str,
        diff: dict[str, Any],
        evidence: dict[str, Any],
        actor: Identity,
    ) -> ProposalRecord:
        """Creating a proposal requires any authenticated internal identity - no role restriction.
        Today's only caller is the sweep's service identity (§5.2/§5.3); a human-filed proposal
        route is a later API addition, not a policy or schema change, so this deliberately does not
        encode a "bot vs. human" distinction anywhere.
        """
        return self.store.create(
            kind=kind, summary=summary, rationale=rationale, diff=diff, evidence=evidence, actor=actor
        )

    def decide(
        self,
        proposal_id: str,
        *,
        to_status: str,
        actor: Identity,
        reason: str | None = None,
        edited_diff: dict[str, Any] | None = None,
    ) -> ProposalRecord:
        record = self.store.get(proposal_id)
        if record is None:
            raise ProposalStoreError(f"no such proposal: {proposal_id}")

        from_status = record.status
        if (from_status, to_status) not in TRANSITIONS:
            raise ProposalPolicyError(
                f"{from_status!r} -> {to_status!r} is not an allowed proposal transition "
                f"(allowed: {sorted(TRANSITIONS)})"
            )

        if edited_diff is not None:
            if to_status != "approved":
                raise ProposalPolicyError("edited_diff is only meaningful on an approve decision")
            # approve-with-edits: the edit must itself be a well-formed diff for this proposal's kind.
            validate_diff(record.kind, edited_diff)

        if to_status in ("approved", "rejected"):
            self._check_decide(record, actor, to_status, reason)
        # pending_hitl -> withdrawn carries no extra policy beyond appearing in TRANSITIONS, mirroring
        # ap_review.ReviewWorkflow's withdraw/revise transitions - withdrawn is for dedup-supersede
        # and admin housekeeping (§5.4), not restricted to the original creator here.

        return self.store.set_status(
            proposal_id,
            from_status=from_status,
            to_status=to_status,
            actor=actor,
            reason=reason,
            edited_diff=edited_diff,
        )

    def _check_decide(
        self,
        record: ProposalRecord,
        actor: Identity,
        to_status: str,
        reason: str | None,
    ) -> None:
        if not actor.has_role(Role.STANDARD_APPROVER):
            raise ProposalPolicyError(
                f"actor {actor.id!r} may not decide proposal {record.proposal_id!r} - requires the "
                "standard_approver role (or admin)"
            )
        if to_status == "rejected" and not (reason and reason.strip()):
            raise ProposalPolicyError("rejecting a proposal requires a non-empty decision_reason")
