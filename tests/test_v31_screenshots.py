"""v3.1 - capture real Chromium PNG screenshots of the operator dashboard for visual review.

Writes bounded PNGs under reports/screenshots/ (desktop + 390px mobile). Runs in CI's browser
job (playwright_acceptance marker; zero skips) and the PNGs are uploaded as a build artifact tied
to the candidate SHA. Local dashboard only; nothing external.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

import pytest

pytest.importorskip("playwright", reason="playwright not installed")

from playwright.sync_api import sync_playwright  # noqa: E402

from core.orchestration.client_work import ClientWorkService  # noqa: E402
from core.orchestration.operator_executor import (  # noqa: E402
    OperatorWorkspaceExecutor,
    ProducedArtifact,
)
from core.orchestration.providers import FixedClock, SequentialIds  # noqa: E402
from core.orchestration.work_execution import WorkExecutionService  # noqa: E402
from core.schemas.work_execution import ValidationOutcome  # noqa: E402
from core.scout.dashboard import start_dashboard  # noqa: E402
from core.scout.service import ScoutService  # noqa: E402

_BRIEF = "Reproduce and fix a defect in a small Python module and add a regression test."
_OUT = Path("reports/screenshots")


def _chromium_available() -> bool:
    try:
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            b.close()
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.playwright_acceptance,
    pytest.mark.skipif(not _chromium_available(), reason="Chromium build not available"),
]


def _passing(_c):
    return ValidationOutcome(passed=True, tests_run=1, tests_passed=1)


def _seed(tmp_path):
    # A client-work project at DELIVERY_PREPARED (rich detail + evidence).
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(_BRIEF, "alpha")
    ws = tmp_path / "alpha" / "40_ark_work"
    (ws / "fix.py").write_text("x = 1\n", encoding="utf-8")
    (ws / "evidence").mkdir(exist_ok=True)
    (ws / "evidence" / "log.txt").write_text("regression ok\n", encoding="utf-8")
    svc = WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))
    svc.approve("alpha", reviewer="op")
    ex = OperatorWorkspaceExecutor(
        [ProducedArtifact("fix.py", "fix"),
         ProducedArtifact("evidence/log.txt", "report", is_evidence=True,
                          evidence_kind="test_output", description="evidence")], _passing)
    svc.execute("alpha", ex)
    svc.validate("alpha", ex)
    svc.review("alpha", reviewer="op", approved=True)
    svc.prepare_delivery("alpha")


def _try_radar(tmp_path):
    try:
        from core.scout.comms.demo import run_radar_demo
        return run_radar_demo(str(tmp_path))
    except Exception:
        return None


def test_capture_dashboard_screenshots(tmp_path):
    _OUT.mkdir(parents=True, exist_ok=True)
    _seed(tmp_path)
    summary = _try_radar(tmp_path)
    service = ScoutService(str(tmp_path))
    if summary:
        try:
            service.attach(summary["campaign_id"])
        except Exception:
            pass
    server, url = start_dashboard(service, operator_home=True)
    # Resolve a real company id for the company-detail shot, if the demo produced one.
    cid = ""
    try:
        with urllib.request.urlopen(url + "/api/results", timeout=5) as r:
            comps = json.loads(r.read()).get("companies", [])
            cid = comps[0]["company_id"] if comps else ""
    except Exception:
        cid = ""

    desktop = {
        "overview": "/", "scout-home": "/scout", "scout-campaigns": "/scout/campaigns",
        "results": "/results?sev=", "company": f"/company?id={cid}" if cid else "/company?id=unknown",
        "work-list": "/work", "project-summary": "/work/alpha?tab=summary",
        "project-plan": "/work/alpha?tab=plan", "project-results": "/work/alpha?tab=results",
        "project-delivery": "/work/alpha?tab=delivery", "tools": "/tools", "activity": "/activity",
        "settings": "/settings",
    }
    mobile = {"overview": "/", "scout-home": "/scout", "work-list": "/work",
              "project-detail": "/work/alpha", "nav-more": "/tools"}
    # Representative Light-theme pages (dark is the default; these prove the toggle looks right).
    light = {"overview": "/", "work-list": "/work", "tools": "/tools"}
    captured = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})
            for name, path in desktop.items():
                page.goto(url + path, wait_until="load")
                page.evaluate("() => window.scrollTo(0, 0)")   # reset scroll before capture
                out = _OUT / f"desktop-dark-{name}.png"
                page.screenshot(path=str(out), full_page=True)
                captured.append(out)
            page.close()
            lp = browser.new_page(viewport={"width": 1280, "height": 900})
            lp.add_init_script("try{localStorage.setItem('aiqa_theme','light');}catch(e){}")
            for name, path in light.items():
                lp.goto(url + path, wait_until="load")
                lp.evaluate("() => window.scrollTo(0, 0)")
                out = _OUT / f"desktop-light-{name}.png"
                lp.screenshot(path=str(out), full_page=True)
                captured.append(out)
            lp.close()
            mp = browser.new_page(viewport={"width": 390, "height": 844})
            for name, path in mobile.items():
                mp.goto(url + path, wait_until="load")
                mp.evaluate("() => window.scrollTo(0, 0)")
                out = _OUT / f"mobile-dark-{name}.png"
                mp.screenshot(path=str(out), full_page=True)
                captured.append(out)
            browser.close()
    finally:
        server.shutdown()
    assert len(captured) == len(desktop) + len(light) + len(mobile)
    for f in captured:
        assert f.exists() and f.stat().st_size > 0, f
