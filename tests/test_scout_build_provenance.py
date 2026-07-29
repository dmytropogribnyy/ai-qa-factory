"""Which code made a result, which code checked it, and which code packaged it — three questions.

A run already records the build that executed it, so re-validating an old run cannot restamp it.
This module pins what that separation is worth once the values start travelling:

* A process started from a working tree is NOT the commit it started from. The stamp records both
  the commit and the honest name (``<sha> + local changes``), and every reader that reached for the
  bare SHA quietly promoted a dirty build to a clean commit — the one claim the marker exists to
  prevent.
* The report named the executing build explicitly and left the validating one as ``build``, a name
  that says nothing about which of the two it is. A machine consumer choosing between them is
  guessing.
* The client package carried ONE build: the one that zipped it. Re-exporting a months-old run today
  therefore printed today's build beside findings today's code never produced.
* And the report a run writes for itself skipped the surface check entirely, so the artifact most
  likely to be read unattended was the one that could reach VALIDATED without anyone comparing the
  operator's screen to the store.
"""
from __future__ import annotations

import json

import pytest

from core.scout.run_validation import UNKNOWN, validate_run
from core.scout.store import RunStore

_CONFIG = {"campaign_name": "acc", "seeds": ["https://fixture.example/"], "browser_mode": "static",
           "coverage": "adaptive", "video_mode": "manual", "run_purpose": "acceptance",
           "max_pages_per_site": 12, "max_sites": 10, "concurrency": 1,
           "check_families": ["accessibility"],
           "intake": {"kind": "paste", "rows_read": 1, "rows_accepted": 1, "rows_rejected": 0,
                      "duplicates": 0, "rows_capped": 0}}
_DIRTY = "madebysha001 + local changes"
_DOMAIN = "fixture.example"


def _check(report, check_id):
    return next((c for c in report.checks if c.check_id == check_id), None)


def _run(tmp_path, run_id="dirty-run", *, sha="madebysha001", build=_DIRTY):
    """A finished run stamped by a process that was started from a MODIFIED working tree."""
    store = RunStore(str(tmp_path), run_id)
    store.write_config(_CONFIG)
    store.save_state({"status": "COMPLETED", "started_at": "2026-07-28T09:00:00+00:00",
                      "finished_at": "2026-07-28T09:05:00+00:00", "config": _CONFIG,
                      "execution_build": {"sha": sha, "build": build,
                                          "product_version": "AI QA Factory v3.2",
                                          "recorded_at": "2026-07-28T09:00:00+00:00"},
                      "prospects": {"01": {"status": "DONE", "url": f"https://{_DOMAIN}/",
                                           "verified_findings": 1, "verified_defects": 1}}})
    store.save_prospect_artifact("01", "findings.json", {"verified": [
        {"title": "Issue", "severity": "high", "signature": "s1", "url": f"https://{_DOMAIN}/"}]})
    for event in ({"event": "run_started"}, {"event": "prospect_done", "prospect": "01"},
                  {"event": "run_finished"}):
        store.append_event(event)
    return store


# --- 1. a dirty build never reads as a clean commit -----------------------------------------------

def test_a_dirty_execution_build_is_not_reported_as_a_clean_commit(tmp_path):
    """The stamp holds both names. Reading the bare SHA is what turned "and some uncommitted edits"
    into a commit anybody can check out and fail to reproduce."""
    _run(tmp_path)

    assert validate_run(str(tmp_path), "dirty-run").execution_build == _DIRTY


def test_a_promoted_child_keeps_its_own_local_changes_marker(tmp_path):
    _run(tmp_path, "child-run")
    parent = RunStore(str(tmp_path), "parent-run")
    parent.write_config(_CONFIG)
    parent.save_state({"status": "COMPLETED", "started_at": "2026-07-28T09:00:00+00:00",
                       "finished_at": "2026-07-28T09:05:00+00:00", "config": _CONFIG,
                       "prospects": {},
                       "candidates": [{"candidate_id": "c1", "registrable_domain": _DOMAIN,
                                       "promotion_decision": "promoted",
                                       "promoted_scout_run": "child-run"}]})

    check = _check(validate_run(str(tmp_path), "parent-run"), "execution_build_identity")

    assert check.observed["children"]["child-run"] == _DIRTY


# --- 2. the report says which build is which ------------------------------------------------------

def test_the_report_names_the_validating_build_explicitly(tmp_path, monkeypatch):
    """``build`` alone cannot say whether it made the run or checked it. Both names, side by side."""
    from core.scout import run_validation

    _run(tmp_path)
    monkeypatch.setattr(run_validation, "_build_marker", lambda: "checkedbysha2")
    payload = validate_run(str(tmp_path), "dirty-run").to_dict()

    assert payload["validation_build"] == "checkedbysha2"
    assert payload["execution_build"] == _DIRTY
    assert payload["build"] == payload["validation_build"], "the old key stays, as the same value"


def test_the_validating_build_keeps_its_local_changes_marker(tmp_path, monkeypatch):
    """A report written from a modified tree is not evidence produced by the commit it names."""
    from core import build_identity
    from core.scout import run_validation

    _run(tmp_path)
    monkeypatch.setattr(build_identity, "current_identity",
                        lambda *a, **k: {"running_sha": "checkedbysha2",
                                         "running_build": "checkedbysha2 + local changes"})

    assert run_validation._build_marker() == "checkedbysha2 + local changes"


# --- 3. the report a run writes for itself checks the surfaces ------------------------------------

def test_a_report_with_no_read_model_is_not_validated(tmp_path):
    """The rule stated once: agreement between the store and the screen is not OPTIONAL. A report
    that could not check it says so, and an unchecked surface can never read VALIDATED."""
    _run(tmp_path)

    report = validate_run(str(tmp_path), "dirty-run")

    assert _check(report, "surface_agreement").status == UNKNOWN
    assert report.validated is False


def test_the_report_a_run_writes_for_itself_checks_the_surfaces(tmp_path):
    """The artifact most likely to be read unattended was the one skipping the check."""
    from core.scout.config import ScoutRunConfig
    from core.scout.engine import ScoutEngine

    cfg = ScoutRunConfig(campaign_name="acc", seeds=["https://127.0.0.1:1/"],
                         output_dir=str(tmp_path), run_id="auto-run",
                         allowed_local_hosts=frozenset({"127.0.0.1"}), resolve_dns=False)
    store = RunStore(str(tmp_path), "auto-run")
    try:
        ScoutEngine(cfg, store).run()
    except Exception:                      # the scan may fail; the report is written regardless
        pass

    written = json.loads((store.root / "run_validation.json").read_text(encoding="utf-8"))
    surface = next((c for c in written["checks"] if c["check_id"] == "surface_agreement"), None)

    assert surface is not None, "the run validated itself without ever looking at the read model"
    assert surface["status"] != UNKNOWN, "a read model was available and was not used"


# --- 4. the client package separates the run's build from the packaging build ---------------------

@pytest.fixture
def packaged(tmp_path, monkeypatch):
    from core.scout import client_evidence
    from core.scout.campaign_service import CampaignService
    from core.scout.client_evidence import build_client_evidence_bundle
    from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry

    _run(tmp_path)
    AnalyzedSiteRegistry(str(tmp_path)).record_analysis(_DOMAIN, status=ANALYZED,
                                                        campaign_id="dirty-run")
    # Exported LATER, by a different build than the one that produced the findings.
    monkeypatch.setattr(client_evidence, "_build_identity", lambda: "packagedbysha9")
    detail = CampaignService(str(tmp_path)).target_detail(_DOMAIN, run="dirty-run")
    bundle = build_client_evidence_bundle(str(tmp_path), run_id="dirty-run", prospect_id="01",
                                          domain=_DOMAIN, detail=detail)
    import zipfile
    with zipfile.ZipFile(bundle.path) as archive:
        name = next(n for n in archive.namelist() if n.endswith("manifest.json"))
        return json.loads(archive.read(name).decode("utf-8"))


def test_the_manifest_names_the_build_that_produced_the_findings(packaged):
    assert packaged["execution_build"] == _DIRTY


def test_the_manifest_names_the_build_that_packaged_it_separately(packaged):
    """Re-exporting an old run must not attribute its findings to today's code."""
    assert packaged["package_build"] == "packagedbysha9"
    assert packaged["execution_build"] != packaged["package_build"]


# --- 5. and the operator sees both ----------------------------------------------------------------

def test_the_run_page_shows_executed_by_and_validated_by_separately(tmp_path, monkeypatch):
    from core.scout.dashboard import start_dashboard
    from core.scout.service import ScoutService
    from tests.scout_seam_fixtures import get, no_tavily

    no_tavily(monkeypatch)
    _run(tmp_path)
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        _, html = get(f"{url}/scout/run?id=dirty-run")
    finally:
        server.shutdown()

    assert "Executed by" in html
    assert "Validated by" in html
    assert "local changes" in html, "the page showed a dirty build as a clean commit"
