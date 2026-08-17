"""IdentityAllowlist: explicit, fail-closed loading (task requirement 3 - no auto-provisioning)."""

from __future__ import annotations

import json

import pytest

from ap_chat.identity_map import AllowlistError, IdentityAllowlist, add_entry, read_entries, remove_entry


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


# -- P5.4 write helpers: add_entry/remove_entry/read_entries -------------------------------------


def test_read_entries_returns_empty_for_a_missing_file(tmp_path):
    assert read_entries(tmp_path / "does-not-exist.json") == {}


def test_add_entry_creates_the_file_and_parent_dir_if_missing(tmp_path):
    path = tmp_path / "nested" / "allowlist.json"
    add_entry(path, "111", fathm_user_id="planner.bob", token="tok-bob")
    entries = read_entries(path)
    assert entries["111"].fathm_user_id == "planner.bob"
    assert entries["111"].token == "tok-bob"


def test_add_entry_is_atomic_no_partial_file_left_behind(tmp_path):
    path = tmp_path / "allowlist.json"
    add_entry(path, "111", fathm_user_id="planner.bob", token="tok-bob")
    add_entry(path, "222", fathm_user_id="planner.carol", token="tok-carol")
    # No leftover .allowlist-*.tmp files - a crash mid-write would leave temp siblings behind.
    assert list(path.parent.glob(".allowlist-*.tmp")) == []
    entries = read_entries(path)
    assert set(entries) == {"111", "222"}


def test_remove_entry_removes_only_the_named_row(tmp_path):
    path = tmp_path / "allowlist.json"
    add_entry(path, "111", fathm_user_id="planner.bob", token="tok-bob")
    add_entry(path, "222", fathm_user_id="planner.carol", token="tok-carol")

    removed = remove_entry(path, "111")
    assert removed is True
    entries = read_entries(path)
    assert set(entries) == {"222"}


def test_remove_entry_on_absent_id_is_a_no_op(tmp_path):
    path = tmp_path / "allowlist.json"
    add_entry(path, "111", fathm_user_id="planner.bob", token="tok-bob")
    assert remove_entry(path, "does-not-exist") is False
    assert set(read_entries(path)) == {"111"}
