"""Read-model dataclasses returned by ProposalStore. See ap_proposals.db for the schema they mirror."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ProposalRecord:
    proposal_id: str
    created_at: str
    kind: str  # standard_change | profile_change | reason_code_add | check_add
    summary: str
    rationale: str
    diff_json: str
    evidence_json: str
    status: str  # pending_hitl | approved | rejected | withdrawn
    created_by_id: str
    created_by_roles: str
    decided_by_id: str | None
    decided_at: str | None
    decision_reason: str | None
    edited_diff_json: str | None
    dry_run_json: str | None
    applied_version: str | None
    applied_at: str | None

    def diff(self) -> dict[str, Any]:
        return json.loads(self.diff_json)

    def evidence(self) -> dict[str, Any]:
        return json.loads(self.evidence_json)

    def edited_diff(self) -> dict[str, Any] | None:
        return json.loads(self.edited_diff_json) if self.edited_diff_json is not None else None

    def dry_run(self) -> dict[str, Any] | None:
        return json.loads(self.dry_run_json) if self.dry_run_json is not None else None


@dataclass(frozen=True)
class ProposalAuditEntry:
    id: int
    proposal_id: str
    from_status: str | None
    to_status: str
    actor_id: str
    actor_roles: str
    reason: str | None
    ts: str
