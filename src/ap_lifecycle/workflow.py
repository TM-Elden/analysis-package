"""LifecycleWorkflow: the C12 package-lifecycle state machine (supersede, recall, restore, legal
hold, purge).

Mirrors `ap_review.ReviewWorkflow`'s policy/mechanism split exactly, over the *same*
`PackageStore.set_status` CAS + audit mechanism (plus the new `link_replaces` / `set_legal_hold` /
`purge` mechanism methods `ap_store.store.PackageStore` gained alongside this module - see that
module's docstrings). This module owns policy (roles, reason-required, hold/approved guards);
`PackageStore` owns mechanism.

**Union state machine.** `ReviewWorkflow.TRANSITIONS` (draft/in_review/approved/rejected) is
untouched - lifecycle states are a *separate* transition set layered on top of it:

    approved   -> superseded   (reviewer or admin; requires naming an existing `approved`
                                 successor package/version - no corpus gaps by construction)
    approved   -> recalled     (reviewer or admin; reason REQUIRED - a recall with no recorded
                                 why is an audit hole)
    recalled   -> approved     (admin only - `restore()`)
    superseded -> approved     (admin only - `restore()`, the symmetric restore path for when a
                                 successor itself gets recalled or purged)

A recalled/superseded package cannot re-enter `ReviewWorkflow`'s review states except through the
admin restore path above; review transitions can never reach a lifecycle state. Both new statuses
drop the package from the C4 search index via `ap_index.reindex.reindex_package`'s existing
approved-only rule - see the reindex-wiring note below.

**Legal hold.** `legal_hold`/`legal_hold_reason` are admin-only to set or clear (`set_legal_hold`),
and a hold blocks **purge only** - recall/supersede stay allowed under hold (they are reversible
status moves; freezing them would let a hold keep bad content live in the corpus).

**Purge** (`purge`) is the first genuinely irreversible action in the product: admin-only, and only
a non-`approved`, non-held package may be purged (recall or supersede an approved package first).
`PackageStore.purge` re-checks both guards itself (defense in depth - see that method's docstring),
so this is not the only thing standing between a caller and destroying live content.

**Reindex-wiring fix (the real bug this task also fixes).** `ap_index.reindex.reindex_package`
correctly computes index membership from a package's *current* store status, but before this task
nothing outside the test suite ever called it - not `ap_review`'s API/console routes, not any
lifecycle transition. In a live deployment this meant an approval never actually reached the bot's
searchable index. The fix is wiring, not a workflow change: `reindex_package` is now called from
the routes layer (`ap_api.app.review_package`, `ap_console.routes.console_review_action`, and this
module's own future routes) immediately after every status-changing call, exactly as this module's
own docstring below insists - the call is deliberately kept OUT of `ReviewWorkflow`/
`LifecycleWorkflow` themselves, preserving the existing rule that `ap_review` (and now
`ap_lifecycle`) must not import `ap_index`. `LifecycleWorkflow.purge` is the one exception: purge
is not wired through `reindex_package` at all (its approved-only rule doesn't apply to a purged
package, and wiring it would still require this module to import `ap_index`) - a purge caller must
separately call `IndexStore.remove_package(package_id, package_version)`, same layering discipline,
different call.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_lifecycle.policy import LifecyclePolicy
from ap_store.models import PackageRecord
from ap_store.store import PackageStore, StoreError

# Allowed (from_status, to_status) pairs - a separate set from ap_review.workflow.TRANSITIONS,
# deliberately not merged with it (see module docstring).
TRANSITIONS: frozenset[tuple[str, str]] = frozenset(
    {
        ("approved", "superseded"),
        ("approved", "recalled"),
        ("recalled", "approved"),
        ("superseded", "approved"),
    }
)


class LifecyclePolicyError(StoreError):
    """A lifecycle action was attempted but role/reason/hold/approved-only policy forbids it.

    Distinct from the plain StoreError PackageStore's CAS methods raise on a concurrency conflict
    or a missing row - an API layer can map this to 403 (policy) vs 404/409 (not found/conflict),
    mirroring ReviewPolicyError's role in ap_review.
    """


@dataclass
class LifecycleWorkflow:
    store: PackageStore
    policy: LifecyclePolicy = field(default_factory=LifecyclePolicy)

    # -- supersede / recall / restore --------------------------------------------------------

    def supersede(
        self,
        package_id: str,
        package_version: str,
        *,
        successor_package_id: str,
        successor_package_version: str,
        actor: Identity,
        reason: str | None = None,
    ) -> PackageRecord:
        record = self._require(package_id, package_version)
        self._require_transition(record.status, "superseded")
        self._require_reviewer_or_admin(actor, "supersede")
        if (successor_package_id, successor_package_version) == (package_id, package_version):
            raise LifecyclePolicyError("a package cannot supersede itself")
        successor = self.store.get(successor_package_id, successor_package_version)
        if successor is None or successor.status != "approved":
            raise LifecyclePolicyError(
                f"successor {successor_package_id!r}/{successor_package_version!r} must be an "
                "existing, currently-approved package/version"
            )
        updated = self.store.set_status(
            package_id, package_version, from_status="approved", to_status="superseded", actor=actor, reason=reason
        )
        self.store.link_replaces(
            successor_package_id,
            successor_package_version,
            replaces_package_id=package_id,
            replaces_package_version=package_version,
            actor=actor,
        )
        return updated

    def recall(
        self,
        package_id: str,
        package_version: str,
        *,
        actor: Identity,
        reason: str,
    ) -> PackageRecord:
        record = self._require(package_id, package_version)
        self._require_transition(record.status, "recalled")
        self._require_reviewer_or_admin(actor, "recall")
        if not (reason and reason.strip()):
            raise LifecyclePolicyError("recalling a package requires a non-empty reason")
        return self.store.set_status(
            package_id, package_version, from_status="approved", to_status="recalled", actor=actor, reason=reason
        )

    def restore(
        self,
        package_id: str,
        package_version: str,
        *,
        actor: Identity,
        reason: str | None = None,
    ) -> PackageRecord:
        """`recalled -> approved` or `superseded -> approved` - admin only either way (C12's
        "recall is reversible only by admin"; superseded restore is the symmetric path for when a
        successor itself gets recalled or purged)."""
        record = self._require(package_id, package_version)
        if record.status not in ("recalled", "superseded"):
            raise LifecyclePolicyError(
                f"cannot restore {package_id}/{package_version} from status {record.status!r} - "
                "only a 'recalled' or 'superseded' package can be restored"
            )
        if not actor.has_role(Role.ADMIN):
            raise LifecyclePolicyError(f"actor {actor.id!r} may not restore a package - requires admin")
        return self.store.set_status(
            package_id, package_version, from_status=record.status, to_status="approved", actor=actor, reason=reason
        )

    # -- legal hold -----------------------------------------------------------------------------

    def set_legal_hold(
        self,
        package_id: str,
        package_version: str,
        *,
        hold: bool,
        reason: str | None,
        actor: Identity,
    ) -> PackageRecord:
        self._require(package_id, package_version)
        if not actor.has_role(Role.ADMIN):
            raise LifecyclePolicyError(f"actor {actor.id!r} may not set/clear legal hold - requires admin")
        if hold and not (reason and reason.strip()):
            raise LifecyclePolicyError("setting a legal hold requires a non-empty reason")
        return self.store.set_legal_hold(package_id, package_version, hold=hold, reason=reason, actor=actor)

    # -- retention marker -------------------------------------------------------------------------

    def get_retention_days(self) -> int | None:
        return self.store.get_retention_days()

    def set_retention_days(self, days: int, *, actor: Identity) -> None:
        if not actor.has_role(Role.ADMIN):
            raise LifecyclePolicyError(f"actor {actor.id!r} may not set retention_days - requires admin")
        self.store.set_retention_days(days, actor=actor)

    # -- purge ------------------------------------------------------------------------------------

    def purge(self, package_id: str, package_version: str, *, actor: Identity, reason: str | None = None) -> PackageRecord:
        record = self._require(package_id, package_version)
        if not actor.has_role(Role.ADMIN):
            raise LifecyclePolicyError(f"actor {actor.id!r} may not purge a package - requires admin")
        if record.status == "approved":
            raise LifecyclePolicyError(
                f"cannot purge {package_id}/{package_version} - it is 'approved'; recall or supersede it first"
            )
        if record.legal_hold:
            raise LifecyclePolicyError(
                f"cannot purge {package_id}/{package_version} - it is under legal hold "
                f"({record.legal_hold_reason!r}); clear the hold first"
            )
        return self.store.purge(package_id, package_version, actor=actor, reason=reason)

    # -- internals ----------------------------------------------------------------------------

    def _require(self, package_id: str, package_version: str) -> PackageRecord:
        record = self.store.get(package_id, package_version)
        if record is None:
            raise StoreError(f"no such package_version: {package_id}/{package_version}")
        return record

    def _require_transition(self, from_status: str, to_status: str) -> None:
        if (from_status, to_status) not in TRANSITIONS:
            raise LifecyclePolicyError(
                f"{from_status!r} -> {to_status!r} is not an allowed lifecycle transition "
                f"(allowed: {sorted(TRANSITIONS)})"
            )

    def _require_reviewer_or_admin(self, actor: Identity, action: str) -> None:
        if not (actor.has_role(Role.REVIEWER) or actor.has_role(Role.ADMIN)):
            raise LifecyclePolicyError(f"actor {actor.id!r} may not {action} a package - requires reviewer (or admin)")
