"""Which code produced a run, recorded by the run rather than inferred afterwards.

A validation report carried one build field, filled from whatever was checked out when the report
was written. Re-validating a finished run on today's code therefore restamped it with today's SHA,
and the one fact a disputed finding needs — which code made it — was overwritten by the act of
checking it. Separating the two fields was the first half; the second half is that something has to
WRITE the executing build, and nothing did, so the separated field could only ever read UNKNOWN.

The rule: the stamp is written once when the run is created, survives resume, restart and any later
validation, and a run created before stamping existed stays UNKNOWN. The alternative to knowing is
saying so — never the current checkout standing in for an unknown one.
"""
from __future__ import annotations

import json

import pytest

from core.scout.run_validation import PARTIAL, PASS, UNKNOWN, validate_run
from core.scout.store import RunStore

_CONFIG = {"campaign_name": "acc", "seeds": ["https://fixture.example/"], "browser_mode": "static",
           "coverage": "adaptive", "video_mode": "manual", "run_purpose": "acceptance",
           "max_pages_per_site": 12, "max_sites": 10, "concurrency": 1,
           "check_families": ["accessibility"],
           "intake": {"kind": "paste", "rows_read": 1, "rows_accepted": 1, "rows_rejected": 0,
                      "duplicates": 0, "rows_capped": 0}}


def _check(report, check_id):
    return next(c for c in report.checks if c.check_id == check_id)


def _run(tmp_path, run_id="build-run", *, stamp="abc123def456"):
    """A finished run carrying the stamp the engine writes at start."""
    store = RunStore(str(tmp_path), run_id)
    store.write_config(_CONFIG)
    state = {"status": "COMPLETED", "started_at": "2026-07-28T09:00:00+00:00",
             "finished_at": "2026-07-28T09:05:00+00:00", "config": _CONFIG,
             "prospects": {"01": {"status": "DONE", "url": "https://fixture.example/",
                                  "verified_findings": 1, "verified_defects": 1}}}
    if stamp is not None:
        state["execution_build"] = {"sha": stamp, "build": stamp[:12],
                                    "product_version": "AI QA Factory v3.2",
                                    "recorded_at": "2026-07-28T09:00:00+00:00"}
    store.save_state(state)
    store.save_prospect_artifact("01", "findings.json", {"verified": [
        {"title": "Issue", "severity": "high", "signature": "s1"}]})
    for event in ({"event": "run_started"}, {"event": "prospect_done", "prospect": "01"},
                  {"event": "run_finished"}):
        store.append_event(event)
    return store


# --- 1. a new run records the build that executed it ----------------------------------------------

def test_the_engine_stamps_the_executing_build_at_start(tmp_path, monkeypatch):
    """Not a fixture: the real engine path, so the stamp cannot exist only in tests."""
    from core import build_identity
    from core.scout.config import ScoutRunConfig
    from core.scout.engine import ScoutEngine

    monkeypatch.setattr(build_identity, "execution_identity",
                        lambda: {"sha": "deadbeefcafe", "build": "deadbeefcafe",
                                 "product_version": "test", "recorded_at": "now"})
    cfg = ScoutRunConfig(campaign_name="acc", seeds=["https://127.0.0.1:1/"],
                         output_dir=str(tmp_path), run_id="engine-run",
                         allowed_local_hosts=frozenset({"127.0.0.1"}), resolve_dns=False)
    store = RunStore(str(tmp_path), "engine-run")
    try:
        ScoutEngine(cfg, store).run()
    except Exception:                     # the scan itself may fail; the stamp is written first
        pass

    state = json.loads((store.root / "state.json").read_text(encoding="utf-8"))
    assert state["execution_build"]["sha"] == "deadbeefcafe"


def test_a_stamped_run_reports_its_own_build(tmp_path):
    _run(tmp_path)

    report = validate_run(str(tmp_path), "build-run")

    assert report.execution_build == "abc123def456"
    assert _check(report, "execution_build_identity").status == PASS


# --- 2. a resume or restart keeps the build that did the work --------------------------------------

def test_resuming_a_run_does_not_restamp_it(tmp_path, monkeypatch):
    """`setdefault`, not assignment: the build that picked a run back up did not do the work."""
    from core import build_identity
    from core.scout.config import ScoutRunConfig
    from core.scout.engine import ScoutEngine

    store = _run(tmp_path, "resume-run", stamp="originalsha01")
    monkeypatch.setattr(build_identity, "execution_identity",
                        lambda: {"sha": "todayssha9999", "build": "todayssha9999",
                                 "product_version": "test", "recorded_at": "now"})
    cfg = ScoutRunConfig(campaign_name="acc", seeds=["https://127.0.0.1:1/"],
                         output_dir=str(tmp_path), run_id="resume-run", resume=True,
                         allowed_local_hosts=frozenset({"127.0.0.1"}), resolve_dns=False)
    try:
        ScoutEngine(cfg, store).run()
    except Exception:
        pass

    state = json.loads((store.root / "state.json").read_text(encoding="utf-8"))
    assert state["execution_build"]["sha"] == "originalsha01"


# --- 3. validating later changes only the validating build ----------------------------------------

def test_revalidating_on_another_build_changes_only_the_validation_build(tmp_path, monkeypatch):
    """The exact erasure this prevents: checking a run must not rewrite what made it."""
    _run(tmp_path, stamp="madebysha001")
    from core.scout import run_validation

    monkeypatch.setattr(run_validation, "_build_marker", lambda: "checkedbysha2")
    report = validate_run(str(tmp_path), "build-run")
    payload = report.to_dict()

    assert payload["execution_build"] == "madebysha001"
    assert payload["build"] == "checkedbysha2"
    assert payload["execution_build"] != payload["build"]


def test_the_two_fields_are_both_present_in_the_written_report(tmp_path):
    _run(tmp_path)
    validate_run(str(tmp_path), "build-run", write=True)

    written = json.loads((RunStore(str(tmp_path), "build-run").root / "run_validation.json")
                         .read_text(encoding="utf-8"))

    assert written["execution_build"] == "abc123def456"
    assert "build" in written


# --- 4. a run that recorded nothing is not given a SHA --------------------------------------------

def test_a_legacy_run_without_the_stamp_stays_unknown(tmp_path, monkeypatch):
    """Fail closed: the alternative to knowing is saying so, not the current checkout."""
    _run(tmp_path, "legacy-run", stamp=None)
    from core.scout import run_validation

    monkeypatch.setattr(run_validation, "_build_marker", lambda: "checkedbysha2")
    report = validate_run(str(tmp_path), "legacy-run")

    assert report.execution_build == UNKNOWN
    assert report.build == "checkedbysha2"
    assert _check(report, "execution_build_identity").status == UNKNOWN
    assert report.status != "VALIDATED"


# --- parent and child are recorded and checked apart ----------------------------------------------

def _discovery(tmp_path, *, parent="parentsha0001", child="childsha00001"):
    campaign = RunStore(str(tmp_path), "camp-build")
    config = {**_CONFIG, "intake": {"kind": "discovery", "query": "dental clinics"}}
    campaign.write_config(config)
    state = {"status": "COMPLETED", "started_at": "2026-07-28T09:00:00+00:00",
             "finished_at": "2026-07-28T09:20:00+00:00", "config": config,
             "counts": {"discovered": 1, "promoted": 1, "eligible": 1, "rejected": 0,
                        "duplicates": 0, "already_analyzed": 0, "qa_analyzed": 1, "failed": 0},
             "candidates": [{"registrable_domain": "found.example", "candidate_id": "c0",
                             "promotion_decision": "promoted",
                             "promoted_scout_run": "camp-build-promo-01"}],
             "prospects": {}}
    if parent:
        state["execution_build"] = {"sha": parent, "build": parent}
    campaign.save_state(state)
    campaign.append_event({"event": "campaign_started"})
    campaign.append_event({"event": "campaign_finished"})

    kid = RunStore(str(tmp_path), "camp-build-promo-01")
    kid.write_config({**_CONFIG, "intake": {"kind": "discovery", "source_name": "camp-build"}})
    child_state = {"status": "COMPLETED", "prospects": {
        "01": {"status": "DONE", "url": "https://found.example/", "verified_findings": 1,
               "verified_defects": 1}}}
    if child:
        child_state["execution_build"] = {"sha": child, "build": child}
    kid.save_state(child_state)
    kid.save_prospect_artifact("01", "findings.json", {"verified": [
        {"title": "Issue", "severity": "high", "signature": "s0"}]})
    kid.save_prospect_artifact("01", "observation.json", {"axe_status": "ok",
                                                          "perf": {"load_ms": 800}})
    kid.save_prospect_artifact("01", "screenshots.json", {"captured": 1})
    return campaign, kid


def test_a_promoted_child_records_its_own_build_separately(tmp_path):
    """A long campaign can promote a run after the checkout under it moved. Both facts, kept apart."""
    _discovery(tmp_path)

    check = _check(validate_run(str(tmp_path), "camp-build"), "execution_build_identity")

    assert check.status == PASS
    assert check.observed["execution_build"] == "parentsha0001"
    assert check.observed["children"] == {"camp-build-promo-01": "childsha00001"}
    assert check.observed["children_match_parent"] is False


def test_a_child_that_recorded_no_build_is_partial_not_borrowed_from_its_parent(tmp_path):
    _discovery(tmp_path, child=None)

    check = _check(validate_run(str(tmp_path), "camp-build"), "execution_build_identity")

    assert check.status == PARTIAL
    assert check.observed["children"] == {"camp-build-promo-01": UNKNOWN}
    assert "does not say which code executed it" in check.explanation


@pytest.mark.parametrize("same", [True, False])
def test_matching_builds_are_reported_without_being_required(tmp_path, same):
    """Differing builds are a fact to record, not a failure to raise."""
    _discovery(tmp_path, parent="samesha000001",
               child="samesha000001" if same else "othersha00001")

    check = _check(validate_run(str(tmp_path), "camp-build"), "execution_build_identity")

    assert check.status == PASS
    assert check.observed["children_match_parent"] is same
