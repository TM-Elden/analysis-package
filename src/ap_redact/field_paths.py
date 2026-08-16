"""Which field paths get person-identifier-scrubbed by default, and how a profile's
`redaction.json` adjusts that set.

Field paths are plain dotted strings naming a location this module understands, not a generic
resolver over arbitrary manifest shapes (contrast `ap_gate.field_path`, which resolves
profile-declared grammar against override rows - a different, unrelated concept). The two kinds
recognized here:

- `manifest.<dotted path under MANIFEST.yaml>` - e.g. `manifest.owners.analyst.id`.
- `labels.<field name>` - that field is dropped from every `labels/*.jsonl` row (overrides,
  judgments, truths alike), regardless of which file it came from.
"""

from __future__ import annotations

from typing import Any

# 13e default: person identifiers scrubbed everywhere they appear in the example package.
# `manifest.owners.agent` scrubs the whole agent sub-object (id, harness, model,
# prompt_tool_hash) - all of it is agent-identifying, not just `.id` like analyst/reviewer.
DEFAULT_SCRUB_FIELD_PATHS: frozenset[str] = frozenset(
    {
        "manifest.owners.analyst.id",
        "manifest.owners.reviewer.id",
        "manifest.owners.agent",
        "labels.author",
    }
)


def resolve_scrub_set(profile_cfg: dict[str, Any] | None) -> frozenset[str]:
    """Merge `DEFAULT_SCRUB_FIELD_PATHS` with a profile's `allow_field_paths` (paths the profile
    chooses to keep unredacted) and `deny_field_paths` (extra paths the profile wants scrubbed).
    No profile config (the `reason_codes.json`-precedent case) means the defaults apply
    unmodified."""
    cfg = profile_cfg or {}
    allow = set(cfg.get("allow_field_paths") or [])
    deny = set(cfg.get("deny_field_paths") or [])
    return frozenset((set(DEFAULT_SCRUB_FIELD_PATHS) | deny) - allow)


def disabled_detectors(profile_cfg: dict[str, Any] | None) -> frozenset[str]:
    return frozenset((profile_cfg or {}).get("disabled_detectors") or [])


def scrub_manifest_dict(manifest: dict[str, Any], scrub_paths: frozenset[str]) -> dict[str, Any]:
    """Return a deep-ish copy of `manifest` with every `manifest.<dotted>` path in `scrub_paths`
    removed. Only touches the `owners` sub-tree paths this module knows about - anything else in
    `scrub_paths` that doesn't resolve is simply a no-op (a profile can list a path that doesn't
    exist in a given package without erroring)."""
    import copy

    out = copy.deepcopy(manifest)
    for path in scrub_paths:
        if not path.startswith("manifest."):
            continue
        parts = path.removeprefix("manifest.").split(".")
        _delete_path(out, parts)
    return out


def _delete_path(data: dict[str, Any], parts: list[str]) -> None:
    node = data
    for part in parts[:-1]:
        if not isinstance(node, dict) or part not in node:
            return
        node = node[part]
    if isinstance(node, dict):
        node.pop(parts[-1], None)


def scrub_label_row(row: dict[str, Any], scrub_paths: frozenset[str]) -> dict[str, Any]:
    """Return a copy of one labels/*.jsonl row with every `labels.<field>` in `scrub_paths`
    dropped."""
    fields_to_drop = {p.removeprefix("labels.") for p in scrub_paths if p.startswith("labels.")}
    return {k: v for k, v in row.items() if k not in fields_to_drop}
