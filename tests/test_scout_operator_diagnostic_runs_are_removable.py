"""M2 — an operator's diagnostic action must not create data the product refuses to delete.

Two Dashboard buttons start a bounded one-target run for the operator's own benefit: "Watch headed
replay" and the manual CAPTCHA check. Neither is client work. Both built their ``ScoutRunConfig``
without ``run_purpose``, so the dataclass default ``PURPOSE_PRODUCTION`` was persisted — and then the
trap closed from both sides: Data management refuses to trash production ("this is production data")
and separately refuses to relabel a run that already declared a purpose ("re-labelling something to
make it deletable is not a cleanup step"). Both refusals are **correct**. The defect is upstream: the
run declared the wrong thing about itself, so every press of a diagnostic button left a permanent row
in the Production tile with no product path to remove it.

The fix is that each site declares what it actually is — ``diagnostic`` for the replay,
``manual_test`` for the challenge check. Both are in ``REMOVABLE_PURPOSES``, so the ordinary staged
preview → trash → confirm flow applies.

Neither test restates what the production code does. The manual check is driven end to end through
the ``backend_factory`` seam; the replay asserts on ``dashboard.headed_replay_config``, the factory
the handler itself calls. An earlier draft of this file rebuilt the replay config inline and stayed
green while the handler still declared production — testing its own copy, which is the failure mode
this whole blocker is about.

This does **not** relax ``resolve_requested_purpose``: that gate refuses a purpose arriving in an HTTP request,
because a request cannot mark its own data disposable. Here the purpose is a constant chosen
server-side per call site and read from nothing. The last test pins that distinction so a future
change cannot quietly turn the constant into a request-supplied value.
"""
from __future__ import annotations

import time

from core.scout.backends import PageObservation
from core.scout.challenge_session import ChallengeSessionManager
from core.scout.config import ScoutRunConfig
from core.scout.dashboard import headed_replay_config
from core.scout.data_management import DataManagementStore
from core.scout.run_purpose import (PURPOSE_DIAGNOSTIC, PURPOSE_MANUAL_TEST, PURPOSE_PRODUCTION,
                                    REMOVABLE_PURPOSES, RunPurposeIndex)
from core.scout.store import RunStore

DOMAIN = "blocked.example"
SOURCE_RUN = "campaign-original"


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
        return PageObservation(url=url, final_url=url, status=200, ok=True, backend="playwright",
                               title="Ready", meta_description="Ready", has_viewport_meta=True,
                               headings=[{"level": 1, "text": "Ready"}], landmarks={"main": 1},
                               axe_status="ok")


def _wait_state(manager, sid, wanted, timeout=8):
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
                                         "reason": "captcha_detected", "analysis_complete": False}}})
    return store


def _run_a_real_manual_check(out: str) -> str:
    """Drive the genuine manual-check path to completion; return the run id it created."""
    _blocked_original_run(out)
    manager = ChallengeSessionManager(out, wait_timeout_s=5, resolve_dns=False,
                                      backend_factory=lambda **kw: _WaitingBackend(**kw))
    item = manager.start(DOMAIN, source_run=SOURCE_RUN)
    _wait_state(manager, item["id"], {"waiting"})
    manager.signal(item["id"], "continue")
    done = _wait_state(manager, item["id"], {"completed", "failed", "deferred"})
    assert done["state"] == "completed", f"the manual check did not finish: {done}"
    return done["result_run"]


def _headed_replay_config(out: str, run_id: str) -> ScoutRunConfig:
    """The config the Dashboard's "Watch headed replay" handler really builds.

    Calls the production factory rather than restating it — an earlier draft of this file rebuilt
    the construction here and therefore stayed green while the handler still declared production.
    """
    return headed_replay_config(out, run_id, DOMAIN)


# --- what the two operator paths declare ---------------------------------------------------------

def test_a_real_manual_check_run_declares_a_removable_purpose(tmp_path):
    """Driven through the real path, not by rebuilding the config the test wants to see."""
    out = str(tmp_path)
    run_id = _run_a_real_manual_check(out)

    declared = RunPurposeIndex(out).purpose_of(run_id)
    assert declared == PURPOSE_MANUAL_TEST, (
        f"the manual check persisted run_purpose={declared!r}; an operator solving a CAPTCHA by hand "
        "is not client work, and declaring production makes the run permanently undeletable"
    )
    assert declared in REMOVABLE_PURPOSES


def test_a_real_manual_check_run_can_be_removed_through_the_product(tmp_path):
    """The point of the blocker: the operator can clean up without editing files by hand."""
    out = str(tmp_path)
    run_id = _run_a_real_manual_check(out)

    preview = DataManagementStore(out).preview([run_id])
    protected = {p["run_id"]: p.get("reason", "") for p in preview.protected}
    assert run_id not in protected, (
        f"the product refuses to remove a run its own manual-check button created: "
        f"{protected.get(run_id)!r}"
    )
    assert run_id in [r.run_id for r in preview.runs], (
        "the manual-check run is neither protected nor offered for removal - it fell between the two"
    )


def test_the_headed_replay_config_declares_a_removable_purpose(tmp_path):
    cfg = _headed_replay_config(str(tmp_path), "replay-blocked.example-1785")
    assert cfg.run_purpose == PURPOSE_DIAGNOSTIC, (
        f"the headed replay declares {cfg.run_purpose!r}; watching one target in a visible browser "
        "is a diagnostic look, and declaring production makes the run permanently undeletable"
    )
    assert cfg.run_purpose in REMOVABLE_PURPOSES


def test_a_headed_replay_run_can_be_removed_through_the_product(tmp_path):
    out = str(tmp_path)
    run_id = "replay-blocked.example-1785"
    cfg = _headed_replay_config(out, run_id)
    store = RunStore(out, run_id)
    store.write_config(cfg.to_dict())
    store.save_state({"status": "COMPLETED", "finished_at": "2026-07-30T10:00:00+00:00",
                      "prospects": {}})

    preview = DataManagementStore(out).preview([run_id])
    protected = {p["run_id"]: p.get("reason", "") for p in preview.protected}
    assert run_id not in protected, (
        f"the product refuses to remove a run its own replay button created: {protected.get(run_id)!r}"
    )
    assert run_id in [r.run_id for r in preview.runs], (
        "the replay run is neither protected nor offered for removal - it fell between the two"
    )


# --- the guarantees this must not break ----------------------------------------------------------

def test_a_real_production_campaign_is_still_refused(tmp_path):
    """Guard the guard: making diagnostic runs removable must not make client work removable."""
    out = str(tmp_path)
    run_id = "campaign-real-20260720t100000z-abc123"
    cfg = ScoutRunConfig(campaign_name="operator-scan", seeds=[f"https://{DOMAIN}/"], max_sites=1,
                         output_dir=out, run_id=run_id, run_purpose=PURPOSE_PRODUCTION)
    store = RunStore(out, run_id)
    store.write_config(cfg.to_dict())
    store.save_state({"status": "COMPLETED", "finished_at": "2026-07-20T10:00:00+00:00",
                      "prospects": {}})

    preview = DataManagementStore(out).preview([run_id])
    protected = {p["run_id"]: p.get("reason", "") for p in preview.protected}
    assert run_id in protected, "a production campaign must never become removable"
    assert "production" in protected[run_id].lower()
    assert run_id not in [r.run_id for r in preview.runs]


def test_the_http_gate_on_request_supplied_purposes_is_untouched():
    """The fix must not become a way for a request to mark its own data disposable.

    ``resolve_requested_purpose`` refuses a non-production purpose unless the server was started with
    AIQA_SCOUT_TEST_PURPOSE=1. M2 sets a server-side constant at two call sites and reads nothing
    from a request; this pins that the request path still fails closed.
    """
    from core.scout.run_purpose import PurposeNotPermitted, resolve_requested_purpose

    assert resolve_requested_purpose(None, allow_test=False) == PURPOSE_PRODUCTION
    for wanted in sorted(REMOVABLE_PURPOSES):
        try:
            resolve_requested_purpose(wanted, allow_test=False)
        except PurposeNotPermitted:
            continue
        raise AssertionError(
            f"resolve_requested_purpose accepted request-supplied {wanted!r} without the server opt-in; "
            "the M2 change must not have relaxed this gate"
        )
