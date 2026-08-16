"""C8 agent runtime contract slice: package.create / package.check / package.publish, and the
reference agent script producing a real package that passes the gate end to end."""

from __future__ import annotations

import pytest

from ap_agent_tools.reference_agent import run
from ap_agent_tools.tools import TOOL_SCHEMAS, package_check, package_create, package_publish
from ap_auth.identity import Identity
from ap_auth.roles import Role
from ap_gate.checks.registry import ALL_CHECK_IDS


def test_tool_schemas_cover_the_c8_minimum():
    assert {"package.create", "package.check", "package.publish"} <= TOOL_SCHEMAS.keys()
    for name, schema in TOOL_SCHEMAS.items():
        assert schema["description"]
        assert schema["input_schema"]["type"] == "object"


def test_package_create_check_publish_round_trip(tmp_path):
    pkg_dir = package_create(tmp_path / "pkg", title="Tool test pack", analyst_id="tom.analyst")
    assert (pkg_dir / "MANIFEST.yaml").is_file()

    report = package_check(pkg_dir)
    assert report["overall"] == "pass"
    assert {r["check_id"] for r in report["results"]} == set(ALL_CHECK_IDS)

    record = package_publish(
        pkg_dir, store_root=tmp_path / "store", actor=Identity(id="tom.analyst", roles=frozenset({Role.ANALYST}))
    )
    assert record.status == "draft"
    assert record.gate_overall == "pass"


def test_package_create_refuses_to_overwrite(tmp_path):
    package_create(tmp_path / "pkg", title="First", analyst_id="tom.analyst")
    with pytest.raises(FileExistsError):
        package_create(tmp_path / "pkg", title="Second", analyst_id="tom.analyst")


def test_reference_agent_produces_a_real_passing_published_package(tmp_path):
    result = run(tmp_path / "agent-pack", store_root=tmp_path / "store")

    assert result.gate_report["overall"] == "pass"
    failing = [r for r in result.gate_report["results"] if r["result"] == "fail" and not r["waived"]]
    assert not failing

    assert result.published is not None
    assert result.published.gate_overall == "pass"
    assert (result.package_dir / "MANIFEST.yaml").is_file()

    # package.check on the created directory is the exact same library call ap-gate check uses
    rechecked = package_check(result.package_dir)
    assert rechecked["overall"] == "pass"
