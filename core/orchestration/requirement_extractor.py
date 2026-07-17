"""RequirementExtractor — Phase 8.1 (deterministic, no LLM).

Derives atomic Requirement records from the (redacted) brief plus classification and
profile. Pure heuristics: sentence scanning for obligation cues ("must"/"should"/"need")
plus a small set of profile baseline requirements. It never calls an LLM and never uses
private methods of InitialAnalysisEngine.
"""
from __future__ import annotations

import re
from typing import List

from core.schemas.requirement import Requirement
from core.orchestration.providers import ClockProvider, IdProvider

_OBLIGATION = re.compile(r"\b(must|should|shall|need to|needs to|require[sd]?)\b", re.I)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?;\n])\s+")

# Small deterministic baseline requirements per profile.
_PROFILE_BASELINE: dict[str, list[str]] = {
    "web_app_audit": [
        "Key pages are reachable and render without errors",
        "No critical accessibility violations on primary flows",
        "Page performance is within an acceptable budget",
    ],
    "api_project": [
        "Documented endpoints match their contract",
        "Error responses are handled and documented",
    ],
    "data_project": [
        "Read access to the target data is confirmed and scoped",
        "Schema and access constraints are documented",
    ],
    "code_project": [
        "Implemented change compiles and passes its tests",
        "Change is scoped to the stated deliverable",
    ],
    "automation_project": [
        "Automation trigger and target systems are identified",
        "Side effects are enumerated before any execution",
    ],
    "technical_writing": [
        "Document matches the requested audience and format",
        "Content is grounded in provided source material",
    ],
    "mvp_launch_audit": [
        "Launch-readiness checklist is produced",
        "Critical blockers are identified before go-live",
    ],
    "research_only": [
        "Findings are grounded in cited sources",
    ],
}


class RequirementExtractor:
    """Deterministic requirement extraction."""

    def __init__(self, clock: ClockProvider, ids: IdProvider) -> None:
        self._clock = clock
        self._ids = ids

    def extract(self, redacted_text: str, profile: str, source_ref: str) -> List[Requirement]:
        reqs: List[Requirement] = []
        now = self._clock.now_iso()
        priority = 1

        # Obligation-cued sentences → functional requirements (stable order).
        for sentence in _SENTENCE_SPLIT.split(redacted_text.strip()):
            s = sentence.strip()
            if s and _OBLIGATION.search(s):
                reqs.append(Requirement(
                    id=self._ids.new_id(),
                    text=s[:300],
                    source_ref=source_ref,
                    requirement_type="functional",
                    priority=priority,
                    confidence=0.5,
                    verification_status="unverified",
                    assumptions=["derived heuristically from the brief"],
                    created_at=now,
                ))
                priority += 1

        # Profile baseline requirements (quality/non_functional).
        for baseline in _PROFILE_BASELINE.get(profile, []):
            reqs.append(Requirement(
                id=self._ids.new_id(),
                text=baseline,
                source_ref=f"profile:{profile}",
                requirement_type="quality",
                priority=priority,
                confidence=0.4,
                verification_status="unverified",
                assumptions=["profile baseline; confirm with client"],
                created_at=now,
            ))
            priority += 1

        return reqs
