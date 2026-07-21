"""Role-separated MCP server for the AI QA Factory review relay."""
from __future__ import annotations

import json
import os
from typing import Any, Callable, Dict, List

try:
    import mcp.types as types  # type: ignore[import-untyped,import-not-found]
    from mcp.server import Server  # type: ignore[import-untyped,import-not-found]
    from mcp.server.stdio import stdio_server  # type: ignore[import-untyped,import-not-found]
    _MCP_AVAILABLE = True
except ImportError:
    _MCP_AVAILABLE = False

from core.review_relay import ReviewRelay, ReviewRelayError

_SERVER_NAME = "ai-qa-review-relay"
_SERVER_VERSION = "1.0.0"
_VALID_ROLES = {"worker", "reviewer", "both"}


def relay_role() -> str:
    role = os.environ.get("AIQA_REVIEW_RELAY_ROLE", "").strip().lower()
    if role not in _VALID_ROLES:
        raise RuntimeError("AIQA_REVIEW_RELAY_ROLE must be worker, reviewer, or both")
    return role


def _relay() -> ReviewRelay:
    return ReviewRelay(os.environ.get("AIQA_OUTPUT_ROOT", "outputs"))


def _int(args: Dict[str, Any], key: str, default: int) -> int:
    try:
        return int(args.get(key, default))
    except (TypeError, ValueError):
        return default


def _worker(args: Dict[str, Any], fn: Callable[[ReviewRelay, Dict[str, Any]], Any]) -> Any:
    if relay_role() not in {"worker", "both"}:
        return {"status": "blocked", "reason": "worker role required"}
    return fn(_relay(), args)


def _reviewer(args: Dict[str, Any], fn: Callable[[ReviewRelay, Dict[str, Any]], Any]) -> Any:
    if relay_role() not in {"reviewer", "both"}:
        return {"status": "blocked", "reason": "reviewer role required"}
    return fn(_relay(), args)


def _both(args: Dict[str, Any], fn: Callable[[ReviewRelay, Dict[str, Any]], Any]) -> Any:
    return fn(_relay(), args)


HANDLERS: Dict[str, Callable[[Dict[str, Any]], Any]] = {
    "relay_submit_checkpoint": lambda a: _worker(a, lambda r, x: r.submit_checkpoint(
        slice_name=str(x.get("slice_name", "")), branch=str(x.get("branch", "")),
        head_sha=str(x.get("head_sha", "")), base_sha=str(x.get("base_sha", "")),
        pr_number=x.get("pr_number"), summary=str(x.get("summary", "")),
        question=str(x.get("question", "")), evidence=str(x.get("evidence", "")))),
    "relay_get_decision": lambda a: _worker(a, lambda r, x: r.get_decision(
        str(x.get("checkpoint_id", "")))),
    "relay_ack_decision": lambda a: _worker(a, lambda r, x: r.acknowledge_decision(
        checkpoint_id=str(x.get("checkpoint_id", "")), note=str(x.get("note", "")))),
    "relay_list_checkpoints": lambda a: _reviewer(a, lambda r, x: r.list_checkpoints(
        status=str(x.get("status", "pending")), limit=_int(x, "limit", 20))),
    "relay_get_checkpoint": lambda a: _reviewer(a, lambda r, x: r.get_checkpoint(
        str(x.get("checkpoint_id", "")))),
    "relay_post_decision": lambda a: _reviewer(a, lambda r, x: r.post_decision(
        checkpoint_id=str(x.get("checkpoint_id", "")), decision=str(x.get("decision", "")),
        reviewed_sha=str(x.get("reviewed_sha", "")), message=str(x.get("message", "")),
        reviewer=str(x.get("reviewer", "gpt-reviewer")))),
    "relay_get_status": lambda a: _both(a, lambda r, x: {**r.status(), "role": relay_role()}),
}


def _schema(name: str, description: str, properties: Dict[str, Any], required=None,
            roles: tuple[str, ...] = ("worker", "reviewer", "both")) -> Dict[str, Any]:
    return {"name": name, "description": description,
            "inputSchema": {"type": "object", "properties": properties,
                            "required": required or []}, "roles": roles}


_ALL_SCHEMAS: List[Dict[str, Any]] = [
    _schema("relay_submit_checkpoint",
            "Worker-only: submit a bounded, redacted slice checkpoint for independent review. No merge or execution occurs.",
            {"slice_name": {"type": "string"}, "branch": {"type": "string"},
             "head_sha": {"type": "string"}, "base_sha": {"type": "string"},
             "pr_number": {"type": "integer"}, "summary": {"type": "string"},
             "question": {"type": "string"}, "evidence": {"type": "string"}},
            ["slice_name", "branch", "head_sha", "summary"], ("worker", "both")),
    _schema("relay_get_decision", "Worker-only: read the independent decision for one checkpoint.",
            {"checkpoint_id": {"type": "string"}}, ["checkpoint_id"], ("worker", "both")),
    _schema("relay_ack_decision", "Worker-only: append an acknowledgement after reading a decision.",
            {"checkpoint_id": {"type": "string"}, "note": {"type": "string"}},
            ["checkpoint_id"], ("worker", "both")),
    _schema("relay_list_checkpoints", "Reviewer-only: list pending/decided/acked checkpoints.",
            {"status": {"type": "string", "enum": ["pending", "decided", "acked", "all"]},
             "limit": {"type": "integer"}}, roles=("reviewer", "both")),
    _schema("relay_get_checkpoint", "Reviewer-only: read a full checkpoint and its decision/ack state.",
            {"checkpoint_id": {"type": "string"}}, ["checkpoint_id"], ("reviewer", "both")),
    _schema("relay_post_decision",
            "Reviewer-only: post GO, NO-GO, or COMMENT bound to the reviewed head SHA. Never authorizes merge.",
            {"checkpoint_id": {"type": "string"},
             "decision": {"type": "string", "enum": ["GO", "NO-GO", "COMMENT"]},
             "reviewed_sha": {"type": "string"}, "message": {"type": "string"},
             "reviewer": {"type": "string"}},
            ["checkpoint_id", "decision", "reviewed_sha", "message"], ("reviewer", "both")),
    _schema("relay_get_status", "Read relay queue counts and safety capabilities for the current role.",
            {}, roles=("worker", "reviewer", "both")),
]


def tool_schemas(role: str | None = None) -> List[Dict[str, Any]]:
    selected = role or relay_role()
    return [{k: v for k, v in schema.items() if k != "roles"}
            for schema in _ALL_SCHEMAS if selected in schema["roles"]]


def tool_names(role: str | None = None) -> List[str]:
    return [schema["name"] for schema in tool_schemas(role)]


def call_handler(name: str, arguments: Dict[str, Any]) -> str:
    if name not in HANDLERS:
        return json.dumps({"status": "error", "message": f"Unknown tool: {name}"})
    if name not in tool_names():
        return json.dumps({"status": "blocked", "reason": "tool not exposed for this relay role"})
    try:
        result = HANDLERS[name](arguments or {})
        return json.dumps(result, indent=2, ensure_ascii=False, default=str)
    except ReviewRelayError as exc:
        return json.dumps({"status": "blocked", "reason": str(exc)})
    except Exception as exc:
        return json.dumps({"status": "error", "message": f"{type(exc).__name__}: {str(exc)[:200]}"})


def build_server() -> "Server":
    if not _MCP_AVAILABLE:
        raise ImportError("The 'mcp' package is required. Install with: pip install mcp")
    server = Server(_SERVER_NAME)

    @server.list_tools()
    async def list_tools() -> list[types.Tool]:
        return [types.Tool(name=t["name"], description=t["description"], inputSchema=t["inputSchema"])
                for t in tool_schemas()]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
        return [types.TextContent(type="text", text=call_handler(name, arguments or {}))]

    return server


def build_http_app(token: str):
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


def run_http_server(host: str = "127.0.0.1", port: int = 8775, token: str = "") -> None:
    import uvicorn
    token = token or os.environ.get("AIQA_RELAY_MCP_TOKEN", "")
    if not token:
        raise RuntimeError("AIQA_RELAY_MCP_TOKEN is required; refusing an open relay endpoint")
    uvicorn.run(build_http_app(token), host=host, port=port, log_level="warning")


async def run_server() -> None:
    server = build_server()
    from mcp.server import NotificationOptions  # type: ignore[import-untyped,import-not-found]
    from mcp.server.models import InitializationOptions  # type: ignore[import-untyped,import-not-found]
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, InitializationOptions(
            server_name=_SERVER_NAME, server_version=_SERVER_VERSION,
            capabilities=server.get_capabilities(notification_options=NotificationOptions(),
                                                 experimental_capabilities={})))
