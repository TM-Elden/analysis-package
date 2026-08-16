"""reindex_package: the one-package-at-a-time reindex hook.

Not wired as an automatic side effect of `ap_review.ReviewWorkflow.transition` - that would invert
the module layering (`ap_review` builds on `ap_store`, neither imports `ap_index`) and this task is
explicitly index-and-query only, not the bot/console that will call it. Instead, this is a plain
function a caller invokes after any status-changing transition (a later API route, or a test - see
`tests/test_ap_index.py`). At this corpus scale a full package re-index is sub-second (report
section 5.3), so there is deliberately no incremental/partial-chunk update path here - re-deriving
membership from the store's current status on every call is the whole strategy.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ap_gate.load_manifest import load_manifest
from ap_index.index_store import IndexStore
from ap_redact.redact import redact_package
from ap_redact.report import RedactionReport, write_report
from ap_store.store import PackageStore


def reindex_package(
    *,
    store: PackageStore,
    index: IndexStore,
    store_root: Path | str,
    package_id: str,
    package_version: str,
) -> RedactionReport | None:
    """Re-derive one package version's index membership from its current store status.

    `approved` -> redact + (re)index and write the redaction-report sidecar.
    anything else (draft/in_review/rejected, or the record no longer exists) -> ensure it is
    absent from the index. Returns the `RedactionReport` when redaction ran (i.e. the package was
    `approved`), else None - callers that only care about corpus membership can ignore the return.
    """
    record = store.get(package_id, package_version)
    if record is None or record.status != "approved":
        index.remove_package(package_id, package_version)
        return None

    with tempfile.TemporaryDirectory(prefix="ap-index-redact-") as tmp:
        pkg_dir = store.extract(package_id, package_version, Path(tmp) / "pkg")
        manifest = load_manifest(pkg_dir)
        chunks, report = redact_package(pkg_dir, manifest, package_id=package_id, package_version=package_version)

    write_report(store_root, report)
    if report.blocked:
        index.remove_package(package_id, package_version)
    else:
        index.index_package(chunks)
    return report
