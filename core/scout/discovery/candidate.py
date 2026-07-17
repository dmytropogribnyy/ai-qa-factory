"""Runtime candidate representation for the discovery pipeline (Phase 8.4).

`CandidateRecord` is the mutable working record threaded through the pipeline
(normalize -> dedup -> suppression -> technical eligibility -> commercial triage ->
promotion). It carries explainable reason codes at every stage and a reference to the
Scout run it was promoted into (if any). It never holds contact data.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

# Duplicate classification.
DUP_UNIQUE = "unique"
DUP_URL = "duplicate_url"
DUP_DOMAIN = "duplicate_domain"
DUP_COMPANY = "duplicate_company"
DUP_UNCERTAIN = "uncertain_identity"        # marked for review; never silently merged

# Suppression classification (none, or one of the Phase 8.2 SuppressionPolicy modes).
SUP_NONE = "none"

# Technical eligibility.
TECH_PENDING, TECH_OK, TECH_REJECT, TECH_SKIPPED = "pending", "technical_ok", "technical_reject", "skipped"

# Commercial triage.
COMM_PENDING, COMM_ELIGIBLE, COMM_WEAK, COMM_REJECT = "pending", "eligible", "weak", "rejected"

# Promotion decision.
PROMO_PENDING, PROMO_PROMOTED, PROMO_NOT_PROMOTED, PROMO_HELD = (
    "pending", "promoted", "not_promoted", "held_for_review",
)


@dataclass
class CandidateRecord:
    candidate_id: str = ""
    campaign_id: str = ""
    provider_id: str = ""
    source_provenance: List[Dict[str, Any]] = field(default_factory=list)  # SourceReference dicts
    public_url: str = ""
    normalized_url: str = ""
    registrable_domain: str = ""
    business_name: str = ""
    country_hint: str = ""
    language_hint: str = ""
    industry_hint: str = ""
    business_type_hint: str = ""
    discovered_at: str = ""
    confidence: str = "low"

    duplicate_status: str = DUP_UNIQUE
    duplicate_of: str = ""

    suppression_status: str = SUP_NONE
    suppression_reason: str = ""

    eligibility_status: str = TECH_PENDING
    technical_reasons: List[str] = field(default_factory=list)

    commercial_status: str = COMM_PENDING
    commercial_score: int = 0
    commercial_scorecard: Dict[str, Any] = field(default_factory=dict)  # LeadScorecard dict
    commercial_reasons: List[str] = field(default_factory=list)

    promotion_decision: str = PROMO_PENDING
    promoted_scout_run: str = ""
    reason_codes: List[str] = field(default_factory=list)

    def add_reason(self, code: str) -> None:
        if code not in self.reason_codes:
            self.reason_codes.append(code)

    @property
    def is_scannable(self) -> bool:
        """A candidate may be HTTP-profiled only if not a duplicate and not NO_SCAN-suppressed."""
        return (self.duplicate_status in (DUP_UNIQUE, DUP_UNCERTAIN)
                and self.suppression_status != "NO_SCAN")

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CandidateRecord":
        known = set(cls().__dict__.keys())
        return cls(**{k: v for k, v in data.items() if k in known})
