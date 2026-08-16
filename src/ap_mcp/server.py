"""fathm-ap MCP server: JSON-RPC 2.0 over newline-delimited stdio (the MCP stdio transport), stdlib
only - no `mcp` SDK dependency, so it runs in environments (like this repo's dev sandbox) that
can't `pip install` it. `handle_request` is the pure, directly-testable core; `main()` just wires
it to stdin/stdout.

Implements the three methods a stdio MCP client needs for tool use: `initialize`, `tools/list`,
`tools/call`. Tool call arguments are validated against the exact schema object advertised in
`tools/list` (`ap_mcp.tools.TOOL_SCHEMAS`) - see `ap_mcp.errors.validate_arguments` - so server-side
enforcement cannot drift from the advertised schema (design report §3.2, §6: this exact drift is a
documented MCP ecosystem bug class).
"""

from __future__ import annotations

import json
import sys
from typing import Any

from ap_mcp.errors import ToolValidationError
from ap_mcp.tools import TOOL_SCHEMAS, override_record, package_check, package_create, package_finalize

SERVER_NAME = "fathm-ap"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2025-06-18"

_IMPLEMENTATIONS = {
    "package_create": package_create,
    "package_check": package_check,
    "package_finalize": package_finalize,
    "override_record": override_record,
}


def _tools_list_payload() -> list[dict[str, Any]]:
    return [
        {"name": name, "description": schema["description"], "inputSchema": schema["input_schema"]}
        for name, schema in TOOL_SCHEMAS.items()
    ]


def _call_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    impl = _IMPLEMENTATIONS.get(name)
    if impl is None:
        return {
            "content": [{"type": "text", "text": f"unknown tool {name!r} - known tools: {sorted(_IMPLEMENTATIONS)}"}],
            "isError": True,
        }
    try:
        result = impl(**arguments)
    except ToolValidationError as exc:
        return {"content": [{"type": "text", "text": str(exc)}], "isError": True}
    except (FileNotFoundError, FileExistsError, ValueError) as exc:
        return {"content": [{"type": "text", "text": f"{name}: {exc}"}], "isError": True}

    text = result if isinstance(result, str) else json.dumps(result, default=str, indent=2)
    return {"content": [{"type": "text", "text": text}], "isError": False}


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    """Handle one parsed JSON-RPC request/notification; return the response dict, or None for a
    notification (no `id`) which gets no reply per JSON-RPC 2.0."""
    method = message.get("method")
    msg_id = message.get("id")
    params = message.get("params") or {}

    if method == "initialize":
        result = {
            "protocolVersion": PROTOCOL_VERSION,
            "capabilities": {"tools": {}},
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
        }
    elif method == "tools/list":
        result = {"tools": _tools_list_payload()}
    elif method == "tools/call":
        result = _call_tool(params.get("name", ""), params.get("arguments") or {})
    elif method == "notifications/initialized":
        return None
    else:
        if msg_id is None:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"method not found: {method}"}}

    if msg_id is None:
        return None
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def main() -> int:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}) + "\n")
            sys.stdout.flush()
            continue
        response = handle_request(message)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
