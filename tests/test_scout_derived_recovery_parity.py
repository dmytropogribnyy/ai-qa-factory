"""Derived-only recovery + ONE canonical campaign-state answer on every operator surface.

Two lies shared a screen: a campaign the operator had STOPPED, and one whose worker had been gone a
day, both showed as active with "watch progress" — because ProjectIndex read `scout/<id>/state.json`
(the worker writes RUNNING at start and rewrites it only on a graceful finish) while Observer read
the run-control record. So the fix is parity first, recovery second, and the recovery half is a
*reading*: rewriting the record made a returning worker's next complete() illegal and turned a wrong
guess into a permanent wrong fact, where derived it is a display the next heartbeat corrects.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from core.dashboard.read_model import DashboardReadModel
from core.orchestration.project_index import ProjectIndex
from core.scout.campaign_service import CampaignService
from core.scout.canonical_runs import canonical_run_state, is_active_run
from core.scout.observer_api import ObserverAPI
from core.scout.run_control import (
    ANALYZING,
    PAUSED,
    RECOVERABLE,
    RECOVERY_STALE_S,
    STOPPED_CHECKPOINT,
    CampaignRunControl,
    heartbeat_age_s,
    is_unattended,
)
from core.scout.store import RunStore

FRESH = "campaign-fresh-worker-20260730T080000Z-a1b2c3"
STALE = "campaign-gone-worker-20260728T120707Z-50451a"
TERMINAL = "campaign-operator-stopped-20260729T114450Z-65ac65"
PARKED = "campaign-parked-run-20260729T090000Z-d4e5f6"
LEGACY = "campaign-legacy-recoverable-20260727T165424Z-1ea92e"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stale_iso(seconds: float = RECOVERY_STALE_S * 2) -> str:
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds)).isoformat()


def _write_campaign(tmp_path, cid, *, state, heartbeat, worker_status="RUNNING",
                    requested_control="", stop_reason=""):
    """A campaign as it exists on disk. Written as JSON, not driven through the state machine, so a
    row can hold exactly the combination a crash leaves behind."""
    rc_dir = tmp_path / "scout" / "_runcontrol"
    rc_dir.mkdir(parents=True, exist_ok=True)
    (rc_dir / f"{cid}.json").write_text(json.dumps({
        "campaign_id": cid, "state": state, "requested_control": requested_control,
        "stop_reason": stop_reason, "owner_pid": 44000, "heartbeat_at": heartbeat,
        "updated_at": "2026-07-29T15:19:09.395705+00:00",
        "checkpoint": {"pending_queue": [], "completed": [], "budgets": {},
                       "current_company": "", "current_page": ""},
    }, indent=2, sort_keys=True), encoding="utf-8")
    base = tmp_path / "scout" / cid
    base.mkdir(parents=True, exist_ok=True)
    (base / "state.json").write_text(json.dumps({
        "campaign_id": cid, "status": worker_status, "counts": {},
        "started_at": "2026-07-28T12:07:07.061427+00:00"}), encoding="utf-8")
    return cid


def _standard_set(tmp_path):
    """The one fixture set every surface is asked about, so parity is proven rather than asserted."""
    _write_campaign(tmp_path, FRESH, state=ANALYZING, heartbeat=_now_iso())
    _write_campaign(tmp_path, STALE, state=ANALYZING, heartbeat=_stale_iso())
    _write_campaign(tmp_path, TERMINAL, state=STOPPED_CHECKPOINT, heartbeat=_stale_iso(),
                    requested_control="stop")
    _write_campaign(tmp_path, PARKED, state=PAUSED, heartbeat=_stale_iso())
    _write_campaign(tmp_path, LEGACY, state=RECOVERABLE, heartbeat=_stale_iso(),
                    stop_reason="worker_gone: an earlier release persisted this")


def _surface_states(tmp_path):
    """The state each surface reports, per campaign."""
    out = str(tmp_path)
    svc, obs = CampaignService(out), ObserverAPI(out)
    index = {e.project_id: e for e in ProjectIndex(out).list_projects(include_diagnostics=True)}
    rows = {c["campaign_id"]: c for c in obs.list_campaigns(limit=500)["campaigns"]}
    return {cid: {"canonical": canonical_run_state(out, cid)["state"],
                  "progress_api": svc.progress(cid)["run_state"],
                  "observer_list": rows[cid]["run_state"],
                  "observer_get": obs.get_campaign(cid)["run_state"],
                  "project_index": index[cid].lifecycle_state}
            for cid in (FRESH, STALE, TERMINAL, PARKED, LEGACY)}


def _fingerprint(tmp_path, cid):
    p = tmp_path / "scout" / "_runcontrol" / f"{cid}.json"
    return p.read_bytes(), p.stat().st_mtime_ns


# --- parity: one answer per campaign, on every surface -------------------------------------------

def test_every_surface_reports_the_same_state_for_the_same_campaign(tmp_path):
    _standard_set(tmp_path)
    answers = _surface_states(tmp_path)
    for cid, per_surface in answers.items():
        assert len(set(per_surface.values())) == 1, f"{cid} disagreed: {per_surface}"
    assert {cid: next(iter(v.values())) for cid, v in answers.items()} == {
        FRESH: ANALYZING, STALE: RECOVERABLE, TERMINAL: STOPPED_CHECKPOINT,
        PARKED: PAUSED, LEGACY: RECOVERABLE}


def test_a_live_run_keeps_its_active_state(tmp_path):
    """The guard: reporting live work as lost is the same defect inverted."""
    _standard_set(tmp_path)
    assert is_active_run(canonical_run_state(str(tmp_path), FRESH)) is True


def test_a_terminal_run_whose_worker_file_still_says_running_is_not_active(tmp_path):
    """The row proving parity is its own defect: no recovery rule makes a stopped run active."""
    _standard_set(tmp_path)
    out = str(tmp_path)
    assert is_active_run(canonical_run_state(out, TERMINAL)) is False
    entry = {e.project_id: e for e in ProjectIndex(out).list_projects(include_diagnostics=True)}
    assert "watch progress" not in entry[TERMINAL].operator_next_action


def test_overview_counts_only_genuinely_live_campaigns(tmp_path):
    _standard_set(tmp_path)
    overview = DashboardReadModel(str(tmp_path)).overview(include_diagnostics=True)
    assert [c["campaign_id"] for c in overview.active_campaigns] == [FRESH]
    assert overview.counts["active_campaigns"] == 1


def test_observer_active_campaigns_excludes_paused_and_recoverable(tmp_path):
    """`paused` is not active — the Observer's own literal disagreed with ACTIVE_STATES about it."""
    _standard_set(tmp_path)
    assert ObserverAPI(str(tmp_path)).get_project_overview()["active_campaigns"] == [FRESH]


def test_a_recoverable_run_is_surfaced_for_a_decision_not_silently_dropped(tmp_path):
    """Ceasing to call it active must not make it vanish — that was one of the live defects."""
    _standard_set(tmp_path)
    overview = DashboardReadModel(str(tmp_path)).overview(include_diagnostics=True)
    flagged = {a["project_id"]: a for a in overview.scout_attention}
    assert STALE in flagged and LEGACY in flagged
    assert "resume" not in flagged[STALE]["next_action"].lower()   # nothing relaunches a dead worker


def test_the_shared_predicate_is_the_only_active_rule(tmp_path):
    _standard_set(tmp_path)
    out = str(tmp_path)
    for cid, want in {FRESH: True, STALE: False, TERMINAL: False, PARKED: False,
                      LEGACY: False}.items():
        assert is_active_run(canonical_run_state(out, cid)) is want, cid


# --- the read is a reading -----------------------------------------------------------------------

def test_reading_changes_nothing_on_disk_and_logs_no_activity(tmp_path):
    _standard_set(tmp_path)
    before = {cid: _fingerprint(tmp_path, cid) for cid in (STALE, TERMINAL, PARKED, LEGACY)}
    _surface_states(tmp_path)
    DashboardReadModel(str(tmp_path)).overview(include_diagnostics=True)
    ObserverAPI(str(tmp_path)).get_project_overview()
    assert {cid: _fingerprint(tmp_path, cid) for cid in before} == before
    assert RunStore(str(tmp_path), STALE).read_events() == []


def test_a_campaign_row_is_one_snapshot_even_if_the_worker_returns_mid_read(tmp_path, monkeypatch):
    """A row built from two canonical reads can contradict itself.

    With a heartbeat landing between them, `run_state` came from the stale read while
    `persisted_state`/`derived`/`active` came from the fresh one — so one row said `recoverable`,
    `derived: false` and `active: true` at the same time. Deterministic here: the patched reader
    performs the real read and *then* lets the worker return, so read 1 and read 2 must differ.
    """
    _write_campaign(tmp_path, STALE, state=ANALYZING, heartbeat=_stale_iso())
    out = str(tmp_path)
    import core.scout.canonical_runs as canonical_module
    real = canonical_module.canonical_run_state
    seen = {"n": 0}

    def racing(output_dir, run_id):
        view = real(output_dir, run_id)
        seen["n"] += 1
        if seen["n"] == 1:
            CampaignRunControl(run_id, output_dir).heartbeat()      # the worker comes back
        return view

    monkeypatch.setattr(canonical_module, "canonical_run_state", racing)
    row = ObserverAPI(out).list_campaigns(limit=10)["campaigns"][0]
    # One read per row is the structural guarantee; a second one is what created the race at all.
    assert seen["n"] == 1, f"the row must come from one canonical read, saw {seen['n']}"
    # Whichever instant the row describes, it must describe only one.
    assert row["derived"] is (row["run_state"] != row["persisted_state"])
    assert row["active"] is (row["run_state"] == ANALYZING)
    assert not (row["run_state"] == RECOVERABLE and row["active"])
    assert not (row["run_state"] == RECOVERABLE and row["derived"] is False)


def test_the_progress_payload_comes_from_one_physical_run_control_read(tmp_path, monkeypatch):
    """Counting `canonical_run_state()` calls is not enough — it cannot see a second loader call.

    This counts actual `CampaignRunControl._load` invocations and rewrites the record right after the
    first one, so any field still sourced from a later read shows the *new* value and the payload
    becomes a hybrid of two instants. `requested_control` is the tell: it used to come from a second
    `CampaignRunControl` built inside `progress()`.
    """
    _write_campaign(tmp_path, STALE, state=ANALYZING, heartbeat=_stale_iso(),
                    requested_control="stop")
    out = str(tmp_path)
    from core.scout import run_control as rc_module
    real_load = rc_module.CampaignRunControl._load
    loads = {"n": 0}

    def counting_load(self):
        loaded = real_load(self)
        loads["n"] += 1
        if loads["n"] == 1:
            # The operator's Stop is cleared and the worker returns, immediately after the first read.
            _write_campaign(tmp_path, STALE, state=ANALYZING, heartbeat=_now_iso(),
                            requested_control="")
        return loaded

    monkeypatch.setattr(rc_module.CampaignRunControl, "_load", counting_load)
    payload = CampaignService(out).progress(STALE)
    assert loads["n"] == 1, f"the payload must come from one run-control read, saw {loads['n']}"
    # Every field describes the first instant. A mix would show a fresh heartbeat beside a stale state.
    assert (payload["run_state"], payload["persisted_state"]) == (RECOVERABLE, ANALYZING)
    assert payload["derived"] is True
    assert payload["requested_control"] == "stop"
    assert payload["stop_reason"] == ""


def test_a_returning_worker_becomes_authoritative_on_its_next_heartbeat(tmp_path):
    """Disk still says `analyzing`, so the worker's own lifecycle is untouched by our reading."""
    _standard_set(tmp_path)
    out = str(tmp_path)
    assert canonical_run_state(out, STALE)["state"] == RECOVERABLE
    rc = CampaignRunControl(STALE, out)
    rc.heartbeat()
    assert canonical_run_state(out, STALE)["state"] == ANALYZING
    rc.complete()                      # the transition a persisted RECOVERABLE made illegal
    assert canonical_run_state(out, STALE)["state"] == "completed"


def test_a_live_worker_survives_a_read_in_production_callback_order(tmp_path):
    _standard_set(tmp_path)
    rc = CampaignRunControl(FRESH, str(tmp_path))
    _surface_states(tmp_path)
    rc.reload()                        # the real progress_cb order
    assert rc.should_stop() is False and rc.should_pause() is False
    rc.heartbeat()
    rc.complete()


@pytest.mark.parametrize("control,probe", [("stop", "should_stop"), ("pause", "should_pause")])
def test_a_pending_operator_control_survives_the_derived_read(tmp_path, control, probe):
    """`requested_control` is the operator's instruction, not a fact about the worker."""
    _write_campaign(tmp_path, STALE, state=ANALYZING, heartbeat=_stale_iso(),
                    requested_control=control)
    out = str(tmp_path)
    assert canonical_run_state(out, STALE)["state"] == RECOVERABLE
    rc = CampaignRunControl(STALE, out)
    rc.reload()
    assert getattr(rc, probe)() is True
    assert rc.state.requested_control == control


# --- heartbeat policy ---------------------------------------------------------------------------

@pytest.mark.parametrize("heartbeat", ["", None, [], {}, 0, 1753000000, "not-a-timestamp",
                                       "2026-13-45T99:99:99"])
def test_an_unusable_heartbeat_on_an_active_run_means_unattended(heartbeat):
    """Deterministic and list-safe: `fromisoformat` raises TypeError on a list, not ValueError."""
    assert heartbeat_age_s(heartbeat) == float("inf")
    assert is_unattended(ANALYZING, heartbeat) is True


def test_a_naive_legacy_timestamp_is_read_as_utc():
    naive = datetime.now(timezone.utc).replace(tzinfo=None).isoformat()
    assert heartbeat_age_s(naive) < 60.0
    assert is_unattended(ANALYZING, naive) is False


def test_the_stale_threshold_boundary_is_pinned():
    """At exactly the threshold a run counts as unattended, so a 0.0 window means "always"."""
    assert is_unattended(ANALYZING, _stale_iso(RECOVERY_STALE_S + 1)) is True
    assert is_unattended(ANALYZING, _now_iso(), recovery_stale_s=0.0) is True
    assert is_unattended(ANALYZING, _stale_iso(RECOVERY_STALE_S / 2)) is False


@pytest.mark.parametrize("state", [PAUSED, STOPPED_CHECKPOINT, RECOVERABLE, "completed", "failed",
                                   "blocked", "queued"])
def test_a_non_active_state_is_never_unattended_whatever_the_heartbeat_says(state):
    """Membership is tested before the timestamp, so a parked or finished row is never parsed."""
    assert is_unattended(state, []) is False
    assert is_unattended(state, "garbage") is False


def test_a_parked_run_with_a_malformed_heartbeat_reads_as_paused(tmp_path):
    _write_campaign(tmp_path, PARKED, state=PAUSED, heartbeat=[])
    assert canonical_run_state(str(tmp_path), PARKED)["state"] == PAUSED


# --- provenance, terminality, legacy rows -------------------------------------------------------

def test_the_canonical_view_shows_both_layers(tmp_path):
    _standard_set(tmp_path)
    out = str(tmp_path)
    stale = canonical_run_state(out, STALE)
    assert (stale["state"], stale["persisted_state"], stale["derived"]) == (
        RECOVERABLE, ANALYZING, True)
    assert stale["state_source"] == f"scout/_runcontrol/{STALE}.json"
    assert "worker_gone" in stale["derived_reason"]
    live = canonical_run_state(out, FRESH)
    assert (live["state"], live["persisted_state"], live["derived"], live["derived_reason"]) == (
        ANALYZING, ANALYZING, False, "")
    # `stopped_with_checkpoint` and `blocked` were absent from the canonical terminal set.
    assert canonical_run_state(out, TERMINAL)["terminal"] is True
    assert (stale["terminal"], live["terminal"]) == (False, False)


def test_the_progress_api_keeps_run_state_and_adds_provenance(tmp_path):
    _standard_set(tmp_path)
    payload = CampaignService(str(tmp_path)).progress(STALE)
    assert payload["run_state"] == RECOVERABLE          # existing key, existing meaning
    assert payload["persisted_state"] == ANALYZING
    assert payload["derived"] is True
    assert payload["state_source"] == f"scout/_runcontrol/{STALE}.json"
    assert payload["stop_reason"] == ""                 # nothing written, so nothing claimed
    assert "worker_gone" in payload["derived_reason"]


def test_a_legacy_persisted_recoverable_row_stays_readable_and_resumable(tmp_path):
    """Rows an earlier release persisted keep working; nothing migrates or rewrites them."""
    _standard_set(tmp_path)
    out = str(tmp_path)
    view = canonical_run_state(out, LEGACY)
    assert (view["state"], view["persisted_state"], view["derived"]) == (
        RECOVERABLE, RECOVERABLE, False)
    assert CampaignRunControl(LEGACY, out).resume() == ANALYZING
