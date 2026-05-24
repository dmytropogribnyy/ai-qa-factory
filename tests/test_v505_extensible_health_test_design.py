from pathlib import Path

from core.config import get_settings
from core.agent_registry import build_agent_registry
from core.initial_analysis_engine import InitialAnalysisEngine
from core.llm_router import LLMRouter
from core.quality_gate import QualityGate
from core.workflow_registry import WORKFLOWS
from core.orchestrator import QAFactoryOrchestrator


def test_v505_agents_registered(monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    settings = get_settings()
    router = LLMRouter(settings)
    registry = build_agent_registry(InitialAnalysisEngine(router), router, QualityGate())
    assert "project_extension" in registry
    assert "self_health_monitor" in registry
    assert "test_strategy" in registry
    assert "test_plan_writer" in registry
    assert "test_case_writer" in registry


def test_v505_test_design_workflow_registered():
    assert "test-design" in WORKFLOWS
    assert "test_strategy" in WORKFLOWS["test-design"]
    assert "test_plan_writer" in WORKFLOWS["test-design"]
    assert "test_case_writer" in WORKFLOWS["test-design"]
    assert "self_health_monitor" in WORKFLOWS["test-design"]


def test_v505_test_design_outputs(tmp_path, monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    settings = get_settings()
    state = QAFactoryOrchestrator(settings).run(
        "test-design",
        "Need test strategy, test plan and test cases for SaaS onboarding, Stripe billing, roles and API validation.",
        execution_mode="auto",
    )
    assert "TEST_STRATEGY.md" in state.generated_outputs
    assert "TEST_PLAN.md" in state.generated_outputs
    assert "TEST_CASES.md" in state.generated_outputs
    assert "SELF_HEALTH_REPORT.md" in state.generated_outputs
    assert "SYSTEM_REPAIR_PLAN.md" in state.generated_outputs
    assert state.health_status in {"healthy", "review_recommended", "needs_repair"}
    assert (settings.output_dir / state.project_id / "TEST_STRATEGY.md").exists()


def test_v505_project_extension_suggests_test_design(tmp_path, monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    settings = get_settings()
    state = QAFactoryOrchestrator(settings).run(
        "prescreen",
        "We need a test strategy and test cases for a React Native app with Maestro.",
        execution_mode="auto",
    )
    assert "PROJECT_EXTENSION_PLAN.md" in state.generated_outputs
    assert any(req.get("pack_id") == "test_design_pack" for req in state.project_extension_requests)
    assert any(req.get("pack_id") in {"mobile_maestro_pack", "react_native_release_pack"} for req in state.project_extension_requests)
