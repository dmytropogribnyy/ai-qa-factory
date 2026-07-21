"""v3.0.0 Milestone 5 - shared project index (adapter over existing state; deterministic).

Slice 2: Scout campaigns are enumerated from the CANONICAL orchestration source (scout/_runcontrol/,
the same source Observer uses), NOT a folder scan. Production excludes diagnostic ids; the demo run
(radar-demo) is a legacy folder artifact and appears only under include_diagnostics.
"""
from __future__ import annotations

import json
import urllib.request
from pathlib import Path

from core.orchestration.client_work import ClientWorkService
from core.orchestration.project_index import ProjectIndex
from core.orchestration.providers import FixedClock, SequentialIds
from core.scout.comms.demo import run_radar_demo
from core.scout.dashboard import start_dashboard
from core.scout.service import ScoutService

# A real production campaign id (see fresh_campaign_id: campaign-<slug>-<stamp>-<hex>).
_PROD_CAMPAIGN = "campaign-balanced-production-20260721T101500Z-abc123"


def _seed_production_campaign(tmp_path, campaign_id: str = _PROD_CAMPAIGN) -> str:
    """Seed a real orchestrated campaign: a _runcontrol record (canonical) + its run state dir."""
    rc = Path(tmp_path) / "scout" / "_runcontrol"
    rc.mkdir(parents=True, exist_ok=True)
    (rc / f"{campaign_id}.json").write_text(
        json.dumps({"campaign_id": campaign_id, "state": "COMPLETED", "stop_reason": "completed"}),
        encoding="utf-8")
    run = Path(tmp_path) / "scout" / campaign_id
    run.mkdir(parents=True, exist_ok=True)
    (run / "state.json").write_text(
        json.dumps({"campaign_id": campaign_id, "status": "COMPLETED",
                    "started_at": "2026-07-21T10:15:00Z", "counts": {}}), encoding="utf-8")
    return campaign_id


def test_index_unifies_client_work_and_scout(tmp_path):
    # A client-work project (via the real analyze path) + a real canonical Scout campaign.
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(
        "Build a Playwright TypeScript E2E framework with CI.", "proj-cw")
    _seed_production_campaign(tmp_path)

    projects = ProjectIndex(str(tmp_path)).list_projects()
    by_type = {p.type for p in projects}
    assert "client_work" in by_type and "scout_campaign" in by_type
    cw = next(p for p in projects if p.type == "client_work")
    assert cw.project_id == "proj-cw" and cw.lifecycle_state and cw.operator_next_action
    assert "40_ark_work" in cw.workspace_path
    sc = next(p for p in projects if p.type == "scout_campaign")
    assert sc.project_id == _PROD_CAMPAIGN and sc.diagnostic is False


def _seed_client_work(tmp_path, project_id: str, *, status: str = "PLANNED") -> None:
    ark = Path(tmp_path) / project_id / "40_ark_work"
    ark.mkdir(parents=True, exist_ok=True)
    (ark / "WORK_PACKET.json").write_text(
        json.dumps({"title": project_id, "created_at": "2026-07-21T10:00:00Z"}), encoding="utf-8")
    (ark / "WORK_RUN_STATE.json").write_text(
        json.dumps({"status": status, "updated_at": "2026-07-21T10:05:00Z"}), encoding="utf-8")


def test_diagnostic_client_work_excluded_from_production(tmp_path):
    # 'smoke-a' is diagnostic test data; 'proj-cw' is real client work.
    _seed_client_work(tmp_path, "smoke-a")
    _seed_client_work(tmp_path, "proj-cw")
    prod = ProjectIndex(str(tmp_path)).list_projects()
    ids = {p.project_id for p in prod if p.type == "client_work"}
    assert ids == {"proj-cw"}                                         # smoke-a hidden from production
    diag = ProjectIndex(str(tmp_path)).list_projects(include_diagnostics=True)
    smoke = next(p for p in diag if p.project_id == "smoke-a")
    assert smoke.diagnostic is True and smoke.type == "client_work"


def test_scout_folder_without_runcontrol_is_not_a_production_campaign(tmp_path):
    # The demo run writes outputs/scout/radar-demo/ but NO _runcontrol record → not canonical.
    run_radar_demo(str(tmp_path))
    prod = ProjectIndex(str(tmp_path)).list_projects()
    assert not any(p.type == "scout_campaign" for p in prod)          # excluded from production
    diag = ProjectIndex(str(tmp_path)).list_projects(include_diagnostics=True)
    demo = next(p for p in diag if p.type == "scout_campaign" and "radar-demo" in p.project_id)
    assert demo.diagnostic is True                                   # visible only as diagnostic


def test_overview_counts_exclude_diagnostics_by_default(tmp_path):
    from core.dashboard.read_model import DashboardReadModel
    _seed_client_work(tmp_path, "smoke-a")
    _seed_client_work(tmp_path, "proj-cw")
    rm = DashboardReadModel(str(tmp_path))
    assert rm.overview().counts["projects"] == 1                     # production only (smoke-a hidden)
    assert rm.overview(include_diagnostics=True).counts["projects"] == 2


def test_dashboard_toggle_hides_and_reveals_diagnostics_over_http(tmp_path):
    _seed_client_work(tmp_path, "smoke-a")
    _seed_client_work(tmp_path, "proj-cw")
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        with urllib.request.urlopen(url + "/api/overview", timeout=5) as r:
            ov = json.loads(r.read())
        assert ov["counts"]["projects"] == 1                        # production: smoke-a hidden
        assert ov["counts"]["diagnostics_hidden"] >= 1
        with urllib.request.urlopen(url + "/api/overview?diagnostics=1", timeout=5) as r:
            assert json.loads(r.read())["counts"]["projects"] == 2  # toggle reveals it
        with urllib.request.urlopen(url + "/api/work", timeout=5) as r:
            prod_ids = {p["project_id"] for p in json.loads(r.read())["projects"]}
        assert "smoke-a" not in prod_ids and "proj-cw" in prod_ids
        with urllib.request.urlopen(url + "/api/work?diagnostics=1", timeout=5) as r:
            diag_ids = {p["project_id"] for p in json.loads(r.read())["projects"]}
        assert "smoke-a" in diag_ids                                # not mixed into production
    finally:
        server.shutdown()


def test_index_tolerates_malformed_state(tmp_path):
    # A project dir with a malformed WORK_PACKET must not crash the index.
    ark = tmp_path / "broken" / "40_ark_work"
    ark.mkdir(parents=True)
    (ark / "WORK_PACKET.json").write_text("{ not json", encoding="utf-8")
    (ark / "WORK_RUN_STATE.json").write_text(json.dumps({"status": "PLANNED"}), encoding="utf-8")
    projects = ProjectIndex(str(tmp_path)).list_projects()
    broken = next(p for p in projects if p.project_id == "broken")
    assert broken.lifecycle_state == "PLANNED"     # read from the valid run-state; no crash


def test_snapshot_shape(tmp_path):
    _seed_production_campaign(tmp_path)
    snap = ProjectIndex(str(tmp_path)).snapshot()
    assert snap["project_count"] >= 1 and "scout_campaign" in snap["by_type"]
    assert all("operator_next_action" in p for p in snap["projects"])


def test_dashboard_serves_projects(tmp_path):
    _seed_production_campaign(tmp_path)
    server, url = start_dashboard(ScoutService(str(tmp_path)))
    try:
        with urllib.request.urlopen(url + "/api/projects", timeout=5) as r:
            data = json.loads(r.read())
        assert data["project_count"] >= 1
        with urllib.request.urlopen(url + "/projects", timeout=5) as r:
            assert "projects" in r.read().decode("utf-8").lower()
    finally:
        server.shutdown()
