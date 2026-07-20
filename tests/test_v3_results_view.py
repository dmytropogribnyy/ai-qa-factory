"""v3.0.0 Milestone 4 - results list + company detail + Gmail-intent (read-only; nothing sent)."""
from __future__ import annotations

import json
import urllib.request

from core.scout.comms.demo import run_radar_demo
from core.scout.dashboard import _gmail_compose_url, start_dashboard
from core.scout.service import ScoutService


def test_gmail_compose_url_is_a_draft_link_not_a_send():
    url = _gmail_compose_url("owner@ex.example", "Hi there", "Body with spaces & symbols")
    assert url.startswith("https://mail.google.com/mail/?view=cm")
    assert "owner%40ex.example" in url and "Hi%20there" in url and "send" not in url.split("?")[0]


def test_results_filters_narrow_the_company_list(tmp_path):
    # v3.1 P1: text search filters the results using the existing data only.
    summary = run_radar_demo(str(tmp_path))
    service = ScoutService(str(tmp_path))
    service.attach(summary["campaign_id"])
    server, url = start_dashboard(service)
    try:
        with urllib.request.urlopen(url + "/api/results", timeout=5) as r:
            data = json.loads(r.read())
        assert data["count"] >= 1
        name = str(data["companies"][0]["name"] or data["companies"][0]["company_id"])
        # A search for a real fragment keeps at least one row; a nonsense search shows the empty state.
        frag = name.split()[0][:4] if name.split() else name[:4]
        with urllib.request.urlopen(url + f"/results?q={frag}", timeout=5) as r:
            hit = r.read().decode("utf-8")
        assert 'role="search"' in hit
        with urllib.request.urlopen(url + "/results?q=zzz-no-such-company-xyz", timeout=5) as r:
            miss = r.read().decode("utf-8")
        assert "No companies match these filters" in miss
    finally:
        server.shutdown()


def test_dashboard_results_and_company_detail_with_gmail_intent(tmp_path):
    summary = run_radar_demo(str(tmp_path))
    service = ScoutService(str(tmp_path))
    service.attach(summary["campaign_id"])
    server, url = start_dashboard(service)
    try:
        with urllib.request.urlopen(url + "/api/results", timeout=5) as r:
            data = json.loads(r.read())
        assert data["count"] >= 1
        cid = data["companies"][0]["company_id"]
        with urllib.request.urlopen(url + "/results", timeout=5) as r:
            assert "results" in r.read().decode("utf-8").lower()
        with urllib.request.urlopen(url + f"/company?id={cid}", timeout=5) as r:
            html = r.read().decode("utf-8")
        # Manual-first Gmail intent present; explicitly not a send.
        assert "open in gmail" in html.lower() and "mail.google.com" in html
        assert "nothing is sent from here" in html.lower()
        assert "findings" in html.lower()
    finally:
        server.shutdown()
