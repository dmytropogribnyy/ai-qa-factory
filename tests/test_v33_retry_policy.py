"""v3.3 — bounded self-recovery/retry policy: transient failures retry, terminal never, no loops."""
from __future__ import annotations

import pytest

from core.scout.retry_policy import (
    RETRYABLE,
    TERMINAL,
    RetryPolicy,
    classify_failure,
    is_retryable,
)


def test_transient_failures_are_retryable():
    for kind in ("provider_timeout", "http_429", "dns_transient", "browser_page_crash",
                 "file_lock", "stale_owner"):
        assert classify_failure(kind) == RETRYABLE
        assert is_retryable(kind) is True


def test_terminal_and_unknown_failures_are_not_retryable():
    for kind in ("access_denied", "captcha_challenge", "irreversible_boundary",
                 "cleanup_failed_unsafe", "budget_exhausted", "something_unknown"):
        assert classify_failure(kind) == TERMINAL      # unknown fails closed => terminal
        assert is_retryable(kind) is False


def test_retry_stops_at_max_attempts_no_infinite_loop():
    p = RetryPolicy(max_attempts=3)
    assert p.should_retry(kind="http_429", attempt=1)[0] is True
    assert p.should_retry(kind="http_429", attempt=2)[0] is True
    stop, reason = p.should_retry(kind="http_429", attempt=3)
    assert stop is False and reason == "max_attempts_reached"


def test_terminal_failure_never_retries():
    p = RetryPolicy(max_attempts=5)
    stop, reason = p.should_retry(kind="access_denied", attempt=1)
    assert stop is False and reason.startswith("terminal_failure")


def test_backoff_is_bounded_and_increases():
    p = RetryPolicy(base_delay_s=1.0, backoff_factor=2.0, max_delay_s=10.0, jitter_ratio=0.0)
    d1 = p.next_delay(1, rand=0.5)
    d2 = p.next_delay(2, rand=0.5)
    d5 = p.next_delay(5, rand=0.5)
    assert d1 == 1.0 and d2 == 2.0
    assert d5 == 10.0                                  # capped, never unbounded


def test_jitter_stays_within_bounds():
    p = RetryPolicy(base_delay_s=4.0, backoff_factor=1.0, max_delay_s=4.0, jitter_ratio=0.25)
    lo = p.next_delay(1, rand=0.0)                     # -25%
    hi = p.next_delay(1, rand=1.0)                     # +25%
    assert 3.0 <= lo <= 4.0 <= hi <= 5.0


def test_bad_config_rejected():
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)
