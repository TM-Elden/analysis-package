"""ProposalWorkflow: the C7 proposal decision state machine.

`pending_hitl -> approved | rejected | withdrawn` (§10's own set - see
`data/fathm-phase4-readiness/report.md` §5.4 in the firstmate repo). Approve-with-edits is
`approved` with `edited_diff_json` populated, not a fifth state - the edited diff is stored
*beside* the original (`ProposalStore.set_status`'s `edited_diff` param), never overwriting it.

There is no separate `applied` state: apply happens **in the same decision call** as approve
(`decide`, below), before `ProposalStore.set_status` is ever invoked - see `ap_proposals.apply`
for the config-vs-code split this drives:

- Declarative kinds (`profile_change`, `reason_code_add`) get a real registry write
  (`ap_proposals.apply.apply_declarative`). If that write raises, `decide` propagates the error
  *without* calling `set_status` at all - the proposal is left exactly where it was
  (`pending_hitl`), never "approved but silently unapplied".
- Code kinds (`standard_change`, `check_add`) get a spec artifact export
  (`ap_proposals.apply.export_spec`) instead - no mechanism can auto-apply Python.

`policy.require_dry_run_for_declarative` (default on, §5.6 "mandatory-at-decision, not
decorative") additionally refuses to approve a declarative-kind proposal with no `dry_run_json`
recorded - see `record_dry_run` below, the method that runs `ap_planner_bot.dry_run.dry_run` and
persists the result. Code kinds skip this: you cannot dry-run a check that doesn't exist yet.

Policy/mechanism split mirrors `ap_review.ReviewWorkflow` exactly: this module owns policy (roles,
reject-requires-reason, dry-run-required); `ProposalStore.set_status` owns mechanism
(compare-and-swap + audit row); `ap_proposals.apply` owns the apply step itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_proposals.apply import apply_declarative, export_spec, run_dry_run
from ap_proposals.kinds import CODE_KINDS, DECLARATIVE_KINDS, validate_diff
from ap_proposals.models import ProposalRecord
from ap_proposals.policy import ProposalPolicy
from ap_proposals.store import ProposalStore, ProposalStoreError
from ap_registry.profile_registry import ProfileRegistry

# Allowed (from_status, to_status) pairs.
TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("pending_hitl", "approved"),
        ("pending_hitl", "rejected"),
        ("pending_hitl", "withdrawn"),
    }
)


class ProposalPolicyError(ProposalStoreError):
    """A decision was attempted but role/reason/dry-run policy forbids it.

    Distinct from the plain ProposalStoreError ProposalStore.set_status raises on a concurrency
    conflict, and from ProposalApplyError (the apply step itself failed) - an API layer can map
    this to 403 (policy) vs 409 (conflict) vs 502/500 (apply failure), same convention as
    ap_review.workflow.ReviewPolicyError vs. StoreError.
    """


@dataclass
class ProposalWorkflow:
    store: ProposalStore
    policy: ProposalPolicy = field(default_factory=ProposalPolicy)
    #: Defaults to a registry rooted at the same store_root ProposalStore uses
    #: (`<store_root>/standard_registry/...`) - the same root PackageStore/ProposalStore share
    #: (see CLAUDE.md's ap_proposals section). Pass explicitly only for tests that want an
    #: isolated registry.
    registry: ProfileRegistry | None = None

    def __post_init__(self) -> None:
        if self.registry is None:
            self.registry = ProfileRegistry(self.store.root)

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

        applied_version: str | None = None
        spec_artifact_path: str | None = None
        if to_status == "approved":
            effective_diff = edited_diff if edited_diff is not None else record.diff()
            if record.kind in DECLARATIVE_KINDS:
                if self.policy.require_dry_run_for_declarative and record.dry_run_json is None:
                    raise ProposalPolicyError(
                        f"proposal {proposal_id!r} (kind {record.kind!r}) has no recorded dry-run - "
                        "call ProposalWorkflow.record_dry_run before approving a declarative-kind "
                        "proposal (§5.6: dry-run is mandatory-at-decision, not decorative)"
                    )
                # Apply BEFORE touching the proposal store: if this raises, nothing below runs and
                # the proposal is left exactly as it was (pending_hitl) - the transactional
                # contract from §5.4, honored across two different storage backends by ordering
                # rather than a shared transaction (the registry is a filesystem write, not SQL).
                applied_version = apply_declarative(self.registry, record.kind, effective_diff, actor_id=actor.id)
            elif record.kind in CODE_KINDS:
                spec_artifact_path = export_spec(
                    self.store.root,
                    proposal_id,
                    record.kind,
                    record.summary,
                    record.rationale,
                    effective_diff,
                    actor_id=actor.id,
                )
            else:  # pragma: no cover - unreachable, kind was already schema-validated at create time
                raise ProposalPolicyError(f"unknown proposal kind {record.kind!r}")

        return self.store.set_status(
            proposal_id,
            from_status=from_status,
            to_status=to_status,
            actor=actor,
            reason=reason,
            edited_diff=edited_diff,
            applied_version=applied_version,
            spec_artifact_path=spec_artifact_path,
        )

    def record_dry_run(self, proposal_id: str, package_store: Any, *, edited_diff: dict[str, Any] | None = None) -> ProposalRecord:
        """Run `ap_planner_bot.dry_run.dry_run` for a still-`pending_hitl` declarative-kind
        proposal and persist the result (`ProposalStore.record_dry_run`) - what satisfies the
        `decide`-time "no declarative approval without a dry-run on record" requirement above.
        `package_store` is the `ap_store.store.PackageStore` the corpus scan runs against (not
        held on the workflow itself - same reasoning `ReviewWorkflow` doesn't hold an
        `ap_index.IndexStore`: this is a read-only cross-module call, not workflow state).

        Dry-runs the proposal's original `diff_json` by default; pass `edited_diff` to dry-run a
        prospective approve-with-edits value instead (either way, `decide` only checks that
        *some* dry-run is on record - it does not require the dry-run to match the diff finally
        approved, matching the "either is fine" acceptance wording in the design brief).
        """
        record = self.store.get(proposal_id)
        if record is None:
            raise ProposalStoreError(f"no such proposal: {proposal_id}")
        if record.kind not in DECLARATIVE_KINDS:
            raise ProposalPolicyError(
                f"proposal {proposal_id!r} (kind {record.kind!r}) is a code kind - dry-run only "
                "applies to declarative kinds (you cannot dry-run a check that doesn't exist yet)"
            )
        diff = edited_diff if edited_diff is not None else record.diff()
        dry_run_json = run_dry_run(package_store, self.store.root, record.kind, diff)
        return self.store.record_dry_run(proposal_id, dry_run_json)

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
