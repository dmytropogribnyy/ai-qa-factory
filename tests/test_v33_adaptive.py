"""v3.3 operator workflow — adaptive allocation + per-target test planner.

Deterministic. Depth is opportunity-driven (not a fixed ratio); hard ceilings are caps not quotas;
outcome targets can stop a run early; diversity caps stop one dimension dominating; the planner
emits a bounded, explainable Target Test Plan that respects safety boundaries.
"""
from __future__ import annotations

from core.scout.adaptive import (
    DEPTH_BASELINE,
    DEPTH_DEEP,
    DEPTH_SELECTIVE,
    DEPTH_SKIP,
    STRATEGY_BALANCED,
    STRATEGY_CONSERVATIVE,
    STRATEGY_OPPORTUNITY,
    AdaptiveAllocator,
    DiversityCaps,
    HardCeilings,
    OutcomeTargets,
)
from core.scout.presets import SITE_TYPE_BOOKING, SITE_TYPE_ECOMMERCE, SITE_TYPE_PERSONAL
from core.scout.target_planner import plan_target
from core.scout.verticals import select_profile


# --- adaptive depth is opportunity-driven, not a fixed ratio -----------------------------------
def test_depth_varies_with_opportunity_same_strategy():
    a = AdaptiveAllocator(strategy=STRATEGY_BALANCED)
    hi = a.decide(domain="hi.com", commercial_score=85, qa_risk=60, safety_ok=True)
    mid = a.decide(domain="mid.com", commercial_score=62, qa_risk=30, safety_ok=True)
    lo = a.decide(domain="lo.com", commercial_score=48, qa_risk=5, safety_ok=True)
    none = a.decide(domain="no.com", commercial_score=20, qa_risk=0, safety_ok=True)
    assert hi.depth == DEPTH_DEEP
    assert mid.depth == DEPTH_SELECTIVE
    assert lo.depth == DEPTH_BASELINE
    assert none.depth == DEPTH_SKIP


def test_strategy_changes_generosity():
    strong = dict(commercial_score=62, qa_risk=35, safety_ok=True, domain="x.com")
    assert AdaptiveAllocator(strategy=STRATEGY_CONSERVATIVE).decide(**strong).depth != DEPTH_DEEP
    assert AdaptiveAllocator(strategy=STRATEGY_OPPORTUNITY).decide(**strong).depth == DEPTH_DEEP


def test_unsafe_target_is_never_browser_tested():
    a = AdaptiveAllocator(strategy=STRATEGY_OPPORTUNITY)
    d = a.decide(domain="x.com", commercial_score=99, qa_risk=99, safety_ok=False)
    assert d.depth == DEPTH_SKIP
    assert "unsafe_or_ambiguous_target" in d.reasons


# --- hard ceilings are caps, not quotas --------------------------------------------------------
def test_browser_ceiling_caps_further_testing():
    a = AdaptiveAllocator(strategy=STRATEGY_BALANCED,
                          ceilings=HardCeilings(max_browser_tested=1))
    d1 = a.decide(domain="a.com", commercial_score=85, qa_risk=60, safety_ok=True)
    a.record(d1)
    d2 = a.decide(domain="b.com", commercial_score=85, qa_risk=60, safety_ok=True)
    assert d1.depth == DEPTH_DEEP
    assert d2.depth == DEPTH_SKIP
    assert "max_browser_tested_reached" in d2.reasons


def test_deep_ceiling_downgrades_to_selective():
    a = AdaptiveAllocator(strategy=STRATEGY_BALANCED,
                          ceilings=HardCeilings(max_deep_tested=1))
    a.record(a.decide(domain="a.com", commercial_score=90, qa_risk=70, safety_ok=True))
    d2 = a.decide(domain="b.com", commercial_score=90, qa_risk=70, safety_ok=True)
    assert d2.depth == DEPTH_SELECTIVE
    assert any("deep_ceiling" in r for r in d2.reasons)


# --- diversity caps ----------------------------------------------------------------------------
def test_industry_diversity_cap_blocks_domination():
    a = AdaptiveAllocator(strategy=STRATEGY_OPPORTUNITY,
                          diversity=DiversityCaps(per_industry=1))
    d1 = a.decide(domain="a.com", commercial_score=80, qa_risk=50, safety_ok=True, industry="saas")
    a.record(d1, industry="saas")
    d2 = a.decide(domain="b.com", commercial_score=80, qa_risk=50, safety_ok=True, industry="saas")
    assert d2.depth == DEPTH_SKIP
    assert any("diversity_cap_industry" in r for r in d2.reasons)


# --- outcome targets stop early ----------------------------------------------------------------
def test_outcome_target_reached_allows_early_stop():
    a = AdaptiveAllocator(strategy=STRATEGY_BALANCED, outcomes=OutcomeTargets(actionable=2))
    assert a.outcome_reached() == (False, "")
    a.record(a.decide(domain="a.com", commercial_score=85, qa_risk=60, safety_ok=True),
             actionable=True)
    assert a.outcome_reached()[0] is False
    a.record(a.decide(domain="b.com", commercial_score=85, qa_risk=60, safety_ok=True),
             actionable=True)
    ok, why = a.outcome_reached()
    assert ok is True and "outcome" in why


def test_no_outcome_targets_never_forces_early_stop():
    a = AdaptiveAllocator(strategy=STRATEGY_BALANCED)
    assert a.outcome_reached() == (False, "")


# --- per-target planner ------------------------------------------------------------------------
def test_plan_baseline_is_passive_only():
    plan = plan_target(domain="a.com", profile=select_profile(SITE_TYPE_ECOMMERCE),
                       depth=DEPTH_BASELINE)
    assert plan.flow == "passive"
    assert "browser_flow" in plan.checks_skipped
    assert plan.max_duration_s > 0
    assert "reachability" in plan.checks_selected


def test_plan_selective_adds_the_vertical_flow_with_stop_boundaries():
    plan = plan_target(domain="b.com", profile=select_profile(SITE_TYPE_BOOKING),
                       depth=DEPTH_SELECTIVE)
    assert plan.flow == "booking_inspect"
    assert plan.stop_boundaries              # e.g. reserve/book/confirm/pay
    assert any("stage3_selective" in d for d in plan.decisions)


def test_plan_deep_requires_trace_evidence():
    plan = plan_target(domain="c.com", profile=select_profile(SITE_TYPE_ECOMMERCE),
                       depth=DEPTH_DEEP)
    assert "playwright_trace" in plan.evidence_requirements
    assert plan.cleanup_required is True     # cart flow changes reversible state


def test_plan_skip_tests_nothing():
    plan = plan_target(domain="d.com", profile=select_profile(SITE_TYPE_PERSONAL),
                       depth=DEPTH_SKIP)
    assert plan.max_duration_s == 0
    assert plan.checks_selected == []


def test_plan_time_cap_respects_remaining_budget():
    plan = plan_target(domain="e.com", profile=select_profile(SITE_TYPE_ECOMMERCE),
                       depth=DEPTH_BASELINE, max_target_duration_s=180, remaining_budget_s=30)
    assert plan.max_duration_s == 30
