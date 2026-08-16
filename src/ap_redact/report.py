"""RedactionReport: the C14 audit record, and its store-sidecar persistence.

Stored under `<store_root>/redaction/<package_id>/<package_version>.json` - a sidecar next to the
store, never inside the package's own `qa/` directory. Packages are immutable after publish
(phase-2 precedent); the redaction report is a live, re-derivable-at-will artifact (redaction rules
and secret detectors evolve), so it cannot live inside package content without violating that
immutability model. Keyed to `(package_id, package_version)` exactly like every other store-scoped
record (`ap_store.db`'s `packages` / `package_audit` tables).
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def _utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class RedactionReport:
    package_id: str
    package_version: str
    generated_at: str = field(default_factory=_utcnow)
    blocked: bool = False
    block_reason: str | None = None
    redacted_field_paths: tuple[str, ...] = ()
    secret_findings: tuple[dict[str, str], ...] = ()
    chunk_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RedactionReport":
        data = dict(data)
        data["redacted_field_paths"] = tuple(data.get("redacted_field_paths") or ())
        data["secret_findings"] = tuple(data.get("secret_findings") or ())
        return cls(**data)


def sidecar_path(store_root: Path | str, package_id: str, package_version: str) -> Path:
    return Path(store_root) / "redaction" / package_id / f"{package_version}.json"


def write_report(store_root: Path | str, report: RedactionReport) -> Path:
    path = sidecar_path(store_root, report.package_id, report.package_version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report.to_dict(), indent=2, sort_keys=True), encoding="utf-8")
    return path


def read_report(store_root: Path | str, package_id: str, package_version: str) -> RedactionReport | None:
    path = sidecar_path(store_root, package_id, package_version)
    if not path.is_file():
        return None
    return RedactionReport.from_dict(json.loads(path.read_text(encoding="utf-8")))
