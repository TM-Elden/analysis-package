"""C14 redaction pipeline: person-identifier scrub, secret fail-closed, business content preserved."""

from __future__ import annotations

import shutil

from ap_gate.load_manifest import load_manifest
from ap_redact.field_paths import DEFAULT_SCRUB_FIELD_PATHS, resolve_scrub_set
from ap_redact.redact import redact_package
from ap_redact.report import read_report, write_report

from conftest import EXAMPLE_PACKAGE


def _copy_example(tmp_path, name: str = "pkg"):
    dest = tmp_path / name
    shutil.copytree(EXAMPLE_PACKAGE, dest)
    return dest


def test_person_identifiers_scrubbed_from_every_chunk(tmp_path):
    pkg_dir = _copy_example(tmp_path)
    manifest = load_manifest(pkg_dir)
    chunks, report = redact_package(
        pkg_dir, manifest, package_id=manifest["package_id"], package_version=manifest["package_version"]
    )

    assert not report.blocked
    assert chunks, "expected chunks for a clean package"
    blob = "\n".join(c.text for c in chunks)

    # owners.analyst.id / owners.reviewer.id / owners.agent.* and every label row's author
    assert manifest["owners"]["analyst"]["id"] not in blob
    assert manifest["owners"]["reviewer"]["id"] not in blob
    assert manifest["owners"]["agent"]["id"] not in blob
    assert "author" not in blob

    assert set(report.redacted_field_paths) == resolve_scrub_set(None) == DEFAULT_SCRUB_FIELD_PATHS


def test_business_content_is_not_redacted(tmp_path):
    pkg_dir = _copy_example(tmp_path)
    manifest = load_manifest(pkg_dir)
    chunks, report = redact_package(
        pkg_dir, manifest, package_id=manifest["package_id"], package_version=manifest["package_version"]
    )
    assert not report.blocked
    blob = "\n".join(c.text for c in chunks)

    # Supplier names, part numbers, quantities, contract refs - explicitly not redacted (13e / 5.4).
    assert "ACME" in blob
    assert "BBU-100" in blob
    assert "HOLD_FOR_PRICE_NEGOTIATION" in blob
    assert "contracts://supplier-ACME" in blob


def test_confidentiality_carried_as_chunk_metadata_not_removed(tmp_path):
    pkg_dir = _copy_example(tmp_path)
    manifest = load_manifest(pkg_dir)
    chunks, report = redact_package(
        pkg_dir, manifest, package_id=manifest["package_id"], package_version=manifest["package_version"]
    )
    assert not report.blocked
    assert manifest["confidentiality"] == "internal_restricted"
    assert all(c.confidentiality == "internal_restricted" for c in chunks)
    # It's metadata, not a content edit - the raw value still shows up in the manifest summary chunk.
    summary = next(c for c in chunks if c.chunk_type == "manifest_summary")
    assert "internal_restricted" in summary.text


def test_secret_salted_package_fails_closed_and_is_not_indexed(tmp_path):
    pkg_dir = _copy_example(tmp_path)
    # Salt fake secrets into the package's real risk surface (13e / 5.4: code/, input CSVs, reason_text).
    (pkg_dir / "code" / "leaked_creds.py").write_text(
        "AWS_KEY = 'AKIAABCDEFGHIJKLMNOP'\n"
        "GITHUB_TOKEN = 'ghp_abcdefghijklmnopqrstuvwxyz0123456789AB'\n",
        encoding="utf-8",
    )
    manifest = load_manifest(pkg_dir)
    package_id, package_version = manifest["package_id"], manifest["package_version"]

    chunks, report = redact_package(pkg_dir, manifest, package_id=package_id, package_version=package_version)

    assert report.blocked is True
    assert report.chunk_count == 0
    assert chunks == []
    assert report.secret_findings
    detectors = {f["detector"] for f in report.secret_findings}
    assert "aws_access_key_id" in detectors
    assert "github_token" in detectors
    for finding in report.secret_findings:
        # The report records a masked preview, never the raw secret.
        assert "AKIAABCDEFGHIJKLMNOP" not in finding["snippet"]
        assert "ghp_abcdefghijklmnopqrstuvwxyz0123456789AB" not in finding["snippet"]


def test_authorized_human_can_still_read_raw_package_from_store(tmp_path):
    """13e's acceptance bar: the raw, unredacted package stays readable from the store directly -
    redaction only ever affects what ap_index sees, never store content."""
    from ap_auth.identity import Identity
    from ap_auth.roles import Role
    from ap_store.store import PackageStore

    pkg_dir = _copy_example(tmp_path)
    (pkg_dir / "code" / "leaked_creds.py").write_text("AWS_KEY = 'AKIAABCDEFGHIJKLMNOP'\n", encoding="utf-8")
    manifest = load_manifest(pkg_dir)

    store = PackageStore(tmp_path / "store")
    actor = Identity(id=manifest["owners"]["analyst"]["id"], roles=frozenset({Role.ANALYST}))
    record = store.publish(pkg_dir, actor=actor)

    extracted = store.extract(record.package_id, record.package_version, tmp_path / "raw")
    raw_text = (extracted / "code" / "leaked_creds.py").read_text(encoding="utf-8")
    assert "AKIAABCDEFGHIJKLMNOP" in raw_text  # still there for an authorized human, unredacted
    store.close()


def test_mention_scrub_is_word_boundary_not_substring(tmp_path):
    """A free-text token that merely *contains* the analyst id as a substring (e.g. a longer
    system/model name) is business content and must survive verbatim - only a whole-word mention
    of the id is a person-identifier mention. A naive `str.replace` would mangle the longer token
    too; the word-boundary regex must not."""
    pkg_dir = _copy_example(tmp_path)
    manifest = load_manifest(pkg_dir)
    analyst_id = manifest["owners"]["analyst"]["id"]  # "planner.example"

    run_summary = pkg_dir / "outputs" / "RUN_SUMMARY.md"
    run_summary.write_text(
        run_summary.read_text(encoding="utf-8") + f"\n- **Engine build:** {analyst_id}2-forecast-engine\n",
        encoding="utf-8",
    )

    chunks, report = redact_package(
        pkg_dir, manifest, package_id=manifest["package_id"], package_version=manifest["package_version"]
    )
    assert not report.blocked
    blob = "\n".join(c.text for c in chunks)

    # The longer token that merely embeds the id as a substring is preserved untouched...
    assert f"{analyst_id}2-forecast-engine" in blob
    # ...while the standalone "**Analyst:** planner.example" mention is still redacted.
    assert "**Analyst:** [REDACTED_PERSON]" in blob


def test_redaction_report_sidecar_round_trip(tmp_path):
    pkg_dir = _copy_example(tmp_path)
    manifest = load_manifest(pkg_dir)
    _chunks, report = redact_package(
        pkg_dir, manifest, package_id=manifest["package_id"], package_version=manifest["package_version"]
    )

    store_root = tmp_path / "store"
    path = write_report(store_root, report)
    assert path.is_file()
    # Sidecar lives next to the store, never inside the package's own qa/ directory.
    assert "qa" not in path.parts
    assert path.is_relative_to(store_root)

    loaded = read_report(store_root, report.package_id, report.package_version)
    assert loaded == report


def test_no_profile_file_means_core_defaults_only():
    assert resolve_scrub_set(None) == DEFAULT_SCRUB_FIELD_PATHS


def test_profile_can_deny_extra_field_and_allow_a_default_back():
    cfg = {"deny_field_paths": ["manifest.custom.note"], "allow_field_paths": ["labels.author"]}
    scrub = resolve_scrub_set(cfg)
    assert "manifest.custom.note" in scrub
    assert "labels.author" not in scrub
    assert "manifest.owners.analyst.id" in scrub  # untouched default survives
