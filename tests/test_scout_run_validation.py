"""Proving a run, rather than reading its settings back.

Almost everything an operator sees after a run is a configuration value. ``browser_mode=playwright``
means a browser was permitted; ``video_mode=qualified_auto`` means a clip was allowed; a COMPLETED
status means the process ended. None of the three says what happened, and each has been read as
though it did.

These tests hold the separation: a requested value never satisfies a check on its own, a missing
receipt reports UNKNOWN or PARTIAL rather than zero, and ``Validated`` is refused while anything is
unresolved. They also pin the direction of evidence — the report is built from the store upward, so
breaking a file must break the verdict even when every screen still renders happily.
"""
from __future__ import annotations

import json

import pytest

from core.scout.run_validation import (FAIL, NOT_APPLICABLE, PARTIAL, PASS, UNKNOWN, validate_run)
from core.scout.store import RunStore

_CONFIG = {"campaign_name": "acc", "seeds": ["https://fixture.example/"], "browser_mode": "static",
           "coverage": "adaptive", "video_mode": "manual", "run_purpose": "acceptance",
           "max_pages_per_site": 12, "max_sites": 10, "concurrency": 1,
           "check_families": ["accessibility"],
           # Where the one seed came from. Without it the run is honestly UNKNOWN rather than clean.
           "intake": {"kind": "paste", "rows_read": 1, "rows_accepted": 1, "rows_rejected": 0,
                      "duplicates": 0, "rows_capped": 0}}


def _run(tmp_path, *, config=None, prospect=None, findings=1, events=None, run_id="acc-run"):
    """One completed run on disk, in the shape the engine leaves it."""
    cfg = {**_CONFIG, **(config or {})}
    store = RunStore(str(tmp_path), run_id)
    store.write_config(cfg)
    record = {"status": "DONE", "url": "https://fixture.example/", "verified_findings": findings,
              "verified_defects": findings, **(prospect or {})}
    store.save_state({"status": "COMPLETED", "run_id": run_id,
                      "started_at": "2026-07-27T10:00:00+00:00",
                      "finished_at": "2026-07-27T10:05:00+00:00",
                      # The stamp the engine writes at start; without it the run honestly cannot say
                      # which code produced it, and a fixture that omits it is not a clean run.
                      "execution_build": {"sha": "fixturesha001", "build": "fixturesha001"},
                      "config": cfg, "prospects": {"01": record}})
    store.save_prospect_artifact("01", "findings.json", {"verified": [
        {"title": f"Issue {i}", "severity": "high", "signature": f"s{i}"} for i in range(findings)]})
    for event in (events if events is not None else
                  [{"event": "run_started"}, {"event": "prospect_done", "prospect": "01"},
                   {"event": "run_finished"}]):
        store.append_event(event)
    return store


def _check(report, check_id):
    return next(c for c in report.checks if c.check_id == check_id)


# --- the shape of the answer ----------------------------------------------------------------------

def test_a_run_that_does_not_exist_fails_rather_than_passing_vacuously(tmp_path):
    report = validate_run(str(tmp_path), "no-such-run")

    assert report.validated is False
    assert report.status == "FAILED"
    assert _check(report, "run_exists").status == FAIL


def _fully_evidenced(tmp_path):
    """A run where every module left a receipt — the only shape allowed to read VALIDATED."""
    store = _run(tmp_path, config={"browser_mode": "playwright"})
    store.save_prospect_artifact("01", "browser_trace.json", {"backend": "playwright", "passes": []})
    store.save_prospect_artifact("01", "observation.json", {"axe_status": "ok",
                                                            "perf": {"load_ms": 900}})
    store.save_prospect_artifact("01", "screenshots.json", {"captured": 2})
    store.save_prospect_artifact("01", "interaction_scenario.json", {"outcome": "interaction_trace",
                                                                     "cleanup_ok": True})
    from core.scout.media_probe import sha256_of
    entries = []
    for name in ("landing.png", "verification.png"):
        shot = store.prospect_dir("01") / name
        shot.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(64))
        entries.append({"ref": name, "kind": "screenshot", "bytes": shot.stat().st_size,
                        "sha256": sha256_of(shot)})
    store.save_prospect_artifact("01", "evidence_manifest.json", {"entries": entries})
    return store


def test_a_clean_run_validates_and_says_what_it_checked(tmp_path):
    """WITH a read model, because agreement between the store and the screen is not optional: a
    validation that never looked at the derived layer cannot report VALIDATED."""
    from core.scout.campaign_service import CampaignService

    _fully_evidenced(tmp_path)

    report = validate_run(str(tmp_path), "acc-run", read_model=CampaignService(str(tmp_path)))

    assert report.validated is True
    assert report.status == "VALIDATED"
    assert report.purpose == "acceptance"
    assert report.counts[PASS] >= 6
    assert report.problems() == []


def test_the_three_layers_are_reported_separately(tmp_path):
    """The whole point: a requested value and an observed one are never the same field."""
    _run(tmp_path, config={"browser_mode": "playwright"})

    layers = validate_run(str(tmp_path), "acc-run").layers

    assert layers["execution_mode"]["requested"] == "playwright"
    assert layers["execution_mode"]["observed"] == UNKNOWN      # nothing proves a browser ran
    assert layers["targets"]["requested"] == ["https://fixture.example/"]
    assert layers["targets"]["observed"] == {"analyzed": 1}


def test_requesting_a_browser_is_not_evidence_that_one_ran(tmp_path):
    _run(tmp_path, config={"browser_mode": "playwright"})

    report = validate_run(str(tmp_path), "acc-run")
    receipt = _check(report, "browser_receipt")

    assert receipt.status == FAIL
    assert report.validated is False
    assert "no target has browser evidence" in receipt.explanation


def test_a_static_run_is_not_penalised_for_having_no_browser_receipt(tmp_path):
    _run(tmp_path)

    assert _check(validate_run(str(tmp_path), "acc-run"), "browser_receipt").status == NOT_APPLICABLE


def test_a_real_browser_receipt_is_accepted(tmp_path):
    store = _run(tmp_path, config={"browser_mode": "playwright"})
    store.save_prospect_artifact("01", "browser_trace.json", {"backend": "playwright", "passes": []})
    (store.prospect_dir("01") / "landing.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(64))

    assert _check(validate_run(str(tmp_path), "acc-run"), "browser_receipt").status == PASS


def test_some_targets_with_evidence_and_some_without_is_partial_not_pass(tmp_path):
    store = _run(tmp_path, config={"browser_mode": "playwright"})
    state = store.load_state()
    state["prospects"]["02"] = {"status": "DONE", "url": "https://other.example/",
                                "verified_findings": 0, "verified_defects": 0}
    store.save_state(state)
    store.save_prospect_artifact("01", "browser_trace.json", {"backend": "playwright"})
    (store.prospect_dir("01") / "landing.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(64))
    store.save_prospect_artifact("02", "findings.json", {"verified": []})

    report = validate_run(str(tmp_path), "acc-run")

    assert _check(report, "browser_receipt").status == PARTIAL
    assert report.validated is False


# --- lying counters -------------------------------------------------------------------------------

def test_a_summary_count_that_disagrees_with_the_records_fails(tmp_path):
    """The exact shape of "1 confirmed issue" beside "we can fix 2"."""
    store = _run(tmp_path, findings=1)
    state = store.load_state()
    state["prospects"]["01"]["verified_findings"] = 5
    store.save_state(state)

    report = validate_run(str(tmp_path), "acc-run")

    assert _check(report, "finding_count_consistency").status == FAIL
    assert report.validated is False


def test_a_target_the_run_never_held_is_caught(tmp_path):
    store = _run(tmp_path)
    state = store.load_state()
    state["prospects"]["01"]["url"] = "https://somewhere-else.example/"
    store.save_state(state)

    assert _check(validate_run(str(tmp_path), "acc-run"),
                  "source_intake_consistency").status == FAIL


def test_a_terminal_run_with_no_finish_time_is_not_consistent(tmp_path):
    store = _run(tmp_path)
    state = store.load_state()
    state.pop("finished_at")
    store.save_state(state)

    assert _check(validate_run(str(tmp_path), "acc-run"), "lifecycle_consistency").status == FAIL


def test_a_duplicated_terminal_event_is_caught(tmp_path):
    _run(tmp_path, events=[{"event": "run_started"}, {"event": "prospect_done", "prospect": "01"},
                           {"event": "prospect_done", "prospect": "01"},
                           {"event": "run_finished"}])

    check = _check(validate_run(str(tmp_path), "acc-run"), "activity_no_duplicates")

    assert check.status == FAIL
    assert check.observed["duplicate_completions"] == {"01": 2}


# --- evidence is checked against the disk, not against the record of it ---------------------------

def test_evidence_that_has_gone_missing_breaks_the_verdict(tmp_path):
    store = _run(tmp_path)
    shot = store.prospect_dir("01") / "landing.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(64))
    from core.scout.media_probe import sha256_of
    store.save_prospect_artifact("01", "evidence_manifest.json", {"entries": [
        {"ref": "landing.png", "kind": "screenshot", "bytes": shot.stat().st_size,
         "sha256": sha256_of(shot)}]})
    assert _check(validate_run(str(tmp_path), "acc-run"),
                  "evidence_existence_hashes").status == PASS

    shot.unlink()

    check = _check(validate_run(str(tmp_path), "acc-run"), "evidence_existence_hashes")
    assert check.status == FAIL
    assert check.observed["broken"][0]["reason"] == "missing"


def test_evidence_that_has_changed_since_it_was_hashed_breaks_the_verdict(tmp_path):
    store = _run(tmp_path)
    shot = store.prospect_dir("01") / "landing.png"
    shot.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(64))
    store.save_prospect_artifact("01", "evidence_manifest.json", {"entries": [
        {"ref": "landing.png", "sha256": "0" * 64}]})

    check = _check(validate_run(str(tmp_path), "acc-run"), "evidence_existence_hashes")

    assert check.status == FAIL
    assert check.observed["broken"][0]["reason"] == "hash changed"


def test_a_clip_that_does_not_decode_fails_the_video_check(tmp_path):
    store = _run(tmp_path, config={"video_mode": "qualified_auto"})
    (store.prospect_dir("01") / "interaction.webm").write_bytes(b"definitely not a video")

    check = _check(validate_run(str(tmp_path), "acc-run"), "video_playback")

    assert check.status == FAIL
    assert "does not decode" in check.explanation


def test_a_real_clip_passes_and_is_described_by_its_own_bytes(tmp_path):
    from tests.test_scout_interaction_video import webm_bytes

    store = _run(tmp_path, config={"video_mode": "qualified_auto"})
    (store.prospect_dir("01") / "interaction.webm").write_bytes(webm_bytes())

    check = _check(validate_run(str(tmp_path), "acc-run"), "video_playback")

    assert check.status == PASS
    assert check.observed[0]["duration_s"] == 3.0
    assert len(check.observed[0]["sha256"]) == 64


def test_no_clip_under_an_automatic_policy_is_a_policy_outcome_not_a_failure(tmp_path):
    _run(tmp_path, config={"video_mode": "qualified_auto"})

    check = _check(validate_run(str(tmp_path), "acc-run"), "video_playback")

    assert check.status == NOT_APPLICABLE
    assert "policy outcome" in check.explanation


def test_a_temporary_recording_directory_left_behind_is_caught(tmp_path):
    store = _run(tmp_path)
    (store.prospect_dir("01") / "_scenariotmp").mkdir(parents=True)

    assert _check(validate_run(str(tmp_path), "acc-run"), "cleanup_result").status == FAIL


# --- honest unknowns ------------------------------------------------------------------------------

def test_a_run_written_before_purposes_existed_is_unknown_not_invented(tmp_path):
    _run(tmp_path, config={"run_purpose": ""})

    check = _check(validate_run(str(tmp_path), "acc-run"), "purpose_isolation")

    assert check.status == UNKNOWN
    assert "never swept" in check.explanation


def test_a_module_with_no_receipt_reports_not_executed_rather_than_clean(tmp_path):
    _run(tmp_path)

    check = _check(validate_run(str(tmp_path), "acc-run"), "module_receipts")

    assert check.status == PARTIAL
    # Semantic, not prose: the receipt value and the "rather than clean" contract are what this
    # guards. Pinning one contiguous sentence made it fail when the explanation grew to distinguish
    # an absent receipt from a module that was tried and could not run.
    assert "not_executed" in str(check.observed), check.observed
    assert "rather than" in check.explanation and "clean" in check.explanation, check.explanation


def test_an_unresolved_check_blocks_the_validated_badge(tmp_path):
    _run(tmp_path)

    report = validate_run(str(tmp_path), "acc-run")

    assert any(c.status in (FAIL, PARTIAL, UNKNOWN) for c in report.checks)
    assert report.validated is False
    assert report.status in ("PARTIAL", "INCOMPLETE", "FAILED")


# --- the report itself ----------------------------------------------------------------------------

def test_the_report_is_written_where_a_reviewer_can_find_it(tmp_path):
    _run(tmp_path)

    validate_run(str(tmp_path), "acc-run", write=True)

    path = tmp_path / "scout" / "acc-run" / "run_validation.json"
    payload = json.loads(path.read_text(encoding="utf-8"))

    assert payload["schema"] == "scout-run-validation/v1"
    assert payload["run_id"] == "acc-run"
    assert {"check_id", "status", "expected", "observed", "explanation", "evidence_refs"} <= set(
        payload["checks"][0])
    assert payload["generated_at"] and "build" in payload


def test_the_read_model_is_compared_against_the_store_not_trusted_as_it(tmp_path):
    class _Disagreeing:
        def target_detail(self, domain, run=""):
            return {"domain": domain, "findings": [{"severity": "high", "title": "invented"},
                                                   {"severity": "high", "title": "also invented"}]}

    _run(tmp_path, findings=1)

    report = validate_run(str(tmp_path), "acc-run", read_model=_Disagreeing())
    check = _check(report, "surface_agreement")

    assert check.status == FAIL
    assert check.observed[0]["store"] == 1 and check.observed[0]["shown"] == 2


# --- what the first live discovery run exposed ----------------------------------------------------

def _discovery(tmp_path, *, promoted="camp-1-promo-01"):
    """A discovery campaign holds no targets itself; it promotes them into their own runs."""
    campaign = RunStore(str(tmp_path), "camp-1")
    campaign.write_config({"campaign_name": "acc", "run_purpose": "acceptance",
                           "browser_mode": "playwright", "video_mode": "manual",
                           "intake": {"kind": "discovery", "query": "dental clinics, DE"}})
    campaign.save_state({
        "status": "COMPLETED", "started_at": "2026-07-27T10:00:00+00:00",
        "finished_at": "2026-07-27T10:20:00+00:00",
        "execution_build": {"sha": "fixturesha001", "build": "fixturesha001"},
        "config": {"campaign_name": "acc", "run_purpose": "acceptance",
                   "browser_mode": "playwright", "video_mode": "manual"},
        "counts": {"discovered": 6, "eligible": 1, "promoted": 1, "rejected": 4,
                   "duplicates": 0, "already_analyzed": 0, "qa_analyzed": 1, "failed": 0},
        # Six discovered candidates, six explicit dispositions. `discovered` is `len(records)` in a
        # real campaign, so a stand that published 6 while persisting 1 was a state the product
        # cannot reach — and it let a campaign that loses a candidate look exactly like a healthy one.
        "candidates": [{"registrable_domain": "found.example", "candidate_id": "c0",
                        "promotion_decision": "promoted", "promoted_scout_run": promoted}]
                      + [{"registrable_domain": f"rejected-{n}.example", "candidate_id": f"c{n}",
                          "promotion_decision": "not_promoted"} for n in range(1, 6)],
        "prospects": {}})
    campaign.append_event({"event": "run_started"})
    campaign.append_event({"event": "run_finished"})
    child = RunStore(str(tmp_path), promoted)
    child.write_config({"campaign_name": "camp-1", "run_purpose": "acceptance",
                        "browser_mode": "playwright", "video_mode": "manual",
                        "seeds": ["https://found.example/"],
                        "intake": {"kind": "discovery", "source_name": "camp-1"}})
    child.save_state({"status": "COMPLETED",
                      "execution_build": {"sha": "fixturesha001", "build": "fixturesha001"},
                      "prospects": {
                          "01": {"status": "DONE", "url": "https://found.example/",
                                 "verified_findings": 1, "verified_defects": 1}}})
    child.save_prospect_artifact("01", "findings.json", {"verified": [
        {"title": "Issue", "severity": "high", "signature": "s0"}]})
    child.save_prospect_artifact("01", "browser_trace.json", {"backend": "playwright"})
    child.save_prospect_artifact("01", "observation.json", {"axe_status": "ok",
                                                            "perf": {"load_ms": 800}})
    child.save_prospect_artifact("01", "screenshots.json", {"captured": 2})
    from core.scout.media_probe import sha256_of
    entries = []
    for name in ("landing.png", "verification.png"):
        shot = child.prospect_dir("01") / name
        shot.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(64))
        entries.append({"ref": name, "sha256": sha256_of(shot)})
    child.save_prospect_artifact("01", "evidence_manifest.json", {"entries": entries})
    return campaign, child


def test_a_discovery_campaign_is_validated_through_the_runs_it_promoted(tmp_path):
    """Validating only the campaign directory found no targets and reported UNKNOWN for work that
    had in fact been done one level down."""
    from core.scout.campaign_service import CampaignService

    _discovery(tmp_path)

    report = validate_run(str(tmp_path), "camp-1", read_model=CampaignService(str(tmp_path)))

    assert _check(report, "browser_receipt").status == PASS
    assert _check(report, "evidence_existence_hashes").status == PASS
    assert _check(report, "target_count_arithmetic").status == PASS
    assert report.validated is True


def test_a_discovery_campaign_counts_its_candidates_not_its_seeds(tmp_path):
    _discovery(tmp_path)

    intake = _check(validate_run(str(tmp_path), "camp-1"), "source_intake_consistency")

    assert intake.status == PASS
    assert intake.observed["candidates"][0] == "found.example"
    assert len(intake.observed["candidates"]) == 6
    assert "given a query, not a target list" in intake.explanation


def test_more_dispositions_than_discoveries_is_caught(tmp_path):
    """The overlapping labels can never be summed against `discovered` — one candidate is often a
    duplicate AND rejected — but each of them is a subset of it, so none may exceed it."""
    campaign, _child = _discovery(tmp_path)
    state = campaign.load_state()
    state["counts"]["rejected"] = 99
    campaign.save_state(state)

    check = _check(validate_run(str(tmp_path), "camp-1"), "target_count_arithmetic")

    assert check.status == FAIL
    assert check.observed["impossible_counters"] == ["rejected"]


def test_the_read_model_is_asked_about_the_run_the_evidence_lives_in(tmp_path):
    """Pinning the campaign id asks for evidence that was never there, gets the correct refusal,
    and then reads as the surfaces disagreeing."""
    seen = []

    class _Recording:
        def target_detail(self, domain, run=""):
            seen.append(run)
            return {"domain": domain, "findings": [{"severity": "high", "title": "Issue"}]}

    _discovery(tmp_path)

    report = validate_run(str(tmp_path), "camp-1", read_model=_Recording())

    assert seen == ["camp-1-promo-01"]
    assert _check(report, "surface_agreement").status == PASS


def test_a_contact_the_engine_wrote_is_not_reported_as_missing(tmp_path):
    """contacts.json is written under "public". Reading a key the engine does not use reported two
    real addresses as an empty contact file — the very failure this check exists to catch."""
    _campaign, child = _discovery(tmp_path)
    child.save_prospect_artifact("01", "contacts.json", {"schema": "scout-contacts/v1", "public": [
        {"email": "sales@found.example", "source_url": "https://found.example/contact"}]})

    check = _check(validate_run(str(tmp_path), "camp-1"), "contact_persistence")

    assert check.status == PASS
    assert check.observed[0]["count"] == 1


def test_a_module_the_policy_switched_off_is_not_reported_as_a_missing_receipt(tmp_path):
    """"Not requested" and "not executed" are different facts."""
    _discovery(tmp_path)                       # video_mode=manual: no interaction was ever asked for

    report = validate_run(str(tmp_path), "camp-1")
    modules = _check(report, "module_receipts")

    assert modules.status == PASS
    # Receipts are per TARGET. A flat {module: outcome} map let the first target answer for all of
    # them, so a second target missing a receipt was not merely unreported but unobservable.
    assert [m["interaction"] for m in modules.observed.values()] == ["not_requested"]


def test_an_automatic_policy_that_produced_nothing_is_still_a_missing_receipt(tmp_path):
    campaign, child = _discovery(tmp_path)
    config = json.loads((child.root / "config.json").read_text(encoding="utf-8"))
    (child.root / "config.json").unlink()
    child.write_config({**config, "video_mode": "qualified_auto"})
    state = campaign.load_state()
    state["config"]["video_mode"] = "qualified_auto"
    campaign.save_state(state)
    campaign_config = json.loads((campaign.root / "config.json").read_text(encoding="utf-8"))
    (campaign.root / "config.json").unlink()
    campaign.write_config({**campaign_config, "video_mode": "qualified_auto"})

    modules = _check(validate_run(str(tmp_path), "camp-1"), "module_receipts")

    assert modules.status == PARTIAL
    assert [m["interaction"] for m in modules.observed.values()] == ["not_executed"]


@pytest.mark.parametrize("status", ["COMPLETED", "FAILED", "STOPPED"])
def test_every_terminal_status_is_checked_the_same_way(tmp_path, status):
    store = _run(tmp_path)
    state = store.load_state()
    state["status"] = status
    store.save_state(state)

    assert _check(validate_run(str(tmp_path), "acc-run"), "lifecycle_consistency").status == PASS
