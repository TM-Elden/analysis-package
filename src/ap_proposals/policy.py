"""Policy knobs for the C7 proposal workflow. Data only - ProposalWorkflow reads these.

Mirrors `ap_review.policy.ReviewPolicy`'s shape. `require_dry_run_for_declarative` is a documented
extension point, not yet enforced: the dry-run engine (`data/fathm-phase4-readiness/report.md` §5.6
in the firstmate repo) is a separate, later task, so `ProposalWorkflow` cannot honestly require a
`dry_run_json` that nothing yet computes. Wiring the enforcement is that later task's job, not a
schema change - the flag and the `dry_run_json` column already exist for it.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProposalPolicy:
    #: Reserved for the dry-run engine task (§5.6): once wired, approving a declarative-kind
    #: proposal (profile_change, reason_code_add) should require a recorded dry_run_json. Not
    #: enforced yet - see module docstring.
    require_dry_run_for_declarative: bool = True
