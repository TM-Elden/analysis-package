"""no_unlabeled_diff (stubbed/skipped in phase 1), qa_approved_implies_pass (two-phase)."""

from __future__ import annotations

from ap_gate.checks.context import CheckContext
from ap_gate.checks.types import CheckOutcome

CHECK_ID_NO_UNLABELED_DIFF = "no_unlabeled_diff"
CHECK_ID_QA_APPROVED_IMPLIES_PASS = "qa_approved_implies_pass"


def check_no_unlabeled_diff(ctx: CheckContext) -> CheckOutcome:
    """Engine-replay checking. Explicitly out of phase-1 scope - see task exclusions.

    Always returns skip, regardless of package contents. Real engine
    implementations are a phase-2 candidate (second review section 5.5);
    until they exist there is nothing to replay against.
    """
    return CheckOutcome.skip(
        CHECK_ID_NO_UNLABELED_DIFF,
        "engine replay not implemented in phase 1 (stubbed) - no_unlabeled_diff always skips "
        "until real deterministic engines exist to replay against.",
    )


def check_qa_approved_implies_pass(ctx: CheckContext, prior_outcomes: list[CheckOutcome]) -> CheckOutcome:
    """Runs last (two-phase): if qa.status is approved, no other required check may have failed.

    no_unlabeled_diff is exempted from this check by design (MVP doc: "allow
    skip for no_unlabeled_diff only") since it is permanently stubbed in
    phase 1 - a skip there must not block approval.

    This evaluates the gate's own freshly computed results, never the
    manifest's qa.checks[] historical record (second review section 4.3) -
    otherwise a package could satisfy the gate purely by asserting pass in
    its own manifest.
    """
    status = (ctx.manifest.get("qa") or {}).get("status")
    if status != "approved":
        return CheckOutcome.skip(
            CHECK_ID_QA_APPROVED_IMPLIES_PASS, f"qa.status is {status!r}, not 'approved' - not applicable"
        )

    blocking = [
        o for o in prior_outcomes
        if o.check_id != CHECK_ID_NO_UNLABELED_DIFF and o.blocks_overall_pass()
    ]
    if blocking:
        ids = ", ".join(o.check_id for o in blocking)
        return CheckOutcome.fail(
            CHECK_ID_QA_APPROVED_IMPLIES_PASS,
            f"qa.status is 'approved' but these required checks failed: {ids} - "
            "fix them, waive them with a reason in qa.waivers, or set qa.status back "
            "to 'in_review' until they pass.",
        )
    return CheckOutcome.ok(
        CHECK_ID_QA_APPROVED_IMPLIES_PASS, "all required checks pass or are waived - approved status is consistent"
    )
