"""What came of a site — the one verdict History, Details and the client package all quote.

History used to report "Analyzed" and "Prospect". Neither is an outcome: the first repeats that a
scan happened, the second repeats that nobody has been contacted. An operator reading the list could
not tell a company with three confirmed defects and a public mailbox from one that came back clean
without opening both.

The verdict is derived, never stored, and it is derived from the SAME read model the target page
renders (``CampaignService.target_detail``). That matters more than it looks: a stored verdict drifts
the moment evidence is re-walked or a manual check rescues a target, and two independently-computed
verdicts drift immediately. Here the row and the page cannot disagree, because they are the same
sentence computed once.

The fail-closed rule from PR #51 is inherited rather than re-implemented: ``target_detail`` already
withholds confirmed findings for an incomplete analysis, so a blocked target arrives here with zero
findings and cannot be dressed up as a clean result.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List

READY_TO_CONTACT = "ready_to_contact"
NEEDS_REVIEW = "needs_review"
NO_ACTIONABLE = "no_actionable_findings"
BLOCKED = "blocked"
FAILED = "failed"
# A sixth value, and a deliberate departure from the five the specification lists. A target that was
# discovered but never scanned did not fail — nothing was attempted. Folding it into "Failed" would
# report an event that never happened, and "Not analyzed" is the wording already used on the target
# card for the same state.
NOT_ANALYZED = "not_analyzed"

LABELS = {
    READY_TO_CONTACT: "Ready to contact",
    NEEDS_REVIEW: "Needs review",
    NO_ACTIONABLE: "No actionable findings",
    BLOCKED: "Blocked",
    FAILED: "Failed",
    NOT_ANALYZED: "Not analyzed",
}

# Badge tone per verdict, so the colour agrees with the words next to it.
KINDS = {
    READY_TO_CONTACT: "ok",
    NEEDS_REVIEW: "attention",
    NO_ACTIONABLE: "",
    BLOCKED: "attention",
    FAILED: "danger",
    NOT_ANALYZED: "",
}

_IMAGE_SUFFIXES = (".png", ".jpg", ".jpeg", ".webp", ".gif")
_VIDEO_SUFFIXES = (".webm", ".mp4")


@dataclass
class SiteResult:
    result: str
    label: str
    kind: str                       # badge tone
    priority: str                   # A/B/C from the scorecard, "" when none was written
    findings: int
    actionable: int
    screenshots: int
    has_video: bool
    contact_email: str
    contact_source_url: str
    reason: str                     # why it is blocked/failed, in the engine's own words

    @property
    def evidence_label(self) -> str:
        """What was actually captured — never a blank cell that could mean "still working"."""
        parts: List[str] = []
        if self.screenshots:
            parts.append(f"{self.screenshots} screenshot"
                         f"{'s' if self.screenshots != 1 else ''}")
        if self.has_video:
            parts.append("video")
        return " · ".join(parts) if parts else "None captured"

    @property
    def can_draft_outreach(self) -> bool:
        """No confirmed actionable finding means there is nothing honest to write about."""
        return self.actionable > 0

    def to_dict(self) -> Dict[str, Any]:
        return {**self.__dict__, "evidence_label": self.evidence_label,
                "can_draft_outreach": self.can_draft_outreach}


def site_result(detail: Dict[str, Any]) -> SiteResult:
    """Turn one ``target_detail`` read model into the verdict shown wherever the site appears."""
    detail = detail or {}
    # ONE canonical split, shared with the fix offer and the outreach draft. Counting here with a
    # private rule is exactly how "1 confirmed issue" came to sit above "we can fix 2".
    from core.scout.actionable import actionable_set
    canonical = actionable_set(detail.get("findings") or [])
    findings = canonical.actionable + canonical.informational
    actionable = canonical.actionable
    media = [str(m) for m in (detail.get("media") or [])]
    screenshots = sum(1 for m in media if m.lower().endswith(_IMAGE_SUFFIXES))
    has_video = any(m.lower().endswith(_VIDEO_SUFFIXES) for m in media)
    records = list(detail.get("contact_records") or [])
    first = records[0] if records else {}
    prospect_status = str(detail.get("prospect_status") or "")
    entry = detail.get("entry") or {}
    # The registry persists these lower-cased ("analyzed"/"failed"); prospect statuses are upper.
    # Comparing the two vocabularies without normalising is how "analyzed" fell through to Failed.
    registry_status = str(entry.get("analysis_status") or "").strip().upper()
    manual = detail.get("manual_action") or {}
    reason = str(manual.get("reason") or entry.get("reason") or "")

    if prospect_status == "MANUAL_ACTION_REQUIRED":
        verdict = BLOCKED
    elif prospect_status == "FAILED" or registry_status == "FAILED":
        verdict = FAILED
        reason = reason or "the run could not complete this target"
    elif prospect_status == "DONE" or detail.get("analysis_complete") is True:
        if actionable:
            # A confirmed defect is only "ready to contact" when there is a proven public mailbox to
            # send it to. Without one the operator has to find a channel first — that is review work,
            # not a finished result.
            verdict = READY_TO_CONTACT if first.get("email") else NEEDS_REVIEW
        else:
            verdict = NO_ACTIONABLE
    elif detail.get("evidence_status") in ("prospect_not_found", "error"):
        # The scan happened — the registry records it — but the run we resolved holds no prospect
        # for this domain, so its evidence cannot be reached. Calling that "Failed" would assert a
        # scan failure that never occurred. It is a human's problem to look at, not a bad outcome.
        verdict = NEEDS_REVIEW if registry_status == "ANALYZED" else FAILED
        reason = reason or ("the analysis is recorded, but its evidence could not be located in "
                            "the run resolved for this site")
    elif prospect_status in ("PENDING", "") and not detail.get("scout_run"):
        verdict = NOT_ANALYZED
    elif prospect_status in ("PENDING", "SKIPPED"):
        verdict = NOT_ANALYZED
        reason = reason or f"the run recorded this target as {prospect_status.lower()}"
    else:
        verdict = FAILED
        reason = reason or "the analysis did not complete"

    # The scorecard arrives already gated by the read model: it is withheld for an incomplete
    # analysis exactly like the findings it is derived from, so a blocked target cannot show a rank.
    return SiteResult(
        result=verdict, label=LABELS[verdict], kind=KINDS[verdict],
        priority=str((detail.get("scorecard") or {}).get("priority") or ""),
        findings=len(findings), actionable=len(actionable),
        screenshots=screenshots, has_video=has_video,
        contact_email=str(first.get("email") or ""),
        contact_source_url=str(first.get("source_url") or ""),
        reason=reason)
