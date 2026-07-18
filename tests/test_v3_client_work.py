"""v3.0.0 Milestone 2 — client-work feasibility + workspace (deterministic; read-only planning)."""
from __future__ import annotations

from pathlib import Path

from core.orchestration.client_work import ClientWorkService
from core.orchestration.feasibility import FeasibilityAssessor
from core.orchestration.providers import FixedClock, SequentialIds
from core.schemas.feasibility import (
    NOT_RECOMMENDED,
    RECOMMENDED_TO_TAKE,
    TAKE_AFTER_ACCESS_OR_TOOL_SETUP,
    TAKE_AFTER_CLARIFICATION,
    VERDICTS,
)


def _artifacts(*, profile="playwright_ts_framework", confidence=0.8, requirements=3, blocking=None,
               missing_caps=None, blocked_caps=None, approvals=None, discovery=False):
    return {
        "work_packet": {"title": "t", "summary": "Build a QA framework",
                        "capability_profile": profile,
                        "requirements": [{"text": f"r{i}"} for i in range(requirements)]},
        "capability_plan": {"required_capabilities": ["a", "b"],
                            "planned": [{"capability": "a", "requires_discovery": discovery}],
                            "missing_capabilities": missing_caps or [],
                            "blocked_capabilities": blocked_caps or [],
                            "approvals_required": approvals or []},
        "toolchain_plan": {"steps": [{"capability": "a", "backend": "playwright",
                                      "resolution_status": "available"}]},
        "intake_report": {"profile_selection": {"selected_profile": profile, "confidence": confidence},
                          "missing_information": {"blocking": blocking or [], "clarification": [],
                                                  "approval_needed": []}},
    }


def _assess(**over):
    return FeasibilityAssessor().assess(project_id="p", **_artifacts(**over))


def test_recommended_when_resolved_and_available():
    r = _assess()
    assert r.verdict == RECOMMENDED_TO_TAKE and r.risk_level == "low"
    assert r.selected_tools == ["playwright"] and r.expected_deliverables


def test_clarify_when_blocking_information_missing():
    r = _assess(blocking=["What is the target URL / environment?"])
    assert r.verdict == TAKE_AFTER_CLARIFICATION and "What is the target URL / environment?" in r.client_questions


def test_setup_when_approvals_or_discovery_required():
    assert _assess(approvals=["github_write"]).verdict == TAKE_AFTER_ACCESS_OR_TOOL_SETUP
    assert _assess(discovery=True).verdict == TAKE_AFTER_ACCESS_OR_TOOL_SETUP


def test_not_recommended_when_profile_unresolved():
    r = _assess(profile="unknown")
    assert r.verdict == NOT_RECOMMENDED and r.reasons_to_reject


def test_not_recommended_when_capability_unavailable():
    r = _assess(missing_caps=["java_execution"])
    assert r.verdict == NOT_RECOMMENDED
    assert any("java_execution" in x for x in r.reasons_to_reject)
    assert "java_execution" in r.unavailable_blockers


# --- integration through the real planning pipeline (reuses WorkPlanningWorkflow) -----------------

def test_analyze_playwright_brief_produces_workspace(tmp_path):
    svc = ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))
    res = svc.analyze("Build a Playwright TypeScript end-to-end test framework with GitHub Actions CI, "
                      "critical user flows, API checks, and HTML reporting.", "proj-a")
    assert res.verdict in VERDICTS
    ws = Path(res.workspace_dir)
    # Feasibility artifacts added AND the planning artifacts preserved (nothing dropped).
    for name in ("FEASIBILITY_REPORT.json", "FEASIBILITY_SUMMARY.md", "CLIENT_QUESTIONS.md",
                 "PROPOSAL_DRAFT.md", "WORK_PACKET.json", "CAPABILITY_PLAN.json", "WORK_RUN_STATE.json"):
        assert (ws / name).exists(), f"missing {name}"


def test_analyze_java_only_no_access_is_not_recommended(tmp_path):
    svc = ClientWorkService(FixedClock(), SequentialIds(), output_dir=str(tmp_path))
    res = svc.analyze("Senior Java Spring Boot microservices engineer needed to build a large backend "
                      "framework from scratch. No repository access. Must deliver in 2 days.", "proj-e")
    # Honest: a Java-only deep build with no access is never a strong recommend.
    assert res.verdict != RECOMMENDED_TO_TAKE
    assert res.feasibility.reasons_to_reject or res.feasibility.client_questions
