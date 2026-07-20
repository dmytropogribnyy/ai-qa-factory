"""v3.1 M1 - dashboard read model + actions DTOs over the existing core services."""
from __future__ import annotations

from core.dashboard.actions import ProjectDetailBuilder, allowed_actions, primary_action
from core.dashboard.read_model import SCHEMA_VERSION, DashboardReadModel
from core.orchestration.client_work import ClientWorkService
from core.orchestration.operator_executor import OperatorWorkspaceExecutor, ProducedArtifact
from core.orchestration.providers import FixedClock, SequentialIds
from core.orchestration.work_execution import WorkExecutionService
from core.schemas.work_execution import ValidationOutcome

_BRIEF = "Reproduce and fix a defect in a small Python module and add a regression test."


def _passing(_ctx):
    return ValidationOutcome(passed=True, tests_run=1, tests_passed=1, report="ok")


def _svc(tmp_path):
    return WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))


def _analyze(tmp_path, pid):
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(_BRIEF, pid)


def _to_ready_for_review(tmp_path, pid):
    _analyze(tmp_path, pid)
    ws = tmp_path / pid / "40_ark_work"
    (ws / "fix.py").write_text("x = 1\n", encoding="utf-8")
    svc = _svc(tmp_path)
    svc.approve(pid, reviewer="op")
    ex = OperatorWorkspaceExecutor([ProducedArtifact("fix.py", "fix")], _passing)
    svc.execute(pid, ex)
    svc.validate(pid, ex)
    return svc


def test_allowed_actions_follow_the_state_machine():
    assert [a.id for a in allowed_actions("PLANNED")][0] == "approve"
    assert primary_action("READY_FOR_DELIVERY")["id"] == "prepare_delivery"
    assert primary_action("DELIVERY_PREPARED")["id"] == "mark_delivered"
    # No allowed action is ever a raw command/argv over HTTP.
    for status in ("VERIFYING", "READY_TO_EXECUTE", "READY_FOR_REVIEW", "DELIVERY_PREPARED"):
        for a in allowed_actions(status):
            assert "command" not in a.endpoint and "argv" not in a.endpoint
            if a.kind == "http_mutation":
                assert a.endpoint.startswith("/api/work/")
    # Validation is a handoff, never an HTTP mutation.
    assert all(a.kind != "http_mutation" for a in allowed_actions("VERIFYING"))


def test_overview_surfaces_attention_items(tmp_path):
    _to_ready_for_review(tmp_path, "needsreview")     # deterministic attention: Ready for review
    rm = DashboardReadModel(str(tmp_path), clock=lambda: "T")
    ov = rm.overview()
    assert ov.schema == SCHEMA_VERSION
    items = {a["project_id"]: a for a in ov.attention}
    assert "needsreview" in items and items["needsreview"]["title"] == "Ready for review"
    assert items["needsreview"]["href"] == "/work/needsreview"
    assert ov.counts["projects"] >= 1 and ov.counts["attention"] >= 1


def test_project_list_filters(tmp_path):
    _to_ready_for_review(tmp_path, "rev")
    rm = DashboardReadModel(str(tmp_path), clock=lambda: "T")
    allp = rm.project_list(view="all")
    assert allp["total"] >= 1 and allp["schema"] == SCHEMA_VERSION
    review = rm.project_list(view="ready_for_review")
    assert all(p["status"] == "READY_FOR_REVIEW" for p in review["projects"])
    assert any(p["project_id"] == "rev" for p in review["projects"])
    item = review["projects"][0]
    assert item["stage"] == "Ready for review" and item["href"] == "/work/rev"


def test_project_detail_and_work_order(tmp_path):
    _to_ready_for_review(tmp_path, "d1")
    b = ProjectDetailBuilder(str(tmp_path))
    detail = b.detail("d1")
    assert detail["header"]["status"] == "READY_FOR_REVIEW"
    assert detail["primary_action"]["id"] == "review_approve"
    assert "fix.py" in detail["results"]["artifacts"]
    order = b.work_order("d1")
    assert "Work Order - d1" in order and "record-execution" in order
    assert detail["workspace_path"].endswith("40_ark_work")


def test_tools_dto_carries_ui_levels(tmp_path):
    rm = DashboardReadModel(str(tmp_path), clock=lambda: "T")
    tools = rm.tools()
    assert tools["any_live_accepted"] is False
    levels = {t["id"]: t["ui_level"] for t in tools["tools"]}
    assert levels["api_runner_internal"] == "Fixture Verified"
    assert levels["playwright_internal"] == "Binding Available"


def test_detail_missing_project_is_none(tmp_path):
    assert ProjectDetailBuilder(str(tmp_path)).detail("nope") is None
