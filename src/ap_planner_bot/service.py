"""C6 stage 2: turn one deterministic `Finding` (`detectors.py`) into a drafted `ap_proposals`
record - the piece stage 1's own docstring calls out as "a later chunk" (P4.4, design report
section 5.3 in the firstmate repo).

Reuses the C4 manager bot's seams directly rather than reinventing them (task brief): `LLMClient`
(`ap_manager_bot.llm_client`) for the model call, and the same citation-registry enforcement shape
as `ap_manager_bot.tool_backend`/`service.py`'s `_final_answer` - here applied to a drafted diff
instead of a chat answer. The LLM never computes a statistic itself (`detectors.py` already did
that); it only narrates one finding into `summary` / `rationale` / a typed `diff`, and every part of
that draft is re-validated server-side before anything is persisted:

- **`diff` is schema-validated per `kind`** (`ap_proposals.kinds.validate_diff`) before persist - an
  invalid diff is discarded, never "fixed up" or stored raw.
- **Evidence is a citation registry, not free-form text**: `_fetch_evidence` fetches redacted
  chunks from the index for exactly the finding's own `package_ids` (never raw package bytes, same
  rule C4 follows), scoped through `ap_manager_bot.scoping`'s pre+post confidentiality
  double-check, and records each retrieved chunk's `chunk_id -> package_id` in a registry. The
  model's `evidence[].ref_id` values are resolved against that registry only - an invented ref_id is
  dropped, and a draft whose evidence is entirely invented (nothing resolves) is discarded whole.
- **Dedup**: a new draft matching an already-`pending_hitl` proposal's `(kind, target)` is
  suppressed (`proposal_target`) - weekly sweeps must not spam the queue with repeats of a finding
  that already has an open proposal.

The model gets exactly one turn per finding (no retrieval loop like C4's Q&A): the finding and its
evidence are fully known up front, so there is nothing further for the model to search for - it
either drafts via the one `draft_proposal` tool, or makes no tool call at all, which this module
treats as a considered decline (not every finding need become a proposal), never a fabricated draft.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ap_auth.identity import Identity
from ap_index.index_store import IndexStore
from ap_index.models import SearchFilters
from ap_manager_bot.llm_client import LLMClient, LLMClientError
from ap_manager_bot.scoping import chunk_in_scope, confidentiality_filter_for
from ap_planner_bot.detectors import Finding
from ap_proposals.kinds import ProposalValidationError, validate_diff
from ap_proposals.models import ProposalRecord
from ap_proposals.store import ListFilter as ProposalListFilter
from ap_proposals.workflow import ProposalWorkflow

#: Evidence chunks fetched per finding, capped to keep the drafting prompt small at pilot scale -
#: same tune-in-place honesty as detectors.py's thresholds, not load-bearing math.
MAX_EVIDENCE_CHUNKS_PER_FINDING = 6

_SYSTEM_PROMPT = """You are fathm's C6 planner bot. You turn one deterministic drift finding - \
already computed by a corpus scan, not by you - into a draft Standard-change proposal for a human \
standard_approver to review.

Rules:
- Call draft_proposal exactly once with your draft, or make no tool call at all if this finding \
does not actually warrant a proposal (e.g. the evidence is too thin to draft a specific diff from).
- diff must match the shape for the given kind:
    reason_code_add -> {profile, code, description}
    profile_change   -> {profile, file, before, after}
    standard_change  -> {target, description[, patch]}
    check_add        -> {check_id, severity, description}
- Every evidence[].ref_id you cite must be one shown to you this turn under "Evidence available" -
  never invent one, and never cite a package_id that wasn't shown.
- The finding you were given carries no author/planner identity - never invent or imply one in
  summary or rationale."""

DRAFT_PROPOSAL_TOOL_SCHEMA: dict[str, Any] = {
    "description": (
        "Draft one Standard-change proposal from the finding you were given. summary and "
        "rationale are prose for a human reviewer; diff is typed per kind (see system prompt); "
        "evidence lists the ref_id(s) - from what was shown to you this turn - that support the "
        "draft."
    ),
    "input_schema": {
        "type": "object",
        "required": ["kind", "summary", "rationale", "diff", "evidence"],
        "properties": {
            "kind": {
                "type": "string",
                "enum": ["reason_code_add", "profile_change", "standard_change", "check_add"],
            },
            "summary": {"type": "string"},
            "rationale": {"type": "string"},
            "diff": {"type": "object"},
            "evidence": {
                "type": "array",
                "items": {"type": "object", "required": ["ref_id"], "properties": {"ref_id": {"type": "string"}}},
            },
        },
    },
}


def proposal_target(kind: str, diff: dict[str, Any]) -> tuple[Any, ...] | None:
    """The (kind-specific) identity a proposal's diff targets - dedup's comparison key
    (`_has_open_duplicate` below). `None` for an unrecognized kind (never reached once `diff` has
    passed `validate_diff`, since every known kind's schema requires these fields)."""
    if kind == "reason_code_add":
        return (diff.get("profile"), diff.get("code"))
    if kind == "profile_change":
        return (diff.get("profile"), diff.get("file"))
    if kind == "standard_change":
        return (diff.get("target"),)
    if kind == "check_add":
        return (diff.get("check_id"),)
    return None


@dataclass(frozen=True)
class DraftOutcome:
    """One finding's drafting outcome. `proposal` is set only on a real, persisted proposal;
    `discarded_reason` explains why nothing was persisted otherwise - `"declined"` (model made no
    draft call), `"no_evidence_resolved"` (no chunk evidence available, or every cited ref_id was
    invented / out of scope), `"invalid_diff"` (schema-invalid diff, or missing summary/rationale),
    `"duplicate"` (an open proposal already covers this kind/target), or `"llm_error"` (the model
    call itself raised `LLMClientError` - a transport/rate-limit failure, not a bad response to
    judge)."""

    proposal: ProposalRecord | None = None
    discarded_reason: str | None = None


@dataclass(frozen=True)
class SweepDraftResult:
    created: tuple[ProposalRecord, ...] = ()
    #: discard reason -> count, for the sweep's own summary line (sweep.py / the console notice).
    discarded: dict[str, int] = field(default_factory=dict)


class ProposalDrafter:
    """Drafts and persists proposals for one sweep's worth of findings, under one `identity`
    (the sweep's service identity, or the console session's identity when triggered from the
    button - design report section 5.1)."""

    def __init__(self, *, index: IndexStore, workflow: ProposalWorkflow, llm_client: LLMClient, identity: Identity):
        self._index = index
        self._workflow = workflow
        self._llm_client = llm_client
        self._identity = identity
        self._confidentiality = confidentiality_filter_for(identity)

    def draft_for_finding(self, finding: Finding) -> DraftOutcome:
        citable = self._fetch_evidence(finding)
        if not citable:
            return DraftOutcome(discarded_reason="no_evidence_resolved")

        prompt = _finding_prompt(finding, citable)
        try:
            response = self._llm_client.complete(
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": [{"type": "text", "text": prompt}]}],
                tools=[{"name": "draft_proposal", **DRAFT_PROPOSAL_TOOL_SCHEMA}],
            )
        except LLMClientError:
            return DraftOutcome(discarded_reason="llm_error")
        tool_uses = [
            b for b in (response.get("content") or []) if b.get("type") == "tool_use" and b.get("name") == "draft_proposal"
        ]
        if not tool_uses:
            return DraftOutcome(discarded_reason="declined")

        tool_input = tool_uses[0].get("input") or {}
        kind = str(tool_input.get("kind") or "")
        diff = tool_input.get("diff") if isinstance(tool_input.get("diff"), dict) else {}
        summary = str(tool_input.get("summary") or "").strip()
        rationale = str(tool_input.get("rationale") or "").strip()
        raw_evidence = tool_input.get("evidence") or []

        try:
            validate_diff(kind, diff)
        except ProposalValidationError:
            return DraftOutcome(discarded_reason="invalid_diff")
        if not summary or not rationale:
            return DraftOutcome(discarded_reason="invalid_diff")

        resolved_package_ids = sorted(
            {citable[e["ref_id"]] for e in raw_evidence if isinstance(e, dict) and e.get("ref_id") in citable}
        )
        if not resolved_package_ids:
            return DraftOutcome(discarded_reason="no_evidence_resolved")

        target = proposal_target(kind, diff)
        if target is not None and self._has_open_duplicate(kind, target):
            return DraftOutcome(discarded_reason="duplicate")

        record = self._workflow.create(
            kind=kind,
            summary=summary,
            rationale=rationale,
            diff=diff,
            evidence={"package_ids": resolved_package_ids},
            actor=self._identity,
        )
        return DraftOutcome(proposal=record)

    # -- internals ------------------------------------------------------

    def _fetch_evidence(self, finding: Finding) -> dict[str, str]:
        """`chunk_id -> package_id` for chunks actually retrieved and in-scope this turn - the
        citation-registry pattern `ap_manager_bot.tool_backend` uses, applied to a finding's fixed
        `package_ids` instead of a free-text search. Every approved+indexed package carries at
        least one `manifest_summary` chunk (`ap_redact.chunk.build_manifest_summary_chunk`), so a
        package that is genuinely indexed always contributes at least one ref_id."""
        citable: dict[str, str] = {}
        for package_id in finding.package_ids:
            filters = SearchFilters(package_id=package_id, confidentiality_in=self._confidentiality)
            for result in self._index.search(None, filters=filters, limit=MAX_EVIDENCE_CHUNKS_PER_FINDING):
                chunk = result.chunk
                if chunk_in_scope(self._identity, chunk):
                    citable[chunk.chunk_id] = chunk.package_id
        return citable

    def _has_open_duplicate(self, kind: str, target: tuple[Any, ...]) -> bool:
        page = self._workflow.store.list(ProposalListFilter(kind=kind, status="pending_hitl", page_size=200))
        return any(proposal_target(kind, record.diff()) == target for record in page.items)


def _finding_prompt(finding: Finding, citable: dict[str, str]) -> str:
    evidence_lines = "\n".join(f"- ref_id={ref_id} package_id={package_id}" for ref_id, package_id in sorted(citable.items()))
    return (
        f"Finding detector={finding.detector!r} kind={finding.kind!r}\n"
        f"Summary: {finding.summary}\n"
        f"Detail: {json.dumps(finding.detail, sort_keys=True)}\n"
        f"Evidence available this turn (cite ref_id values only):\n{evidence_lines}\n"
    )


def draft_proposals(
    findings: list[Finding], *, index: IndexStore, workflow: ProposalWorkflow, llm_client: LLMClient, identity: Identity
) -> SweepDraftResult:
    """Draft + persist proposals for every finding in one sweep. Never raises on a single
    finding's bad draft, nor on the LLM call itself failing (`LLMClientError` - rate limit,
    transport, etc.) - discards are counted, not propagated, so one malformed model response or
    one transient API failure can't abort an otherwise-good sweep."""
    drafter = ProposalDrafter(index=index, workflow=workflow, llm_client=llm_client, identity=identity)
    created: list[ProposalRecord] = []
    discarded: dict[str, int] = {}
    for finding in findings:
        outcome = drafter.draft_for_finding(finding)
        if outcome.proposal is not None:
            created.append(outcome.proposal)
        elif outcome.discarded_reason:
            discarded[outcome.discarded_reason] = discarded.get(outcome.discarded_reason, 0) + 1
    return SweepDraftResult(created=tuple(created), discarded=discarded)
