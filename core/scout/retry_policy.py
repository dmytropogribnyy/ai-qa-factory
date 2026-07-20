"""Bounded self-recovery / retry policy (v3.3) — unattended runs survive ordinary hiccups.

Classifies a failure as RETRYABLE (transient provider/network/browser/file issues) or TERMINAL
(access denial, confirmed challenge, irreversible-boundary refusal, auth bypass, cleanup failure,
malformed config, exhausted budget) and computes a bounded backoff with jitter. There are NO
infinite loops: a maximum attempt count always applies, and terminal failures are never retried.
When a single target fails terminally the caller continues other targets; only a global condition
fails the whole campaign.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

# Failure kinds.
RETRYABLE = "retryable"
TERMINAL = "terminal"

_RETRYABLE_KINDS = frozenset({
    "provider_timeout", "http_429", "dns_transient", "network_transient", "browser_page_crash",
    "browser_context_crash", "evidence_write_transient", "file_lock", "worker_interrupted",
    "stale_owner", "screenshot_transient", "trace_transient",
})
_TERMINAL_KINDS = frozenset({
    "access_denied", "captcha_challenge", "irreversible_boundary", "auth_bypass_required",
    "unauthorized_action", "cleanup_failed_unsafe", "malformed_config", "budget_exhausted",
})


def classify_failure(kind: str) -> str:
    """Return RETRYABLE or TERMINAL for a failure kind (unknown kinds fail closed => TERMINAL)."""
    k = (kind or "").strip().lower()
    if k in _RETRYABLE_KINDS:
        return RETRYABLE
    return TERMINAL   # unknown / explicitly-terminal kinds are never retried (fail closed)


def is_retryable(kind: str) -> bool:
    return classify_failure(kind) == RETRYABLE


@dataclass
class RetryPolicy:
    max_attempts: int = 3            # hard cap — no infinite loops
    base_delay_s: float = 0.5
    max_delay_s: float = 30.0
    backoff_factor: float = 2.0
    jitter_ratio: float = 0.2

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")

    def next_delay(self, attempt: int, *, rand: float = 0.5) -> float:
        """Bounded exponential backoff with deterministic-injectable jitter (attempt starts at 1)."""
        raw = self.base_delay_s * (self.backoff_factor ** max(0, attempt - 1))
        capped = min(raw, self.max_delay_s)
        # jitter in [-jitter_ratio, +jitter_ratio] of the capped delay (rand in [0,1))
        jitter = capped * self.jitter_ratio * (2 * rand - 1)
        return max(0.0, round(capped + jitter, 4))

    def should_retry(self, *, kind: str, attempt: int) -> Tuple[bool, str]:
        """Decide whether to retry a failure of `kind` on this attempt (1-based)."""
        if not is_retryable(kind):
            return False, f"terminal_failure:{kind}"
        if attempt >= self.max_attempts:
            return False, "max_attempts_reached"
        return True, "retry"
