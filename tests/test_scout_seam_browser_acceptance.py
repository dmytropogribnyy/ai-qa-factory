"""Scout seam — the actions on the run and target surfaces must actually execute.

A rendered button proves nothing: PR #49 shipped two confirm-buttons whose onclick threw a
SyntaxError and did nothing at all. These checks click for real.
"""
from __future__ import annotations

import pytest

pytest.importorskip("playwright")
from playwright.sync_api import sync_playwright  # noqa: E402

from core.scout.dashboard import start_dashboard  # noqa: E402
from core.scout.service import ScoutService  # noqa: E402
from tests.scout_seam_fixtures import RUN_A, RUN_ARCHIVED, build_seam_stand  # noqa: E402


def _expand_run_administration(page) -> None:
    """The Archive/Restore controls live inside the "Run administration" <details>, which is
    closed by default (see tests/test_v31_dashboard_browser_acceptance.py:579 and commit
    d827faf4) — a real operator must click the summary to reveal them before they can act."""
    page.locator("summary", has_text="Run administration").click()


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


def test_every_details_link_on_the_run_page_opens_its_own_target(tmp_path):
    build_seam_stand(str(tmp_path))
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"{url}/scout/run?id={RUN_A}", wait_until="load")

            domains = page.eval_on_selector_all(
                'td[data-label="Target"]', "els => els.map(e => e.textContent.trim())")
            assert domains, "no target rows rendered"

            for domain in domains:
                page.goto(f"{url}/scout/run?id={RUN_A}", wait_until="load")
                row = page.locator("tr", has_text=domain).first
                row.get_by_role("link", name="Details").click()
                page.wait_for_load_state("load")
                assert domain in page.locator("h1").inner_text()
            assert errors == [], f"JavaScript errors on the run/target path: {errors}"
            browser.close()
    finally:
        server.shutdown()


def test_archive_and_restore_actually_change_the_run(tmp_path):
    build_seam_stand(str(tmp_path))
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("dialog", lambda d: d.accept())

            page.goto(f"{url}/scout/run?id={RUN_A}", wait_until="load")
            _expand_run_administration(page)
            # runAction() reloads asynchronously (fetch().then(location.reload)); expect_navigation
            # is armed before the click so it observes that reload instead of racing a later goto().
            with page.expect_navigation(wait_until="load"):
                page.get_by_role("button", name="Archive run").click()
            page.goto(f"{url}/scout/run?id={RUN_A}", wait_until="load")
            assert "archived" in page.content().lower()
            _expand_run_administration(page)
            assert page.get_by_role("button", name="Restore run").count() == 1

            with page.expect_navigation(wait_until="load"):
                page.get_by_role("button", name="Restore run").click()
            page.goto(f"{url}/scout/run?id={RUN_A}", wait_until="load")
            _expand_run_administration(page)
            assert page.get_by_role("button", name="Archive run").count() == 1
            assert errors == [], f"JavaScript errors on the archive path: {errors}"
            browser.close()
    finally:
        server.shutdown()


def test_archived_run_page_warns_and_offers_restore(tmp_path):
    build_seam_stand(str(tmp_path))
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(f"{url}/scout/run?id={RUN_ARCHIVED}", wait_until="load")
            assert "hidden from normal operator lists" in page.content()
            _expand_run_administration(page)
            assert page.get_by_role("button", name="Restore run").count() == 1
            browser.close()
    finally:
        server.shutdown()


def test_a_partial_bulk_result_keeps_the_operator_on_the_page_with_the_reason(tmp_path):
    """The client half of the bulk-feedback fix, which server-rendered tests cannot reach.

    A clean success reloads, because the reloaded page carries the persistent banner and marker. A
    partial result must NOT reload: the refusal is not persisted anywhere, so a reload would erase
    the only account of it and the operator would be told nothing at all.
    """
    build_seam_stand(str(tmp_path))
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"{url}/scout/run?id={RUN_A}", wait_until="load")

            # alpha is DONE and cannot be skipped; delta is queued and can be.
            for domain in ("alpha.example", "delta.example"):
                page.locator("tr", has_text=domain).first.locator("input.pick").check()
            page.get_by_role("button", name="Skip queued").click()
            page.wait_for_function(
                "() => (document.getElementById('bulkmsg')||{}).textContent.trim().length > 0")

            message = page.locator("#bulkmsg").inner_text()
            assert "refused" in message, f"the refusal was not reported: {message!r}"
            assert "01-alpha" in message, f"the refused target is not named: {message!r}"
            # Still on the same page: the message was not erased by a reload.
            assert page.locator("#bulkmsg").is_visible()
            assert errors == [], f"JavaScript errors during the bulk action: {errors}"
            browser.close()
    finally:
        server.shutdown()


def test_a_clean_bulk_success_reloads_into_the_persistent_confirmation(tmp_path):
    """With nothing refused there is nothing transient to preserve, so the page reloads and the
    operator sees the banner and the row marker that survive any later refresh."""
    build_seam_stand(str(tmp_path))
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            errors = []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(f"{url}/scout/run?id={RUN_A}", wait_until="load")

            page.locator("tr", has_text="delta.example").first.locator("input.pick").check()
            with page.expect_navigation(wait_until="load"):
                page.get_by_role("button", name="Skip queued").click()

            assert "will not start" in page.content()
            row = page.locator("tr", has_text="delta.example").first
            assert "Skip requested" in row.inner_text()
            assert errors == [], f"JavaScript errors during the bulk action: {errors}"
            browser.close()
    finally:
        server.shutdown()

