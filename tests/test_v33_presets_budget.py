"""v3.3 operator workflow — session/campaign presets + budget mapping + actionable-target stop.

Deterministic unit tests (no network, no browser). They pin the finite-run contract:
every session preset carries hard budgets, both named campaign presets exist with the
required safety properties, build_config maps a preset+session into a bounded
DiscoveryCampaignConfig, and the discovery engine stops at the actionable target and never
QA-analyzes more than the preset allows.
"""
from __future__ import annotations

import pytest

from core.scout.presets import (
    CAMPAIGN_PRESETS,
    DEFAULT_CAMPAIGN_PRESET,
    SESSION_PRESETS,
    build_config,
    get_campaign_preset,
    get_session_preset,
)


# --- session presets ---------------------------------------------------------------------------
def test_session_presets_have_exact_spec_budgets():
    quick = SESSION_PRESETS["quick"]
    assert (quick.actionable_target, quick.max_discovered, quick.max_qa_analyzed,
            quick.max_pages_per_site, quick.max_duration_s) == (2, 15, 5, 3, 20 * 60)
    standard = SESSION_PRESETS["standard"]
    assert (standard.actionable_target, standard.max_discovered, standard.max_qa_analyzed,
            standard.max_pages_per_site, standard.max_duration_s) == (5, 40, 12, 5, 45 * 60)
    extended = SESSION_PRESETS["extended"]
    assert (extended.actionable_target, extended.max_discovered, extended.max_qa_analyzed,
            extended.max_pages_per_site, extended.max_duration_s) == (10, 80, 25, 5, 90 * 60)


def test_get_session_preset_fails_closed_on_unknown():
    assert get_session_preset("quick").key == "quick"
    with pytest.raises(KeyError):
        get_session_preset("infinite")


def test_every_session_preset_is_finite():
    for p in SESSION_PRESETS.values():
        assert p.actionable_target >= 1
        assert p.max_discovered >= p.max_qa_analyzed >= 1
        assert p.max_pages_per_site >= 1
        assert p.max_duration_s > 0


# --- named campaign presets --------------------------------------------------------------------
def test_both_named_presets_exist():
    assert "us-de-commercial" in CAMPAIGN_PRESETS
    assert "safe-live-acceptance" in CAMPAIGN_PRESETS


def test_safe_live_acceptance_preset_is_bounded_and_us_de_only():
    p = get_campaign_preset("safe-live-acceptance")
    assert p.label == "Safe Live Acceptance — US/DE"
    assert set(c.lower() for c in p.countries) == {"us", "de"}
    assert p.session_preset == "quick"          # low budget by default
    assert p.schedule_enabled is False          # never auto-runs
    # representative but limited vertical coverage
    assert 1 <= len(p.site_types) <= 4


def test_us_de_commercial_preset_matches_spec():
    p = get_campaign_preset("us-de-commercial")
    assert set(c.lower() for c in p.countries) == {"us", "de"}
    assert set(lang.lower() for lang in p.languages) == {"en", "de"}
    assert p.min_commercial_threshold == 70
    assert p.rescan_interval_days == 30
    assert p.schedule_mode == "weekdays"
    assert p.schedule_time == "09:00"
    assert p.schedule_timezone == "Europe/Bratislava"
    assert p.schedule_enabled is False
    for signal in ("pricing", "free trial", "book demo", "sign up", "shop", "cart",
                   "availability", "booking"):
        assert signal in p.keywords


def test_default_is_a_real_production_preset_not_quick():
    assert DEFAULT_CAMPAIGN_PRESET == "balanced-production"
    p = get_campaign_preset(DEFAULT_CAMPAIGN_PRESET)
    assert p.session_preset != "quick"       # production default is not a 20-minute smoke scan
    assert p.is_smoke is False
    assert p.strategy == "balanced"


def test_production_presets_exist_with_strategies():
    for key, strat in (("balanced-production", "balanced"),
                       ("conservative-production", "conservative"),
                       ("opportunity-production", "opportunity"),
                       ("scheduled-daily", "balanced")):
        assert CAMPAIGN_PRESETS[key].strategy == strat


def test_build_config_carries_strategy_and_overrides():
    cfg = build_config("balanced-production", provider_allowlist=["tavily"],
                       overrides={"countries": ["us"], "strategy": "opportunity"})
    assert cfg.strategy == "opportunity"     # override wins
    assert cfg.countries == ["us"]
    assert cfg.outcome_targets == {"actionable": 5}


# --- build_config: preset + session -> bounded DiscoveryCampaignConfig --------------------------
def test_build_config_maps_session_budgets_onto_campaign_config():
    cfg = build_config("safe-live-acceptance", "quick", provider_allowlist=["tavily"],
                       output_dir="outputs", approve_live_discovery=False)
    assert cfg.actionable_target == 2
    assert cfg.max_candidates == 15          # max_discovered
    assert cfg.max_qa_analyzed == 5
    assert cfg.max_promoted <= 5             # QA promotion never exceeds qa-analyzed budget
    assert cfg.max_pages_per_site == 3
    assert cfg.time_budget_s == 20 * 60
    assert cfg.session_preset == "quick"
    # never outreach; live discovery stays operator-gated
    assert cfg.approve_live_discovery is False
    assert "us" in [c.lower() for c in cfg.countries]


def test_build_config_session_override_changes_budgets():
    cfg = build_config("us-de-commercial", "extended", provider_allowlist=["tavily"])
    assert cfg.actionable_target == 10
    assert cfg.max_candidates == 80
    assert cfg.max_qa_analyzed == 25
    assert cfg.time_budget_s == 90 * 60


def test_build_config_rejects_unknown_provider_empty():
    with pytest.raises(Exception):
        build_config("safe-live-acceptance", "quick", provider_allowlist=[])
