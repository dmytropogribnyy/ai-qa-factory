"""Normalized findings with a full lifecycle (Final Phase I).

A `NormalizedFinding` carries two orthogonal states:

- a **verification** state (reusing the Scout lifecycle):
  UNVERIFIED -> REPRODUCED -> EVIDENCE_CAPTURED -> SANITIZED -> VERIFIED; and
- a **finding** lifecycle: ACTIVE -> RESOLVED -> REGRESSED.

Only an independently reproduced, sanitized, VERIFIED finding from a CLEAN session (verified
reversible-session cleanup, when applicable) that is currently ACTIVE with unexpired evidence is
CLIENT_SAFE. Normalization merges overlapping observations only when they share one root user
impact (`root_impact_key`); distinct defects are never merged just because titles look similar,
and provenance is always preserved.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

# Verification lifecycle (reused from the Scout runtime).
V_UNVERIFIED, V_REPRODUCED, V_EVIDENCE, V_SANITIZED, V_VERIFIED, V_REJECTED = (
    "UNVERIFIED", "REPRODUCED", "EVIDENCE_CAPTURED", "SANITIZED", "VERIFIED", "REJECTED",
)
VERIFICATION_STATES = frozenset({V_UNVERIFIED, V_REPRODUCED, V_EVIDENCE, V_SANITIZED,
                                 V_VERIFIED, V_REJECTED})

# Finding lifecycle.
L_ACTIVE, L_RESOLVED, L_REGRESSED = "ACTIVE", "RESOLVED", "REGRESSED"
LIFECYCLE_STATES = frozenset({L_ACTIVE, L_RESOLVED, L_REGRESSED})

SEVERITIES = ("info", "low", "medium", "high")
CONFIDENCES = ("low", "medium", "high")
CATEGORIES = frozenset({
    "accessibility", "performance", "seo", "structured_data", "mobile", "functional",
    "business_flow", "reliability", "coverage", "security",
})


@dataclass
class NormalizedFinding:
    finding_id: str = ""
    campaign_id: str = ""
    company_id: str = ""
    session_id: str = ""
    url: str = ""
    capability: str = ""                 # axe | performance | seo | flow | ...
    category: str = "functional"
    title: str = ""
    severity: str = "low"
    confidence: str = "medium"
    root_impact_key: str = ""            # normalization key: one shared root user impact
    signature: str = ""                  # stable reproduction signature
    reproduction_steps: List[str] = field(default_factory=list)
    expected: str = ""
    actual: str = ""
    business_impact: str = ""
    evidence_ids: List[str] = field(default_factory=list)
    provenance: List[Dict[str, Any]] = field(default_factory=list)
    verification_state: str = V_UNVERIFIED
    lifecycle_state: str = L_ACTIVE
    sanitized: bool = False
    from_clean_session: bool = True      # False if it came from an unclean reversible session
    evidence_expired: bool = False
    first_seen_at: str = ""
    last_seen_at: str = ""
    resolved_at: str = ""
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
        if self.lifecycle_state not in LIFECYCLE_STATES:
            raise ValueError(f"unknown lifecycle_state: {self.lifecycle_state!r}")

    @property
    def is_client_safe(self) -> bool:
        """CLIENT_SAFE only when independently verified, sanitized, current, from a clean
        session, and with unexpired evidence."""
        return (self.verification_state == V_VERIFIED and self.sanitized
                and self.from_clean_session and not self.evidence_expired
                and self.lifecycle_state in (L_ACTIVE, L_REGRESSED))

    @property
    def is_draftable(self) -> bool:
        """A finding may back a draft only when CLIENT_SAFE and currently ACTIVE (a RESOLVED
        finding can never enter a draft)."""
        return self.is_client_safe and self.lifecycle_state == L_ACTIVE

    def to_dict(self) -> Dict[str, Any]:
        d = dict(self.__dict__)
        d["is_client_safe"] = self.is_client_safe
        d["is_draftable"] = self.is_draftable
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "NormalizedFinding":
        known = set(cls().__dict__.keys())
        kwargs = {k: v for k, v in data.items() if k in known}
        for name in ("reproduction_steps", "evidence_ids", "provenance", "notes"):
            if name in kwargs and not isinstance(kwargs[name], list):
                kwargs[name] = []
        return cls(**kwargs)
