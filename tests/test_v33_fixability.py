"""v3.3 - conservative fixability classification for the stage-3 paid fix offer."""
from __future__ import annotations

from core.scout.outreach.fixability import (
    FIX_AFTER_ACCESS,
    FIX_READY,
    OUT_OF_SCOPE,
    classify_finding_fixability,
    classify_fixability,
)


def test_fixable_category_needs_access_to_be_ready():
    f = {"category": "accessibility", "title": "low contrast"}
    assert classify_finding_fixability(f, access_available=False)["fix_tier"] == FIX_AFTER_ACCESS
    assert classify_finding_fixability(f, access_available=True)["fix_tier"] == FIX_READY


def test_meta_and_unknown_categories_are_out_of_scope():
    assert classify_finding_fixability({"category": "coverage"},
                                       access_available=True)["fix_tier"] == OUT_OF_SCOPE
    assert classify_finding_fixability({"category": "backend-crypto"},
                                       access_available=True)["fix_tier"] == OUT_OF_SCOPE


def test_classify_is_conservative_without_access():
    findings = [{"category": "functional", "severity": "high", "title": "a"},
                {"category": "seo", "severity": "low", "title": "b"},
                {"category": "coverage", "title": "c"}]
    out = classify_fixability(findings, access_available=False)
    assert out["counts"][FIX_READY] == 0                 # never 'ready' without access
    assert out["counts"][FIX_AFTER_ACCESS] == 2
    assert out["counts"][OUT_OF_SCOPE] == 1
    assert out["offerable"] == 2
    assert "after you grant" in out["summary"]


def test_classify_ready_with_access():
    out = classify_fixability([{"category": "functional", "title": "x"}], access_available=True)
    assert out["counts"][FIX_READY] == 1 and out["offerable"] == 1
