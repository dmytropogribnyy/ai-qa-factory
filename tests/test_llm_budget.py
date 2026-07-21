"""Slice 3 — Scout budget-safe LLM guard.

3a: strict model allowlist. Scout's autonomous LLM use is Haiku/Sonnet ONLY; Opus and any unknown
model are refused in code (never a silent premium spend), independent of profile config.
"""
from __future__ import annotations

import pytest

from core.scout.llm_budget import ModelNotAllowed, ensure_allowed, is_allowed_model, model_tier


def test_haiku_and_sonnet_are_allowed():
    assert model_tier("anthropic/claude-haiku-4-5") == "haiku"
    assert model_tier("anthropic/claude-sonnet-5") == "sonnet"
    assert model_tier("anthropic/claude-sonnet-4-6") == "sonnet"
    assert is_allowed_model("anthropic/claude-haiku-4-5")
    assert ensure_allowed("anthropic/claude-haiku-4-5") == "haiku"


def test_opus_is_refused():
    assert model_tier("anthropic/claude-opus-4-7") is None
    assert not is_allowed_model("anthropic/claude-opus-4-7")
    with pytest.raises(ModelNotAllowed):
        ensure_allowed("anthropic/claude-opus-4-7")


def test_unknown_or_other_provider_model_is_refused():
    for m in ("gpt-4o", "gemini-1.5-pro", "mistral-large", "", "claude", "some-random"):
        assert model_tier(m) is None, m
        assert not is_allowed_model(m), m
        with pytest.raises(ModelNotAllowed):
            ensure_allowed(m)
