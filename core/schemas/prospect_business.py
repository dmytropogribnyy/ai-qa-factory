"""Prospect Radar business & site profile contracts (Phase 8.2 — slice 2).

Planning / contracts only. No runtime, discovery, crawling, browser, network, MCP,
provider, contact lookup, outreach, or database. These dataclasses only *describe*
observed/inferred context about a prospect business and its site.

Slice-2 scope (see `docs/handoffs/PHASE_8_2_REUSE_ANALYSIS.md`):
`BusinessContext`, `SiteProfile`, `BusinessFlowProfile` (this module) and
`CoverageMap` / `SiteFingerprint` (`prospect_coverage.py`).

REUSE NOTES (verified against the repository):
- Serialization: `core.schemas.base.SchemaMixin` (unknown keys ignored → additive-safe).
- Confidence vocabulary reuses `core.schemas.finding.Confidence` values (high/medium/low).
- Provenance reuses `core.schemas.source_reference.SourceReference`.
- Planned interaction risk reuses `InteractionActionClass` from `prospect_interaction.py`.
- Capability references are validated against the existing `ATOMIC_CAPABILITIES`
  vocabulary (`core.schemas.capability`) — no new capability names are invented here.
- Version string reuses `PROSPECT_CONTRACT_SCHEMA_VERSION`.

Nothing here asserts that any page was tested, or that a company is able or willing to
pay. Every classification defaults to an explicit "unknown".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from core.schemas.base import SchemaMixin
from core.schemas.capability import ATOMIC_CAPABILITIES
from core.schemas.finding import Confidence
from core.schemas.source_reference import SourceReference
from core.schemas.prospect_interaction import (
    PROSPECT_CONTRACT_SCHEMA_VERSION,
    InteractionActionClass,
)

# Reused confidence vocabulary (values of the existing Confidence enum).
CONFIDENCE_LEVELS = frozenset(c.value for c in Confidence)

# Business/organization taxonomy (the KIND of commercial entity). Distinct from
# RESOURCE_TYPES (the kind of digital resource). Older values are retained for backward
# compatibility; richer categories were added in slice-2 hardening (A1).
BUSINESS_TYPES = frozenset({
    "unknown",
    # backward-compatible values previously accepted for business_type:
    "ecommerce", "saas", "marketplace", "local_service", "lead_generation",
    "content_media", "booking", "other",
    # richer organization categories:
    "ecommerce_business", "saas_company", "marketplace_operator", "agency",
    "professional_services", "education", "real_estate", "hospitality", "hotel",
    "clinic", "restaurant", "personal_brand", "startup_mvp",
})

# Digital-resource taxonomy (the KIND of site/application). Distinct from BUSINESS_TYPES.
# Older values retained for backward compatibility.
RESOURCE_TYPES = frozenset({
    "unknown",
    # backward-compatible values previously accepted for resource_type:
    "ecommerce", "saas", "local_service", "marketplace", "content_media", "booking",
    "lead_generation", "other",
    # richer resource categories:
    "corporate_site", "ecommerce_site", "saas_marketing_site", "web_application",
    "booking_site", "premium_landing", "public_app_area", "authenticated_app",
})

BUSINESS_MODELS = frozenset({
    "unknown",
    "b2c",
    "b2b",
    "b2b2c",
    "marketplace",
    "subscription",
    "transactional",
    "advertising",
    "other",
})

IMPORTANCE_LEVELS = frozenset({"unknown", "low", "medium", "high"})

ACCESS_CLASSIFICATIONS = frozenset({
    "unknown",
    "public_open",
    "protected",
    "partially_protected",
    "authenticated_required",
})

FLOW_TYPES = frozenset({
    "unknown",
    "checkout",
    "booking",
    "signup",
    "login",
    "search",
    "contact",
    "lead_capture",
    "subscription",
    "payment",
    "other",
})

FLOW_ROLES = frozenset({"primary", "secondary"})

CRITICALITY_LEVELS = frozenset({"low", "medium", "high", "critical"})

_VALID_ACTION_CLASSES = frozenset(c.value for c in InteractionActionClass)


def _require_subset(values: List[str], allowed: frozenset[str], field_name: str) -> None:
    """Fail closed: unknown values raise rather than silently becoming permissive."""
    for value in values:
        if value not in allowed:
            raise ValueError(f"Unknown value {value!r} in {field_name}")


def _dedup(seq: List[str]) -> List[str]:
    """Order-preserving de-duplication."""
    seen: set[str] = set()
    out: List[str] = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


@dataclass
class BusinessContext(SchemaMixin):
    """Observed / inferred commercial context for a prospect (planning-only).

    Records observations and signals, not conclusions. `commercial_capacity_signals`
    are observed hints — this schema never asserts that a company is definitely able
    or willing to pay. Unknown classification stays explicit (`unknown` defaults).
    """

    schema_version: str = PROSPECT_CONTRACT_SCHEMA_VERSION
    business_type: str = "unknown"
    business_model: str = "unknown"
    countries: List[str] = field(default_factory=list)
    regions: List[str] = field(default_factory=list)
    languages: List[str] = field(default_factory=list)
    markets: List[str] = field(default_factory=list)
    commercial_capacity_signals: List[str] = field(default_factory=list)
    primary_flows: List[str] = field(default_factory=list)
    secondary_flows: List[str] = field(default_factory=list)
    confidence: str = "low"
    sources: List[SourceReference] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.business_type not in BUSINESS_TYPES:
            raise ValueError(f"Unknown business_type: {self.business_type!r}")
        if self.business_model not in BUSINESS_MODELS:
            raise ValueError(f"Unknown business_model: {self.business_model!r}")
        if self.confidence not in CONFIDENCE_LEVELS:
            raise ValueError(f"Unknown confidence: {self.confidence!r}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "business_type": self.business_type,
            "business_model": self.business_model,
            "countries": list(self.countries),
            "regions": list(self.regions),
            "languages": list(self.languages),
            "markets": list(self.markets),
            "commercial_capacity_signals": list(self.commercial_capacity_signals),
            "primary_flows": list(self.primary_flows),
            "secondary_flows": list(self.secondary_flows),
            "confidence": self.confidence,
            "sources": [s.to_dict() for s in self.sources],
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BusinessContext":
        known = {
            "schema_version", "business_type", "business_model", "countries",
            "regions", "languages", "markets", "commercial_capacity_signals",
            "primary_flows", "secondary_flows", "confidence", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        sources = data.get("sources") or []
        kwargs["sources"] = [
            SourceReference.from_dict(s) for s in sources if isinstance(s, dict)
        ]
        return cls(**kwargs)


@dataclass
class SiteProfile(SchemaMixin):
    """Observed technical profile of a prospect site (planning-only).

    Technology indicators are *observations*, not a claim that any page was tested.
    Public and authenticated surfaces are tracked separately; access classification
    and its confidence are explicit.
    """

    schema_version: str = PROSPECT_CONTRACT_SCHEMA_VERSION
    domain_ref: str = ""
    resource_type: str = "unknown"
    technology_indicators: List[str] = field(default_factory=list)
    languages: List[str] = field(default_factory=list)
    markets: List[str] = field(default_factory=list)
    mobile_importance: str = "unknown"
    seo_importance: str = "unknown"
    public_surfaces: List[str] = field(default_factory=list)
    authenticated_surfaces: List[str] = field(default_factory=list)
    access_classification: str = "unknown"
    classification_confidence: str = "low"
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.resource_type not in RESOURCE_TYPES:
            raise ValueError(f"Unknown resource_type: {self.resource_type!r}")
        if self.mobile_importance not in IMPORTANCE_LEVELS:
            raise ValueError(f"Unknown mobile_importance: {self.mobile_importance!r}")
        if self.seo_importance not in IMPORTANCE_LEVELS:
            raise ValueError(f"Unknown seo_importance: {self.seo_importance!r}")
        if self.access_classification not in ACCESS_CLASSIFICATIONS:
            raise ValueError(
                f"Unknown access_classification: {self.access_classification!r}"
            )
        if self.classification_confidence not in CONFIDENCE_LEVELS:
            raise ValueError(
                f"Unknown classification_confidence: {self.classification_confidence!r}"
            )
        # Surface consistency (A2): de-duplicate, forbid a route appearing in both
        # lists, and forbid public_open coexisting with authenticated surfaces.
        self.public_surfaces = _dedup(self.public_surfaces)
        self.authenticated_surfaces = _dedup(self.authenticated_surfaces)
        overlap = set(self.public_surfaces) & set(self.authenticated_surfaces)
        if overlap:
            raise ValueError(
                "a surface cannot be both public and authenticated: "
                f"{sorted(overlap)}"
            )
        if self.access_classification == "public_open" and self.authenticated_surfaces:
            raise ValueError(
                "access_classification 'public_open' cannot have authenticated surfaces"
            )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SiteProfile":
        return super().from_dict(data)


@dataclass
class BusinessFlowProfile(SchemaMixin):
    """A classified business flow and its planned (not executed) interaction limits."""

    schema_version: str = PROSPECT_CONTRACT_SCHEMA_VERSION
    flow_id: str = ""
    flow_name: str = ""
    flow_type: str = "unknown"
    role: str = "primary"
    criticality: str = "medium"
    affects_revenue: bool = False
    affects_lead_generation: bool = False
    affects_trust: bool = False
    required_capabilities: List[str] = field(default_factory=list)
    planned_interaction_action_class: str = InteractionActionClass.READ_ONLY.value
    execution_constraints: List[str] = field(default_factory=list)
    access_constraints: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.flow_type not in FLOW_TYPES:
            raise ValueError(f"Unknown flow_type: {self.flow_type!r}")
        if self.role not in FLOW_ROLES:
            raise ValueError(f"Unknown role: {self.role!r}")
        if self.criticality not in CRITICALITY_LEVELS:
            raise ValueError(f"Unknown criticality: {self.criticality!r}")
        _require_subset(
            self.required_capabilities, ATOMIC_CAPABILITIES, "required_capabilities"
        )
        if self.planned_interaction_action_class not in _VALID_ACTION_CLASSES:
            raise ValueError(
                "Unknown planned_interaction_action_class: "
                f"{self.planned_interaction_action_class!r}"
            )
        # A planned Scout interaction is never destructive. This field describes the
        # planned Prospect Radar interaction class, not what the site itself can do;
        # actual permission is governed only by InteractionBoundary.
        if self.planned_interaction_action_class == InteractionActionClass.DESTRUCTIVE.value:
            raise ValueError(
                "DESTRUCTIVE is not a valid planned_interaction_action_class for a "
                "prospect flow"
            )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BusinessFlowProfile":
        return super().from_dict(data)
