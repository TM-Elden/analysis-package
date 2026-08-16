"""must_fields, standard_version, qa_status_enum, training_eligibility_present."""

from __future__ import annotations

from ap_gate.checks.context import CheckContext
from ap_gate.checks.types import CheckOutcome
from ap_gate.schema import error_field_path, load_schema_for_version, validate_manifest
from ap_gate.versions import supported_versions

CHECK_ID_MUST_FIELDS = "must_fields"
CHECK_ID_STANDARD_VERSION = "standard_version"
CHECK_ID_QA_STATUS_ENUM = "qa_status_enum"
CHECK_ID_TRAINING_ELIGIBILITY_PRESENT = "training_eligibility_present"

QA_STATUS_ENUM = ("draft", "in_review", "approved", "rejected")

_MAX_ERRORS_SHOWN = 20


def check_must_fields(ctx: CheckContext) -> CheckOutcome:
    standard_version = ctx.manifest.get("standard_version")
    schema = load_schema_for_version(standard_version) if isinstance(standard_version, str) else None
    if schema is None:
        return CheckOutcome.skip(
            CHECK_ID_MUST_FIELDS,
            "cannot validate MUST fields: standard_version is missing or unsupported "
            "- see the standard_version check for the fix.",
        )
    errors = validate_manifest(ctx.manifest, schema)
    if not errors:
        return CheckOutcome.ok(CHECK_ID_MUST_FIELDS, "MANIFEST.yaml satisfies the ap/0.2 MUST-field schema")

    shown = errors[:_MAX_ERRORS_SHOWN]
    lines = [f"MANIFEST.yaml{error_field_path(e)}: {e.message}" for e in shown]
    if len(errors) > len(shown):
        lines.append(f"... and {len(errors) - len(shown)} more field error(s)")
    return CheckOutcome.fail(
        CHECK_ID_MUST_FIELDS,
        "MANIFEST.yaml is missing or has invalid MUST fields:\n" + "\n".join(f"  - {l}" for l in lines)
        + "\n  Fix each field in MANIFEST.yaml, then re-run ap-gate.",
        paths=["MANIFEST.yaml"],
    )


def check_standard_version(ctx: CheckContext) -> CheckOutcome:
    version = ctx.manifest.get("standard_version")
    supported = supported_versions()
    if isinstance(version, str) and version in supported:
        return CheckOutcome.ok(CHECK_ID_STANDARD_VERSION, f"standard_version '{version}' is supported")
    return CheckOutcome.fail(
        CHECK_ID_STANDARD_VERSION,
        f"MANIFEST.yaml standard_version is {version!r} - supported values: {', '.join(supported)}. "
        "Set standard_version in MANIFEST.yaml to a supported value.",
        paths=["MANIFEST.yaml"],
    )


def check_qa_status_enum(ctx: CheckContext) -> CheckOutcome:
    status = (ctx.manifest.get("qa") or {}).get("status")
    if status in QA_STATUS_ENUM:
        return CheckOutcome.ok(CHECK_ID_QA_STATUS_ENUM, f"qa.status '{status}' is valid")
    return CheckOutcome.fail(
        CHECK_ID_QA_STATUS_ENUM,
        f"MANIFEST.yaml qa.status is {status!r} - must be one of {list(QA_STATUS_ENUM)}. "
        "Fix qa.status in MANIFEST.yaml.",
        paths=["MANIFEST.yaml"],
    )


def check_training_eligibility_present(ctx: CheckContext) -> CheckOutcome:
    value = ctx.manifest.get("training_eligibility")
    if isinstance(value, bool):
        return CheckOutcome.ok(CHECK_ID_TRAINING_ELIGIBILITY_PRESENT, f"training_eligibility is {value}")
    return CheckOutcome.fail(
        CHECK_ID_TRAINING_ELIGIBILITY_PRESENT,
        f"MANIFEST.yaml training_eligibility is missing or not a boolean (got {value!r}) - "
        "set training_eligibility: true or false (default should be false per policy D7 "
        "until reviewed).",
        paths=["MANIFEST.yaml"],
    )
