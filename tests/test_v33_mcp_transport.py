"""v3.3 — REAL stdio MCP transport smoke (guarded: skips when the `mcp` package is absent).

Crosses the actual transport boundary: MCP client -> stdio -> qa-factory server -> Observer handler
-> ObserverAPI. Guards the two defects found during deployment (server start + absolute-path leak).
Skipped in environments without `mcp` installed (e.g. CI that doesn't install it), so it never
reddens CI while still proving the boundary locally.
"""
from __future__ import annotations

import asyncio
import importlib.util

import pytest

# Function-level skip (NOT module-level importorskip): a module-level skip is counted during
# collection before marker deselection, which trips the browser-acceptance zero-skip gate. With a
# skipif marker, this test is simply DESELECTED by the browser job's -m filter (it has no browser
# marker) and only skips in jobs that run it without mcp installed.
pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("mcp") is None, reason="mcp package not installed")


async def _smoke(output_root: str) -> dict:
    import os
    import sys
    from pathlib import Path

    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    repo = Path(__file__).resolve().parents[1]
    env = dict(os.environ)
    env["AIQA_OUTPUT_ROOT"] = output_root
    # This test asserts the DEFAULT role. Inheriting AIQA_MCP_ROLE=operator from a developer shell or
    # a CI job would silently stop it testing that default.
    env.pop("AIQA_MCP_ROLE", None)
    env.setdefault("PYTHONPATH", str(repo))
    params = StdioServerParameters(command=sys.executable,
                                   args=[str(repo / "tools" / "run_mcp_server.py")], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = sorted(t.name for t in tools.tools)
            ov = await session.call_tool("observer_get_project_overview", {})
            storage = await session.call_tool("observer_get_storage_status", {})
            bad = await session.call_tool("observer_get_run_progress",
                                          {"campaign_id": "../../etc/passwd"})
            return {"names": names,
                    "overview": ov.content[0].text if ov.content else "",
                    "storage": storage.content[0].text if storage.content else "",
                    "bad": bad.content[0].text if bad.content else ""}


def test_stdio_transport_lists_and_calls_observer_tools(tmp_path):
    res = asyncio.run(_smoke(str(tmp_path)))
    names = res["names"]
    # The subprocess sets no AIQA_MCP_ROLE, so it resolves to the default RESTRICTED role — the same
    # situation as the live tunnel launcher. This asserts what that role may expose over a real
    # transport: 19 genuinely read-only observer tools. observer_export_ai_review_bundle is the 20th
    # and is deliberately absent because it writes files (mkdir + write_text).
    observer_tools = [n for n in names if n.startswith("observer_")]
    assert len(observer_tools) == 19
    assert "observer_export_ai_review_bundle" not in names, \
        "a file-writing tool must not be exposed to the default read-only role"
    assert "observer_campaign_counts" in names          # canonical read-model tool still present
    assert "qa_factory_health" in names
    # No planning/write tool reaches the restricted role over a real transport.
    assert not [n for n in names if n in {
        "analyze_project", "run_quality_audit", "run_flaky_test_analysis", "generate_delivery_pack",
        "propose_self_healing_fixes", "apply_self_healing_fixes"}]
    # a real tool call reflects persisted state
    assert "analyzed_sites" in res["overview"]
    # no absolute path leaked via storage status (regression guard for the path-leak fix)
    assert str(tmp_path) not in res["storage"]
    # invalid campaign id fails closed across the transport
    assert "error" in res["bad"]
    # no control/write tool exposed
    assert not [n for n in names if any(k in n for k in ("pause", "stop_campaign", "control"))]
