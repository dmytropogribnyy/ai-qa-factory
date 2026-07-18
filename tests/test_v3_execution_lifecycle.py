"""v3.0.0 Milestone 7 - persisted execution lifecycle + fixture-backed acceptance A-E (deterministic).

Factory orchestrates and PERSISTS approval -> execution -> progress/blockers -> artifacts ->
evidence -> validation -> delivery -> resume. Executors here are ACCEPTANCE FIXTURES (no autonomous
agent, no LLM, no network, no real send/scan). Real client execution is Claude-Code-driven.
"""
from __future__ import annotations

import json

from core.orchestration.client_work import ClientWorkService
from core.orchestration.fixture_executors import (
    ApiTestingFixtureExecutor,
    BugFixFixtureExecutor,
    PlaywrightFrameworkFixtureExecutor,
    QaAuditFixtureExecutor,
)
from core.orchestration.providers import FixedClock, SequentialIds
from core.orchestration.work_execution import WorkExecutionService
from core.schemas.feasibility import NOT_RECOMMENDED, RECOMMENDED_TO_TAKE


def _analyze(tmp_path, brief, pid):
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(brief, pid)


def _svc(tmp_path):
    return WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))


def _run_lifecycle(tmp_path, pid, executor):
    svc = _svc(tmp_path)
    svc.approve(pid, reviewer="operator", note="approved for acceptance")
    state, outcome = svc.execute(pid, executor)
    assert state.status in ("VERIFYING", "BLOCKED")
    state, result = svc.validate(pid, executor)
    assert state.status in ("READY_FOR_REVIEW", "REPAIR_REQUIRED")
    if result.passed:
        svc.review(pid, reviewer="operator", approved=True, note="looks good")  # explicit review gate
        svc.prepare_delivery(pid)
    return svc, result


def test_scenario_a_playwright_framework_full_lifecycle(tmp_path):
    _analyze(tmp_path, "Build a Playwright + TypeScript E2E framework with CI and reporting.", "a")
    svc, result = _run_lifecycle(tmp_path, "a", PlaywrightFrameworkFixtureExecutor())
    assert result.passed
    ws = tmp_path / "a" / "40_ark_work"
    # Framework files, evidence, validation, and the delivery package are PERSISTED by Factory.
    assert (ws / "delivery" / "package.json").exists() and (ws / "delivery" / "tests" / "example.spec.ts").exists()
    assert (ws / "EVIDENCE_INDEX.json").exists() and (ws / "TEST_RESULTS.json").exists()
    assert (ws / "WORK_DELIVERY_MANIFEST.json").exists() and (ws / "DELIVERY_REPORT.md").exists()
    view = svc.status("a")
    assert view.status == "READY_FOR_DELIVERY" and view.delivery_ready and view.tests_run > 0


def test_scenario_b_qa_audit_findings_and_evidence(tmp_path):
    _analyze(tmp_path, "Run a QA audit of our public website and report defects with evidence.", "b")
    svc, result = _run_lifecycle(tmp_path, "b", QaAuditFixtureExecutor())
    assert result.passed
    ws = tmp_path / "b" / "40_ark_work"
    assert (ws / "delivery" / "findings.json").exists()
    assert (ws / "evidence" / "finding_f1.txt").exists()
    assert svc.status("b").evidence_count >= 2


def test_scenario_c_bug_fix_fails_before_passes_after(tmp_path):
    _analyze(tmp_path, "Reproduce and fix a defect in our small Python module; add a regression test.", "c")
    svc = _svc(tmp_path)
    svc.approve("c", reviewer="operator")
    state, outcome = svc.execute("c", BugFixFixtureExecutor())
    ws = tmp_path / "c" / "40_ark_work"
    # The defect was reproduced (failing before) as evidence, then fixed.
    assert (ws / "evidence" / "failing_before.txt").exists()
    assert "FAIL before the fix" in (ws / "evidence" / "failing_before.txt").read_text(encoding="utf-8")
    assert (ws / "fixture_repo" / "calc.py").read_text(encoding="utf-8").strip().endswith("return a + b")
    state, result = svc.validate("c", BugFixFixtureExecutor())     # passing after
    assert result.passed and result.tests_passed == 1
    svc.review("c", reviewer="operator", approved=True)
    svc.prepare_delivery("c")
    assert json.loads((ws / "TEST_RESULTS.json").read_text(encoding="utf-8"))["passed"] is True


def test_scenario_d_api_testing_executes_positive_and_negative(tmp_path):
    _analyze(tmp_path, "Build API tests from our OpenAPI spec with positive and negative cases.", "d")
    svc, result = _run_lifecycle(tmp_path, "d", ApiTestingFixtureExecutor())
    assert result.passed and result.tests_run == 4 and result.tests_passed == 4
    ws = tmp_path / "d" / "40_ark_work"
    assert (ws / "delivery" / "API_TEST_RESULTS.json").exists()


def test_scenario_e_java_only_impossible_is_rejected_and_not_executed(tmp_path):
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(
        "Senior Java Spring Boot engineer to build a large backend framework from scratch. No repo "
        "access. Deliver in 2 days.", "e")
    fr = json.loads((tmp_path / "e" / "40_ark_work" / "FEASIBILITY_REPORT.json").read_text(encoding="utf-8"))
    assert fr["verdict"] == NOT_RECOMMENDED and fr["reasons_to_reject"]
    # Nothing was executed: no execution/delivery artifacts exist.
    ws = tmp_path / "e" / "40_ark_work"
    assert not (ws / "EXECUTION_PROGRESS.json").exists() and not (ws / "WORK_DELIVERY_MANIFEST.json").exists()


def test_lifecycle_resumes_after_restart(tmp_path):
    _analyze(tmp_path, "Build a Playwright + TypeScript E2E framework.", "r")
    svc = _svc(tmp_path)
    svc.approve("r", reviewer="operator")
    svc.execute("r", PlaywrightFrameworkFixtureExecutor())
    svc.validate("r", PlaywrightFrameworkFixtureExecutor())
    svc.review("r", reviewer="operator", approved=True)
    svc.prepare_delivery("r")
    # A brand-new service instance (new process / new Claude session) reads the persisted state.
    resumed = WorkExecutionService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).resume("r")
    assert resumed.status == "READY_FOR_DELIVERY" and resumed.delivery_ready
    assert resumed.progress == 95


def test_recommended_verdict_reaches_planned_and_is_approvable(tmp_path):
    # A clean bug-fix brief with no blocking questions should be recommended/approvable.
    ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path)).analyze(
        "Reproduce and fix a defect in a small Python module and add a regression test.", "ok")
    fr = json.loads((tmp_path / "ok" / "40_ark_work" / "FEASIBILITY_REPORT.json").read_text(encoding="utf-8"))
    assert fr["verdict"] in (RECOMMENDED_TO_TAKE, "TAKE_AFTER_CLARIFICATION",
                             "TAKE_AFTER_ACCESS_OR_TOOL_SETUP")
    _svc(tmp_path).approve("ok", reviewer="operator")   # does not raise
