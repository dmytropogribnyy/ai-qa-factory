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
import os

try:
    import mcp.types as types  # type: ignore[import-untyped,import-not-found]
    from mcp.server import Server  # type: ignore[import-untyped,import-not-found]
    from mcp.server.stdio import stdio_server  # type: ignore[import-untyped,import-not-found]

    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False

from integrations.mcp.observer_handlers import OBSERVER_HANDLERS, OBSERVER_TOOL_SCHEMAS
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


# The full tool catalog = the original planning tools + the Observer tools.
ALL_TOOL_SCHEMAS: list[dict] = _TOOL_SCHEMAS + OBSERVER_TOOL_SCHEMAS

# --- role-scoped catalog ---------------------------------------------------------------------------
# ONE server, ONE logical implementation, a role-filtered catalog — the same pattern
# integrations/mcp/review_relay_server.py already uses. This exists because the transport documented
# and operated as a read-only Observer previously published the WHOLE catalog, including
# `apply_self_healing_fixes`, whose approval flag is a caller-supplied boolean and which writes into
# spec files. Least privilege is enforced at dispatch, so it holds on every transport.
_VALID_ROLES = {"observer", "operator"}
# Fail closed. An existing launcher that sets no role — including the running tunnel — gets the
# RESTRICTED catalog, so the correction takes effect without reconfiguring anything.
_DEFAULT_ROLE = "observer"

# An explicit ALLOWLIST of genuinely non-mutating tools, not a denylist of dangerous ones. A denylist
# fails OPEN: a tool added to OBSERVER_TOOL_SCHEMAS later — a future write or active probe — would be
# exposed to the read-only role until someone remembered to deny it. Anything not named here is
# operator-only by default, so forgetting to classify a new tool is safe rather than a leak.
READ_ONLY_TOOLS = frozenset({
    # Pure health read; no filesystem or network side effect.
    "qa_factory_health",
    # Observer reads over persisted state. observer_export_ai_review_bundle is deliberately ABSENT
    # (mkdir + write_text under <output_root>/scout/_bundles).
    "observer_get_project_overview",
    "observer_get_system_readiness",       # shallow only; deep=true is gated separately below
    "observer_get_release_readiness",
    "observer_get_storage_status",
    "observer_list_campaigns",
    "observer_campaign_counts",
    "observer_get_campaign",
    "observer_get_run_progress",
    "observer_get_run_stop_reason",
    "observer_get_updates_since",
    "observer_list_targets",
    "observer_get_target",
    "observer_get_target_test_plan",
    "observer_get_target_decision_history",
    "observer_list_findings",
    "observer_get_finding",
    "observer_get_evidence_manifest",
    "observer_get_evidence_item",
    "observer_get_activity_log",
})


def server_role() -> str:
    """The active role. Anything unset or unrecognised resolves to the restricted role."""
    role = os.environ.get("AIQA_MCP_ROLE", "").strip().lower()
    return role if role in _VALID_ROLES else _DEFAULT_ROLE


def tool_schemas(role: str | None = None) -> list[dict]:
    selected = role or server_role()
    if selected == "operator":
        return list(ALL_TOOL_SCHEMAS)
    return [s for s in ALL_TOOL_SCHEMAS if s["name"] in READ_ONLY_TOOLS]


def tool_names(role: str | None = None) -> list[str]:
    return [s["name"] for s in tool_schemas(role)]


def _call_handler(name: str, arguments: dict) -> str:
    """Dispatch a tool call and return a JSON string result, enforcing the active role's catalog.

    The role gate runs BEFORE any handler, so a tool outside the active catalog cannot execute on any
    transport, and `deep` diagnostics cannot be unlocked by a caller-supplied boolean.
    """
    role = server_role()
    arguments = arguments or {}

    if name in OBSERVER_HANDLERS or name in HANDLERS:
        if name not in tool_names(role):
            return json.dumps({"status": "blocked",
                               "reason": f"tool not exposed for the '{role}' MCP role"})

    # `deep=true` launches Chromium + network probes — an active diagnostic, not a passive read.
    # Refused, never silently downgraded: a downgrade would let the caller believe a deep probe ran.
    if (name == "observer_get_system_readiness" and bool(arguments.get("deep", False))
            and role != "operator"):
        return json.dumps({"status": "blocked",
                           "reason": ("deep readiness launches a browser and network probes and "
                                      f"requires the 'operator' MCP role (active: '{role}')")})

    if name in OBSERVER_HANDLERS:
        try:
            return json.dumps(OBSERVER_HANDLERS[name](arguments), indent=2, default=str)
        except Exception as exc:                       # structured error, no traceback/secret
            return json.dumps({"status": "error", "message": f"{type(exc).__name__}"})
    if name not in HANDLERS:
        return json.dumps({"status": "error", "message": f"Unknown tool: {name}"})
    try:
        result = HANDLERS[name](arguments)  # type: ignore[operator]
        if name == "qa_factory_health" and isinstance(result, dict):
            # Advertise only what this role can actually call; the handler itself is role-agnostic.
            result = {**result, "available_modules": tool_names(role), "mcp_role": role}
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
        # Role-scoped: a caller must not even see a tool it cannot call. Resolved per request, so the
        # advertised catalog can never drift from what _call_handler will accept.
        return [
            types.Tool(
                name=t["name"],
                description=t["description"],
                inputSchema=t["inputSchema"],
            )
            for t in tool_schemas()
        ]

    @server.call_tool()
    async def call_tool(
        name: str, arguments: dict
    ) -> list[types.TextContent]:
        result_json = _call_handler(name, arguments or {})
        return [types.TextContent(type="text", text=result_json)]

    return server


def build_http_app(token: str):
    """Build a Starlette ASGI app serving the SAME MCP tools over authenticated streamable-HTTP.

    Reuses build_server() — ONE logical tool implementation regardless of transport (no second
    Observer/server). Every request must present `Authorization: Bearer <token>`; anything else gets
    a 401. This is the transport a remote client (e.g. ChatGPT via a tunnel) uses; the Observer tools
    remain read-only, redacted, and path-confined exactly as over stdio.
    """
    import contextlib

    from mcp.server.streamable_http_manager import (  # type: ignore[import-untyped,import-not-found]
        StreamableHTTPSessionManager,
    )
    from starlette.applications import Starlette
    from starlette.routing import Mount

    server = build_server()
    manager = StreamableHTTPSessionManager(app=server, json_response=False, stateless=False)

    async def _mcp_asgi(scope, receive, send):
        await manager.handle_request(scope, receive, send)

    async def _guarded(scope, receive, send):
        if scope.get("type") == "http":
            headers = {k.decode().lower(): v.decode() for k, v in (scope.get("headers") or [])}
            if not token or headers.get("authorization", "") != f"Bearer {token}":
                await send({"type": "http.response.start", "status": 401,
                            "headers": [(b"content-type", b"application/json")]})
                await send({"type": "http.response.body", "body": b'{"error":"unauthorized"}'})
                return
        await _mcp_asgi(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan(_app):
        async with manager.run():
            yield

    return Starlette(routes=[Mount("/mcp", app=_guarded)], lifespan=lifespan)


def run_http_server(host: str = "127.0.0.1", port: int = 8765, token: str = "") -> None:
    """Serve the Observer MCP over authenticated streamable-HTTP (loopback by default).

    Refuses to start without a bearer token, so there is never an open/unauthenticated endpoint.
    Binding stays on 127.0.0.1 unless the operator explicitly passes a host; a public URL is the
    operator's tunnel step, never done automatically here.
    """
    import os

    import uvicorn

    token = token or os.environ.get("AIQA_MCP_TOKEN", "")
    if not token:
        raise RuntimeError(
            "AIQA_MCP_TOKEN is required to start the HTTP MCP server (refusing an open endpoint)")
    app = build_http_app(token)
    uvicorn.run(app, host=host, port=port, log_level="warning")


async def run_server() -> None:
    """Start the MCP server over stdio. Requires mcp package."""
    server = build_server()
    from mcp.server import NotificationOptions  # type: ignore[import-untyped,import-not-found]
    from mcp.server.models import InitializationOptions  # type: ignore[import-untyped,import-not-found]

    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            InitializationOptions(
                server_name=_SERVER_NAME,
                server_version=_SERVER_VERSION,
                # Current mcp requires a NotificationOptions instance (not None), else
                # get_capabilities() raises AttributeError and the server never starts over stdio.
                capabilities=server.get_capabilities(
                    notification_options=NotificationOptions(),
                    experimental_capabilities={},
                ),
            ),
        )
