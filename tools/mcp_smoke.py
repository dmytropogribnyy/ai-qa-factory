#!/usr/bin/env python
"""Compatible-client MCP smoke test — crosses the REAL stdio transport boundary.

Spawns the existing qa-factory MCP server (tools/run_mcp_server.py) as a subprocess and talks to
it as a real MCP client over stdio: initialize -> tools/list -> tools/call. This is the acceptance
that direct Python handler tests cannot provide (MCP client -> stdio -> server -> Observer handler
-> ObserverAPI -> persisted source of truth). Writes a redacted acceptance report under
outputs/mcp_acceptance/. Requires: pip install mcp.

Usage:
    python tools/mcp_smoke.py [--output-root outputs]
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_ABS_PATH_RE = re.compile(r"[A-Za-z]:\\|(?:^|[\"'\s])/(?:etc|home|root|Users)/")
_SECRET_RE = re.compile(r"tvly-[A-Za-z0-9._-]+|Bearer\s+\S+", re.I)


def _leaks(obj) -> list[str]:
    """Return any secret/absolute-path leaks found in a serialized MCP result."""
    blob = json.dumps(obj, default=str)
    problems = []
    if _SECRET_RE.search(blob):
        problems.append("secret_pattern")
    if _ABS_PATH_RE.search(blob):
        problems.append("absolute_path")
    return problems


async def _run(output_root: str) -> dict:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = dict(os.environ)
    env["AIQA_OUTPUT_ROOT"] = output_root
    env.setdefault("PYTHONPATH", str(REPO))
    params = StdioServerParameters(
        command=sys.executable, args=[str(REPO / "tools" / "run_mcp_server.py")], env=env)

    report: dict = {"schema": "mcp-connection-acceptance/v1",
                    "at": datetime.now(timezone.utc).isoformat(),
                    "transport": "stdio", "output_root": output_root, "steps": [], "leaks": []}

    def step(name, ok, detail=""):
        report["steps"].append({"step": name, "ok": bool(ok), "detail": detail})

    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            step("initialize", True, "MCP session initialized over stdio")

            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            observer = [n for n in names if n.startswith("observer_")]
            step("list_tools", len(names) >= 26, f"{len(names)} tools ({len(observer)} observer)")
            report["tool_count"] = len(names)
            report["observer_tool_count"] = len(observer)

            async def call(tool, args):
                res = await session.call_tool(tool, args)
                text = res.content[0].text if res.content else "{}"
                try:
                    parsed = json.loads(text)
                except json.JSONDecodeError:
                    parsed = {"_raw": text[:200]}
                leaks = _leaks(parsed)
                report["leaks"].extend(f"{tool}:{p}" for p in leaks)
                step(f"call:{tool}", not leaks, f"keys={sorted(parsed.keys())[:6]}")
                return parsed

            await call("qa_factory_health", {})
            ov = await call("observer_get_project_overview", {})
            await call("observer_get_system_readiness", {"deep": False})
            await call("observer_get_storage_status", {})
            camps = await call("observer_list_campaigns", {"limit": 5})

            cid = None
            for c in (camps.get("campaigns") or []):
                cid = c.get("campaign_id")
                break
            if cid:
                await call("observer_get_run_progress", {"campaign_id": cid})
                await call("observer_list_targets", {"limit": 5})
                await call("observer_list_findings", {"campaign_id": cid, "limit": 5})
                await call("observer_get_evidence_manifest", {"campaign_id": cid})
            else:
                step("campaign_dependent_calls", True, "no campaign present — skipped (expected)")

            # Security: an invalid/traversal campaign id must fail closed (structured error).
            bad = await call("observer_get_run_progress", {"campaign_id": "../../etc/passwd"})
            step("invalid_campaign_id_refused", bad.get("status") == "error", str(bad)[:80])

            # Confirm NO write/control tool is exposed.
            control = [n for n in names if any(k in n for k in
                       ("pause", "resume_campaign", "stop_campaign", "control", "run_campaign",
                        "create_campaign", "delete"))]
            step("no_control_tools", not control, f"control tools: {control}")
            report["control_tools_exposed"] = control

    report["ok"] = all(s["ok"] for s in report["steps"]) and not report["leaks"]
    report["project_overview_reflects_state"] = "analyzed_sites" in ov
    return report


def _write(report: dict) -> Path:
    out = REPO / "outputs" / "mcp_acceptance"
    out.mkdir(parents=True, exist_ok=True)
    (out / "MCP_CONNECTION_ACCEPTANCE.json").write_text(
        json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    lines = [f"# MCP Connection Acceptance ({report['transport']})", "",
             f"- at: {report['at']}", f"- tools: {report.get('tool_count')} "
             f"({report.get('observer_tool_count')} observer)",
             f"- leaks: {report['leaks'] or 'none'}",
             f"- control tools exposed: {report.get('control_tools_exposed') or 'none'}",
             f"- **result: {'PASS' if report.get('ok') else 'FAIL'}**", "", "## Steps", ""]
    lines += [f"- [{'x' if s['ok'] else ' '}] {s['step']} — {s['detail']}"
              for s in report["steps"]]
    md = out / "MCP_CONNECTION_ACCEPTANCE.md"
    md.write_text("\n".join(lines), encoding="utf-8")
    return md


def main() -> int:
    ap = argparse.ArgumentParser(description="Compatible-client MCP smoke over real stdio transport")
    ap.add_argument("--output-root", default=os.environ.get("AIQA_OUTPUT_ROOT", "outputs"))
    args = ap.parse_args()
    try:
        report = asyncio.run(_run(args.output_root))
    except Exception as exc:  # honest failure, no traceback dump to callers
        print(f"[mcp-smoke] FAILED: {type(exc).__name__}: {str(exc)[:200]}")
        return 1
    path = _write(report)
    print(f"[mcp-smoke] {'PASS' if report['ok'] else 'FAIL'} — report: {path}")
    print(f"[mcp-smoke] tools={report.get('tool_count')} "
          f"observer={report.get('observer_tool_count')} leaks={report['leaks'] or 'none'}")
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
