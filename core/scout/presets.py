"""Session + named-campaign presets for the v3.3 operator workflow.

A *session preset* (Quick / Standard / Extended) carries the hard, finite budgets that bound
one Scout run. A *campaign preset* is a ready-to-use, US/DE-focused campaign template that
defaults to a session preset. `build_config` maps a chosen campaign+session onto the existing
`DiscoveryCampaignConfig` — every run is finite and never enables outreach.

Reuse-first: this module adds NO new engine, provider, or store; it only produces a bounded
`DiscoveryCampaignConfig` that the existing `DiscoveryEngine` already knows how to run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Optional, Tuple

from core.scout.discovery.config import DiscoveryCampaignConfig

# Supported site types (default is the safe commercial company; personal is opt-in/disabled).
SITE_TYPE_COMMERCIAL = "commercial_product_company"
SITE_TYPE_B2B_SAAS = "b2b_saas"
SITE_TYPE_ECOMMERCE = "ecommerce"
SITE_TYPE_BOOKING = "booking_travel"
SITE_TYPE_PROFESSIONAL = "professional_services"
SITE_TYPE_MARKETPLACE = "marketplace"
SITE_TYPE_PERSONAL = "personal_portfolio"

SUPPORTED_SITE_TYPES: Tuple[str, ...] = (
    SITE_TYPE_COMMERCIAL, SITE_TYPE_B2B_SAAS, SITE_TYPE_ECOMMERCE, SITE_TYPE_BOOKING,
    SITE_TYPE_PROFESSIONAL, SITE_TYPE_MARKETPLACE, SITE_TYPE_PERSONAL,
)

# Initial industries only (kept for back-compat).
INITIAL_INDUSTRIES: Tuple[str, ...] = (
    "B2B SaaS", "E-commerce", "Travel/Booking", "Professional Services",
)

# Broad built-in industry taxonomy for the campaign form (multi-select; extend with custom).
INDUSTRY_TAXONOMY: Tuple[str, ...] = (
    "SaaS", "E-commerce", "Marketplaces", "Travel and hospitality", "Professional services",
    "Fintech", "Health and pharma", "Education", "Media and content", "Agencies",
    "B2B platforms", "Local services", "Logistics", "Real estate", "HR and recruiting",
    "Legal services", "Restaurants and food services", "Events", "Subscription services",
)

# Target-type taxonomy for the form (multi-select + include/exclude).
TARGET_TYPE_TAXONOMY: Tuple[str, ...] = (
    "corporate website", "SaaS product", "web application", "e-commerce store", "marketplace",
    "travel or booking platform", "landing page", "startup MVP", "local-business website",
    "professional-services website", "customer portal", "directory", "media or content site",
    "documentation hub", "public dashboard", "agency portfolio", "campaign microsite",
    "signup funnel", "checkout funnel", "booking funnel", "subscription product", "public demo",
)


@dataclass(frozen=True)
class SessionPreset:
    """Finite budgets for one Scout run. Every field is a hard ceiling."""
    key: str
    label: str
    actionable_target: int
    max_discovered: int
    max_qa_analyzed: int
    max_pages_per_site: int
    max_duration_s: int


SESSION_PRESETS: Dict[str, SessionPreset] = {
    "quick": SessionPreset("quick", "Quick", actionable_target=2, max_discovered=15,
                           max_qa_analyzed=5, max_pages_per_site=3, max_duration_s=20 * 60),
    "standard": SessionPreset("standard", "Standard", actionable_target=5, max_discovered=40,
                              max_qa_analyzed=12, max_pages_per_site=5, max_duration_s=45 * 60),
    "extended": SessionPreset("extended", "Extended", actionable_target=10, max_discovered=80,
                              max_qa_analyzed=25, max_pages_per_site=5, max_duration_s=90 * 60),
}


def get_session_preset(key: str) -> SessionPreset:
    """Return a session preset, failing closed (KeyError) on an unknown key."""
    return SESSION_PRESETS[key]


@dataclass(frozen=True)
class CampaignPreset:
    """An editable campaign template (NOT a fixed-ratio workflow). Schedules default to disabled."""
    key: str
    label: str
    countries: Tuple[str, ...]
    languages: Tuple[str, ...]
    site_types: Tuple[str, ...]
    industries: Tuple[str, ...]
    keywords: Tuple[str, ...]
    min_commercial_threshold: int
    session_preset: str
    rescan_interval_days: int
    schedule_mode: str          # manual | daily | weekdays | weekly
    schedule_time: str          # "HH:MM" local
    schedule_timezone: str
    schedule_enabled: bool = False
    exclude_keywords: Tuple[str, ...] = field(default_factory=tuple)
    # Adaptive strategy + optional outcome targets / diversity caps (0 == uncapped/not-a-goal).
    strategy: str = "balanced"
    outcome_targets: Dict[str, int] = field(default_factory=dict)
    diversity_caps: Dict[str, int] = field(default_factory=dict)
    is_smoke: bool = False      # True only for small dev/diagnostic presets (never the default)


_COMMERCIAL_SIGNALS: Tuple[str, ...] = (
    "pricing", "free trial", "book demo", "sign up", "shop", "cart", "availability", "booking",
)

_ALL_COMMERCIAL_SITE_TYPES = (SITE_TYPE_COMMERCIAL, SITE_TYPE_B2B_SAAS, SITE_TYPE_ECOMMERCE,
                              SITE_TYPE_BOOKING, SITE_TYPE_PROFESSIONAL, SITE_TYPE_MARKETPLACE)

# DEFAULT_CAMPAIGN_PRESET is a real production workflow (NOT a 15-minute Quick scan).
DEFAULT_CAMPAIGN_PRESET = "balanced-production"

CAMPAIGN_PRESETS: Dict[str, CampaignPreset] = {
    "balanced-production": CampaignPreset(
        key="balanced-production",
        label="Balanced Production Scout",
        countries=(),                     # no country restriction (configurable in the form)
        languages=("en",),
        site_types=_ALL_COMMERCIAL_SITE_TYPES,
        industries=("SaaS", "E-commerce", "Marketplaces", "Travel and hospitality",
                    "Professional services", "B2B platforms"),
        keywords=_COMMERCIAL_SIGNALS,
        min_commercial_threshold=65,
        session_preset="standard",
        rescan_interval_days=30,
        schedule_mode="manual", schedule_time="09:00", schedule_timezone="Europe/Bratislava",
        strategy="balanced",
        outcome_targets={"actionable": 5},
        diversity_caps={"per_company": 1, "per_industry": 8},
    ),
    "conservative-production": CampaignPreset(
        key="conservative-production",
        label="Conservative Scout",
        countries=(), languages=("en",),
        site_types=(SITE_TYPE_COMMERCIAL, SITE_TYPE_B2B_SAAS, SITE_TYPE_PROFESSIONAL),
        industries=("SaaS", "Professional services", "B2B platforms"),
        keywords=_COMMERCIAL_SIGNALS,
        min_commercial_threshold=72,
        session_preset="standard",
        rescan_interval_days=60,
        schedule_mode="manual", schedule_time="09:00", schedule_timezone="Europe/Bratislava",
        strategy="conservative",
        outcome_targets={"actionable": 3},
        diversity_caps={"per_company": 1, "per_industry": 5},
    ),
    "opportunity-production": CampaignPreset(
        key="opportunity-production",
        label="Opportunity-Maximizing Scout",
        countries=(), languages=("en",),
        site_types=_ALL_COMMERCIAL_SITE_TYPES,
        industries=INDUSTRY_TAXONOMY[:12],
        keywords=_COMMERCIAL_SIGNALS,
        min_commercial_threshold=55,
        session_preset="extended",
        rescan_interval_days=30,
        schedule_mode="manual", schedule_time="09:00", schedule_timezone="Europe/Bratislava",
        strategy="opportunity",
        outcome_targets={"actionable": 10, "min_industries": 4},
        diversity_caps={"per_company": 1, "per_industry": 10},
    ),
    "scheduled-daily": CampaignPreset(
        key="scheduled-daily",
        label="Scheduled Daily Scout",
        countries=(), languages=("en",),
        site_types=_ALL_COMMERCIAL_SITE_TYPES,
        industries=("SaaS", "E-commerce", "Professional services", "B2B platforms"),
        keywords=_COMMERCIAL_SIGNALS,
        min_commercial_threshold=68,
        session_preset="standard",
        rescan_interval_days=30,
        schedule_mode="daily", schedule_time="07:00", schedule_timezone="Europe/Bratislava",
        schedule_enabled=False,           # created disabled; operator enables it explicitly
        strategy="balanced",
        outcome_targets={"actionable": 4},
        diversity_caps={"per_company": 1, "per_industry": 6},
    ),
    "us-de-commercial": CampaignPreset(
        key="us-de-commercial",
        label="US-DE Commercial QA Prospects",
        countries=("us", "de"),
        languages=("en", "de"),
        site_types=(SITE_TYPE_COMMERCIAL, SITE_TYPE_B2B_SAAS, SITE_TYPE_ECOMMERCE,
                    SITE_TYPE_BOOKING),
        industries=("B2B SaaS", "E-commerce", "Travel/Booking"),
        keywords=_COMMERCIAL_SIGNALS,
        min_commercial_threshold=70,
        session_preset="standard",
        rescan_interval_days=30,
        schedule_mode="weekdays", schedule_time="09:00", schedule_timezone="Europe/Bratislava",
        strategy="balanced",
        outcome_targets={"actionable": 5},
        diversity_caps={"per_company": 1},
    ),
    "safe-live-acceptance": CampaignPreset(
        key="safe-live-acceptance",
        label="Safe Live Acceptance — US/DE",
        countries=("us", "de"),
        languages=("en", "de"),
        # Representative but limited vertical coverage for a fast, safe acceptance run.
        site_types=(SITE_TYPE_COMMERCIAL, SITE_TYPE_B2B_SAAS, SITE_TYPE_ECOMMERCE),
        industries=("B2B SaaS", "E-commerce"),
        keywords=_COMMERCIAL_SIGNALS,
        min_commercial_threshold=70,
        session_preset="quick",           # small + bounded: this is an acceptance run, not production
        rescan_interval_days=30,
        schedule_mode="manual", schedule_time="09:00", schedule_timezone="Europe/Bratislava",
        strategy="conservative",          # safest allocation for a live external run
        outcome_targets={"actionable": 2},
        diversity_caps={"per_company": 1},
        is_smoke=True,
    ),
}


def get_campaign_preset(key: str) -> CampaignPreset:
    """Return a campaign preset, failing closed (KeyError) on an unknown key."""
    return CAMPAIGN_PRESETS[key]


def build_config(campaign_preset: str, session_preset: Optional[str] = None, *,
                 provider_allowlist,
                 output_dir: str = "outputs",
                 approve_live_discovery: bool = False,
                 campaign_name: Optional[str] = None,
                 browser_mode: str = "static",
                 overrides: Optional[Dict] = None) -> DiscoveryCampaignConfig:
    """Map a campaign preset + session preset onto a bounded `DiscoveryCampaignConfig`.

    Session budgets are hard ceilings: `max_qa_analyzed` also caps QA promotion
    (`max_promoted`), and the duration maps to the run time budget. Outreach is never enabled;
    live discovery stays operator-gated via `approve_live_discovery`. `overrides` lets the
    Dashboard form customize any config field (e.g. countries, industries, strategy, ceilings)
    after the preset defaults are applied — the config still validates itself (never unbounded).
    """
    camp = get_campaign_preset(campaign_preset)
    sess = get_session_preset(session_preset or camp.session_preset)
    kwargs = dict(
        campaign_name=campaign_name or camp.label,
        countries=list(camp.countries),
        languages=list(camp.languages),
        industries=list(camp.industries),
        keywords=list(camp.keywords),
        exclude_keywords=list(camp.exclude_keywords),
        site_types=list(camp.site_types),
        provider_allowlist=list(provider_allowlist),
        allow_readonly_profiling_when_no_outreach=True,
        min_commercial_threshold=camp.min_commercial_threshold,
        # Finite session budgets (hard ceilings).
        actionable_target=sess.actionable_target,
        max_candidates=sess.max_discovered,
        max_qa_analyzed=sess.max_qa_analyzed,
        # QA promotion never exceeds the QA-analysis budget.
        max_eligible=max(sess.max_qa_analyzed, 1),
        max_promoted=max(sess.max_qa_analyzed, 1),
        max_pages_per_site=sess.max_pages_per_site,
        time_budget_s=float(sess.max_duration_s),
        session_preset=sess.key,
        strategy=camp.strategy,
        outcome_targets=dict(camp.outcome_targets),
        diversity_caps=dict(camp.diversity_caps),
        output_dir=output_dir,
        approve_live_discovery=approve_live_discovery,
        browser_mode=browser_mode,
    )
    if overrides:
        known = set(DiscoveryCampaignConfig(campaign_name="x", provider_allowlist=["p"]).__dict__)
        kwargs.update({k: v for k, v in overrides.items() if k in known})
    return DiscoveryCampaignConfig(**kwargs)
