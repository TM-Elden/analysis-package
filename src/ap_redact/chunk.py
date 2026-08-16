"""Typed chunk extraction from a package directory - the C4 retrieval unit.

Each chunk is one of: `manifest_summary` (one per package), `override` / `judgment` / `truth`
(one per `labels/*.jsonl` row), `run_summary` (one per `##`-delimited section of
`outputs/RUN_SUMMARY.md`), or `exception` (one per row of the exception-list output). This is the
same typed-row breakdown `ap_index` tags and indexes - it lives here, not in `ap_index`, because
person-identifier scrubbing has to happen before text ever leaves this module (see `redact.py`).

Manifest-declared output paths are resolved with `ap_gate.checks.pathsafe.resolve_contained`, not a
bare `pkg / rel_path` join - see CLAUDE.md's path-containment note; a package's own manifest is
planner/agent-authored content, same trust level as anywhere else that rule applies.
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ap_gate.checks.pathsafe import resolve_contained
from ap_redact.field_paths import scrub_label_row, scrub_manifest_dict

_LABEL_FILES = {
    "override": ("overrides_path", "override_id"),
    "judgment": ("judgments_path", "judgment_id"),
    "truth": ("truths_applied_path", "rule_id"),
}

_MANIFEST_SUMMARY_FIELDS = (
    "package_id",
    "package_version",
    "title",
    "profile",
    "purpose",
    "intended_use",
    "out_of_scope",
    "confidentiality",
)


@dataclass(frozen=True)
class RawChunk:
    """Pre-render, already-scrubbed chunk content, before `redact.py` turns it into a `Chunk`."""

    chunk_type: str
    row_id: str
    field_path: str
    data: dict[str, Any]


def render_text(data: dict[str, Any]) -> str:
    """Flatten a chunk's data dict into the plain-text blob FTS5 indexes."""
    lines = []
    for key, value in data.items():
        if value in (None, "", [], {}):
            continue
        lines.append(f"{key}: {value}")
    return "\n".join(lines)


def build_manifest_summary_chunk(manifest: dict[str, Any], scrub_paths: frozenset[str]) -> RawChunk:
    scrubbed = scrub_manifest_dict(manifest, scrub_paths)
    owners = scrubbed.get("owners") or {}
    data = {field: manifest.get(field) for field in _MANIFEST_SUMMARY_FIELDS}
    # Roles are not person identifiers - keep them; ids are scrubbed via scrub_manifest_dict above.
    data["analyst_role"] = (owners.get("analyst") or {}).get("role")
    data["reviewer_role"] = (owners.get("reviewer") or {}).get("role")
    package_id = str(manifest.get("package_id", "unknown"))
    return RawChunk(chunk_type="manifest_summary", row_id=package_id, field_path="MANIFEST.yaml", data=data)


def build_label_chunks(package_dir: Path, manifest: dict[str, Any], scrub_paths: frozenset[str]) -> list[RawChunk]:
    labels = manifest.get("labels") or {}
    chunks: list[RawChunk] = []
    for chunk_type, (path_key, id_key) in _LABEL_FILES.items():
        rel_path = labels.get(path_key)
        if not isinstance(rel_path, str) or not rel_path:
            continue
        resolved = resolve_contained(package_dir, rel_path)
        if resolved is None or not resolved.is_file():
            continue
        for line_no, line in enumerate(resolved.read_text(encoding="utf-8").splitlines(), start=1):
            line = line.strip()
            if not line:
                continue
            row = json.loads(line)
            row_id = str(row.get(id_key) or f"{chunk_type}-line{line_no}")
            scrubbed = scrub_label_row(row, scrub_paths)
            chunks.append(
                RawChunk(chunk_type=chunk_type, row_id=row_id, field_path=f"{rel_path}#{row_id}", data=scrubbed)
            )
    return chunks


def build_run_summary_chunks(package_dir: Path, manifest: dict[str, Any]) -> list[RawChunk]:
    rel_path = _output_path(manifest, "run_summary")
    if rel_path is None:
        return []
    resolved = resolve_contained(package_dir, rel_path)
    if resolved is None or not resolved.is_file():
        return []
    text = resolved.read_text(encoding="utf-8")
    sections = _split_markdown_sections(text)
    return [
        RawChunk(
            chunk_type="run_summary",
            row_id=f"section-{i}",
            field_path=f"{rel_path}#{heading}",
            data={"heading": heading, "body": body},
        )
        for i, (heading, body) in enumerate(sections)
    ]


def build_exception_chunks(package_dir: Path, manifest: dict[str, Any]) -> list[RawChunk]:
    rel_path = _output_path(manifest, "exception_list")
    if rel_path is None:
        return []
    resolved = resolve_contained(package_dir, rel_path)
    if resolved is None or not resolved.is_file():
        return []
    chunks: list[RawChunk] = []
    with resolved.open(encoding="utf-8", newline="") as fh:
        for row in csv.DictReader(fh):
            row_id = str(row.get("exception_id") or row.get("id") or len(chunks))
            chunks.append(
                RawChunk(chunk_type="exception", row_id=row_id, field_path=f"{rel_path}#{row_id}", data=dict(row))
            )
    return chunks


def build_all_chunks(package_dir: Path, manifest: dict[str, Any], scrub_paths: frozenset[str]) -> list[RawChunk]:
    chunks = [build_manifest_summary_chunk(manifest, scrub_paths)]
    chunks.extend(build_label_chunks(package_dir, manifest, scrub_paths))
    chunks.extend(build_run_summary_chunks(package_dir, manifest))
    chunks.extend(build_exception_chunks(package_dir, manifest))
    return chunks


def _output_path(manifest: dict[str, Any], name: str) -> str | None:
    for entry in manifest.get("output_contract") or []:
        if isinstance(entry, dict) and entry.get("name") == name:
            path = entry.get("path")
            return path if isinstance(path, str) else None
    return None


def _split_markdown_sections(text: str) -> list[tuple[str, str]]:
    """Split on `## ` headings; anything before the first one is the "preamble" section."""
    sections: list[tuple[str, str]] = []
    heading = "preamble"
    body_lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            sections.append((heading, "\n".join(body_lines).strip()))
            heading = line.removeprefix("## ").strip()
            body_lines = []
        else:
            body_lines.append(line)
    sections.append((heading, "\n".join(body_lines).strip()))
    return [(h, b) for h, b in sections if b]


@dataclass(frozen=True)
class Chunk:
    """One indexable, already-redacted unit - `ap_index`'s only input type."""

    chunk_id: str
    package_id: str
    package_version: str
    as_of: str
    profile: str
    chunk_type: str
    field_path: str
    confidentiality: str
    text: str
