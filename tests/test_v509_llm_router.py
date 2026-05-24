"""P1.5 regression tests — silent mock fallback counter."""


def test_fallback_to_mock_increments_counter(monkeypatch):
    """When all real LLM calls fail, fallback_to_mock_count must be incremented."""
    monkeypatch.setenv("LLM_MODE", "real")
    monkeypatch.setenv("MODEL_PROFILE", "budget")

    from core.config import Settings
    from core.llm_router import LLMRouter

    settings = Settings()
    assert not settings.is_mock, "Settings must be in real mode for this test."

    def always_fail(self, *args, **kwargs):
        raise RuntimeError("simulated LLM API failure")

    monkeypatch.setattr(LLMRouter, "_litellm_completion", always_fail)

    router = LLMRouter(settings)
    assert router.fallback_to_mock_count == 0

    response = router.complete("analysis", "system prompt", "user prompt")

    assert router.fallback_to_mock_count == 1, (
        f"Expected fallback_to_mock_count=1, got {router.fallback_to_mock_count}. "
        "The counter must increment when all real calls fail and mock is used."
    )
    assert response.used_fallback is True
    assert response.model == "mock"
