"""Phase 8.3 — full deterministic Scout E2E over the bundled demo site.

Proves the complete pipeline end to end with the static backend (no external network, no
browser): campaign -> URL eligibility -> profiling -> browser checks -> findings -> evidence
-> verification -> scoring -> persistence -> dashboard/API retrieval -> report export. Also
verifies the clean control, CAPTCHA manual-action, sanitized report, and that no secret leaks.
"""
from __future__ import annotations

import itertools
import json
import urllib.request

from core.scout.config import ScoutRunConfig
from core.scout.engine import ScoutEngine
from core.scout.report import build_report
from core.scout.service import ScoutService
from core.scout.dashboard import start_dashboard
from core.scout.store import RunStore
from core.scout.demo_site import serve_demo_site

_SCENARIOS = ["clean", "broken_link", "accessibility", "seo", "structured_data",
              "mobile", "presubmit", "business_flow", "captcha", "access_prohibition"]
_c = itertools.count()


def _clock():
    return f"2026-07-17T02:00:{next(_c):02d}+00:00"


def _run(tmp):
    with serve_demo_site() as (base, host):
        seeds = [f"{base}/{n}/index.html" for n in _SCENARIOS]
        cfg = ScoutRunConfig(campaign_name="e2e", seeds=seeds,
                             allowed_local_hosts=frozenset({host}), browser_mode="static",
                             output_dir=str(tmp), run_id="e2e", resolve_dns=False)
        store = RunStore(str(tmp), "e2e")
        state = ScoutEngine(cfg, store, clock=_clock).run()
        summary = build_report(store, clock=_clock)
        return state, store, summary


def test_full_pipeline_and_report(tmp_path):
    state, store, summary = _run(tmp_path)
    assert state["status"] == "COMPLETED"

    # Report artifacts published.
    rdir = store.report_dir()
    for name in ("REPORT.json", "EVIDENCE_INDEX.json", "CAMPAIGN_SUMMARY.md",
                 "PROSPECT_SHORTLIST.md", "VERIFIED_FINDINGS.md",
                 "COVERAGE_AND_LIMITATIONS.md", "SCORECARD_SUMMARY.md"):
        assert (rdir / name).exists(), f"missing report artifact: {name}"

    report = json.loads((rdir / "REPORT.json").read_text(encoding="utf-8"))
    assert report["verified_findings"]  # at least one verified defect
    # CAPTCHA and access-prohibition -> manual action (no interaction).
    manual_urls = {m["url"] for m in report["manual_action_required"]}
    assert any("captcha" in u for u in manual_urls)
    assert any("access_prohibition" in u for u in manual_urls)

    # Clean control produced no verified defects.
    clean = next(r for r in report["shortlist"] if r["url"].endswith("/clean/index.html"))
    assert clean["verified_defects"] == 0

    # Every verified finding is client-safe.
    assert all(f["is_client_safe"] for f in report["verified_findings"])


def test_report_is_sanitized_no_secret_leak(tmp_path):
    _, store, _ = _run(tmp_path)
    # The fixture sends a Set-Cookie: session=secretcookievalue; it must never reach any artifact.
    for path in store.root.rglob("*"):
        if path.is_file():
            blob = path.read_bytes()
            assert b"secretcookievalue" not in blob, f"secret leaked into {path.name}"
            assert b"set-cookie" not in blob.lower()


def test_evidence_index_references_only_approved_artifacts(tmp_path):
    _, store, _ = _run(tmp_path)
    idx = json.loads((store.report_dir() / "EVIDENCE_INDEX.json").read_text(encoding="utf-8"))
    for pid, entry in idx.items():
        ref = entry["evidence_ref"]           # e.g. prospects/01-.../evidence.json
        assert (store.root / ref).exists(), f"evidence ref not an approved artifact: {ref}"


def test_dashboard_serves_finished_run(tmp_path):
    _, store, _ = _run(tmp_path)
    service = ScoutService(str(tmp_path))
    service.attach("e2e")
    server, url = start_dashboard(service)
    try:
        with urllib.request.urlopen(url + "/api/status", timeout=5) as r:
            assert json.loads(r.read())["state"]["status"] == "COMPLETED"
        with urllib.request.urlopen(url + "/artifact?path=report/REPORT.json", timeout=5) as r:
            assert r.status == 200 and b"verified_findings" in r.read()
    finally:
        server.shutdown()
