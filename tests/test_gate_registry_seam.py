"""End-to-end gate-check coverage of the `ap_gate.profiles` registry seam: the env-var knobs
`ap-gate check` (and any other CLI/library caller) resolves against, not just the loader
functions in isolation (see `test_profile_registry.py` for those)."""

from __future__ import annotations

from conftest import EXAMPLE_PACKAGE

from ap_gate import profiles as profiles_mod
from ap_gate.checks.context import CheckContext
from ap_gate.checks.registry import run_all
from ap_gate.load_manifest import load_manifest
from ap_registry.profile_registry import ProfileRegistry

PROFILE = "commodity_commit_forecast"


def _run(ctx):
    return {o.check_id: o for o in run_all(ctx)}


def test_no_registry_env_configured_matches_gold_pack_baseline(tmp_path, monkeypatch):
    monkeypatch.delenv(profiles_mod.ENV_REGISTRY_ROOT, raising=False)
    monkeypatch.delenv(profiles_mod.ENV_FAIL_CLOSED_UNKNOWN_VERSION, raising=False)

    manifest = load_manifest(EXAMPLE_PACKAGE)
    ctx = CheckContext(package_path=EXAMPLE_PACKAGE, manifest=manifest)
    outcomes = _run(ctx)
    assert outcomes["reason_codes_known"].result == "pass"


def test_registry_configured_via_env_serves_registry_content(tmp_path, monkeypatch):
    registry = ProfileRegistry(tmp_path)
    registry.ensure_seeded(PROFILE)
    registry.bump_version(PROFILE, "0.2", {"reason_codes.json": {"reason_codes": ["ONLY_FROM_REGISTRY"]}})

    manifest = dict(load_manifest(EXAMPLE_PACKAGE))
    manifest["profile"] = f"{PROFILE}/0.2"

    monkeypatch.setenv(profiles_mod.ENV_REGISTRY_ROOT, str(registry.root))
    monkeypatch.delenv(profiles_mod.ENV_FAIL_CLOSED_UNKNOWN_VERSION, raising=False)
    ctx = CheckContext(package_path=EXAMPLE_PACKAGE, manifest=manifest)
    outcomes = _run(ctx)

    # The example package's real override rows use reason codes not in the 0.2 allow-list, so
    # under the registry's 0.2 content the check must fail (proves the registry content, not
    # the repo default, was actually consulted).
    assert outcomes["reason_codes_known"].result == "fail"
    assert "ONLY_FROM_REGISTRY" in outcomes["reason_codes_known"].message


def test_fail_closed_off_falls_back_on_unknown_version(tmp_path, monkeypatch):
    registry = ProfileRegistry(tmp_path)
    registry.ensure_seeded(PROFILE)  # only 0.1 registered

    manifest = dict(load_manifest(EXAMPLE_PACKAGE))
    manifest["profile"] = f"{PROFILE}/9.9"  # unknown to the registry

    monkeypatch.setenv(profiles_mod.ENV_REGISTRY_ROOT, str(registry.root))
    monkeypatch.setenv(profiles_mod.ENV_FAIL_CLOSED_UNKNOWN_VERSION, "0")
    ctx = CheckContext(package_path=EXAMPLE_PACKAGE, manifest=manifest)
    outcomes = _run(ctx)

    # Falls back to repo PROFILES_ROOT content, so the real (valid) override rows pass.
    assert outcomes["reason_codes_known"].result == "pass"


def test_fail_closed_on_blocks_gate_on_unknown_version(tmp_path, monkeypatch):
    registry = ProfileRegistry(tmp_path)
    registry.ensure_seeded(PROFILE)  # only 0.1 registered

    manifest = dict(load_manifest(EXAMPLE_PACKAGE))
    manifest["profile"] = f"{PROFILE}/9.9"  # unknown to the registry

    monkeypatch.setenv(profiles_mod.ENV_REGISTRY_ROOT, str(registry.root))
    monkeypatch.setenv(profiles_mod.ENV_FAIL_CLOSED_UNKNOWN_VERSION, "1")
    ctx = CheckContext(package_path=EXAMPLE_PACKAGE, manifest=manifest)
    outcomes = _run(ctx)

    assert outcomes["reason_codes_known"].result == "fail"
    assert "9.9" in outcomes["reason_codes_known"].message
    assert outcomes["reason_codes_known"].blocks_overall_pass()


def test_registry_write_visible_on_next_gate_check_no_restart(tmp_path, monkeypatch):
    """Non-negotiable per the task brief: write a new profile version, immediately gate-check
    a package under it, and prove the new version's rules are in effect - same process, no
    cache clear called by the test itself."""
    registry = ProfileRegistry(tmp_path)
    registry.ensure_seeded(PROFILE)

    monkeypatch.setenv(profiles_mod.ENV_REGISTRY_ROOT, str(registry.root))
    monkeypatch.delenv(profiles_mod.ENV_FAIL_CLOSED_UNKNOWN_VERSION, raising=False)

    manifest_v1 = dict(load_manifest(EXAMPLE_PACKAGE))
    manifest_v1["profile"] = f"{PROFILE}/0.1"
    ctx_v1 = CheckContext(package_path=EXAMPLE_PACKAGE, manifest=manifest_v1)
    # First read of 0.1 - populates the cache for that version.
    assert _run(ctx_v1)["reason_codes_known"].result == "pass"

    # Bump 0.2 mid-process.
    registry.bump_version(PROFILE, "0.2", {"reason_codes.json": {"reason_codes": ["BRAND_NEW_ONLY"]}})

    manifest_v2 = dict(load_manifest(EXAMPLE_PACKAGE))
    manifest_v2["profile"] = f"{PROFILE}/0.2"
    ctx_v2 = CheckContext(package_path=EXAMPLE_PACKAGE, manifest=manifest_v2)
    outcomes_v2 = _run(ctx_v2)

    assert outcomes_v2["reason_codes_known"].result == "fail"
    assert "BRAND_NEW_ONLY" in outcomes_v2["reason_codes_known"].message
