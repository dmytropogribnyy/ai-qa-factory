"""Two findings that look identical once you throw away what told them apart.

A live discovery run reported seven actionable findings for a target and listed six. Nothing
miscounted: `_project_target_finding` drops `signature`, and every consumer downstream re-ran the
canonical split over the projected list. Two findings the split had kept apart by signature became
one finding with the same title and URL, and the second one vanished between the count and the list.
The client ZIP inherited it, because its own projection drops the same field and re-splits again.

Restoring the field would fix these two projections and leave the shape of the mistake in place:
the next attribute anybody drops re-creates it. So the rule this module pins is stronger —

    the canonical split is decided ONCE, on the complete findings, and the DECISION travels
    with each finding as data. Nothing downstream re-decides.

Every surface therefore reads a label it was handed rather than re-deriving one from fields that may
no longer be there.
"""
from __future__ import annotations

import csv
import io
import json
import zipfile

import pytest

from core.scout.actionable import actionable_set

# Same title, same URL, different signatures. These are two distinct problems the engine confirmed
# separately — a checker that runs per page finds the same class of defect on two pages of one
# template, and the signature is what says so.
_TWINS = [
    {"title": "Form field has no label", "url": "https://twins.example/contact",
     "severity": "high", "category": "accessibility", "signature": "a11y-label-name-1",
     "business_impact": "Screen-reader users cannot tell what to type."},
    {"title": "Form field has no label", "url": "https://twins.example/contact",
     "severity": "high", "category": "accessibility", "signature": "a11y-label-name-2",
     "business_impact": "Screen-reader users cannot tell what to type."},
    {"title": "Slow first paint", "url": "https://twins.example/", "severity": "medium",
     "category": "performance", "signature": "perf-fcp", "business_impact": "Visitors wait."},
    {"title": "Uses HTTP/2", "url": "https://twins.example/", "severity": "info",
     "category": "seo", "signature": "info-http2", "business_impact": ""},
]
_ACTIONABLE = 3
_INFORMATIONAL = 1


@pytest.fixture
def packaged(tmp_path):
    from core.scout.campaign_service import CampaignService
    from core.scout.client_evidence import build_client_evidence_bundle
    from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
    from core.scout.store import RunStore

    store = RunStore(str(tmp_path), "run-twins")
    store.write_config({"campaign_name": "adhoc", "run_purpose": "production"})
    store.save_state({"status": "COMPLETED", "prospects": {
        "01": {"status": "DONE", "url": "https://twins.example/",
               "verified_findings": len(_TWINS), "verified_defects": _ACTIONABLE}}})
    store.save_prospect_artifact("01", "findings.json", {"verified": _TWINS})
    AnalyzedSiteRegistry(str(tmp_path)).record_analysis("twins.example", status=ANALYZED,
                                                        campaign_id="run-twins")

    detail = CampaignService(str(tmp_path)).target_detail("twins.example", run="run-twins")
    bundle = build_client_evidence_bundle(str(tmp_path), run_id="run-twins", prospect_id="01",
                                          domain="twins.example", detail=detail)
    with zipfile.ZipFile(bundle.path) as archive:
        blobs = {name.split("/", 1)[1]: archive.read(name)
                 for name in archive.namelist() if "/" in name}
    return {"detail": detail, "blobs": blobs}


def _text(packaged, name):
    return packaged["blobs"][name].decode("utf-8")


# --- the split itself keeps them apart ------------------------------------------------------------

def test_the_canonical_split_keeps_two_signatures_apart():
    """If this ever collapses, everything below is testing the wrong thing."""
    canonical = actionable_set(_TWINS)

    assert canonical.confirmed_issue_count == _ACTIONABLE
    assert len(canonical.suppressed) == 0
    assert len(canonical.informational) == _INFORMATIONAL


def test_re_splitting_a_projection_is_what_used_to_lose_one():
    """The mechanism, stated once: without the signature these two ARE indistinguishable."""
    stripped = [{k: v for k, v in f.items() if k != "signature"} for f in _TWINS]

    assert actionable_set(stripped).confirmed_issue_count == _ACTIONABLE - 1


# --- the read model hands the decision on rather than inviting a recount --------------------------

def test_target_detail_lists_as_many_actionable_findings_as_it_counts(packaged):
    detail = packaged["detail"]
    listed = [f for f in detail["findings"] if f.get("kind") == "actionable"]

    assert detail["actionable_summary"]["confirmed_issues"] == _ACTIONABLE
    assert len(listed) == _ACTIONABLE
    assert len(detail["findings"]) == _ACTIONABLE + _INFORMATIONAL


def test_every_projected_finding_carries_the_decision_that_was_made_about_it(packaged):
    kinds = [f.get("kind") for f in packaged["detail"]["findings"]]

    assert kinds.count("actionable") == _ACTIONABLE
    assert kinds.count("informational") == _INFORMATIONAL
    assert None not in kinds


def test_the_draft_agrees_with_the_list_it_was_drawn_from(packaged):
    draft = packaged["detail"]["draft"]

    assert draft["confirmed_issue_count"] == _ACTIONABLE
    assert f"{_ACTIONABLE} confirmed issues" in draft["subject"]
    assert packaged["detail"]["fixability"]["offerable"] <= _ACTIONABLE
    assert sum(packaged["detail"]["fixability"]["counts"].values()) == _ACTIONABLE


# --- the client package must not lose one on the way out ------------------------------------------

def test_the_html_report_counts_and_lists_the_same_number(packaged):
    report = _text(packaged, "QA-Report.html")
    rows = report.split("Informational observations")[0].count("<tr><td><span class=\"sev\"")

    assert f"<strong>{_ACTIONABLE}</strong><br>actionable findings" in report
    assert rows == _ACTIONABLE, "the report's actionable table lost a row its own metric counts"


def test_the_csv_carries_both_twins(packaged):
    rows = list(csv.DictReader(io.StringIO(_text(packaged, "Findings.csv").lstrip("﻿"))))
    actionable = [r for r in rows if r["Type"] == "Actionable"]

    assert len(actionable) == _ACTIONABLE
    assert sum(1 for r in actionable if r["Title"] == "Form field has no label") == 2


def test_the_structured_json_counts_match_its_own_list(packaged):
    payload = json.loads(_text(packaged, "Evidence/Technical/findings.json"))

    assert payload["actionable_count"] == _ACTIONABLE
    assert sum(1 for f in payload["findings"] if f["kind"] == "Actionable") == _ACTIONABLE
    assert len(payload["findings"]) == _ACTIONABLE + _INFORMATIONAL


def test_the_zip_manifest_counts_match_its_own_list(packaged):
    manifest = json.loads(_text(packaged, "manifest.json"))

    assert manifest["actionable_findings"] == _ACTIONABLE
    assert sum(1 for f in manifest["findings"] if f["kind"] == "Actionable") == _ACTIONABLE


def test_the_scan_summary_agrees(packaged):
    summary = _text(packaged, "Evidence/Technical/scan-summary.md")

    assert f"Confirmed actionable findings: **{_ACTIONABLE}**" in summary
    assert summary.count("Form field has no label") == 2


def test_every_surface_answers_with_the_same_number(packaged):
    """One assertion over all of them at once — the shape of the defect, in one place."""
    detail = packaged["detail"]
    manifest = json.loads(_text(packaged, "manifest.json"))
    payload = json.loads(_text(packaged, "Evidence/Technical/findings.json"))
    rows = list(csv.DictReader(io.StringIO(_text(packaged, "Findings.csv").lstrip("﻿"))))

    totals = {
        "summary count": detail["actionable_summary"]["confirmed_issues"],
        "detail list": sum(1 for f in detail["findings"] if f.get("kind") == "actionable"),
        "draft": detail["draft"]["confirmed_issue_count"],
        "json count": payload["actionable_count"],
        "json list": sum(1 for f in payload["findings"] if f["kind"] == "Actionable"),
        "manifest count": manifest["actionable_findings"],
        "manifest list": sum(1 for f in manifest["findings"] if f["kind"] == "Actionable"),
        "csv": sum(1 for r in rows if r["Type"] == "Actionable"),
    }

    assert set(totals.values()) == {_ACTIONABLE}, f"surfaces disagree: {totals}"


# --- and the validator notices when they do not ---------------------------------------------------

def test_the_validator_compares_carried_counts_rather_than_recomputing(tmp_path):
    """It re-split the projected list and reported the product's own projection as a disagreement."""
    from core.scout.campaign_service import CampaignService
    from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
    from core.scout.run_validation import PASS, validate_run
    from core.scout.store import RunStore

    store = RunStore(str(tmp_path), "run-twins")
    store.write_config({"campaign_name": "adhoc", "run_purpose": "production",
                        "seeds": ["https://twins.example/"],
                        "intake": {"kind": "paste", "rows_read": 1, "rows_accepted": 1,
                                   "rows_rejected": 0, "duplicates": 0, "rows_capped": 0}})
    store.save_state({"status": "COMPLETED", "started_at": "2026-07-28T09:00:00+00:00",
                      "finished_at": "2026-07-28T09:05:00+00:00", "prospects": {
                          "01": {"status": "DONE", "url": "https://twins.example/",
                                 "verified_findings": _ACTIONABLE + _INFORMATIONAL,
                                 "verified_defects": _ACTIONABLE}}})
    store.save_prospect_artifact("01", "findings.json", {"verified": _TWINS})
    AnalyzedSiteRegistry(str(tmp_path)).record_analysis("twins.example", status=ANALYZED,
                                                        campaign_id="run-twins")
    store.append_event({"event": "run_started"})
    store.append_event({"event": "prospect_done", "prospect": "01"})
    store.append_event({"event": "run_finished"})

    report = validate_run(str(tmp_path), "run-twins", read_model=CampaignService(str(tmp_path)))
    checks = {c.check_id: c for c in report.checks}

    assert checks["finding_count_consistency"].status == PASS, checks[
        "finding_count_consistency"].observed
    assert checks["surface_agreement"].status == PASS, checks["surface_agreement"].observed
