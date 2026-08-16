"""engines_pinned - every engine has name/version/deterministic, and its path (if set) exists.

The path-existence check is a small addition to the MVP/system-doc spec of
this check (second review section 4.3): a declared engines[].path that
points nowhere previously passed the gate silently. Same spirit as
output_contract_files - cheap, structural, no domain logic required.
"""

from __future__ import annotations

from ap_gate.checks.context import CheckContext
from ap_gate.checks.types import CheckOutcome

CHECK_ID = "engines_pinned"


def check_engines_pinned(ctx: CheckContext) -> CheckOutcome:
    pkg = ctx.package_path
    engines = ctx.manifest.get("engines") or []
    problems: list[str] = []
    paths: list[str] = []

    for i, e in enumerate(engines):
        if not isinstance(e, dict):
            problems.append(f"engines[{i}] is not an object")
            continue
        label = e.get("name") or f"engines[{i}]"
        if not e.get("name"):
            problems.append(f"engines[{i}]: missing name")
        if not e.get("version"):
            problems.append(f"{label}: missing version")
        if not isinstance(e.get("deterministic"), bool):
            problems.append(f"{label}: deterministic must be true or false")
        rel_path = e.get("path")
        if rel_path:
            full_path = pkg / rel_path
            if not full_path.is_file():
                problems.append(
                    f"{label}: declared path '{rel_path}' does not exist - "
                    f"drop engines[{i}].path if this engine has no code yet, or add the file"
                )
                paths.append(rel_path)

    if problems:
        return CheckOutcome.fail(
            CHECK_ID,
            "Engine declaration problems:\n" + "\n".join(f"  - {p}" for p in problems),
            paths=paths,
        )
    return CheckOutcome.ok(CHECK_ID, f"{len(engines)} engine(s) declared with name/version/deterministic")
