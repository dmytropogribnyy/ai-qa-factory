"""Scout — the read model, not just the UI, must fail closed for an incomplete analysis.

target_detail() previously treated only MANUAL_ACTION_REQUIRED and FAILED as incomplete, so a
PENDING or SKIPPED prospect loaded findings.json and reproduction.json. The Target PAGE hides that
(dashboard.py:2655 gates any non-empty non-DONE status), but /api/scout/target returns the read model
verbatim and the unpinned page never reaches that gate. Confirmed findings must come from a completed
analysis on EVERY surface.
"""
from __future__ import annotations

import json

from core.scout.campaign_service import CampaignService
from core.scout.dashboard import start_dashboard
from core.scout.service import ScoutService
from core.scout.store import RunStore
from tests.scout_seam_fixtures import RUN_A, build_seam_stand, get, no_tavily


def test_pending_target_exposes_no_findings_through_the_read_model(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    det = CampaignService(str(tmp_path)).target_detail("delta.example", run=RUN_A)

    assert det["prospect_status"] == "PENDING"
    assert det["analysis_complete"] is False
    assert det["findings"] == []                 # the artifact exists, but the analysis never completed
    assert det.get("reproduction") in (None, {})


def test_skipped_target_exposes_no_findings_through_the_read_model(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    det = CampaignService(str(tmp_path)).target_detail("eta.example", run=RUN_A)

    assert det["prospect_status"] == "SKIPPED"
    assert det["analysis_complete"] is False
    assert det["findings"] == []


def test_an_unrecognized_future_status_fails_closed(tmp_path, monkeypatch):
    """Unknown must not mean 'assume complete' — a status this build has never seen still may not
    present artifact rows as confirmed findings."""
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    store = RunStore(str(tmp_path), RUN_A)
    state = store.load_state()
    state["prospects"]["04-delta"]["status"] = "QUARANTINED"      # a status from some future engine
    store.save_state(state)

    det = CampaignService(str(tmp_path)).target_detail("delta.example", run=RUN_A)
    assert det["findings"] == []
    assert det["analysis_complete"] is False


def test_empty_legacy_status_keeps_loading_its_artifact(tmp_path, monkeypatch):
    """The sole exemption (invariant 3): a historical run with no status at all keeps its existing
    backward-compatible behaviour."""
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    store = RunStore(str(tmp_path), RUN_A)
    state = store.load_state()
    state["prospects"]["04-delta"]["status"] = ""                 # legacy seed data
    store.save_state(state)

    det = CampaignService(str(tmp_path)).target_detail("delta.example", run=RUN_A)
    assert len(det["findings"]) == 2
    assert det["analysis_complete"] is None                       # genuinely unknown, not False


def test_done_target_is_untouched_by_the_fail_closed_rule(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    det = CampaignService(str(tmp_path)).target_detail("alpha.example", run=RUN_A)

    assert det["analysis_complete"] is True
    assert len(det["findings"]) == 5


def test_read_api_does_not_leak_a_pending_targets_findings(tmp_path, monkeypatch):
    """The route that returns the read model verbatim — the surface the UI gate never covers."""
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        status, body = get(f"{url}/api/scout/target?run={RUN_A}&domain=delta.example")
    finally:
        server.shutdown()

    assert status == 200
    payload = json.loads(body)
    assert payload["findings"] == []
    assert "delta.example: delta (high)" not in body       # not anywhere in the response, either


def test_unpinned_target_page_does_not_render_a_pending_targets_findings(tmp_path, monkeypatch):
    """Without ?run= the page never reaches the gate at dashboard.py:2655 — the read model is the
    only thing standing between the operator and an unconfirmed finding."""
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        status, html = get(f"{url}/scout/target?domain=delta.example")
    finally:
        server.shutdown()

    assert status == 200
    assert "delta.example: delta (high)" not in html


def test_a_prospect_absent_from_state_never_borrows_its_own_artifacts(tmp_path, monkeypatch):
    """Task 2 found this state: an interrupt during the FIRST prospect leaves state["prospects"]
    empty while findings.json is already on disk. The read model must fail honestly rather than
    resolve the artifacts by any other route."""
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    store = RunStore(str(tmp_path), RUN_A)
    state = store.load_state()
    del state["prospects"]["04-delta"]                    # the prospect never reached the state file
    store.save_state(state)

    det = CampaignService(str(tmp_path)).target_detail("delta.example", run=RUN_A)
    assert det["evidence_status"] == "prospect_not_found"
    assert det["findings"] == []
