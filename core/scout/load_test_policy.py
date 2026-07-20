"""Load/stress-test authorization policy (v3.3, concept §8).

Against arbitrary public third-party sites, Scout performs ONLY single-user, bounded performance
inspection (rendered timing, page weight, blocking resources, slow requests, layout-shift signals).
Real load / stress / soak / volume / endurance testing is a SEPARATE authorized capability and is
refused here unless fully authorized: explicit operator approval, an owned/client-authorized
environment, a hostname allowlist, documented scope, concurrency + rate limits, abort thresholds,
and isolated test data. This module never generates concurrent load itself; it is the guard.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Tuple
from urllib.parse import urlsplit


class LoadTestNotAuthorized(RuntimeError):
    """Raised when load/stress testing is attempted without complete authorization."""


# Public Scout performance is single-user only.
PERF_SINGLE_USER = "single_user_rendered"


@dataclass
class LoadTestAuthorization:
    approved: bool = False
    owned_or_client_authorized: bool = False
    hostname_allowlist: Tuple[str, ...] = field(default_factory=tuple)
    max_concurrency: int = 0
    max_rate_per_s: float = 0.0
    abort_error_rate: float = 0.0
    isolated_test_data: bool = False
    documented_scope: str = ""

    def is_complete(self) -> bool:
        return (self.approved and self.owned_or_client_authorized and bool(self.hostname_allowlist)
                and self.max_concurrency > 0 and self.max_rate_per_s > 0
                and self.abort_error_rate > 0 and self.isolated_test_data
                and bool(self.documented_scope.strip()))


def assert_public_scout_performance_only(mode: str) -> None:
    """A normal public Scout run may only do single-user rendered performance — never load/stress."""
    if mode != PERF_SINGLE_USER:
        raise LoadTestNotAuthorized(
            f"public Scout performs single-user performance only; {mode!r} requires authorized "
            "load-testing mode")


def authorize_load_test(auth: LoadTestAuthorization, target_url: str) -> None:
    """Raise unless authorization is complete AND the target host is on the allowlist."""
    if not auth.is_complete():
        raise LoadTestNotAuthorized("load testing requires complete authorization (approval, owned/"
                                    "authorized env, allowlist, limits, abort threshold, isolated "
                                    "data, documented scope)")
    host = (urlsplit(target_url).hostname or "").lower()
    allow = {h.lower() for h in auth.hostname_allowlist}
    if host not in allow:
        raise LoadTestNotAuthorized(f"host {host!r} is not on the authorized load-test allowlist")
