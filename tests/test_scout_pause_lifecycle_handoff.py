"""Pausing a campaign must pause it — not kill it, and not lose the pause.

Regression found by the acceptance re-run on 092e5dc3eba5 (checkpoint `5159632764`). The worker
runs its lifecycle back to back:

    rc.advance(TRIAGING)
    rc.advance(ANALYZING)

If the operator's Pause lands between those two, the state is PAUSING, and PAUSING -> ANALYZING is
not a legal transition, so the run failed with
``RunControlError: invalid transition 'pausing' -> 'analyzing'``.

Before PR #70 the same sequence "worked" only because ``advance()`` validated against the worker's
stale snapshot — and that same write erased the pause. So the two wrong outcomes are the two sides
of one missing handoff: the lifecycle steps never yielded to a pending control the way the engine's
own progress callback already does.
"""
from __future__ import annotations

import threading

from core.scout.campaign_service import CampaignService
from core.scout.run_control import (
    ANALYZING,
    DISCOVERING,
    PAUSED,
    TRIAGING,
    CampaignRunControl,
    Checkpoint,
)

_RESULTS = [{"url": "https://acme-saas.com", "title": "Acme", "content": "b2b saas pricing"}]


def _pause_between_lifecycle_steps(tmp_path, monkeypatch, *, resume_after_s=0.6):
    """Force the exact window: pause immediately after the worker reaches TRIAGING.

    The interleaving is deterministic — everything else is the real production sequence.
    """
    timers: list = []
    fired: list = []

    # The lifecycle step is the seam, so the pause lands squarely between the two. Which method
    # IS that step differs across the trees this regression test has to run on: the fixed one
    # decides atomically in `begin_phase`, the one that failed advanced through `advance`. Binding
    # to whichever exists keeps the revert-proof meaningful — patching a name the old tree does
    # not have would fail on setup and prove nothing.
    atomic = hasattr(CampaignRunControl, "begin_phase")
    seam = "begin_phase" if atomic else "advance"
    real_step = getattr(CampaignRunControl, seam)

    def step_then_pause(self, target):
        outcome = real_step(self, target)
        if target == TRIAGING and not fired and (outcome == "advanced" or not atomic):
            fired.append(True)
            cid, out = self.campaign_id, str(tmp_path)
            CampaignRunControl(cid, out).request_pause()
            t = threading.Timer(resume_after_s,
                                lambda: CampaignRunControl(cid, out).resume())
            t.start()
            timers.append(t)
        return outcome

    monkeypatch.setattr(CampaignRunControl, seam, step_then_pause)
    return fired, timers


def _spy_transitions(monkeypatch):
    seen: list = []
    real = CampaignRunControl._transition

    def spy(self, target):
        real(self, target)
        seen.append(target)

    monkeypatch.setattr(CampaignRunControl, "_transition", spy)
    return seen


def test_a_pause_between_lifecycle_steps_does_not_fail_the_run(tmp_path, monkeypatch):
    """The exact window from the acceptance: TRIAGING -> Pause -> ANALYZING."""
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-TESTKEY")
    fired, timers = _pause_between_lifecycle_steps(tmp_path, monkeypatch)

    svc = CampaignService(output_dir=str(tmp_path))
    res = svc.launch(campaign_preset="safe-live-acceptance", approve_live_discovery=True,
                     transport=lambda body, key: {"results": _RESULTS},
                     overrides={"browser_mode": "static"},
                     background=False, resolve_dns=False)
    for t in timers:
        t.join()

    assert fired, "the pause was never injected — the test proves nothing"
    prog = svc.progress(res["campaign_id"])
    assert str(prog["run_state"]).lower() != "failed", prog.get("stop_reason")
    assert "invalid transition" not in str(prog.get("stop_reason") or "")


def test_pause_then_resume_completes_the_run_without_discovering_again(tmp_path, monkeypatch):
    """Pause -> Resume -> normal completion, and discovery must not run a second time."""
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-TESTKEY")
    seen = _spy_transitions(monkeypatch)
    fired, timers = _pause_between_lifecycle_steps(tmp_path, monkeypatch)

    svc = CampaignService(output_dir=str(tmp_path))
    res = svc.launch(campaign_preset="safe-live-acceptance", approve_live_discovery=True,
                     transport=lambda body, key: {"results": _RESULTS},
                     overrides={"browser_mode": "static"},
                     background=False, resolve_dns=False)
    for t in timers:
        t.join()

    assert fired
    prog = svc.progress(res["campaign_id"])
    assert str(prog["run_state"]).lower() == "completed", prog.get("stop_reason")
    assert prog["stop_reason"], "a completed run must still say why it stopped"

    assert seen.count(DISCOVERING) == 1, \
        f"discovery must not run again after a resume, transitions seen: {seen}"
    assert ANALYZING in seen


def test_a_pause_landing_after_the_control_check_still_cannot_fail_the_run(tmp_path, monkeypatch):
    """The TOCTOU window: the Pause is written AFTER the controls read clear, BEFORE the advance.

    A separate thread plays the operator, because that is the only faithful way to test it — the
    guarantee is that a concurrent writer either gets there first or waits, and a same-thread
    injection would re-enter this campaign's lock and defeat the very thing under test.

    On the production code that only re-read before advancing, the pause lands in the gap and the
    phase step meets PAUSING, producing `invalid transition 'pausing' -> ...` and a FAILED run.
    """
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-TESTKEY")
    fired: list = []
    timers: list = []
    real_should_pause = CampaignRunControl.should_pause

    def pause_lands_in_the_gap(self):
        clear = real_should_pause(self)
        if not clear and not fired:
            fired.append(True)
            cid, out = self.campaign_id, str(tmp_path)
            operator = threading.Thread(
                target=lambda: CampaignRunControl(cid, out).request_pause())
            operator.start()
            # Wait for the operator's write to become durable. Where the decision is NOT atomic
            # this returns quickly and the pause is on disk before the advance; where it IS, the
            # operator is blocked on the lock and this simply times out — which is the point.
            operator.join(timeout=2.0)
            # The correct outcome is that the run PARKS on that pause at the next phase boundary,
            # so something has to release it or the worker waits out `wait_until_resumed`.
            t = threading.Timer(1.5, lambda: CampaignRunControl(cid, out).resume())
            t.start()
            timers.append(t)
        return clear

    monkeypatch.setattr(CampaignRunControl, "should_pause", pause_lands_in_the_gap)

    svc = CampaignService(output_dir=str(tmp_path))
    res = svc.launch(campaign_preset="safe-live-acceptance", approve_live_discovery=True,
                     transport=lambda body, key: {"results": _RESULTS},
                     overrides={"browser_mode": "static"},
                     background=False, resolve_dns=False)

    for t in timers:
        t.join()

    assert fired, "the pause was never injected into the gap — the test proves nothing"
    prog = svc.progress(res["campaign_id"])
    assert "invalid transition" not in str(prog.get("stop_reason") or "")
    assert str(prog["run_state"]).lower() != "failed", prog.get("stop_reason")


def test_a_stop_saved_while_the_worker_is_about_to_park_wins_and_does_not_fail(tmp_path,
                                                                              monkeypatch):
    """Pause noticed, then Stop & Save completes before the worker parks.

    Reporting "paused" and parking as a second mutation would let the Stop land in between, and
    the park would then attempt STOPPED_CHECKPOINT -> PAUSED — illegal, so the orderly stop became
    a FAILED run. The already-written Stop must win outright: no PAUSED, no exception, no failure.
    """
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-TESTKEY")
    fired: list = []
    seen = _spy_transitions(monkeypatch)
    real_begin = CampaignRunControl.begin_phase

    def stop_lands_before_the_park(self, target):
        if target == ANALYZING and not fired:
            fired.append(True)
            cid, out = self.campaign_id, str(tmp_path)
            operator = CampaignRunControl(cid, out)
            operator.request_pause()                      # the worker is about to notice this...
            operator.stop_and_save(Checkpoint())          # ...but Stop & Save completes first
        return real_begin(self, target)

    monkeypatch.setattr(CampaignRunControl, "begin_phase", stop_lands_before_the_park)

    svc = CampaignService(output_dir=str(tmp_path))
    res = svc.launch(campaign_preset="safe-live-acceptance", approve_live_discovery=True,
                     transport=lambda body, key: {"results": _RESULTS},
                     overrides={"browser_mode": "static"},
                     background=False, resolve_dns=False)

    assert fired, "the stop was never injected — the test proves nothing"
    prog = svc.progress(res["campaign_id"])
    assert str(prog["run_state"]).lower() == "stopped_with_checkpoint", prog.get("stop_reason")
    assert "invalid transition" not in str(prog.get("stop_reason") or "")
    assert PAUSED not in seen, f"a written Stop must not be overtaken by a park: {seen}"


def test_the_operator_pause_is_still_recorded_while_the_worker_advances(tmp_path, monkeypatch):
    """The fix must not restore the old behaviour of quietly dropping the control.

    Guards the PR #70 guarantee from the other direction: honouring the pause is not allowed to
    become 'ignore the pause and carry on'.
    """
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-TESTKEY")
    observed: list = []

    real_wait = CampaignRunControl.wait_until_resumed

    def record_then_wait(self, *a, **kw):
        fresh = CampaignRunControl(self.campaign_id, str(tmp_path))
        observed.append((fresh.state.state, fresh.state.requested_control))
        return real_wait(self, *a, **kw)

    monkeypatch.setattr(CampaignRunControl, "wait_until_resumed", record_then_wait)
    fired, timers = _pause_between_lifecycle_steps(tmp_path, monkeypatch)

    svc = CampaignService(output_dir=str(tmp_path))
    svc.launch(campaign_preset="safe-live-acceptance", approve_live_discovery=True,
               transport=lambda body, key: {"results": _RESULTS},
               overrides={"browser_mode": "static"},
               background=False, resolve_dns=False)
    for t in timers:
        t.join()

    assert fired
    assert observed, "the worker never parked on the operator's pause"
    assert observed[0][0] == "paused", f"the run must be persisted as paused, saw {observed[0]}"
