"""Scout budget-safe LLM guard (Slice 3).

Scout may use an LLM autonomously, but ONLY within explicit owner budgets and ONLY with cheap models.
This module is the enforcement layer that wraps core.llm_router.LLMRouter; it is not a second router.

3a — strict model allowlist (this file, to be extended by the ledger/cache/routing sub-slices):
  Haiku and Sonnet are the ONLY permitted tiers. Opus and any unknown/other-provider model are
  refused IN CODE, regardless of profile config — Scout never makes a silent premium spend. Sonnet
  is permitted but bounded (escalation only) by the budget ledger (later sub-slice); Opus is never
  permitted anywhere.
"""
from __future__ import annotations

from typing import Optional

# Permitted cheap tiers, cheapest first. Opus is deliberately absent and never added.
ALLOWED_TIERS = ("haiku", "sonnet")


class ModelNotAllowed(RuntimeError):
    """Raised when a model outside the Haiku/Sonnet allowlist (e.g. Opus, or any unknown model) is
    requested for a Scout LLM call."""


def model_tier(model: str) -> Optional[str]:
    """Classify a model id into an allowed tier, or None if it is not permitted.

    Returns "haiku" or "sonnet" for an allowed Anthropic cheap model; None for Opus (explicitly
    forbidden) and for any unknown / other-provider model (fail closed)."""
    m = (model or "").strip().lower()
    if not m or "claude-opus" in m:
        return None
    if "claude-haiku" in m:
        return "haiku"
    if "claude-sonnet" in m:
        return "sonnet"
    return None


def is_allowed_model(model: str) -> bool:
    return model_tier(model) is not None


def ensure_allowed(model: str) -> str:
    """Return the allowed tier for ``model`` or raise ModelNotAllowed. The single code-level gate
    every Scout LLM call passes through before any request is made."""
    tier = model_tier(model)
    if tier is None:
        raise ModelNotAllowed(
            f"model not on Scout budget allowlist (Haiku/Sonnet only, never Opus): {model!r}")
    return tier
