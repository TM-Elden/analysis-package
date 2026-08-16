"""Policy knobs for the C7 proposal workflow. Data only - ProposalWorkflow reads these.

Mirrors `ap_review.policy.ReviewPolicy`'s shape. `require_dry_run_for_declarative` is enforced by
`ProposalWorkflow.decide` (`data/fathm-phase4-readiness/report.md` §5.6 in the firstmate repo):
with the flag on (the default), approving a declarative-kind proposal (profile_change,
reason_code_add) requires a recorded `dry_run_json` - see `ap_proposals/workflow.py` and
`ap_proposals/apply.py::run_dry_run`.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProposalPolicy:
    #: Enforced in `ProposalWorkflow.decide` (§5.6): approving a declarative-kind proposal
    #: (profile_change, reason_code_add) requires a recorded dry_run_json - see module docstring.
    require_dry_run_for_declarative: bool = True
