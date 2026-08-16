"""C7 apply-on-approve mechanism (`ap_proposals.apply` + `ProposalWorkflow.decide`): the
transactional registry write for declarative kinds, the spec export for code kinds, the
dry-run-mandatory-before-approve invariant, and the `GET /standard/versions` pull surface.
See CLAUDE.md's "apply mechanism" section and `data/fathm-phase4-readiness/report.md` §5.4/5.5/5.6
in the firstmate repo for the design this implements."""

from __future__ import annotations

import json
import os

import pytest
from fastapi.testclient import TestClient

import ap_api.deps as deps
from _planner_bot_corpus import build_clean_corpus

from ap_api.app import app
from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_auth.store import AuthStore
from ap_gate.checks.context import CheckContext
from ap_gate.checks.labels import check_reason_codes_known
from ap_proposals.apply import ProposalApplyError
from ap_proposals.policy import ProposalPolicy
from ap_proposals.store import ProposalStore
from ap_proposals.workflow import ProposalPolicyError, ProposalWorkflow
from ap_registry.profile_registry import ProfileRegistry

PROFILE = "commodity_commit_forecast"

SWEEP = Identity(id="sweep.bot", roles=frozenset({Role.ANALYST}))
CAPTAIN = Identity(id="cap.tan", roles=frozenset({Role.STANDARD_APPROVER}))


def _reason_code_add_diff(code: str = "NEW_TEST_CODE") -> dict:
    return {"profile": PROFILE, "code": code, "description": "seen repeatedly in override evidence"}


def test_reason_code_add_full_path_registry_bump_changelog_versions_and_gate(tmp_path):
    """Acceptance test 1: reason_code_add -> approve -> registry version bump -> changelog row ->
    GET /standard/versions reflects it -> a gate check against a package declaring the new
    version actually resolves to the new rules."""
    package_store = build_clean_corpus(tmp_path)
    store_root = package_store.root
    proposal_store = ProposalStore(store_root)
    wf = ProposalWorkflow(store=proposal_store)  # default policy: dry-run required

    record = wf.create(
        kind="reason_code_add",
        summary="Add NEW_TEST_CODE",
        rationale="Seen repeatedly across override evidence",
        diff=_reason_code_add_diff(),
        evidence={"package_ids": ["pkg-1"]},
        actor=SWEEP,
    )

    # Approve is refused with no dry-run recorded (see the dedicated test below for the isolated
    # assertion) - record one now so the happy path can proceed.
    wf.record_dry_run(record.proposal_id, package_store)
    approved = wf.decide(record.proposal_id, to_status="approved", actor=CAPTAIN)

    assert approved.status == "approved"
    assert approved.applied_version == "0.2"
    assert approved.spec_artifact_path is None

    registry = ProfileRegistry(store_root)
    assert registry.current_version(PROFILE) == "0.2"
    files = registry.read_version(PROFILE, "0.2")
    assert "NEW_TEST_CODE" in files["reason_codes.json"]["reason_codes"]
    changelog = registry.changelog(PROFILE)
    assert [row["version"] for row in changelog] == ["0.1", "0.2"]
    assert changelog[-1]["actor"] == "cap.tan"

    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    auth_store.create_user("ro.reader", display_name="Reader", roles=frozenset({Role.TEAM_READER}), password="pw")
    app.dependency_overrides[deps.get_proposal_store] = lambda: proposal_store
    app.dependency_overrides[deps.get_auth_store] = lambda: auth_store
    try:
        client = TestClient(app, base_url="https://testserver")
        login = client.post("/login", json={"user_id": "ro.reader", "password": "pw"})
        assert login.status_code == 200, login.text
        r = client.get("/standard/versions")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "ap/0.2" in body["standard_versions"]
        profile_entry = next(p for p in body["profiles"] if p["name"] == PROFILE)
        assert profile_entry["current_version"] == "0.2"
        assert [row["version"] for row in profile_entry["changelog"]] == ["0.1", "0.2"]
    finally:
        app.dependency_overrides.clear()
        auth_store.close()

    # A gate check against a package declaring the *new* version actually resolves the new rules:
    # NEW_TEST_CODE fails at 0.1 (not yet in the allow-list) and passes at 0.2 (just added).
    pkg_dir = tmp_path / "gate-check-pkg"
    (pkg_dir / "labels").mkdir(parents=True)
    (pkg_dir / "labels" / "overrides.jsonl").write_text(
        json.dumps({"override_id": "ovr1", "reason_code": "NEW_TEST_CODE"}) + "\n", encoding="utf-8"
    )
    base_manifest = {"labels": {"overrides_path": "labels/overrides.jsonl"}}
    os.environ["AP_STANDARD_REGISTRY_ROOT"] = str(registry.root)
    os.environ.pop("AP_GATE_FAIL_CLOSED_UNKNOWN_PROFILE_VERSION", None)
    try:
        manifest_v1 = dict(base_manifest, profile=f"{PROFILE}/0.1")
        outcome_v1 = check_reason_codes_known(CheckContext(package_path=pkg_dir, manifest=manifest_v1))
        assert outcome_v1.result == "fail"

        manifest_v2 = dict(base_manifest, profile=f"{PROFILE}/0.2")
        outcome_v2 = check_reason_codes_known(CheckContext(package_path=pkg_dir, manifest=manifest_v2))
        assert outcome_v2.result == "pass"
    finally:
        os.environ.pop("AP_STANDARD_REGISTRY_ROOT", None)

    package_store.close()
    proposal_store.close()


def test_registry_write_failure_leaves_proposal_pending_hitl(tmp_path):
    """Acceptance test 2: simulate a registry write failure at apply time and assert the
    proposal is still `pending_hitl` afterward, not silently 'approved but unapplied'."""
    store_root = tmp_path / "store"
    proposal_store = ProposalStore(store_root)
    wf = ProposalWorkflow(store=proposal_store, policy=ProposalPolicy(require_dry_run_for_declarative=False))

    record = wf.create(
        kind="reason_code_add",
        summary="Add X",
        rationale="r",
        diff=_reason_code_add_diff("X"),
        evidence={},
        actor=SWEEP,
    )

    # Force the registry write apply_declarative will attempt (bump 0.1 -> 0.2) to fail: seed the
    # profile, then pre-create the 0.2 version directory so ProfileRegistry.bump_version's
    # immutable-version-directory guard raises.
    registry = ProfileRegistry(store_root)
    registry.ensure_seeded(PROFILE)
    (registry.root / PROFILE / "0.2").mkdir(parents=True)

    with pytest.raises(ProposalApplyError):
        wf.decide(record.proposal_id, to_status="approved", actor=CAPTAIN)

    reloaded = proposal_store.get(record.proposal_id)
    assert reloaded.status == "pending_hitl"
    assert reloaded.applied_version is None
    assert reloaded.decided_by_id is None
    proposal_store.close()


def test_approve_refused_without_dry_run_then_succeeds_once_recorded(tmp_path):
    """Acceptance test 3: approve is refused on a declarative proposal with no dry-run recorded;
    succeeds once one is."""
    package_store = build_clean_corpus(tmp_path)
    store_root = package_store.root
    proposal_store = ProposalStore(store_root)
    wf = ProposalWorkflow(store=proposal_store)  # default policy: dry-run required

    record = wf.create(
        kind="reason_code_add",
        summary="Add Y",
        rationale="r",
        diff=_reason_code_add_diff("Y"),
        evidence={},
        actor=SWEEP,
    )

    with pytest.raises(ProposalPolicyError, match="no recorded dry-run"):
        wf.decide(record.proposal_id, to_status="approved", actor=CAPTAIN)
    assert proposal_store.get(record.proposal_id).status == "pending_hitl"

    wf.record_dry_run(record.proposal_id, package_store)
    assert proposal_store.get(record.proposal_id).dry_run_json is not None

    approved = wf.decide(record.proposal_id, to_status="approved", actor=CAPTAIN)
    assert approved.status == "approved"
    assert approved.applied_version is not None

    package_store.close()
    proposal_store.close()


def test_check_add_dry_run_not_required_and_skipped_honestly(tmp_path):
    """Code kinds skip dry-run entirely (you cannot dry-run a check that doesn't exist yet) -
    approve must not demand one, and record_dry_run itself must refuse a code kind."""
    store_root = tmp_path / "store"
    proposal_store = ProposalStore(store_root)
    wf = ProposalWorkflow(store=proposal_store)  # default policy: dry-run required (for declarative)

    record = wf.create(
        kind="check_add",
        summary="New check",
        rationale="found a gap",
        diff={"check_id": "new_check", "severity": "advisory", "description": "..."},
        evidence={},
        actor=SWEEP,
    )

    with pytest.raises(ProposalPolicyError, match="code kind"):
        wf.record_dry_run(record.proposal_id, package_store=None)

    approved = wf.decide(record.proposal_id, to_status="approved", actor=CAPTAIN)
    assert approved.status == "approved"
    proposal_store.close()


def test_code_kind_approval_exports_spec_and_does_not_touch_registry(tmp_path):
    """Acceptance test 4: a standard_change/check_add approval produces a retrievable spec
    artifact and does NOT touch the registry."""
    store_root = tmp_path / "store"
    proposal_store = ProposalStore(store_root)
    wf = ProposalWorkflow(store=proposal_store)

    diff = {
        "target": "standard/ap-0.2/STANDARD.md",
        "description": "Clarify override evidence_refs grammar",
        "patch": "--- a/STANDARD.md\n+++ b/STANDARD.md\n@@ -1 +1 @@\n-old\n+new\n",
    }
    record = wf.create(
        kind="standard_change",
        summary="Clarify evidence_refs grammar",
        rationale="Two planners misread the fragment syntax this sprint",
        diff=diff,
        evidence={"package_ids": ["pkg-1", "pkg-2"]},
        actor=SWEEP,
    )

    approved = wf.decide(record.proposal_id, to_status="approved", actor=CAPTAIN)
    assert approved.status == "approved"
    assert approved.applied_version is None
    assert approved.spec_artifact_path is not None

    artifact_path = store_root / approved.spec_artifact_path
    assert artifact_path.is_file()
    content = artifact_path.read_text(encoding="utf-8")
    assert "Clarify evidence_refs grammar" in content
    assert "Two planners misread" in content
    assert "old" in content and "new" in content  # the draft patch made it in

    # No registry directory was created at all - the approval never touched it.
    assert not (store_root / "standard_registry").exists()

    # Retrievable via the API too.
    app.dependency_overrides[deps.get_proposal_store] = lambda: proposal_store
    from ap_auth.store import AuthStore

    auth_store = AuthStore(tmp_path / "auth.sqlite3")
    auth_store.create_user("ro.reader", display_name="Reader", roles=frozenset({Role.TEAM_READER}), password="pw")
    app.dependency_overrides[deps.get_auth_store] = lambda: auth_store
    try:
        client = TestClient(app, base_url="https://testserver")
        login = client.post("/login", json={"user_id": "ro.reader", "password": "pw"})
        assert login.status_code == 200, login.text
        r = client.get(f"/proposals/{record.proposal_id}/spec")
        assert r.status_code == 200, r.text
        assert "Clarify evidence_refs grammar" in r.text
    finally:
        app.dependency_overrides.clear()
        auth_store.close()

    proposal_store.close()
