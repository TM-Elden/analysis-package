"""The C6 evidence layer's stage 1: a deterministic corpus scan.

Extracts every **approved** package (`store.extract`, generalizing the pattern in
`ap_console.gate_report.render_gate_report_html` - read that module first if this one is
unfamiliar), reruns the gate in-process against the extracted bytes exactly like
`ap_console.gate_report` and `ap_api.app._run_gate` do, and parses the manifest + override rows
into a flat, aggregable `PackageScan`. No persisted telemetry and no incremental state: a full
scan recomputes from the store every call. Measured cost at pilot scale (design report section
5.2/2) is well under a second per package, so this is cheap enough to run on every sweep and every
proposal dry-run (a later chunk) without caching.

**Shape carries the no-author-aggregation invariant, not just discipline in `detectors.py`.**
`PackageScan.override_rows` keeps only `field_path` / `reason_code` / `reason_text` from each
parsed `labels/overrides.jsonl` row - `author`, `ts`, `before`, `after`, `evidence_refs`,
`agent_draft` are dropped at parse time. A detector literally cannot key off an author it was
never handed. See `detectors.py`'s module docstring for the rest of the invariant and
`test_detectors.py::test_no_author_or_owner_keys_anywhere_in_scan_or_findings` for the enforcement
test.
"""

from __future__ import annotations

import json
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from ap_gate.checks.context import CheckContext
from ap_gate.checks.pathsafe import resolve_contained
from ap_gate.checks.registry import run_all
from ap_gate.checks.types import CheckOutcome
from ap_gate.load_manifest import load_manifest
from ap_store.store import ListFilter, PackageStore


@dataclass(frozen=True)
class OverrideRow:
    """A `labels/overrides.jsonl` row, stripped to only the fields any v0 detector may use.

    Deliberately excludes `author`, `ts`, `before`, `after`, `evidence_refs`, `agent_draft` -
    not because they're uninteresting, but because keeping them on this type would make it easy
    for a future detector to key off `author` by accident. Add a field here only after checking
    it against the no-author-aggregation invariant (`detectors.py`'s module docstring).
    """

    field_path: str
    reason_code: str
    reason_text: str = ""


@dataclass(frozen=True)
class PackageScan:
    package_id: str
    package_version: str
    profile: str  # manifest's raw "<name>/<version>" string, "" if unset
    #: check_id -> outcome, post-waiver (the same `run_all` every other gate consumer uses).
    outcomes: dict[str, CheckOutcome] = field(default_factory=dict)
    override_rows: tuple[OverrideRow, ...] = ()


@dataclass(frozen=True)
class CorpusScan:
    packages: tuple[PackageScan, ...] = ()

    def __len__(self) -> int:
        return len(self.packages)


def _iter_approved_records(store: PackageStore):
    """Page through every `status == "approved"` record in the store."""
    page = 1
    page_size = 50
    while True:
        result = store.list(ListFilter(status="approved", page=page, page_size=page_size))
        if not result.items:
            return
        yield from result.items
        if len(result.items) < page_size:
            return
        page += 1


def _parse_override_rows(pkg_dir: Path, manifest: dict) -> tuple[OverrideRow, ...]:
    overrides_path = (manifest.get("labels") or {}).get("overrides_path")
    if not overrides_path:
        return ()
    full_path = resolve_contained(pkg_dir, overrides_path)
    if full_path is None or not full_path.is_file():
        return ()

    rows: list[OverrideRow] = []
    for line in full_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue  # labels_jsonl_parse already reports this in the rerun gate outcomes
        if not isinstance(obj, dict):
            continue
        field_path = obj.get("field_path")
        reason_code = obj.get("reason_code")
        if not field_path or not reason_code:
            continue
        rows.append(
            OverrideRow(
                field_path=str(field_path),
                reason_code=str(reason_code),
                reason_text=str(obj.get("reason_text") or ""),
            )
        )
    return tuple(rows)


def scan_package(store: PackageStore, package_id: str, package_version: str) -> PackageScan:
    """Extract, rerun the gate, and parse override rows for one approved package version.

    Raises `ap_store.store.StoreError` if no such package_version exists (mirrors
    `ap_console.gate_report.render_gate_report_html`).
    """
    with tempfile.TemporaryDirectory(prefix="ap-planner-scan-") as tmp:
        pkg_dir = store.extract(package_id, package_version, Path(tmp))
        manifest = load_manifest(pkg_dir)
        ctx = CheckContext(package_path=pkg_dir, manifest=manifest)
        outcomes = {o.check_id: o for o in run_all(ctx)}
        override_rows = _parse_override_rows(pkg_dir, manifest)

    return PackageScan(
        package_id=package_id,
        package_version=package_version,
        profile=str(manifest.get("profile") or ""),
        outcomes=outcomes,
        override_rows=override_rows,
    )


def scan_corpus(store: PackageStore) -> CorpusScan:
    """Scan every currently-approved package version in `store`.

    One `PackageScan` per approved `(package_id, package_version)` row - if a package has been
    republished under a new version and only the new one is `approved`, only that version is
    scanned (mirrors the store's own live-status semantics, not a snapshot of publish history).
    """
    scans = tuple(
        scan_package(store, record.package_id, record.package_version)
        for record in _iter_approved_records(store)
    )
    return CorpusScan(packages=scans)
