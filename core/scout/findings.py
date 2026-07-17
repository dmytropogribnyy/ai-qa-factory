"""Scout findings + verification lifecycle (Phase 8.3).

A `ScoutFinding` is a bounded, sanitizable QA observation. Findings carry an independent
verification state and never embed secrets/PII/cookies/tokens (evidence is stored by
reference only). Scoring is separate and never authorizes outreach.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

SEVERITIES = ("info", "low", "medium", "high")
CONFIDENCES = ("low", "medium", "high")

CATEGORIES = frozenset({
    "functional", "accessibility", "performance", "seo", "structured_data",
    "mobile", "business_flow", "reliability", "coverage",
})

# Verification lifecycle (fail-closed): only a fully verified + sanitized finding is CLIENT_SAFE.
VERIFY_UNVERIFIED = "UNVERIFIED"
VERIFY_REPRODUCED = "REPRODUCED"
VERIFY_EVIDENCE_CAPTURED = "EVIDENCE_CAPTURED"
VERIFY_SANITIZED = "SANITIZED"
VERIFY_VERIFIED = "VERIFIED"
VERIFY_REJECTED = "REJECTED"

VERIFICATION_STATES = (
    VERIFY_UNVERIFIED, VERIFY_REPRODUCED, VERIFY_EVIDENCE_CAPTURED,
    VERIFY_SANITIZED, VERIFY_VERIFIED, VERIFY_REJECTED,
)


@dataclass
class ScoutFinding:
    """One bounded QA finding (planning + evidence-by-reference only)."""

    finding_id: str = ""
    run_id: str = ""
    prospect_ref: str = ""
    url: str = ""
    check_family: str = ""
    category: str = "functional"
    title: str = ""
    severity: str = "low"
    confidence: str = "medium"
    reproduction_steps: List[str] = field(default_factory=list)
    expected: str = ""
    actual: str = ""
    business_impact: str = ""
    environment: Dict[str, Any] = field(default_factory=dict)
    evidence_refs: List[str] = field(default_factory=list)
    sanitized: bool = False
    verification_state: str = VERIFY_UNVERIFIED
    coverage_limitation: str = ""
    # A stable, backend-independent signature used to confirm reproduction.
    signature: str = ""
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.severity not in SEVERITIES:
            raise ValueError(f"unknown severity: {self.severity!r}")
        if self.confidence not in CONFIDENCES:
            raise ValueError(f"unknown confidence: {self.confidence!r}")
        if self.category not in CATEGORIES:
            raise ValueError(f"unknown category: {self.category!r}")
        if self.verification_state not in VERIFICATION_STATES:
            raise ValueError(f"unknown verification_state: {self.verification_state!r}")

    @property
    def is_client_safe(self) -> bool:
        """Client-safe only when independently verified AND sanitized."""
        return self.verification_state == VERIFY_VERIFIED and self.sanitized

    def to_dict(self) -> Dict[str, Any]:
        return {
            "finding_id": self.finding_id, "run_id": self.run_id,
            "prospect_ref": self.prospect_ref, "url": self.url,
            "check_family": self.check_family, "category": self.category,
            "title": self.title, "severity": self.severity, "confidence": self.confidence,
            "reproduction_steps": list(self.reproduction_steps),
            "expected": self.expected, "actual": self.actual,
            "business_impact": self.business_impact, "environment": dict(self.environment),
            "evidence_refs": list(self.evidence_refs), "sanitized": self.sanitized,
            "verification_state": self.verification_state,
            "coverage_limitation": self.coverage_limitation, "signature": self.signature,
            "notes": list(self.notes), "is_client_safe": self.is_client_safe,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScoutFinding":
        known = {
            "finding_id", "run_id", "prospect_ref", "url", "check_family", "category",
            "title", "severity", "confidence", "reproduction_steps", "expected", "actual",
            "business_impact", "environment", "evidence_refs", "sanitized",
            "verification_state", "coverage_limitation", "signature", "notes",
        }
        obj = cls(**{k: v for k, v in data.items() if k in known})
        # Fail closed: never rehydrate a finding as already sanitized/verified.
        obj.sanitized = False
        obj.verification_state = VERIFY_UNVERIFIED
        return obj
