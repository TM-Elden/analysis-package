"""redact_package: the C14 pipeline entry point - `package dir -> redacted chunk stream +
redaction report`.

Business content (supplier names, part numbers, quantities, contract refs) is deliberately never
touched here - see CLAUDE.md and report section 5.4 for why; within-tenant protection for that
content is C9 tenancy + C11 role scope, not redaction. `confidentiality` is carried onto every
`Chunk` as metadata for role-based retrieval filtering, never used to remove content here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ap_gate.profiles import load_profile_redaction, profile_short_name
from ap_redact.chunk import Chunk, build_all_chunks, render_text
from ap_redact.field_paths import disabled_detectors, resolve_scrub_set
from ap_redact.report import RedactionReport
from ap_redact.secrets_scan import scan_package_tree


def _collect_identifier_values(manifest: dict[str, Any], scrub_paths: frozenset[str]) -> list[str]:
    """String values the field-path scrub decided were person identifiers, for the free-text
    mention pass below (`_scrub_mentions`)."""
    owners = manifest.get("owners") or {}
    values: list[str] = []
    if "manifest.owners.analyst.id" in scrub_paths:
        v = (owners.get("analyst") or {}).get("id")
        if isinstance(v, str) and v:
            values.append(v)
    if "manifest.owners.reviewer.id" in scrub_paths:
        v = (owners.get("reviewer") or {}).get("id")
        if isinstance(v, str) and v:
            values.append(v)
    if "manifest.owners.agent" in scrub_paths:
        for v in (owners.get("agent") or {}).values():
            if isinstance(v, str) and len(v) > 2:
                values.append(v)
    return values


def _scrub_mentions(text: str, identifier_values: list[str]) -> str:
    for value in identifier_values:
        text = text.replace(value, "[REDACTED_PERSON]")
    return text


def redact_package(
    package_dir: Path,
    manifest: dict[str, Any],
    *,
    package_id: str,
    package_version: str,
) -> tuple[list[Chunk], RedactionReport]:
    """Run the full C14 pipeline against an already-extracted package directory.

    Fail-closed: if the secret scan finds any high-severity hit, the returned chunk list is empty
    (nothing is indexable) and `RedactionReport.blocked` is True with the findings recorded for
    the console to surface later (not built in this module). Person-identifier scrubbing and
    business-content preservation both happen regardless of the secret-scan outcome - the report
    always tells the whole story, even for a blocked package.
    """
    profile_name = str(manifest.get("profile", ""))
    profile_cfg = load_profile_redaction(profile_short_name(profile_name) or "")
    scrub_paths = resolve_scrub_set(profile_cfg)
    skip_detectors = disabled_detectors(profile_cfg)

    findings = scan_package_tree(package_dir, disabled_detectors=skip_detectors)
    high_severity = [f for f in findings if f.severity == "high"]

    redacted_field_paths = tuple(sorted(scrub_paths))
    secret_findings = tuple(f.to_dict() for f in findings)

    if high_severity:
        report = RedactionReport(
            package_id=package_id,
            package_version=package_version,
            blocked=True,
            block_reason=(
                f"{len(high_severity)} high-severity secret finding(s) detected "
                f"({', '.join(sorted({f.detector for f in high_severity}))}) - package not indexed"
            ),
            redacted_field_paths=redacted_field_paths,
            secret_findings=secret_findings,
            chunk_count=0,
        )
        return [], report

    as_of = str(manifest.get("as_of", ""))
    confidentiality = str(manifest.get("confidentiality", ""))
    raw_chunks = build_all_chunks(package_dir, manifest, scrub_paths)
    # Structured field scrubbing (scrub_manifest_dict / scrub_label_row) only removes identifiers
    # from the field they live in - it can't catch the same value re-typed into free prose (e.g.
    # RUN_SUMMARY.md's "**Analyst:** planner.example"). This second pass replaces literal mentions
    # of every value the field-path scrub decided was a person identifier, wherever it resurfaces
    # in any chunk's rendered text.
    identifier_values = _collect_identifier_values(manifest, scrub_paths)
    chunks = [
        Chunk(
            chunk_id=f"{package_id}/{package_version}/{rc.chunk_type}/{rc.row_id}",
            package_id=package_id,
            package_version=package_version,
            as_of=as_of,
            profile=profile_name,
            chunk_type=rc.chunk_type,
            field_path=rc.field_path,
            confidentiality=confidentiality,
            text=_scrub_mentions(render_text(rc.data), identifier_values),
        )
        for rc in raw_chunks
    ]

    report = RedactionReport(
        package_id=package_id,
        package_version=package_version,
        blocked=False,
        block_reason=None,
        redacted_field_paths=redacted_field_paths,
        secret_findings=secret_findings,
        chunk_count=len(chunks),
    )
    return chunks, report
