"""Pydantic request/response shapes for the interface layer (design doc section 15).

Shaped deliberately for a future UI consumer (phase-3 manager console), not just curl - see
`ReviewRequest` and `ListResponse` docstrings.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from ap_manager_bot.models import ChatAnswer
from ap_proposals.models import ProposalRecord
from ap_store.models import PackageRecord


class LoginRequest(BaseModel):
    user_id: str
    password: str


class LoginResponse(BaseModel):
    """Returned once at login. `csrf_token` is not a secret the way the session cookie is (it's a
    public function of it, see ap_auth.csrf) but it never travels in a cookie, so the client must
    hold onto it and echo it back as the `X-Csrf` header on every state-changing request."""

    user_id: str
    roles: list[str]
    csrf_token: str


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


class SupersedeRequest(BaseModel):
    """C12 lifecycle: `POST /packages/{id}/supersede`. `package_version` is the *predecessor*
    version being superseded (from the URL's package_id); the successor is named explicitly since
    it may be a different package_id entirely (a rewrite, not just a new version)."""

    package_version: str
    successor_package_id: str
    successor_package_version: str
    reason: str | None = None


class RecallRequest(BaseModel):
    package_version: str
    reason: str = Field(description="Required - a recall with no recorded why is an audit hole")


class RestoreRequest(BaseModel):
    """Admin-only: `recalled -> approved` or `superseded -> approved`."""

    package_version: str
    reason: str | None = None


class LegalHoldRequest(BaseModel):
    package_version: str
    hold: bool = Field(description="True to set the hold, False to clear it")
    reason: str | None = Field(default=None, description="Required when hold=True")


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
    legal_hold: bool = False
    legal_hold_reason: str | None = None
    purged_at: str | None = None


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


class ChatRequest(BaseModel):
    question: str = Field(description="Natural-language question over the caller's approved, in-scope package corpus")


class CitationOut(BaseModel):
    package_id: str
    package_version: str
    field_path: str
    chunk_type: str


class ChatResponse(BaseModel):
    answer: str
    citations: list[CitationOut]
    refused: bool


def chat_answer_to_out(answer: ChatAnswer) -> ChatResponse:
    return ChatResponse(
        answer=answer.answer,
        refused=answer.refused,
        citations=[
            CitationOut(package_id=c.package_id, package_version=c.package_version, field_path=c.field_path, chunk_type=c.chunk_type)
            for c in answer.citations
        ],
    )


class ProposalCreateRequest(BaseModel):
    """C6/C7 proposal creation payload. `diff` is validated against `kind`'s schema
    (`ap_proposals.kinds.DIFF_SCHEMAS`) server-side - see ap_proposals.store.ProposalStore.create."""

    kind: str = Field(description="one of: standard_change, profile_change, reason_code_add, check_add")
    summary: str
    rationale: str
    diff: dict[str, Any]
    evidence: dict[str, Any] = Field(default_factory=dict)


class ProposalDecisionRequest(BaseModel):
    """Decision payload for POST /proposals/{id}/decision. `reason` is required when
    `to_status == 'rejected'` (enforced server-side by ProposalWorkflow regardless of what the
    client sends). `edited_diff` populates approve-with-edits - stored beside the original diff,
    never over it."""

    to_status: str = Field(description="one of: approved, rejected, withdrawn")
    reason: str | None = None
    edited_diff: dict[str, Any] | None = None


class ProposalOut(BaseModel):
    proposal_id: str
    created_at: str
    kind: str
    summary: str
    rationale: str
    diff: dict[str, Any]
    evidence: dict[str, Any]
    status: str
    created_by_id: str
    created_by_roles: str
    decided_by_id: str | None
    decided_at: str | None
    decision_reason: str | None
    edited_diff: dict[str, Any] | None
    dry_run: dict[str, Any] | None
    applied_version: str | None
    applied_at: str | None


class ProposalListResponse(BaseModel):
    items: list[ProposalOut]
    total: int
    page: int
    page_size: int


class ProfileVersionsOut(BaseModel):
    """One entry per registry-tracked profile in the `GET /standard/versions` response."""

    name: str
    current_version: str | None
    changelog: list[dict[str, Any]] = Field(
        description="Oldest-first list of {version, previous, note, actor, ts} bump records"
    )


class StandardVersionsOut(BaseModel):
    """`GET /standard/versions`: the pull surface a future notify/agent-docs task points agents
    at (§5.5). `standard_versions` is the Standard's own supported-version list
    (`ap_gate.versions.supported_versions`, unrelated to per-profile registry versions below)."""

    standard_versions: list[str]
    profiles: list[ProfileVersionsOut]


def proposal_record_to_out(record: ProposalRecord) -> ProposalOut:
    return ProposalOut(
        proposal_id=record.proposal_id,
        created_at=record.created_at,
        kind=record.kind,
        summary=record.summary,
        rationale=record.rationale,
        diff=record.diff(),
        evidence=record.evidence(),
        status=record.status,
        created_by_id=record.created_by_id,
        created_by_roles=record.created_by_roles,
        decided_by_id=record.decided_by_id,
        decided_at=record.decided_at,
        decision_reason=record.decision_reason,
        edited_diff=record.edited_diff(),
        dry_run=record.dry_run(),
        applied_version=record.applied_version,
        applied_at=record.applied_at,
    )


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
        legal_hold=record.legal_hold,
        legal_hold_reason=record.legal_hold_reason,
        purged_at=record.purged_at,
    )
