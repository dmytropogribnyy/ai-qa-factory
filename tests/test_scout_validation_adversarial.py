"""Seven ways a run can be wrong, and a validator that has to notice each one.

`VALIDATED` is a claim that every applicable check passed. The way that claim goes bad is never a
crash — it is a check that cannot observe the thing it is named after, so it passes over a run that
is in fact broken. `_observed_modules` was the clearest case: it collapsed per-target receipts into
one flat map with `setdefault`, so the FIRST target answered for all of them and a second target
that never ran accessibility was not merely unreported, it was unobservable.

So each test here starts from a run that genuinely validates, breaks exactly one thing, and asserts
both that the right check caught it AND that the report as a whole stopped saying VALIDATED. A test
that only asserts the second half would pass on a validator that fails everything.
"""
from __future__ import annotations

import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from core.scout.run_validation import FAIL, PARTIAL, PASS, validate_run
from core.scout.store import RunStore

_CONFIG = {"campaign_name": "adhoc", "run_purpose": "acceptance", "browser_mode": "static",
           "video_mode": "manual", "coverage": "adaptive", "max_pages_per_site": 12,
           "max_sites": 5, "concurrency": 1, "check_families": ["seo"]}


def _check(report, check_id):
    return next(c for c in report.checks if c.check_id == check_id)


def _run(tmp_path, run_id="adv-run", *, targets=2):
    """A plain Scout run with nothing wrong with it."""
    from core.scout.media_probe import sha256_of
    seeds = [f"https://t{n}.example/" for n in range(1, targets + 1)]
    config = {**_CONFIG, "seeds": seeds,
              "intake": {"kind": "paste", "rows_read": targets, "rows_accepted": targets,
                         "rows_rejected": 0, "duplicates": 0, "rows_capped": 0}}
    store = RunStore(str(tmp_path), run_id)
    store.write_config(config)
    prospects = {}
    for n in range(1, targets + 1):
        pid = f"0{n}"
        prospects[pid] = {"status": "DONE", "url": seeds[n - 1],
                          "verified_findings": 1, "verified_defects": 1}
        store.save_prospect_artifact(pid, "findings.json", {"verified": [
            {"title": f"Issue {n}", "severity": "high", "signature": f"s{n}"}]})
        store.save_prospect_artifact(pid, "observation.json",
                                     {"axe_status": "ok", "perf": {"load_ms": 800}})
        store.save_prospect_artifact(pid, "screenshots.json", {"captured": 1})
        shot = store.prospect_dir(pid) / "landing.png"
        shot.write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(64))
        store.save_prospect_artifact(pid, "evidence_manifest.json", {
            "entries": [{"ref": "landing.png", "sha256": sha256_of(shot)}]})
    store.save_state({"status": "COMPLETED", "started_at": "2026-07-28T09:00:00+00:00",
                      "finished_at": "2026-07-28T09:20:00+00:00", "config": config,
                      # The stamp the engine writes at start. A run that cannot say which code
                      # produced it is not a clean baseline for the tests below.
                      "execution_build": {"sha": "advsha0000001", "build": "advsha0000001"},
                      "prospects": prospects})
    store.append_event({"event": "run_started"})
    for pid in prospects:
        store.append_event({"event": "prospect_done", "prospect": pid})
    store.append_event({"event": "run_finished"})
    return store


def _discovery(tmp_path, *, child_purpose="acceptance", child_status="COMPLETED",
               child_exists=True, candidates=6):
    """A discovery campaign that promotes one candidate into its own run."""
    campaign = RunStore(str(tmp_path), "camp-adv")
    config = {**_CONFIG, "browser_mode": "static",
              "intake": {"kind": "discovery", "query": "dental clinics, DE"}}
    campaign.write_config(config)
    records = [{"registrable_domain": "found.example", "candidate_id": "c0",
                "promotion_decision": "promoted", "promoted_scout_run": "camp-adv-promo-01"}]
    records += [{"registrable_domain": f"r{n}.example", "candidate_id": f"c{n}",
                 "promotion_decision": "not_promoted"} for n in range(1, candidates)]
    campaign.save_state({
        "status": "COMPLETED", "started_at": "2026-07-28T09:00:00+00:00",
        "finished_at": "2026-07-28T09:20:00+00:00", "config": config,
        "execution_build": {"sha": "advsha0000001", "build": "advsha0000001"},
        "counts": {"discovered": candidates, "eligible": 1, "promoted": 1,
                   "rejected": candidates - 1, "duplicates": 0, "already_analyzed": 0,
                   "qa_analyzed": 1, "failed": 0},
        "candidates": records, "prospects": {}})
    campaign.append_event({"event": "campaign_started"})
    campaign.append_event({"event": "campaign_finished"})
    if not child_exists:
        return campaign, None
    child = RunStore(str(tmp_path), "camp-adv-promo-01")
    child.write_config({**_CONFIG, "run_purpose": child_purpose,
                        "seeds": ["https://found.example/"],
                        "intake": {"kind": "discovery", "source_name": "camp-adv"}})
    child.save_state({"status": child_status,
                      "execution_build": {"sha": "advsha0000001", "build": "advsha0000001"},
                      "prospects": {
                          "01": {"status": "DONE", "url": "https://found.example/",
                                 "verified_findings": 1, "verified_defects": 1}}})
    child.save_prospect_artifact("01", "findings.json", {"verified": [
        {"title": "Issue", "severity": "high", "signature": "s0"}]})
    child.save_prospect_artifact("01", "observation.json",
                                 {"axe_status": "ok", "perf": {"load_ms": 800}})
    child.save_prospect_artifact("01", "screenshots.json", {"captured": 1})
    return campaign, child


# --- the baseline the seven tests break -----------------------------------------------------------

def test_an_untouched_run_validates(tmp_path):
    """Without this, every test below would pass on a validator that simply fails everything."""
    from core.scout.campaign_service import CampaignService

    _run(tmp_path)

    # With the read model: a report that never compared the screen to the store is INCOMPLETE by
    # rule, so a VALIDATED baseline has to supply one.
    report = validate_run(str(tmp_path), "adv-run", read_model=CampaignService(str(tmp_path)))

    assert report.status == "VALIDATED", [c.to_dict() for c in report.problems()]


# --- 1. an unaccounted discovery candidate --------------------------------------------------------

def test_a_candidate_the_campaign_never_decided_about_is_caught(tmp_path):
    campaign, _child = _discovery(tmp_path)
    state = campaign.load_state()
    state["candidates"][3].pop("promotion_decision")
    campaign.save_state(state)

    report = validate_run(str(tmp_path), "camp-adv")
    check = _check(report, "target_count_arithmetic")

    assert check.status == FAIL
    assert check.observed["unaccounted"] == ["c3"]
    assert report.status != "VALIDATED"


def test_records_that_disagree_with_the_published_total_are_caught(tmp_path):
    campaign, _child = _discovery(tmp_path)
    state = campaign.load_state()
    state["candidates"].pop()                       # a candidate silently lost after publication
    campaign.save_state(state)

    check = _check(validate_run(str(tmp_path), "camp-adv"), "target_count_arithmetic")

    assert check.status == FAIL
    assert check.observed["accounted"] == 5 and check.observed["declared_discovered"] == 6


# --- the owner's refinement: a running child is not a missing one ---------------------------------

def test_a_promoted_child_still_running_is_partial_not_failed(tmp_path):
    """A healthy in-flight campaign must never read as corrupt."""
    _discovery(tmp_path, child_status="RUNNING")

    check = _check(validate_run(str(tmp_path), "camp-adv"), "target_count_arithmetic")

    assert check.status == PARTIAL
    assert check.observed["running_children"] == ["camp-adv-promo-01"]
    assert check.observed["missing_children"] == []


def test_a_promoted_child_that_does_not_exist_is_failed(tmp_path):
    _discovery(tmp_path, child_exists=False)

    check = _check(validate_run(str(tmp_path), "camp-adv"), "target_count_arithmetic")

    assert check.status == FAIL
    assert check.observed["missing_children"] == ["camp-adv-promo-01"]


def test_a_candidate_held_for_human_review_is_partial(tmp_path):
    campaign, _child = _discovery(tmp_path)
    state = campaign.load_state()
    state["candidates"][2]["promotion_decision"] = "held_for_review"
    campaign.save_state(state)

    check = _check(validate_run(str(tmp_path), "camp-adv"), "target_count_arithmetic")

    assert check.status == PARTIAL
    assert check.observed["buckets"]["held_for_review"] == 1


# --- intake provenance: where the target list came from -------------------------------------------

def test_a_run_that_cannot_say_where_its_targets_came_from_is_not_validated(tmp_path):
    """Fail closed: an unrecorded source is UNKNOWN, never assumed to be fine."""
    store = _run(tmp_path)
    config = json.loads((store.root / "config.json").read_text(encoding="utf-8"))
    config.pop("intake")
    (store.root / "config.json").unlink()
    store.write_config(config)

    report = validate_run(str(tmp_path), "adv-run")

    assert _check(report, "intake_provenance").status == "UNKNOWN"
    assert report.status != "VALIDATED"


def test_an_uploaded_list_that_does_not_name_its_file_is_caught(tmp_path):
    store = _run(tmp_path)
    config = json.loads((store.root / "config.json").read_text(encoding="utf-8"))
    config["intake"] = {**config["intake"], "kind": "upload"}      # no source_name
    (store.root / "config.json").unlink()
    store.write_config(config)

    check = _check(validate_run(str(tmp_path), "adv-run"), "intake_provenance")

    assert check.status == FAIL
    assert "which file" in check.explanation


def test_intake_accounting_that_does_not_add_up_is_caught(tmp_path):
    """Every row read ends in exactly one bucket, including the ones the site limit cut off."""
    store = _run(tmp_path)
    config = json.loads((store.root / "config.json").read_text(encoding="utf-8"))
    config["intake"] = {**config["intake"], "rows_read": 9}        # 9 read, 2 accounted for
    (store.root / "config.json").unlink()
    store.write_config(config)

    check = _check(validate_run(str(tmp_path), "adv-run"), "intake_provenance")

    assert check.status == FAIL
    assert check.observed["accounted"] == 2


def test_a_truncated_list_still_balances(tmp_path):
    """The site limit cutting a list short must not read as rows vanishing."""
    store = _run(tmp_path)
    config = json.loads((store.root / "config.json").read_text(encoding="utf-8"))
    config["intake"] = {**config["intake"], "rows_read": 9, "rows_capped": 7}
    (store.root / "config.json").unlink()
    store.write_config(config)

    assert _check(validate_run(str(tmp_path), "adv-run"), "intake_provenance").status == PASS


# --- 2. a missing module receipt on the SECOND target ---------------------------------------------

def test_a_module_receipt_missing_on_the_second_target_is_seen(tmp_path):
    """The exact blind spot: a flat receipts map let the first target answer for the second."""
    store = _run(tmp_path)
    (store.prospect_dir("02") / "observation.json").unlink()

    report = validate_run(str(tmp_path), "adv-run")
    check = _check(report, "module_receipts")

    assert check.status == PARTIAL
    assert check.observed["01"]["accessibility"] == "ok"
    assert check.observed["02"]["accessibility"] == "not_executed"
    assert "02" in check.explanation
    assert report.status != "VALIDATED"


# --- 3. missing lifecycle events ------------------------------------------------------------------

@pytest.mark.parametrize("dropped", ["run_started", "run_finished"])
def test_a_missing_lifecycle_event_is_caught(tmp_path, dropped):
    """Only counting events that occur too OFTEN left the opposite hole wide open."""
    store = _run(tmp_path)
    events = [json.loads(line) for line in
              (store.root / "events.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    kept = [e for e in events if e.get("event") != dropped]
    (store.root / "events.jsonl").write_text(
        "".join(json.dumps(e) + "\n" for e in kept), encoding="utf-8")

    report = validate_run(str(tmp_path), "adv-run")
    check = _check(report, "activity_no_duplicates")

    assert check.status == FAIL
    assert report.status != "VALIDATED"


# --- 4. cleanup_ok = false ------------------------------------------------------------------------

def test_an_interaction_that_could_not_be_undone_fails(tmp_path):
    """A control changed on someone else's site and not restored is not an observation."""
    store = _run(tmp_path)
    store.save_prospect_artifact("01", "interaction_scenario.json", {
        "scenario": "add_remove", "outcome": "trace", "action_performed": True,
        "cleanup_ok": False})

    report = validate_run(str(tmp_path), "adv-run")
    check = _check(report, "cleanup_result")

    assert check.status == FAIL
    assert check.observed[0]["prospect"] == "01"
    assert report.status != "VALIDATED"


def test_an_interaction_that_never_acted_needs_no_undo(tmp_path):
    """Fail-closed must not become fail-always: nothing was touched, so nothing must be restored."""
    store = _run(tmp_path)
    store.save_prospect_artifact("01", "interaction_scenario.json", {
        "scenario": "add_remove", "outcome": "not_applicable", "action_performed": False,
        "cleanup_ok": None})

    assert _check(validate_run(str(tmp_path), "adv-run"), "cleanup_result").status == PASS


# --- 5. missing contact provenance ----------------------------------------------------------------

def test_a_contact_without_the_page_it_came_from_is_caught(tmp_path):
    store = _run(tmp_path)
    store.save_prospect_artifact("01", "contacts.json", {"schema": "scout-contacts/v1", "public": [
        {"email": "info@t1.example", "source_url": "https://t1.example/contact"}]})
    store.save_prospect_artifact("02", "contacts.json", {"schema": "scout-contacts/v1", "public": [
        {"email": "info@t2.example"}]})           # kept, with nothing to justify it

    report = validate_run(str(tmp_path), "adv-run")
    check = _check(report, "contact_persistence")

    assert check.status == PARTIAL
    assert check.observed[0]["without_provenance"] == ["info@t2.example"]
    assert report.status != "VALIDATED"


# --- 6. a promoted child with the wrong purpose ---------------------------------------------------

def test_a_promoted_child_that_declares_another_purpose_is_caught(tmp_path):
    """An acceptance campaign whose children land in production counters is not isolated."""
    _discovery(tmp_path, child_purpose="production")

    report = validate_run(str(tmp_path), "camp-adv")
    check = _check(report, "purpose_isolation")

    assert check.status == FAIL
    assert check.observed == {"camp-adv-promo-01": "production"}
    assert report.status != "VALIDATED"


# --- 7. a corrupted client package ----------------------------------------------------------------

def _package(tmp_path, run_id, files, *, root="t1.example-qa-evidence-20260728",
             tamper=None, unlisted=None):
    # Hand-crafted hostile ZIPs, but at the CANONICAL export location — the directory the real
    # builder resolves. A tampered package planted where the validator never looks proves nothing.
    from core.scout.client_evidence import client_export_dir
    export = client_export_dir(str(tmp_path), run_id)
    export.mkdir(parents=True, exist_ok=True)
    entries = [{"path": name, "bytes": len(body), "mime": "text/plain",
                "sha256": hashlib.sha256(body).hexdigest()} for name, body in files.items()]
    if tamper:
        next(e for e in entries if e["path"] == tamper)["sha256"] = "0" * 64
    manifest = {"schema": "scout-client-evidence/v2", "root": root, "domain": "t1.example",
                "run_id": run_id, "entries": entries, "findings": []}
    path = export / f"{root}.zip"
    with zipfile.ZipFile(path, "w") as archive:
        for name, body in files.items():
            archive.writestr(f"{root}/{name}", body)
        for name, body in (unlisted or {}).items():
            archive.writestr(f"{root}/{name}", body)
        archive.writestr(f"{root}/manifest.json",
                         json.dumps(manifest, indent=2).encode("utf-8"))
    return path


def test_a_packaged_file_that_no_longer_matches_its_hash_is_caught(tmp_path):
    _run(tmp_path)
    _package(tmp_path, "adv-run", {"QA-Report.html": b"<p>findings</p>"}, tamper="QA-Report.html")

    report = validate_run(str(tmp_path), "adv-run")
    check = _check(report, "client_package")

    assert check.status == FAIL
    assert check.observed[0]["reason"] == "hash mismatch"
    assert report.status != "VALIDATED"


def test_a_manifest_entry_missing_from_the_archive_is_caught(tmp_path):
    _run(tmp_path)
    path = _package(tmp_path, "adv-run", {"QA-Report.html": b"<p>findings</p>",
                                          "Findings.csv": b"Type,Severity\r\n"})
    root = "t1.example-qa-evidence-20260728"
    keep = {n: zipfile.ZipFile(path).read(n) for n in zipfile.ZipFile(path).namelist()
            if not n.endswith("Findings.csv")}
    with zipfile.ZipFile(path, "w") as archive:      # rebuild without the file, manifest unchanged
        for name, body in keep.items():
            archive.writestr(name, body)
    assert f"{root}/Findings.csv" not in zipfile.ZipFile(path).namelist()

    check = _check(validate_run(str(tmp_path), "adv-run"), "client_package")

    assert check.status == FAIL
    assert check.observed["missing"] == ["Findings.csv"]


def test_a_file_the_manifest_never_listed_is_caught(tmp_path):
    """A hash for every member is worthless if a member can arrive without one."""
    _run(tmp_path)
    _package(tmp_path, "adv-run", {"QA-Report.html": b"<p>ok</p>"},
             unlisted={"Evidence/notes.txt": b"an operator note nobody signed for"})

    check = _check(validate_run(str(tmp_path), "adv-run"), "client_package")

    assert check.status == FAIL
    assert check.observed["unlisted"] == [
        "t1.example-qa-evidence-20260728/Evidence/notes.txt"]


def test_a_package_carrying_a_local_path_is_caught(tmp_path):
    _run(tmp_path)
    _package(tmp_path, "adv-run",
             {"QA-Report.html": b"<p>see C:\\Users\\operator\\outputs</p>"})

    check = _check(validate_run(str(tmp_path), "adv-run"), "client_package")

    assert check.status == FAIL
    assert any(leak["reason"] == "absolute local path" for leak in check.observed)


def test_a_package_that_scatters_its_files_is_caught(tmp_path):
    """One root folder, the one the manifest names: a flat ZIP unpacks over the client's desktop."""
    from core.scout.client_evidence import client_export_dir
    _run(tmp_path)
    export = client_export_dir(str(tmp_path), "adv-run")
    export.mkdir(parents=True, exist_ok=True)
    body = b"<p>ok</p>"
    manifest = {"root": "declared-root", "entries": [
        {"path": "QA-Report.html", "sha256": hashlib.sha256(body).hexdigest()}]}
    with zipfile.ZipFile(export / "loose.zip", "w") as archive:
        archive.writestr("elsewhere/QA-Report.html", body)
        archive.writestr("elsewhere/manifest.json", json.dumps(manifest).encode("utf-8"))

    check = _check(validate_run(str(tmp_path), "adv-run"), "client_package")

    assert check.status == FAIL
    assert check.observed["roots"] == ["elsewhere"]


def test_the_package_the_real_builder_writes_is_the_package_validation_checks(tmp_path):
    """The builder exports into client_export_dir() — a slug-and-hash directory — while a validator
    that globs a folder named after the raw run id audits a place nothing ever writes to. Then every
    real deliverable reads NOT_APPLICABLE and a tampered one still validates. The two sides must
    resolve the SAME directory: the genuine package is seen (PASS), and corrupting one member of
    that exact ZIP fails the run."""
    from core.scout.campaign_service import CampaignService
    from core.scout.client_evidence import client_export_dir

    _run(tmp_path)
    result = CampaignService(str(tmp_path)).export_client_evidence("t1.example", run="adv-run")
    built = Path(result["path"])
    assert built.parent == client_export_dir(str(tmp_path), "adv-run")

    check = _check(validate_run(str(tmp_path), "adv-run"), "client_package")
    assert check.status == PASS, check.to_dict()

    # Corrupt one member in place; the manifest beside it still promises the original hash.
    with zipfile.ZipFile(built) as archive:
        blobs = {n: archive.read(n) for n in archive.namelist()}
    victim = next(n for n in blobs if n.endswith("QA-Report.html"))
    blobs[victim] = b"<p>quietly replaced after export</p>"
    with zipfile.ZipFile(built, "w") as archive:
        for name, body in blobs.items():
            archive.writestr(name, body)

    report = validate_run(str(tmp_path), "adv-run")
    check = _check(report, "client_package")

    assert check.status == FAIL
    assert any(row.get("reason") == "hash mismatch" for row in check.observed)
    assert report.status != "VALIDATED"


# --- the build that ran is not the build that checked ---------------------------------------------

def test_the_report_keeps_the_execution_build_apart_from_its_own(tmp_path):
    """Re-validating an old run on today's code must not restamp it with today's SHA."""
    store = _run(tmp_path)

    report = validate_run(str(tmp_path), "adv-run")

    assert report.execution_build == "advsha0000001"
    assert report.to_dict()["execution_build"] == "advsha0000001"
    assert report.build != report.execution_build

    # A run written before the structured stamp, carrying only the older scalar, is still read
    # rather than treated as unknown — the point is never to invent one, not to ignore one.
    state = store.load_state()
    state.pop("execution_build")
    state["build"] = "abc1234"
    store.save_state(state)

    assert validate_run(str(tmp_path), "adv-run").execution_build == "abc1234"
