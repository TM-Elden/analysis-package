"""Per-profile field_path grammar (P2): resolves a labels/overrides.jsonl row's
field_path string into the output-schema key columns + value column it refers to.

Declared in profiles/<name>/field_path_grammar.json (loaded via
ap_gate.profiles.load_profile_field_path_grammar), not hardcoded here - each profile
maps its own output naming convention. This makes field_path resolution mechanical
instead of the per-profile eyeballing the gap analysis found (report section 2.3, G2);
it also benefits the planned C17 cycle-diff and C4 bot-citation work, not just training
export, so it lives in ap_gate proper rather than under a training-specific module.

Not wired into any gate check today - declarative grammar + resolver only, per task
scope. A future check (or the training exporter) can call resolve_field_path directly.
"""

from __future__ import annotations

import re
from typing import Any

from ap_gate.profiles import load_profile_field_path_grammar

_PLACEHOLDER_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")


def _template_to_regex(template: str) -> re.Pattern[str]:
    """Turn a '{name}'-templated field_path (dots and literal text as separators) into
    an anchored regex with one named group per placeholder. Placeholders never cross a
    '.' segment boundary - field_path segments are dot-separated by convention."""
    parts: list[str] = []
    last = 0
    for m in _PLACEHOLDER_RE.finditer(template):
        parts.append(re.escape(template[last : m.start()]))
        parts.append(f"(?P<{m.group(1)}>[^.]+)")
        last = m.end()
    parts.append(re.escape(template[last:]))
    return re.compile("^" + "".join(parts) + "$")


def resolve_field_path(profile_name: str, field_path: str) -> dict[str, Any] | None:
    """Resolve field_path against profile_name's declared grammar.

    Returns {"output": <output_contract name>, "value_column": <str|None>, "keys": {col: value}}
    on a match, or None if the profile has no registered grammar or no declared template
    matches field_path.
    """
    grammar = load_profile_field_path_grammar(profile_name)
    if grammar is None:
        return None
    for output_name, spec in (grammar.get("outputs") or {}).items():
        template = spec.get("template")
        if not template:
            continue
        match = _template_to_regex(template).match(field_path)
        if match is None:
            continue
        key_columns = spec.get("key_columns", [])
        return {
            "output": output_name,
            "value_column": spec.get("value_column"),
            "keys": {col: match.group(col) for col in key_columns if col in match.groupdict()},
        }
    return None
