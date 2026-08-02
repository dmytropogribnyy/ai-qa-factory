"""An operator control must survive a competing writer, or say plainly that it did not.

From the 2026-08-02 Scout functional acceptance re-run (checkpoint `5157209878`): pressing Pause
on a live campaign closed the HTTP connection with no response and the pause was never recorded —
the run continued as if nothing had been asked. Two independent faults produced that:

* every ``CampaignRunControl`` writes the SAME ``<campaign>.json.tmp``, so two savers race for one
  temp file and the loser's ``os.replace`` raises ``FileNotFoundError``;
* each saver writes its WHOLE in-memory snapshot, so a worker holding a pre-pause snapshot erases
  ``requested_control`` and rolls ``PAUSING`` back when it next beats.

The three guarantees below are pinned separately: fixing the temp collision alone would leave a
stale snapshot silently overwriting the pause — a quieter version of the same defect.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from core.scout import run_control
from core.scout.dashboard import start_dashboard
from core.scout.run_control import ANALYZING, PAUSING, TRIAGING, CampaignRunControl
from core.scout.service import ScoutService


def _live_worker(tmp_path, campaign_id="c1"):
    """A worker that has started a run and therefore holds a snapshot of it.

    DISCOVERING -> ANALYZING is not a legal transition; the run goes through TRIAGING.
    """
    rc = CampaignRunControl(campaign_id, str(tmp_path))
    rc.run_now()                      # -> DISCOVERING
    rc.advance(TRIAGING)
    rc.advance(ANALYZING)
    return rc


def _fresh(tmp_path, campaign_id="c1"):
    return CampaignRunControl(campaign_id, str(tmp_path))


# --- guarantee 1: two writers must not collide on one temp file -------------------------------

def test_a_competing_save_midway_through_ours_does_not_break_the_control(tmp_path, monkeypatch):
    """Deterministic interleaving: another writer completes a full save inside our own save.

    That is exactly the window the acceptance hit — both savers had written the shared temp file
    and the other one's ``os.replace`` consumed it first.
    """
    _live_worker(tmp_path)
    operator = _fresh(tmp_path)

    real_replace = run_control.atomic_replace
    fired: list = []

    def interleaved(tmp, path, **kw):
        if not fired:                       # once, on the operator's own save
            fired.append(True)
            _fresh(tmp_path).heartbeat()    # a competing writer completes a whole save
        return real_replace(tmp, path, **kw)

    monkeypatch.setattr(run_control, "atomic_replace", interleaved)

    operator.request_pause()                # must not raise

    assert fired, "the interleaving never happened — the test proves nothing"
    assert _fresh(tmp_path).state.requested_control == "pause"


# --- guarantee 2: a stale snapshot must not erase a durable control ----------------------------

def test_a_stale_worker_heartbeat_cannot_erase_a_durable_pause(tmp_path):
    """stale worker snapshot -> durable Pause -> worker heartbeat -> fresh read still sees Pause.

    No threads and no patching: the worker simply holds the snapshot it loaded before the pause,
    which is what the campaign thread does between event boundaries.
    """
    worker = _live_worker(tmp_path)                 # snapshot predates the pause
    operator = _fresh(tmp_path)

    operator.request_pause()
    assert _fresh(tmp_path).state.requested_control == "pause"

    worker.heartbeat()                              # writes its own view of the world

    after = _fresh(tmp_path)
    assert after.state.requested_control == "pause", "the worker's stale view erased the pause"
    assert after.state.state == PAUSING, "the pause transition must not be rolled back"


def test_a_stale_worker_checkpoint_save_cannot_erase_a_durable_pause(tmp_path):
    """The same guarantee for the other mutator the worker calls while running."""
    from core.scout.run_control import Checkpoint

    worker = _live_worker(tmp_path)
    _fresh(tmp_path).request_pause()

    worker.save_checkpoint(Checkpoint(current_company="acme.com"))

    after = _fresh(tmp_path)
    assert after.state.requested_control == "pause"
    assert after.state.state == PAUSING
    assert after.state.checkpoint.current_company == "acme.com", "the worker's own write is kept"


# --- guarantee 3: the HTTP path must tell the operator the truth -------------------------------

def _post(url, token, body=None):
    req = urllib.request.Request(url, method="POST",
                                 data=json.dumps(body or {}).encode("utf-8"),
                                 headers={"Content-Type": "application/json",
                                          "X-Scout-CSRF": token})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            return r.status, json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))


def test_pause_over_http_reports_success_only_when_the_control_is_durable(tmp_path):
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        _live_worker(tmp_path)
        status, body = _post(
            f"{url}/api/scout/control?id=c1&action=pause", server.scout_csrf_token)
        assert status == 200 and body.get("ok") is True
        assert _fresh(tmp_path).state.requested_control == "pause", \
            "a 200 must mean the control was actually persisted"
    finally:
        server.shutdown()


def test_an_unknown_control_action_is_refused_at_the_http_layer(tmp_path):
    """A control that was never applied must not be reported as HTTP success.

    ``CampaignService.control()`` answers ``{"ok": False, ...}`` for an action it does not know.
    Returning 200 for that made a rejected request indistinguishable from an applied one at the
    HTTP layer — the same confusion as the lost Pause, arriving by a different route.
    """
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        worker = _live_worker(tmp_path)
        before = worker.state.state

        status, body = _post(
            f"{url}/api/scout/control?id=c1&action=frobnicate", server.scout_csrf_token)

        assert 400 <= status < 500, "an unapplied control must not come back as success"
        assert body.get("ok") is False
        assert "frobnicate" in str(body.get("error", ""))

        after = _fresh(tmp_path)
        assert after.state.state == before, "a refused action must not touch the run"
        assert after.state.requested_control == ""
    finally:
        server.shutdown()


def test_pause_over_http_returns_an_explicit_error_when_persistence_fails(tmp_path, monkeypatch):
    """A failed write must reach the operator as JSON, never as a dropped connection."""
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        _live_worker(tmp_path)

        def boom(*_a, **_kw):
            raise OSError("disk gone")

        monkeypatch.setattr(run_control.CampaignRunControl, "_save", boom)

        status, body = _post(
            f"{url}/api/scout/control?id=c1&action=pause", server.scout_csrf_token)

        assert status >= 400, "a failed control must not be reported as success"
        assert body.get("ok") is False
        assert body.get("error"), "the operator must be told what went wrong"
    finally:
        server.shutdown()
