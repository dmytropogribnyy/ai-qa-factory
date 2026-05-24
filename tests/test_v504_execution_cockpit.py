from pathlib import Path

from core.config import get_settings
from core.orchestrator import QAFactoryOrchestrator
from core.state import SCHEMA_VERSION
from core.workflow_registry import WORKFLOWS


def test_v504_schema_version():
    assert SCHEMA_VERSION == "5.0.5"


def test_prescreen_workflow_registered():
    assert "prescreen" in WORKFLOWS
    assert "prescreening" in WORKFLOWS["prescreen"]
    assert "execution_cockpit" in WORKFLOWS["prescreen"]


def test_prescreen_outputs_created(tmp_path, monkeypatch):
    monkeypatch.chdir(Path(__file__).resolve().parents[1])
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    settings = get_settings()
    state = QAFactoryOrchestrator(settings).run(
        "prescreen",
        "Need SaaS QA tester for multi-tenant Stripe billing auth audit. Fixed $450 for 10 hours.",
        execution_mode="auto",
    )
    assert state.system_suitability
    assert state.estimated_effort
    assert "PRESCREENING_REPORT.md" in state.generated_outputs
    assert "EXECUTION_FLOW.md" in state.generated_outputs
    assert "APPROVAL_CHECKPOINTS.md" in state.generated_outputs
    assert "SYSTEM_DIALOG_GUIDE.md" in state.generated_outputs
    assert "TESTING_READINESS_CHECKLIST.md" in state.generated_outputs
    assert (settings.output_dir / state.project_id / "READ_ME_FIRST.md").exists()
