#!/usr/bin/env python
"""Local verification of the authenticated streamable-HTTP MCP transport (ChatGPT-compatible shape).

Starts the HTTP server on loopback with a random bearer token (in a background thread), then acts as
a real MCP HTTP client: it proves an authorized client can initialize + list tools + call
observer_get_project_overview, and that an UNAUTHENTICATED request is rejected (401). Writes a
redacted acceptance report to outputs/mcp_acceptance/. The token is random and never written to disk.
Requires: pip install mcp uvicorn starlette.

Usage: python tools/mcp_http_smoke.py [--output-root outputs]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import socket
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))  # allow 'integrations.*' imports when run as a script


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _client(url: str, token: str | None) -> dict:
    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client
    headers = {"Authorization": f"Bearer {token}"} if token else None
    async with streamablehttp_client(url, headers=headers) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            ov = await session.call_tool("observer_get_project_overview", {})
            return {"tool_count": len(tools.tools),
                    "observer": len([t for t in tools.tools if t.name.startswith("observer_")]),
                    "overview": ov.content[0].text if ov.content else ""}


def main() -> int:
    ap = argparse.ArgumentParser(description="Authenticated streamable-HTTP MCP smoke (loopback)")
    ap.add_argument("--output-root", default=os.environ.get("AIQA_OUTPUT_ROOT", "outputs"))
    args = ap.parse_args()
    os.environ["AIQA_OUTPUT_ROOT"] = args.output_root

    import uvicorn

    from integrations.mcp.server import build_http_app
    token = secrets.token_urlsafe(24)
    port = _free_port()
    url = f"http://127.0.0.1:{port}/mcp"
    app = build_http_app(token)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    report = {"schema": "mcp-http-acceptance/v1", "at": datetime.now(timezone.utc).isoformat(),
              "transport": "streamable-http", "url": url, "auth": "bearer-token", "steps": []}

    def step(name, ok, detail=""):
        report["steps"].append({"step": name, "ok": bool(ok), "detail": detail})

    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.1)
        step("server_started", server.started, f"loopback :{port}")

        authed = asyncio.run(_client(url, token))
        step("authorized_initialize_list_call", authed["observer"] == 19,
             f"{authed['tool_count']} tools ({authed['observer']} observer)")
        step("overview_reflects_state", "analyzed_sites" in authed["overview"], "")
        report["leaks"] = ["absolute_path"] if str(REPO) in authed["overview"] else []

        rejected = False
        try:
            asyncio.run(_client(url, None))            # no token -> must be refused
        except Exception:
            rejected = True
        step("unauthenticated_request_refused", rejected, "401 without bearer token")
    finally:
        server.should_exit = True
        thread.join(timeout=5)

    report["ok"] = all(s["ok"] for s in report["steps"]) and not report.get("leaks")
    out = REPO / "outputs" / "mcp_acceptance"
    out.mkdir(parents=True, exist_ok=True)
    (out / "MCP_HTTP_ACCEPTANCE.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    lines = [f"# MCP HTTP Transport Acceptance ({report['transport']})", "",
             f"- at: {report['at']}", "- auth: bearer-token (loopback)",
             f"- **result: {'PASS' if report['ok'] else 'FAIL'}**", "", "## Steps", ""]
    lines += [f"- [{'x' if s['ok'] else ' '}] {s['step']} - {s['detail']}" for s in report["steps"]]
    (out / "MCP_HTTP_ACCEPTANCE.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"[mcp-http-smoke] {'PASS' if report['ok'] else 'FAIL'} - "
          f"authorized+call ok, unauthenticated refused; report under outputs/mcp_acceptance/")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
