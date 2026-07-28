"""A decision already made must not be made again over poorer data.

The canonical split runs once, on complete findings, and hands each survivor a ``kind``. The read
model then PROJECTS those findings for display, and the projection deliberately drops ``signature``
— the one field that tells two same-titled findings apart.

Everything downstream that re-ran the split over that projection therefore asked a different
question of poorer data. Two accessibility findings on one page merged into one, and the surface
listed — and offered to fix — one fewer than the count printed directly above it.

``tests/test_scout_canonical_identity_survives_projection.py`` pins the surfaces that read the
projection as data. This module pins the ones that re-derive from it: the History verdict, the
operator-triggered draft polish, and the fix offer each of those carries. The distinction matters
because the first set was fixed by carrying the label and the second set was not — it kept calling
the splitter, which was still free to re-identify, re-deduplicate and re-classify what it was given.
"""
from __future__ import annotations

import pytest

from core.scout.actionable import KIND_ACTIONABLE, actionable_set

# Same title, same URL, different signatures: one checker firing on two controls of one form. The
# signature is the only thing that says they are two problems, and it is exactly what the read
# model's whitelist drops.
_TWINS = [
    {"title": "Form field has no label", "url": "https://resplit.example/contact",
     "severity": "high", "category": "accessibility", "signature": "a11y-label-name-1",
     "business_impact": "Screen-reader users cannot tell what to type."},
    {"title": "Form field has no label", "url": "https://resplit.example/contact",
     "severity": "high", "category": "accessibility", "signature": "a11y-label-name-2",
     "business_impact": "Screen-reader users cannot tell what to type."},
    {"title": "Slow first paint", "url": "https://resplit.example/", "severity": "medium",
     "category": "performance", "signature": "perf-fcp", "business_impact": "Visitors wait."},
    {"title": "Uses HTTP/2", "url": "https://resplit.example/", "severity": "info",
     "category": "seo", "signature": "info-http2", "business_impact": ""},
]
_ACTIONABLE = 3
_DOMAIN = "resplit.example"


@pytest.fixture
def surfaces(tmp_path):
    """Every surface GPT's blocker names, read from one run through the real read model."""
    from core.scout.campaign_service import CampaignService
    from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
    from core.scout.site_result import site_result
    from core.scout.store import RunStore

    store = RunStore(str(tmp_path), "run-resplit")
    store.write_config({"campaign_name": "adhoc", "run_purpose": "production"})
    store.save_state({"status": "COMPLETED", "prospects": {
        "01": {"status": "DONE", "url": f"https://{_DOMAIN}/",
               "verified_findings": len(_TWINS), "verified_defects": _ACTIONABLE}}})
    store.save_prospect_artifact("01", "findings.json", {"verified": _TWINS})
    AnalyzedSiteRegistry(str(tmp_path)).record_analysis(_DOMAIN, status=ANALYZED,
                                                        campaign_id="run-resplit")

    service = CampaignService(str(tmp_path))
    # Keep the polish path deterministic: this test is about arithmetic, not prose, and a draft
    # polish must never reach a live model from the suite.
    service._router_cached = None

    detail = service.target_detail(_DOMAIN)
    return {"detail": detail, "verdict": site_result(detail),
            "history": service.history_results(), "polished": service.polish_draft(_DOMAIN)}


# --- the splitter itself: a carried decision is not re-decided ------------------------------------

def test_the_splitter_leaves_an_already_decided_collection_alone():
    """The contract every surface below depends on. Labelled findings arrive decided; the splitter
    counts them, and does not get to merge two of them because a projection made them look alike."""
    decided = [{k: v for k, v in f.items() if k != "signature"}
               for f in actionable_set(_TWINS).labelled()]

    assert actionable_set(decided).confirmed_issue_count == _ACTIONABLE
    assert actionable_set(decided).suppressed == []


def test_an_undecided_collection_is_still_deduplicated():
    """The guard against fixing this by simply never deduplicating: findings that carry no decision
    have not been through the split, and two indistinguishable ones are still one problem."""
    raw = [{k: v for k, v in f.items() if k != "signature"} for f in _TWINS]

    assert actionable_set(raw).confirmed_issue_count == _ACTIONABLE - 1


# --- the surfaces ---------------------------------------------------------------------------------

def test_target_detail_counts_three(surfaces):
    detail = surfaces["detail"]

    assert detail["actionable_summary"]["confirmed_issues"] == _ACTIONABLE
    assert sum(1 for f in detail["findings"] if f.get("kind") == KIND_ACTIONABLE) == _ACTIONABLE


def test_the_site_verdict_counts_three(surfaces):
    """site_result() re-split the projected list, so History disagreed with the card it links to."""
    assert surfaces["verdict"].actionable == _ACTIONABLE


def test_the_history_row_counts_three(surfaces):
    rows = [r for r in surfaces["history"] if r.get("domain") == _DOMAIN]

    assert len(rows) == 1
    assert rows[0]["result"]["actionable"] == _ACTIONABLE


def test_the_initial_draft_counts_three(surfaces):
    draft = surfaces["detail"]["draft"]

    assert draft["confirmed_issue_count"] == _ACTIONABLE
    assert len(draft["problem_bullets"]) == _ACTIONABLE
    assert f"{_ACTIONABLE} confirmed issues" in draft["subject"]


def test_the_polished_draft_counts_three(surfaces):
    """The polish re-enters the builder with the PROJECTED findings — where the count fell to two
    while the initial draft, built from the complete ones, still said three."""
    polished = surfaces["polished"]

    assert polished["confirmed_issue_count"] == _ACTIONABLE
    assert len(polished["problem_bullets"]) == _ACTIONABLE
    assert f"{_ACTIONABLE} confirmed issues" in polished["subject"]


def test_the_fix_offer_scopes_to_three(surfaces):
    """An offer to fix is the surface where an undercount is a promise, so it gets its own check."""
    for name, fixability in (("detail", surfaces["detail"]["fixability"]),
                             ("polished draft", surfaces["polished"]["fixability"])):
        assert sum(fixability["counts"].values()) == _ACTIONABLE, name


def test_every_surface_answers_with_the_same_number(surfaces):
    """The shape of the defect in one assertion: each number is defensible, the page is not."""
    detail, polished = surfaces["detail"], surfaces["polished"]
    totals = {
        "summary count": detail["actionable_summary"]["confirmed_issues"],
        "detail list": sum(1 for f in detail["findings"] if f.get("kind") == KIND_ACTIONABLE),
        "site verdict": surfaces["verdict"].actionable,
        "history row": next(r["result"]["actionable"] for r in surfaces["history"]
                            if r.get("domain") == _DOMAIN),
        "initial draft": detail["draft"]["confirmed_issue_count"],
        "initial bullets": len(detail["draft"]["problem_bullets"]),
        "polished draft": polished["confirmed_issue_count"],
        "polished bullets": len(polished["problem_bullets"]),
        "detail fix offer": sum(detail["fixability"]["counts"].values()),
        "polished fix offer": sum(polished["fixability"]["counts"].values()),
    }

    assert set(totals.values()) == {_ACTIONABLE}, f"surfaces disagree: {totals}"
