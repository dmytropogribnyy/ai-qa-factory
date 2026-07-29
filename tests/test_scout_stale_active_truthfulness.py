"""A run whose worker is gone must stop being reported as running.

The product could already tell (`_is_orphaned`) and already knew what to do about it
(`recover_on_startup` -> RECOVERABLE, never auto-resuming). The two were never wired together, so a
campaign whose process had died kept answering `analyzing` — with no progress, no stop reason, and a
place in `active_campaigns` — until a human happened to notice and press Stop. One such row survived
a full day and several restarts before a reviewer found it.

These tests fix the OBSERVABLE promise, not a mechanism: whatever a surface says about such a run,
it must not be "still working", and it must say why it is recoverable instead.
"""
from __future__ import annotations

import json
import urllib.request
from datetime import datetime, timedelta, timezone

from core.dashboard.read_model import DashboardReadModel
from core.orchestration.project_index import ProjectIndex
from core.scout.campaign_service import CampaignService
from core.scout.dashboard import start_dashboard
from core.scout.observer_api import ObserverAPI
from core.scout.run_control import (
    ACTIVE_STATES,
    ANALYZING,
    DISCOVERING,
    RECOVERABLE,
    CampaignRunControl,
    Checkpoint,
    recover_orphaned_runs,
)
from core.scout.service import ScoutService
from core.scout.store import RunStore

CID = "campaign-balanced-production-scou-20260728T120707Z-50451a"


def _orphaned_active_run(root, campaign_id=CID, *, state="analyzing", age_minutes=90,
                         pending=("pending-site.example",)):
    """Write the run-control row a crashed worker leaves behind: active, but nobody is home.

    Modelled on the real residue — an ACTIVE state, a heartbeat hours old, and an owner pid that
    belongs to no living process. `owner_pid=0` is used deliberately: a recycled pid must never be
    what decides this, so the rule has to rest on the heartbeat.
    """
    rc_dir = root / "scout" / "_runcontrol"
    rc_dir.mkdir(parents=True, exist_ok=True)
    stale_at = (datetime.now(timezone.utc) - timedelta(minutes=age_minutes)).isoformat()
    (rc_dir / f"{campaign_id}.json").write_text(json.dumps({
        "campaign_id": campaign_id,
        "state": state,
        "stop_reason": "",
        "requested_control": "",
        "owner_pid": 0,
        "heartbeat_at": stale_at,
        "updated_at": stale_at,
        "checkpoint": {"budgets": {}, "completed": [], "current_company": "",
                       "current_page": "", "pending_queue": list(pending)},
    }, indent=2), encoding="utf-8")
    return campaign_id


def _engine_state(root, campaign_id=CID, *, status="RUNNING"):
    """The OTHER half of the residue: the engine's own `state.json`, still saying RUNNING.

    The Dashboard reads this file; the Observer reads run-control. That is how one dead run could be
    `RUNNING` on one screen and `analyzing` on the other — two files, two vocabularies, both wrong in
    the same direction. The real 28-July row carries exactly this pair.
    """
    run_dir = root / "scout" / campaign_id
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "state.json").write_text(json.dumps({
        "campaign_id": campaign_id, "status": status,
        "started_at": (datetime.now(timezone.utc) - timedelta(minutes=90)).isoformat(),
    }, indent=2), encoding="utf-8")
    return campaign_id


def test_a_run_whose_worker_is_gone_is_not_reported_as_active(tmp_path):
    """The headline promise: the Observer must not present a dead run as one that is still working."""
    campaign_id = _orphaned_active_run(tmp_path)

    overview = ObserverAPI(str(tmp_path)).get_project_overview()

    assert campaign_id not in overview["active_campaigns"], (
        "a run whose worker is gone is still being reported as active — this is the operator being "
        "told work is in progress when nothing is running")


def test_the_shared_read_model_calls_it_recoverable_and_says_why(tmp_path):
    """Both surfaces read this one model, so the truthful state has to be here, with its reason."""
    campaign_id = _orphaned_active_run(tmp_path)

    progress = CampaignService(str(tmp_path)).progress(campaign_id)

    assert progress["run_state"] == RECOVERABLE
    assert progress["stop_reason"], (
        "a state change the operator did not ask for must explain itself; an empty reason leaves "
        "them guessing why the run stopped saying it was working")


def test_recovery_never_resumes_deletes_or_relabels_the_run(tmp_path):
    """Recovery restores the truth about a run — it must not take any decision on the operator's behalf."""
    campaign_id = _orphaned_active_run(tmp_path, pending=("a.example", "b.example"))

    ObserverAPI(str(tmp_path)).get_project_overview()

    rc = CampaignRunControl(campaign_id, str(tmp_path))
    assert rc.state.state not in ACTIVE_STATES, "recovery must never quietly resume the work"
    assert rc.state.checkpoint.pending_queue == ["a.example", "b.example"], (
        "the unfinished queue is what makes the run resumable — recovery must preserve it")
    assert (tmp_path / "scout" / "_runcontrol" / f"{campaign_id}.json").exists(), (
        "recovery must never remove the run")


def test_a_live_run_keeps_its_active_state(tmp_path):
    """The guard against the obvious over-correction: a working run must still read as working."""
    campaign_id = _orphaned_active_run(tmp_path, age_minutes=0)   # heartbeat is now

    overview = ObserverAPI(str(tmp_path)).get_project_overview()

    assert campaign_id in overview["active_campaigns"], (
        "a run with a fresh heartbeat is genuinely working and must keep saying so")


def test_both_surfaces_name_the_same_state(tmp_path):
    """Truthful on one screen is not truthful: the operator switches between them.

    The Dashboard's own read model derives a campaign's state from `scout/<id>/state.json`, the
    Observer from run-control. Only the state a dead worker leaves in BOTH can be fixed once.
    """
    campaign_id = _orphaned_active_run(tmp_path)
    _engine_state(tmp_path)

    observer_state = ObserverAPI(str(tmp_path)).get_run_progress(campaign_id)["run_state"]
    entry = next(p for p in ProjectIndex(str(tmp_path)).list_projects(True)
                 if p.project_id == campaign_id)

    assert observer_state.upper() == entry.lifecycle_state.upper() == RECOVERABLE.upper(), (
        f"Observer says {observer_state!r} and the Dashboard says {entry.lifecycle_state!r} — "
        "the operator gets a different answer depending on which screen they open")


def test_a_stopped_run_is_not_active_on_the_dashboard_either(tmp_path):
    """Found on the live machine, in the run the previous review used to prove Stop works.

    `state.json` is written by the worker, so a run stopped while its worker was already gone keeps
    the last thing that worker wrote: RUNNING. The Overview believed it and counted the run as
    active a day after it had been stopped through the supported control. Whether work is in
    progress is run-control's answer to give, on every surface.
    """
    campaign_id = _orphaned_active_run(tmp_path, state="stopped_with_checkpoint")
    _engine_state(tmp_path)                       # the worker's last word: RUNNING

    overview = DashboardReadModel(str(tmp_path)).overview()

    assert campaign_id not in [c["campaign_id"] for c in overview.active_campaigns], (
        "a run the product itself calls stopped is still counted as active work")
    assert overview.counts["active_campaigns"] == 0


def test_the_offered_controls_match_the_state_the_operator_is_shown(tmp_path):
    """Found in the browser: the recovered run offered Pause, and hid Resume.

    Pausing a run whose worker is gone does nothing, and Resume — the action the page's own next
    step recommends — was the one control missing. The campaign page decided this from its own copy
    of the state vocabulary, written before RECOVERABLE existed, which is why it never learned about
    it. The state machine that owns the vocabulary answers now, and the page just applies it.
    """
    recovered = _orphaned_active_run(tmp_path)
    live = _orphaned_active_run(tmp_path, campaign_id="campaign-live-20260729T120000Z-aaaaaa",
                                age_minutes=0)
    svc = CampaignService(str(tmp_path))

    assert svc.progress(recovered)["controls"] == {"pause": False, "resume": True, "stop": True}
    assert svc.progress(live)["controls"] == {"pause": True, "resume": False, "stop": True}


def test_a_recovered_run_asks_for_the_operator_instead_of_vanishing(tmp_path):
    """Honest and invisible is its own failure.

    Before this fix the run at least appeared on Overview — under a heading that lied about it.
    Dropping it out of the active list without putting it anywhere would trade a visible lie for a
    silent disappearance, and the decision it needs (resume or stop) is exactly what Overview exists
    to surface.
    """
    campaign_id = _orphaned_active_run(tmp_path)
    _engine_state(tmp_path)

    overview = DashboardReadModel(str(tmp_path)).overview()

    waiting = [a for a in overview.scout_attention if a["project_id"] == campaign_id]
    assert waiting, "a run waiting for an operator decision is on no screen the operator watches"
    assert waiting[0]["reason"], "it must say why it is waiting"
    assert overview.counts["scout_attention"] == 1


def test_the_overview_headline_does_not_call_a_recovered_run_a_failure(tmp_path):
    """The block's heading was written when failure was the only way in — and it counts the list.

    A recovered run is not a failed one: the work is intact and waiting. A heading that says
    otherwise puts a false severity on the operator's first screen, and the row underneath it says
    something different again.
    """
    _orphaned_active_run(tmp_path)
    _engine_state(tmp_path)
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        with urllib.request.urlopen(url + "/", timeout=10) as r:
            page = r.read().decode("utf-8")
    finally:
        server.shutdown()

    assert "waiting for you to resume or stop" in page, (
        "the recovered run is not on the operator's first screen")
    assert "ended in a failed state" not in page, (
        "the Overview calls a recovered run a failure; nothing failed, the worker went away")


def test_reading_the_run_does_not_rewrite_it(tmp_path):
    """A surface that reports on production must not edit production while reporting.

    The correction is DERIVED from what the record already says (an active state whose heartbeat
    stopped), so every reader reaches it independently and a worker that comes back is believed
    again. Rewriting the row on a read would instead destroy the evidence of what actually happened.
    """
    campaign_id = _orphaned_active_run(tmp_path)
    raw_before = (tmp_path / "scout" / "_runcontrol" / f"{campaign_id}.json").read_text("utf-8")

    ObserverAPI(str(tmp_path)).get_project_overview()
    CampaignService(str(tmp_path)).progress(campaign_id)

    raw_after = (tmp_path / "scout" / "_runcontrol" / f"{campaign_id}.json").read_text("utf-8")
    assert json.loads(raw_after) == json.loads(raw_before), (
        "reading a run rewrote its persisted record — the operator's provenance (what state the "
        "worker was in, when it last reported) must survive being looked at")


def test_the_startup_sweep_writes_the_correction_down_once(tmp_path):
    """Startup is where a write is legitimate: no worker of ours is running yet.

    This is the caller `recover_on_startup` never had. It persists what the read model already
    derives, so the stored row stops claiming work is in progress — and says so in Activity, because
    a state change nobody asked for has to be explainable afterwards.
    """
    campaign_id = _orphaned_active_run(tmp_path, pending=("a.example", "b.example"))

    recovered = recover_orphaned_runs(str(tmp_path))

    assert [r["campaign_id"] for r in recovered] == [campaign_id]
    stored = json.loads((tmp_path / "scout" / "_runcontrol" / f"{campaign_id}.json")
                        .read_text("utf-8"))
    assert stored["state"] == RECOVERABLE
    assert stored["stop_reason"], "the persisted row must carry the reason, not just the new state"
    assert stored["checkpoint"]["pending_queue"] == ["a.example", "b.example"]
    assert [e for e in RunStore(str(tmp_path), campaign_id).read_events()
            if e.get("event") == "run_recovered"], "Activity must record the correction"


def test_the_startup_sweep_leaves_a_live_run_alone(tmp_path):
    """The same guard as the read path, at the surface that actually writes."""
    campaign_id = _orphaned_active_run(tmp_path, age_minutes=0)

    assert recover_orphaned_runs(str(tmp_path)) == []
    stored = json.loads((tmp_path / "scout" / "_runcontrol" / f"{campaign_id}.json")
                        .read_text("utf-8"))
    assert stored["state"] == "analyzing", "a run that is still reporting must not be touched"


def test_a_worker_that_reports_in_again_is_believed(tmp_path):
    """A correction drawn from silence must not outlive the silence.

    The engine reloads its own record on every progress event and then heartbeats. A read-time
    correction that survived that heartbeat would make a live run persist ITSELF as recoverable
    whenever one analysis step ran long — the same lie as the one being fixed, pointing the other
    way, and this time written down where no later read can undo it.
    """
    campaign_id = _orphaned_active_run(tmp_path)                  # heartbeat 90 minutes old
    rc = CampaignRunControl(campaign_id, str(tmp_path))
    assert rc.state.state == RECOVERABLE                          # what a reader concludes

    rc.heartbeat()                                                # the worker: I am still here

    assert rc.state.state == ANALYZING, "the worker's own heartbeat outranks a reader's inference"
    assert rc.state.stop_reason == "", "a running run must not carry a reason for having stopped"
    stored = json.loads((tmp_path / "scout" / "_runcontrol" / f"{campaign_id}.json")
                        .read_text("utf-8"))
    assert stored["state"] == ANALYZING and stored["stop_reason"] == ""


def test_starting_again_over_a_recovered_run_starts_clean(tmp_path):
    """`run_now` replaces the record — nothing inferred about the dead run may leak into the new one."""
    campaign_id = _orphaned_active_run(tmp_path)
    rc = CampaignRunControl(campaign_id, str(tmp_path))
    assert rc.state.state == RECOVERABLE

    rc.run_now()
    rc.heartbeat()                       # the new worker's first report

    assert rc.state.state == DISCOVERING, "the new run was dragged back into the dead run's state"
    assert rc.state.stop_reason == ""


def test_resuming_a_recovered_run_stops_calling_it_stopped(tmp_path):
    """The campaign page prints `stop_reason` as "Stopped because ..." whenever it is set."""
    campaign_id = _orphaned_active_run(tmp_path)
    recover_orphaned_runs(str(tmp_path))

    rc = CampaignRunControl(campaign_id, str(tmp_path))
    rc.resume()

    assert rc.state.state == ANALYZING
    assert rc.state.stop_reason == "", (
        "a resumed run still carrying the recovery reason tells the operator it is running and "
        "stopped at the same time")


def test_stop_records_why_it_stopped(tmp_path):
    """Stop & Save left `stop_reason` empty, so a stopped row could not say what stopped it."""
    rc = CampaignRunControl("camp-stop", output_dir=str(tmp_path))
    rc.run_now()

    rc.stop_and_save(Checkpoint(pending_queue=["left.example"]))

    assert rc.state.stop_reason, (
        "a stopped run must record why — 'stopped_with_checkpoint' names the state, not the cause")
    assert rc.state.checkpoint.pending_queue == ["left.example"], "Stop & Save keeps the queue"


def test_stop_leaves_an_activity_trail(tmp_path):
    """Activity is where the operator reconstructs what happened after the fact.

    A stopped campaign whose feed shows no stop is a run that ended without anyone being told; the
    reason the caller gives is the one that has to survive into the feed, not a generic label.
    """
    rc = CampaignRunControl("camp-stop", output_dir=str(tmp_path))
    rc.run_now()

    rc.stop_and_save(Checkpoint(), reason="operator pressed Stop & Save")

    stops = [e for e in RunStore(str(tmp_path), "camp-stop").read_events()
             if e.get("event") == "run_stopped"]
    assert stops, "Stop & Save wrote no Activity event"
    assert stops[-1].get("reason") == "operator pressed Stop & Save"
    assert rc.state.stop_reason == "operator pressed Stop & Save"
