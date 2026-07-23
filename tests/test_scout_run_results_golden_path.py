"""Scout — PR-A1: run-scoped Target golden path + MANUAL_ACTION truthfulness (deterministic core).

A completed Manual/XLSX run must be navigable through a normal operator UI with EXACT run+domain
identity, and a MANUAL_ACTION_REQUIRED target must show a truthful incomplete-analysis state rather
than an unqualified "0 defects". This wave pins the read-model + engine contract the UI depends on:

  * the engine persists a canonical manual_action record (reason / stage / stop boundary / whether
    Chromium started / whether the landing loaded / recommended action) when it fails closed;
  * target_detail(domain, run=<run_id>) binds the EXACT run store (never a newer run, never the
    first prospect) and surfaces prospect_status / analysis_complete / manual_action;
  * a DONE target exposes its findings; a MANUAL target exposes 0 confirmed findings + the persisted
    reason and never a healthy conclusion; a domain absent from the pinned run fails honestly.
"""
from __future__ import annotations

import urllib.error
import urllib.request

from core.scout.backends import PageObservation
from core.scout.campaign_service import CampaignService
from core.scout.config import ScoutRunConfig
from core.scout.dashboard import start_dashboard
from core.scout.engine import ScoutEngine
from core.scout.findings import ScoutFinding
from core.scout.service import ScoutService
from core.scout.store import RunStore


# -- engine: persist a canonical manual-action record on a fail-closed target -----------------------


class _CaptchaBackend:
    name = "playwright"
    screenshot_dir = None

    def observe(self, url, timeout_s, max_bytes, *, record_video=False, deep_qa=False):
        return PageObservation(url=url, final_url=url, ok=True, status=200, backend=self.name,
                               captcha_marker=True, headings=[{"level": 1, "text": "verify"}],
                               landmarks={"main": 1})


def test_engine_persists_a_canonical_manual_action_record(tmp_path):
    cfg = ScoutRunConfig(campaign_name="m", seeds=["https://blocked.example/"], browser_mode="playwright",
                         resolve_dns=False, output_dir=str(tmp_path), run_id="run-m")
    store = RunStore(str(tmp_path), "run-m")
    state = ScoutEngine(cfg, store, backend=_CaptchaBackend()).run()
    pid = next(iter(state["prospects"]))
    assert state["prospects"][pid]["status"] == "MANUAL_ACTION_REQUIRED"

    rec = store.load_prospect_artifact(pid, "manual_action.json")
    assert rec is not None
    assert rec["reason"] == "captcha_detected"
    assert rec["chromium_started"] is True          # a real browser was used
    assert rec["landing_loaded"] is True            # the landing page did load before we stopped
    assert rec["analysis_complete"] is False
    assert rec["stage"] and rec["stop_boundary"]    # honest stage + boundary
    assert rec["recommended_action"]                # a safe operator next-step


# -- run-scoped target_detail: exact run + domain, DONE vs MANUAL --------------------------------------

_RUN = "curated-run-A"


def _finding(domain):
    return ScoutFinding(signature="missing_meta_description", category="seo", severity="medium",
                        title=f"{domain}: missing meta description").to_dict()


def _build_run(out, run_id=_RUN):
    store = RunStore(out, run_id)
    store.save_state({"status": "COMPLETED", "prospects": {
        "01-alpha": {"status": "DONE", "url": "https://alpha.example/",
                     "verified_findings": 3, "verified_defects": 2},
        "02-beta": {"status": "MANUAL_ACTION_REQUIRED", "url": "https://beta.example/",
                    "reason": "captcha_detected", "analysis_complete": False}}})
    store.save_prospect_artifact("01-alpha", "findings.json",
                                 {"verified": [_finding("alpha.example")], "rejected": []})
    store.save_prospect_artifact("01-alpha", "observation.json",
                                 {"status": 200, "final_url": "https://alpha.example/"})
    store.save_prospect_artifact("02-beta", "observation.json",
                                 {"status": 200, "final_url": "https://beta.example/", "backend": "playwright"})
    store.save_prospect_artifact("02-beta", "manual_action.json", {
        "reason": "captcha_detected", "stage": "post_landing_precheck",
        "stop_boundary": "stopped_before_interaction", "chromium_started": True,
        "landing_loaded": True, "analysis_complete": False,
        "recommended_action": "Solve the CAPTCHA yourself, then rescan."})
    return store


def test_run_scoped_target_detail_done_exposes_findings(tmp_path):
    _build_run(str(tmp_path))
    det = CampaignService(str(tmp_path)).target_detail("alpha.example", run=_RUN)
    assert det["run"] == _RUN and det["prospect_id"] == "01-alpha"
    assert det["prospect_status"] == "DONE" and det["analysis_complete"] is True
    assert any("missing meta description" in f["title"] for f in det["findings"])
    assert det.get("manual_action") in (None, {})


def test_run_scoped_target_detail_manual_is_truthfully_incomplete(tmp_path):
    _build_run(str(tmp_path))
    det = CampaignService(str(tmp_path)).target_detail("beta.example", run=_RUN)
    assert det["run"] == _RUN and det["prospect_id"] == "02-beta"
    assert det["prospect_status"] == "MANUAL_ACTION_REQUIRED"
    assert det["analysis_complete"] is False
    assert det["findings"] == []                              # never confirmed findings for a manual target
    ma = det["manual_action"]
    assert ma["reason"] == "captcha_detected" and ma["chromium_started"] is True
    assert ma["landing_loaded"] is True and ma["recommended_action"]


def test_pinned_run_never_substitutes_a_newer_run(tmp_path):
    out = str(tmp_path)
    _build_run(out, "run-old")
    newer = RunStore(out, "run-new")
    newer.save_state({"status": "COMPLETED",
                      "prospects": {"01-alpha": {"status": "DONE", "url": "https://alpha.example/"}}})
    newer.save_prospect_artifact("01-alpha", "findings.json", {"verified": [
        ScoutFinding(signature="broken_link", category="functional", severity="high",
                     title="alpha.example: NEWER RUN finding").to_dict()], "rejected": []})
    # Pinning the OLD run must return the OLD run's finding, never the newer run's.
    det = CampaignService(out).target_detail("alpha.example", run="run-old")
    titles = " ".join(f["title"] for f in det["findings"])
    assert "missing meta description" in titles and "NEWER RUN" not in titles
    assert det["run"] == "run-old"


def test_pinned_run_without_matching_domain_fails_honestly(tmp_path):
    _build_run(str(tmp_path))
    det = CampaignService(str(tmp_path)).target_detail("gamma.example", run=_RUN)
    assert det["evidence_status"] == "prospect_not_found"
    assert det["findings"] == [] and det.get("manual_action") in (None, {})


# -- HTTP golden path: run rows link to a human-readable exact-run Target ---------------------------


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read().decode("utf-8"), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8"), e.headers.get("Content-Type", "")


def _serve(out):
    _build_run(out)
    svc = ScoutService(out)
    svc.attach(_RUN)                                  # view the finished run read-only
    return start_dashboard(svc, operator_home=True)


def test_manual_target_page_shows_incomplete_analysis_not_a_healthy_conclusion(tmp_path):
    server, url = _serve(str(tmp_path))
    try:
        status, html, _ = _get(f"{url}/scout/target?run={_RUN}&domain=beta.example")
    finally:
        server.shutdown()
    assert status == 200
    assert "0 confirmed findings" in html and "analysis incomplete" in html.lower()
    assert "captcha_detected" in html                 # the persisted reason is shown
    assert "Solve the CAPTCHA" in html                # the persisted recommended action
    assert "no problems" not in html.lower() and "no verified problem" not in html.lower()
    assert "Back to run" in html


def test_done_target_page_shows_findings_and_back_to_run(tmp_path):
    server, url = _serve(str(tmp_path))
    try:
        status, html, _ = _get(f"{url}/scout/target?run={_RUN}&domain=alpha.example")
    finally:
        server.shutdown()
    assert status == 200
    assert "missing meta description" in html and "Back to run" in html


def test_run_page_details_link_is_human_readable_not_raw_json(tmp_path):
    server, url = _serve(str(tmp_path))
    try:
        _s, html, _ = _get(f"{url}/scout")
    finally:
        server.shutdown()
    # Every prospect row's primary Details link points to the human-readable exact-run Target.
    assert f"/scout/target?run={_RUN}&domain=alpha.example" in html
    assert f"/scout/target?run={_RUN}&domain=beta.example" in html
    # A raw-JSON diagnostic remains available as a SEPARATE secondary action.
    assert "/api/prospect?id=01-alpha" in html and "View raw JSON" in html


def test_api_prospect_remains_json(tmp_path):
    server, url = _serve(str(tmp_path))
    try:
        status, _body, ctype = _get(f"{url}/api/prospect?id=01-alpha")
    finally:
        server.shutdown()
    assert status == 200 and "application/json" in ctype


def test_run_results_lists_done_and_manual_targets(tmp_path):
    server, url = _serve(str(tmp_path))
    try:
        status, html, _ = _get(f"{url}/scout/run?id={_RUN}")
    finally:
        server.shutdown()
    assert status == 200
    assert "alpha.example" in html and "beta.example" in html
    assert "DONE" in html and "MANUAL_ACTION_REQUIRED" in html
    assert f"/scout/target?run={_RUN}&domain=alpha.example" in html   # human-readable details
    # The run Results action is run-scoped, not the generic client/project /results read-model.
    assert "No companies match" not in html


def test_manual_target_not_registered_but_still_visible_in_the_run(tmp_path):
    out = str(tmp_path)
    store = _build_run(out)
    ScoutService(out)._register_analyzed_run(store, store.load_state())   # realistic History write
    from core.scout.discovery.analyzed_registry import AnalyzedSiteRegistry
    domains = {e.domain for e in AnalyzedSiteRegistry(out).all()}
    assert "alpha.example" in domains          # the DONE target is registered as analyzed
    assert "beta.example" not in domains       # the incomplete MANUAL target is NOT registered
    # ...but it remains visible in its own run's results.
    svc = ScoutService(out)
    svc.attach(_RUN)
    server, url = start_dashboard(svc, operator_home=True)
    try:
        _s, html, _ = _get(f"{url}/scout/run?id={_RUN}")
    finally:
        server.shutdown()
    assert "beta.example" in html and "MANUAL_ACTION_REQUIRED" in html


def test_run_scoped_target_does_not_leak_across_domains(tmp_path):
    _build_run(str(tmp_path))
    da = CampaignService(str(tmp_path)).target_detail("alpha.example", run=_RUN)
    # alpha's DONE card carries alpha's finding and none of beta's manual-action evidence.
    assert da["prospect_id"] == "01-alpha"
    assert da.get("manual_action") in (None, {})
    assert all("beta" not in f["title"] for f in da["findings"])
