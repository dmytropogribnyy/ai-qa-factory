"""A4.5 foundation closure — an unreadable value must not become good news.

Four boundaries turned "I cannot tell" into a definite, favourable answer:

1. **A corrupt campaign lock was reclaimed as expired.** `FileExistsError` proves a lock EXISTS;
   the handler then parsed it, collapsed any failure to ``{}``, read ``until`` as ``0`` and
   concluded the lease was stale — so a torn lock (the writer does `os.open`+`os.write` with no
   fsync, so a crash mid-write leaves partial JSON) *admits a second concurrent run against the
   same targets*, which is exactly what the lock exists to prevent. Same expression twice: the
   campaign lock and the per-domain claim lease.
2. **A malformed ``until`` escaped the handler entirely.** ``float(None)`` raises `TypeError`,
   which is not in the caught tuple, so `{"until": null}` crashed instead of failing closed.
3. **A corrupt work-state file was laundered into a healthy fresh intake.** `_read_json` returns
   ``{}`` on failure and ``status = rs.get("status") or "RECEIVED"`` turns that into a definite
   lifecycle state — which maps to "Intake", 10%, and health "ok", so a project that was mid-
   execution silently reappears as new work and never reaches the attention inbox.
4. **The existence of a directory was read as completion.** ``"COMPLETED" if report.is_dir()``:
   a worker creates `report/` on its FIRST write, so a campaign killed mid-run presents as finished
   at 100%.

The rule these share is the controller's: missing != zero, UNKNOWN != PASS. A lock that cannot be
read is held, not free; a state that cannot be parsed is unknown, not fresh; a directory is not a
verdict.
"""
from __future__ import annotations

import json

import pytest


# --- locks: unreadable means HELD ----------------------------------------------------------------

def _lock(tmp_path, body: str):
    from core.scout.discovery.run_lock import CampaignRunLock
    lock = CampaignRunLock(str(tmp_path), "camp-1", lease_s=300.0, clock=lambda: 1000.0)
    path = tmp_path / "scout" / "_registry" / "run-camp-1.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")
    return lock, path


@pytest.mark.parametrize("body, why", [
    ("{not json at all", "a torn write leaves partial JSON"),
    ("", "an empty file is a lock whose contents were lost"),
    ('{"pid": 1}', "a lock with no lease says nothing about expiry"),
    ('{"pid": 1, "until": null}', "a null lease is not an expired lease"),
    ('{"pid": 1, "until": "soon"}', "a non-numeric lease is not an expired lease"),
])
def test_an_unreadable_campaign_lock_is_treated_as_held(tmp_path, body, why):
    from core.scout.discovery.run_lock import CampaignBusy
    lock, _ = _lock(tmp_path, body)
    with pytest.raises(CampaignBusy):
        lock.acquire()


def test_a_genuinely_expired_campaign_lock_is_still_reclaimed(tmp_path):
    """Control: fail-closed must not mean a dead run blocks the campaign for ever."""
    lock, path = _lock(tmp_path, json.dumps({"pid": 1, "until": 500.0}))   # clock is 1000.0
    lock.acquire()
    assert json.loads(path.read_text(encoding="utf-8"))["until"] > 1000.0


def test_a_live_campaign_lock_still_blocks(tmp_path):
    from core.scout.discovery.run_lock import CampaignBusy
    lock, _ = _lock(tmp_path, json.dumps({"pid": 1, "until": 9999.0}))
    with pytest.raises(CampaignBusy):
        lock.acquire()


@pytest.mark.parametrize("body", ["{broken", "", '{"owner": "x"}', '{"owner": "x", "until": null}'])
def test_an_unreadable_domain_claim_lease_is_not_granted(tmp_path, body):
    """The sibling of the campaign lock, with the same expression and the same consequence."""
    from core.scout.discovery.analyzed_registry import AnalyzedSiteRegistry
    reg = AnalyzedSiteRegistry(str(tmp_path))
    reg._locks.mkdir(parents=True, exist_ok=True)
    (reg._locks / "example.com.lock").write_text(body, encoding="utf-8")
    assert reg.claim("example.com", owner="campaign-b", lease_s=300.0) is False


# --- a corrupt work state is UNKNOWN, not a fresh intake -----------------------------------------

def test_a_corrupt_work_run_state_is_not_reported_as_a_healthy_new_intake(tmp_path):
    """The screen whose whole job is to surface trouble must not hide corruption."""
    from core.orchestration.project_index import ProjectIndex
    ark = tmp_path / "proj-1" / "40_ark_work"
    ark.mkdir(parents=True)
    (ark / "WORK_PACKET.json").write_text(json.dumps({"project_id": "proj-1", "title": "t"}),
                                          encoding="utf-8")
    (ark / "WORK_RUN_STATE.json").write_text("{truncated mid-write", encoding="utf-8")

    entries = ProjectIndex(str(tmp_path))._client_projects()
    assert entries, "the project must still be listed - hiding it is not the fix"
    entry = entries[0]
    assert entry.lifecycle_state != "RECEIVED", (
        "a state file that could not be parsed must not be reported as a fresh intake")
    assert entry.lifecycle_state in ("UNKNOWN", "UNREADABLE"), entry.lifecycle_state
    assert entry.blockers, "an unreadable state is a blocker the operator must see"


def test_a_readable_work_run_state_is_unaffected(tmp_path):
    """Control: the normal path keeps its real status."""
    from core.orchestration.project_index import ProjectIndex
    ark = tmp_path / "proj-2" / "40_ark_work"
    ark.mkdir(parents=True)
    (ark / "WORK_PACKET.json").write_text(json.dumps({"project_id": "proj-2"}), encoding="utf-8")
    (ark / "WORK_RUN_STATE.json").write_text(json.dumps({"status": "EXECUTING"}), encoding="utf-8")
    assert ProjectIndex(str(tmp_path))._client_projects()[0].lifecycle_state == "EXECUTING"


# --- a directory is not a verdict -----------------------------------------------------------------

def test_a_report_directory_alone_does_not_mean_the_campaign_completed(tmp_path):
    """A worker creates `report/` on its FIRST write, so this read a killed run as finished."""
    from core.orchestration.project_index import ProjectIndex
    scout = tmp_path / "scout" / "camp-1"
    (scout / "report").mkdir(parents=True)
    (scout / "report" / "partial.json").write_text("{}", encoding="utf-8")

    # The legacy-folder branch (a demo/acceptance run that bypassed run-control) is what admits a
    # folder carrying only `report/`, and it is reachable with include_diagnostics=True.
    entries = [e for e in ProjectIndex(str(tmp_path))._scout_campaigns(include_diagnostics=True)
               if "camp-1" in e.project_id]
    assert entries, "the campaign must still be listed"
    assert entries[0].lifecycle_state != "COMPLETED", (
        "the existence of a report directory is not evidence that the run finished")


# --- the classification must stay complete as states are added -----------------------------------

def test_every_work_run_state_is_explicitly_classified_for_health():
    """`_HEALTH.get(status, "ok")` defaults to healthy, which is right for the known in-flight
    states and wrong for anything nobody classified. The default is kept (flipping it would mark
    legitimately progressing work as a problem), and this test is what stops it absorbing a NEW
    state silently: add one to `WORK_RUN_STATES` without deciding its health and this fails.
    """
    from core.dashboard.read_model import _HEALTH
    from core.orchestration.project_index import _CLIENT_PROGRESS
    from core.schemas.work_run_state import WORK_RUN_STATES

    # States that legitimately mean "progressing normally"; everything else must be named in _HEALTH.
    in_flight = {"RECEIVED", "INTAKE_COMPLETE", "READY_TO_EXECUTE", "EXECUTING",
                 "EXECUTION_PARTIAL", "VERIFYING"}
    unclassified = sorted(s for s in WORK_RUN_STATES if s not in _HEALTH and s not in in_flight)
    assert not unclassified, (
        "these lifecycle states would silently inherit health 'ok': " + repr(unclassified))

    missing_progress = sorted(s for s in WORK_RUN_STATES if s not in _CLIENT_PROGRESS)
    assert not missing_progress, (
        "these lifecycle states would silently report 0% progress: " + repr(missing_progress))


def test_an_unreadable_state_is_not_healthy():
    from core.dashboard.read_model import health_of
    assert health_of("UNKNOWN") != "ok"
