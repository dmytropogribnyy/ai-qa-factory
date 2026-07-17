"""Phase 8.3.1 — the concurrency option is honest about the sequential runtime.

v1.0.x runs strictly sequentially, so the only accepted value is 1; anything else fails
closed rather than presenting a decorative option that appears implemented.
"""
from __future__ import annotations

import pytest

from core.scout.config import ScoutConfigError, ScoutRunConfig


def _cfg(**kw):
    base = dict(seeds=["https://example.com/"])
    base.update(kw)
    return ScoutRunConfig(**base)


def test_default_concurrency_is_one():
    assert _cfg().concurrency == 1


@pytest.mark.parametrize("value", [0, 2, 3, 8, 99, -1])
def test_non_unit_concurrency_fails_closed(value):
    with pytest.raises(ScoutConfigError):
        _cfg(concurrency=value)


def test_concurrency_true_bool_rejected():
    with pytest.raises(ScoutConfigError):
        _cfg(concurrency=True)  # bool must not masquerade as 1
