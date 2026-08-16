"""ProposalStore: the C6/C7 proposal store (mechanism layer).

Persists Standard-change proposals and their audit trail in a sibling SQLite database (see
`ap_proposals` module docstring). Mirrors `ap_store.PackageStore`'s shape deliberately: `create`
is the analogue of `publish` (validates and inserts once), `set_status` is the same
compare-and-swap-plus-audit-row mechanism `PackageStore.set_status` uses, and this module enforces
no decision policy itself - that is `ap_proposals.workflow.ProposalWorkflow`'s job, exactly the
policy/mechanism split `ap_review.ReviewWorkflow` / `ap_store.PackageStore` already use.
"""

from __future__ import annotations

import datetime as dt
import json
import secrets
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ap_auth.identity import Identity
from ap_proposals.db import connect
from ap_proposals.kinds import validate_diff
from ap_proposals.models import ProposalAuditEntry, ProposalRecord


class ProposalStoreError(Exception):
    """Base for store-level errors (distinct from ProposalPolicyError - see ap_proposals.workflow)."""


def _utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _new_proposal_id() -> str:
    return f"prop_{secrets.token_urlsafe(16)}"


@dataclass
class ListFilter:
    status: str | None = None
    kind: str | None = None
    created_by: str | None = None
    page: int = 1
    page_size: int = 20


@dataclass
class ListPage:
    items: list[ProposalRecord] = field(default_factory=list)
    total: int = 0
    page: int = 1
    page_size: int = 20


class ProposalStore:
    def __init__(self, root: Path | str):
        self.root = Path(root)
        self.conn = connect(self.root / "proposals.sqlite3")
        # Same reasoning as PackageStore / AuthStore: ap_api's FastAPI sync route handlers each run
        # in their own threadpool worker thread, so one connection (opened check_same_thread=False)
        # is shared across threads, guarded by an RLock (not Lock - create()/set_status() call the
        # _get_row()/get() helpers internally while already holding the lock).
        self._lock = threading.RLock()

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "ProposalStore":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- create -----------------------------------------------------------

    def create(
        self,
        *,
        kind: str,
        summary: str,
        rationale: str,
        diff: dict[str, Any],
        evidence: dict[str, Any],
        actor: Identity,
    ) -> ProposalRecord:
        """Create a new proposal in `pending_hitl`. Validates `diff` against `kind`'s schema
        (`ap_proposals.kinds.validate_diff`) before writing - a proposal is never stored with a
        malformed diff. Raises `ap_proposals.kinds.ProposalValidationError` on a bad kind/diff."""
        validate_diff(kind, diff)
        if not summary or not summary.strip():
            raise ProposalStoreError("summary must be non-empty")
        if not rationale or not rationale.strip():
            raise ProposalStoreError("rationale must be non-empty")

        proposal_id = _new_proposal_id()
        now = _utcnow()
        status = "pending_hitl"

        with self._lock, self.conn:
            self.conn.execute(
                """INSERT INTO proposals (
                    proposal_id, created_at, kind, summary, rationale, diff_json, evidence_json,
                    status, created_by_id, created_by_roles, decided_by_id, decided_at,
                    decision_reason, edited_diff_json, dry_run_json, applied_version, applied_at,
                    spec_artifact_path
                ) VALUES (?,?,?,?,?,?,?,?,?,?,NULL,NULL,NULL,NULL,NULL,NULL,NULL,NULL)""",
                (
                    proposal_id,
                    now,
                    kind,
                    summary,
                    rationale,
                    json.dumps(diff),
                    json.dumps(evidence),
                    status,
                    actor.id,
                    actor.roles_csv(),
                ),
            )
            self._insert_audit(proposal_id, None, status, actor, "created")

        return self._row_to_record(self._get_row(proposal_id))

    # -- retrieval ----------------------------------------------------------

    def get(self, proposal_id: str) -> ProposalRecord | None:
        with self._lock:
            row = self._get_row(proposal_id)
            return self._row_to_record(row) if row else None

    def list(self, filt: ListFilter | None = None) -> ListPage:
        filt = filt or ListFilter()
        clauses: list[str] = []
        params: list[Any] = []
        if filt.status:
            clauses.append("status = ?")
            params.append(filt.status)
        if filt.kind:
            clauses.append("kind = ?")
            params.append(filt.kind)
        if filt.created_by:
            clauses.append("created_by_id = ?")
            params.append(filt.created_by)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

        page = max(1, filt.page)
        page_size = max(1, min(filt.page_size, 200))
        offset = (page - 1) * page_size

        with self._lock:
            total = self.conn.execute(f"SELECT COUNT(*) FROM proposals {where}", params).fetchone()[0]
            rows = self.conn.execute(
                f"SELECT * FROM proposals {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
                [*params, page_size, offset],
            ).fetchall()
            return ListPage(items=[self._row_to_record(r) for r in rows], total=total, page=page, page_size=page_size)

    # -- workflow support (called by ap_proposals.workflow, not policy-aware itself) -------------

    def set_status(
        self,
        proposal_id: str,
        *,
        from_status: str,
        to_status: str,
        actor: Identity,
        reason: str | None = None,
        edited_diff: dict[str, Any] | None = None,
        applied_version: str | None = None,
        spec_artifact_path: str | None = None,
    ) -> ProposalRecord:
        """Compare-and-swap status update + audit row, mirroring `PackageStore.set_status`.

        `edited_diff` (approve-with-edits), `applied_version` (declarative-kind apply, see
        `ap_proposals.apply.apply_declarative`), and `spec_artifact_path` (code-kind apply, see
        `ap_proposals.apply.export_spec`) are written in this same transaction as the decision -
        the extension point the apply-mechanism task (`ap_proposals.workflow.ProposalWorkflow.decide`)
        uses to make "approved with the apply step applied" one atomic outcome, per the C7 contract
        that an approval can never be silently unapplied: the caller performs the apply step
        (registry write or spec export) *before* calling this method, and only calls it at all if
        that step succeeded - so a failed apply never reaches this UPDATE and the proposal simply
        stays in its prior status. This method enforces no decision policy itself (roles,
        reject-requires-reason) - that is `ap_proposals.workflow.ProposalWorkflow`'s job, which
        calls this only after its policy checks (and any apply step) pass.
        """
        decided_at = _utcnow() if to_status in ("approved", "rejected") else None
        with self._lock, self.conn:
            cur = self.conn.execute(
                """UPDATE proposals SET
                       status=?,
                       decided_by_id=COALESCE(?, decided_by_id),
                       decided_at=COALESCE(?, decided_at),
                       decision_reason=COALESCE(?, decision_reason),
                       edited_diff_json=COALESCE(?, edited_diff_json),
                       applied_version=COALESCE(?, applied_version),
                       applied_at=COALESCE(?, applied_at),
                       spec_artifact_path=COALESCE(?, spec_artifact_path)
                   WHERE proposal_id=? AND status=?""",
                (
                    to_status,
                    actor.id if decided_at else None,
                    decided_at,
                    reason,
                    json.dumps(edited_diff) if edited_diff is not None else None,
                    applied_version,
                    _utcnow() if applied_version else None,
                    spec_artifact_path,
                    proposal_id,
                    from_status,
                ),
            )
            if cur.rowcount == 0:
                current = self._get_row(proposal_id)
                if current is None:
                    raise ProposalStoreError(f"no such proposal: {proposal_id}")
                raise ProposalStoreError(
                    f"expected {proposal_id} to be '{from_status}' but it is '{current['status']}' - "
                    "concurrent decision or stale caller state"
                )
            self._insert_audit(proposal_id, from_status, to_status, actor, reason)
            return self._row_to_record(self._get_row(proposal_id))

    def record_dry_run(self, proposal_id: str, dry_run_json: dict[str, Any]) -> ProposalRecord:
        """Persist a dry-run result on a still-`pending_hitl` proposal (§5.6: "mandatory-at-
        decision, not decorative" - `ProposalWorkflow.decide` refuses to approve a declarative-kind
        proposal until this has been called at least once). Not a status transition - no audit row,
        no actor/reason bookkeeping, callable any number of times (each call overwrites the prior
        result with the latest run)."""
        with self._lock, self.conn:
            cur = self.conn.execute(
                "UPDATE proposals SET dry_run_json=? WHERE proposal_id=?",
                (json.dumps(dry_run_json), proposal_id),
            )
            if cur.rowcount == 0:
                raise ProposalStoreError(f"no such proposal: {proposal_id}")
            return self._row_to_record(self._get_row(proposal_id))

    def audit_trail(self, proposal_id: str) -> list[ProposalAuditEntry]:
        with self._lock:
            rows = self.conn.execute(
                "SELECT * FROM proposal_audit WHERE proposal_id=? ORDER BY id ASC",
                (proposal_id,),
            ).fetchall()
        return [
            ProposalAuditEntry(
                id=r["id"],
                proposal_id=r["proposal_id"],
                from_status=r["from_status"],
                to_status=r["to_status"],
                actor_id=r["actor_id"],
                actor_roles=r["actor_roles"],
                reason=r["reason"],
                ts=r["ts"],
            )
            for r in rows
        ]

    # -- internals ----------------------------------------------------------

    def _get_row(self, proposal_id: str):
        return self.conn.execute(
            "SELECT * FROM proposals WHERE proposal_id=?", (proposal_id,)
        ).fetchone()

    def _insert_audit(
        self,
        proposal_id: str,
        from_status: str | None,
        to_status: str,
        actor: Identity,
        reason: str | None,
    ) -> None:
        self.conn.execute(
            """INSERT INTO proposal_audit
               (proposal_id, from_status, to_status, actor_id, actor_roles, reason, ts)
               VALUES (?,?,?,?,?,?,?)""",
            (proposal_id, from_status, to_status, actor.id, actor.roles_csv(), reason, _utcnow()),
        )

    def _row_to_record(self, row) -> ProposalRecord:
        return ProposalRecord(
            proposal_id=row["proposal_id"],
            created_at=row["created_at"],
            kind=row["kind"],
            summary=row["summary"],
            rationale=row["rationale"],
            diff_json=row["diff_json"],
            evidence_json=row["evidence_json"],
            status=row["status"],
            created_by_id=row["created_by_id"],
            created_by_roles=row["created_by_roles"],
            decided_by_id=row["decided_by_id"],
            decided_at=row["decided_at"],
            decision_reason=row["decision_reason"],
            edited_diff_json=row["edited_diff_json"],
            dry_run_json=row["dry_run_json"],
            applied_version=row["applied_version"],
            applied_at=row["applied_at"],
            spec_artifact_path=row["spec_artifact_path"],
        )
