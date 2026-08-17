"""I/O for the gate-analytics trend file, `<store_root>/analytics/snapshots.jsonl` (design report
`data/fathm-phase5-readiness/report.md` section 5.2). Deliberately split out of `analytics.py`
(pure computation, no I/O) - this module's only job is appending/reading the file, over dicts
`analytics.py::build_snapshot` already produced.

One JSON object per line, oldest first. Append-only: `append_snapshot` never edits or drops a
prior row, so the trend series is exactly the run history (weekly sweep + on-demand "Recompute
now" clicks both append here - see `ap_planner_bot.sweep.run_sweep` and
`ap_console.routes.dashboard_recompute`). The append itself is write-whole-file-to-temp-then-
`os.replace`, the same atomic-write pattern `ap_registry.profile_registry` uses, so a reader never
observes a torn line from a concurrent writer.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

_ANALYTICS_DIRNAME = "analytics"
_SNAPSHOTS_FILENAME = "snapshots.jsonl"


def snapshots_path(store_root: Path) -> Path:
    return Path(store_root) / _ANALYTICS_DIRNAME / _SNAPSHOTS_FILENAME


def append_snapshot(store_root: Path, snapshot: dict[str, Any]) -> None:
    path = snapshots_path(store_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    new_line = json.dumps(snapshot, sort_keys=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=".snapshots-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(existing)
            fh.write(new_line + "\n")
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)


def read_snapshots(store_root: Path) -> list[dict[str, Any]]:
    """Oldest-first. Empty list if the file doesn't exist yet (no sweep/recompute has ever run)."""
    path = snapshots_path(store_root)
    if not path.is_file():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows
