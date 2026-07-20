"""v3.3 Scout Brain — target understanding + adaptive replanning + combined/confidence scoring.

Deterministic. These tests map to the Scout Brain concept acceptance criteria
(docs/architecture/SCOUT_BRAIN_CONCEPT.md §15): different plans per archetype, plan changes on new
evidence, stop on weak / deepen on strong-safe, value over count, honest confidence + safety cap.
"""
from __future__ import annotations

from core.scout.scout_brain import (
    ACTION_BLOCK,
    ACTION_DEEPEN,
    ACTION_ESCALATE,
    ACTION_STOP,
    ARCH_BOOKING,
    ARCH_ECOMMERCE,
    ARCH_SAAS,
    ARCH_UNKNOWN,
    SRC_DETERMINISTIC,
    combined_opportunity_score,
    evidence_confidence,
    replan_on_evidence,
    safety_confidence,
    understand_target,
)


# --- Phase A: understand the target (criterion 1: different archetypes) -------------------------
def test_understands_distinct_archetypes():
    ecom = understand_target(signals={"title": "Shop", "markers": ["Add to cart", "Checkout"]})
    booking = understand_target(signals={"headings": ["Check availability"], "markers": ["Book now"]})
    saas = understand_target(signals={"markers": ["Pricing plans", "Free trial", "Sign up", "API"]})
    assert ecom.archetype == ARCH_ECOMMERCE
    assert booking.archetype == ARCH_BOOKING
    assert saas.archetype == ARCH_SAAS
    # Different archetypes yield different primary journeys (=> different plans downstream).
    assert ecom.primary_journeys != booking.primary_journeys != saas.primary_journeys


def test_ambiguous_page_is_honest_low_confidence_unknown():
    u = understand_target(signals={"title": "Welcome", "markers": []})
    assert u.archetype == ARCH_UNKNOWN
    assert u.confidence <= 20
    assert u.reasoning_source == SRC_DETERMINISTIC   # never pretends model reasoning happened


def test_confidence_rises_with_corroborating_evidence():
    weak = understand_target(signals={"markers": ["Add to cart"]})
    strong = understand_target(signals={"markers": ["Add to cart", "Checkout"], "forms": True,
                                        "structured_data": True})
    assert strong.confidence > weak.confidence
    assert "form(s) present" in strong.evidence


# --- Phase E/F: adapt on evidence (criterion 3) ------------------------------------------------
def test_plan_changes_after_new_evidence():
    deepen = replan_on_evidence(archetype=ARCH_ECOMMERCE, event="price_inconsistency",
                                remaining_budget_s=60)
    assert deepen.action == ACTION_DEEPEN
    assert deepen.focus_flow == "cart"


def test_weak_target_stops_and_strong_defect_escalates():
    stop = replan_on_evidence(archetype=ARCH_ECOMMERCE, event="minor_only_weak_target")
    escalate = replan_on_evidence(archetype=ARCH_ECOMMERCE, event="probable_high_severity",
                                  remaining_budget_s=60)
    assert stop.action == ACTION_STOP
    assert escalate.action == ACTION_ESCALATE


def test_captcha_and_cleanup_failure_block_or_stop_over_deepening():
    assert replan_on_evidence(archetype=ARCH_SAAS, event="captcha").action == ACTION_BLOCK
    assert replan_on_evidence(archetype=ARCH_SAAS, event="auth_ambiguity").action == ACTION_BLOCK
    assert replan_on_evidence(archetype=ARCH_ECOMMERCE,
                              event="cleanup_failure").action == ACTION_STOP


def test_exhausted_budget_forces_stop_even_on_deepen_event():
    d = replan_on_evidence(archetype=ARCH_ECOMMERCE, event="price_inconsistency",
                           remaining_budget_s=0)
    assert d.action == ACTION_STOP


def test_booking_deepen_keeps_reservation_stop_boundary():
    d = replan_on_evidence(archetype=ARCH_BOOKING, event="calendar_inconsistency",
                           remaining_budget_s=60)
    assert d.action == ACTION_DEEPEN
    assert "reserve" in d.stop_before.lower()


# --- separate + combined scoring (criterion 15: value over count, safety cap) -------------------
def test_evidence_and_safety_confidence():
    assert evidence_confidence([]) == 0
    strong = evidence_confidence([{"evidence_refs": ["e1"], "signature": "sig"}])
    assert strong > 0
    assert safety_confidence(cleanup_verified=True, crossed_boundary=False,
                             client_safe_capable=True) == 100
    # a crossed boundary is always zero safety confidence
    assert safety_confidence(cleanup_verified=True, crossed_boundary=True,
                             client_safe_capable=True) == 0


def test_combined_score_is_capped_by_safety():
    safe = combined_opportunity_score(commercial=90, qa_value=80, evidence_conf=80, safety_conf=100)
    unsafe = combined_opportunity_score(commercial=90, qa_value=80, evidence_conf=80, safety_conf=0)
    assert safe > unsafe
    assert unsafe == 0                          # unsafe target is never top-ranked


def test_value_over_count_one_high_beats_many_low():
    from core.scout.priority import qa_value_score
    one_high = qa_value_score([{"severity": "high", "evidence_refs": ["e"]}])
    many_low = qa_value_score([{"severity": "low"}] * 4)
    assert one_high > many_low
