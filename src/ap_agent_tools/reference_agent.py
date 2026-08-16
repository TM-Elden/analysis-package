#!/usr/bin/env python3
"""Reference agent script (C8 acceptance: "at least one reference agent script ... produces a
package and passes gate").

Demonstrates the full agent runtime contract slice end to end:

    package.create -> package.check (must pass) -> package.publish

Run directly:

    PYTHONPATH=src python3 -m ap_agent_tools.reference_agent --dest /tmp/demo-pack

Or import and call `run()` from a test / another script. This intentionally does not implement real
domain engines (bom_explode/allocate/netting) - see ap_agent_tools/templates/commodity_commit_forecast/
README.md; it demonstrates the contract, not a new computed forecast.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path

from ap_agent_tools.tools import package_check, package_create, package_publish
from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_store.models import PackageRecord


@dataclass
class RunResult:
    package_dir: Path
    gate_report: dict
    published: PackageRecord | None


def run(
    dest_dir: Path,
    *,
    title: str = "Reference agent commodity commit pack",
    analyst_id: str = "agent.reference",
    store_root: Path | None = None,
    publish: bool = True,
) -> RunResult:
    """Create a package, gate-check it, and (by default) publish it. Raises if the gate fails."""
    package_dir = package_create(dest_dir, title=title, analyst_id=analyst_id)

    report = package_check(package_dir)
    if report["overall"] != "pass":
        failing = [r["check_id"] for r in report["results"] if r["result"] == "fail" and not r["waived"]]
        raise RuntimeError(f"reference agent's own package failed the gate on {failing} - this is a bug, not expected")

    published = None
    if publish:
        actor = Identity(id=analyst_id, roles=frozenset({Role.ANALYST}))
        published = package_publish(package_dir, store_root=store_root or (Path(tempfile.mkdtemp(prefix="ap-store-")) ), actor=actor)

    return RunResult(package_dir=package_dir, gate_report=report, published=published)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", required=True, help="Directory to create the new package at (must not exist)")
    parser.add_argument("--title", default="Reference agent commodity commit pack")
    parser.add_argument("--analyst-id", default="agent.reference")
    parser.add_argument("--store-root", default=None, help="PackageStore root (defaults to a fresh temp dir)")
    parser.add_argument("--no-publish", action="store_true", help="Skip package.publish, just create + check")
    args = parser.parse_args(argv)

    result = run(
        Path(args.dest),
        title=args.title,
        analyst_id=args.analyst_id,
        store_root=Path(args.store_root) if args.store_root else None,
        publish=not args.no_publish,
    )

    print(f"ap-agent-tools: created package at {result.package_dir}")
    print(f"ap-agent-tools: gate overall = {result.gate_report['overall']}")
    if result.published is not None:
        print(
            f"ap-agent-tools: published {result.published.package_id}/{result.published.package_version} "
            f"(status={result.published.status}, gate_overall={result.published.gate_overall})"
        )
    print(json.dumps(result.gate_report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
