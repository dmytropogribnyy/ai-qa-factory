"""v3.0.0 M7d - the REAL (non-fixture) operator execution path, persisted by the Factory.

Proves OperatorWorkspaceExecutor records operator/Claude-Code-authored files (fabricating nothing),
runs a real validation, and drives the SAME persisted lifecycle as the CI fixtures - here with
``is_acceptance_fixture=False``. A missing declared artifact is an honest blocker (state BLOCKED).
"""
from __future__ import annotations

import json
from pathlib import Path

from core.orchestration.client_work import ClientWorkService
from core.orchestration.operator_executor import OperatorWorkspaceExecutor, ProducedArtifact
from core.orchestration.providers import FixedClock, SequentialIds
from core.orchestration.work_execution import WorkExecutionService
from core.schemas.work_execution import ExecutionContext, ValidationOutcome


def _svc(tmp_path):
    return WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))


def _author_bugfix(ws: Path) -> None:
    """Stand in for what a real Claude Code operator writes into the workspace."""
    (ws / "src").mkdir(parents=True, exist_ok=True)
    (ws / "src" / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    (ws / "tests").mkdir(parents=True, exist_ok=True)
    (ws / "tests" / "test_calc.py").write_text(
        "from src.calc import add\n\n\ndef test_add():\n    assert add(2, 3) == 5\n", encoding="utf-8")
    (ws / "evidence").mkdir(parents=True, exist_ok=True)
    (ws / "evidence" / "regression.txt").write_text("add(2,3)==5 after the fix\n", encoding="utf-8")


def _real_validator(ctx: ExecutionContext) -> ValidationOutcome:
    # A genuine check: import the operator-authored module and run its behavior in-process.
    src = (Path(ctx.workspace_dir) / "src" / "calc.py").read_text(encoding="utf-8")
    ns: dict = {}
    exec(compile(src, "calc.py", "exec"), ns)  # noqa: S102 - runs the operator's own authored code
    ok = ns["add"](2, 3) == 5
    return ValidationOutcome(passed=ok, tests_run=1, tests_passed=1 if ok else 0,
                             failures=[] if ok else ["add(2,3) != 5"],
                             report="ran the operator-authored regression in-process")


def _produced():
    return [
        ProducedArtifact("src/calc.py", "fix"),
        ProducedArtifact("tests/test_calc.py", "test"),
        ProducedArtifact("evidence/regression.txt", "report", is_evidence=True,
                         evidence_kind="test_output", description="passing regression evidence"),
    ]


def test_operator_execution_is_recorded_and_persisted(tmp_path):
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(
        "Reproduce and fix a defect in a small Python module and add a regression test.", "op")
    ws = tmp_path / "op" / "40_ark_work"
    _author_bugfix(ws)   # the operator (a real Claude Code session) does the work

    svc = _svc(tmp_path)
    svc.approve("op", reviewer="operator", note="reviewed the plan")
    executor = OperatorWorkspaceExecutor(_produced(), _real_validator,
                                         executor_id="operator:claude-code")
    assert executor.is_acceptance_fixture is False   # NOT a CI fixture

    state, outcome = svc.execute("op", executor)
    assert state.status == "VERIFYING" and not outcome.blockers
    state, result = svc.validate("op", executor)
    assert result.passed and result.tests_passed == 1 and state.status == "READY_FOR_REVIEW"
    # Delivery needs an explicit operator review; it cannot be prepared straight from validation.
    import pytest
    with pytest.raises(Exception):
        svc.prepare_delivery("op")
    svc.review("op", reviewer="operator", approved=True, note="reviewed the deliverables")
    manifest = svc.prepare_delivery("op")

    # The Factory PERSISTED the operator-authored artifacts, evidence, validation, and delivery.
    prog = json.loads((ws / "EXECUTION_PROGRESS.json").read_text(encoding="utf-8"))
    assert prog["is_acceptance_fixture"] is False
    assert (ws / "EVIDENCE_INDEX.json").exists() and svc.status("op").evidence_count == 1
    assert json.loads((ws / "TEST_RESULTS.json").read_text(encoding="utf-8"))["passed"] is True
    assert manifest["validation_passed"] and manifest["review_approved"] is True
    assert manifest["artifact_hashes"] and (ws / "WORK_DELIVERY_MANIFEST.json").exists()
    assert svc.status("op").status == "READY_FOR_DELIVERY"


def test_command_validation_executor_runs_a_real_command(tmp_path):
    import sys as _sys

    from core.orchestration.operator_executor import CommandValidationExecutor
    from core.schemas.work_execution import ExecutionContext
    (tmp_path / "calc.py").write_text("def add(a, b):\n    return a + b\n", encoding="utf-8")
    ctx = ExecutionContext(project_id="x", profile="", workspace_dir=str(tmp_path),
                           requirements=[], now="t")
    ok = CommandValidationExecutor([_sys.executable, "-c", "import calc; assert calc.add(2, 3) == 5"])
    res = ok.validate(ctx)
    assert res.passed and res.details["returncode"] == 0
    assert (tmp_path / "evidence" / "validation_output.txt").exists()   # captured output as evidence
    bad = CommandValidationExecutor([_sys.executable, "-c", "raise SystemExit(1)"])
    assert bad.validate(ctx).passed is False


def test_missing_operator_artifact_is_an_honest_blocker(tmp_path):
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(
        "Reproduce and fix a defect in a small Python module and add a regression test.", "op2")
    # The operator did NOT author the declared files -> execution records a blocker, state BLOCKED.
    svc = _svc(tmp_path)
    svc.approve("op2", reviewer="operator")
    executor = OperatorWorkspaceExecutor(_produced(), _real_validator)
    state, outcome = svc.execute("op2", executor)
    assert state.status == "BLOCKED" and outcome.blockers
