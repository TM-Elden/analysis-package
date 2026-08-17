"""PackageStore: the C3 package store.

Persists published packages (content-addressed bytes + a SQLite metadata index) and supports
retrieval and filtered/paginated listing. Deliberately dependency-light per the phase-2 brief: no
external database service, just the stdlib (`sqlite3`, `tarfile`, `gzip`) plus `ap_gate` itself for
manifest loading and gate evaluation - this module never re-implements gate logic (see
PackageStore.publish, which calls `ap_gate.checks.registry.run_all`, the exact function `ap-gate
check` uses).

Immutability: a given `(package_id, package_version)` is written once. Publishing the same pair
again with byte-identical content is a no-op (idempotent retry, e.g. an agent retrying after a
network hiccup); publishing it again with *different* content raises ImmutabilityError - an edit
must bump `package_version` and publish that as a new row, never overwrite. `status`, however, is a
mutable column: it is the live review/lifecycle workflow status (ap_review, plus ap_lifecycle's
supersede/recall/purge states layered on top - see CLAUDE.md's Phase 5 section), intentionally
decoupled from whatever `qa.status` the immutable manifest happened to declare at publish time (see
ap_store.db module docstring, and CLAUDE.md).

Single-tenant by design - see ap_store.db.
"""

from __future__ import annotations

import datetime as dt
import json
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ap_auth.identity import Identity
from ap_gate.checks.context import CheckContext
from ap_gate.checks.registry import run_all
from ap_gate.load_manifest import load_manifest
from ap_gate.report.model import build_report
from ap_redact.report import sidecar_path
from ap_store.blobstore import BlobStore, blob_sha256, make_blob
from ap_store.db import connect
from ap_store.models import AuditEntry, PackageRecord


class StoreError(Exception):
    """Base for store-level errors (distinct from a gate failure, which is not an error - see publish)."""


class ImmutabilityError(StoreError):
    """A publish would overwrite an existing (package_id, package_version) with different content."""


def _utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass
class ListFilter:
    profile: str | None = None
    status: str | None = None
    owner: str | None = None  # matches analyst_id OR reviewer_id
    as_of_from: str | None = None
    as_of_to: str | None = None
    query: str | None = None  # free-text substring match against title
    page: int = 1
    page_size: int = 20


@dataclass
class ListPage:
    items: list[PackageRecord] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


@dataclass
class StoreStats:
    """Tier-1 gate-analytics dashboard input (design report `data/fathm-phase5-readiness/
    report.md` section 5.2): plain `GROUP BY` counts over columns that are never a person
    identifier - `status`, `profile`, `gate_overall`. Deliberately does not select `analyst_id` /
    `reviewer_id` (present on this same table) or anything from `owners_json` - see
    `PackageStore.stats`'s docstring and CLAUDE.md's dashboard section."""

    total: int = 0
    status_counts: dict[str, int] = field(default_factory=dict)
    profile_counts: dict[str, int] = field(default_factory=dict)
    gate_overall_counts: dict[str, int] = field(default_factory=dict)


class PackageStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.blob_store = BlobStore(self.root / "blobs")
        self.conn = connect(self.root / "index.sqlite3")
        # ap_api's FastAPI sync route handlers each run in their own threadpool worker thread, so
        # one PackageStore (and its one sqlite3 connection, opened check_same_thread=False) is
        # shared across threads. RLock (not Lock) because publish()/set_status() call the _get_row
        # / get() helpers internally while already holding the lock.
        self._lock = threading.RLock()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "PackageStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- publish --------------------------------------------------------

    def publish(
        self,
        package_dir: Path | str,
        *,
        actor: Identity,
        gate_report: dict[str, Any] | None = None,
    ) -> PackageRecord:
        """Publish a package directory as an immutable package_version.

        Runs ap-gate's own check logic to record gate status at publish time. Publishing does NOT
        require a passing gate: C3's contract is "gate status recorded with each publish", not
        "gate blocks publish" - the policy knob that requires a pass is ap_review's
        gate-before-review, evaluated later at the draft -> in_review transition, not here. This
        mirrors real workflow: an analyst may want a draft visible/shareable before it's polished.
        """
        package_dir = Path(package_dir).resolve()
        manifest = load_manifest(package_dir)
        package_id = manifest.get("package_id")
        package_version = manifest.get("package_version")
        if not isinstance(package_id, str) or not package_id:
            raise StoreError("manifest package_id is missing or empty - cannot publish")
        if not isinstance(package_version, str) or not package_version:
            raise StoreError("manifest package_version is missing or empty - cannot publish")

        blob = make_blob(package_dir)
        sha = blob_sha256(blob)

        with self._lock:
            existing = self._get_row(package_id, package_version)
            if existing is not None:
                if existing["blob_sha256"] == sha:
                    return self._row_to_record(existing)  # idempotent republish, not an error
                raise ImmutabilityError(
                    f"{package_id}/{package_version} is already published with different content - "
                    "bump package_version for an edit; a published version is never mutated in place"
                )

            self.blob_store.put(blob, sha)

            if gate_report is None:
                ctx = CheckContext(package_path=package_dir, manifest=manifest)
                outcomes = run_all(ctx)
                gate_report = build_report(
                    package_id=package_id,
                    title=str(manifest.get("title", "")),
                    as_of=str(manifest.get("as_of", "")),
                    qa_status=str((manifest.get("qa") or {}).get("status", "")),
                    profile=str(manifest.get("profile", "")),
                    outcomes=outcomes,
                )

            owners = manifest.get("owners") or {}
            analyst_id = (owners.get("analyst") or {}).get("id")
            reviewer_id = (owners.get("reviewer") or {}).get("id")
            status = "draft"
            now = _utcnow()

            with self.conn:
                self.conn.execute(
                    """INSERT INTO packages (
                        package_id, package_version, profile, title, as_of, created_at, status,
                        blob_sha256, analyst_id, reviewer_id, owners_json, gate_overall,
                        published_by_id, published_by_roles, replaces_package_id, replaces_package_version
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        package_id,
                        package_version,
                        str(manifest.get("profile", "")),
                        str(manifest.get("title", "")),
                        str(manifest.get("as_of", "")),
                        now,
                        status,
                        sha,
                        analyst_id,
                        reviewer_id,
                        json.dumps(owners),
                        gate_report["overall"],
                        actor.id,
                        actor.roles_csv(),
                        None,
                        None,
                    ),
                )
                self._insert_audit(package_id, package_version, None, status, actor, "published")

            return self._row_to_record(self._get_row(package_id, package_version))

    # -- retrieval --------------------------------------------------------

    def get(self, package_id: str, package_version: str | None = None) -> PackageRecord | None:
        """Retrieve a specific version, or the most recently published version if version is None.
        `created_at` is second-precision (`_utcnow`), so two versions published within the same
        second tie on it - `rowid DESC` breaks the tie deterministically in insertion order (rowid
        is monotonically increasing per insert), so "most recently published" stays correct even
        for a rapid republish. This matters beyond tests: `ap_console`'s NC.3 citation-actions
        lookup (`routes.py::_citation_review_context`) depends on this exact "latest version" read
        being right every time, not just usually."""
        with self._lock:
            if package_version is not None:
                row = self._get_row(package_id, package_version)
                return self._row_to_record(row) if row else None
            row = self.conn.execute(
                "SELECT * FROM packages WHERE package_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1",
                (package_id,),
            ).fetchone()
            return self._row_to_record(row) if row else None

    def extract(self, package_id: str, package_version: str, dest_dir: Path | str) -> Path:
        """Materialize a published version's bytes back onto disk (e.g. to re-run the gate)."""
        record = self.get(package_id, package_version)
        if record is None:
            raise StoreError(f"no such package_version: {package_id}/{package_version}")
        dest_dir = Path(dest_dir)
        self.blob_store.extract(record.blob_sha256, dest_dir)
        return dest_dir

    def list(self, filt: ListFilter | None = None) -> ListPage:
        filt = filt or ListFilter()
        clauses: list[str] = []
        params: list[Any] = []
        if filt.profile:
            clauses.append("profile = ?")
            params.append(filt.profile)
        if filt.status:
            clauses.append("status = ?")
            params.append(filt.status)
        if filt.owner:
            clauses.append("(analyst_id = ? OR reviewer_id = ?)")
            params.extend([filt.owner, filt.owner])
        if filt.as_of_from:
            clauses.append("as_of >= ?")
            params.append(filt.as_of_from)
        if filt.as_of_to:
            clauses.append("as_of <= ?")
            params.append(filt.as_of_to)
        if filt.query:
            clauses.append("title LIKE ?")
            params.append(f"%{filt.query}%")
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        page = max(1, filt.page)
        page_size = max(1, min(filt.page_size, 200))
        offset = (page - 1) * page_size

        with self._lock:
            total = self.conn.execute(f"SELECT COUNT(*) FROM packages {where}", params).fetchone()[0]
            rows = self.conn.execute(
                f"SELECT * FROM packages {where} ORDER BY as_of DESC, created_at DESC LIMIT ? OFFSET ?",
                [*params, page_size, offset],
            ).fetchall()
            return ListPage(items=[self._row_to_record(r) for r in rows], total=total, page=page, page_size=page_size)

    def stats(self) -> StoreStats:
        """Instant, scan-free counts for the gate-analytics dashboard's tier 1 (design report
        section 5.2). Every `GROUP BY` here is over `status` / `profile` / `gate_overall` only -
        no `analyst_id`/`reviewer_id`/`owners_json` column is ever selected, by construction, so
        this method cannot regress into the author-keyed aggregation the dashboard's hard
        invariant forbids (see CLAUDE.md)."""
        with self._lock:
            total = self.conn.execute("SELECT COUNT(*) FROM packages").fetchone()[0]
            status_rows = self.conn.execute("SELECT status, COUNT(*) FROM packages GROUP BY status").fetchall()
            profile_rows = self.conn.execute("SELECT profile, COUNT(*) FROM packages GROUP BY profile").fetchall()
            gate_rows = self.conn.execute(
                "SELECT gate_overall, COUNT(*) FROM packages GROUP BY gate_overall"
            ).fetchall()
        return StoreStats(
            total=total,
            status_counts={r[0]: r[1] for r in status_rows},
            profile_counts={r[0]: r[1] for r in profile_rows},
            gate_overall_counts={r[0]: r[1] for r in gate_rows},
        )

    # -- workflow support (called by ap_review, not policy-aware itself) --

    def set_status(
        self,
        package_id: str,
        package_version: str,
        *,
        from_status: str,
        to_status: str,
        actor: Identity,
        reason: str | None = None,
    ) -> PackageRecord:
        """Compare-and-swap status update + audit row.

        This method enforces no review policy itself (role checks, reject-requires-reason,
        gate-before-review) - that is ap_review.workflow's job, which calls this only after its
        policy checks pass. It does enforce optimistic concurrency: the UPDATE only matches a row
        currently in `from_status`, so two concurrent transitions can't both "succeed" from a stale
        read.
        """
        with self._lock, self.conn:
            cur = self.conn.execute(
                "UPDATE packages SET status=? WHERE package_id=? AND package_version=? AND status=?",
                (to_status, package_id, package_version, from_status),
            )
            if cur.rowcount == 0:
                current = self._get_row(package_id, package_version)
                if current is None:
                    raise StoreError(f"no such package_version: {package_id}/{package_version}")
                raise StoreError(
                    f"expected {package_id}/{package_version} to be '{from_status}' but it is "
                    f"'{current['status']}' - concurrent transition or stale caller state"
                )
            self._insert_audit(package_id, package_version, from_status, to_status, actor, reason)
            return self._row_to_record(self._get_row(package_id, package_version))

    # -- C12 lifecycle mechanism (policy lives in ap_lifecycle.LifecycleWorkflow) -----------------

    def link_replaces(
        self,
        package_id: str,
        package_version: str,
        *,
        replaces_package_id: str,
        replaces_package_version: str,
        actor: Identity,
    ) -> PackageRecord:
        """Write the successor's `replaces_*` columns - the supersede link. An audited one-column
        (pair) UPDATE, same shape as `set_status`, but not a status transition itself: the caller
        (`ap_lifecycle.LifecycleWorkflow.supersede`) separately flips the predecessor's own status
        to `superseded` via `set_status`."""
        with self._lock, self.conn:
            cur = self.conn.execute(
                "UPDATE packages SET replaces_package_id=?, replaces_package_version=? "
                "WHERE package_id=? AND package_version=?",
                (replaces_package_id, replaces_package_version, package_id, package_version),
            )
            if cur.rowcount == 0:
                raise StoreError(f"no such package_version: {package_id}/{package_version}")
            self._insert_audit(
                package_id,
                package_version,
                None,
                "replaces_linked",
                actor,
                f"replaces {replaces_package_id}/{replaces_package_version}",
            )
            return self._row_to_record(self._get_row(package_id, package_version))

    def set_legal_hold(
        self,
        package_id: str,
        package_version: str,
        *,
        hold: bool,
        reason: str | None,
        actor: Identity,
    ) -> PackageRecord:
        """Set or clear the legal-hold flag. Mechanism only (admin-only enforcement, and requiring
        a reason to *set* a hold, are `ap_lifecycle.LifecycleWorkflow`'s job) - writes a
        `package_audit` row exactly like a status transition, using `legal_hold_set`/
        `legal_hold_cleared` as the (pseudo) `to_status` value since this is not itself a status
        change."""
        with self._lock, self.conn:
            cur = self.conn.execute(
                "UPDATE packages SET legal_hold=?, legal_hold_reason=? WHERE package_id=? AND package_version=?",
                (1 if hold else 0, reason if hold else None, package_id, package_version),
            )
            if cur.rowcount == 0:
                raise StoreError(f"no such package_version: {package_id}/{package_version}")
            self._insert_audit(
                package_id,
                package_version,
                None,
                "legal_hold_set" if hold else "legal_hold_cleared",
                actor,
                reason,
            )
            return self._row_to_record(self._get_row(package_id, package_version))

    def purge(self, package_id: str, package_version: str, *, actor: Identity, reason: str | None = None) -> PackageRecord:
        """The first genuinely irreversible operation in the product. Mechanism only - the admin
        role check and the "recall/supersede first" nudge live in `ap_lifecycle.LifecycleWorkflow`
        - but the two hard safety invariants (never purge an `approved` package, never purge under
        legal hold) are enforced here too, defense-in-depth, the same double-check discipline
        `ap_manager_bot.scoping` applies to confidentiality: a caller that reaches this method by
        any path but the workflow still cannot destroy an approved or held package.

        Deletes the blob only if no other non-purged package row shares its `blob_sha256` (blobs
        are content-addressed and shared - see ap_store.blobstore); deletes the C14 redaction
        sidecar; tombstones the row (`purged_at` set, `status` -> `purged`, content-bearing
        metadata blanked, `package_id`/`package_version`/audit history kept) so audit rows,
        proposal evidence links, and supersede chains resolve to an honest "purged" record instead
        of dangling. Does NOT touch the C4 search index - purge is not wired into
        `ap_index.reindex.reindex_package`'s approved-only rule (that would require this module to
        import `ap_index`, which would be circular: `ap_index.reindex` already imports
        `ap_store.store`). A purge caller must separately call `IndexStore.remove_package` -
        same "call stays in the caller, not the workflow/store" layering the reindex-wiring fix
        elsewhere in this task established, documented in `ap_lifecycle`'s module docstring.
        """
        with self._lock, self.conn:
            row = self._get_row(package_id, package_version)
            if row is None:
                raise StoreError(f"no such package_version: {package_id}/{package_version}")
            if row["purged_at"]:
                return self._row_to_record(row)  # idempotent: already purged
            if row["status"] == "approved":
                raise StoreError(
                    f"cannot purge {package_id}/{package_version} - it is 'approved'; recall or "
                    "supersede it first"
                )
            if row["legal_hold"]:
                raise StoreError(
                    f"cannot purge {package_id}/{package_version} - it is under legal hold "
                    f"({row['legal_hold_reason']!r}); clear the hold first"
                )

            blob_sha = row["blob_sha256"]
            other_refs = self.conn.execute(
                "SELECT COUNT(*) FROM packages WHERE blob_sha256=? "
                "AND NOT (package_id=? AND package_version=?) AND purged_at IS NULL",
                (blob_sha, package_id, package_version),
            ).fetchone()[0]
            if other_refs == 0:
                self.blob_store.delete(blob_sha)

            sidecar = sidecar_path(self.root, package_id, package_version)
            if sidecar.is_file():
                sidecar.unlink()

            now = _utcnow()
            self.conn.execute(
                """UPDATE packages SET status='purged', purged_at=?, title='', as_of='',
                   owners_json='{}', analyst_id=NULL, reviewer_id=NULL
                   WHERE package_id=? AND package_version=?""",
                (now, package_id, package_version),
            )
            self._insert_audit(package_id, package_version, row["status"], "purged", actor, reason)
            return self._row_to_record(self._get_row(package_id, package_version))

    # -- retention marker (C12; get_setting/set_setting mechanism below is shared with P5.3's -----
    # admin tab settings) --------------------------------------------------------------------------

    RETENTION_DAYS_KEY = "retention_days"

    def get_retention_days(self) -> int | None:
        """No automatic deletion reads this - it is purely a marker a human (or a future retention
        screen, §5.5, out of scope here) uses to decide which packages are due for review."""
        value = self.get_setting(self.RETENTION_DAYS_KEY)
        return int(value) if value is not None else None

    def set_retention_days(self, days: int, *, actor: Identity) -> None:
        if days < 0:
            raise StoreError("retention_days must be >= 0")
        self.set_setting(self.RETENTION_DAYS_KEY, str(days), actor=actor)

    def audit_trail(self, package_id: str, package_version: str) -> list[AuditEntry]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM package_audit WHERE package_id=? AND package_version=? ORDER BY id ASC",
                (package_id, package_version),
            ).fetchall()
        return [
            AuditEntry(
                id=r["id"],
                package_id=r["package_id"],
                package_version=r["package_version"],
                from_status=r["from_status"],
                to_status=r["to_status"],
                actor_id=r["actor_id"],
                actor_roles=r["actor_roles"],
                reason=r["reason"],
                ts=r["ts"],
            )
            for r in rows
        ]

    # -- store settings (P5.3 admin tab; retention_days et al.) ----------

    def get_setting(self, key: str) -> str | None:
        with self._lock:
            row = self.conn.execute("SELECT value FROM store_settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else None

    def set_setting(self, key: str, value: str, *, actor: Identity) -> None:
        """Upsert one `store_settings` row and append a `store_settings_audit` row in the same
        transaction (old value, new value, actor, when) - mirrors `_insert_audit`'s "mutation and
        its audit row are never observably split" discipline."""
        with self._lock, self.conn:
            existing = self.conn.execute("SELECT value FROM store_settings WHERE key=?", (key,)).fetchone()
            old_value = existing["value"] if existing else None
            self.conn.execute(
                "INSERT INTO store_settings (key, value, updated_at, updated_by_id, updated_by_roles) "
                "VALUES (?,?,?,?,?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at, "
                "updated_by_id=excluded.updated_by_id, updated_by_roles=excluded.updated_by_roles",
                (key, value, _utcnow(), actor.id, actor.roles_csv()),
            )
            self.conn.execute(
                "INSERT INTO store_settings_audit (key, old_value, new_value, actor_id, actor_roles, ts) "
                "VALUES (?,?,?,?,?,?)",
                (key, old_value, value, actor.id, actor.roles_csv(), _utcnow()),
            )

    def settings_audit_trail(self, key: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            if key is None:
                rows = self.conn.execute("SELECT * FROM store_settings_audit ORDER BY id DESC").fetchall()
            else:
                rows = self.conn.execute(
                    "SELECT * FROM store_settings_audit WHERE key=? ORDER BY id DESC", (key,)
                ).fetchall()
        return [dict(r) for r in rows]

    # -- internals --------------------------------------------------------

    def _get_row(self, package_id: str, package_version: str):
        return self.conn.execute(
            "SELECT * FROM packages WHERE package_id=? AND package_version=?",
            (package_id, package_version),
        ).fetchone()

    def _insert_audit(
        self,
        package_id: str,
        package_version: str,
        from_status: str | None,
        to_status: str,
        actor: Identity,
        reason: str | None,
    ) -> None:
        self.conn.execute(
            """INSERT INTO package_audit
               (package_id, package_version, from_status, to_status, actor_id, actor_roles, reason, ts)
               VALUES (?,?,?,?,?,?,?,?)""",
            (package_id, package_version, from_status, to_status, actor.id, actor.roles_csv(), reason, _utcnow()),
        )

    def _row_to_record(self, row) -> PackageRecord:
        return PackageRecord(
            package_id=row["package_id"],
            package_version=row["package_version"],
            profile=row["profile"],
            title=row["title"],
            as_of=row["as_of"],
            created_at=row["created_at"],
            status=row["status"],
            blob_sha256=row["blob_sha256"],
            analyst_id=row["analyst_id"],
            reviewer_id=row["reviewer_id"],
            owners_json=row["owners_json"],
            gate_overall=row["gate_overall"],
            published_by_id=row["published_by_id"],
            published_by_roles=row["published_by_roles"],
            replaces_package_id=row["replaces_package_id"],
            replaces_package_version=row["replaces_package_version"],
            legal_hold=bool(row["legal_hold"]),
            legal_hold_reason=row["legal_hold_reason"],
            purged_at=row["purged_at"],
        )
