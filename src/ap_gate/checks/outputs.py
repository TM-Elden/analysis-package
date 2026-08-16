"""output_contract_files - every output_contract entry has a non-empty artifact on disk."""

from __future__ import annotations

from ap_gate.checks.context import CheckContext
from ap_gate.checks.types import CheckOutcome

CHECK_ID = "output_contract_files"


def check_output_contract_files(ctx: CheckContext) -> CheckOutcome:
    pkg = ctx.package_path
    contract = ctx.manifest.get("output_contract") or []
    problems: list[str] = []
    paths: list[str] = []
    ok_count = 0

    for i, item in enumerate(contract):
        if not isinstance(item, dict):
            problems.append(f"output_contract[{i}] is not an object")
            continue
        label = item.get("name") or f"output_contract[{i}]"
        rel_path = item.get("path")
        if not rel_path:
            problems.append(f"{label}: output_contract entry has no path - add output_contract[{i}].path")
            continue
        full_path = pkg / rel_path
        if not full_path.is_file():
            problems.append(
                f"{label}: declared output '{rel_path}' does not exist - generate it, "
                f"or remove this output_contract entry if '{label}' isn't produced yet"
            )
            paths.append(rel_path)
        elif full_path.stat().st_size == 0:
            problems.append(f"{label}: declared output '{rel_path}' exists but is empty (0 bytes)")
            paths.append(rel_path)
        else:
            ok_count += 1

    if problems:
        return CheckOutcome.fail(
            CHECK_ID,
            "Output contract problems:\n" + "\n".join(f"  - {p}" for p in problems),
            paths=paths,
        )
    return CheckOutcome.ok(CHECK_ID, f"{ok_count}/{len(contract)} output_contract files present and non-empty")
