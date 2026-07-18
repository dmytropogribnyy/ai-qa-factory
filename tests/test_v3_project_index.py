"""v3.0.0 Milestone 5 - shared project index (adapter over existing state; deterministic)."""
from __future__ import annotations

import json
import urllib.request

from core.orchestration.client_work import ClientWorkService
from core.orchestration.project_index import ProjectIndex
from core.orchestration.providers import FixedClock, SequentialIds
from core.scout.comms.demo import run_radar_demo
from core.scout.dashboard import start_dashboard
from core.scout.service import ScoutService


def test_index_unifies_client_work_and_scout(tmp_path):
    # A client-work project (via the real analyze path) + a Scout campaign (via the demo run).
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(
        "Build a Playwright TypeScript E2E framework with CI.", "proj-cw")
    run_radar_demo(str(tmp_path))

    projects = ProjectIndex(str(tmp_path)).list_projects()
    by_type = {p.type for p in projects}
    assert "client_work" in by_type and "scout_campaign" in by_type
    cw = next(p for p in projects if p.type == "client_work")
    assert cw.project_id == "proj-cw" and cw.lifecycle_state and cw.operator_next_action
    assert "40_ark_work" in cw.workspace_path


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
    run_radar_demo(str(tmp_path))
    snap = ProjectIndex(str(tmp_path)).snapshot()
    assert snap["project_count"] >= 1 and "scout_campaign" in snap["by_type"]
    assert all("operator_next_action" in p for p in snap["projects"])


def test_dashboard_serves_projects(tmp_path):
    summary = run_radar_demo(str(tmp_path))
    service = ScoutService(str(tmp_path))
    service.attach(summary["campaign_id"])
    server, url = start_dashboard(service)
    try:
        with urllib.request.urlopen(url + "/api/projects", timeout=5) as r:
            data = json.loads(r.read())
        assert data["project_count"] >= 1
        with urllib.request.urlopen(url + "/projects", timeout=5) as r:
            assert "projects" in r.read().decode("utf-8").lower()
    finally:
        server.shutdown()
