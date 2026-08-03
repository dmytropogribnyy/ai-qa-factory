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

from core.scout import campaign_service as campaign_service_module
from core.scout.campaign_service import CampaignService
from core.scout.run_control import (
    ANALYZING,
    COMPLETED,
    DISCOVERING,
    PAUSED,
    STOPPED_CHECKPOINT,
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


def test_pause_parking_is_durable_before_a_concurrent_stop_can_win(tmp_path, monkeypatch):
    """Once Pause wins the phase decision, its PAUSED write stays inside that same lock hold.

    The operator thread starts Stop precisely when the worker is about to transition to PAUSED.
    It must block until PAUSED is durable; only then may it record STOPPED_CHECKPOINT. Moving the
    park back outside ``begin_phase`` reverses those writes (or raises on STOPPED -> PAUSED).
    """
    rc = CampaignRunControl("c1", str(tmp_path))
    rc.run_now()
    rc.advance(TRIAGING)
    rc.advance(ANALYZING)
    rc.request_pause()

    about_to_park = threading.Event()
    stop_started = threading.Event()
    stop_finished = threading.Event()
    operator_errors: list[BaseException] = []
    saved_states: list[str] = []
    real_transition = CampaignRunControl._transition
    real_save = CampaignRunControl._save

    def gate_the_park(self, target):
        if target == PAUSED and not about_to_park.is_set():
            about_to_park.set()
            assert stop_started.wait(1.0), "the concurrent Stop thread never started"
            assert not stop_finished.wait(0.1), \
                "Stop persisted before the worker's atomic Pause decision was parked"
        return real_transition(self, target)

    def record_save(self):
        real_save(self)
        saved_states.append(self.state.state)

    monkeypatch.setattr(CampaignRunControl, "_transition", gate_the_park)
    monkeypatch.setattr(CampaignRunControl, "_save", record_save)

    def stop_concurrently():
        try:
            assert about_to_park.wait(1.0), "the worker never reached the parking write"
            stop_started.set()
            CampaignRunControl("c1", str(tmp_path)).stop_and_save(Checkpoint())
        except BaseException as exc:  # captured for an assertion in the owning test thread
            operator_errors.append(exc)
        finally:
            stop_finished.set()

    operator = threading.Thread(target=stop_concurrently)
    operator.start()
    outcome = rc.begin_phase(ANALYZING)
    operator.join(timeout=2.0)

    assert not operator.is_alive(), "the concurrent Stop thread did not finish"
    assert not operator_errors, operator_errors
    assert outcome == "paused"
    assert saved_states[:2] == [PAUSED, STOPPED_CHECKPOINT], saved_states
    assert CampaignRunControl("c1", str(tmp_path)).state.state == STOPPED_CHECKPOINT


def _install_fast_finished_engine(monkeypatch):
    """Keep finalization interleavings focused: no provider, browser or real discovery work."""
    class FinishedEngine:
        def __init__(self, *_args, **_kwargs):
            pass

        def run(self):
            return {"stop_reason": "completed", "candidates": []}

    monkeypatch.setattr(campaign_service_module, "DiscoveryEngine", FinishedEngine)
    monkeypatch.setattr(campaign_service_module, "build_tavily_registry",
                        lambda **_kwargs: (None, object()))


def test_pause_between_engine_finish_and_completion_parks_then_completes(tmp_path, monkeypatch):
    """A Pause in the final handoff must park, resume and complete — never become FAILED."""
    _install_fast_finished_engine(monkeypatch)
    observed: list[tuple[str, str]] = []
    svc = CampaignService(output_dir=str(tmp_path))

    def pause_before_completion(cfg, _state):
        CampaignRunControl(cfg.campaign_id, str(tmp_path)).request_pause()

    def resume_after_observing_park(self, *_args, **_kwargs):
        fresh = CampaignRunControl(self.campaign_id, str(tmp_path))
        observed.append((fresh.state.state, fresh.state.requested_control))
        fresh.resume()

    monkeypatch.setattr(svc, "_persist_brain", pause_before_completion)
    monkeypatch.setattr(CampaignRunControl, "wait_until_resumed", resume_after_observing_park)

    res = svc.launch(campaign_preset="safe-live-acceptance", approve_live_discovery=True,
                     transport=lambda body, key: {"results": _RESULTS},
                     overrides={"browser_mode": "static"},
                     background=False, resolve_dns=False)

    final = CampaignRunControl(res["campaign_id"], str(tmp_path)).state
    assert observed == [(PAUSED, "")], observed
    assert final.state == COMPLETED, final.stop_reason
    assert "invalid transition" not in final.stop_reason


def test_stop_between_engine_finish_and_completion_remains_stopped(tmp_path, monkeypatch):
    """A durable Stop in the final handoff wins without a repeat transition or worker traceback."""
    _install_fast_finished_engine(monkeypatch)
    svc = CampaignService(output_dir=str(tmp_path))

    def stop_before_completion(cfg, _state):
        CampaignRunControl(cfg.campaign_id, str(tmp_path)).stop_and_save(
            Checkpoint(completed=["acme-saas.com"]))

    monkeypatch.setattr(svc, "_persist_brain", stop_before_completion)

    res = svc.launch(campaign_preset="safe-live-acceptance", approve_live_discovery=True,
                     transport=lambda body, key: {"results": _RESULTS},
                     overrides={"browser_mode": "static"},
                     background=False, resolve_dns=False)

    final = CampaignRunControl(res["campaign_id"], str(tmp_path)).state
    assert final.state == STOPPED_CHECKPOINT, final.stop_reason
    assert final.checkpoint.completed == ["acme-saas.com"]
    assert "invalid transition" not in final.stop_reason


def test_stop_after_a_progress_pause_decision_cannot_overtake_parking(tmp_path, monkeypatch):
    """The engine-event boundary needs the same atomic decision/parking contract as phases.

    The fake engine first records Pause, then emits one real progress callback. Stop starts only
    after that callback has observed the Pause. On a split ``reload/check -> enter_paused`` path it
    reaches disk first and the worker attempts STOPPED_CHECKPOINT -> PAUSED. With one boundary lock,
    Stop waits until PAUSED is durable and then wins normally.
    """
    operator_threads: list[threading.Thread] = []
    operator_errors: list[BaseException] = []
    fired: list[bool] = []
    saved_states: list[str] = []
    real_should_pause = CampaignRunControl.should_pause
    real_save = CampaignRunControl._save

    class OneBoundaryEngine:
        def __init__(self, cfg, _registry, _store, *, progress=None, **_kwargs):
            self.campaign_id = cfg.campaign_id
            self.progress = progress

        def run(self):
            CampaignRunControl(self.campaign_id, str(tmp_path)).request_pause()
            self.progress({"event": "candidate_scored", "candidate": "acme-saas.com"})
            return {"stop_reason": "completed", "candidates": []}

    def record_save(self):
        real_save(self)
        saved_states.append(self.state.state)

    def stop_after_true_pause_decision(self):
        decision = real_should_pause(self)
        if decision and not fired:
            fired.append(True)

            def stop():
                try:
                    CampaignRunControl(self.campaign_id, str(tmp_path)).stop_and_save(
                        Checkpoint(completed=["acme-saas.com"]))
                except BaseException as exc:  # surfaced in the owning test thread below
                    operator_errors.append(exc)

            operator = threading.Thread(target=stop)
            operator.start()
            operator.join(timeout=0.2)
            operator_threads.append(operator)
        return decision

    monkeypatch.setattr(campaign_service_module, "DiscoveryEngine", OneBoundaryEngine)
    monkeypatch.setattr(campaign_service_module, "build_tavily_registry",
                        lambda **_kwargs: (None, object()))
    monkeypatch.setattr(CampaignRunControl, "_save", record_save)
    monkeypatch.setattr(CampaignRunControl, "should_pause", stop_after_true_pause_decision)

    svc = CampaignService(output_dir=str(tmp_path))
    res = svc.launch(campaign_preset="safe-live-acceptance", approve_live_discovery=True,
                     transport=lambda body, key: {"results": _RESULTS},
                     overrides={"browser_mode": "static"},
                     background=False, resolve_dns=False)
    for operator in operator_threads:
        operator.join(timeout=2.0)

    assert fired, "the callback never observed Pause — the interleaving was not exercised"
    assert all(not operator.is_alive() for operator in operator_threads)
    assert not operator_errors, operator_errors
    paused_at = saved_states.index(PAUSED)
    stopped_at = saved_states.index(STOPPED_CHECKPOINT)
    assert paused_at < stopped_at, saved_states
    final = CampaignRunControl(res["campaign_id"], str(tmp_path)).state
    assert final.state == STOPPED_CHECKPOINT, final.stop_reason
    assert final.checkpoint.completed == ["acme-saas.com"]
    assert "invalid transition" not in final.stop_reason
