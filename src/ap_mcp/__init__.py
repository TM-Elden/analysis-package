"""fathm-ap MCP server (C8 tool distribution + P4 agent_draft capture).

Thin layer over `ap_gate` / `ap_agent_tools` / `ap_store` - see `ap_mcp.tools` for the four tool
implementations and `ap_mcp.server` for the JSON-RPC/stdio transport. No gate logic lives here;
every tool calls the exact same library functions `ap-gate check` and `ap_agent_tools` use.
"""
