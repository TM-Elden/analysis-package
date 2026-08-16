"""C7 dry-run (Phase 4 design report section 5.6): "as if republished under the proposal".

`dry_run(...)` materializes a proposed post-change profile into a scratch standard-registry
root, reruns `ap_planner_bot.scan`'s corpus scan against it, and diffs per-package/per-check
outcomes against the current baseline (whatever the real registry, if any, currently serves).
Built directly on `scan.py`'s scan-under-an-overlay capability (`scan_corpus`'s
`registry_root` param, `scan_package`'s `_registry_root_override` seam) - it does not
reimplement gate-rerun logic.

Pure over the store + a throwaway scratch registry: never writes to the real
`<store_root>/standard_registry`, and has no `ap_proposals` dependency - attaching a result to
a proposal record is `ap_proposals.apply.run_dry_run`'s wiring, not this module's job. Cost is
the same as one extra full corpus scan (seconds at pilot scale, per `ap_planner_bot.scan`'s own
measured cost).
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ap_gate.profiles import PROFILES_ROOT
from ap_planner_bot.scan import CorpusScan, PackageScan, scan_corpus
from ap_registry.profile_registry import ProfileRegistry
from ap_store.store import PackageStore


@dataclass(frozen=True)
class CheckMovement:
    package_id: str
    package_version: str
    check_id: str
    before: str  # CheckOutcome.result: "pass" | "fail" | "skip"
    after: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "package_version": self.package_version,
            "check_id": self.check_id,
            "before": self.before,
            "after": self.after,
        }


@dataclass(frozen=True)
class DryRunResult:
    profile_name: str
    #: the profile version the overlay was evaluated at - the same version every currently-
    #: approved package under `profile_name` already declares (see `dry_run`'s docstring for
    #: why this is *not* a new version number).
    evaluated_version: str
    #: "<package_id>@<package_version>", packages whose overall gate pass/fail flips.
    newly_failing_packages: tuple[str, ...]
    newly_passing_packages: tuple[str, ...]
    #: every individual check_id whose result changed, even where the package's overall
    #: pass/fail didn't (e.g. an advisory check moving, or one required check among several
    #: already-failing ones).
    check_movements: tuple[CheckMovement, ...]

    def to_dict(self) -> dict[str, Any]:
        """JSON-serializable - the shape `ap_proposals.apply.run_dry_run` attaches to a
        proposal's `dry_run_json`."""
        return {
            "profile_name": self.profile_name,
            "evaluated_version": self.evaluated_version,
            "newly_failing_packages": list(self.newly_failing_packages),
            "newly_passing_packages": list(self.newly_passing_packages),
            "check_movements": [m.to_dict() for m in self.check_movements],
        }


def _package_key(scan: PackageScan) -> str:
    return f"{scan.package_id}@{scan.package_version}"


def _overall_pass(scan: PackageScan) -> bool:
    return not any(outcome.blocks_overall_pass() for outcome in scan.outcomes.values())


def _repo_default_files(profile_name: str) -> dict[str, Any]:
    seed_dir = PROFILES_ROOT / profile_name
    if not seed_dir.is_dir():
        return {}
    return {path.name: json.loads(path.read_text(encoding="utf-8")) for path in sorted(seed_dir.glob("*.json"))}


def dry_run(
    store: PackageStore,
    store_root: Path,
    profile_name: str,
    proposed_files: dict[str, dict[str, Any] | None],
) -> DryRunResult:
    """Diff the corpus scan under `proposed_files` (a patch: filename -> new content, or None
    to delete that file) applied on top of `profile_name`'s current registry files, against the
    real baseline.

    Deliberately evaluates the overlay at the *same* version number every currently-approved
    package under `profile_name` already declares, rather than a new one: a real approve bumps
    the version (0.1 -> 0.2, §5.5), and version-pinning means an already-published package would
    never adopt that new version's rules on its own - only new packages would. But "which
    packages would newly fail" is exactly the question a proposal's approver needs answered
    *before* deciding, over the corpus that exists *today* - so dry-run answers "if these
    packages' pinned version's files read as the proposal instead", which requires overlaying
    the version number they already pin, not one they'll never resolve to. This is the "as if
    republished under the proposal" framing from the design report (section 5.6): the packages
    aren't touched, only the profile files the gate resolves for them are.

    Baseline resolution mirrors production exactly: the real registry at
    `<store_root>/standard_registry` if one exists there, repo `PROFILES_ROOT` defaults
    otherwise - the same order `ap_gate.profiles` uses. Never writes to the real registry -
    the overlay lives in an isolated scratch registry for the duration of this call only.
    """
    real_registry = ProfileRegistry(store_root)
    baseline = scan_corpus(store, registry_root=real_registry.root)

    base_version = real_registry.current_version(profile_name)
    if base_version is not None:
        base_files = real_registry.read_version(profile_name, base_version) or {}
    else:
        base_version = "0.1"  # matches ProfileRegistry.ensure_seeded's own default first version
        base_files = _repo_default_files(profile_name)

    new_files = dict(base_files)
    for filename, content in proposed_files.items():
        if content is None:
            new_files.pop(filename, None)
        else:
            new_files[filename] = content

    with tempfile.TemporaryDirectory(prefix="ap-dry-run-registry-") as tmp:
        scratch_registry = ProfileRegistry(Path(tmp))
        scratch_registry.seed_version(profile_name, base_version, new_files)
        proposed = scan_corpus(store, registry_root=scratch_registry.root)

    return _diff(profile_name, base_version, baseline, proposed)


def _diff(profile_name: str, evaluated_version: str, baseline: CorpusScan, proposed: CorpusScan) -> DryRunResult:
    proposed_by_key = {_package_key(p): p for p in proposed.packages}
    movements: list[CheckMovement] = []
    newly_failing: list[str] = []
    newly_passing: list[str] = []

    for before in baseline.packages:
        key = _package_key(before)
        after = proposed_by_key.get(key)
        if after is None:
            continue  # package dropped out of the approved corpus mid-call - not this diff's concern

        before_pass, after_pass = _overall_pass(before), _overall_pass(after)
        if before_pass and not after_pass:
            newly_failing.append(key)
        elif after_pass and not before_pass:
            newly_passing.append(key)

        for check_id, before_outcome in before.outcomes.items():
            after_outcome = after.outcomes.get(check_id)
            if after_outcome is not None and before_outcome.result != after_outcome.result:
                movements.append(
                    CheckMovement(
                        package_id=before.package_id,
                        package_version=before.package_version,
                        check_id=check_id,
                        before=before_outcome.result,
                        after=after_outcome.result,
                    )
                )

    return DryRunResult(
        profile_name=profile_name,
        evaluated_version=evaluated_version,
        newly_failing_packages=tuple(newly_failing),
        newly_passing_packages=tuple(newly_passing),
        check_movements=tuple(movements),
    )
