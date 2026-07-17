"""Prospect Radar scoring contracts (Phase 8.2 — slice 4, foundation only).

Planning / contracts only. No scoring runtime against real businesses, no contact lookup,
no outreach eligibility by default, no hidden single-score model. Every score dimension
stays independently visible; an optional weighted total is computed only from explicit,
valid weights.

REUSE NOTES (verified against the repository):
- Serialization: `core.schemas.base.SchemaMixin`.
- `agents/opportunity_filter.py` (`OpportunityFilterAgent`) is a *runtime heuristic*
  precursor (fit-score / apply-skip). It is inspected as prior art only and deliberately
  NOT reused here — this module is a pure data contract, not a scoring engine.
- Version string reuses `PROSPECT_CONTRACT_SCHEMA_VERSION`.

This schema states no legal or commercial conclusion as fact; dimensions are explainable
observations with reasons and risk notes. Access complexity is an independent dimension,
never the inverse of commercial opportunity; public coverage is separate from commercial
capacity; remediation fit never lowers audit value automatically.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

from core.schemas.base import SchemaMixin
from core.schemas.prospect_interaction import PROSPECT_CONTRACT_SCHEMA_VERSION

# The independent score dimensions. Each is scored 0..100 on its own axis.
SCORE_DIMENSIONS = frozenset({
    "technical_confidence",
    "business_impact",
    "evidence_quality",
    "audit_opportunity",
    "contactability",
    "commercial_capacity",
    "market_fit",
    "website_criticality",
    "outreach_value",
    "public_coverage",
    "access_complexity",
    "remediation_fit",
})


class ProspectPriority(str, Enum):
    """Coarse prospect priority grade. `REJECTED` is an explicit non-pursuit grade."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"
    REJECTED = "REJECTED"


_VALID_PRIORITIES = frozenset(p.value for p in ProspectPriority)


@dataclass
class ScoreDimension(SchemaMixin):
    """One independent, explainable score axis (0..100)."""

    name: str = ""
    value: int = 0
    reasons: List[str] = field(default_factory=list)
    risk_notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.name not in SCORE_DIMENSIONS:
            raise ValueError(f"Unknown score dimension: {self.name!r}")
        if not isinstance(self.value, int) or isinstance(self.value, bool):
            raise ValueError(f"score value must be an int, got {self.value!r}")
        if not 0 <= self.value <= 100:
            raise ValueError(f"score value must be within 0..100, got {self.value}")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ScoreDimension":
        return super().from_dict(data)


@dataclass
class LeadScorecard(SchemaMixin):
    """A prospect scorecard keeping every dimension independently visible (planning-only).

    An optional `weighted_total` is computed only when `weights` are explicit and valid
    (known present dimensions, non-negative, positive sum); weights are normalized to sum
    to 1. With no weights, `weighted_total` stays `None` — there is no hidden opaque score.
    `outreach_eligible` defaults False and is never derived automatically.
    """

    schema_version: str = PROSPECT_CONTRACT_SCHEMA_VERSION
    prospect_id: str = ""
    dimensions: List[ScoreDimension] = field(default_factory=list)
    priority: str = "D"
    weights: Dict[str, float] = field(default_factory=dict)
    weighted_total: Optional[float] = None
    outreach_eligible: bool = False
    rationale: List[str] = field(default_factory=list)
    risk_notes: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.priority not in _VALID_PRIORITIES:
            raise ValueError(f"Unknown prospect priority: {self.priority!r}")
        names = [d.name for d in self.dimensions]
        if len(names) != len(set(names)):
            raise ValueError("duplicate score dimension in scorecard")
        if self.weights:
            self._validate_and_compute_weights()
        else:
            self.weighted_total = None

    def _validate_and_compute_weights(self) -> None:
        dim_by_name = {d.name: d for d in self.dimensions}
        total = 0.0
        for name, weight in self.weights.items():
            if name not in SCORE_DIMENSIONS:
                raise ValueError(f"weight for unknown dimension: {name!r}")
            if name not in dim_by_name:
                raise ValueError(f"weight for a dimension not present in scorecard: {name!r}")
            if weight < 0:
                raise ValueError(f"weight cannot be negative: {name}={weight}")
            total += weight
        if total <= 0:
            raise ValueError("weights must sum to a positive value")
        normalized = {name: weight / total for name, weight in self.weights.items()}
        self.weights = normalized
        self.weighted_total = round(
            sum(normalized[name] * dim_by_name[name].value for name in normalized), 6
        )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "prospect_id": self.prospect_id,
            "dimensions": [d.to_dict() for d in self.dimensions],
            "priority": self.priority,
            "weights": dict(self.weights),
            "weighted_total": self.weighted_total,
            "outreach_eligible": self.outreach_eligible,
            "rationale": list(self.rationale),
            "risk_notes": list(self.risk_notes),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "LeadScorecard":
        known = {
            "schema_version", "prospect_id", "priority", "weights", "weighted_total",
            "outreach_eligible", "rationale", "risk_notes", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        dims = data.get("dimensions") or []
        kwargs["dimensions"] = [
            ScoreDimension.from_dict(d) for d in dims if isinstance(d, dict)
        ]
        return cls(**kwargs)
