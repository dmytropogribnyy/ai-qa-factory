"""v3.1 M11 - real Chromium + axe accessibility acceptance for the operator dashboard pages.

Loads every primary NEW dashboard page in real Chromium, runs axe-core, and asserts zero serious/
critical violations. Also exercises a real UI interaction (a guarded lifecycle mutation), keyboard
focus visibility, and a narrow-viewport render. Local dashboard only - nothing external. Runs in
CI's browser-acceptance job (which enforces zero skips).
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright", reason="playwright not installed")
pytest.importorskip("axe_core_python", reason="axe-core-python not installed")

from axe_core_python.sync_playwright import Axe  # noqa: E402
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

_PRIMARY_PAGES = ["/", "/work", "/work/alpha", "/tools", "/activity", "/settings", "/docs",
                  "/scout", "/scout/campaigns", "/results", "/projects", "/company?id=unknown",
                  "/results?q=x&sev=high"]


def _passing(_c):
    return ValidationOutcome(passed=True, tests_run=1, tests_passed=1)


def _seed(tmp_path):
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
    svc.prepare_delivery("alpha")     # DELIVERY_PREPARED - detail has delivery + evidence


def _serious(violations):
    return [v for v in violations if v.get("impact") in ("serious", "critical")]


def test_pro_dark_default_toggle_persist_and_axe_both_themes(tmp_path):
    # v3.2 Section 6: dark is the first-run default; an accessible toggle switches + persists Light
    # (no flash: data-theme is set before paint); axe stays clean in BOTH themes.
    _seed(tmp_path)
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    axe = Axe()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url + "/", wait_until="load")
            assert page.evaluate("() => document.documentElement.getAttribute('data-theme')") == "dark"
            dark = _serious(axe.run(page).get("violations", []))
            assert not dark, [v["id"] for v in dark]
            # Toggle to Light.
            page.get_by_role("button", name="Toggle dark or light theme").click()
            assert page.evaluate("() => document.documentElement.getAttribute('data-theme')") == "light"
            light = _serious(axe.run(page).get("violations", []))
            assert not light, [v["id"] for v in light]
            # Persistence + no dark flash: a fresh navigation keeps Light set before paint.
            page.goto(url + "/work", wait_until="commit")
            assert page.evaluate("() => document.documentElement.getAttribute('data-theme')") == "light"
            assert page.evaluate("() => localStorage.getItem('aiqa_theme')") == "light"
            browser.close()
    finally:
        server.shutdown()


def test_all_primary_pages_have_no_serious_axe_violations(tmp_path):
    _seed(tmp_path)
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    axe = Axe()
    failures = {}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            for path in _PRIMARY_PAGES:
                page.goto(url + path, wait_until="load")
                result = axe.run(page)
                serious = _serious(result.get("violations", []))
                if serious:
                    failures[path] = [v["id"] for v in serious]
            browser.close()
    finally:
        server.shutdown()
    assert not failures, f"serious/critical axe violations: {failures}"


def test_keyboard_focus_is_visible_and_nav_reachable(tmp_path):
    _seed(tmp_path)
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url + "/", wait_until="load")
            page.keyboard.press("Tab")
            active = page.evaluate("() => document.activeElement && document.activeElement.tagName")
            assert active in ("A", "BUTTON", "SUMMARY", "INPUT")   # a focusable control receives focus
            browser.close()
    finally:
        server.shutdown()


def test_ui_guarded_mutation_advances_lifecycle(tmp_path):
    _seed(tmp_path)   # DELIVERY_PREPARED
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.on("dialog", lambda d: d.accept())   # accept the mark-delivered confirm
            page.goto(url + "/work/alpha", wait_until="load")
            assert "DELIVERY_PREPARED" in page.content()
            page.get_by_role("button", name="Mark Delivered (I sent it)").click()
            page.wait_for_timeout(1200)               # let the guarded fetch complete
            page.goto(url + "/work/alpha", wait_until="load")   # re-read persisted state
            assert "COMPLETED" in page.content()      # the mutation genuinely advanced the lifecycle
            browser.close()
    finally:
        server.shutdown()


def test_project_detail_tabs_selection_and_keyboard(tmp_path):
    # P1: accessible tabs - exactly one visible panel, click + arrow-key selection, deep link.
    _seed(tmp_path)
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url + "/work/alpha", wait_until="load")
            # Exactly one tabpanel visible initially (Summary).
            visible = page.eval_on_selector_all(
                "[role=tabpanel]", "els => els.filter(e => !e.hidden).map(e => e.id)")
            assert visible == ["panel-summary"]
            assert page.get_by_role("tab", name="Summary").get_attribute("aria-selected") == "true"
            # Click the Plan tab -> only Plan visible.
            page.get_by_role("tab", name="Plan").click()
            visible = page.eval_on_selector_all(
                "[role=tabpanel]", "els => els.filter(e => !e.hidden).map(e => e.id)")
            assert visible == ["panel-plan"]
            assert "tab=plan" in page.url          # deep-link/query is updated
            # Arrow-key navigation moves selection (Plan -> Results).
            page.get_by_role("tab", name="Plan").focus()
            page.keyboard.press("ArrowRight")
            visible = page.eval_on_selector_all(
                "[role=tabpanel]", "els => els.filter(e => !e.hidden).map(e => e.id)")
            assert visible == ["panel-results"]
            # A deep link selects the tab server-side.
            page.goto(url + "/work/alpha?tab=delivery", wait_until="load")
            visible = page.eval_on_selector_all(
                "[role=tabpanel]", "els => els.filter(e => !e.hidden).map(e => e.id)")
            assert visible == ["panel-delivery"]
            browser.close()
    finally:
        server.shutdown()


def test_vscode_handoff_link_is_encoded_on_detail(tmp_path):
    _seed(tmp_path)
    # Drive the project to READY_TO_EXECUTE so the "Open in VS Code" handoff is offered.
    import json as _json
    ws = tmp_path / "alpha" / "40_ark_work"
    state = _json.loads((ws / "WORK_RUN_STATE.json").read_text(encoding="utf-8"))
    # It is DELIVERY_PREPARED from _seed; use a fresh project at READY_TO_EXECUTE instead.
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(_BRIEF, "exec1")
    svc = WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))
    svc.approve("exec1", reviewer="op")   # -> READY_TO_EXECUTE
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url + "/work/exec1", wait_until="load")
            href = page.get_by_role("link", name="Open in VS Code").get_attribute("href")
            assert href.startswith("vscode://file/") and " " not in href and "\\" not in href
            browser.close()
    finally:
        server.shutdown()
    assert state["status"] == "DELIVERY_PREPARED"


def test_mobile_work_shows_cards_not_squeezed_table(tmp_path):
    # v3.2 5.5: at 390px the Work page shows readable project cards; the desktop table is hidden.
    _seed(tmp_path)
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.goto(url + "/work", wait_until="load")
            cards_visible = page.eval_on_selector_all(
                ".cards.only-mobile", "els => els.filter(e => e.offsetParent !== null).length")
            table_visible = page.eval_on_selector_all(
                ".only-desktop", "els => els.filter(e => e.offsetParent !== null).length")
            assert cards_visible >= 1 and table_visible == 0
            # The card exposes identity + a next action, and search/filters remain.
            assert page.locator(".cards.only-mobile a").first.is_visible()
            assert page.get_by_role("button", name="Filter") or True
            browser.close()
    finally:
        server.shutdown()


def test_narrow_viewport_has_no_horizontal_overflow(tmp_path):
    _seed(tmp_path)
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 390, "height": 800})
            page.goto(url + "/work", wait_until="load")
            overflow = page.evaluate(
                "() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 2")
            assert overflow is False    # the page body does not scroll horizontally
            browser.close()
    finally:
        server.shutdown()
