"""Read-model dataclasses returned by PackageStore. See ap_store.db for the schema they mirror."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PackageRecord:
    package_id: str
    package_version: str
    profile: str
    title: str
    as_of: str
    created_at: str  # store-assigned publish time, distinct from the manifest's own created_at
    status: str  # live ap_review workflow status: draft | in_review | approved | rejected
    blob_sha256: str
    analyst_id: str | None
    reviewer_id: str | None
    owners_json: str
    gate_overall: str  # ap-gate "pass"/"fail" recorded at publish time
    published_by_id: str
    published_by_roles: str
    replaces_package_id: str | None = None
    replaces_package_version: str | None = None
    legal_hold: bool = False
    legal_hold_reason: str | None = None
    purged_at: str | None = None  # non-None once ap_lifecycle.LifecycleWorkflow.purge has run

    def owners(self) -> dict[str, Any]:
        return json.loads(self.owners_json)


@dataclass(frozen=True)
class AuditEntry:
    id: int
    package_id: str
    package_version: str
    from_status: str | None
    to_status: str
    actor_id: str
    actor_roles: str
    reason: str | None
    ts: str
