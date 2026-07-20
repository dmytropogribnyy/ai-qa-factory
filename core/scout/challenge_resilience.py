"""Campaign-level challenge resilience (v3.3) — one CAPTCHA must NOT stop the whole campaign.

Reuses the existing decision policy (`core/orchestration/challenge_policy.py`: public Scout is
OBSERVE_ONLY, never solves/bypasses, solver services prohibited). This module adds the campaign-
level *non-blocking* behaviour the operator needs for unattended runs:

- classify the challenge type (recaptcha / hcaptcha / turnstile / generic / bot-verification /
  access-denied / login-wall / rate-limit);
- mark the affected TARGET/path BLOCKED_BY_CHALLENGE (never wait for the operator, never retry the
  challenge, never solve it);
- keep going to the next target and reallocate its unused budget;
- stop the whole campaign only when a configured campaign-wide threshold is reached (too many
  consecutive challenged targets, or the challenge rate is too high, or nothing accessible remains).

No public CAPTCHA solver, token injection, or fingerprint evasion is ever added.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

# Challenge types (detection only).
CH_RECAPTCHA = "recaptcha"
CH_HCAPTCHA = "hcaptcha"
CH_TURNSTILE = "turnstile"
CH_GENERIC_CAPTCHA = "generic_captcha"
CH_BOT_VERIFICATION = "bot_verification"
CH_ACCESS_DENIED = "access_denied"
CH_LOGIN_WALL = "login_wall"
CH_RATE_LIMIT = "rate_limit"
CH_NONE = ""

BLOCKED_BY_CHALLENGE = "BLOCKED_BY_CHALLENGE"

# Ordered (most specific first) marker → type.
_MARKERS = (
    (CH_RECAPTCHA, ("recaptcha", "g-recaptcha", "grecaptcha")),
    (CH_HCAPTCHA, ("hcaptcha", "h-captcha")),
    (CH_TURNSTILE, ("cf-turnstile", "turnstile")),
    (CH_RATE_LIMIT, ("rate limit", "too many requests", "429", "slow down")),
    (CH_BOT_VERIFICATION, ("are you a robot", "verify you are human", "bot detection",
                           "checking your browser", "attention required")),
    (CH_ACCESS_DENIED, ("access denied", "403 forbidden", "you have been blocked", "not authorized")),
    (CH_LOGIN_WALL, ("please log in", "sign in to continue", "login required", "members only")),
    (CH_GENERIC_CAPTCHA, ("captcha", "i'm not a robot", "security check")),
)


def classify_challenge(*, page_text: str = "", markers=None) -> str:
    """Return the challenge type from page text/markers, or CH_NONE."""
    hay = (page_text or "").lower()
    if markers:
        hay += " " + " ".join(str(m).lower() for m in markers)
    for ch_type, needles in _MARKERS:
        if any(n in hay for n in needles):
            return ch_type
    return CH_NONE


@dataclass
class ChallengeEvent:
    campaign_id: str
    target: str
    url: str
    challenge_type: str
    plan_step: str = ""
    at: str = ""
    evidence_ref: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class ChallengeTracker:
    """Campaign-wide challenge accounting + the non-blocking stop decision."""
    max_consecutive_challenged: int = 5     # stop after this many challenged targets in a row
    max_challenge_rate: float = 0.8         # or when the challenge rate exceeds this (needs >= min)
    min_targets_for_rate: int = 5
    challenged_targets: int = 0
    total_targets: int = 0
    consecutive: int = 0
    events: List[ChallengeEvent] = field(default_factory=list)

    def record_target(self, *, challenged: bool, event: ChallengeEvent = None) -> None:
        """Record one target outcome. A challenged target is blocked, NOT retried, NOT waited on."""
        self.total_targets += 1
        if challenged:
            self.challenged_targets += 1
            self.consecutive += 1
            if event is not None:
                self.events.append(event)
        else:
            self.consecutive = 0            # an accessible target resets the streak

    def should_stop_campaign(self) -> tuple:
        """Return (stop, reason). One challenged target never stops the campaign; only a
        campaign-wide threshold does."""
        if self.consecutive >= self.max_consecutive_challenged:
            return True, "excessive_consecutive_challenged_targets"
        if (self.total_targets >= self.min_targets_for_rate
                and self.challenged_targets / self.total_targets > self.max_challenge_rate):
            return True, "challenge_rate_above_threshold"
        return False, ""

    def counters(self) -> Dict[str, Any]:
        rate = round(self.challenged_targets / self.total_targets, 3) if self.total_targets else 0.0
        return {"challenged_targets": self.challenged_targets, "total_targets": self.total_targets,
                "consecutive_challenged": self.consecutive, "challenge_rate": rate,
                "challenge_events": len(self.events)}
