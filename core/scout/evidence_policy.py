"""Adaptive evidence escalation + video-qualification policy (v3.3, concept §9).

Evidence collection is adaptive, not maximal. The default pass collects lightweight-but-strong
evidence (screenshots, trace, console, network, DOM/visible state, actions, expected/actual, stop
boundary, cleanup). Depth escalates only when a finding becomes more valuable:

    Level 1 basic screenshot + structured observation
    Level 2 + state screenshots / trace / console / network
    Level 3 + safe reproduction attempt
    Level 4 + short video (only when justified)

Continuous video for every site is NOT the default. Video is qualified only when the issue is
interaction/visual, reproducible, screenshots are insufficient, and the reproduction path is safe
and deterministic. Scout never claims successful reproduction or creates synthetic evidence when
reproduction failed (that decision lives in the reproduction runtime; this module only decides
whether a video is *permitted* and bounds it).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Tuple

LEVEL_BASIC = 1
LEVEL_STATE = 2
LEVEL_REPRODUCE = 3
LEVEL_VIDEO = 4

VIDEO_OFF = "off"
VIDEO_MANUAL = "manual"
VIDEO_QUALIFIED_AUTO = "qualified_auto"
_VIDEO_MODES = frozenset({VIDEO_OFF, VIDEO_MANUAL, VIDEO_QUALIFIED_AUTO})

_SEV_RANK = {"info": 0, "low": 1, "medium": 2, "high": 3}


@dataclass
class EvidenceSettings:
    video_mode: str = VIDEO_MANUAL
    max_video_seconds: int = 30
    max_videos_per_campaign: int = 10
    storage_quota_mb: int = 512
    retention_days: int = 30
    auto_cleanup_expired: bool = True
    min_video_severity: str = "medium"
    min_qa_score_for_video: int = 50

    def __post_init__(self) -> None:
        if self.video_mode not in _VIDEO_MODES:
            raise ValueError(f"unknown video_mode: {self.video_mode!r}")
        # 10–30s is the normal useful window; hard-cap at 30s.
        self.max_video_seconds = max(1, min(self.max_video_seconds, 30))


def evidence_level_for(*, severity: str, evidence_confidence: int, reproducible: bool,
                       screenshots_sufficient: bool) -> int:
    """Decide the evidence depth for a finding (never jumps to video unless justified)."""
    sev = _SEV_RANK.get(severity, 0)
    if sev <= 1:
        return LEVEL_BASIC                       # low/info: a screenshot + observation is enough
    if sev == 2 and (screenshots_sufficient or evidence_confidence >= 60):
        return LEVEL_STATE
    if reproducible and not screenshots_sufficient:
        return LEVEL_REPRODUCE
    return LEVEL_STATE


def video_qualified(settings: EvidenceSettings, *, severity: str, qa_score: int, reproduced: bool,
                    visual_or_interaction: bool, screenshots_sufficient: bool,
                    safe_deterministic_path: bool,
                    videos_recorded: int = 0) -> Tuple[bool, str]:
    """Decide whether a qualified-auto short video is permitted for this finding. Returns
    (allowed, reason). Manual/off modes never auto-qualify."""
    if settings.video_mode != VIDEO_QUALIFIED_AUTO:
        return False, f"video_mode={settings.video_mode} (not qualified-auto)"
    if videos_recorded >= settings.max_videos_per_campaign:
        return False, "max_videos_per_campaign reached"
    if _SEV_RANK.get(severity, 0) < _SEV_RANK.get(settings.min_video_severity, 2):
        return False, "below min_video_severity"
    if qa_score < settings.min_qa_score_for_video:
        return False, "below min_qa_score_for_video"
    if not reproduced:
        return False, "not reproduced (never fabricate a video)"
    if not visual_or_interaction:
        return False, "not a visual/interaction issue"
    if screenshots_sufficient:
        return False, "screenshots already sufficient"
    if not safe_deterministic_path:
        return False, "reproduction path not safe/deterministic"
    return True, "qualified: reproduced visual/interaction issue, screenshots insufficient, safe path"
