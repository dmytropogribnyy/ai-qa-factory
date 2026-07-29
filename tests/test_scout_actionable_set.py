"""Every number about a target's findings, counted from the same findings.

The failure this prevents was quiet and completely reasonable-looking: a page saying "1 confirmed
issue" above an offer to fix two. Nothing was invented. The verdict excluded informational findings,
the fix offer did not, and the draft letter applied a third rule. Each surface was defensible alone;
the page was not true.

The table below is the contract: for a given set of findings, the confirmed-issue count, the fix
offer, the talking points and the draft subject must all describe the same collection.
"""
from __future__ import annotations

import pytest

from core.scout.actionable import ActionableSet, actionable_set, is_actionable
from core.scout.outreach.qa_draft import build_review_draft, problem_bullets
from core.scout.site_result import site_result


def _finding(title, severity="high", category="functional", signature="", url="https://x.example/"):
    return {"title": title, "severity": severity, "category": category, "url": url,
            "signature": signature or title.lower().replace(" ", "-"),
            "business_impact": "some impact"}


# --- the one rule ---------------------------------------------------------------------------------

@pytest.mark.parametrize("severity,expected", [
    ("high", True), ("medium", True), ("low", True),
    ("info", False), ("informational", False), ("", False), (None, False), ("none", False),
])
def test_actionability_is_decided_by_severity_alone(severity, expected):
    assert is_actionable({"severity": severity}) is expected


# --- the table --------------------------------------------------------------------------------

_CASES = {
    "one actionable and one info": (
        [_finding("Broken checkout"), _finding("Uses HTTP/2", severity="info")], 1, 1, 0),
    "only info": (
        [_finding("Uses HTTP/2", severity="info"), _finding("No sitemap", severity="info")],
        0, 2, 0),
    "two actionable of different kinds": (
        [_finding("Broken checkout"), _finding("Missing alt text", category="accessibility",
                                               severity="medium")], 2, 0, 0),
    "the same problem reported twice": (
        [_finding("Broken checkout"), _finding("Broken checkout")], 1, 0, 1),
    "an interaction trace beside a real defect": (
        [_finding("Broken checkout"),
         _finding("Filter interaction recorded", severity="info", category="coverage")], 1, 1, 0),
    "nothing at all": ([], 0, 0, 0),
}


@pytest.mark.parametrize("case", sorted(_CASES), ids=sorted(_CASES))
def test_the_split_is_the_same_whoever_asks(case):
    findings, actionable, informational, suppressed = _CASES[case]

    result = actionable_set(findings)

    assert result.confirmed_issue_count == actionable
    assert len(result.informational) == informational
    assert len(result.suppressed) == suppressed
    assert result.total == actionable + informational


@pytest.mark.parametrize("case", sorted(_CASES), ids=sorted(_CASES))
def test_the_verdict_the_offer_and_the_draft_never_disagree(case):
    """The heart of it: one collection explains all four numbers."""
    findings, expected_actionable, _informational, _suppressed = _CASES[case]
    detail = {"domain": "x.example", "findings": findings, "analysis_complete": True,
              "prospect_status": "DONE", "entry": {"analysis_status": "analyzed"},
              "media": [], "contact_records": []}

    verdict = site_result(detail)
    bullets = problem_bullets(findings)
    draft = build_review_draft(domain="x.example", findings=findings)
    offerable = draft["fixability"]["offerable"]

    assert verdict.actionable == expected_actionable
    assert len(bullets) == expected_actionable
    assert offerable <= expected_actionable
    if expected_actionable:
        assert f"{expected_actionable} confirmed" in draft["subject"]
    else:
        assert draft["available"] is False
        assert offerable == 0


def test_an_informational_finding_is_never_offered_as_a_repair():
    """The exact "1 confirmed issue / we can fix 2" shape."""
    findings = [_finding("Broken checkout"), _finding("Uses HTTP/2", severity="info")]

    verdict = site_result({"domain": "x.example", "findings": findings, "analysis_complete": True,
                           "prospect_status": "DONE", "entry": {"analysis_status": "analyzed"}})
    draft = build_review_draft(domain="x.example", findings=findings)

    assert verdict.actionable == 1
    assert draft["fixability"]["offerable"] == 1
    assert draft["fixability"]["counts"]["out_of_scope"] == 0


def test_a_video_fixture_interaction_never_becomes_something_to_sell():
    """A recording that proved the pipeline works is not a defect a client should hear about."""
    from core.scout.interaction_scenario import (OUTCOME_TRACE, SCENARIO_ADD_REMOVE, ScenarioResult,
                                                 finding_from)

    trace = ScenarioResult(scenario=SCENARIO_ADD_REMOVE, outcome=OUTCOME_TRACE,
                           action_performed=True, cleanup_ok=True)
    assert finding_from(trace, run_id="r", prospect_ref="01") is None

    draft = build_review_draft(domain="the-internet.herokuapp.com", findings=[])
    assert draft["available"] is False
    assert draft["fixability"]["offerable"] == 0


def test_a_suppressed_duplicate_is_explained_rather_than_silently_dropped():
    result = actionable_set([_finding("Broken checkout"), _finding("Broken checkout")])

    assert result.suppressed[0]["suppressed_reason"] == "duplicate of Broken checkout"
    assert result.to_dict()["suppressed"] == 1


def test_findings_without_a_signature_dedupe_on_what_a_reader_would_compare():
    same = [{"title": "Broken checkout", "severity": "high", "url": "https://x.example/cart"},
            {"title": "Broken checkout", "severity": "high", "url": "https://x.example/cart"}]
    different = [{"title": "Broken checkout", "severity": "high", "url": "https://x.example/cart"},
                 {"title": "Broken checkout", "severity": "high", "url": "https://x.example/pay"}]

    assert actionable_set(same).confirmed_issue_count == 1
    assert actionable_set(different).confirmed_issue_count == 2


def test_the_severity_breakdown_adds_up_to_the_confirmed_count():
    result = actionable_set([_finding("A"), _finding("B", severity="medium"),
                             _finding("C", severity="medium"), _finding("D", severity="info")])

    breakdown = result.severity_breakdown()

    assert sum(breakdown.values()) == result.confirmed_issue_count == 3
    assert breakdown == {"high": 1, "medium": 2}


def test_the_read_model_carries_the_counts_with_the_findings(tmp_path):
    """So a surface never has to recompute the split and never gets a different answer."""
    from core.scout.campaign_service import CampaignService
    from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
    from core.scout.store import RunStore

    store = RunStore(str(tmp_path), "run-1")
    store.write_config({"campaign_name": "adhoc", "run_purpose": "production"})
    store.save_state({"status": "COMPLETED", "prospects": {
        "01": {"status": "DONE", "url": "https://x.example/", "verified_findings": 2}}})
    store.save_prospect_artifact("01", "findings.json", {"verified": [
        _finding("Broken checkout"), _finding("Uses HTTP/2", severity="info")]})
    AnalyzedSiteRegistry(str(tmp_path)).record_analysis("x.example", status=ANALYZED,
                                                        campaign_id="run-1")

    detail = CampaignService(str(tmp_path)).target_detail("x.example", run="run-1")

    assert detail["actionable_summary"]["confirmed_issues"] == 1
    assert detail["actionable_summary"]["informational"] == 1
    assert detail["fixability"]["offerable"] == 1


def test_an_empty_set_reports_zero_rather_than_unknown():
    empty = ActionableSet()

    assert empty.confirmed_issue_count == 0
    assert empty.total == 0
    assert empty.severity_breakdown() == {}
