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


def profile_short_name(profile: str | None) -> str | None:
    """'commodity_commit_forecast/0.1' -> 'commodity_commit_forecast'."""
    if not isinstance(profile, str) or not profile:
        return None
    return profile.split("/", 1)[0]
