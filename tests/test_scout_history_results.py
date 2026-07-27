"""History should say what came of a site, not what kind of run touched it.

"Analyzed" and "Prospect" were the only two things the table said about an outcome, and neither is an
outcome: one repeats that a scan happened, the other repeats that the site has not been contacted.
An operator scanning the list could not tell a company with three confirmed defects and a public
mailbox from one that came back clean, without opening both.

So the column becomes a real verdict — ready to contact, needs review, no actionable findings,
blocked, failed — derived from the same run artifacts the target page reads, plus the evidence and
contact facts that decide which of them is true.
"""
from __future__ import annotations

import urllib.request

import pytest

from core.scout.campaign_service import CampaignService
from core.scout.dashboard import start_dashboard
from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
from core.scout.service import ScoutService
from core.scout.site_result import (BLOCKED, FAILED, NEEDS_REVIEW, NO_ACTIONABLE, NOT_ANALYZED,
                                    READY_TO_CONTACT, site_result)
from core.scout.store import RunStore

FINDING = {"id": "f1", "title": "Checkout button does nothing on mobile", "severity": "high",
           "business_impact": "Visitors cannot complete a purchase.", "confidence": "verified"}
INFO_ONLY = {"id": "f2", "title": "Missing meta description", "severity": "info",
             "business_impact": "Minor search presentation issue."}


def _analyzed_run(out: str, run_id: str, domain: str, *, findings=(), status: str = "DONE",
                  emails: str = "", screenshots: int = 0, video: bool = False,
                  priority: str = "") -> None:
    """One persisted run holding exactly one prospect for `domain`."""
    store = RunStore(out, run_id)
    pid = "01"
    store.save_state({"status": "COMPLETED", "finished_at": "2026-07-26T10:00:00+00:00",
                      "prospects": {pid: {"url": f"https://{domain}/", "status": status}}})
    links = [f"mailto:{emails}"] if emails else []
    store.save_prospect_artifact(pid, "observation.json", {
        "url": f"https://{domain}/", "final_url": f"https://{domain}/contact",
        "status": 200, "links": links, "title": domain, "headings": []})
    if findings:
        store.save_prospect_artifact(pid, "findings.json", {"verified": list(findings)})
    if priority:
        store.save_prospect_artifact(pid, "scorecard.json", {"priority": priority})
    pdir = store.prospect_dir(pid)
    for index in range(screenshots):
        (pdir / f"page-{index}.png").write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(64))
    if video:
        (pdir / "reproduction.webm").write_bytes(b"\x1a\x45\xdf\xa3" + bytes(64))
        store.save_prospect_artifact(pid, "reproduction.json", {"reproduced": True})
    AnalyzedSiteRegistry(out).record_analysis(
        domain, status=ANALYZED, evidence_ref=f"scout/{run_id}", campaign_id=run_id)


def _result(out: str, domain: str):
    return site_result(CampaignService(out).target_detail(domain))


# --- the five verdicts ---------------------------------------------------------------------------

def test_findings_plus_a_public_mailbox_is_ready_to_contact(tmp_path):
    out = str(tmp_path)
    _analyzed_run(out, "c1", "plausible.io", findings=[FINDING], emails="hello@plausible.io",
                  screenshots=1)

    result = _result(out, "plausible.io")

    assert result.result == READY_TO_CONTACT
    assert result.label == "Ready to contact"
    assert result.contact_email == "hello@plausible.io"


def test_findings_without_a_contact_needs_review(tmp_path):
    """There is something worth saying and nobody proven to say it to."""
    out = str(tmp_path)
    _analyzed_run(out, "c1", "userlist.com", findings=[FINDING], screenshots=1)

    result = _result(out, "userlist.com")

    assert result.result == NEEDS_REVIEW
    assert result.label == "Needs review"
    assert result.contact_email == ""


def test_a_clean_site_is_no_actionable_findings_not_a_failure(tmp_path):
    out = str(tmp_path)
    _analyzed_run(out, "c1", "nolt.io", emails="hello@nolt.io", screenshots=1)

    result = _result(out, "nolt.io")

    assert result.result == NO_ACTIONABLE
    assert result.label == "No actionable findings"


def test_informational_notes_alone_are_not_actionable(tmp_path):
    """An info-severity note is not a defect worth an email."""
    out = str(tmp_path)
    _analyzed_run(out, "c1", "nolt.io", findings=[INFO_ONLY], emails="hello@nolt.io")

    result = _result(out, "nolt.io")

    assert result.result == NO_ACTIONABLE
    assert result.findings == 1
    assert result.actionable == 0


def test_a_challenged_target_is_blocked(tmp_path):
    out = str(tmp_path)
    _analyzed_run(out, "c1", "bookoo.eu", status="MANUAL_ACTION_REQUIRED")

    result = _result(out, "bookoo.eu")

    assert result.result == BLOCKED
    assert result.label == "Blocked"


def test_a_failed_target_is_failed(tmp_path):
    out = str(tmp_path)
    _analyzed_run(out, "c1", "broken.example", status="FAILED")

    assert _result(out, "broken.example").result == FAILED


def test_a_target_that_was_never_scanned_says_so(tmp_path):
    """Forcing a never-started target into "Failed" would be a lie about what happened."""
    out = str(tmp_path)
    AnalyzedSiteRegistry(out).record_analysis("never.example", status="DISCOVERED")

    result = _result(out, "never.example")

    assert result.result == NOT_ANALYZED
    assert result.label == "Not analyzed"


# --- the facts the row shows beside the verdict --------------------------------------------------

def test_the_row_counts_evidence_that_actually_exists(tmp_path):
    out = str(tmp_path)
    _analyzed_run(out, "c1", "plausible.io", findings=[FINDING], emails="hello@plausible.io",
                  screenshots=2, video=True)

    result = _result(out, "plausible.io")

    assert result.screenshots == 2
    assert result.has_video is True
    assert result.evidence_label == "2 screenshots · video"


def test_no_evidence_is_reported_as_none_not_as_a_blank(tmp_path):
    out = str(tmp_path)
    _analyzed_run(out, "c1", "nolt.io", emails="hello@nolt.io")

    assert _result(out, "nolt.io").evidence_label == "None captured"


def test_priority_comes_from_the_scorecard_and_is_blank_when_absent(tmp_path):
    out = str(tmp_path)
    _analyzed_run(out, "c1", "plausible.io", findings=[FINDING], priority="A")
    _analyzed_run(out, "c2", "nolt.io", findings=[FINDING])

    assert _result(out, "plausible.io").priority == "A"
    assert _result(out, "nolt.io").priority == ""


def test_an_incomplete_analysis_never_reports_findings(tmp_path):
    """PR #51's fail-closed rule: a blocked target has no confirmed findings to show."""
    out = str(tmp_path)
    _analyzed_run(out, "c1", "bookoo.eu", findings=[FINDING], status="MANUAL_ACTION_REQUIRED")

    result = _result(out, "bookoo.eu")

    assert result.findings == 0
    assert result.actionable == 0


# --- the table the operator reads ----------------------------------------------------------------

@pytest.fixture()
def history_page(tmp_path):
    out = str(tmp_path)
    _analyzed_run(out, "c1", "plausible.io", findings=[FINDING], emails="hello@plausible.io",
                  screenshots=2, video=True, priority="A")
    _analyzed_run(out, "c2", "nolt.io", emails="hello@nolt.io", screenshots=1)
    _analyzed_run(out, "c3", "bookoo.eu", status="MANUAL_ACTION_REQUIRED")
    server, url = start_dashboard(ScoutService(out), operator_home=True)
    try:
        with urllib.request.urlopen(url + "/scout/history", timeout=15) as response:
            yield response.read().decode("utf-8")
    finally:
        server.shutdown()


def test_history_has_the_agreed_columns(history_page):
    for column in ("Site", "Result", "Priority", "Evidence", "Contact", "Analyzed", "Open"):
        assert f"<th>{column}</th>" in history_page, column


def test_history_shows_the_verdict_not_the_run_type(history_page):
    assert "Ready to contact" in history_page
    assert "No actionable findings" in history_page
    assert "Blocked" in history_page
    assert "<th>Analysis</th>" not in history_page
    assert "<th>Prospect stage</th>" not in history_page


def test_history_shows_the_contact_it_actually_found(history_page):
    assert "hello@plausible.io" in history_page
    assert "Not found" in history_page          # the blocked target has none


def test_history_offers_one_date_filter_not_three(history_page):
    """Presets, a last-N-days box and a from/to range all at once is three ways to say one thing."""
    assert history_page.count('name="days"') <= 1
    assert "<summary>Date range</summary>" in history_page
    assert history_page.count('class="chip active"') <= 1


def test_history_keeps_search_and_a_status_filter(history_page):
    assert 'name="text"' in history_page
    assert 'name="result"' in history_page
