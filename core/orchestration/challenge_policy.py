"""Test identities + challenge handling policy (v3.2 Section 13).

Decides how an authentication/challenge may be handled, by context. It is deterministic and
conservative: PUBLIC Scout targets may only OBSERVE (detect + capture permitted evidence + mark
blocked) and MUST NEVER solve or bypass a CAPTCHA; only explicitly AUTHORIZED CLIENT QA may use
official test keys / staging bypass / test TOTP / a pre-authorized session. Public-target CAPTCHA
solver services (Anti-Captcha and similar) are always PROHIBITED.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List

# Challenge modes.
OFFICIAL_TEST_MODE = "OFFICIAL_TEST_MODE"        # official reCAPTCHA/Turnstile/hCaptcha test keys
CLIENT_TEST_BYPASS = "CLIENT_TEST_BYPASS"        # client-provided staging bypass
AUTHORIZED_SESSION = "AUTHORIZED_SESSION"        # pre-authorized bounded session / test TOTP / OAuth tenant
HUMAN_CHECKPOINT = "HUMAN_CHECKPOINT"            # pause; the operator completes the challenge
OBSERVE_ONLY = "OBSERVE_ONLY"                    # detect + evidence + mark blocked; never solve
PROHIBITED = "PROHIBITED"                        # never allowed

# Preferred test-identity order (Section 13).
IDENTITY_ORDER = ("local_synthetic_identity", "client_staging_account", "gmail_test_inbox_readonly",
                  "authorized_oauth_test_tenant", "human_checkpoint")

# Public-target solver services are never integrated.
PROHIBITED_SOLVER_SERVICES = frozenset({"anti-captcha", "anticaptcha", "2captcha", "deathbycaptcha",
                                        "capmonster", "capsolver"})


@dataclass
class ChallengeDecision:
    mode: str
    allowed: bool
    reason: str
    next_action: str


def decide_challenge(*, scope: str, challenge: str, authorizations: List[str] | None = None,
                     solver_service: str | None = None) -> ChallengeDecision:
    """Return the only permitted handling for a detected challenge.

    ``scope`` is 'public_scout' or 'authorized_client'. ``authorizations`` lists client-provided
    authorizations (e.g. 'official_test_keys', 'staging_bypass', 'test_totp', 'oauth_test_tenant',
    'preauthorized_session'). Any request to use a public-target solver service is refused.
    """
    auths = set(authorizations or [])
    if solver_service and solver_service.strip().lower() in PROHIBITED_SOLVER_SERVICES:
        return ChallengeDecision(PROHIBITED, False,
                                 "public-target CAPTCHA solver services are never integrated",
                                 "do not attempt to solve; mark blocked and continue safe checks")

    if scope == "public_scout":
        # Public Scout NEVER solves or bypasses a challenge.
        return ChallengeDecision(OBSERVE_ONLY, False,
                                 "public Scout must not solve or bypass challenges",
                                 "detect, capture permitted evidence, mark blocked, continue safe "
                                 "checks; never retry after denial")

    if scope == "authorized_client":
        if "official_test_keys" in auths and challenge in ("recaptcha", "turnstile", "hcaptcha"):
            return ChallengeDecision(OFFICIAL_TEST_MODE, True,
                                     "official test keys authorized for client QA",
                                     "use the official test key in the client test environment")
        if "staging_bypass" in auths:
            return ChallengeDecision(CLIENT_TEST_BYPASS, True,
                                     "client staging bypass authorized",
                                     "use the client-provided staging bypass")
        if auths & {"test_totp", "oauth_test_tenant", "preauthorized_session"}:
            return ChallengeDecision(AUTHORIZED_SESSION, True,
                                     "authorized bounded session / test identity",
                                     "use the pre-authorized test identity")
        return ChallengeDecision(HUMAN_CHECKPOINT, True,
                                 "no automated authorization; pause for the operator",
                                 "pause + preserve state; the operator completes the challenge, then "
                                 "resume")
    return ChallengeDecision(PROHIBITED, False, "unknown scope",
                             "define an authorized scope before handling any challenge")
