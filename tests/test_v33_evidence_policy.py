"""v3.3 — evidence escalation + video-qualification + load-test authorization (concept §8/§9)."""
from __future__ import annotations

import pytest

from core.scout.evidence_policy import (
    LEVEL_BASIC,
    LEVEL_REPRODUCE,
    VIDEO_MANUAL,
    VIDEO_QUALIFIED_AUTO,
    EvidenceSettings,
    evidence_level_for,
    video_qualified,
)
from core.scout.load_test_policy import (
    PERF_SINGLE_USER,
    LoadTestAuthorization,
    LoadTestNotAuthorized,
    assert_public_scout_performance_only,
    authorize_load_test,
)


# --- evidence escalation -----------------------------------------------------------------------
def test_low_severity_stays_basic():
    assert evidence_level_for(severity="low", evidence_confidence=90, reproducible=True,
                              screenshots_sufficient=False) == LEVEL_BASIC


def test_reproducible_high_when_screenshots_insufficient_reaches_reproduce():
    assert evidence_level_for(severity="high", evidence_confidence=40, reproducible=True,
                              screenshots_sufficient=False) == LEVEL_REPRODUCE


# --- video qualification -----------------------------------------------------------------------
def test_manual_mode_never_auto_qualifies():
    s = EvidenceSettings(video_mode=VIDEO_MANUAL)
    ok, _ = video_qualified(s, severity="high", qa_score=90, reproduced=True,
                            visual_or_interaction=True, screenshots_sufficient=False,
                            safe_deterministic_path=True)
    assert ok is False


def test_qualified_auto_requires_reproduced_visual_safe():
    s = EvidenceSettings(video_mode=VIDEO_QUALIFIED_AUTO)
    ok, why = video_qualified(s, severity="high", qa_score=90, reproduced=True,
                              visual_or_interaction=True, screenshots_sufficient=False,
                              safe_deterministic_path=True)
    assert ok is True and "qualified" in why
    # never fabricate: not reproduced => not allowed
    ok2, why2 = video_qualified(s, severity="high", qa_score=90, reproduced=False,
                                visual_or_interaction=True, screenshots_sufficient=False,
                                safe_deterministic_path=True)
    assert ok2 is False and "not reproduced" in why2


def test_video_duration_hard_capped_at_30s():
    assert EvidenceSettings(max_video_seconds=600).max_video_seconds == 30


def test_video_cap_per_campaign():
    s = EvidenceSettings(video_mode=VIDEO_QUALIFIED_AUTO, max_videos_per_campaign=2)
    ok, why = video_qualified(s, severity="high", qa_score=90, reproduced=True,
                              visual_or_interaction=True, screenshots_sufficient=False,
                              safe_deterministic_path=True, videos_recorded=2)
    assert ok is False and "max_videos" in why


# --- load-test authorization -------------------------------------------------------------------
def test_public_scout_is_single_user_only():
    assert_public_scout_performance_only(PERF_SINGLE_USER)     # ok
    with pytest.raises(LoadTestNotAuthorized):
        assert_public_scout_performance_only("concurrent_load")


def test_load_test_refused_without_complete_authorization():
    with pytest.raises(LoadTestNotAuthorized):
        authorize_load_test(LoadTestAuthorization(approved=True), "https://example.com")


def test_load_test_allowed_only_for_allowlisted_host_with_full_auth():
    auth = LoadTestAuthorization(
        approved=True, owned_or_client_authorized=True, hostname_allowlist=("staging.mine.com",),
        max_concurrency=5, max_rate_per_s=2.0, abort_error_rate=0.1, isolated_test_data=True,
        documented_scope="signed SOW #42")
    authorize_load_test(auth, "https://staging.mine.com/checkout")   # ok
    with pytest.raises(LoadTestNotAuthorized):
        authorize_load_test(auth, "https://someone-elses-site.com")
