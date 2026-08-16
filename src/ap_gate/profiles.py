"""Loads per-profile machine files (reason-code allow-lists, etc.).

Profile-specific requirements never fork the core manifest schema - they
live under profiles/<name>/ and are loaded here by profile id. See
STANDARD.md extensibility rule 3 and second review section 5.3.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from ap_gate.versions import REPO_ROOT

PROFILES_ROOT = REPO_ROOT / "profiles"


@lru_cache(maxsize=None)
def load_profile_reason_codes(profile_name: str) -> dict[str, Any] | None:
    """Return the parsed profiles/<profile_name>/reason_codes.json, or None if not registered."""
    path = PROFILES_ROOT / profile_name / "reason_codes.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def load_profile_training_grade(profile_name: str) -> dict[str, Any] | None:
    """Return the parsed profiles/<profile_name>/training_grade.json, or None if the
    profile hasn't opted into stricter training-export requirements at all.

    Core stays permissive by default: a missing file (or a present file with a flag left
    false) means that requirement isn't enforced. Recognized flags: `require_reason_text`
    (labels_row_shape, P1) and `require_agent_draft` (agent_draft_present, P4).
    """
    path = PROFILES_ROOT / profile_name / "training_grade.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def load_profile_field_path_grammar(profile_name: str) -> dict[str, Any] | None:
    """Return the parsed profiles/<profile_name>/field_path_grammar.json, or None if the
    profile has no declared grammar (P2). See ap_gate.field_path.resolve_field_path."""
    path = PROFILES_ROOT / profile_name / "field_path_grammar.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=None)
def load_profile_redaction(profile_name: str) -> dict[str, Any] | None:
    """Return the parsed profiles/<profile_name>/redaction.json, or None if the profile has no
    redaction overrides (C14). Core stays permissive: no file means ap_redact's hardcoded
    defaults apply unmodified. Recognized keys (see ap_redact.field_paths):
    `allow_field_paths` (default-scrubbed paths this profile keeps unredacted),
    `deny_field_paths` (extra paths to scrub beyond the defaults), and `disabled_detectors`
    (secret-detector names to skip)."""
    path = PROFILES_ROOT / profile_name / "redaction.json"
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def profile_short_name(profile: str | None) -> str | None:
    """'commodity_commit_forecast/0.1' -> 'commodity_commit_forecast'."""
    if not isinstance(profile, str) or not profile:
        return None
    return profile.split("/", 1)[0]
