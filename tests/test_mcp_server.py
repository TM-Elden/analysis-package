"""fathm-ap MCP server transport: initialize/tools-list/tools-call over the JSON-RPC message
shape a real MCP client sends, and the server-side rejection of a call missing a required field."""

from __future__ import annotations

import json

from ap_mcp.server import PROTOCOL_VERSION, handle_request
from ap_mcp.tools import package_create


def test_initialize():
    resp = handle_request({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert resp["result"]["protocolVersion"] == PROTOCOL_VERSION
    assert resp["result"]["serverInfo"]["name"] == "fathm-ap"


def test_notification_gets_no_response():
    assert handle_request({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_tools_list_advertises_override_record_with_draft_reason_text_required():
    resp = handle_request({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    tools = {t["name"]: t for t in resp["result"]["tools"]}
    assert "override_record" in tools
    assert "draft_reason_text" in tools["override_record"]["inputSchema"]["required"]


def test_tools_call_missing_draft_reason_text_is_rejected_by_the_server(tmp_path):
    pkg_dir = package_create(dest_dir=str(tmp_path / "pkg"), title="Test pack", analyst_id="tom.analyst")
    overrides_path = pkg_dir / "labels" / "overrides.jsonl"
    before_lines = overrides_path.read_text(encoding="utf-8").splitlines()

    request = {
        "jsonrpc": "2.0",
        "id": 3,
        "method": "tools/call",
        "params": {
            "name": "override_record",
            "arguments": {
                "package_dir": str(pkg_dir),
                "field_path": "supplier_forecast.ACME.BBU-100.week_36_qty",
                "before": 1200,
                "after": 900,
                "reason_code": "HOLD_FOR_PRICE_NEGOTIATION",
                # draft_reason_text deliberately omitted - a real client can send this
            },
        },
    }

    resp = handle_request(request)

    assert resp["id"] == 3
    assert resp["result"]["isError"] is True
    text = resp["result"]["content"][0]["text"]
    assert "draft_reason_text" in text
    assert "override_record" in text

    # a rejected call appends no row
    after_lines = overrides_path.read_text(encoding="utf-8").splitlines()
    assert after_lines == before_lines


def test_tools_call_complete_override_record_round_trips_through_the_server(tmp_path):
    pkg_dir = package_create(dest_dir=str(tmp_path / "pkg"), title="Test pack", analyst_id="tom.analyst")

    request = {
        "jsonrpc": "2.0",
        "id": 4,
        "method": "tools/call",
        "params": {
            "name": "override_record",
            "arguments": {
                "package_dir": str(pkg_dir),
                "field_path": "supplier_forecast.ACME.BBU-100.week_36_qty",
                "before": 1200,
                "after": 900,
                "reason_code": "HOLD_FOR_PRICE_NEGOTIATION",
                "draft_reason_text": "Draft: hold ~300u off ACME pending price talks",
            },
        },
    }

    resp = handle_request(request)

    assert resp["result"]["isError"] is False
    row = json.loads(resp["result"]["content"][0]["text"])
    assert row["agent_draft"]["reason_text"] == "Draft: hold ~300u off ACME pending price talks"

    overrides_path = pkg_dir / "labels" / "overrides.jsonl"
    lines = [line for line in overrides_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert json.loads(lines[-1])["override_id"] == row["override_id"]


def test_unknown_method_returns_json_rpc_error():
    resp = handle_request({"jsonrpc": "2.0", "id": 5, "method": "not/a/method", "params": {}})
    assert resp["error"]["code"] == -32601
