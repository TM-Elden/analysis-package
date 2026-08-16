"""inputs_pinned - each input is a pinned file (hash-verified if declared) or a valid external_ref."""

from __future__ import annotations

import hashlib

from ap_gate.checks.context import CheckContext
from ap_gate.checks.types import CheckOutcome

CHECK_ID = "inputs_pinned"


def _digest(path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_inputs_pinned(ctx: CheckContext) -> CheckOutcome:
    pkg = ctx.package_path
    inputs = ctx.manifest.get("inputs") or []
    problems: list[str] = []
    paths: list[str] = []

    for i, item in enumerate(inputs):
        if not isinstance(item, dict):
            problems.append(f"inputs[{i}] is not an object")
            continue
        label = item.get("name") or f"inputs[{i}]"

        if item.get("availability") == "external_ref":
            if not item.get("external_ref"):
                problems.append(
                    f"{label}: availability is external_ref but external_ref is empty "
                    "- set external_ref to a locator, or provide a path instead"
                )
            continue

        rel_path = item.get("path")
        if not rel_path:
            problems.append(
                f"{label}: no path set and not marked availability: external_ref "
                "- add a path under inputs/, or declare availability: external_ref + external_ref"
            )
            continue

        full_path = pkg / rel_path
        if not full_path.is_file():
            problems.append(f"{label}: declared path '{rel_path}' does not exist")
            paths.append(rel_path)
            continue

        declared_hash = item.get("content_sha256")
        if declared_hash:
            declared = declared_hash.split(":", 1)[-1] if ":" in declared_hash else declared_hash
            actual = _digest(full_path)
            if declared.lower() != actual.lower():
                problems.append(
                    f"{label}: content_sha256 does not match the bytes at '{rel_path}' "
                    f"(declared {declared[:16]}..., actual {actual[:16]}...) "
                    "- recompute the hash (sha256sum) and update MANIFEST.yaml, or refresh the input snapshot"
                )
                paths.append(rel_path)

    if problems:
        return CheckOutcome.fail(
            CHECK_ID,
            "Input pinning problems:\n" + "\n".join(f"  - {p}" for p in problems),
            paths=paths,
        )
    return CheckOutcome.ok(CHECK_ID, f"{len(inputs)} input(s) pinned (path/hash or external_ref verified)")
