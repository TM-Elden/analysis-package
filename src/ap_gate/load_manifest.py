"""Isolated manifest loading.

Every check receives an already-parsed manifest dict plus the package root
path - none of them touch YAML directly. That keeps a future alternate
envelope loader (e.g. reading ro-crate-metadata.json instead of
MANIFEST.yaml, per D1) a swap in this one module, not a change to every
check. See second review section 5.4.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ManifestLoadError(Exception):
    """Raised when MANIFEST.yaml is missing or is not parseable YAML at all.

    This is an IO/usage problem (exit code 2), distinct from a manifest that
    parses fine but fails schema validation (a normal must_fields check
    failure, exit code 1).
    """


def manifest_path(package_path: Path) -> Path:
    return package_path / "MANIFEST.yaml"


def load_manifest(package_path: Path) -> dict[str, Any]:
    """Load and parse MANIFEST.yaml from a package directory.

    Raises ManifestLoadError if the file is missing, unreadable, or not
    valid YAML, or if it does not parse to a mapping.
    """
    path = manifest_path(package_path)
    if not path.is_file():
        raise ManifestLoadError(f"MANIFEST.yaml not found at {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        raise ManifestLoadError(f"could not read {path}: {exc}") from exc
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ManifestLoadError(f"{path} is not valid YAML: {exc}") from exc
    if not isinstance(data, dict):
        raise ManifestLoadError(f"{path} must parse to a YAML mapping (object), got {type(data).__name__}")
    return data
