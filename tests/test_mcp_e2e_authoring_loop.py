"""End-to-end planner authoring loop through the real MCP dispatch entry point
(`ap_mcp.server.handle_request`), per NC.1 (`data/fathm-native-chat-readiness/report.md` §5.1/§5.2
in the firstmate repo): create -> override_record -> check -> finalize -> submit_review, driven
exactly as a real MCP client would (JSON-RPC `tools/call` messages, not direct calls into
`ap_mcp.tools`), asserting the package actually lands `in_review` in the real review queue
(`ap_store.PackageStore` / `ap_review.ReviewWorkflow`, not mocked at the workflow layer) and is
readable back via `package_status`.
"""

from __future__ import annotations

from ap_mcp.server import handle_request
from ap_store.store import PackageStore


def _call(name: str, arguments: dict, *, msg_id: int) -> dict:
    resp = handle_request(
        {"jsonrpc": "2.0", "id": msg_id, "method": "tools/call", "params": {"name": name, "arguments": arguments}}
    )
    assert resp is not None
    assert resp["id"] == msg_id
    return resp["result"]


def test_full_planner_authoring_loop_lands_package_in_review_queue(tmp_path):
    pkg_dir = str(tmp_path / "pkg")
    store_root = str(tmp_path / "store")

    create_result = _call(
        "package_create",
        {"dest_dir": pkg_dir, "title": "E2E authoring loop pack", "analyst_id": "tom.analyst"},
        msg_id=1,
    )
    assert create_result["isError"] is False

    override_result = _call(
        "override_record",
        {
            "package_dir": pkg_dir,
            "field_path": "supplier_forecast.ACME.BBU-100.week_36_qty",
            "before": 1200,
            "after": 900,
            "reason_code": "HOLD_FOR_PRICE_NEGOTIATION",
            "draft_reason_text": "Draft: hold ~300u off ACME pending price talks",
        },
        msg_id=2,
    )
    assert override_result["isError"] is False

    check_result = _call("package_check", {"package_dir": pkg_dir}, msg_id=3)
    assert check_result["isError"] is False
    assert '"overall": "pass"' in check_result["content"][0]["text"]

    finalize_result = _call(
        "package_finalize",
        {"package_dir": pkg_dir, "store_root": store_root, "actor_id": "tom.analyst", "actor_roles": "analyst"},
        msg_id=4,
    )
    assert finalize_result["isError"] is False
    assert '"status": "draft"' in finalize_result["content"][0]["text"]

    # Extract package_id/package_version to submit for review, exactly as a real client would
    # parse the tool result text (the tool contract is text content, not structured JSON-RPC data).
    import json

    finalize_payload = json.loads(finalize_result["content"][0]["text"])
    package_id = finalize_payload["package_id"]
    package_version = finalize_payload["package_version"]

    submit_result = _call(
        "package_submit_review",
        {
            "package_id": package_id,
            "package_version": package_version,
            "store_root": store_root,
            "actor_id": "tom.analyst",
            "actor_roles": "analyst",
        },
        msg_id=5,
    )
    assert submit_result["isError"] is False
    submit_payload = json.loads(submit_result["content"][0]["text"])
    assert submit_payload["status"] == "in_review"

    # Confirm via package_status, driven through the same real dispatch entry point.
    status_result = _call(
        "package_status", {"package_id": package_id, "store_root": store_root}, msg_id=6
    )
    assert status_result["isError"] is False
    status_payload = json.loads(status_result["content"][0]["text"])
    assert status_payload["status"] == "in_review"

    # And confirm directly against the real store/review queue - not mocked at the workflow layer.
    with PackageStore(store_root) as store:
        record = store.get(package_id, package_version)
        assert record is not None
        assert record.status == "in_review"
        page = store.list()
        assert any(r.package_id == package_id and r.status == "in_review" for r in page.items)


def test_package_submit_review_gate_failure_is_a_planner_serving_message_not_a_stack_trace(tmp_path):
    pkg_dir = str(tmp_path / "pkg")
    store_root = str(tmp_path / "store")

    _call("package_create", {"dest_dir": pkg_dir, "title": "Gate-failing pack", "analyst_id": "tom.analyst"}, msg_id=1)

    # Corrupt the manifest so the gate fails: reference an input file that doesn't exist.
    import yaml
    from pathlib import Path

    manifest_path = Path(pkg_dir) / "MANIFEST.yaml"
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8"))
    manifest["inputs"] = manifest.get("inputs") or []
    manifest["inputs"].append({"path": "inputs/does_not_exist.csv", "content_sha256": "0" * 64})
    manifest_path.write_text(yaml.safe_dump(manifest, sort_keys=False), encoding="utf-8")

    finalize_result = _call(
        "package_finalize",
        {"package_dir": pkg_dir, "store_root": store_root, "actor_id": "tom.analyst", "actor_roles": "analyst"},
        msg_id=2,
    )
    assert finalize_result["isError"] is False

    import json

    finalize_payload = json.loads(finalize_result["content"][0]["text"])

    submit_result = _call(
        "package_submit_review",
        {
            "package_id": finalize_payload["package_id"],
            "package_version": finalize_payload["package_version"],
            "store_root": store_root,
            "actor_id": "tom.analyst",
            "actor_roles": "analyst",
        },
        msg_id=3,
    )
    assert submit_result["isError"] is True
    text = submit_result["content"][0]["text"]
    assert "gate-before-review" in text
    assert "Traceback" not in text

    with PackageStore(store_root) as store:
        record = store.get(finalize_payload["package_id"], finalize_payload["package_version"])
        assert record.status == "draft"  # rejected submission never mutated the store record
