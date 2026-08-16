"""Version-keyed registry: which standard_version maps to which schema file.

Kept as a single data table (not literals scattered through checks.py /
schema.py / cli.py) so a future ap/0.3 only needs one new entry here, and so
C13 (Standard migration, multi-version gate support) is additive rather than
a rewrite. See second review section 5.4.
"""

from __future__ import annotations

from pathlib import Path

# Repo root, computed once from this file's location:
# <repo>/src/ap_gate/versions.py -> parents[2] == <repo>
REPO_ROOT = Path(__file__).resolve().parents[2]

# standard_version string -> schema file path (absolute, resolved from REPO_ROOT).
# Add a new entry here when a new ap/N.M ships; do not add version literals
# to individual checks.
SUPPORTED_VERSIONS: dict[str, Path] = {
    "ap/0.2": REPO_ROOT / "standard" / "ap-0.2" / "schemas" / "manifest.schema.json",
}


def schema_path_for(standard_version: str) -> Path | None:
    """Return the schema file Path for a standard_version string, or None if unsupported."""
    return SUPPORTED_VERSIONS.get(standard_version)


def supported_versions() -> list[str]:
    return sorted(SUPPORTED_VERSIONS.keys())
