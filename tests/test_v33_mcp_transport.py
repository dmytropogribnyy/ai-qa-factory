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
    # server starts (regression guard for the NotificationOptions fix) + full catalog is exposed
    # (20 read-only observer tools incl. observer_campaign_counts, added in the canonical read-model)
    assert len([n for n in names if n.startswith("observer_")]) == 20
    assert "qa_factory_health" in names
    # a real tool call reflects persisted state
    assert "analyzed_sites" in res["overview"]
    # no absolute path leaked via storage status (regression guard for the path-leak fix)
    assert str(tmp_path) not in res["storage"]
    # invalid campaign id fails closed across the transport
    assert "error" in res["bad"]
    # no control/write tool exposed
    assert not [n for n in names if any(k in n for k in ("pause", "stop_campaign", "control"))]
