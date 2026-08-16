"""Assembles the layered gate report.

Two layers, by construction (second review sections 5.2 and 7.2):

- `results[]` - content-free: {check_id, result, severity, waived} only.
  No file paths, no field values, no messages, no person identifiers
  (author, owners.*). This is the layer a future telemetry / pooled
  conformance pipeline can consume directly, and the layer gate statistics
  must stay package-level (never person-level) on.
- `evidence[]` - human-facing: {check_id, message, paths}. Messages are
  written to serve the planner fixing the package (which path, which
  field, how to fix) - not as a compliance tripwire. Never carries person
  identifiers either (waiver author, override author) - see registry.py
  and the individual checks, which never put those into a message.

`package` carries manifest-level (not person-level) summary fields for the
human report header; it is not part of the content-free layer.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from ap_gate import __version__
from ap_gate.checks.types import CheckOutcome


def build_report(
    *,
    package_id: str,
    title: str,
    as_of: str,
    qa_status: str,
    profile: str,
    outcomes: list[CheckOutcome],
) -> dict[str, Any]:
    overall = "fail" if any(o.blocks_overall_pass() for o in outcomes) else "pass"
    return {
        "validator": f"ap-gate/{__version__}",
        "checks_run_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "package_id": package_id,
        "overall": overall,
        "results": [o.to_result_row() for o in outcomes],
        "evidence": [o.to_evidence_row() for o in outcomes],
        "package": {
            "title": title,
            "as_of": as_of,
            "qa_status": qa_status,
            "profile": profile,
        },
    }
