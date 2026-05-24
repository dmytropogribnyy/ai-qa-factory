
from types import SimpleNamespace

from core.config import get_settings
from core.llm_router import LLMRouter
from core.orchestrator import QAFactoryOrchestrator


def test_triggered_pre_run_prompts_are_recorded_noninteractive(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("MEMORY_DIR", str(tmp_path / "memory"))
    settings = get_settings()
    state = QAFactoryOrchestrator(settings).run(
        "upwork",
        "Need Playwright tests for Stripe checkout on a live app ASAP.",
    )
    assert state.triggered_prompts_answers["payment_sandbox"] == "not_asked_non_interactive"
    assert state.triggered_prompts_answers["production_safety"] == "not_asked_non_interactive"
    assert state.triggered_prompts_answers["urgency_scope"] == "not_asked_non_interactive"
    assert "triggered_pre_run_prompts.md" in state.generated_outputs


def test_llm_usage_extraction_supports_litellm_shape(tmp_path, monkeypatch):
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    monkeypatch.setenv("MEMORY_DIR", str(tmp_path / "memory"))
    router = LLMRouter(get_settings())
    response = SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=11, completion_tokens=7, total_tokens=18),
        _hidden_params={"response_cost": 0.0012},
    )
    usage = router._extract_usage(response)
    assert usage == {
        "prompt_tokens": 11,
        "completion_tokens": 7,
        "total_tokens": 18,
        "cost_usd": 0.0012,
    }
