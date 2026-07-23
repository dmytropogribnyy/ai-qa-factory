"""Scout — PR-A2: evidence usability + operator UI truthfulness (deterministic core).

A real curated smoke run already proved the engine captures useful evidence beyond the basics PR-A1
covered: axe accessibility evidence, console/network/perf evidence, and reproduction video policy.
This wave makes that evidence USABLE and the operator UI TRUTHFUL, without inventing any new
evidence store: it reuses the SAME RunStore/CampaignService/dashboard read-model PR-A1 pinned.

  * Screenshots and raw JSON evidence (observation/findings/scorecard/coverage/manual_action) open
    through the SAME safe, path-confined /scout/artifact route (exact run + exact prospect).
  * A missing artifact, a traversal attempt, and an artifact from another run are all refused
    honestly (404/403) — never silently substituted.
  * A curated/manual-import target shows a truthful label instead of misleading blank dashes for
    fields ("archetype", "business model") that only adaptive discovery ever computes.
  * The Activity page never says "No activity yet" once a Scout run is attached and has produced
    real evidence; when detailed per-event history is absent it says so honestly instead.
  * A manual/disabled video-capture policy is rendered as an intentional policy, never as a failed
    capture.
  * Informational findings (severity == "info") are visually distinguishable from actionable
    defects on the Target page, using the SAME rule the engine already uses for verified_defects.

Every PR-A1 golden-path guarantee (exact-run pinning, MANUAL_ACTION truthfulness, cross-domain
isolation) must still hold — see tests/test_scout_run_results_golden_path.py, re-run unchanged.
"""
from __future__ import annotations

import urllib.error
import urllib.request

from core.scout.campaign_service import CampaignService
from core.scout.dashboard import start_dashboard
from core.scout.findings import ScoutFinding
from core.scout.service import ScoutService
from core.scout.store import RunStore

_RUN = "curated-evidence-run"


def _finding(domain, severity="medium", title="missing meta description"):
    return ScoutFinding(signature=title.replace(" ", "_"), category="seo", severity=severity,
                        title=f"{domain}: {title}").to_dict()


def _build_run(out, run_id=_RUN, *, campaign_name="curated", video_mode="manual"):
    """One curated run with a DONE prospect carrying axe evidence + a screenshot, plus a second
    DONE prospect (a different domain) so cross-prospect isolation can be asserted."""
    store = RunStore(out, run_id)
    store.write_config({"campaign_name": campaign_name, "video_mode": video_mode,
                        "browser_mode": "playwright", "seeds": ["https://alpha.example/"],
                        "max_sites": 1})
    store.save_state({"status": "COMPLETED", "prospects": {
        "01-alpha": {"status": "DONE", "url": "https://alpha.example/",
                     "verified_findings": 2, "verified_defects": 1},
        "02-gamma": {"status": "DONE", "url": "https://gamma.example/",
                     "verified_findings": 1, "verified_defects": 1}}})
    store.save_prospect_artifact("01-alpha", "findings.json", {
        "verified": [_finding("alpha.example", "high", "broken checkout link"),
                     _finding("alpha.example", "info", "minor heading order note")],
        "rejected": []})
    store.save_prospect_artifact("01-alpha", "observation.json", {
        "status": 200, "final_url": "https://alpha.example/", "backend": "playwright",
        "console_errors": ["TypeError: x is not a function"],
        "failed_resources": ["https://alpha.example/broken.js"],
        "timing_ms": {"load": 812.0},
        "axe_status": "ok",
        "axe_violations": [{"id": "color-contrast", "impact": "serious",
                            "help": "Elements must meet minimum color contrast ratio",
                            "nodes": [{}, {}]}],
        "perf": {"domContentLoaded": 400.0}})
    (store.prospect_dir("01-alpha") / "screenshot.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
    store.save_prospect_artifact("01-alpha", "scorecard.json", {"priority": "high"})
    store.save_prospect_artifact("02-gamma", "findings.json",
                                 {"verified": [_finding("gamma.example", "high", "gamma-only issue")],
                                  "rejected": []})
    store.save_prospect_artifact("02-gamma", "observation.json", {
        "status": 200, "final_url": "https://gamma.example/", "backend": "playwright",
        "axe_status": "unavailable"})
    (store.prospect_dir("02-gamma") / "screenshot.png").write_bytes(b"\x89PNG\r\n\x1a\nother")
    return store


def _get(url):
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read().decode("utf-8", "replace"), r.headers.get("Content-Type", "")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), e.headers.get("Content-Type", "")


def _serve(out, **kw):
    _build_run(out, **kw)
    svc = ScoutService(out)
    svc.attach(_RUN)
    return start_dashboard(svc, operator_home=True)


# -- 1: a valid exact-run screenshot artifact opens ---------------------------------------------


def test_exact_run_screenshot_artifact_opens(tmp_path):
    server, url = _serve(str(tmp_path))
    try:
        status, body, ctype = _get(f"{url}/scout/artifact?run={_RUN}&rel=prospects/01-alpha/screenshot.png")
    finally:
        server.shutdown()
    assert status == 200 and ctype == "image/png"
    assert body.startswith("\x89PNG") or "PNG" in body


# -- 2: exact-run text/JSON evidence opens safely -----------------------------------------------


def test_exact_run_json_evidence_opens_safely(tmp_path):
    server, url = _serve(str(tmp_path))
    try:
        status, body, ctype = _get(
            f"{url}/scout/artifact?run={_RUN}&rel=prospects/01-alpha/observation.json")
    finally:
        server.shutdown()
    assert status == 200 and "application/json" in ctype
    assert "axe_status" in body and "color-contrast" in body


# -- 3: a missing artifact produces a truthful not-found state, not a silent 200 -----------------


def test_missing_artifact_is_a_truthful_not_found(tmp_path):
    server, url = _serve(str(tmp_path))
    try:
        status, _body, _ct = _get(f"{url}/scout/artifact?run={_RUN}&rel=prospects/01-alpha/nope.json")
    finally:
        server.shutdown()
    assert status == 404


# -- 4: traversal / absolute path attempts are rejected ------------------------------------------


def test_path_traversal_is_rejected(tmp_path):
    server, url = _serve(str(tmp_path))
    try:
        status, _body, _ct = _get(
            f"{url}/scout/artifact?run={_RUN}&rel=../../../../etc/passwd")
        status_abs, _b2, _c2 = _get(f"{url}/scout/artifact?run={_RUN}&rel=/etc/passwd")
    finally:
        server.shutdown()
    assert status in (403, 404)
    assert status_abs in (403, 404)


# -- 5: an artifact from another run cannot be opened through the selected run -------------------


def test_artifact_from_another_run_not_reachable_through_selected_run(tmp_path):
    out = str(tmp_path)
    _build_run(out, run_id="run-a")
    other = RunStore(out, "run-b")
    other.write_config({"campaign_name": "curated"})
    other.save_state({"status": "COMPLETED", "prospects": {
        "01-alpha": {"status": "DONE", "url": "https://alpha.example/"}}})
    other.save_prospect_artifact("01-alpha", "observation.json", {"status": 200})
    (other.prospect_dir("01-alpha") / "secret.png").write_bytes(b"other-run-secret")
    svc = ScoutService(out)
    svc.attach("run-a")
    server, url = start_dashboard(svc, operator_home=True)
    try:
        status, _body, _ct = _get(f"{url}/scout/artifact?run=run-a&rel=prospects/01-alpha/secret.png")
    finally:
        server.shutdown()
    assert status == 404


# -- 6: an artifact/finding from another prospect/domain cannot leak onto this target's page -----


def test_cross_prospect_media_never_leaks_into_the_wrong_domain(tmp_path):
    _build_run(str(tmp_path))
    det_alpha = CampaignService(str(tmp_path)).target_detail("alpha.example", run=_RUN)
    det_gamma = CampaignService(str(tmp_path)).target_detail("gamma.example", run=_RUN)
    assert all("02-gamma" not in m for m in det_alpha["media"])
    assert all("01-alpha" not in m for m in det_gamma["media"])
    titles_alpha = " ".join(f["title"] for f in det_alpha["findings"])
    assert "gamma-only issue" not in titles_alpha


# -- 7: curated/manual source renders a truthful label instead of misleading dashes --------------


def test_curated_source_renders_a_truthful_label_not_bare_dashes(tmp_path):
    server, url = _serve(str(tmp_path), campaign_name="curated")
    try:
        _s, html, _ct = _get(f"{url}/scout/target?run={_RUN}&domain=alpha.example")
    finally:
        server.shutdown()
    assert "curated list import" in html.lower()
    assert "not missing data" in html.lower()


def test_manual_source_renders_a_truthful_label(tmp_path):
    server, url = _serve(str(tmp_path), campaign_name="adhoc")
    try:
        _s, html, _ct = _get(f"{url}/scout/target?run={_RUN}&domain=alpha.example")
    finally:
        server.shutdown()
    assert "manual url scan" in html.lower()


# -- 8: a completed run does not render "No activity yet" ----------------------------------------


def test_completed_run_does_not_render_no_activity_yet(tmp_path):
    out = str(tmp_path)
    store = _build_run(out)
    store.append_event({"event": "campaign_started"})
    store.append_event({"event": "prospect_done", "prospect": "01-alpha", "verified": 2, "defects": 1})
    svc = ScoutService(out)
    svc.attach(_RUN)
    server, url = start_dashboard(svc, operator_home=True)
    try:
        status, html, _ct = _get(f"{url}/activity")
    finally:
        server.shutdown()
    assert status == 200
    assert "no activity yet" not in html.lower()
    assert "prospect_done" in html


# -- 9: absent detailed history is described honestly, not as "no activity" ----------------------


def test_absent_detailed_activity_history_is_described_honestly(tmp_path):
    out = str(tmp_path)
    _build_run(out)                                   # a completed run, but NO events.jsonl written
    svc = ScoutService(out)
    svc.attach(_RUN)
    server, url = start_dashboard(svc, operator_home=True)
    try:
        status, html, _ct = _get(f"{url}/activity")
    finally:
        server.shutdown()
    assert status == 200
    assert "no activity yet" not in html.lower()
    assert "historical activity" in html.lower() and "unavailable" in html.lower()


# -- 10: manual/disabled video policy is shown as policy, not a failed capture --------------------


def test_manual_video_policy_is_not_shown_as_a_capture_failure(tmp_path):
    server, url = _serve(str(tmp_path), video_mode="manual")
    try:
        _s, html, _ct = _get(f"{url}/scout/target?run={_RUN}&domain=alpha.example")
    finally:
        server.shutdown()
    assert "manual/opt-in" in html.lower() and "expected, not a defect" in html.lower()


def test_disabled_video_policy_is_shown_as_intentional(tmp_path):
    server, url = _serve(str(tmp_path), video_mode="off")
    try:
        _s, html, _ct = _get(f"{url}/scout/target?run={_RUN}&domain=alpha.example")
    finally:
        server.shutdown()
    assert "disabled for this run" in html.lower()
    assert "intentional policy, not a failed capture" in html.lower()


# -- 11: informational evidence is distinguishable from actionable defects -----------------------


def test_informational_findings_are_distinguishable_from_defects(tmp_path):
    server, url = _serve(str(tmp_path))
    try:
        _s, html, _ct = _get(f"{url}/scout/target?run={_RUN}&domain=alpha.example")
    finally:
        server.shutdown()
    assert "Informational" in html and ">Defect<" in html


def test_axe_evidence_is_surfaced_with_honest_status(tmp_path):
    server, url = _serve(str(tmp_path))
    try:
        _s, html_alpha, _ct = _get(f"{url}/scout/target?run={_RUN}&domain=alpha.example")
        _s2, html_gamma, _ct2 = _get(f"{url}/scout/target?run={_RUN}&domain=gamma.example")
    finally:
        server.shutdown()
    assert "color-contrast" in html_alpha
    assert "axe-core evidence was unavailable" in html_gamma.lower()


# -- 12: PR-A1 exact-run + MANUAL_ACTION regression guarantees remain intact ----------------------


def test_pr_a1_exact_run_pinning_and_manual_truthfulness_still_hold(tmp_path):
    """A light, self-contained re-check of the PR-A1 read-model contract this PR must not regress
    (the FULL regression suite lives in tests/test_scout_run_results_golden_path.py)."""
    out = str(tmp_path)
    _build_run(out, run_id="run-old")
    newer = RunStore(out, "run-new")
    newer.write_config({"campaign_name": "curated"})
    newer.save_state({"status": "COMPLETED",
                      "prospects": {"01-alpha": {"status": "DONE", "url": "https://alpha.example/"}}})
    newer.save_prospect_artifact("01-alpha", "findings.json",
                                 {"verified": [_finding("alpha.example", "high", "NEWER RUN finding")],
                                  "rejected": []})
    det = CampaignService(out).target_detail("alpha.example", run="run-old")
    titles = " ".join(f["title"] for f in det["findings"])
    assert "broken checkout link" in titles and "NEWER RUN" not in titles
    assert det["run"] == "run-old"
