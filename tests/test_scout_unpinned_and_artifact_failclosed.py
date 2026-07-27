"""Scout — the unpinned Target page and the artifact route must obey the SAME completeness rule.

Two P1 gaps this pins, both reachable from production UI rather than a synthetic URL:

* the Target page chose its renderer by whether a ``run`` query parameter was present
  (``dashboard.py``), not by whether the analysis completed. The History table links to
  ``/scout/target?domain=...`` with NO run, so a domain whose LATEST run was interrupted rendered the
  completed-analysis card — "Analysis complete", a healthy "no actionable defect" conclusion and a
  client-ready evidence button — for a target that was never analyzed.
* a page that says "0 confirmed findings" still linked to the result-bearing artifacts themselves
  (findings.json, scorecard.json, reproduction.json, the reproduction video), and ``/scout/artifact``
  served them to a direct request with no completeness gate at all.

The rescan-interrupted fixture below is the real shape: a domain completed once, was rescanned, and
the rescan died before its result was recorded. History still lists the domain, and unpinned
resolution binds the LATEST run store.
"""
from __future__ import annotations

import urllib.error
import urllib.request

from core.scout.dashboard import start_dashboard
from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
from core.scout.findings import ScoutFinding
from core.scout.service import ScoutService
from core.scout.store import RunStore
from tests.scout_seam_fixtures import RUN_A, build_seam_stand, no_tavily

DONE_RUN = "rescan-run-A"
INTERRUPTED_RUN = "rescan-run-B"
DOMAIN = "omega.example"
PID = "01-omega"

# Artifacts that carry a QA RESULT. They may only be reachable for a completed analysis.
RESULT_BEARING = ("findings.json", "scorecard.json", "reproduction.json", "reproduction.webm")


def _finding(tag: str, severity: str) -> dict:
    return ScoutFinding(signature=f"{tag}_{severity}", category="seo", check_family="seo",
                        severity=severity, confidence="high",
                        title=f"{DOMAIN}: {tag} ({severity})",
                        actual=f"observed on https://{DOMAIN}/").to_dict()


def _write_result_artifacts(store: RunStore, tag: str) -> None:
    store.save_prospect_artifact(PID, "findings.json", {
        "verified": [_finding(tag, "high"), _finding(tag, "info")], "rejected": []})
    store.save_prospect_artifact(PID, "observation.json",
                                 {"status": 200, "final_url": f"https://{DOMAIN}/"})
    store.save_prospect_artifact(PID, "scorecard.json", {"prospect_id": PID, "priority": "A"})
    store.save_prospect_artifact(PID, "reproduction.json", {
        "signature": f"{tag}_high", "reproduced": True, "video_ref": "reproduction.webm"})
    pdir = store.prospect_dir(PID)
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "reproduction.webm").write_bytes(b"WEBM-" + tag.encode())
    (pdir / "shot.png").write_bytes(b"PNG-" + tag.encode())


def build_rescan_interrupted_stand(out: str) -> None:
    """One domain, analyzed successfully once and then rescanned into an interrupted run.

    History registers the domain from the COMPLETED run; the registry then also records the rescan,
    so unpinned resolution walks ``campaign_ids`` in reverse and binds the interrupted run.
    """
    done = RunStore(out, DONE_RUN)
    done_state = {"status": "COMPLETED", "prospects": {
        PID: {"status": "DONE", "url": f"https://{DOMAIN}/",
              "verified_findings": 2, "verified_defects": 1}}}
    done.save_state(done_state)
    _write_result_artifacts(done, "first-pass")
    ScoutService(out)._register_analyzed_run(done, done_state)

    interrupted = RunStore(out, INTERRUPTED_RUN)
    interrupted.save_state({"status": "RUNNING", "prospects": {
        PID: {"status": "PENDING", "url": f"https://{DOMAIN}/"}}})
    _write_result_artifacts(interrupted, "rescan")
    AnalyzedSiteRegistry(out).record_analysis(DOMAIN, status=ANALYZED,
                                              campaign_id=INTERRUPTED_RUN)


def _get(url: str) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(url, timeout=5) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")


def _serve(out: str):
    return start_dashboard(ScoutService(out), operator_home=True)


# -- P1-A: the renderer is chosen by completeness, not by the presence of ?run= -------------------


def test_unpinned_page_for_an_interrupted_rescan_is_not_a_healthy_conclusion(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    out = str(tmp_path)
    build_rescan_interrupted_stand(out)
    server, url = _serve(out)
    try:
        status, html = _get(f"{url}/scout/target?domain={DOMAIN}")
    finally:
        server.shutdown()

    assert status == 200
    assert "Analysis complete" not in html
    assert "No actionable defect was confirmed" not in html
    assert "Completed with confirmed actionable findings" not in html
    assert "0 confirmed findings" in html
    assert "Download client evidence (.zip)" not in html


def test_unpinned_page_for_an_interrupted_rescan_names_the_real_state(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    out = str(tmp_path)
    build_rescan_interrupted_stand(out)
    server, url = _serve(out)
    try:
        _, html = _get(f"{url}/scout/target?domain={DOMAIN}")
    finally:
        server.shutdown()

    assert "Not analyzed" in html                       # the PENDING label, badge and <title>
    assert "did not finish" in html
    assert "Needs your help" not in html                # it was interrupted, not blocked


def test_pinned_non_done_still_renders_the_incomplete_screen(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    out = str(tmp_path)
    build_seam_stand(out)
    server, url = _serve(out)
    try:
        _, html = _get(f"{url}/scout/target?run={RUN_A}&domain=delta.example")
    finally:
        server.shutdown()

    assert "0 confirmed findings" in html
    assert "Analysis complete" not in html
    assert "Download client evidence (.zip)" not in html


def test_a_done_target_keeps_its_completed_card_pinned_and_unpinned(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    out = str(tmp_path)
    build_seam_stand(out)
    server, url = _serve(out)
    try:
        _, pinned = _get(f"{url}/scout/target?run={RUN_A}&domain=alpha.example")
        _, unpinned = _get(f"{url}/scout/target?domain=alpha.example")
    finally:
        server.shutdown()

    for html in (pinned, unpinned):
        assert "Analysis complete" in html
        assert "Download client evidence (.zip)" in html
        assert "alpha.example: alpha (high)" in html    # confirmed findings stay available


# -- P1-B: result-bearing artifacts are not reachable for an incomplete analysis ------------------


def test_incomplete_page_does_not_link_result_bearing_artifacts(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    out = str(tmp_path)
    build_rescan_interrupted_stand(out)
    server, url = _serve(out)
    try:
        _, html = _get(f"{url}/scout/target?domain={DOMAIN}")
    finally:
        server.shutdown()

    for name in RESULT_BEARING:
        assert name not in html, f"{name} is linked from a page that reports 0 confirmed findings"
    assert "Finding records" not in html
    assert "Priority scorecard" not in html
    assert "Reproduction record" not in html
    # A neutral page-level capture stays available — it explains why the scan stopped.
    assert "shot.png" in html or "No screenshot was captured" in html


def test_direct_artifact_requests_fail_closed_for_an_incomplete_target(tmp_path, monkeypatch):
    """The user-facing artifact URL is guessable; the gate cannot live in the page alone."""
    no_tavily(monkeypatch)
    out = str(tmp_path)
    build_rescan_interrupted_stand(out)
    server, url = _serve(out)
    try:
        for name in RESULT_BEARING:
            code, body = _get(
                f"{url}/scout/artifact?run={INTERRUPTED_RUN}&rel=prospects/{PID}/{name}")
            assert code in (403, 404, 409), f"{name} served with HTTP {code}"
            assert "rescan (high)" not in body, f"{name} leaked finding content"
            assert "WEBM" not in body, f"{name} leaked video bytes"
    finally:
        server.shutdown()


def test_direct_artifact_requests_still_work_for_a_completed_target(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    out = str(tmp_path)
    build_rescan_interrupted_stand(out)
    server, url = _serve(out)
    try:
        code, body = _get(f"{url}/scout/artifact?run={DONE_RUN}&rel=prospects/{PID}/findings.json")
        vid, _ = _get(f"{url}/scout/artifact?run={DONE_RUN}&rel=prospects/{PID}/reproduction.webm")
    finally:
        server.shutdown()

    assert code == 200 and "first-pass (high)" in body
    assert vid == 200


def test_neutral_artifacts_stay_available_for_an_incomplete_target(tmp_path, monkeypatch):
    """Withholding the result must not blind the operator to WHY the run stopped."""
    no_tavily(monkeypatch)
    out = str(tmp_path)
    build_rescan_interrupted_stand(out)
    server, url = _serve(out)
    try:
        obs, _ = _get(f"{url}/scout/artifact?run={INTERRUPTED_RUN}&rel=prospects/{PID}/observation.json")
        shot, _ = _get(f"{url}/scout/artifact?run={INTERRUPTED_RUN}&rel=prospects/{PID}/shot.png")
    finally:
        server.shutdown()

    assert obs == 200
    assert shot == 200


def test_client_ready_evidence_is_refused_for_an_incomplete_target(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    out = str(tmp_path)
    build_rescan_interrupted_stand(out)
    server, url = _serve(out)
    try:
        code, body = _get(
            f"{url}/scout/client-evidence?run={INTERRUPTED_RUN}&domain={DOMAIN}")
    finally:
        server.shutdown()

    assert code >= 400
    assert "rescan (high)" not in body


# -- the real challenge workflow must survive untouched -------------------------------------------


def test_challenge_target_keeps_its_workflow_and_manual_action_data(tmp_path, monkeypatch):
    no_tavily(monkeypatch)
    out = str(tmp_path)
    build_seam_stand(out)
    server, url = _serve(out)
    try:
        _, html = _get(f"{url}/scout/target?run={RUN_A}&domain=beta.example")
    finally:
        server.shutdown()

    assert "Needs your help" in html
    assert "human verification check" in html           # the persisted manual-action reason
    for element_id in ("opencheck", "continuecheck", "defercheck", "skipcheck", "challengemsg"):
        assert f'id="{element_id}"' in html, f"challenge element {element_id} disappeared"
    assert "Stop-reason record" in html                 # manual_action.json stays reachable
