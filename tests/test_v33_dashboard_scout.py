"""v3.3 — Dashboard adaptive-Scout routes (loopback HTTP). Pages render under CSP; mutating
endpoints are refused without CSRF; read models return the expected shape. No live calls."""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request

from core.scout.campaign_service import CampaignService
from core.scout.dashboard import start_dashboard
from core.scout.service import ScoutService


def _dash(tmp_path):
    return start_dashboard(ScoutService(str(tmp_path)), operator_home=True)


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode("utf-8"), dict(r.headers)


def _post_nocsrf(url, body):
    req = urllib.request.Request(url, method="POST", data=json.dumps(body).encode("utf-8"),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            return r.status, r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8")


def _post(url, body, csrf):
    req = urllib.request.Request(
        url,
        method="POST",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json", "X-Scout-CSRF": csrf},
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        return response.status, response.read().decode("utf-8")


def test_scout_pages_render_under_csp(tmp_path):
    server, url = _dash(tmp_path)
    try:
        for path in ["/scout/new", "/scout/history", "/scout/progress?id=none"]:
            status, body, headers = _get(url + path)
            assert status == 200 and "<main>" in body, path
            assert "default-src 'self'" in headers.get("Content-Security-Policy", ""), path
        _, newbody, _ = _get(url + "/scout/new")
        # The daily form is now one Start Scout over three sources. The campaign-preset picker and
        # the manual "Check system readiness" button it used to carry are deliberately gone —
        # readiness is a preflight Scout runs itself (see tests/test_scout_unified_start.py).
        assert "Start Scout" in newbody
        assert "Find websites" in newbody and "Paste URLs" in newbody
    finally:
        server.shutdown()


def test_scout_catalog_and_progress_read_models(tmp_path):
    server, url = _dash(tmp_path)
    try:
        _, api, _ = _get(url + "/api/scout/catalog")
        cat = json.loads(api)
        assert cat["default_campaign_preset"] == "balanced-production"
        assert any(p["key"] == "safe-live-acceptance" for p in cat["campaign_presets"])
        _, prog, _ = _get(url + "/api/scout/progress?id=does-not-exist")
        data = json.loads(prog)
        assert data["run_state"] == "queued"          # default for an unknown campaign
        assert "counters" in data
    finally:
        server.shutdown()


def test_mutating_scout_endpoints_refused_without_csrf(tmp_path):
    server, url = _dash(tmp_path)
    try:
        for path in ["/api/scout/launch", "/api/scout/preflight",
                     "/api/scout/control?id=x&action=pause", "/api/scout/export?id=x"]:
            code, _ = _post_nocsrf(url + path, {"campaign_preset": "safe-live-acceptance"})
            assert code == 403, path                  # CSRF/origin guard blocks it
    finally:
        server.shutdown()


def test_preflight_uses_the_current_campaign_form_values(tmp_path, monkeypatch):
    captured = {}

    def fake_preflight(self, **kwargs):
        captured.update(kwargs)
        return {"preflight": {"ok": True, "checks": []}}

    monkeypatch.setattr(CampaignService, "preflight", fake_preflight)
    server, url = _dash(tmp_path)
    try:
        _, html, _ = _get(url + "/scout/new")
        csrf = re.search(r'const CSRF="([^"]+)"', html).group(1)
        status, payload = _post(
            url + "/api/scout/preflight",
            {
                "campaign_preset": "us-de-commercial",
                "session_preset": "extended",
                "overrides": {
                    "countries": ["sk"],
                    "exclude_keywords": ["jobs"],
                    "max_pages_per_site": 7,
                    "browser_mode": "playwright",
                },
                "probe_browser": False,
            },
            csrf,
        )
    finally:
        server.shutdown()

    assert status == 200
    assert json.loads(payload)["ok"] is True
    assert captured["campaign_preset"] == "us-de-commercial"
    assert captured["session_preset"] == "extended"
    assert captured["overrides"]["countries"] == ["sk"]
    assert captured["overrides"]["exclude_keywords"] == ["jobs"]
    assert captured["overrides"]["max_pages_per_site"] == 7
    assert captured["overrides"]["browser_mode"] == "playwright"
    assert captured["probe_browser_launch"] is False
