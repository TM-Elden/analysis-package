"""ap-gate CLI.

    ap-gate check PATH [--json] [--html PATH]

Exit codes: 0 pass (including waived), 1 fail, 2 IO/usage error.
Same entrypoint for humans, CI, and agents (D6C) - there is no second soft path.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ap_gate import __version__
from ap_gate.checks.context import CheckContext
from ap_gate.checks.registry import run_all
from ap_gate.load_manifest import ManifestLoadError, load_manifest
from ap_gate.report.html_report import to_html
from ap_gate.report.json_report import to_json
from ap_gate.report.model import build_report


def _print_human(report: dict, outcomes) -> None:
    overall = report["overall"]
    status_word = "PASS" if overall == "pass" else "FAIL"
    n_pass = sum(1 for o in outcomes if o.result == "pass" and not o.waived)
    n_waived = sum(1 for o in outcomes if o.waived)
    n_fail = sum(1 for o in outcomes if o.result == "fail" and not o.waived)
    n_skip = sum(1 for o in outcomes if o.result == "skip")

    summary = f"ap-gate: {status_word} {report['package_id']}  {n_fail} failed, {n_pass} passed, {n_skip} skipped"
    if n_waived:
        summary += f", {n_waived} waived"
    print(summary)

    for o in outcomes:
        if o.waived:
            marker = "WAIVED"
        elif o.result == "fail":
            marker = "FAIL"
        elif o.result == "skip":
            marker = "SKIP"
        else:
            continue  # clean passes stay out of the default stdout summary
        first_line = (o.message or "").splitlines()[0] if o.message else ""
        print(f"  - [{marker}] {o.check_id}: {first_line}")

    if overall != "pass":
        print(
            "\nFor full evidence (paths, fields, how to fix each item): rerun with --json, "
            "or generate a report with --html PATH.",
            file=sys.stderr,
        )


def cmd_check(args: argparse.Namespace) -> int:
    package_path = Path(args.path)
    if not package_path.is_dir():
        print(f"ap-gate: error: '{args.path}' is not a directory", file=sys.stderr)
        return 2

    package_path = package_path.resolve()
    try:
        manifest = load_manifest(package_path)
    except ManifestLoadError as exc:
        print(f"ap-gate: error: {exc}", file=sys.stderr)
        return 2

    ctx = CheckContext(package_path=package_path, manifest=manifest)
    outcomes = run_all(ctx)
    report = build_report(
        package_id=str(manifest.get("package_id", "(unknown)")),
        title=str(manifest.get("title", "")),
        as_of=str(manifest.get("as_of", "")),
        qa_status=str((manifest.get("qa") or {}).get("status", "")),
        profile=str(manifest.get("profile", "")),
        outcomes=outcomes,
    )

    if args.json:
        print(to_json(report))
    else:
        _print_human(report, outcomes)

    if args.html:
        Path(args.html).write_text(to_html(report), encoding="utf-8")

    return 0 if report["overall"] == "pass" else 1


def cmd_version(_args: argparse.Namespace) -> int:
    print(f"fathm L1 gate (ap-gate) {__version__}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ap-gate",
        description="fathm L1 gate - Analysis Package structural validator",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="Validate an Analysis Package directory")
    p_check.add_argument("path", help="Path to the package directory")
    p_check.add_argument("--json", action="store_true", help="Print the full layered JSON report to stdout")
    p_check.add_argument("--html", metavar="PATH", help="Write a self-contained HTML report to PATH")
    p_check.set_defaults(func=cmd_check)

    p_version = sub.add_parser("version", help="Print ap-gate version")
    p_version.set_defaults(func=cmd_version)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:  # unexpected internal error -> usage/IO bucket
        print(f"ap-gate: internal error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
