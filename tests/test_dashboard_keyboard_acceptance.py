"""Real-keyboard acceptance for the operator Dashboard shell.

axe cannot see these: it audits the rendered tree, not what actually happens when an operator
presses Tab or Escape. Each test below drives real key events in Chromium.
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright", reason="playwright not installed")

from playwright.sync_api import sync_playwright  # noqa: E402

from core.scout.dashboard import start_dashboard  # noqa: E402
from core.scout.service import ScoutService  # noqa: E402


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

_HIDDEN_MENU_ITEMS = {"Activity", "Collaboration", "Settings", "Help"}


def test_collapsed_more_menu_is_not_in_the_tab_order(tmp_path):
    """A collapsed menu must never place invisible stops in the tab order.

    The menu is an absolutely-positioned child of a closed <details>, and those links DO still
    report a layout box - static inspection therefore suggests a keyboard defect. A real Tab walk
    shows the browser already skips them, so no fix is warranted; this test pins that invariant so
    a future change (e.g. replacing <details> with a JS-toggled div) cannot regress it silently.
    """
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url + "/", wait_until="load")
            assert page.evaluate("() => document.querySelector('header details').open") is False
            visited = []
            page.evaluate("() => document.querySelector('header a').focus()")
            for _ in range(10):
                visited.append(page.evaluate(
                    "() => (document.activeElement.textContent || '').trim()"))
                page.keyboard.press("Tab")
            browser.close()
    finally:
        server.shutdown()
    leaked = _HIDDEN_MENU_ITEMS.intersection(visited)
    assert not leaked, f"tab order stops on links inside the collapsed More menu: {sorted(leaked)}"


def test_more_menu_items_become_reachable_once_opened(tmp_path):
    """Hiding the collapsed menu must not make the destinations unreachable by keyboard."""
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url + "/", wait_until="load")
            page.get_by_role("group").get_by_text("More").click()
            assert page.evaluate("() => document.querySelector('header details').open") is True
            reachable = page.evaluate(
                "() => [...document.querySelectorAll('header .nav-menu a')]"
                ".filter(a => a.offsetParent !== null).map(a => a.textContent.trim())")
            browser.close()
    finally:
        server.shutdown()
    assert _HIDDEN_MENU_ITEMS.issubset(set(reachable)), reachable


def test_confirm_dialog_closes_on_escape_without_running_the_action(tmp_path):
    """Escape must dismiss the guarded confirmation and leave the lifecycle untouched."""
    ark = tmp_path / "prepared" / "40_ark_work"
    ark.mkdir(parents=True)
    (ark / "WORK_PACKET.json").write_text('{"title": "Prepared project"}', encoding="utf-8")
    (ark / "WORK_RUN_STATE.json").write_text(
        '{"status": "DELIVERY_PREPARED", "updated_at": "2026-07-24T10:00:00Z", "history": []}',
        encoding="utf-8")
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url + "/work/prepared", wait_until="load")
            page.get_by_role("button", name="Mark Delivered (I sent it)").click()
            assert page.evaluate("() => document.getElementById('qa-confirm').open") is True
            page.keyboard.press("Escape")
            page.wait_for_timeout(300)
            assert page.evaluate("() => document.getElementById('qa-confirm').open") is False
            page.wait_for_timeout(700)
            status = page.evaluate(
                "async () => (await (await fetch('/api/work/prepared')).json()).summary.status")
            browser.close()
    finally:
        server.shutdown()
    assert status == "DELIVERY_PREPARED", "Escape must cancel, never perform, the guarded action"
