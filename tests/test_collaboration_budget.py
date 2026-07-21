"""Direct Collaboration Driver v1 (Issue #14.E) — budget + reliability guardrails, fail-closed."""
from __future__ import annotations

import pytest

from core.collaboration.budget import (
    BudgetLedger,
    BudgetPolicy,
    RetryExhausted,
    run_with_retries,
)


def _ledger(tmp_path, **overrides):
    policy = BudgetPolicy(**{**dict(per_thread_calls=2, per_thread_usd=1.0, daily_calls=3,
                                    daily_usd=5.0, max_input_chars=50, max_retries=3,
                                    backoff_base_seconds=0.01), **overrides})
    clock = overrides.pop("clock", None) or (lambda: "2026-07-21T20:00:00+00:00")
    return BudgetLedger(str(tmp_path), policy=policy, clock=clock)


def test_call_allowed_until_thread_call_cap_then_fails_closed(tmp_path):
    led = _ledger(tmp_path)
    assert led.check("t-1").allowed is True
    led.record("t-1", calls=1, usd=0.1)
    led.record("t-1", calls=1, usd=0.1)
    v = led.check("t-1")
    assert v.allowed is False
    assert v.cap == "per_thread_calls"


def test_daily_call_cap_blocks_across_threads(tmp_path):
    led = _ledger(tmp_path, daily_calls=2, per_thread_calls=99)
    led.record("t-1", calls=1, usd=0.1)
    led.record("t-2", calls=1, usd=0.1)
    v = led.check("t-3")
    assert v.allowed is False
    assert v.cap == "daily_calls"


def test_spend_cap_blocks_when_thread_usd_exceeded(tmp_path):
    led = _ledger(tmp_path, per_thread_calls=99)
    led.record("t-1", calls=1, usd=1.0)
    v = led.check("t-1")
    assert v.allowed is False
    assert v.cap == "per_thread_usd"


def test_response_cache_round_trips_by_fingerprint(tmp_path):
    led = _ledger(tmp_path)
    assert led.cache_get("fp-abc") is None
    led.cache_put("fp-abc", {"verdict": "GO", "message": "looks good"})
    assert led.cache_get("fp-abc")["verdict"] == "GO"


def test_clamp_input_redacts_and_bounds_length(tmp_path):
    led = _ledger(tmp_path, max_input_chars=40)
    out = led.clamp_input("Authorization: Bearer abcdefghijklmnopqrstuvwxyz " + "x" * 200)
    assert len(out) <= 40
    assert "abcdefghijklmnopqrstuvwxyz" not in out


def test_retries_are_bounded_with_exponential_backoff(tmp_path):
    sleeps = []
    calls = {"n": 0}

    def always_fails():
        calls["n"] += 1
        raise RuntimeError("boom")

    policy = BudgetPolicy(max_retries=3, backoff_base_seconds=0.5)
    with pytest.raises(RetryExhausted):
        run_with_retries(always_fails, policy=policy, sleep=sleeps.append)
    assert calls["n"] == 3                       # bounded: exactly max_retries attempts, no infinite loop
    assert sleeps == [0.5, 1.0]                  # backoff between attempts only (2 gaps for 3 tries)


def test_retries_return_first_success(tmp_path):
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 2:
            raise RuntimeError("transient")
        return "ok"

    assert run_with_retries(flaky, policy=BudgetPolicy(max_retries=3), sleep=lambda _s: None) == "ok"
    assert calls["n"] == 2


def test_ledger_persists_usage_across_restart(tmp_path):
    led = _ledger(tmp_path)
    led.record("t-1", calls=1, usd=0.4)
    reopened = _ledger(tmp_path)
    usage = reopened.usage("t-1")
    assert usage["thread_calls"] == 1
    assert usage["thread_usd"] == pytest.approx(0.4)
    assert usage["daily_calls"] == 1
