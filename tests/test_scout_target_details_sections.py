"""A target page must say why evidence is missing, not leave a gap that looks like progress.

"0 captured", "Not available" and an empty cell all mean different things and all read the same: as
though something were still running. They are not the same. A static scan never opens a browser, so a
screenshot is *not applicable*; a deep scan that found no reproducible interaction *did not capture*
one and that is a policy outcome; a deep scan whose axe-core injection failed is a *capture failure*
and is the only one of the three that is a defect in us.

So evidence carries one of four explicit states, each with the reason attached, and the page is laid
out as the four sections an operator works through: Findings, Evidence, Contact & outreach, Client
package.
"""
from __future__ import annotations

import urllib.request

import pytest

from core.scout.campaign_service import CampaignService
from core.scout.dashboard import start_dashboard
from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
from core.scout.evidence_state import (AVAILABLE, CAPTURE_FAILED, NOT_APPLICABLE, NOT_CAPTURED,
                                       evidence_states)
from core.scout.service import ScoutService
from core.scout.store import RunStore

FINDING = {"id": "f1", "title": "Checkout button does nothing on mobile", "severity": "high",
           "category": "functional", "url": "https://plausible.io/pricing",
           "business_impact": "Visitors cannot complete a purchase.", "confidence": "verified",
           "reproduction_steps": ["Open /pricing on a phone", "Tap Start free trial"],
           "evidence_refs": ["pricing.png"]}


def _run(out: str, domain: str, *, run_id: str = "c1", findings=(), emails: str = "",
         screenshots=(), video: bool = False, axe_status: str = "ok", axe_violations=(),
         perf=None, video_mode: str = "qualified_auto", console_errors=()) -> None:
    store = RunStore(out, run_id)
    pid = "01"
    store.save_artifact("config.json", {"campaign_name": "operator-scan",
                                        "video_mode": video_mode})
    store.save_state({"status": "COMPLETED", "finished_at": "2026-07-26T10:00:00+00:00",
                      "prospects": {pid: {"url": f"https://{domain}/", "status": "DONE"}}})
    store.save_prospect_artifact(pid, "observation.json", {
        "url": f"https://{domain}/", "final_url": f"https://{domain}/contact", "status": 200,
        "links": [f"mailto:{emails}"] if emails else [], "title": domain, "headings": [],
        "axe_status": axe_status, "axe_violations": list(axe_violations),
        "console_errors": list(console_errors), "perf": dict(perf or {}),
        "timing_ms": {"total": 812} if perf else {}})
    if findings:
        store.save_prospect_artifact(pid, "findings.json", {"verified": list(findings)})
        store.save_prospect_artifact(pid, "scorecard.json", {"priority": "A"})
    pdir = store.prospect_dir(pid)
    for name in screenshots:
        (pdir / name).write_bytes(b"\x89PNG\r\n\x1a\n" + bytes(96))
    if screenshots:
        store.save_prospect_artifact(pid, "screenshots.json", {"frames": [
            {"file": name, "role": name.rsplit(".", 1)[0], "url": f"https://{domain}/{name[:-4]}"}
            for name in screenshots]})
    if video:
        (pdir / "reproduction.webm").write_bytes(b"\x1a\x45\xdf\xa3" + bytes(96))
        store.save_prospect_artifact(pid, "reproduction.json", {"reproduced": True})
    AnalyzedSiteRegistry(out).record_analysis(
        domain, status=ANALYZED, evidence_ref=f"scout/{run_id}", campaign_id=run_id)


def _states(out: str, domain: str):
    return {s.kind: s for s in evidence_states(CampaignService(out).target_detail(domain))}


# --- the four states -----------------------------------------------------------------------------

def test_captured_screenshots_are_available(tmp_path):
    out = str(tmp_path)
    _run(out, "plausible.io", screenshots=("landing.png", "pricing.png"))

    state = _states(out, "plausible.io")["screenshots"]

    assert state.state == AVAILABLE
    assert state.count == 2
    assert state.label == "Available"


def test_a_static_scan_reports_screenshots_as_not_applicable(tmp_path):
    """No browser was opened, so there is nothing that failed — it was never in scope."""
    out = str(tmp_path)
    _run(out, "nolt.io", axe_status="")

    state = _states(out, "nolt.io")["screenshots"]

    assert state.state == NOT_APPLICABLE
    assert "static scan" in state.label
    assert state.label.startswith("Not applicable")


def test_axe_that_could_not_run_is_a_capture_failure(tmp_path):
    """The browser opened and axe-core still did not run. That one is ours."""
    out = str(tmp_path)
    _run(out, "nolt.io", screenshots=("landing.png",), axe_status="unavailable")

    state = _states(out, "nolt.io")["accessibility"]

    assert state.state == CAPTURE_FAILED
    assert state.label.startswith("Capture failed:")


def test_axe_that_ran_clean_is_available_not_missing(tmp_path):
    """Zero violations is a result. Reporting it as absent evidence would invert the finding."""
    out = str(tmp_path)
    _run(out, "nolt.io", screenshots=("landing.png",), axe_status="ok")

    state = _states(out, "nolt.io")["accessibility"]

    assert state.state == AVAILABLE
    assert state.count == 0


def test_a_static_scan_reports_axe_as_not_applicable(tmp_path):
    out = str(tmp_path)
    _run(out, "nolt.io", axe_status="")

    assert _states(out, "nolt.io")["accessibility"].state == NOT_APPLICABLE


# --- video, where the policy decides ------------------------------------------------------------

def test_video_disabled_for_the_run_is_not_applicable(tmp_path):
    out = str(tmp_path)
    _run(out, "nolt.io", screenshots=("landing.png",), video_mode="off")

    state = _states(out, "nolt.io")["video"]

    assert state.state == NOT_APPLICABLE
    assert "disabled" in state.label


def test_video_that_qualified_but_did_not_reproduce_is_not_captured(tmp_path):
    """An honest policy outcome, not a failure: nothing safe reproduced cleanly."""
    out = str(tmp_path)
    _run(out, "nolt.io", screenshots=("landing.png",), video_mode="qualified_auto")

    state = _states(out, "nolt.io")["video"]

    assert state.state == NOT_CAPTURED
    assert state.label.startswith("Not captured:")
    assert "reproduced" in state.label


def test_a_recorded_video_is_available(tmp_path):
    out = str(tmp_path)
    _run(out, "plausible.io", findings=[FINDING], screenshots=("landing.png",), video=True)

    state = _states(out, "plausible.io")["video"]

    assert state.state == AVAILABLE
    assert state.count == 1


def test_an_unrecorded_video_policy_is_never_guessed(tmp_path):
    out = str(tmp_path)
    _run(out, "nolt.io", screenshots=("landing.png",), video_mode="")

    state = _states(out, "nolt.io")["video"]

    assert state.state == NOT_CAPTURED
    assert "not recorded" in state.label.lower()


# --- every state carries a reason ----------------------------------------------------------------

def test_no_state_is_ever_a_bare_blank(tmp_path):
    out = str(tmp_path)
    _run(out, "nolt.io", axe_status="")

    for state in evidence_states(CampaignService(out).target_detail("nolt.io")):
        assert state.label.strip(), state.kind
        assert state.label not in ("", "—", "N/A", "Pending"), state.kind
        if state.state in (NOT_CAPTURED, CAPTURE_FAILED):
            assert ":" in state.label, state.kind        # the reason is attached


# --- the page ------------------------------------------------------------------------------------

@pytest.fixture()
def target_page(tmp_path):
    out = str(tmp_path)
    _run(out, "plausible.io", findings=[FINDING], emails="hello@plausible.io",
         screenshots=("landing.png", "pricing.png"), video=True,
         axe_violations=[{"id": "image-alt", "help": "Images must have alternate text"}],
         perf={"lcp_ms": 3400}, console_errors=["TypeError: x is not a function"])
    server, url = start_dashboard(ScoutService(out), operator_home=True)
    try:
        with urllib.request.urlopen(url + "/scout/target?domain=plausible.io", timeout=15) as r:
            yield r.read().decode("utf-8")
    finally:
        server.shutdown()


def test_the_page_has_the_four_agreed_sections(target_page):
    for section in ("Findings", "Evidence", "Contact &amp; outreach", "Client package"):
        assert f"<h2>{section}</h2>" in target_page, section


def test_the_sections_are_in_working_order(target_page):
    order = [target_page.index(f"<h2>{s}</h2>") for s in
             ("Findings", "Evidence", "Contact &amp; outreach", "Client package")]
    assert order == sorted(order), order


def test_a_finding_carries_what_it_takes_to_act_on_it(target_page):
    assert "Checkout button does nothing on mobile" in target_page
    assert "Visitors cannot complete a purchase." in target_page
    assert "Tap Start free trial" in target_page                 # reproduction steps
    assert "plausible.io/pricing" in target_page                 # the affected URL
    assert "verified" in target_page.lower()                     # verification status


def test_evidence_states_reach_the_page_with_their_reasons(target_page):
    assert "Available" in target_page
    for label in ("Screenshots", "Reproduction video", "Accessibility", "Performance"):
        assert label in target_page, label


def test_evidence_can_be_opened_and_downloaded(target_page):
    assert "/scout/artifact?" in target_page
    assert "download" in target_page                            # a real download affordance


def test_the_video_plays_inline(target_page):
    assert "<video" in target_page
    assert "controls" in target_page


def test_the_contact_shows_where_it_came_from(target_page):
    assert "hello@plausible.io" in target_page
    assert "plausible.io/contact" in target_page                # the source URL, not a guess


def test_the_draft_says_it_was_not_sent(target_page):
    assert "Draft &mdash; not sent" in target_page or "Draft — not sent" in target_page
    assert "Copy draft" in target_page


def test_talking_points_are_shown_separately_from_the_draft(target_page):
    assert "Talking points" in target_page
    assert "Suggested subject" in target_page


def test_the_client_package_states_what_it_would_contain(target_page):
    assert "Client package" in target_page
    assert "Download client evidence (.zip)" in target_page
    assert "Preview report" in target_page


def test_the_client_package_is_not_pre_approved(target_page):
    """Generating a ZIP is not the same as deciding it may be sent."""
    assert "review" in target_page.lower()
    assert "approved_for_client_delivery" not in target_page


# --- what must never leak ------------------------------------------------------------------------

def test_a_clean_site_gets_no_outreach_draft(tmp_path):
    out = str(tmp_path)
    _run(out, "nolt.io", emails="hello@nolt.io", screenshots=("landing.png",))
    server, url = start_dashboard(ScoutService(out), operator_home=True)
    try:
        with urllib.request.urlopen(url + "/scout/target?domain=nolt.io", timeout=15) as r:
            html = r.read().decode("utf-8")
    finally:
        server.shutdown()

    assert "Copy draft" not in html
    assert "no actionable finding" in html
    # And it must not overclaim in the other direction either.
    assert "not a conclusion that the site is defect-free" in html
