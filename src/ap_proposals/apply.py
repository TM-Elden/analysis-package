"""The C7 apply mechanism (design report section 5.5): the config-vs-code split.

`profile_change` and `reason_code_add` are config - they get a real, transactional write to the
versioned profile registry (`ap_registry.profile_registry.ProfileRegistry`). `standard_change` and
`check_add` are code - no mechanism can auto-apply Python, so approval instead exports a
human-readable spec artifact a maintainer takes into a normal PR.

This module is pure wiring: it reuses `ProfileRegistry` (already built,
`src/ap_registry/profile_registry.py`) and `ap_planner_bot.dry_run.dry_run` (already built)
exactly as they stand - it does not reimplement registry or dry-run logic. `ap_proposals.workflow.
ProposalWorkflow` is the only caller; see that module for the transactional contract (apply first,
only persist the decision if the apply step succeeds).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ap_gate.profiles import PROFILES_ROOT
from ap_proposals.store import ProposalStoreError
from ap_registry.profile_registry import ProfileRegistry, ProfileRegistryError


class ProposalApplyError(ProposalStoreError):
    """The apply step (registry write for a declarative kind, spec export for a code kind)
    failed. Raised *before* any status-changing store write, so the proposal is guaranteed to
    still be `pending_hitl` when this propagates - see `ProposalWorkflow.decide`."""


def _bump_minor(version: str) -> str:
    """'0.1' -> '0.2'. Profile registry versions are '<major>.<minor>' (see
    `ProfileRegistry._version_sort_key`) - every apply-on-approve bump is a minor bump; a major
    bump (breaking change) is not something a HITL-approved proposal does automatically."""
    major, _, minor = version.partition(".")
    try:
        return f"{major}.{int(minor) + 1}"
    except ValueError as exc:
        raise ProposalApplyError(f"cannot bump non-numeric registry version {version!r}") from exc


def _current_file_content(registry: ProfileRegistry, name: str, filename: str) -> dict[str, Any] | None:
    """Read-only: `name`'s current registry content for `filename`, or the repo's vendored
    default if `name` has never been touched in this registry. Never seeds or writes - safe to
    call from a dry-run (which must never mutate the real registry)."""
    version = registry.current_version(name)
    if version is not None:
        return (registry.read_version(name, version) or {}).get(filename)
    seed_path = PROFILES_ROOT / name / filename
    if seed_path.is_file():
        return json.loads(seed_path.read_text(encoding="utf-8"))
    return None


def compute_changed_files(registry: ProfileRegistry, kind: str, diff: dict[str, Any]) -> dict[str, dict[str, Any] | None]:
    """The `ProfileRegistry.bump_version`-shaped patch (filename -> new content, or None to
    delete) a declarative proposal's `diff_json` represents. Read-only over `registry` - used
    identically by the real apply (`apply_declarative`) and by dry-run (`run_dry_run`)."""
    if kind == "profile_change":
        return {diff["file"]: diff["after"]}
    if kind == "reason_code_add":
        name = diff["profile"]
        current = _current_file_content(registry, name, "reason_codes.json") or {
            "profile": name,
            "reason_codes": [],
            "other_requires_reason_text": False,
        }
        codes = list(current.get("reason_codes", []))
        if diff["code"] not in codes:
            codes.append(diff["code"])
        updated = dict(current)
        updated["reason_codes"] = codes
        return {"reason_codes.json": updated}
    raise ValueError(f"compute_changed_files: not a declarative kind: {kind!r}")


def apply_declarative(registry: ProfileRegistry, kind: str, diff: dict[str, Any], *, actor_id: str) -> str:
    """Write the proposal's effective diff to the registry as a new profile version and return
    that version string. Seeds the profile from the repo default on first touch (idempotent).
    Raises `ProposalApplyError` on any registry-level failure (e.g. a version collision) - the
    caller (`ProposalWorkflow.decide`) must not have written anything to the proposal store yet
    when this raises, so the proposal is left exactly where it was."""
    name = diff["profile"]
    try:
        registry.ensure_seeded(name)
        current = registry.current_version(name)
        assert current is not None  # ensure_seeded just guaranteed this
        changed_files = compute_changed_files(registry, kind, diff)
        new_version = _bump_minor(current)
        return registry.bump_version(
            name, new_version, changed_files, note=f"applied via proposal decision ({kind})", actor=actor_id
        )
    except ProfileRegistryError as exc:
        raise ProposalApplyError(f"registry apply failed for profile {name!r}: {exc}") from exc


def run_dry_run(package_store: Any, store_root: Path, kind: str, diff: dict[str, Any]) -> dict[str, Any]:
    """Run `ap_planner_bot.dry_run.dry_run` for a declarative proposal's effective diff and
    return its JSON-serializable shape (what gets stored in `dry_run_json`). Imported lazily to
    avoid `ap_proposals` importing `ap_planner_bot` (and its `ap_gate`/`ap_store` transitive
    weight) at module load time for callers that never dry-run."""
    from ap_planner_bot.dry_run import dry_run as _dry_run

    profile_name = diff["profile"]
    registry = ProfileRegistry(store_root)
    proposed_files = compute_changed_files(registry, kind, diff)
    result = _dry_run(package_store, store_root, profile_name, proposed_files)
    return result.to_dict()


def export_spec(store_root: Path, proposal_id: str, kind: str, summary: str, rationale: str, diff: dict[str, Any], *, actor_id: str) -> str:
    """Write a markdown spec artifact (+ the proposal's draft patch, if `diff` carries one) to
    `<store_root>/proposal_specs/<proposal_id>.md` and return its path relative to `store_root`
    (posix-style) - what gets stored in `spec_artifact_path` and served back by
    `GET /proposals/{id}/spec`. This is the concrete, retrievable artifact a maintainer takes
    into a normal PR; no code is ever auto-applied."""
    specs_dir = Path(store_root) / "proposal_specs"
    specs_dir.mkdir(parents=True, exist_ok=True)
    target = specs_dir / f"{proposal_id}.md"

    lines = [
        f"# Standard-change proposal: {proposal_id}",
        "",
        f"- kind: {kind}",
        f"- approved by: {actor_id}",
        "",
        "## Summary",
        "",
        summary,
        "",
        "## Rationale",
        "",
        rationale,
        "",
        "## Diff (as approved)",
        "",
        "```json",
        json.dumps(diff, indent=2, sort_keys=True),
        "```",
    ]
    patch = diff.get("patch") if isinstance(diff, dict) else None
    if patch:
        lines += ["", "## Draft patch", "", "```diff", patch, "```"]
    lines += [
        "",
        "---",
        "This spec was exported automatically on approval of a `standard_change`/`check_add` "
        "proposal (C7). It is not applied to the codebase - land it through the normal PR/CI "
        "path (gold-pack regression and all).",
        "",
    ]
    target.write_text("\n".join(lines), encoding="utf-8")
    return target.relative_to(Path(store_root)).as_posix()
