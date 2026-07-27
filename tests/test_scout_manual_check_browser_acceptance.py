"""Real-browser acceptance for the manual-check round trip.

The deterministic tests pin the state machine; this one pins what the operator actually sees in a
browser at each stop: a blocked target that keeps waiting however long they are away, the manual
check offered on it, and — after a check has carried it to a result — a page that no longer asks for
help and links to where the findings live.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright  # noqa: E402

from core.scout.backends import PageObservation  # noqa: E402
from core.scout.challenge_session import ChallengeSessionManager  # noqa: E402
from core.scout.dashboard import start_dashboard  # noqa: E402
from core.scout.service import ScoutService  # noqa: E402
from core.scout.store import RunStore  # noqa: E402

SOURCE_RUN = "campaign-manual-browser"
DOMAIN = "blocked.example"


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


class _WaitingBackend:
    name = "playwright"
    screenshot_dir = None
    screenshot_filename = "landing.png"

    def __init__(self, *, manual_gate, **_kwargs):
        self.manual_gate = manual_gate
        self.cleared = False

    def observe(self, url, _timeout_s, _max_bytes, *, record_video=False, deep_qa=False):
        if not self.cleared:
            blocked = PageObservation(url=url, final_url=url, status=403, ok=False,
                                      backend="playwright", captcha_marker=True,
                                      challenge_kind="blocking", challenge_confidence="confirmed",
                                      headings=[{"level": 1, "text": "Verify"}])
            if self.manual_gate(None, blocked) != "continue":
                return blocked
            self.cleared = True
        return PageObservation(url=url, final_url=url, status=200, ok=True,
                               backend="playwright", title="Ready", meta_description="Ready",
                               has_viewport_meta=True, headings=[{"level": 1, "text": "Ready"}],
                               landmarks={"main": 1}, axe_status="ok")


def _blocked_run(out: str) -> None:
    store = RunStore(out, SOURCE_RUN)
    store.save_prospect_artifact("01-blocked", "manual_action.json", {
        "reason": "captcha_detected", "stage": "post_landing_precheck",
        "stop_boundary": "stopped_before_interaction", "chromium_started": True,
        "landing_loaded": False, "analysis_complete": False,
        "challenge_confidence": "confirmed",
        "challenge_signal": "HTTP 403 answered instead of the page",
        "recommended_action": "Solve it yourself in a browser, then rescan."})
    store.save_state({"status": "COMPLETED", "finished_at": "2026-07-27T00:00:00+00:00",
                      "prospects": {"01-blocked": {
                          "status": "MANUAL_ACTION_REQUIRED", "url": f"https://{DOMAIN}/",
                          "reason": "captcha_detected", "analysis_complete": False}}})


def _wait_state(manager, sid, wanted, timeout=6):
    end = time.time() + timeout
    while time.time() < end:
        item = manager.get(sid)
        if item and item["state"] in wanted:
            return item
        time.sleep(0.02)
    return manager.get(sid)


def test_operator_sees_the_manual_check_then_the_result_it_produced(tmp_path):
    _blocked_run(str(tmp_path))
    target = f"/scout/target?run={SOURCE_RUN}&domain={DOMAIN}"
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1280, "height": 900})

            # Before: the target is waiting, and the check is offered on it.
            page.goto(url + target, wait_until="load")
            assert page.get_by_role("button", name="Open manual check").is_visible()
            assert page.get_by_text("human verification check", exact=False).is_visible()
            assert page.get_by_text("Needs your help", exact=False).first.is_visible()

            # The queue lists it, and keeps listing it however long the operator is away.
            page.goto(url + "/scout/attention", wait_until="load")
            assert page.get_by_text(DOMAIN, exact=False).first.is_visible()

            # The operator opens the check and completes the manual step.
            manager = ChallengeSessionManager(str(tmp_path), wait_timeout_s=6, resolve_dns=False,
                                              backend_factory=lambda **kw: _WaitingBackend(**kw))
            item = manager.start(DOMAIN, source_run=SOURCE_RUN)
            _wait_state(manager, item["id"], {"waiting"})
            manager.signal(item["id"], "continue")
            done = _wait_state(manager, item["id"], {"completed", "failed", "deferred"})
            assert done["state"] == "completed"

            # After: the same page no longer asks for help and points at the result.
            page.goto(url + target, wait_until="load")
            assert page.get_by_text("Resolved by a manual check", exact=False).first.is_visible()
            assert page.get_by_role("button", name="Open manual check").count() == 0
            result_link = page.get_by_role("link", name="Open the result")
            assert result_link.is_visible()
            result_link.click()
            page.wait_for_load_state("load")
            assert item["result_run"] in page.url

            browser.close()
    finally:
        server.shutdown()
