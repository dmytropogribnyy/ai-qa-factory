"""Phase 6 — QA Factory MCP Server.

Wraps tool_handlers.py as MCP tools. Requires: pip install mcp

Usage:
    python tools/run_mcp_server.py

Or add to your Claude Desktop / VS Code MCP config:
    {
      "mcpServers": {
        "qa-factory": {
          "command": "python",
          "args": ["tools/run_mcp_server.py"]
        }
      }
    }

Safety:
- All tools default to planning_only (no network, no browser)
- Execution requires explicit approval flags in tool arguments
- No credentials accepted or returned
"""
from __future__ import annotations

import json

try:
    import mcp.types as types
    from mcp.server import Server
    from mcp.server.stdio import stdio_server

    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False

from integrations.mcp.tool_handlers import HANDLERS, APP_VERSION

_SERVER_NAME = "qa-factory"
_SERVER_VERSION = APP_VERSION

# ---------------------------------------------------------------------------
# Tool schema definitions
# ---------------------------------------------------------------------------

_TOOL_SCHEMAS: list[dict] = [
    {
        "name": "qa_factory_health",
        "description": (
            "Return QA Factory health, version, available modules, and safety mode. "
            "No network or file access."
        ),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "analyze_project",
        "description": (
            "Classify a project outputs directory and return available modules, "
            "found artifacts, and recommended next steps."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string", "description": "Project identifier"},
                "outputs_root": {
                    "type": "string",
                    "description": "Root outputs directory (default: outputs)",
                },
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "run_quality_audit",
        "description": (
            "Run accessibility, performance, and passive security audit modules. "
            "Default: planning_only (no network). "
            "Execution requires approve_public_readonly_execution and/or approve_browser_execution."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "target_url": {"type": "string", "description": "Target URL to audit"},
                "outputs_root": {"type": "string"},
                "approve_public_readonly_execution": {
                    "type": "boolean",
                    "description": "Approve passive HEAD request for security check",
                },
                "approve_browser_execution": {
                    "type": "boolean",
                    "description": "Approve browser-based accessibility/performance checks",
                },
                "write_files": {"type": "boolean"},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "run_flaky_test_analysis",
        "description": (
            "Static analysis of Playwright spec files. "
            "Detects hard waits, fragile selectors, non-web-first assertions. "
            "Returns selector stability score and self-healing proposals. "
            "No code changes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "spec_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Playwright spec file paths (auto-discovered if omitted)",
                },
                "outputs_root": {"type": "string"},
                "write_files": {"type": "boolean"},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "generate_delivery_pack",
        "description": (
            "Generate a client delivery pack: QA report, evidence index, risk matrix, "
            "recommendations, and a ZIP archive. "
            "Secret scan always runs. approved_for_client_delivery is always False — "
            "human sign-off required."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "outputs_root": {"type": "string"},
                "write_files": {"type": "boolean"},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "propose_self_healing_fixes",
        "description": (
            "Generate self-healing proposals for weak selectors. "
            "Proposals only — no code is modified. "
            "Returns HEAL-xxx proposals with affected file and line number."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "spec_files": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "outputs_root": {"type": "string"},
                "write_files": {"type": "boolean"},
            },
            "required": ["project_id"],
        },
    },
    {
        "name": "apply_self_healing_fixes",
        "description": (
            "Apply self-healing proposals as TODO comments at affected lines. "
            "Requires approve_code_modification=true. "
            "dry_run=true by default (no file changes). "
            "Developer must implement the suggested changes."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "spec_files": {
                    "type": "array",
                    "items": {"type": "string"},
                },
                "outputs_root": {"type": "string"},
                "approve_code_modification": {
                    "type": "boolean",
                    "description": "Must be true to apply proposals",
                },
                "dry_run": {
                    "type": "boolean",
                    "description": "If true (default), shows preview without modifying files",
                },
            },
            "required": ["project_id"],
        },
    },
]


def _call_handler(name: str, arguments: dict) -> str:
    """Dispatch tool call and return JSON string result."""
    if name not in HANDLERS:
        return json.dumps({"status": "error", "message": f"Unknown tool: {name}"})
    try:
        result = HANDLERS[name](arguments)  # type: ignore[operator]
        return json.dumps(result, indent=2, default=str)
    except ValueError as exc:
        return json.dumps({"status": "blocked", "reason": str(exc)})
    except Exception as exc:
        return json.dumps({"status": "error", "message": str(exc)})


def build_server() -> "Server":
    """Build and return a configured MCP Server. Raises ImportError if mcp not installed."""
    if not _MCP_AVAILABLE:
        raise ImportError(
            "The 'mcp' package is required to run the MCP server. "
            "Install with: pip install mcp"
        )

    server = Server(_SERVER_NAME)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [
            types.Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=t["inputSchema"],
            )
            for t in _TOOL_SCHEMAS
        ]

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict
    ) -> list[types.TextContent]:
        result_json = _call_handler(name, arguments or {})
        return [types.TextContent(type="text", text=result_json)]

    return server


async def run_server() -> None:
    """Start the MCP server over stdio. Requires mcp package."""
    server = build_server()
    from mcp.server.models import InitializationOptions

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name=_SERVER_NAME,
                server_version=_SERVER_VERSION,
                capabilities=server.get_capabilities(
                    notification_options=None,
                    experimental_capabilities={},
                ),
            ),
        )
