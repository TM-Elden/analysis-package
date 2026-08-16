"""Loads per-profile machine files (reason-code allow-lists, etc.).

Profile-specific requirements never fork the core manifest schema - they
live under profiles/<name>/ and are loaded here by profile id. See
STANDARD.md extensibility rule 3 and second review section 5.3.

Phase 4 (C7 apply substrate, `data/fathm-phase4-readiness/report.md` section 5.5 in the
firstmate repo) adds a version-aware resolution seam on top of that: `<store_root>/
standard_registry/profiles/<name>/<version>/*.json` (written/read by `ap_registry.
profile_registry.ProfileRegistry`) is the tenant's live, mutable profile state; this
module's repo-relative `PROFILES_ROOT` remains the vendored seed/default. Resolution order
per file lookup is **registry root first (when configured), repo `PROFILES_ROOT` fallback**:

- With no registry configured (`AP_STANDARD_REGISTRY_ROOT` unset and no `registry_root=`
  kwarg passed), every loader behaves exactly as before this task - a flat, version-oblivious
  read of `profiles/<name>/<file>`. This is what keeps the `examples/commodity-commit-v1`
  gold-pack regression passing unchanged.
- With a registry configured, a loader only consults it when the caller passed a manifest's
  raw `profile` value in `<name>/<version>` shape (see `resolve_profile_declaration`) - a
  bare short name (no `/`) skips the registry entirely and goes straight to `PROFILES_ROOT`,
  same as today. This is deliberate: only call sites that resolve a specific package's
  declared profile version (today, `ap_gate.checks.labels`) get version-aware behavior;
  declarative/corpus-wide callers that only ever had a short name (`ap_redact`,
  `ap_planner_bot.detectors`, `ap_gate.field_path`) are unaffected.
- When the registry *is* configured and consulted, an unrecognized `<name>/<version>` (the
  version directory doesn't exist under the registry root) either fails closed
  (`UnknownProfileVersionError`, when the `AP_GATE_FAIL_CLOSED_UNKNOWN_PROFILE_VERSION=1`
  knob - or `fail_closed=True` - is on) or falls back to `PROFILES_ROOT` (when the knob is
  off) - C7's acceptance bar requires the fail-closed option to exist, not that it's the
  default.

**Cache lifecycle**: `_REGISTRY_FILE_CACHE` is keyed by `(registry_root, name, version,
filename)`, not just `(name, filename)` like the old bare `lru_cache`. A version's on-disk
files never change once written - `ProfileRegistry.bump_version`/`seed_version` always create
a *new* version directory - so a cache hit for an already-resolved version can never go stale:
the key for any new content is necessarily a key this cache has never seen. `bump_version`
also calls `invalidate_registry_cache` defensively (belt-and-suspenders against a future
in-place-edit escape hatch), but the version-keying is what actually makes "a write is visible
on the next read without a process restart" true by construction - see
`tests/test_profile_registry.py::test_cache_invalidation_no_restart_needed`.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from ap_gate.versions import REPO_ROOT

PROFILES_ROOT = REPO_ROOT / "profiles"

ENV_REGISTRY_ROOT = "AP_STANDARD_REGISTRY_ROOT"
ENV_FAIL_CLOSED_UNKNOWN_VERSION = "AP_GATE_FAIL_CLOSED_UNKNOWN_PROFILE_VERSION"


class UnknownProfileVersionError(Exception):
    """Raised (only when the fail-closed knob is on) when a manifest declares a
    profile `<name>/<version>` that the configured registry root doesn't recognize."""


def registry_root_from_env() -> Path | None:
    val = os.environ.get(ENV_REGISTRY_ROOT)
    return Path(val) if val else None


def fail_closed_from_env() -> bool:
    return os.environ.get(ENV_FAIL_CLOSED_UNKNOWN_VERSION, "").strip() == "1"


def profile_short_name(profile: str | None) -> str | None:
    """'commodity_commit_forecast/0.1' -> 'commodity_commit_forecast'.

    Unchanged from before this task: still just the name, version discarded. Use
    `resolve_profile_declaration` where the version matters.
    """
    if not isinstance(profile, str) or not profile:
        return None
    return profile.split("/", 1)[0]


def resolve_profile_declaration(profile: str | None) -> tuple[str, str] | None:
    """'commodity_commit_forecast/0.1' -> ('commodity_commit_forecast', '0.1').

    None if `profile` is unset or doesn't carry an explicit `<name>/<version>` shape - a bare
    name has no version to resolve against the registry, so it always falls through to
    `PROFILES_ROOT` (see the module docstring's resolution-order note).
    """
    if not isinstance(profile, str) or not profile or "/" not in profile:
        return None
    name, _, version = profile.partition("/")
    if not name or not version:
        return None
    return name, version


# (registry_root, name, version, filename) -> parsed content or None. See the module
# docstring's "Cache lifecycle" section for why version-keying alone is sufficient.
_REGISTRY_FILE_CACHE: dict[tuple[str, str, str, str], dict[str, Any] | None] = {}


def invalidate_registry_cache(registry_root: Path | None = None, name: str | None = None) -> None:
    """Drop cached registry reads. Called by `ap_registry.profile_registry.ProfileRegistry`
    after every write. Safe to call with no arguments (clears everything) - e.g. from tests."""
    if registry_root is None and name is None:
        _REGISTRY_FILE_CACHE.clear()
        return
    for key in [
        k
        for k in _REGISTRY_FILE_CACHE
        if (registry_root is None or k[0] == str(registry_root)) and (name is None or k[1] == name)
    ]:
        del _REGISTRY_FILE_CACHE[key]


def _read_registry_file(registry_root: Path, name: str, version: str, filename: str) -> tuple[dict[str, Any] | None, bool]:
    """Returns `(content_or_None, version_known)`. `version_known` distinguishes "this version
    directory exists but doesn't have this particular file" (a legitimate permissive skip, same
    as a missing file under `PROFILES_ROOT` today) from "this version was never registered"
    (the fail-closed trigger)."""
    version_dir = registry_root / name / version
    if not version_dir.is_dir():
        return None, False
    cache_key = (str(registry_root), name, version, filename)
    if cache_key in _REGISTRY_FILE_CACHE:
        return _REGISTRY_FILE_CACHE[cache_key], True
    path = version_dir / filename
    content = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    _REGISTRY_FILE_CACHE[cache_key] = content
    return content, True


def _load_profile_file(
    filename: str,
    profile: str | None,
    *,
    registry_root: Path | None = None,
    fail_closed: bool | None = None,
) -> dict[str, Any] | None:
    name = profile_short_name(profile)
    if not name:
        return None
    if registry_root is None:
        registry_root = registry_root_from_env()
    if fail_closed is None:
        fail_closed = fail_closed_from_env()

    declared = resolve_profile_declaration(profile)
    if registry_root is not None and declared is not None:
        _, version = declared
        content, version_known = _read_registry_file(registry_root, name, version, filename)
        if version_known:
            return content
        if fail_closed:
            raise UnknownProfileVersionError(
                f"profile '{name}' declares version {version!r}, which is not registered in "
                f"the standard registry at {registry_root} - refusing to fall back silently "
                f"({ENV_FAIL_CLOSED_UNKNOWN_VERSION}=1). Register that version, or publish "
                "against a version the registry recognizes."
            )
        # fail_closed off: fall through to the repo default below, same as no registry
        # configured at all.

    path = PROFILES_ROOT / name / filename
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def load_profile_reason_codes(
    profile: str | None, *, registry_root: Path | None = None, fail_closed: bool | None = None
) -> dict[str, Any] | None:
    """Return the resolved reason_codes.json for `profile` ('<name>' or '<name>/<version>'),
    or None if not registered. Raises `UnknownProfileVersionError` per the module docstring."""
    return _load_profile_file("reason_codes.json", profile, registry_root=registry_root, fail_closed=fail_closed)


def load_profile_training_grade(
    profile: str | None, *, registry_root: Path | None = None, fail_closed: bool | None = None
) -> dict[str, Any] | None:
    """Return the resolved training_grade.json for `profile`, or None if the profile hasn't
    opted into stricter training-export requirements at all.

    Core stays permissive by default: a missing file (or a present file with a flag left
    false) means that requirement isn't enforced. Recognized flags: `require_reason_text`
    (labels_row_shape, P1) and `require_agent_draft` (agent_draft_present, P4)."""
    return _load_profile_file("training_grade.json", profile, registry_root=registry_root, fail_closed=fail_closed)


def load_profile_field_path_grammar(
    profile: str | None, *, registry_root: Path | None = None, fail_closed: bool | None = None
) -> dict[str, Any] | None:
    """Return the resolved field_path_grammar.json for `profile`, or None if the profile has
    no declared grammar (P2). See ap_gate.field_path.resolve_field_path."""
    return _load_profile_file("field_path_grammar.json", profile, registry_root=registry_root, fail_closed=fail_closed)


def load_profile_redaction(
    profile: str | None, *, registry_root: Path | None = None, fail_closed: bool | None = None
) -> dict[str, Any] | None:
    """Return the resolved redaction.json for `profile`, or None if the profile has no
    redaction overrides (C14). Core stays permissive: no file means ap_redact's hardcoded
    defaults apply unmodified. Recognized keys (see ap_redact.field_paths):
    `allow_field_paths` (default-scrubbed paths this profile keeps unredacted),
    `deny_field_paths` (extra paths to scrub beyond the defaults), and `disabled_detectors`
    (secret-detector names to skip)."""
    return _load_profile_file("redaction.json", profile, registry_root=registry_root, fail_closed=fail_closed)
