"""IdentityAllowlist: explicit, fail-closed loading (task requirement 3 - no auto-provisioning)."""

from __future__ import annotations

import json

import pytest

from ap_chat.identity_map import AllowlistError, IdentityAllowlist


def test_resolves_a_mapped_platform_user(tmp_path):
    path = tmp_path / "allowlist.json"
    path.write_text(json.dumps({"555": {"fathm_user_id": "planner.alice", "token": "tok-1"}}))
    allowlist = IdentityAllowlist(path)
    identity = allowlist.resolve("555")
    assert identity.fathm_user_id == "planner.alice"
    assert identity.token == "tok-1"


def test_unmapped_platform_user_resolves_to_none(tmp_path):
    path = tmp_path / "allowlist.json"
    path.write_text(json.dumps({"555": {"fathm_user_id": "planner.alice", "token": "tok-1"}}))
    allowlist = IdentityAllowlist(path)
    assert allowlist.resolve("999") is None


def test_missing_file_raises_allowlist_error(tmp_path):
    with pytest.raises(AllowlistError, match="not found"):
        IdentityAllowlist(tmp_path / "missing.json")


def test_malformed_json_raises_allowlist_error(tmp_path):
    path = tmp_path / "allowlist.json"
    path.write_text("{not json")
    with pytest.raises(AllowlistError, match="not valid JSON"):
        IdentityAllowlist(path)


def test_entry_missing_required_field_raises_allowlist_error(tmp_path):
    path = tmp_path / "allowlist.json"
    path.write_text(json.dumps({"555": {"fathm_user_id": "planner.alice"}}))
    with pytest.raises(AllowlistError, match="555"):
        IdentityAllowlist(path)


def test_load_picks_up_edits_without_reconstructing(tmp_path):
    path = tmp_path / "allowlist.json"
    path.write_text(json.dumps({"555": {"fathm_user_id": "planner.alice", "token": "tok-1"}}))
    allowlist = IdentityAllowlist(path)
    path.write_text(json.dumps({"555": {"fathm_user_id": "planner.alice", "token": "tok-2"}}))
    allowlist.load()
    assert allowlist.resolve("555").token == "tok-2"
