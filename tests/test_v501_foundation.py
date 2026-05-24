from __future__ import annotations

from pathlib import Path

from core.agent_registry import build_agent_registry
from core.config import get_settings
from core.initial_analysis_engine import InitialAnalysisEngine
from core.llm_router import LLMRouter
from core.orchestrator import QAFactoryOrchestrator
from core.persistence import JSONFilePersistence
from core.prompt_loader import PromptLoader
from core.quality_gate import CheckResult, QualityGate
from core.state import QAFactoryState


def test_prompt_loader_profile_fallback_default_empty(tmp_path):
    root = tmp_path / "prompts"
    (root / "proposal").mkdir(parents=True)
    (root / "proposal" / "default.md").write_text("DEFAULT", encoding="utf-8")
    loader = PromptLoader(root)
    assert loader.load("proposal", "missing", fallback="also_missing") == "DEFAULT"
    assert loader.load("qa_plan", "missing") == ""


def test_persistence_creates_memory_structure(tmp_path):
    persistence = JSONFilePersistence(tmp_path / "memory", tmp_path / "outputs")
    assert (tmp_path / "memory" / "clients").exists()
    assert (tmp_path / "memory" / "snippets").exists()
    assert (tmp_path / "memory" / "lessons-learned").exists()
    assert persistence.pricing_book_path().exists()


def test_snapshots_are_created_after_agents(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("MEMORY_DIR", str(tmp_path / "memory"))
    settings = get_settings()
    state = QAFactoryOrchestrator(settings).run("upwork", "Need Playwright TypeScript flaky CI audit for SaaS app.")
    snapshots = tmp_path / "outputs" / state.project_id / ".snapshots"
    assert (snapshots / "state_after_job_analyzer.json").exists()
    assert (snapshots / "state_after_proposal_writer.json").exists()
    assert (snapshots / "state_after_quality_gate.json").exists()


def test_dry_run_does_not_write_final_outputs(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("MEMORY_DIR", str(tmp_path / "memory"))
    settings = get_settings()
    state = QAFactoryOrchestrator(settings).run(
        "upwork",
        "Need Playwright TypeScript flaky CI audit for SaaS app.",
        execution_mode="dry-run",
    )
    assert "proposal.md" in state.generated_outputs
    assert not (tmp_path / "outputs" / state.project_id / "proposal.md").exists()


def test_only_agent_uses_saved_state(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("MEMORY_DIR", str(tmp_path / "memory"))
    settings = get_settings()
    orchestrator = QAFactoryOrchestrator(settings)
    original = orchestrator.run("upwork", "Need Playwright TypeScript flaky CI audit for SaaS app.")
    rerun = QAFactoryOrchestrator(settings).run(
        "upwork",
        "Need Playwright TypeScript flaky CI audit for SaaS app.",
        only="proposal_writer",
    )
    assert rerun.project_id == original.project_id
    assert "proposal.md" in rerun.generated_outputs
    assert "qa_plan.md" in rerun.generated_outputs  # preserved from saved state


def test_from_step_uses_saved_state(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("MEMORY_DIR", str(tmp_path / "memory"))
    settings = get_settings()
    original = QAFactoryOrchestrator(settings).run("upwork", "Need Playwright TypeScript flaky CI audit for SaaS app.")
    rerun = QAFactoryOrchestrator(settings).run(
        "upwork",
        "Need Playwright TypeScript flaky CI audit for SaaS app.",
        from_step="proposal_writer",
    )
    assert rerun.project_id == original.project_id
    assert "proposal.md" in rerun.generated_outputs
    assert "QUALITY_GATE_REPORT.md" in rerun.generated_outputs


def test_agent_registry_exposes_core_agents(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("MEMORY_DIR", str(tmp_path / "memory"))
    settings = get_settings()
    router = LLMRouter(settings)
    registry = build_agent_registry(InitialAnalysisEngine(router), router, QualityGate(), persistence=JSONFilePersistence(settings.memory_dir, settings.output_dir))
    for key in ["job_analyzer", "proposal_writer", "pricing_advisor", "api_test_generator", "quality_gate"]:
        assert key in registry


def test_quality_gate_accepts_external_check():
    class AlwaysWarnCheck:
        name = "custom_check"
        severity = "warning"
        def evaluate(self, state):
            return CheckResult(self.name, False, ["custom warning"], self.severity)

    state = QAFactoryState(project_id="p", mode="upwork", raw_input="x")
    state = QualityGate(checks=[AlwaysWarnCheck()]).run(state)
    assert "custom_check" in state.quality_gate_results
    assert "custom warning" in state.generated_outputs["QUALITY_GATE_REPORT.md"]


def test_pricing_book_is_loaded(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("MEMORY_DIR", str(tmp_path / "memory"))
    settings = get_settings()
    persistence = JSONFilePersistence(settings.memory_dir, settings.output_dir)
    persistence.pricing_book_path().write_text(
        "custom:\n  triggers: [playwright]\n  price: \"$999 custom\"\n  milestone: \"Custom milestone.\"\ndefault:\n  price: \"$1 default\"\n  milestone: \"Default milestone.\"\n",
        encoding="utf-8",
    )
    state = QAFactoryOrchestrator(settings).run("upwork", "Need Playwright help")
    assert state.suggested_price == "$999 custom"
