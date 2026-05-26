"""Verify that pytest always runs under mock LLM config regardless of .env."""

from __future__ import annotations

import os



def test_llm_mode_env_is_mock() -> None:
    assert os.environ.get("LLM_MODE") == "mock", (
        "LLM_MODE must be 'mock' during tests. "
        "If you want real LLM tests, run: "
        "LLM_MODE=real MODEL_PROFILE=<profile> python -m pytest -q"
    )


def test_model_profile_env_is_mock() -> None:
    assert os.environ.get("MODEL_PROFILE") == "mock", (
        "MODEL_PROFILE must be 'mock' during tests."
    )


def test_settings_resolve_to_mock() -> None:
    from core.config import get_settings

    settings = get_settings()
    assert settings.llm_mode == "mock"
    assert settings.model_profile == "mock"
    assert settings.is_mock is True


def test_llm_router_returns_mock_responses_for_representative_tasks() -> None:
    """is_mock=True gates all real calls regardless of individual model config strings."""
    from core.config import get_settings
    from core.llm_router import LLMRouter

    settings = get_settings()
    assert settings.is_mock, "Settings.is_mock must be True during default test run"
    router = LLMRouter(settings)
    # One representative task type per alias family
    for task_type in ("job", "scaffold", "review", "upwork", "vision"):
        response = router.complete(task_type, "system", "test prompt")
        assert response.model == "mock", (
            f"Task '{task_type}' returned model='{response.model}' — "
            "expected 'mock'. Real provider calls must not happen in tests."
        )


def test_no_real_provider_required_for_smoke() -> None:
    """Smoke check: orchestrator runs without any real LLM key."""
    import tempfile
    from pathlib import Path

    from core.config import get_settings
    from core.orchestrator import QAFactoryOrchestrator

    with tempfile.TemporaryDirectory() as tmp:
        os.environ["OUTPUT_DIR"] = str(Path(tmp) / "outputs")
        settings = get_settings()
        assert settings.is_mock, "Orchestrator must use mock mode during tests"
        state = QAFactoryOrchestrator(settings).run(
            "job", "Need Playwright TypeScript QA for a SaaS app."
        )
        assert state is not None
