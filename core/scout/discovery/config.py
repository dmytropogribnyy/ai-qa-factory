"""Discovery campaign configuration + budgets (Phase 8.4).

A bounded, fail-closed campaign definition. It validates itself through the Phase 8.2
`ProspectCampaign` / `CampaignTargetCriteria` / `MarketPolicy` / `DiscoverySourcePolicy`
contracts and adds runtime budgets (matrix ceiling, per-provider result budget, candidate /
eligible / promoted caps, time and optional monetary ceilings). It never enables outreach.
"""
from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, FrozenSet, List

from core.schemas.prospect_campaign import (
    CampaignTargetCriteria,
    DiscoverySourcePolicy,
    MarketPolicy,
    ProspectCampaign,
)
from core.scout.url_safety import UrlPolicy


class DiscoveryConfigError(ValueError):
    """Raised when a discovery campaign configuration is invalid."""


def _slug(name: str) -> str:
    return "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-")[:24] or "campaign"


def fresh_campaign_id(name: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"campaign-{_slug(name)}-{stamp}-{secrets.token_hex(3)}"


@dataclass
class DiscoveryCampaignConfig:
    campaign_name: str = "discovery"
    campaign_id: str = ""
    # Target criteria.
    countries: List[str] = field(default_factory=list)
    languages: List[str] = field(default_factory=list)
    industries: List[str] = field(default_factory=list)
    business_types: List[str] = field(default_factory=list)
    keywords: List[str] = field(default_factory=list)
    exclude_keywords: List[str] = field(default_factory=list)
    required_flows: List[str] = field(default_factory=list)
    # Providers.
    provider_allowlist: List[str] = field(default_factory=list)
    # Market policy (outreach stays "none" by default; read-only profiling under NO_OUTREACH
    # is permitted only when explicitly enabled here, and never becomes outreach-ready).
    allowed_discovery_source_categories: List[str] = field(default_factory=list)
    allow_readonly_profiling_when_no_outreach: bool = False
    # Commercial gate.
    min_commercial_threshold: int = 40
    # Budgets (fail-closed).
    matrix_hard_max: int = 500
    max_provider_calls: int = 200
    per_provider_result_budget: int = 50
    max_candidates: int = 500
    max_eligible: int = 200
    max_promoted: int = 10
    time_budget_s: float = 120.0
    cost_ceiling_usd: float = 0.0
    # Promotion / Scout run settings.
    browser_mode: str = "static"
    max_pages_per_site: int = 4
    allowed_local_hosts: FrozenSet[str] = field(default_factory=frozenset)
    resolve_dns: bool = True
    # Runtime.
    output_dir: str = "outputs"
    dry_run: bool = False
    approve_live_discovery: bool = False

    def __post_init__(self) -> None:
        if not self.campaign_name.strip():
            raise DiscoveryConfigError("campaign_name is required")
        if not self.provider_allowlist:
            raise DiscoveryConfigError("at least one provider must be allow-listed")
        if not 0 <= self.min_commercial_threshold <= 100:
            raise DiscoveryConfigError("min_commercial_threshold must be within 0..100")
        for name in ("matrix_hard_max", "max_provider_calls", "per_provider_result_budget",
                     "max_candidates", "max_eligible", "max_promoted"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise DiscoveryConfigError(f"{name} must be a positive int, got {value!r}")
        if self.max_promoted > 50:
            raise DiscoveryConfigError("max_promoted is capped at 50 (bounded promotion)")
        if self.time_budget_s <= 0:
            raise DiscoveryConfigError("time_budget_s must be positive")
        if self.cost_ceiling_usd < 0:
            raise DiscoveryConfigError("cost_ceiling_usd cannot be negative")
        if self.browser_mode not in ("static", "playwright"):
            raise DiscoveryConfigError(f"unknown browser_mode: {self.browser_mode!r}")
        if not (1 <= self.max_pages_per_site <= 50):
            raise DiscoveryConfigError("max_pages_per_site must be within 1..50")
        self.allowed_local_hosts = frozenset(self.allowed_local_hosts)
        if not self.campaign_id:
            self.campaign_id = fresh_campaign_id(self.campaign_name)

    # --- reuse: Phase 8.2 contracts ---------------------------------------
    def build_campaign(self) -> ProspectCampaign:
        """Build (and thereby validate) the Phase 8.2 ProspectCampaign for this config."""
        criteria = CampaignTargetCriteria(
            countries=list(self.countries), languages=list(self.languages),
            industries=list(self.industries), business_types=list(self.business_types),
            include_keywords=list(self.keywords), exclude_keywords=list(self.exclude_keywords),
            required_flows=list(self.required_flows),
            min_commercial_qualification=self.min_commercial_threshold,
            max_targets=self.max_promoted,
        )
        market = self.build_market_policy()
        sources = [
            DiscoverySourcePolicy(source_category="manual_seed", enabled=True,
                                  provider_resolution_status="candidate",
                                  max_results_planned=self.per_provider_result_budget)
            for _ in self.provider_allowlist
        ]
        return ProspectCampaign(
            name=self.campaign_name, status="PLANNED", target_criteria=criteria,
            market_policy=market, discovery_sources=sources)

    def build_market_policy(self) -> MarketPolicy:
        cats = list(self.allowed_discovery_source_categories) or ["manual_seed"]
        return MarketPolicy(market_id=",".join(self.countries) or "unspecified",
                            allowed_discovery_source_categories=cats,
                            allowed_outreach_channels=["none"])  # never outreach in 8.4

    def url_policy(self) -> UrlPolicy:
        return UrlPolicy(allowed_local_hosts=self.allowed_local_hosts, resolve_dns=self.resolve_dns)

    def to_dict(self) -> Dict[str, Any]:
        d = dict(self.__dict__)
        d["allowed_local_hosts"] = sorted(self.allowed_local_hosts)
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DiscoveryCampaignConfig":
        known = set(cls(campaign_name="x", provider_allowlist=["p"]).__dict__.keys())
        kwargs = {k: v for k, v in data.items() if k in known}
        if "allowed_local_hosts" in kwargs:
            kwargs["allowed_local_hosts"] = frozenset(kwargs["allowed_local_hosts"])
        return cls(**kwargs)
