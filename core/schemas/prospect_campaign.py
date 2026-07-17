"""Prospect Radar campaign-definition contracts (Phase 8.2 — slice 1).

Planning / contracts only. No runtime, no discovery, no crawling, no network, no MCP,
no CLI. These dataclasses only *describe* a prospecting campaign and the policies that
would bound a future, separately approved execution phase.

Slice-1 scope (see `docs/handoffs/PHASE_8_2_REUSE_ANALYSIS.md`):
`ProspectCampaign`, `CampaignTargetCriteria`, `MarketPolicy`, `DiscoverySourcePolicy`.
The interaction boundary and action classes live in `prospect_interaction.py`.

REUSE NOTES (verified against the repository):
- Serialization: `core.schemas.base.SchemaMixin` (unknown keys ignored → additive-safe).
- Origin/owner: reuses `core.schemas.source_reference.SourceReference` rather than
  inventing a new provenance model.
- Lifecycle/versioning: mirrors the `WorkRunState` pattern (uuid id, UTC ISO
  timestamps, explicit `schema_version`) *without* reusing client-work states — a
  campaign is planning-only and carries no execution states here.
- Policy shape: modeled on `ToolExecutionPolicy` / `IntegrationPolicy`
  (`read_only=True`, conservative approval defaults). No executable config.
- `DiscoverySourcePolicy` mirrors the reference-only manifest pattern of
  `config/mcp_servers.yaml`: a source is only a *planning candidate*; it never asserts
  verified runtime availability.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin
from core.schemas.source_reference import SourceReference
from core.schemas.prospect_interaction import (
    PROSPECT_CONTRACT_SCHEMA_VERSION,
    InteractionBoundary,
)

# Planning-only campaign states. No execution/delivery states are modeled here —
# those belong to later, separately approved phases.
CAMPAIGN_STATUSES = frozenset({
    "DRAFT",
    "PLANNED",
    "READY_FOR_REVIEW",
    "ARCHIVED",
})

# Discovery-source vocabularies (reference-only planning categories).
DISCOVERY_SOURCE_CATEGORIES = frozenset({
    "search_engine",
    "business_directory",
    "map_listing",
    "public_registry",
    "social_public",
    "news_or_pr",
    "manual_seed",
})

CONTACT_SOURCE_CATEGORIES = frozenset({
    "public_website",
    "public_directory",
    "public_registry",
    "manual_entry",
})

# Planned outreach channels. "none" is the safe default; anything else stays
# approval-gated (never auto-approved by policy).
OUTREACH_CHANNELS = frozenset({
    "none",
    "email",
    "contact_form",
})

# Expected data classification of a discovery source.
SOURCE_DATA_CLASSES = frozenset({
    "public",
    "business",
    "sensitive_pii",
})

TRUST_LEVELS = frozenset({"low", "medium", "high"})

# A discovery source is never "available" in Phase 8.2 — only a planning candidate.
PROVIDER_RESOLUTION_STATUSES = frozenset({
    "unresolved",
    "candidate",
    "planned_gap",
})

LEGAL_REVIEW_STATUSES = frozenset({
    "not_reviewed",
    "in_review",
    "reviewed_approved",
    "reviewed_blocked",
})


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class CampaignTargetCriteria(SchemaMixin):
    """Target-selection criteria for a prospecting campaign (pure data)."""

    countries: List[str] = field(default_factory=list)
    regions: List[str] = field(default_factory=list)
    languages: List[str] = field(default_factory=list)
    industries: List[str] = field(default_factory=list)
    business_types: List[str] = field(default_factory=list)
    required_flows: List[str] = field(default_factory=list)
    preferred_flows: List[str] = field(default_factory=list)
    include_keywords: List[str] = field(default_factory=list)
    exclude_keywords: List[str] = field(default_factory=list)
    # Minimum commercial qualification score a target must reach (0..100).
    min_commercial_qualification: int = 0
    # Share of the campaign budget spent on exploration vs. exploitation (0..100 %).
    exploration_budget_pct: float = 0.0
    # Planning limits. 0 == unset (planning-only); negative is invalid.
    max_targets: int = 0
    max_pages_per_target: int = 0
    max_sessions_planned: int = 0

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if not 0 <= self.min_commercial_qualification <= 100:
            raise ValueError(
                "min_commercial_qualification must be within 0..100, got "
                f"{self.min_commercial_qualification}"
            )
        if not 0.0 <= self.exploration_budget_pct <= 100.0:
            raise ValueError(
                "exploration_budget_pct must be within 0.0..100.0, got "
                f"{self.exploration_budget_pct}"
            )
        for name, value in (
            ("max_targets", self.max_targets),
            ("max_pages_per_target", self.max_pages_per_target),
            ("max_sessions_planned", self.max_sessions_planned),
        ):
            if value < 0:
                raise ValueError(f"{name} cannot be negative, got {value}")

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "CampaignTargetCriteria":
        return super().from_dict(data)


@dataclass
class DiscoverySourcePolicy(SchemaMixin):
    """Read-only planning policy for one discovery source.

    A source is a *planning candidate only*. `read_only` is forced True and the
    resolution status can never assert verified runtime availability in Phase 8.2.
    """

    source_category: str = "manual_seed"
    enabled: bool = False                 # disabled by default; planning candidate only
    trust_level: str = "low"
    expected_data_class: str = "public"
    read_only: bool = True                # discovery is always read-only in 8.2
    public_only: bool = True
    estimated_cost_usd: float = 0.0
    max_requests_planned: int = 0         # 0 == unset planning-only
    max_results_planned: int = 0
    provider_resolution_status: str = "unresolved"
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        if self.source_category not in DISCOVERY_SOURCE_CATEGORIES:
            raise ValueError(f"Unknown discovery source_category: {self.source_category!r}")
        if self.trust_level not in TRUST_LEVELS:
            raise ValueError(f"Unknown trust_level: {self.trust_level!r}")
        if self.expected_data_class not in SOURCE_DATA_CLASSES:
            raise ValueError(f"Unknown expected_data_class: {self.expected_data_class!r}")
        if self.estimated_cost_usd < 0:
            raise ValueError("estimated_cost_usd cannot be negative")
        for name, value in (
            ("max_requests_planned", self.max_requests_planned),
            ("max_results_planned", self.max_results_planned),
        ):
            if value < 0:
                raise ValueError(f"{name} cannot be negative, got {value}")
        # Fail-closed planning invariants: discovery is always read-only in Phase 8.2,
        # and an unknown provider-resolution status is rejected (never silently rewritten
        # and never an available/verified runtime state).
        self.read_only = True
        if self.provider_resolution_status not in PROVIDER_RESOLUTION_STATUSES:
            raise ValueError(
                f"Unknown provider_resolution_status: {self.provider_resolution_status!r}"
            )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiscoverySourcePolicy":
        return super().from_dict(data)


@dataclass
class MarketPolicy(SchemaMixin):
    """Per-market policy decisions and review status (stores decisions, not law).

    This schema records *policy decisions and a legal-review status*. It does not
    decide legality and never auto-approves outreach: whenever any outreach channel
    other than "none" is allowed, `manual_review_required` is forced True.
    """

    market_id: str = ""                   # e.g. country/region identifier
    allowed_discovery_source_categories: List[str] = field(default_factory=list)
    allowed_contact_source_categories: List[str] = field(default_factory=list)
    allowed_outreach_channels: List[str] = field(default_factory=lambda: ["none"])
    manual_review_required: bool = True
    retention_required: bool = True
    suppression_required: bool = True
    respect_robots: bool = True
    legal_review_status: str = "not_reviewed"
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        self._validate()

    def _validate(self) -> None:
        _require_subset(
            self.allowed_discovery_source_categories,
            DISCOVERY_SOURCE_CATEGORIES,
            "allowed_discovery_source_categories",
        )
        _require_subset(
            self.allowed_contact_source_categories,
            CONTACT_SOURCE_CATEGORIES,
            "allowed_contact_source_categories",
        )
        _require_subset(
            self.allowed_outreach_channels,
            OUTREACH_CHANNELS,
            "allowed_outreach_channels",
        )
        if self.legal_review_status not in LEGAL_REVIEW_STATUSES:
            raise ValueError(f"Unknown legal_review_status: {self.legal_review_status!r}")
        # "none" is a sentinel meaning "no outreach" and cannot coexist with a real
        # outreach channel (fail closed rather than accept an ambiguous policy).
        if "none" in self.allowed_outreach_channels and any(
            ch != "none" for ch in self.allowed_outreach_channels
        ):
            raise ValueError(
                "'none' cannot coexist with a real outreach channel in "
                "allowed_outreach_channels"
            )
        # Policy may never imply automatic outreach approval: any real outreach channel
        # keeps manual review mandatory. respect_robots cannot be disabled here.
        if any(ch != "none" for ch in self.allowed_outreach_channels):
            self.manual_review_required = True
        self.respect_robots = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MarketPolicy":
        return super().from_dict(data)


@dataclass
class ProspectCampaign(SchemaMixin):
    """A prospecting campaign header (planning-only).

    Composes target criteria, a market policy, read-only discovery-source policies,
    and a fail-closed interaction boundary. Carries an explicit `schema_version` and
    uuid id / UTC ISO timestamps following the existing schema conventions.
    """

    id: str = field(default_factory=lambda: str(uuid4()))
    name: str = ""
    schema_version: str = PROSPECT_CONTRACT_SCHEMA_VERSION
    status: str = "DRAFT"
    created_at: str = field(default_factory=_now_iso)
    updated_at: str = field(default_factory=_now_iso)
    owner: str = ""
    source: SourceReference = field(default_factory=SourceReference)
    target_criteria: CampaignTargetCriteria = field(default_factory=CampaignTargetCriteria)
    market_policy: MarketPolicy = field(default_factory=MarketPolicy)
    discovery_sources: List[DiscoverySourcePolicy] = field(default_factory=list)
    interaction_boundary: InteractionBoundary = field(default_factory=InteractionBoundary)
    notes: List[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.status not in CAMPAIGN_STATUSES:
            raise ValueError(f"Unknown campaign status: {self.status!r}")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "schema_version": self.schema_version,
            "status": self.status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "owner": self.owner,
            "source": self.source.to_dict(),
            "target_criteria": self.target_criteria.to_dict(),
            "market_policy": self.market_policy.to_dict(),
            "discovery_sources": [d.to_dict() for d in self.discovery_sources],
            "interaction_boundary": self.interaction_boundary.to_dict(),
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ProspectCampaign":
        known = {
            "id", "name", "schema_version", "status",
            "created_at", "updated_at", "owner", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}

        source = data.get("source")
        kwargs["source"] = (
            SourceReference.from_dict(source) if isinstance(source, dict)
            else SourceReference()
        )
        criteria = data.get("target_criteria")
        kwargs["target_criteria"] = (
            CampaignTargetCriteria.from_dict(criteria) if isinstance(criteria, dict)
            else CampaignTargetCriteria()
        )
        market = data.get("market_policy")
        kwargs["market_policy"] = (
            MarketPolicy.from_dict(market) if isinstance(market, dict)
            else MarketPolicy()
        )
        sources = data.get("discovery_sources") or []
        kwargs["discovery_sources"] = [
            DiscoverySourcePolicy.from_dict(s) for s in sources if isinstance(s, dict)
        ]
        boundary = data.get("interaction_boundary")
        kwargs["interaction_boundary"] = (
            InteractionBoundary.from_dict(boundary) if isinstance(boundary, dict)
            else InteractionBoundary()
        )
        return cls(**kwargs)


def _require_subset(values: List[str], allowed: frozenset[str], field_name: str) -> None:
    """Fail closed: unknown values raise rather than silently becoming permissive."""
    for value in values:
        if value not in allowed:
            raise ValueError(f"Unknown value {value!r} in {field_name}")
