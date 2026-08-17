"""Policy knobs for the C12 lifecycle workflow - data only, LifecycleWorkflow reads these.

No knobs today (every lifecycle role requirement - reviewer/admin for supersede/recall, admin-only
for restore/legal-hold/purge - is fixed by the C12 acceptance bar, not a per-deployment choice).
This module exists for symmetry with `ap_review.policy.ReviewPolicy` and so `LifecycleWorkflow`
has the same `policy: LifecyclePolicy` field shape - a future knob (e.g. an opt-in that lets a
non-admin restore a recalled package) has an obvious home to land in.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LifecyclePolicy:
    pass
