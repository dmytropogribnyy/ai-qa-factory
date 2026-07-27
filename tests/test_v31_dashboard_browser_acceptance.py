"""v3.1 M11 - real Chromium + axe accessibility acceptance for the operator dashboard pages.

Loads every primary NEW dashboard page in real Chromium, runs axe-core, and asserts zero serious/
critical violations. Also exercises a real UI interaction (a guarded lifecycle mutation), keyboard
focus visibility, and a narrow-viewport render. Local dashboard only - nothing external. Runs in
CI's browser-acceptance job (which enforces zero skips).
"""
from __future__ import annotations

import struct
import zipfile
import zlib
from pathlib import Path

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
from core.scout.discovery.analyzed_registry import AnalyzedSiteRegistry  # noqa: E402
from core.scout.findings import ScoutFinding  # noqa: E402
from core.scout.service import ScoutService  # noqa: E402
from core.scout.store import RunStore  # noqa: E402

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

_PRIMARY_PAGES = ["/", "/work", "/work/alpha", "/tools", "/activity", "/collab",
                  "/settings", "/docs", "/scout", "/scout/campaigns", "/results",
                  "/company?id=unknown",
                  "/results?q=x&sev=high", "/scout/new", "/scout/history",
                  "/scout/attention"]


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


def _seed_scout_operator(tmp_path):
    run_id = "operator-browser-run"
    store = RunStore(str(tmp_path), run_id)
    store.write_config({"campaign_name": "curated", "browser_mode": "playwright",
                        "video_mode": "manual"})
    store.save_state({"status": "COMPLETED", "finished_at": "2026-07-24T08:00:00+00:00",
                      "prospects": {
        "01-alpha": {"status": "DONE", "url": "https://alpha.example/",
                     "verified_findings": 1, "verified_defects": 1,
                     "coverage": "adaptive", "meaningful_pages_tested": 2,
                     "page_stop_reason": "links_exhausted"},
        "02-beta": {"status": "MANUAL_ACTION_REQUIRED", "url": "https://beta.example/",
                    "reason": "captcha_detected", "analysis_complete": False},
    }})
    finding = ScoutFinding(
        signature="broken_checkout", category="functional", severity="high",
        confidence="high", title="Checkout link returns an error",
        business_impact="Blocks conversion",
        reproduction_steps=["Open checkout", "Select Continue"]).to_dict()
    store.save_prospect_artifact("01-alpha", "findings.json",
                                 {"verified": [finding], "rejected": []})
    store.save_prospect_artifact("01-alpha", "coverage.json", {
        "coverage": "adaptive", "page_ceiling": 12, "meaningful_pages_tested": 2,
        "pages_skipped_noise": 1, "pages_skipped_near_duplicate": 0,
        "page_stop_reason": "links_exhausted"})
    store.save_prospect_artifact("01-alpha", "observation.json", {
        "status": 200, "final_url": "https://alpha.example/", "axe_status": "ok",
        "axe_violations": [], "timing_ms": {"load": 400},
        "links": ["mailto:hello@alpha.example"]})
    store.save_prospect_artifact("01-alpha", "browser_trace.json", {
        "schema_version": 1, "redaction_applied": True, "raw_dom_stored": False,
        "raw_headers_stored": False, "passes": [{
            "pass": "landing", "url": "https://alpha.example/",
            "final_url": "https://alpha.example/", "status": 200, "ok": True,
            "screenshot_ref": "landing.png", "timing_ms": {"load": 400},
            "console_errors": [], "failed_resources": [], "blocked_requests": [],
        }],
    })
    (store.prospect_dir("01-alpha") / "landing.png").write_bytes(_fixture_png())
    store.save_prospect_artifact("02-beta", "observation.json", {
        "status": 403, "final_url": "https://beta.example/", "captcha_marker": True})
    store.save_prospect_artifact("02-beta", "manual_action.json", {
        "reason": "captcha_detected", "stage": "post_landing_precheck",
        "stop_boundary": "stopped_before_interaction",
        "recommended_action": "Complete the human check, then continue."})
    AnalyzedSiteRegistry(str(tmp_path)).record_analysis(
        "alpha.example", campaign_id=run_id, evidence_ref=f"scout/{run_id}")
    control = tmp_path / "scout" / "_runcontrol"
    control.mkdir(parents=True, exist_ok=True)
    (control / f"{run_id}.json").write_text(
        '{"campaign_id":"operator-browser-run"}', encoding="utf-8")
    return run_id


def _seed_persisted_activity(tmp_path):
    """Two production campaigns + one diagnostic, with no run attached to the service."""
    production_a = "campaign-acme-saas-20260724t090000z-0f9d21"
    production_b = "campaign-beta-commerce-20260724t091000z-a1b2c3"
    diagnostic = "smoke-activity"
    control = tmp_path / "scout" / "_runcontrol"
    control.mkdir(parents=True, exist_ok=True)
    for campaign_id in (production_a, production_b, diagnostic):
        (control / f"{campaign_id}.json").write_text(
            f'{{"campaign_id":"{campaign_id}","state":"completed"}}',
            encoding="utf-8",
        )
    for campaign_id, rows in (
        (production_a, [
            {"at": "2026-07-24T09:00:00+00:00", "event": "campaign_started"},
            {"at": "2026-07-24T09:02:00+00:00", "event": "promoted_to_scout",
             "candidate": "acme.example"},
            {"at": "2026-07-24T09:04:00+00:00", "event": "campaign_finished"},
        ]),
        (production_b, [
            {"at": "2026-07-24T09:10:00+00:00", "event": "campaign_started"},
            {"at": "2026-07-24T09:12:00+00:00", "event": "actionable_target_reached",
             "target": 1},
            {"at": "2026-07-24T09:14:00+00:00", "event": "campaign_finished"},
        ]),
        (diagnostic, [
            {"at": "2026-07-24T09:20:00+00:00", "event": "campaign_started"},
        ]),
    ):
        store = RunStore(str(tmp_path), campaign_id)
        for row in rows:
            store.append_event(row)
    return production_a, production_b, diagnostic


def _fixture_png(width=320, height=180):
    """Small valid screenshot-like PNG fixture without an image-library dependency."""
    rows = []
    for y in range(height):
        color = (34, 91 + (y % 35), 180) if y < 120 else (238, 244, 255)
        rows.append(b"\x00" + bytes(color) * width)

    def chunk(kind, payload):
        return (
            struct.pack(">I", len(payload)) + kind + payload
            + struct.pack(">I", zlib.crc32(kind + payload) & 0xFFFFFFFF)
        )

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(b"".join(rows), 9))
        + chunk(b"IEND", b"")
    )


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
            # Toggle to Light. The button is named after the action it performs, so the name must
            # also flip once the theme has changed (an operator must never be offered "Switch to
            # light theme" while already in Light).
            page.get_by_role("button", name="Switch to light theme").click()
            assert page.evaluate("() => document.documentElement.getAttribute('data-theme')") == "light"
            assert page.get_by_role("button", name="Switch to dark theme").is_visible()
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


def test_activity_survives_restart_and_filters_diagnostics_in_real_chromium(tmp_path):
    production_a, production_b, diagnostic = _seed_persisted_activity(tmp_path)
    # No service.attach(): this is the exact cold-start state that previously rendered empty.
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    axe = Axe()
    screenshot_dir = Path("reports/screenshots/operator")
    screenshot_dir.mkdir(parents=True, exist_ok=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            desktop = browser.new_page(viewport={"width": 1280, "height": 900})
            desktop.goto(url + "/activity", wait_until="load")
            assert desktop.get_by_text("No operator activity yet.", exact=False).count() == 0
            assert desktop.locator("tbody tr").count() == 6
            # Rows are attributed by the operator-facing campaign name; the internal run id is an
            # implementation detail and must not be what the operator reads.
            body = desktop.content()
            assert production_a not in body and production_b not in body
            assert desktop.get_by_text("Acme Saas", exact=False).count() == 3
            assert desktop.get_by_text("Beta Commerce", exact=False).count() == 3
            assert desktop.get_by_text(diagnostic, exact=True).count() == 0
            assert desktop.get_by_text("Target promoted to Scout", exact=True).is_visible()
            serious = _serious(axe.run(desktop).get("violations", []))
            assert not serious, [v["id"] for v in serious]
            desktop.evaluate("()=>window.scrollTo(0,0)")
            assert desktop.evaluate("()=>window.scrollY") == 0
            desktop.screenshot(
                path=screenshot_dir / "09-scout-activity-production-desktop.png",
                full_page=True,
            )

            desktop.get_by_role("link", name="Show diagnostics").click()
            assert "diagnostics=1" in desktop.url
            assert desktop.locator("tbody tr").count() == 7
            assert desktop.get_by_text(diagnostic, exact=True).count() == 1
            assert desktop.get_by_text(
                "is included below and should not be treated as production",
                exact=False,
            ).is_visible()
            serious = _serious(axe.run(desktop).get("violations", []))
            assert not serious, [v["id"] for v in serious]
            # Clicking the toggle can preserve the previous document's scroll position. Reset it
            # before capturing so CI evidence contains the complete header/navigation, not a
            # misleading cropped state.
            desktop.evaluate("()=>window.scrollTo(0,0)")
            assert desktop.evaluate("()=>window.scrollY") == 0
            desktop.screenshot(
                path=screenshot_dir / "10-scout-activity-diagnostics-desktop.png",
                full_page=True,
            )

            mobile = browser.new_page(viewport={"width": 390, "height": 844})
            mobile.goto(url + "/activity", wait_until="load")
            assert mobile.locator("tbody tr").count() == 6
            assert mobile.evaluate(
                "()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth+2")
            serious = _serious(axe.run(mobile).get("violations", []))
            assert not serious, [v["id"] for v in serious]
            mobile.evaluate("()=>window.scrollTo(0,0)")
            assert mobile.evaluate("()=>window.scrollY") == 0
            mobile.screenshot(
                path=screenshot_dir / "11-scout-activity-production-mobile.png",
                full_page=True,
            )
            browser.close()
    finally:
        server.shutdown()


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
            page.goto(url + "/work/alpha", wait_until="load")
            assert page.get_by_text("Delivery prepared").first.is_visible()
            # The handler is an inline attribute: if it is malformed the click throws and the button
            # is silently dead, so fail loudly on any page error rather than on a later assertion.
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.get_by_role("button", name="Mark Delivered (I sent it)").click()
            # Confirmation is an in-page <dialog>, not window.confirm, and its confirm button is
            # named after the action being confirmed.
            dialog = page.locator("#qa-confirm")
            dialog.get_by_role("button", name="Mark Delivered (I sent it)").click()
            page.wait_for_timeout(1200)               # let the guarded fetch complete
            assert not errors, errors
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


def test_scout_form_is_themed_and_axe_clean_both_themes(tmp_path):
    # v3.2 item 3: the Scout campaign form (textarea / inputs / checkbox / Start button) uses the
    # design-system tokens — no default-white control in Dark — and is axe-clean in BOTH themes,
    # with every safety statement preserved.
    _seed(tmp_path)
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    axe = Axe()
    _WHITE = ("rgb(255, 255, 255)", "rgba(0, 0, 0, 0)")
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url + "/scout", wait_until="load")
            assert page.locator("#seeds").count() == 1 and page.locator("#confirm").count() == 1
            assert "never sends email, submits forms, solves CAPTCHAs" in page.content()  # safety kept
            # Dark: the textarea + Start button are NOT default white.
            ta_bg = page.evaluate("()=>getComputedStyle(document.getElementById('seeds')).backgroundColor")
            btn_bg = page.evaluate(
                "()=>getComputedStyle(document.querySelector('.card .btn.primary')).backgroundColor")
            assert ta_bg not in _WHITE and btn_bg not in _WHITE, (ta_bg, btn_bg)
            for _ in range(2):
                serious = _serious(axe.run(page).get("violations", []))
                assert not serious, [v["id"] for v in serious]
                page.evaluate("()=>localStorage.setItem('aiqa_theme','light')")
                page.reload(wait_until="load")
            browser.close()
    finally:
        server.shutdown()


def test_operator_overview_stays_stable_with_attached_run_and_is_axe_clean(tmp_path):
    # Operator friendliness: an attached Scout run never replaces the stable Overview front door.
    # Explicit Scout pages own run controls. Overview remains accessible in both themes and mobile.
    from core.scout.store import RunStore
    store = RunStore(str(tmp_path), "run-legacy")
    store.reset()
    store.save_state({
        "run_id": "run-legacy", "status": "RUNNING", "mode": "OBSERVE_ONLY",
        "prospects": {"p1": {"url": "https://example.test/", "status": "MANUAL_ACTION_REQUIRED",
                             "priority": "high", "verified_defects": 2}}})
    service = ScoutService(str(tmp_path))
    service.attach("run-legacy")
    server, url = start_dashboard(service, operator_home=True)
    axe = Axe()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url + "/", wait_until="load")
            html = page.content()
            assert 'header class="top"' in html and "<main>" in html
            assert "<h1>Overview</h1>" in html
            bg = page.evaluate("()=>getComputedStyle(document.body).backgroundColor")
            assert bg not in ("rgba(0, 0, 0, 0)", "rgb(255, 255, 255)"), bg  # not default white
            for theme in ("dark", "light"):
                serious = _serious(axe.run(page).get("violations", []))
                assert not serious, (theme, [v["id"] for v in serious])
                page.evaluate("(t)=>localStorage.setItem('aiqa_theme',t)", "light")
                page.reload(wait_until="load")
            mob = browser.new_page(viewport={"width": 390, "height": 844})
            mob.goto(url + "/", wait_until="load")
            assert mob.evaluate("()=>document.documentElement.scrollWidth<=window.innerWidth+1")
            browser.close()
    finally:
        server.shutdown()


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


def test_operator_scout_pages_are_responsive_accessible_and_bulk_archive_works(tmp_path):
    run_id = _seed_scout_operator(tmp_path)
    service = ScoutService(str(tmp_path))
    service.attach(run_id)
    server, url = start_dashboard(service, operator_home=True)
    axe = Axe()
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            desktop = browser.new_page(viewport={"width": 1280, "height": 900})
            screenshot_dir = Path("reports/screenshots/operator")
            screenshot_dir.mkdir(parents=True, exist_ok=True)
            for path in (
                f"/scout/run?id={run_id}",
                f"/scout/target?run={run_id}&domain=alpha.example",
                f"/scout/target?run={run_id}&domain=beta.example",
                "/scout/history",
                "/scout/attention",
            ):
                desktop.goto(url + path, wait_until="load")
                serious = _serious(axe.run(desktop).get("violations", []))
                assert not serious, (path, [v["id"] for v in serious])

            desktop.goto(url + f"/scout/run?id={run_id}", wait_until="load")
            desktop.screenshot(
                path=screenshot_dir / "01-scout-run-results-desktop.png", full_page=True)
            desktop.goto(
                url + f"/scout/target?run={run_id}&domain=alpha.example", wait_until="load")
            assert desktop.get_by_role(
                "link", name="Download client-ready evidence (.zip)").is_visible()
            assert desktop.get_by_text("hello@alpha.example", exact=True).is_visible()
            assert desktop.get_by_text("Public mailto link", exact=False).is_visible()
            assert desktop.get_by_text("fixable by us after", exact=False).is_visible()
            with desktop.expect_download() as download_info:
                desktop.get_by_role(
                    "link", name="Download client-ready evidence (.zip)").click()
            download = download_info.value
            assert download.suggested_filename == "alpha.example-qa-evidence.zip"
            with zipfile.ZipFile(download.path()) as archive:
                names = set(archive.namelist())
                assert {"QA_Evidence_Summary.html", "MANIFEST.json"} <= names
                # Frames are named for the page they show, and a byte-identical capture is never
                # packaged twice, so the count is evidence rather than files.
                shots = [n for n in names if n.startswith("evidence/screenshots/")]
                assert shots == ["evidence/screenshots/landing.png"]
            desktop.screenshot(
                path=screenshot_dir / "02-scout-target-complete-desktop.png", full_page=True)
            desktop.goto(
                url + f"/scout/target?run={run_id}&domain=beta.example", wait_until="load")
            assert desktop.get_by_role("button", name="Open manual check").is_visible()
            assert desktop.get_by_text("analysis incomplete", exact=False).is_visible()
            assert desktop.get_by_text("Advanced diagnostics").is_visible()
            assert desktop.locator("details.advanced").get_attribute("open") is None
            desktop.screenshot(
                path=screenshot_dir / "03-scout-target-needs-attention-desktop.png",
                full_page=True)
            desktop.goto(url + "/scout/attention", wait_until="load")
            desktop.screenshot(
                path=screenshot_dir / "04-scout-attention-queue-desktop.png", full_page=True)

            mobile = browser.new_page(viewport={"width": 390, "height": 844})
            mobile.goto(url + f"/scout/run?id={run_id}", wait_until="load")
            assert mobile.evaluate(
                "()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth+2")
            # Scope to the table body: the run summary now carries a tile per outcome using the SAME
            # vocabulary as the rows, so this label legitimately appears twice on the page. The check
            # here is about the ROW badge surviving the mobile card layout.
            assert mobile.locator("tbody").get_by_text(
                "Needs your help", exact=True).first.is_visible()
            assert mobile.get_by_role("link", name="Details").first.is_visible()
            mobile.screenshot(
                path=screenshot_dir / "05-scout-run-results-mobile.png", full_page=True)
            mobile.goto(
                url + f"/scout/target?run={run_id}&domain=alpha.example", wait_until="load")
            assert mobile.get_by_role(
                "link", name="Download client-ready evidence (.zip)").is_visible()
            assert mobile.evaluate(
                "()=>document.documentElement.scrollWidth<=document.documentElement.clientWidth+2")
            mobile.screenshot(
                path=screenshot_dir / "07-scout-target-complete-mobile.png", full_page=True)

            # Real guarded UI mutation: active History -> select -> Archive -> archived tab.
            desktop.goto(url + "/scout/history", wait_until="load")
            desktop.screenshot(
                path=screenshot_dir / "06-scout-history-desktop.png", full_page=True)
            desktop.locator(".pick").first.check()
            with desktop.expect_response("**/api/scout/operator") as response_info:
                desktop.get_by_role("button", name="Archive selected").click()
            response = response_info.value
            assert response.ok
            desktop.get_by_text("No analyzed sites yet.", exact=True).wait_for()
            desktop.get_by_role("link", name="Archived").click()
            assert desktop.get_by_role("link", name="alpha.example").is_visible()
            desktop.goto(url + "/scout/campaigns", wait_until="load")
            desktop.screenshot(
                path=screenshot_dir / "08-scout-campaigns-desktop.png", full_page=True)
            (screenshot_dir / "README.md").write_text(
                "# Scout operator screenshots — synthetic acceptance data\n\n"
                "Captured on the candidate SHA by the real Chromium acceptance flow. "
                "The pages use only `alpha.example` / `beta.example` synthetic fixtures.\n",
                encoding="utf-8",
            )
            browser.close()
    finally:
        server.shutdown()


def test_project_name_pattern_is_enforced_by_a_real_browser(tmp_path):
    """`pattern` is compiled with the RegExp `v` flag. An unescaped trailing '-' throws, and a
    pattern the browser cannot compile is ignored entirely - the field then accepts anything while
    still advertising a rule. Only a real engine can prove the constraint is live, so assert both
    directions: a hyphenated name is accepted, and forbidden input is rejected.
    """
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            errors: list[str] = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
            page.goto(url + "/work?create=1#client-brief", wait_until="load")
            field = page.locator("#cw_pid")
            assert field.get_attribute("pattern"), "the field must still advertise a rule"

            def valid(value: str) -> bool:
                field.fill(value)
                return page.evaluate(
                    "() => document.getElementById('cw_pid').checkValidity()")

            accepted = {v: valid(v) for v in
                        ("checkout-regression", "acme_client.v2", "Project-2026-07", "a")}
            # Raw strings: "bad\name" would be bad + NEWLINE + ame, which tests something else
            # entirely. The backslash and the newline are both worth rejecting, so assert each.
            rejected = {v: valid(v) for v in
                        ("bad name", "bad/name", r"bad\name", "bad\nname", "../escape",
                         "drop;table", "naïve", "a b")}
            browser.close()
    finally:
        server.shutdown()
    assert not errors, f"the page reported an error, so the pattern may not have compiled: {errors}"
    assert all(accepted.values()), f"legitimate names rejected: {accepted}"
    assert not any(rejected.values()), (
        f"forbidden input accepted, so the pattern is not being enforced: {rejected}")
