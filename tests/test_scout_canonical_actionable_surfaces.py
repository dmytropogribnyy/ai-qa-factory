"""Eleven problems, and every surface that counts them says eleven.

The previous NO-GO was not a miscount. `problem_bullets(limit=8)` is a DISPLAY cap, and the draft
subject was built from `len(bullets)` — so a target with eleven confirmed problems announced eight
in the subject line and offered to fix eleven three centimetres below. Both numbers were computed
correctly from the same findings; one of them was answering a different question.

A display cap is not a total. This module fixes the shape of that error in place: one fixture with
more than eight actionable findings, carried through every surface a client or an operator can
read — target detail, draft subject, draft body, fix offer, the HTML report, the CSV, the
structured JSON and the ZIP manifest — asserting the same number in all of them, and asserting that
where the list IS capped the page says what it is a subset of.

It also pins the second half of the same blocker: actionable and informational findings are counted
separately everywhere. "13 confirmed findings" over a list of eleven defects and two observations
is the same class of untruth as the subject line.
"""
from __future__ import annotations

import csv
import io
import json
import zipfile

import pytest

from core.scout.actionable import actionable_set
from core.scout.outreach.qa_draft import build_review_draft, problem_bullets

# More than the display cap of eight, so a capped list and a total can never be the same number.
_ACTIONABLE = 11
_INFORMATIONAL = 2


def _finding(title, severity="high", url="https://many.example/"):
    return {"title": title, "severity": severity, "category": "functional", "url": url,
            "signature": title.lower().replace(" ", "-"),
            "business_impact": f"impact of {title}",
            "reproduction_steps": [f"Open {url}", f"Observe {title}"]}


@pytest.fixture
def findings():
    """Eleven actionable, two informational, one exact duplicate that must be suppressed."""
    items = [_finding(f"Confirmed defect {n:02d}",
                      severity=("high" if n % 3 == 0 else "medium" if n % 3 == 1 else "low"))
             for n in range(1, _ACTIONABLE + 1)]
    items += [_finding(f"Observation {n:02d}", severity="info") for n in range(1, _INFORMATIONAL + 1)]
    items.append(_finding("Confirmed defect 01", severity="medium"))      # duplicate signature
    return items


@pytest.fixture
def packaged(tmp_path, findings):
    """One real client ZIP built from the fixture, plus the read model it was built from."""
    from core.scout.campaign_service import CampaignService
    from core.scout.client_evidence import build_client_evidence_bundle
    from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
    from core.scout.store import RunStore

    store = RunStore(str(tmp_path), "run-many")
    store.write_config({"campaign_name": "adhoc", "run_purpose": "production"})
    store.save_state({"status": "COMPLETED", "prospects": {
        "01": {"status": "DONE", "url": "https://many.example/",
               "verified_findings": _ACTIONABLE + _INFORMATIONAL}}})
    store.save_prospect_artifact("01", "findings.json", {"verified": findings})
    AnalyzedSiteRegistry(str(tmp_path)).record_analysis("many.example", status=ANALYZED,
                                                        campaign_id="run-many")

    detail = CampaignService(str(tmp_path)).target_detail("many.example", run="run-many")
    bundle = build_client_evidence_bundle(str(tmp_path), run_id="run-many", prospect_id="01",
                                          domain="many.example", detail=detail)
    with zipfile.ZipFile(bundle.path) as archive:
        blobs = {name.split("/", 1)[1]: archive.read(name)
                 for name in archive.namelist() if "/" in name}
    return {"detail": detail, "blobs": blobs}


def _text(packaged, name):
    return packaged["blobs"][name].decode("utf-8")


# --- the canonical set itself ---------------------------------------------------------------------

def test_the_fixture_is_bigger_than_the_display_cap(findings):
    """If this ever stops being true the whole module stops testing anything."""
    canonical = actionable_set(findings)

    assert canonical.confirmed_issue_count == _ACTIONABLE > len(problem_bullets(findings))
    assert len(canonical.informational) == _INFORMATIONAL
    assert len(canonical.suppressed) == 1


# --- operator surfaces ----------------------------------------------------------------------------

def test_target_detail_reports_the_total_not_the_cap(packaged):
    summary = packaged["detail"]["actionable_summary"]

    assert summary["confirmed_issues"] == _ACTIONABLE
    assert summary["informational"] == _INFORMATIONAL
    assert sum(summary["severity_breakdown"].values()) == _ACTIONABLE


def test_the_draft_subject_states_the_total(findings):
    """The exact defect: the subject line reported the display cap as the finding count."""
    draft = build_review_draft(domain="many.example", findings=findings)

    assert f"{_ACTIONABLE} confirmed issues" in draft["subject"]
    assert f"{len(problem_bullets(findings))} confirmed" not in draft["subject"]


def test_the_draft_says_what_the_capped_list_is_a_subset_of(findings):
    """A shortened list is allowed. Passing it off as the whole list is not."""
    draft = build_review_draft(domain="many.example", findings=findings)
    shown = len(draft["problem_bullets"])

    assert shown < _ACTIONABLE                                  # the cap is genuinely in effect
    assert draft["bullets_shown"] == shown
    assert draft["bullets_total"] == draft["confirmed_issue_count"] == _ACTIONABLE
    assert draft["bullets_capped"] is True
    assert f"showing the top {shown} of {_ACTIONABLE}" in draft["body"].lower()


def test_an_uncapped_draft_makes_no_subset_claim(findings):
    """The caption appears because the list is short, never as decoration."""
    short = [f for f in findings if f["severity"] != "info"][:3]

    draft = build_review_draft(domain="many.example", findings=short)

    assert draft["bullets_capped"] is False
    assert "showing the top" not in draft["body"].lower()
    assert "3 confirmed issues" in draft["subject"]


def test_the_fix_offer_is_scoped_by_the_same_collection(findings):
    draft = build_review_draft(domain="many.example", findings=findings)

    offerable = draft["fixability"]["offerable"]
    assert offerable <= _ACTIONABLE
    assert sum(draft["fixability"]["counts"].values()) == _ACTIONABLE
    if offerable:
        assert f"fixes for {offerable} of these" in draft["fix_offer"]


# --- client-facing surfaces -----------------------------------------------------------------------

def test_the_html_report_separates_defects_from_observations(packaged):
    report = _text(packaged, "QA-Report.html")

    assert f"<strong>{_ACTIONABLE}</strong><br>actionable findings" in report
    assert f"<strong>{_INFORMATIONAL}</strong><br>informational notes" in report
    # The old page put actionable+informational under one "confirmed findings" label.
    assert f"<strong>{_ACTIONABLE + _INFORMATIONAL}</strong><br>confirmed findings" not in report


def test_the_readme_counts_defects_and_observations_apart(packaged):
    readme = _text(packaged, "00-README.html")

    assert f"<strong>{_ACTIONABLE}</strong> actionable finding" in readme
    assert f"<strong>{_INFORMATIONAL}</strong> informational note" in readme


def test_the_csv_marks_every_row_as_a_defect_or_an_observation(packaged):
    rows = list(csv.DictReader(io.StringIO(_text(packaged, "Findings.csv").lstrip("﻿"))))

    assert len(rows) == _ACTIONABLE + _INFORMATIONAL
    kinds = [row["Type"] for row in rows]
    assert kinds.count("Actionable") == _ACTIONABLE
    assert kinds.count("Informational") == _INFORMATIONAL


def test_the_structured_findings_json_carries_the_split(packaged):
    payload = json.loads(_text(packaged, "Evidence/Technical/findings.json"))

    assert payload["actionable_count"] == _ACTIONABLE
    assert payload["informational_count"] == _INFORMATIONAL
    assert len(payload["findings"]) == _ACTIONABLE + _INFORMATIONAL


def test_the_scan_summary_counts_the_same_way_the_rest_of_the_product_does(packaged):
    """It used its own `severity != "info"` rule, which let "informational"/"none"/"" through."""
    summary = _text(packaged, "Evidence/Technical/scan-summary.md")

    assert f"Confirmed actionable findings: **{_ACTIONABLE}**" in summary
    assert f"Informational notes: **{_INFORMATIONAL}**" in summary


def test_the_zip_manifest_agrees_with_every_page_inside_the_zip(packaged):
    manifest = json.loads(_text(packaged, "manifest.json"))

    assert manifest["actionable_findings"] == _ACTIONABLE
    assert manifest["informational_findings"] == _INFORMATIONAL
    assert len(manifest["findings"]) == _ACTIONABLE + _INFORMATIONAL


def test_every_surface_answers_the_same_question_with_the_same_number(packaged, findings):
    """The one assertion the reviewer asked for, stated once, over all of them at the same time."""
    draft = build_review_draft(domain="many.example", findings=findings)
    manifest = json.loads(_text(packaged, "manifest.json"))
    payload = json.loads(_text(packaged, "Evidence/Technical/findings.json"))
    rows = list(csv.DictReader(io.StringIO(_text(packaged, "Findings.csv").lstrip("﻿"))))

    totals = {
        "target detail": packaged["detail"]["actionable_summary"]["confirmed_issues"],
        "draft subject": int(draft["subject"].split("—")[-1].strip().split()[0]),
        "draft payload": draft["confirmed_issue_count"],
        "structured json": payload["actionable_count"],
        "zip manifest": manifest["actionable_findings"],
        "csv": sum(1 for row in rows if row["Type"] == "Actionable"),
        "html report": int(_text(packaged, "QA-Report.html")
                           .split("<br>actionable findings")[0].rsplit("<strong>", 1)[-1]
                           .removesuffix("</strong>")),
    }

    assert set(totals.values()) == {_ACTIONABLE}, f"surfaces disagree: {totals}"
