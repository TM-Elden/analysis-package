"""The canonical check-ID registry and runner.

Check IDs here are the single source of truth for the gate's vocabulary
(second review section 5.1): they are what future conformance telemetry
and any pooled-learning-on-structure would key off of, so they must never
be silently renamed. This list resolves the three-way ID divergence found
across product/CI-L1.md, docs/DESIGN-FATHM-MVP.md, and
docs/DESIGN-FATHM-SYSTEM.md in favor of the system doc's set (the newest,
declared build authority), plus `qa_approved_implies_pass` from the MVP doc
(the one useful MVP-only check). product/CI-L1.md was updated to match this
list in the same pass that created this file.

Order matters only in that `qa_approved_implies_pass` must run last: it is
a two-phase check that inspects every other check's outcome.
"""

from __future__ import annotations

from ap_gate.checks.context import CheckContext
from ap_gate.checks.engines import check_engines_pinned
from ap_gate.checks.inputs import check_inputs_pinned
from ap_gate.checks.labels import (
    check_labels_jsonl_parse,
    check_labels_paths,
    check_reason_codes_known,
)
from ap_gate.checks.layout import check_guideline_exists, check_layout_dirs
from ap_gate.checks.manifest_fields import (
    check_must_fields,
    check_qa_status_enum,
    check_standard_version,
    check_training_eligibility_present,
)
from ap_gate.checks.outputs import check_output_contract_files
from ap_gate.checks.qa import check_no_unlabeled_diff, check_qa_approved_implies_pass
from ap_gate.checks.types import RESULT_FAIL, CheckOutcome

# (check_id, function, is_meta) - is_meta checks take (ctx, outcomes_so_far).
_SIMPLE_CHECKS = [
    ("must_fields", check_must_fields),
    ("standard_version", check_standard_version),
    ("layout_dirs", check_layout_dirs),
    ("guideline_exists", check_guideline_exists),
    ("output_contract_files", check_output_contract_files),
    ("inputs_pinned", check_inputs_pinned),
    ("engines_pinned", check_engines_pinned),
    ("labels_paths", check_labels_paths),
    ("labels_jsonl_parse", check_labels_jsonl_parse),
    ("reason_codes_known", check_reason_codes_known),
    ("qa_status_enum", check_qa_status_enum),
    ("training_eligibility_present", check_training_eligibility_present),
    ("no_unlabeled_diff", check_no_unlabeled_diff),
]

# Meta checks run after every simple check, in listed order, each seeing all
# outcomes computed so far (including earlier meta checks).
_META_CHECKS = [
    ("qa_approved_implies_pass", check_qa_approved_implies_pass),
]

ALL_CHECK_IDS = [check_id for check_id, _ in _SIMPLE_CHECKS] + [check_id for check_id, _ in _META_CHECKS]


def _apply_waivers(outcomes: list[CheckOutcome], manifest: dict) -> None:
    """Mutate fail outcomes into waived passes per manifest qa.waivers[].

    Waiver author is intentionally never copied into the outcome message -
    person identifiers stay out of gate output entirely, not just out of
    the content-free results[] layer (second review sections 5.2, 7.2).
    """
    raw_waivers = (manifest.get("qa") or {}).get("waivers") or []
    waivers = {w.get("check_id"): w for w in raw_waivers if isinstance(w, dict) and w.get("check_id")}
    for outcome in outcomes:
        if outcome.result == RESULT_FAIL and outcome.check_id in waivers:
            reason = waivers[outcome.check_id].get("reason", "")
            outcome.waived = True
            outcome.result = "pass"
            if reason:
                outcome.message = f"{outcome.message}\n  (waived: {reason})" if outcome.message else f"waived: {reason}"


def run_all(ctx: CheckContext) -> list[CheckOutcome]:
    outcomes: list[CheckOutcome] = []
    for check_id, fn in _SIMPLE_CHECKS:
        outcome = fn(ctx)
        assert outcome.check_id == check_id, f"check {fn} returned check_id {outcome.check_id!r}, expected {check_id!r}"
        outcomes.append(outcome)
    for check_id, fn in _META_CHECKS:
        outcome = fn(ctx, outcomes)
        assert outcome.check_id == check_id, f"check {fn} returned check_id {outcome.check_id!r}, expected {check_id!r}"
        outcomes.append(outcome)
    _apply_waivers(outcomes, ctx.manifest)
    return outcomes
