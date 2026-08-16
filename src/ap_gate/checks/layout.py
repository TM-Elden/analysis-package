"""layout_dirs, guideline_exists - package directory shape (STANDARD.md on-disk layout)."""

from __future__ import annotations

from ap_gate.checks.context import CheckContext
from ap_gate.checks.types import CheckOutcome

CHECK_ID_LAYOUT_DIRS = "layout_dirs"
CHECK_ID_GUIDELINE_EXISTS = "guideline_exists"


def check_layout_dirs(ctx: CheckContext) -> CheckOutcome:
    pkg = ctx.package_path
    manifest = ctx.manifest
    missing: list[str] = []

    if not (pkg / "MANIFEST.yaml").is_file():
        missing.append("MANIFEST.yaml")

    inputs = manifest.get("inputs") or []
    all_external = all(
        isinstance(i, dict) and i.get("availability") == "external_ref" for i in inputs
    )
    if not (pkg / "inputs").is_dir() and not all_external:
        missing.append("inputs/ (required unless every input is availability: external_ref)")

    for d in ("outputs", "labels", "qa"):
        if not (pkg / d).is_dir():
            missing.append(f"{d}/")

    if missing:
        return CheckOutcome.fail(
            CHECK_ID_LAYOUT_DIRS,
            "Missing required package layout entries: " + "; ".join(missing)
            + " - create them under the package root (see STANDARD.md on-disk layout).",
            paths=missing,
        )
    return CheckOutcome.ok(CHECK_ID_LAYOUT_DIRS, "required package directories present")


def check_guideline_exists(ctx: CheckContext) -> CheckOutcome:
    pkg = ctx.package_path
    method = ctx.manifest.get("method") or {}
    guideline_path = method.get("guideline_path") if isinstance(method, dict) else None

    if guideline_path:
        candidate = pkg / guideline_path
        if candidate.is_file():
            return CheckOutcome.ok(CHECK_ID_GUIDELINE_EXISTS, f"method card found at {guideline_path}")
        return CheckOutcome.fail(
            CHECK_ID_GUIDELINE_EXISTS,
            f"method.guideline_path is set to '{guideline_path}' but that file does not exist "
            "- fix the path, or add the file.",
            paths=[guideline_path],
        )

    if (pkg / "GUIDELINE.md").is_file():
        return CheckOutcome.ok(CHECK_ID_GUIDELINE_EXISTS, "GUIDELINE.md found at package root")
    return CheckOutcome.fail(
        CHECK_ID_GUIDELINE_EXISTS,
        "No GUIDELINE.md at the package root and method.guideline_path is not set "
        "- add a GUIDELINE.md method card, or set method.guideline_path in MANIFEST.yaml.",
        paths=["GUIDELINE.md"],
    )
