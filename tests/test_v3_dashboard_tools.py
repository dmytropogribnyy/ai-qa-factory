"""v3.0.0 Milestone 4 (partial) — dashboard Tool Readiness page (deterministic, localhost only)."""
from __future__ import annotations

import json
import urllib.request

from core.scout.comms.demo import run_radar_demo
from core.scout.dashboard import start_dashboard
from core.scout.service import ScoutService


def test_dashboard_serves_tool_readiness(tmp_path):
    summary = run_radar_demo(str(tmp_path))          # produce an attachable local run
    service = ScoutService(str(tmp_path))
    service.attach(summary["campaign_id"])
    server, url = start_dashboard(service)
    try:
        with urllib.request.urlopen(url + "/api/tools", timeout=5) as r:
            data = json.loads(r.read())
        assert data["any_live_accepted"] is False and data["tool_count"] > 0
        ids = [t["id"] for t in data["tools"]]
        assert "playwright_internal" in ids and "gmail_personal" in ids
        with urllib.request.urlopen(url + "/tools", timeout=5) as r:
            html = r.read().decode("utf-8")
        assert "tool readiness" in html.lower() and "declared" in html
        # No secret value is ever rendered.
        assert "client_secret" not in html.lower()
    finally:
        server.shutdown()
