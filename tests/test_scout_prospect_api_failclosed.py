"""Close F1: `/api/prospect` must apply the SAME completeness rule as the read model.

`CampaignService.target_detail` (Task 3, 5ab2402) fails closed for any non-empty prospect status
other than DONE. `_prospect` (`dashboard.py`, backing `/api/prospect`) reads the RunStore directly
and never consulted that rule, so a PENDING/SKIPPED/FAILED target's confirmed findings — including
the raw finding titles — leaked verbatim through this raw-JSON diagnostic endpoint even though the
read model and every UI surface correctly withheld them. Three UI links point at it
(dashboard.py:3208, :3491, :4303).

Fix: one shared predicate (`campaign_service.analysis_incomplete`) used by both surfaces.
"""
from __future__ import annotations

import json

from core.scout.dashboard import start_dashboard
from core.scout.service import ScoutService
from tests.scout_seam_fixtures import RUN_A, build_seam_stand, get, no_tavily


def _start(tmp_path):
    return start_dashboard(ScoutService(str(tmp_path)), operator_home=True)


def _prospect_shows_findings(payload: dict) -> bool:
    findings = payload.get("findings")
    return isinstance(findings, dict) and "verified" in findings


def _target_shows_findings(payload: dict) -> bool:
    return bool(payload.get("findings"))


def _assert_withheld(entry, *, artifact_present: bool) -> None:
    """The withheld marker itself, not just the fields around it: must distinguish "the analysis
    did not complete" (this shape) from "nothing was ever written" (artifact_present distinguishes
    that within the shape). A collapse to `None` or `{}` here would silently merge those two
    honestly-different cases back together -- exactly what the brief's marker exists to prevent."""
    assert isinstance(entry, dict)
    assert entry != {}
    assert entry.get("withheld") == "analysis_incomplete"
    assert entry.get("artifact_present") is artifact_present


# --- 1. PENDING (04-delta): must fail closed --------------------------------------------------

def test_pending_prospect_withholds_findings_and_reports_status(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    server, url = _start(tmp_path)
    try:
        status, body = get(f"{url}/api/prospect?run={RUN_A}&id=04-delta")
    finally:
        server.shutdown()

    assert status == 200
    payload = json.loads(body)
    assert payload["prospect_status"] == "PENDING"
    assert payload["analysis_complete"] is False
    assert "verified" not in json.dumps(payload)            # nowhere in the payload, incl. nested
    assert "delta.example: delta 1 (high)" not in body      # the leaked title, raw response text
    # delta genuinely HAS a findings.json on disk (scout_seam_fixtures.py:72) but never a
    # scorecard.json -- the marker must say so honestly, not collapse both to the same shape.
    _assert_withheld(payload["findings"], artifact_present=True)
    _assert_withheld(payload["scorecard"], artifact_present=False)


# --- 2. SKIPPED (07-eta) and FAILED (03-gamma): same invariant --------------------------------

def test_skipped_and_failed_prospects_withhold_findings_too(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    server, url = _start(tmp_path)
    try:
        for pid, expected_status in (("07-eta", "SKIPPED"), ("03-gamma", "FAILED")):
            status, body = get(f"{url}/api/prospect?run={RUN_A}&id={pid}")
            assert status == 200
            payload = json.loads(body)
            assert payload["prospect_status"] == expected_status
            assert payload["analysis_complete"] is False
            assert "verified" not in json.dumps(payload)
            # Neither gamma (scout_seam_fixtures.py:66-69) nor eta (:91-92) ever had a
            # findings.json written -- artifact_present must say so, distinguishing "never
            # written" from delta's "written, but withheld" in test 1.
            _assert_withheld(payload["findings"], artifact_present=False)
            _assert_withheld(payload["scorecard"], artifact_present=False)
    finally:
        server.shutdown()


# --- 3. DONE (01-alpha): confirmed findings remain available ----------------------------------

def test_done_prospect_keeps_confirmed_findings(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    server, url = _start(tmp_path)
    try:
        status, body = get(f"{url}/api/prospect?run={RUN_A}&id=01-alpha")
    finally:
        server.shutdown()

    assert status == 200
    payload = json.loads(body)
    assert payload["prospect_status"] == "DONE"
    assert payload["analysis_complete"] is True
    verified = payload["findings"]["verified"]
    assert len(verified) == 5
    assert sum(1 for f in verified if f["severity"] != "info") == 3
    # A DONE target carries no withheld marker at all -- the marker is specific to the
    # analysis-incomplete case, never present alongside a genuinely confirmed analysis.
    assert "withheld" not in payload["findings"]
    assert payload["scorecard"] is None  # alpha never had a scorecard.json (fixture writes none)


# --- 4. Parity: /api/prospect and /api/scout/target agree ------------------------------------

def test_prospect_api_and_read_model_agree_on_finding_visibility(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    server, url = _start(tmp_path)
    try:
        _, done_prospect_body = get(f"{url}/api/prospect?run={RUN_A}&id=01-alpha")
        _, done_target_body = get(f"{url}/api/scout/target?run={RUN_A}&domain=alpha.example")
        _, pending_prospect_body = get(f"{url}/api/prospect?run={RUN_A}&id=04-delta")
        _, pending_target_body = get(f"{url}/api/scout/target?run={RUN_A}&domain=delta.example")
    finally:
        server.shutdown()

    done_prospect = json.loads(done_prospect_body)
    done_target = json.loads(done_target_body)
    pending_prospect = json.loads(pending_prospect_body)
    pending_target = json.loads(pending_target_body)

    assert _prospect_shows_findings(done_prospect) is True
    assert _target_shows_findings(done_target) is True
    assert _prospect_shows_findings(done_prospect) == _target_shows_findings(done_target)

    assert _prospect_shows_findings(pending_prospect) is False
    assert _target_shows_findings(pending_target) is False
    assert _prospect_shows_findings(pending_prospect) == _target_shows_findings(pending_target)


# --- 5. The three UI links still open valid, understandable JSON ------------------------------

def test_ui_link_shapes_return_parseable_json_for_done_and_non_done_targets(tmp_path, monkeypatch):
    """The exact query shape emitted at dashboard.py:3208, :3491 and :4303: given a real run_id
    (always true at those three call sites — each only renders the link, or takes the `if run_id`
    branch, when a run is bound), all three collapse to `/api/prospect?run=<run>&id=<pid>`. Must
    keep returning a parseable 200 body for both a DONE and a non-DONE target — never a 500."""
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    server, url = _start(tmp_path)
    try:
        for pid in ("01-alpha", "04-delta"):
            status, body = get(f"{url}/api/prospect?run={RUN_A}&id={pid}")
            assert status == 200
            parsed = json.loads(body)                # must not raise -- a parseable body
            assert "prospect_id" in parsed
    finally:
        server.shutdown()


# --- bonus: the genuinely-unpinned path (no ?run=) resolves status from service.store ---------

def test_unpinned_path_resolves_status_from_the_attached_run(tmp_path, monkeypatch):
    """Judgment point 2 from the brief: with no ?run=, `_prospect` must resolve status from
    `service.store` the same way the pinned path does, not skip the rule entirely."""
    no_tavily(monkeypatch)
    build_seam_stand(str(tmp_path))
    service = ScoutService(str(tmp_path))
    service.attach(RUN_A)
    server, url = start_dashboard(service, operator_home=True)
    try:
        status, body = get(f"{url}/api/prospect?id=04-delta")
    finally:
        server.shutdown()

    assert status == 200
    payload = json.loads(body)
    assert payload["prospect_status"] == "PENDING"
    assert payload["analysis_complete"] is False
    assert "verified" not in json.dumps(payload)
    _assert_withheld(payload["findings"], artifact_present=True)
    _assert_withheld(payload["scorecard"], artifact_present=False)
