"""Pydantic request/response shapes for the interface layer (design doc section 15).

Shaped deliberately for a future UI consumer (phase-3 manager console), not just curl - see
`ReviewRequest` and `ListResponse` docstrings.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ap_store.models import PackageRecord


class ValidateRequest(BaseModel):
    package_dir: str = Field(description="Filesystem path to a package directory the server can read")


class PublishRequest(BaseModel):
    package_dir: str = Field(description="Filesystem path to a package directory the server can read")


class ReviewRequest(BaseModel):
    """Review-transition payload, shaped for a form: `to_status` is the action a reviewer/analyst
    picks (submit -> in_review, approve, reject, withdraw/revise -> draft); `reason` is the
    free-text box a UI would only need to show (and require) when `to_status == "rejected"` -
    ReviewWorkflow enforces that requirement server-side regardless of what the client sends.
    """

    package_version: str
    to_status: str = Field(description="one of: in_review, approved, rejected, draft")
    reason: str | None = None


class PackageOut(BaseModel):
    package_id: str
    package_version: str
    profile: str
    title: str
    as_of: str
    created_at: str
    status: str
    blob_sha256: str
    analyst_id: str | None
    reviewer_id: str | None
    owners: dict[str, Any]
    gate_overall: str
    published_by_id: str
    published_by_roles: str
    replaces_package_id: str | None = None
    replaces_package_version: str | None = None


class ListResponse(BaseModel):
    """Paginated list envelope - `total`/`page`/`page_size` let a UI render page controls without a
    second count query."""

    items: list[PackageOut]
    total: int
    page: int
    page_size: int


class AuditEntryOut(BaseModel):
    from_status: str | None
    to_status: str
    actor_id: str
    actor_roles: str
    reason: str | None
    ts: str


def package_record_to_out(record: PackageRecord) -> PackageOut:
    return PackageOut(
        package_id=record.package_id,
        package_version=record.package_version,
        profile=record.profile,
        title=record.title,
        as_of=record.as_of,
        created_at=record.created_at,
        status=record.status,
        blob_sha256=record.blob_sha256,
        analyst_id=record.analyst_id,
        reviewer_id=record.reviewer_id,
        owners=record.owners(),
        gate_overall=record.gate_overall,
        published_by_id=record.published_by_id,
        published_by_roles=record.published_by_roles,
        replaces_package_id=record.replaces_package_id,
        replaces_package_version=record.replaces_package_version,
    )
