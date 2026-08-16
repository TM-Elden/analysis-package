"""C8 agent runtime contract slice: package.create, package.check, package.publish.

`package.check` is a thin wrapper over the exact functions `ap-gate check` uses
(`ap_gate.checks.registry.run_all` + `ap_gate.report.model.build_report`) - there is no second,
parallel implementation of gate logic here (design doc C8 requirement: "Call the same gate before
claiming final/published").

`package.publish` is implemented against `ap_store.PackageStore` (the phase-2 store), not stubbed -
publish semantics are ready, per the brief's "include it if the store's publish semantics are ready"
call.

Tool schemas are kept intentionally small and flat (name, description, input_schema) rather than
adopting any one agent harness's exact tool-definition dialect (OpenAI functions / Claude tool_use /
MCP all differ in envelope, not in the (name, description, JSON-schema-input) core) - a harness
integration adapts TOOL_SCHEMAS to its own envelope, it does not need a second source of truth for
what the tools accept.
"""

from __future__ import annotations

import datetime as dt
import shutil
import uuid
from pathlib import Path
from typing import Any

import yaml

from ap_auth.identity import Identity
from ap_gate.checks.context import CheckContext
from ap_gate.checks.registry import ALL_CHECK_IDS, run_all
from ap_gate.load_manifest import load_manifest
from ap_gate.report.model import build_report
from ap_store.models import PackageRecord
from ap_store.store import PackageStore

TEMPLATES_ROOT = Path(__file__).resolve().parent / "templates"

TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "package.create": {
        "description": (
            "Create a new Analysis Package directory from a profile template and write its "
            "MANIFEST.yaml with a fresh identity. Does not run the gate or publish - call "
            "package.check next, then package.publish."
        ),
        "input_schema": {
            "type": "object",
            "required": ["dest_dir", "title", "analyst_id"],
            "properties": {
                "dest_dir": {"type": "string", "description": "Filesystem path to create the package at; must not already exist"},
                "title": {"type": "string"},
                "analyst_id": {"type": "string", "description": "owners.analyst.id for the new package"},
                "profile": {"type": "string", "default": "commodity_commit_forecast/0.1"},
                "as_of": {"type": "string", "description": "ISO-8601; defaults to now"},
                "template": {"type": "string", "default": "commodity_commit_forecast", "description": "Template name under ap_agent_tools/templates/"},
            },
        },
    },
    "package.check": {
        "description": (
            "Run the ap-gate L1 structural gate against a package directory - the exact library "
            "logic `ap-gate check` uses, no parallel implementation. Returns the layered gate "
            "report ({overall, results[], evidence[]})."
        ),
        "input_schema": {
            "type": "object",
            "required": ["package_dir"],
            "properties": {"package_dir": {"type": "string"}},
        },
    },
    "package.publish": {
        "description": (
            "Publish a package directory to the package store as an immutable package_version. "
            "Does not require the gate to pass - gate status is recorded on the store record, not "
            "enforced at publish time (enforcement is ap_review's gate-before-review policy, "
            "evaluated at the draft -> in_review transition)."
        ),
        "input_schema": {
            "type": "object",
            "required": ["package_dir", "store_root", "actor_id", "actor_roles"],
            "properties": {
                "package_dir": {"type": "string"},
                "store_root": {"type": "string", "description": "PackageStore root directory"},
                "actor_id": {"type": "string"},
                "actor_roles": {"type": "string", "description": "comma-separated role names, e.g. 'analyst'"},
            },
        },
    },
}


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def package_create(
    dest_dir: Path | str,
    *,
    title: str,
    analyst_id: str,
    profile: str = "commodity_commit_forecast/0.1",
    as_of: str | None = None,
    template: str = "commodity_commit_forecast",
) -> Path:
    """Scaffold a new package directory from `template`, with a fresh package_id and manifest.

    Copies the template tree verbatim (inputs/, code/, labels/, outputs/, qa/, GUIDELINE.md - their
    content_sha256-pinned bytes are unchanged, so they stay valid) and rewrites only the
    identity/ownership/QA fields in MANIFEST.yaml.
    """
    dest_dir = Path(dest_dir)
    if dest_dir.exists():
        raise FileExistsError(f"{dest_dir} already exists - package.create never overwrites")

    template_dir = TEMPLATES_ROOT / template
    if not template_dir.is_dir():
        known = sorted(p.name for p in TEMPLATES_ROOT.iterdir() if p.is_dir())
        raise FileNotFoundError(f"no template {template!r} under {TEMPLATES_ROOT} (known: {known})")

    shutil.copytree(template_dir, dest_dir)

    manifest_path = dest_dir / "MANIFEST.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))

    now = _now()
    manifest["package_id"] = f"pkg_{uuid.uuid4().hex}"
    manifest["package_version"] = "1.0.0"
    manifest["profile"] = profile
    manifest["title"] = title
    manifest["created_at"] = now
    manifest["as_of"] = as_of or now
    manifest["owners"] = {
        "analyst": {"id": analyst_id, "role": "commodity_planner"},
        "reviewer": None,
        "agent": {"id": "ap-agent-tools", "harness": "ap_agent_tools", "model": "n/a"},
    }
    manifest["qa"] = {"status": "draft"}
    manifest["change_log"] = [{"version": "1.0.0", "note": f"Created by package.create from template {template!r}"}]
    manifest.pop("related_packages", None)

    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")
    return dest_dir


def package_check(package_dir: Path | str) -> dict[str, Any]:
    """Run the exact ap-gate library logic `ap-gate check` uses; return the layered JSON report."""
    package_dir = Path(package_dir)
    manifest = load_manifest(package_dir)
    ctx = CheckContext(package_path=package_dir, manifest=manifest)
    outcomes = run_all(ctx)
    assert {o.check_id for o in outcomes} == set(ALL_CHECK_IDS), "gate did not run every registered check"
    return build_report(
        package_id=str(manifest.get("package_id", "(unknown)")),
        title=str(manifest.get("title", "")),
        as_of=str(manifest.get("as_of", "")),
        qa_status=str((manifest.get("qa") or {}).get("status", "")),
        profile=str(manifest.get("profile", "")),
        outcomes=outcomes,
    )


def package_publish(package_dir: Path | str, *, store_root: Path | str, actor: Identity) -> PackageRecord:
    """Publish package_dir into the PackageStore rooted at store_root."""
    with PackageStore(store_root) as store:
        return store.publish(package_dir, actor=actor)
