"""Renders an already-published package's gate report as HTML - reuses `ap_gate.report.html_report`
(the same renderer `ap-gate check --html` and every other gate-report consumer uses) rather than
building a second gate-report template. The only new work here is materializing the package's
immutable stored bytes to a scratch directory so the gate can be re-run against them, exactly like
`ap_api.app._run_gate` does for `POST /packages/validate` - kept as its own function (not imported
from `ap_api.app`) so `ap_console` never depends on `ap_api.app` for anything but the FastAPI `app`
instance it mounts onto.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from ap_gate.checks.context import CheckContext
from ap_gate.checks.registry import run_all
from ap_gate.report.html_report import to_html
from ap_gate.report.model import build_report
from ap_gate.load_manifest import load_manifest
from ap_store.store import PackageStore


def render_gate_report_html(store: PackageStore, package_id: str, package_version: str) -> str:
    """Raises `ap_store.store.StoreError` if no such package_version exists."""
    with tempfile.TemporaryDirectory(prefix="ap-console-gate-") as tmp:
        pkg_dir = store.extract(package_id, package_version, Path(tmp))
        manifest = load_manifest(pkg_dir)
        ctx = CheckContext(package_path=pkg_dir, manifest=manifest)
        outcomes = run_all(ctx)
        report = build_report(
            package_id=str(manifest.get("package_id", package_id)),
            title=str(manifest.get("title", "")),
            as_of=str(manifest.get("as_of", "")),
            qa_status=str((manifest.get("qa") or {}).get("status", "")),
            profile=str(manifest.get("profile", "")),
            outcomes=outcomes,
        )
        return to_html(report)
