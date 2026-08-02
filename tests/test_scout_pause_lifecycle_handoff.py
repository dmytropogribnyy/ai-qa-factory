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
    TRIAGING,
    CampaignRunControl,
)

_RESULTS = [{"url": "https://acme-saas.com", "title": "Acme", "content": "b2b saas pricing"}]


def _pause_between_lifecycle_steps(tmp_path, monkeypatch, *, resume_after_s=0.6):
    """Force the exact window: pause immediately after the worker reaches TRIAGING.

    The interleaving is deterministic — everything else is the real production sequence.
    """
    timers: list = []
    real_advance = CampaignRunControl.advance
    fired: list = []

    def advance_then_pause(self, target):
        real_advance(self, target)
        if target == TRIAGING and not fired:
            fired.append(True)
            CampaignRunControl(self.campaign_id, str(tmp_path)).request_pause()
            t = threading.Timer(
                resume_after_s,
                lambda: CampaignRunControl(self.campaign_id, str(tmp_path)).resume())
            t.start()
            timers.append(t)

    monkeypatch.setattr(CampaignRunControl, "advance", advance_then_pause)
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
               background=False, resolve_dns=False)
    for t in timers:
        t.join()

    assert fired
    assert observed, "the worker never parked on the operator's pause"
    assert observed[0][0] == "paused", f"the run must be persisted as paused, saw {observed[0]}"
