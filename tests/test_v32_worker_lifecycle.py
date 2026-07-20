"""v3.2 P0 - the Claude worker plugs into the EXISTING lifecycle; no auto-validation; confinement."""
from __future__ import annotations

import json

import pytest

from core.orchestration.claude_worker import (
    ClaudeWorkerExecutor,
    FixtureClaudeWorker,
    build_order_from_context,
)
from core.orchestration.client_work import ClientWorkService
from core.orchestration.operator_executor import CommandValidationExecutor
from core.orchestration.providers import FixedClock, SequentialIds
from core.orchestration.work_execution import WorkExecutionService
from core.schemas.work_execution import ExecutionContext

_BRIEF = "Reproduce and fix a defect in a small Python module and add a regression test."


def _svc(tmp_path):
    return WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))


def _analyze_approve(tmp_path, pid):
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(_BRIEF, pid)
    _svc(tmp_path).approve(pid, reviewer="op")


def test_worker_order_is_built_only_from_state():
    ctx = ExecutionContext(project_id="proj-1", profile="python", workspace_dir="/x",
                           requirements=["add() must return a+b", "add a regression test"], now="t")
    order = build_order_from_context(ctx)
    assert order.project_id == "proj-1"
    assert "add() must return a+b" in order.objective and "regression test" in order.objective
    # Deterministic, resumable session id derived from the project id (never caller-supplied).
    assert order.session_id == build_order_from_context(ctx).session_id
    assert order.max_budget_usd > 0 and "Edit" in order.allowed_tools


def test_worker_executor_records_real_artifacts_through_lifecycle(tmp_path):
    _analyze_approve(tmp_path, "w")
    ws = tmp_path / "w" / "40_ark_work"
    (ws / "calc.py").write_text("def add(a, b):\n    return a - b  # bug\n", encoding="utf-8")
    executor = ClaudeWorkerExecutor(
        FixtureClaudeWorker(edits={"calc.py": "def add(a, b):\n    return a + b\n"}))
    assert executor.is_acceptance_fixture is True     # a fixture is never presented as the live provider
    svc = _svc(tmp_path)
    state, outcome = svc.execute("w", executor)
    assert state.status == "VERIFYING" and not outcome.blockers
    assert "calc.py" in outcome.files_changed         # GENUINE change, not fabricated
    # The worker session + output are registered as real evidence + hashed by the lifecycle.
    idx = json.loads((ws / "EVIDENCE_INDEX.json").read_text(encoding="utf-8"))
    paths = {e["relative_path"] for e in idx["evidence"]}
    assert "EXECUTION_SESSION.json" in paths and "evidence/worker/stdout.txt" in paths
    hashes = json.loads((ws / "ARTIFACT_HASHES.json").read_text(encoding="utf-8"))["hashes"]
    assert "calc.py" in hashes


def test_worker_executor_does_not_auto_validate(tmp_path):
    ctx = ExecutionContext(project_id="w2", profile="", workspace_dir=str(tmp_path), requirements=[],
                           now="t")
    with pytest.raises(ValueError):
        ClaudeWorkerExecutor(FixtureClaudeWorker()).validate(ctx)


def test_worker_then_real_validation_then_delivery(tmp_path):
    _analyze_approve(tmp_path, "w3")
    ws = tmp_path / "w3" / "40_ark_work"
    (ws / "calc.py").write_text("def add(a, b):\n    return a - b\n", encoding="utf-8")
    svc = _svc(tmp_path)
    svc.execute("w3", ClaudeWorkerExecutor(
        FixtureClaudeWorker(edits={"calc.py": "def add(a, b):\n    return a + b\n"})))
    # Validation is a SEPARATE step through the existing validation executor (no auto-success).
    import sys
    state, res = svc.validate("w3", CommandValidationExecutor(
        [sys.executable, "-c", "import calc; assert calc.add(2, 3) == 5"]))
    assert res.passed and state.status == "READY_FOR_REVIEW"
    svc.review("w3", reviewer="op", approved=True)
    svc.prepare_delivery("w3")
    assert svc.status("w3").status == "DELIVERY_PREPARED"


def test_worker_no_change_is_an_honest_blocker(tmp_path):
    _analyze_approve(tmp_path, "w4")
    svc = _svc(tmp_path)
    state, outcome = svc.execute("w4", ClaudeWorkerExecutor(FixtureClaudeWorker(edits={})))
    assert state.status == "BLOCKED" and outcome.blockers   # never fabricates an artifact list


def test_worker_workspace_is_confined_to_the_project(tmp_path):
    # The executor derives the workspace from WorkExecutionService (the confined project dir); a
    # caller cannot select an arbitrary workspace. An unsafe project id is rejected by the service.
    svc = _svc(tmp_path)
    with pytest.raises(Exception):
        svc.execute("../escape", ClaudeWorkerExecutor(FixtureClaudeWorker(edits={"x": "y"})))
