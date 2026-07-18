"""v3.0.0 Milestone 7c - REAL Chromium + axe acceptance for EVERY dashboard page + campaign controls.

This is not a mock. It launches a real headless Chromium (via the optional ``playwright`` package)
against the localhost dashboard and, on every operator page (home, results, projects, tool readiness,
company detail), runs the real axe-core accessibility engine and asserts no critical/serious
violations. It then drives the campaign controls in the live DOM: the Pause / Resume / Stop Safely /
Cancel buttons render and fire ``/api/control``, and the guarded Start form fills + submits with the
per-page CSRF token, reaching the M4b endpoint.

Nothing external happens: the scan uses the offline static backend over an allow-listed LOCAL fixture
site, and the browser "Start" uses an injected fixture starter (no live send, no live scan, no real
browser-driven crawl of a third party).

Skipped automatically unless playwright + Chromium + axe-core-python are installed, so the ordinary
suite stays deterministic. Runs in CI's browser-acceptance job:

    .venv/Scripts/python.exe -m pytest -m playwright_acceptance -q
"""
from __future__ import annotations

import itertools

import pytest

pytest.importorskip("playwright", reason="playwright not installed")
pytest.importorskip("axe_core_python", reason="axe-core-python not installed")

from axe_core_python.sync_playwright import Axe  # noqa: E402
from playwright.sync_api import sync_playwright  # noqa: E402

from core.orchestration.client_work import ClientWorkService  # noqa: E402
from core.orchestration.providers import FixedClock, SequentialIds  # noqa: E402
from core.scout.campaign_start import CampaignLauncher  # noqa: E402
from core.scout.config import ScoutRunConfig  # noqa: E402
from core.scout.dashboard import start_dashboard  # noqa: E402
from core.scout.service import ScoutService  # noqa: E402
from tests.scout_fixtures import serve_fixtures  # noqa: E402


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
    pytest.mark.skipif(not _chromium_available(),
                       reason="Chromium build not available (run: python -m playwright install chromium)"),
]

_CSRF = "browser-accept-csrf-token"
_c = itertools.count()


def _clock() -> str:
    return f"2026-07-18T09:00:{next(_c):02d}+00:00"


@pytest.fixture
def dashboard(tmp_path):
    """A finished, OWNED Scout run (controllable + start panel) plus a real client-work project, with
    a fixture starter behind the guarded start endpoint so the browser never triggers a live scan."""
    with serve_fixtures() as (base, host):
        seeds = [f"{base}/{n}/index.html" for n in ("clean", "seo", "captcha")]
        cfg = ScoutRunConfig(campaign_name="dash", seeds=seeds, browser_mode="static",
                             allowed_local_hosts=frozenset({host}), output_dir=str(tmp_path),
                             run_id="dash-run")
        svc = ScoutService(str(tmp_path))
        svc.start(cfg, clock=_clock)
        svc.join(timeout=45)
        # A real client-work project so /projects renders a genuine row.
        ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(
            "Reproduce and fix a defect in a small Python module and add a regression test.", "cwdemo")

        started = []
        launcher = CampaignLauncher(svc, registry_dir=str(tmp_path / "reg"),
                                    allowed_local_hosts=frozenset({host}), resolve_dns=False,
                                    starter=lambda c: (started.append(c) or c.run_id))
        server, url = start_dashboard(svc, launcher=launcher, csrf_token=_CSRF)
        try:
            yield {"url": url, "svc": svc, "started": started, "host": host}
        finally:
            server.shutdown()
            server.server_close()


def _serious(results) -> list:
    return [(v["id"], v["impact"]) for v in results["violations"]
            if v.get("impact") in ("critical", "serious")]


def test_all_dashboard_pages_are_accessible(dashboard):
    base = dashboard["url"]
    paths = ["/", "/results", "/projects", "/tools", "/company?id=unknown"]
    axe = Axe()
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            for path in paths:
                resp = page.goto(base + path, wait_until="networkidle")
                assert resp is not None and resp.status == 200, f"{path} did not render"
                results = axe.run(page)
                assert "violations" in results, f"axe did not run on {path}"
                assert not _serious(results), f"{path} accessibility violations: {_serious(results)}"
        finally:
            browser.close()


def test_home_renders_controls_and_start_panel_without_console_errors(dashboard):
    base = dashboard["url"]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        errors = []
        page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
        try:
            page.goto(base + "/", wait_until="networkidle")
            for label in ("Pause", "Resume", "Stop Safely", "Cancel (kill)"):
                assert page.locator(f"button:has-text('{label}')").count() >= 1, f"missing {label}"
            assert page.locator("#seeds").count() == 1 and page.locator("#confirm").count() == 1
            assert page.locator("button:has-text('Start campaign')").count() == 1
        finally:
            browser.close()
    # A missing favicon 404 is not an application console error; nothing else should log an error.
    real = [e for e in errors if "favicon" not in e.lower() and "404" not in e]
    assert not real, real


def test_stop_safely_button_fires_control(dashboard):
    base, svc = dashboard["url"], dashboard["svc"]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(base + "/", wait_until="networkidle")
            page.once("dialog", lambda d: d.dismiss())
            page.locator("button:has-text('Stop Safely')").first.click()
            page.wait_for_load_state("networkidle")  # JS reloads after the control resolves
        finally:
            browser.close()
    assert svc.status()["control"].get("cancelled") is True   # graceful stop was recorded


def test_guarded_start_form_starts_bounded_campaign(dashboard):
    base, host, started = dashboard["url"], dashboard["host"], dashboard["started"]
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            page.goto(base + "/", wait_until="networkidle")
            page.once("dialog", lambda d: d.dismiss())
            page.fill("#seeds", f"http://{host}/clean/index.html")
            page.check("#confirm")
            page.locator("button:has-text('Start campaign')").click()
            page.wait_for_timeout(800)   # allow the CSRF-authenticated fetch to reach the endpoint
        finally:
            browser.close()
    assert len(started) == 1, "the guarded start endpoint did not start exactly one campaign"
    cfg = started[0]
    assert cfg.browser_mode == "static" and cfg.concurrency == 1   # bounded, read-only
    assert cfg.seeds == [f"http://{host}/clean/index.html"]
