"""The manual-check round trip an operator actually lives through.

A target blocked by a real challenge waits in "Needs your help" for as long as it takes; opening the
check re-walks that ONE target in a visible browser; solving it continues in the same session; and
when it finishes the target must stop asking for help. The last step is the one worth pinning: the
manual attempt writes its result into its OWN run, so nothing in the original run knows the target
was rescued unless we say so.
"""
from __future__ import annotations

import time

from core.scout.backends import PageObservation
from core.scout.challenge_session import ChallengeSessionManager
from core.scout.dashboard import start_dashboard
from core.scout.service import ScoutService
from core.scout.store import RunStore
from tests.scout_seam_fixtures import get

SOURCE_RUN = "campaign-original"
DOMAIN = "blocked.example"


class _WaitingBackend:
    """Blocks once, then serves a normal page after the operator chooses Continue."""
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


def _wait_state(manager, sid, wanted, timeout=5):
    end = time.time() + timeout
    while time.time() < end:
        item = manager.get(sid)
        if item and item["state"] in wanted:
            return item
        time.sleep(0.02)
    return manager.get(sid)


def _blocked_original_run(out: str) -> RunStore:
    """An earlier campaign that left this target waiting for a human."""
    store = RunStore(out, SOURCE_RUN)
    store.save_prospect_artifact("01-blocked", "manual_action.json", {
        "reason": "captcha_detected", "stage": "post_landing_precheck",
        "stop_boundary": "stopped_before_interaction", "chromium_started": True,
        "landing_loaded": False, "analysis_complete": False,
        "challenge_confidence": "confirmed", "challenge_signal": "HTTP 403 answered instead",
        "recommended_action": "Solve it yourself, then rescan."})
    store.save_state({"status": "COMPLETED", "finished_at": "2026-07-27T00:00:00+00:00",
                      "prospects": {
                          "01-blocked": {"status": "MANUAL_ACTION_REQUIRED",
                                         "url": f"https://{DOMAIN}/",
                                         "reason": "captcha_detected", "analysis_complete": False},
                          "02-other": {"status": "DONE", "url": "https://other.example/",
                                       "verified_findings": 2, "verified_defects": 1}}})
    return store


def _domains(manager) -> list:
    return [row["domain"] for row in manager.snapshot()["blocked_targets"]]


def test_blocked_target_waits_indefinitely_and_survives_a_restart(tmp_path):
    """Step 3: nothing expires while the operator is away -- not even across a process restart."""
    _blocked_original_run(str(tmp_path))

    assert DOMAIN in _domains(ChallengeSessionManager(str(tmp_path), resolve_dns=False))
    # A brand-new manager stands in for the Dashboard being restarted hours later.
    assert DOMAIN in _domains(ChallengeSessionManager(str(tmp_path), resolve_dns=False))


def test_solved_manual_check_clears_the_target_from_needs_your_help(tmp_path):
    """Step 8: once the operator has rescued it, the target must stop asking for help."""
    _blocked_original_run(str(tmp_path))
    manager = ChallengeSessionManager(str(tmp_path), wait_timeout_s=3, resolve_dns=False,
                                      backend_factory=lambda **kw: _WaitingBackend(**kw))
    assert DOMAIN in _domains(manager)

    item = manager.start(DOMAIN, source_run=SOURCE_RUN)
    _wait_state(manager, item["id"], {"waiting"})
    manager.signal(item["id"], "continue")
    done = _wait_state(manager, item["id"], {"completed", "failed", "deferred"})

    assert done["state"] == "completed"
    assert DOMAIN not in _domains(manager), (
        "the target was analysed successfully but still sits in Needs your help")


def test_the_rest_of_the_original_run_is_left_alone(tmp_path):
    """The rescue must not touch the sibling target's record, nor erase what was seen first."""
    store = _blocked_original_run(str(tmp_path))
    manager = ChallengeSessionManager(str(tmp_path), wait_timeout_s=3, resolve_dns=False,
                                      backend_factory=lambda **kw: _WaitingBackend(**kw))
    item = manager.start(DOMAIN, source_run=SOURCE_RUN)
    _wait_state(manager, item["id"], {"waiting"})
    manager.signal(item["id"], "continue")
    _wait_state(manager, item["id"], {"completed", "failed", "deferred"})

    state = store.load_state()
    assert state["prospects"]["02-other"]["status"] == "DONE"
    assert state["prospects"]["02-other"]["verified_findings"] == 2
    # The original blockage stays on the record: it really happened.
    assert store.load_prospect_artifact("01-blocked", "manual_action.json")["reason"] == \
        "captcha_detected"
    assert state["prospects"]["01-blocked"].get("analysis_complete") is not True


def test_the_original_run_page_stops_asking_for_help_and_points_at_the_result(tmp_path):
    """The list and the target page must tell the same story: rescued, result is over there."""
    _blocked_original_run(str(tmp_path))
    manager = ChallengeSessionManager(str(tmp_path), wait_timeout_s=3, resolve_dns=False,
                                      backend_factory=lambda **kw: _WaitingBackend(**kw))
    item = manager.start(DOMAIN, source_run=SOURCE_RUN)
    _wait_state(manager, item["id"], {"waiting"})
    manager.signal(item["id"], "continue")
    _wait_state(manager, item["id"], {"completed", "failed", "deferred"})

    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        html = get(f"{url}/scout/target?run={SOURCE_RUN}&domain={DOMAIN}")[1]
    finally:
        server.shutdown()

    assert "Open manual check" not in html          # nothing left to solve
    assert "Needs your help" not in html
    assert "Resolved by a manual check" in html
    assert f'run={item["result_run"]}' in html      # and the result is one click away


def test_a_timed_out_check_can_be_retried_and_the_target_stays_listed(tmp_path):
    """Steps 3 + the timeout rule: giving up on one attempt costs the operator nothing."""
    _blocked_original_run(str(tmp_path))
    manager = ChallengeSessionManager(str(tmp_path), wait_timeout_s=0.4, resolve_dns=False,
                                      backend_factory=lambda **kw: _WaitingBackend(**kw))

    first = manager.start(DOMAIN, source_run=SOURCE_RUN)
    timed_out = _wait_state(manager, first["id"], {"timed_out", "deferred", "failed"})
    assert timed_out["state"] in ("timed_out", "deferred")
    assert DOMAIN in _domains(manager)              # still waiting for a human

    second = manager.start(DOMAIN, source_run=SOURCE_RUN)
    assert second["id"] != first["id"]              # a terminal attempt never blocks the next one
    _wait_state(manager, second["id"], {"waiting"})
    manager.signal(second["id"], "continue")
    done = _wait_state(manager, second["id"], {"completed", "failed", "deferred"})
    assert done["state"] == "completed"
    assert DOMAIN not in _domains(manager)
