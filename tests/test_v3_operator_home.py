"""v3.0.0 Milestone 6 — idle HOME dashboard (start the app before any campaign; no scan)."""
from __future__ import annotations

import json
import urllib.request

from core.scout.dashboard import start_dashboard
from core.scout.service import ScoutService


def test_idle_home_dashboard_serves_without_a_run(tmp_path):
    service = ScoutService(str(tmp_path))            # no run started, no attach, no scan
    server, url = start_dashboard(service)
    try:
        with urllib.request.urlopen(url + "/health", timeout=5) as r:
            assert json.loads(r.read())["status"] == "ok"
        with urllib.request.urlopen(url + "/", timeout=5) as r:
            assert "scout" in r.read().decode("utf-8").lower()
        with urllib.request.urlopen(url + "/tools", timeout=5) as r:
            assert "tool readiness" in r.read().decode("utf-8").lower()
    finally:
        server.shutdown()
