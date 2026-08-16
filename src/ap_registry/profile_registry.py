"""Versioned profile registry (C7 apply substrate, Phase 4 design report section 5.5).

`<store_root>/standard_registry/profiles/<name>/<version>/*.json` holds the tenant's live,
mutable profile state - seeded from the repo's vendored `profiles/<name>/` tree the first time
a name is touched. The repo tree remains the default/seed forever; this registry is what
`ap_gate.profiles` (when `AP_STANDARD_REGISTRY_ROOT` is set) reads, and what the later
proposal-approval apply step (not this task - see CLAUDE.md's Phase 4 section) will write to
on approve.

Layout under `self.root` (`<store_root>/standard_registry/profiles`):

    <name>/<version>/*.json   - one immutable snapshot per version, written once
    <name>/_pointer.json      - {"current": "<version>"}
    <name>/_changelog.jsonl   - append-only bump history (one JSON object per line)

A version directory, once written, is never edited in place - `bump_version` always creates a
new one. This is what lets `ap_gate.profiles`' read cache be keyed by version alone (see that
module's docstring) instead of needing invalidation logic beyond a version bump.

Writes are made durable via write-to-temp-then-`os.replace`, both for the version directory
(built under a temp name in the same parent directory, then atomically renamed into place) and
the pointer file - so a reader never observes a half-written version or a pointer aimed at one.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import Any

from ap_gate.profiles import PROFILES_ROOT, invalidate_registry_cache


class ProfileRegistryError(Exception):
    """Registry usage error: unknown name/version, a non-monotonic version bump, or an
    attempt to overwrite an already-written (immutable) version directory."""


def _validate_registry_component(value: str, what: str) -> str:
    """Reject a profile name / version / filename that could escape the registry root via a
    path separator, a `..`/`.` segment, or an absolute-path override - the same class of bug
    `ap_gate.checks.pathsafe.resolve_contained` closes for manifest-declared paths
    (`Path.__truediv__` follows `..` and treats an absolute right-hand side as an override).
    These values ultimately come from proposal `diff_json` (`ap_proposals.apply`), which is
    planner/agent-submitted content - never join one into a filesystem path unvalidated."""
    if not isinstance(value, str) or not value or value in (".", "..") or "\x00" in value:
        raise ProfileRegistryError(f"invalid {what}: {value!r}")
    if "/" in value or "\\" in value:
        raise ProfileRegistryError(f"invalid {what} (must not contain a path separator): {value!r}")
    if Path(value).is_absolute():
        raise ProfileRegistryError(f"invalid {what} (must not be an absolute path): {value!r}")
    return value


def _version_sort_key(version: str) -> tuple[int, ...]:
    """'0.10' sorts after '0.9' - numeric per-segment comparison, not lexicographic."""
    parts = []
    for segment in version.split("."):
        try:
            parts.append(int(segment))
        except ValueError:
            parts.append(0)
    return tuple(parts)


class ProfileRegistry:
    def __init__(self, store_root: Path):
        self.store_root = Path(store_root)
        self.root = self.store_root / "standard_registry" / "profiles"

    def _name_dir(self, name: str) -> Path:
        _validate_registry_component(name, "profile name")
        return self.root / name

    def _pointer_path(self, name: str) -> Path:
        return self._name_dir(name) / "_pointer.json"

    def _changelog_path(self, name: str) -> Path:
        return self._name_dir(name) / "_changelog.jsonl"

    def is_seeded(self, name: str) -> bool:
        return self._pointer_path(name).is_file()

    def names(self) -> list[str]:
        """Every profile name that has been touched (seeded or bumped) in this registry,
        sorted. Used by `GET /standard/versions` (ap_api) to enumerate what to report - a
        directory only counts once it has a `_pointer.json` (i.e. `is_seeded`), so a
        half-written or otherwise stray subdirectory is never reported."""
        if not self.root.is_dir():
            return []
        return sorted(p.name for p in self.root.iterdir() if p.is_dir() and self.is_seeded(p.name))

    def current_version(self, name: str) -> str | None:
        pointer = self._pointer_path(name)
        if not pointer.is_file():
            return None
        return json.loads(pointer.read_text(encoding="utf-8"))["current"]

    def versions(self, name: str) -> list[str]:
        """All version directories for `name`, oldest first."""
        name_dir = self._name_dir(name)
        if not name_dir.is_dir():
            return []
        return sorted((p.name for p in name_dir.iterdir() if p.is_dir()), key=_version_sort_key)

    def read_version(self, name: str, version: str) -> dict[str, Any] | None:
        """`{filename: parsed_json}` for one version directory, or None if it doesn't exist."""
        version_dir = self._name_dir(name) / version
        if not version_dir.is_dir():
            return None
        return {path.name: json.loads(path.read_text(encoding="utf-8")) for path in sorted(version_dir.glob("*.json"))}

    def changelog(self, name: str) -> list[dict[str, Any]]:
        path = self._changelog_path(name)
        if not path.is_file():
            return []
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]

    def ensure_seeded(self, name: str, *, initial_version: str = "0.1") -> str:
        """Seed `<name>/<initial_version>/` from the repo's `profiles/<name>/` tree if this
        name has never been touched in the registry. Idempotent - a second call is a no-op and
        returns the existing current version untouched (even if it isn't `initial_version`)."""
        existing = self.current_version(name)
        if existing is not None:
            return existing

        seed_dir = PROFILES_ROOT / name
        files: dict[str, Any] = {}
        if seed_dir.is_dir():
            for path in sorted(seed_dir.glob("*.json")):
                files[path.name] = json.loads(path.read_text(encoding="utf-8"))

        self._write_version_dir(name, initial_version, files)
        self._write_pointer(name, initial_version)
        self._append_changelog(
            name,
            {
                "version": initial_version,
                "previous": None,
                "note": "seeded from repo profiles/ tree" if seed_dir.is_dir() else "seeded empty (no repo profile found)",
                "actor": None,
                "ts": time.time(),
            },
        )
        invalidate_registry_cache(name=name)
        return initial_version

    def bump_version(
        self,
        name: str,
        new_version: str,
        changed_files: dict[str, dict[str, Any] | None],
        *,
        note: str = "",
        actor: str | None = None,
    ) -> str:
        """Write a new version directory (the current version's files with `changed_files`
        applied on top - a None value deletes that file from the new version), append a
        changelog row, and flip the current pointer.

        This is one atomic sequence with the pointer flip as its linearization point: readers
        see either the old or the new version, never a partially-written one (see the module
        docstring). The trigger for calling this - a declarative-kind proposal being approved -
        is `ap_proposals.apply.apply_declarative`.
        """
        if self.current_version(name) is None:
            self.ensure_seeded(name)
        current = self.current_version(name)
        if current is not None and _version_sort_key(new_version) <= _version_sort_key(current):
            raise ProfileRegistryError(f"profile '{name}': new version {new_version!r} must be greater than current {current!r}")

        base_files = (self.read_version(name, current) or {}) if current else {}
        new_files = dict(base_files)
        for filename, content in changed_files.items():
            if content is None:
                new_files.pop(filename, None)
            else:
                new_files[filename] = content

        self._write_version_dir(name, new_version, new_files)
        self._write_pointer(name, new_version)
        self._append_changelog(
            name,
            {"version": new_version, "previous": current, "note": note, "actor": actor, "ts": time.time()},
        )
        invalidate_registry_cache(name=name)
        return new_version

    def seed_version(self, name: str, version: str, files: dict[str, Any]) -> None:
        """Write `version` directly as `name`'s current version - no changelog entry, no
        monotonic-version check, no read-modify-write of a prior version's files.

        For scratch-registry setup only (`ap_planner_bot.dry_run`'s overlay, and tests) - real
        workflow writes go through `ensure_seeded` (first touch) or `bump_version` (every write
        after)."""
        self._write_version_dir(name, version, files)
        self._write_pointer(name, version)
        invalidate_registry_cache(name=name)

    def _write_version_dir(self, name: str, version: str, files: dict[str, Any]) -> None:
        name_dir = self._name_dir(name)
        _validate_registry_component(version, "version")
        for filename in files:
            _validate_registry_component(filename, "filename")
        name_dir.mkdir(parents=True, exist_ok=True)
        final_dir = name_dir / version
        if final_dir.exists():
            raise ProfileRegistryError(f"profile '{name}' version {version!r} already exists - versions are immutable")
        tmp_dir = Path(tempfile.mkdtemp(prefix=f".{version}.tmp-", dir=name_dir))
        try:
            for filename, content in files.items():
                (tmp_dir / filename).write_text(json.dumps(content, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            os.replace(tmp_dir, final_dir)
        except Exception:
            shutil.rmtree(tmp_dir, ignore_errors=True)
            raise

    def _write_pointer(self, name: str, version: str) -> None:
        pointer = self._pointer_path(name)
        tmp = pointer.with_suffix(".json.tmp")
        tmp.write_text(json.dumps({"current": version}), encoding="utf-8")
        os.replace(tmp, pointer)

    def _append_changelog(self, name: str, row: dict[str, Any]) -> None:
        with self._changelog_path(name).open("a", encoding="utf-8") as f:
            f.write(json.dumps(row) + "\n")
