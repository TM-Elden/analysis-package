"""Policy knobs for the C10 package review workflow. Data only - ReviewWorkflow reads these."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ReviewPolicy:
    #: draft -> in_review requires ap-gate check to pass against the package's stored bytes.
    #: Default True per the phase-2 brief ("policy knob (default: package must pass ap-gate check
    #: before it can move to in_review)"); a team may set False if they want the review queue to
    #: also surface gate-failing drafts (e.g. to review the failure itself), documented as a
    #: deliberate override, not a silent bypass.
    gate_before_review: bool = True

    #: in_review -> approved/rejected normally requires the deciding actor's id to differ from the
    #: package's owners.analyst.id (a distinct reviewer). Default False (distinct reviewer
    #: required) per the phase-2 brief ("default to requiring a distinct reviewer"). Set True to
    #: allow self-approval for small teams where a second reviewer isn't realistic - this is the
    #: documented override the brief asks for, not a workaround.
    allow_self_review: bool = False
