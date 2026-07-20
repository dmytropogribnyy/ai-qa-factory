"""v3.3 operator workflow — A/B/C prioritization + QA-value score + country confidence.

Deterministic. Priority combines commercial fit with evidence-backed QA findings (not commercial
score alone); the QA-value score is tracked separately from the commercial-opportunity score;
country confidence is an honest Verified/Probable/Unverified label backed by bounded evidence and
never a hard reject.
"""
from __future__ import annotations

from core.scout.country_confidence import (
    PROBABLE,
    UNVERIFIED,
    VERIFIED,
    assess_country,
)
from core.scout.priority import classify, qa_value_score


def _finding(severity, *, evidence=True, category="functional"):
    return {"severity": severity, "category": category,
            "evidence_refs": ["ev-1"] if evidence else []}


# --- A/B/C prioritization ----------------------------------------------------------------------
def test_priority_a_requires_strong_commercial_and_evidence_backed_finding():
    p = classify(commercial_score=82, findings=[_finding("high", evidence=True)])
    assert p.priority == "A"
    assert p.strong_finding is True


def test_strong_commercial_without_evidence_backed_finding_is_not_a():
    # High commercial fit but only a low-severity gap => not actionable (B at best).
    p = classify(commercial_score=82, findings=[_finding("low", evidence=True)])
    assert p.priority == "B"


def test_evidence_backed_finding_without_commercial_fit_is_not_a():
    p = classify(commercial_score=40, findings=[_finding("high", evidence=True)])
    assert p.priority != "A"


def test_priority_b_reasonable_commercial_with_useful_gap():
    p = classify(commercial_score=65, findings=[_finding("medium", evidence=False)])
    assert p.priority == "B"


def test_priority_c_weak_or_clean_is_retained_not_discarded():
    clean = classify(commercial_score=65, findings=[])
    weak = classify(commercial_score=45, findings=[_finding("low")])
    assert clean.priority == "C"
    assert weak.priority == "C"


def test_medium_high_needs_evidence_to_be_strong():
    # A medium/high with NO evidence ref is a useful gap (B) but not an A-grade strong finding.
    p = classify(commercial_score=90, findings=[_finding("high", evidence=False)])
    assert p.strong_finding is False
    assert p.priority == "B"


# --- QA-value score (separate from commercial score) -------------------------------------------
def test_qa_value_scales_with_severity_and_evidence_and_caps_at_100():
    assert qa_value_score([]) == 0
    low = qa_value_score([_finding("low", evidence=False)])
    high = qa_value_score([_finding("high", evidence=True)])
    assert 0 < low < high <= 100
    huge = qa_value_score([_finding("high", evidence=True)] * 20)
    assert huge == 100


def test_prioritization_keeps_commercial_and_qa_scores_distinct():
    p = classify(commercial_score=82, findings=[_finding("high", evidence=True)])
    d = p.to_dict()
    assert d["commercial_score"] == 82
    assert d["qa_value"] > 0
    assert d["commercial_score"] != d["qa_value"]


# --- country confidence ------------------------------------------------------------------------
def test_country_verified_from_structured_metadata():
    a = assess_country("de", structured_country="de")
    assert a.status == VERIFIED
    assert any("structured" in e for e in a.evidence)


def test_country_verified_from_imprint():
    a = assess_country("de", imprint_country="de")
    assert a.status == VERIFIED


def test_country_probable_from_cctld_or_language():
    assert assess_country("de", cctld="de").status == PROBABLE
    assert assess_country("de", language_hint="de").status == PROBABLE


def test_country_unverified_when_no_corroborating_evidence():
    a = assess_country("us")
    assert a.status == UNVERIFIED
    # Unverified is a label, never a rejection: the country is still reported.
    assert a.country == "us"


def test_conflicting_structured_country_is_not_verified():
    # declared US but structured metadata says DE => not verified as US.
    a = assess_country("us", structured_country="de")
    assert a.status != VERIFIED
