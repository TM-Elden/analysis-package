"""ReviewWorkflow: the C10 package-level review state machine.

`draft -> in_review -> approved | rejected`, plus two practical escape hatches beyond the brief's
minimum (documented here as the judgment call they are, not left implicit): `in_review -> draft`
(withdraw) and `rejected -> draft` (revise and resubmit) - without them a rejected package would be
a dead end with no path back into the workflow.

This module owns *policy* (roles, self-review, gate-before-review, reject-requires-reason);
`ap_store.PackageStore.set_status` owns *mechanism* (the compare-and-swap status update + audit
row). ReviewWorkflow always re-runs the real ap-gate library check (`ap_gate.checks.registry.run_all`
via `CheckContext`, the exact function `ap-gate check` uses) against the package's immutable stored
bytes - never a second/parallel implementation of gate logic.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_gate.checks.context import CheckContext
from ap_gate.checks.registry import run_all
from ap_gate.load_manifest import load_manifest
from ap_gate.report.model import build_report
from ap_review.policy import ReviewPolicy
from ap_store.models import PackageRecord
from ap_store.store import PackageStore, StoreError

# Allowed (from_status, to_status) pairs.
TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("draft", "in_review"),
        ("in_review", "approved"),
        ("in_review", "rejected"),
        ("in_review", "draft"),  # withdraw
        ("rejected", "draft"),  # revise and resubmit
    }
)


class ReviewPolicyError(StoreError):
    """A transition was attempted but role/self-review/gate/reason policy forbids it.

    Distinct from the plain StoreError PackageStore.set_status raises on a concurrency conflict -
    an API layer can map this to 403 (policy) vs 409 (conflict).
    """


@dataclass
class ReviewWorkflow:
    store: PackageStore
    policy: ReviewPolicy = field(default_factory=ReviewPolicy)

    def transition(
        self,
        package_id: str,
        package_version: str,
        *,
        to_status: str,
        actor: Identity,
        reason: str | None = None,
    ) -> PackageRecord:
        record = self.store.get(package_id, package_version)
        if record is None:
            raise StoreError(f"no such package_version: {package_id}/{package_version}")

        from_status = record.status
        if (from_status, to_status) not in TRANSITIONS:
            raise ReviewPolicyError(
                f"{from_status!r} -> {to_status!r} is not an allowed review transition "
                f"(allowed: {sorted(TRANSITIONS)})"
            )

        if to_status == "in_review":
            self._check_submit(record, actor)
        elif to_status in ("approved", "rejected"):
            self._check_decide(record, actor, to_status, reason)
        # in_review -> draft (withdraw) and rejected -> draft (revise) carry no extra policy
        # beyond appearing in TRANSITIONS - any authenticated actor may pull their own work back.

        return self.store.set_status(
            package_id,
            package_version,
            from_status=from_status,
            to_status=to_status,
            actor=actor,
            reason=reason,
        )

    def _check_submit(self, record: PackageRecord, actor: Identity) -> None:
        if not actor.has_role(Role.ANALYST):
            raise ReviewPolicyError(
                f"actor {actor.id!r} may not submit {record.package_id}/{record.package_version} for "
                "review - requires the analyst role (or admin)"
            )
        if self.policy.gate_before_review:
            report = self._rerun_gate(record)
            if report["overall"] != "pass":
                failing = [r["check_id"] for r in report["results"] if r["result"] == "fail" and not r["waived"]]
                raise ReviewPolicyError(
                    "gate-before-review policy blocks submission: ap-gate check fails on "
                    f"{', '.join(failing)} - fix (or waive with a reason in qa.waivers) before "
                    "moving to in_review, or set ReviewPolicy.gate_before_review=False to override"
                )

    def _check_decide(self, record: PackageRecord, actor: Identity, to_status: str, reason: str | None) -> None:
        if not actor.has_role(Role.REVIEWER):
            raise ReviewPolicyError(
                f"actor {actor.id!r} may not approve/reject {record.package_id}/{record.package_version} "
                "- requires the reviewer role (or admin)"
            )
        if (
            not self.policy.allow_self_review
            and not actor.has_role(Role.ADMIN)
            and record.analyst_id is not None
            and actor.id == record.analyst_id
        ):
            raise ReviewPolicyError(
                f"actor {actor.id!r} is both the analyst and the reviewer of "
                f"{record.package_id}/{record.package_version}; ReviewPolicy.allow_self_review is "
                "False (the default), so a distinct reviewer identity is required - set "
                "allow_self_review=True to allow self-approval for small teams"
            )
        if to_status == "rejected" and not (reason and reason.strip()):
            raise ReviewPolicyError("rejecting a package requires a non-empty reason")

    def _rerun_gate(self, record: PackageRecord) -> dict[str, Any]:
        """Re-run the real gate against the package's immutable stored bytes (extracted to a temp dir)."""
        with tempfile.TemporaryDirectory(prefix="ap-review-gate-") as tmp:
            pkg_dir = self.store.extract(record.package_id, record.package_version, Path(tmp) / "pkg")
            manifest = load_manifest(pkg_dir)
            ctx = CheckContext(package_path=pkg_dir, manifest=manifest)
            outcomes = run_all(ctx)
            return build_report(
                package_id=record.package_id,
                title=str(manifest.get("title", "")),
                as_of=str(manifest.get("as_of", "")),
                qa_status=str((manifest.get("qa") or {}).get("status", "")),
                profile=str(manifest.get("profile", "")),
                outcomes=outcomes,
            )
