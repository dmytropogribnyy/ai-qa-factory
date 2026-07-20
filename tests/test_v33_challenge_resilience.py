"""v3.3 — campaign-level challenge resilience: one CAPTCHA blocks one target, not the campaign."""
from __future__ import annotations

from core.scout.challenge_resilience import (
    BLOCKED_BY_CHALLENGE,
    CH_ACCESS_DENIED,
    CH_HCAPTCHA,
    CH_NONE,
    CH_RECAPTCHA,
    CH_TURNSTILE,
    ChallengeEvent,
    ChallengeTracker,
    classify_challenge,
)


def test_classifies_common_challenge_types():
    assert classify_challenge(page_text="Please complete the reCAPTCHA") == CH_RECAPTCHA
    assert classify_challenge(markers=["cf-turnstile"]) == CH_TURNSTILE
    assert classify_challenge(page_text="h-captcha widget") == CH_HCAPTCHA
    assert classify_challenge(page_text="Access denied — you have been blocked") == CH_ACCESS_DENIED
    assert classify_challenge(page_text="Welcome to our shop") == CH_NONE


def test_one_challenged_target_does_not_stop_the_campaign():
    t = ChallengeTracker(max_consecutive_challenged=5)
    ev = ChallengeEvent(campaign_id="c", target="a.com", url="https://a.com",
                        challenge_type=CH_RECAPTCHA)
    t.record_target(challenged=True, event=ev)
    stop, reason = t.should_stop_campaign()
    assert stop is False and reason == ""
    assert t.counters()["challenged_targets"] == 1
    assert BLOCKED_BY_CHALLENGE == "BLOCKED_BY_CHALLENGE"   # the target status marker exists


def test_accessible_target_resets_the_consecutive_streak():
    t = ChallengeTracker(max_consecutive_challenged=3)
    t.record_target(challenged=True)
    t.record_target(challenged=True)
    t.record_target(challenged=False)      # reset
    t.record_target(challenged=True)
    assert t.should_stop_campaign()[0] is False   # streak was reset, only 1 consecutive now


def test_excessive_consecutive_challenges_stops_campaign():
    t = ChallengeTracker(max_consecutive_challenged=3)
    for _ in range(3):
        t.record_target(challenged=True)
    stop, reason = t.should_stop_campaign()
    assert stop is True and reason == "excessive_consecutive_challenged_targets"


def test_high_challenge_rate_stops_campaign():
    t = ChallengeTracker(max_consecutive_challenged=100, max_challenge_rate=0.5,
                         min_targets_for_rate=4)
    # 4 of 5 challenged => rate 0.8 > 0.5, but interleave so consecutive never hits 100
    for challenged in (True, False, True, True, True):
        t.record_target(challenged=challenged)
    stop, reason = t.should_stop_campaign()
    assert stop is True and reason == "challenge_rate_above_threshold"
