"""Versioned profile registry (C7 apply substrate) + `ap_gate.profiles`' registry seam.

See CLAUDE.md's "Standard registry, gate seam, dry-run" section for the architecture this
tests.
"""

from __future__ import annotations

import pytest

from ap_gate import profiles as profiles_mod
from ap_gate.profiles import UnknownProfileVersionError, load_profile_reason_codes
from ap_registry.profile_registry import ProfileRegistry, ProfileRegistryError

PROFILE = "commodity_commit_forecast"


@pytest.fixture(autouse=True)
def _clear_registry_cache():
    # The registry file cache is module-global; each test uses its own tmp_path root so keys
    # never collide, but clear it anyway to keep tests order-independent and honest.
    profiles_mod.invalidate_registry_cache()
    yield
    profiles_mod.invalidate_registry_cache()


def test_ensure_seeded_copies_repo_defaults(tmp_path):
    registry = ProfileRegistry(tmp_path)
    assert registry.current_version(PROFILE) is None

    version = registry.ensure_seeded(PROFILE)
    assert version == "0.1"
    assert registry.current_version(PROFILE) == "0.1"

    files = registry.read_version(PROFILE, "0.1")
    assert "reason_codes.json" in files
    assert "HOLD_FOR_PRICE_NEGOTIATION" in files["reason_codes.json"]["reason_codes"]


def test_ensure_seeded_is_idempotent(tmp_path):
    registry = ProfileRegistry(tmp_path)
    registry.ensure_seeded(PROFILE)
    registry.bump_version(PROFILE, "0.2", {"reason_codes.json": {"reason_codes": ["ONLY_ONE"]}})
    # a second ensure_seeded call must not clobber the bump back to 0.1
    assert registry.ensure_seeded(PROFILE) == "0.2"


def test_seed_bump_read_round_trip(tmp_path):
    registry = ProfileRegistry(tmp_path)
    registry.ensure_seeded(PROFILE)

    new_version = registry.bump_version(
        PROFILE,
        "0.2",
        {"reason_codes.json": {"reason_codes": ["HOLD_FOR_PRICE_NEGOTIATION", "NEW_CODE"]}},
        note="added NEW_CODE",
        actor="standard.approver",
    )
    assert new_version == "0.2"
    assert registry.current_version(PROFILE) == "0.2"
    assert registry.versions(PROFILE) == ["0.1", "0.2"]

    files = registry.read_version(PROFILE, "0.2")
    assert files["reason_codes.json"]["reason_codes"] == ["HOLD_FOR_PRICE_NEGOTIATION", "NEW_CODE"]
    # unrelated file carried forward unchanged from 0.1
    assert files["training_grade.json"] == registry.read_version(PROFILE, "0.1")["training_grade.json"]

    changelog = registry.changelog(PROFILE)
    assert [row["version"] for row in changelog] == ["0.1", "0.2"]
    assert changelog[1]["previous"] == "0.1"
    assert changelog[1]["note"] == "added NEW_CODE"
    assert changelog[1]["actor"] == "standard.approver"

    # 0.1 is untouched - immutability
    assert "NEW_CODE" not in registry.read_version(PROFILE, "0.1")["reason_codes.json"]["reason_codes"]


def test_bump_version_deletes_file_with_none(tmp_path):
    registry = ProfileRegistry(tmp_path)
    registry.ensure_seeded(PROFILE)
    registry.bump_version(PROFILE, "0.2", {"training_grade.json": None})
    files = registry.read_version(PROFILE, "0.2")
    assert "training_grade.json" not in files
    assert "reason_codes.json" in files  # untouched files still carried forward


def test_bump_version_rejects_non_monotonic(tmp_path):
    registry = ProfileRegistry(tmp_path)
    registry.ensure_seeded(PROFILE)  # 0.1
    registry.bump_version(PROFILE, "0.2", {})
    with pytest.raises(ProfileRegistryError):
        registry.bump_version(PROFILE, "0.2", {})  # not > current
    with pytest.raises(ProfileRegistryError):
        registry.bump_version(PROFILE, "0.1", {})  # regression


def test_version_directories_are_immutable(tmp_path):
    registry = ProfileRegistry(tmp_path)
    registry.ensure_seeded(PROFILE)
    registry.seed_version(PROFILE, "5.0", {})  # write a version out-of-band, as dry-run would
    with pytest.raises(ProfileRegistryError):
        registry.seed_version(PROFILE, "5.0", {"reason_codes.json": {"reason_codes": []}})


# --- ap_gate.profiles seam ---------------------------------------------------------------


def test_no_registry_configured_falls_through_to_repo(tmp_path):
    # No registry_root passed, none in env: exactly today's behavior.
    result = load_profile_reason_codes("commodity_commit_forecast/0.1")
    assert result is not None
    assert "HOLD_FOR_PRICE_NEGOTIATION" in result["reason_codes"]


def test_registry_root_configured_serves_registry_content_for_declared_version(tmp_path):
    registry = ProfileRegistry(tmp_path)
    registry.ensure_seeded(PROFILE)
    registry.bump_version(PROFILE, "0.2", {"reason_codes.json": {"reason_codes": ["ONLY_FROM_REGISTRY"]}})

    result = load_profile_reason_codes(f"{PROFILE}/0.2", registry_root=registry.root)
    assert result == {"reason_codes": ["ONLY_FROM_REGISTRY"]}

    # 0.1 still resolves to the original seeded (repo-derived) content
    result_v1 = load_profile_reason_codes(f"{PROFILE}/0.1", registry_root=registry.root)
    assert "HOLD_FOR_PRICE_NEGOTIATION" in result_v1["reason_codes"]


def test_bare_short_name_skips_registry_even_when_configured(tmp_path):
    registry = ProfileRegistry(tmp_path)
    registry.ensure_seeded(PROFILE)
    registry.bump_version(PROFILE, "0.2", {"reason_codes.json": {"reason_codes": ["ONLY_FROM_REGISTRY"]}})

    # No version in the declaration -> registry is never consulted, repo default wins, same as
    # every pre-this-task caller (ap_redact, ap_planner_bot.detectors, ap_gate.field_path).
    result = load_profile_reason_codes(PROFILE, registry_root=registry.root)
    assert "HOLD_FOR_PRICE_NEGOTIATION" in result["reason_codes"]
    assert "ONLY_FROM_REGISTRY" not in result["reason_codes"]


def test_unknown_version_falls_back_when_fail_closed_off(tmp_path):
    registry = ProfileRegistry(tmp_path)
    registry.ensure_seeded(PROFILE)  # only 0.1 exists

    result = load_profile_reason_codes(f"{PROFILE}/9.9", registry_root=registry.root, fail_closed=False)
    assert result is not None
    assert "HOLD_FOR_PRICE_NEGOTIATION" in result["reason_codes"]  # repo fallback content


def test_unknown_version_raises_when_fail_closed_on(tmp_path):
    registry = ProfileRegistry(tmp_path)
    registry.ensure_seeded(PROFILE)  # only 0.1 exists

    with pytest.raises(UnknownProfileVersionError):
        load_profile_reason_codes(f"{PROFILE}/9.9", registry_root=registry.root, fail_closed=True)


def test_cache_invalidation_no_restart_needed(tmp_path):
    """The sharpest correctness edge (CLAUDE.md/task brief): a registry write must be visible
    on the very next read, in the same process, no cache clear needed by the caller."""
    registry = ProfileRegistry(tmp_path)
    registry.ensure_seeded(PROFILE)

    first = load_profile_reason_codes(f"{PROFILE}/0.1", registry_root=registry.root)
    assert first["reason_codes"] == registry.read_version(PROFILE, "0.1")["reason_codes.json"]["reason_codes"]

    # Read again to populate the cache for this exact key, then bump - a *new* version, so the
    # bump itself can't collide with anything cached.
    load_profile_reason_codes(f"{PROFILE}/0.1", registry_root=registry.root)
    registry.bump_version(PROFILE, "0.2", {"reason_codes.json": {"reason_codes": ["FRESH_AFTER_BUMP"]}})

    second = load_profile_reason_codes(f"{PROFILE}/0.2", registry_root=registry.root)
    assert second == {"reason_codes": ["FRESH_AFTER_BUMP"]}
