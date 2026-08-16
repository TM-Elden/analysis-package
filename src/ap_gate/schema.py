"""JSON Schema loading and validation for the manifest."""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

import jsonschema

from ap_gate.versions import schema_path_for


@lru_cache(maxsize=None)
def _load_schema(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def load_schema_for_version(standard_version: str) -> dict[str, Any] | None:
    """Return the parsed JSON Schema for a standard_version, or None if unsupported."""
    path = schema_path_for(standard_version)
    if path is None or not path.is_file():
        return None
    return _load_schema(path)


def validate_manifest(manifest: dict[str, Any], schema: dict[str, Any]) -> list[jsonschema.exceptions.ValidationError]:
    """Return all schema validation errors (empty list if valid)."""
    validator = jsonschema.Draft202012Validator(schema)
    return sorted(validator.iter_errors(manifest), key=lambda e: list(e.path))


def error_field_path(error: jsonschema.exceptions.ValidationError) -> str:
    """Render a validation error's location as a dotted/bracket field path for humans."""
    if not error.path:
        return "(root)"
    parts: list[str] = []
    for segment in error.path:
        if isinstance(segment, int):
            parts.append(f"[{segment}]")
        else:
            parts.append(f".{segment}" if parts else str(segment))
    return "".join(parts)
