"""Phase 8.3 — Scout dashboard (localhost only; health/API/artifact/control/kill)."""
from __future__ import annotations

import itertools
import json
import urllib.request

from core.scout.config import ScoutRunConfig
from core.scout.service import ScoutService
from core.scout.dashboard import start_dashboard
from core.scout.engine import RUN_KILLED
from tests.scout_fixtures import serve_fixtures

_clock_counter = itertools.count()


def _clock():
    return f"2026-07-17T01:00:{next(_clock_counter):02d}+00:00"


def _get(url):
    with urllib.request.urlopen(url, timeout=5) as r:
        return r.status, r.read().decode("utf-8")


def _post(url):
    req = urllib.request.Request(url, method="POST")
    with urllib.request.urlopen(req, timeout=5) as r:
        return r.status, r.read().decode("utf-8")


def _finished_service(base, host, tmp):
    seeds = [f"{base}/{n}/index.html" for n in ("clean", "seo", "captcha")]
    cfg = ScoutRunConfig(campaign_name="dash", seeds=seeds, allowed_local_hosts=frozenset({host}),
                         browser_mode="static", output_dir=str(tmp), run_id="dash-run")
    svc = ScoutService(str(tmp))
    svc.start(cfg, clock=_clock)
    svc.join(timeout=30)
    return svc


def test_health_and_status_and_prospects(tmp_path):
    with serve_fixtures() as (base, host):
        svc = _finished_service(base, host, tmp_path)
        server, url = start_dashboard(svc)
        try:
            s, body = _get(url + "/health")
            assert s == 200 and json.loads(body)["status"] == "ok"
            s, body = _get(url + "/api/status")
            assert json.loads(body)["state"]["status"] == "COMPLETED"
            s, body = _get(url + "/api/prospects")
            assert len(json.loads(body)["prospects"]) == 3
            s, body = _get(url + "/")   # HTML overview renders
            assert "Prospect QA Scout" in body and "Cancel (kill)" in body and "Stop Safely" in body
        finally:
            server.shutdown()


def test_prospect_detail_and_artifact_pathsafe(tmp_path):
    with serve_fixtures() as (base, host):
        svc = _finished_service(base, host, tmp_path)
        server, url = start_dashboard(svc)
        try:
            s, body = _get(url + "/api/prospect?id=01-127-0-0-1")
            detail = json.loads(body)
            assert detail["findings"] is not None and detail["scorecard"] is not None
            # Path-safe artifact serving works for a real artifact...
            s, body = _get(url + "/artifact?path=prospects/01-127-0-0-1/findings.json")
            assert s == 200 and "verified" in body
            # ...and traversal is refused.
            try:
                _get(url + "/artifact?path=../../../etc/passwd")
                raise AssertionError("traversal should be refused")
            except urllib.error.HTTPError as e:
                assert e.code in (403, 404)
        finally:
            server.shutdown()


def test_global_kill_via_dashboard(tmp_path):
    with serve_fixtures() as (base, host):
        seeds = [f"{base}/{n}/index.html" for n in
                 ("clean", "seo", "accessibility", "mobile", "structured_data",
                  "presubmit", "business_flow", "broken_link")]
        cfg = ScoutRunConfig(campaign_name="killdash", seeds=seeds,
                             allowed_local_hosts=frozenset({host}), browser_mode="static",
                             output_dir=str(tmp_path), run_id="kill-run")
        svc = ScoutService(str(tmp_path))
        server, url = start_dashboard(svc)
        try:
            svc.start(cfg, clock=_clock)
            s, body = _post(url + "/api/control?action=kill")
            assert s == 200 and json.loads(body)["ok"] is True
            svc.join(timeout=30)
            s, body = _get(url + "/api/status")
            assert json.loads(body)["state"]["status"] == RUN_KILLED
            assert svc.is_running() is False
        finally:
            server.shutdown()
