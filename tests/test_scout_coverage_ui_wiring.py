"""Scout — PR-B: within-site Coverage profile wired into the operator UI/CLI + honest readout.

PR #33 built the within-site coverage CORE (core/scout/coverage.py + ScoutRunConfig.coverage):
adaptive -> page ceiling 12, deep -> page ceiling 20, explicit -> raw/back-compat mode (still the
ScoutRunConfig default, never operator-selectable). This file does NOT rebuild that core. It pins
that the guarded /api/campaign/start launcher (Manual URL Scan + curated import both go through it)
now:

  * accepts ONLY the exact operator strings "adaptive" (default) / "deep" for ``coverage``;
  * rejects unknown/non-string coverage with an honest 422 and starts NO run (same fail-closed shape
    as the existing browser_mode validation);
  * never exposes "explicit" as a UI/CLI choice;
  * lets a selected profile override a legacy client-supplied max_pages (ScoutRunConfig.__post_init__
    already enforces this — pinned here end-to-end through the launcher);
  * persists the selected profile into config.json via the real ScoutEngine path.

It also pins the Dashboard's Coverage readout (Target page card + Run Results column): built ONLY
from the persisted exact-run/exact-prospect coverage.json / compact state row, phrasing the page
ceiling as an "up to" cap (never a quota), never claiming multi-step flow support, and showing a
truthful unavailable state — never a fabricated zero — for a historical/legacy/incomplete prospect
with no coverage.json.
"""
from __future__ import annotations

import urllib.request

from core.scout.backends import PageObservation
from core.scout.campaign_service import CampaignService
from core.scout.campaign_start import CampaignLauncher
from core.scout.config import ScoutConfigError, ScoutRunConfig
from core.scout.dashboard import _coverage_card_html, start_dashboard
from core.scout.service import ScoutService
from core.scout.store import RunStore

_HOST = "127.0.0.1:8934"
_SEED = "http://127.0.0.1:8934/"


class _FakeService:
    """Minimal ScoutService stand-in: records the started config without a real engine (same shape
    as tests/test_scout_deep_capture_mode.py, reused here for the launcher-level coverage checks)."""

    def __init__(self, output_dir: str) -> None:
        self.output_dir = output_dir
        self._running = False
        self.started_configs = []
        self.run_id = ""

    def start(self, cfg):
        if self._running:
            raise RuntimeError("a run is already active")
        self._running = True
        self.run_id = cfg.run_id
        self.started_configs.append(cfg)
        return cfg.run_id

    def is_running(self):
        return self._running

    def status(self):
        return {"running": self._running, "mode": "ACTIVE" if self._running else "IDLE",
                "controllable": self._running, "run_id": self.run_id, "state": {}, "control": {}}


def _launcher(tmp_path):
    svc = _FakeService(str(tmp_path))
    launcher = CampaignLauncher(svc, registry_dir=str(tmp_path / "reg"),
                                allowed_local_hosts=frozenset({_HOST}), resolve_dns=False,
                                starter=svc.start)
    return launcher, svc


def _req(key="k1", **extra):
    body = {"confirm": True, "idempotency_key": key, "seeds": [_SEED]}
    body.update(extra)
    return body


# -- 1/2. Manual URL Scan + curated import (SAME guarded endpoint) default to adaptive --------------


def test_manual_scan_launch_defaults_to_adaptive_when_coverage_omitted(tmp_path):
    launcher, svc = _launcher(tmp_path)
    r = launcher.start(_req())
    assert r.ok and svc.started_configs[-1].coverage == "adaptive"


def test_curated_import_launch_defaults_to_adaptive_when_coverage_omitted(tmp_path):
    # The curated-import flow posts through the SAME /api/campaign/start launcher, just with a
    # different campaign name (see dashboard.py launchImport()) — pinned explicitly here too.
    launcher, svc = _launcher(tmp_path)
    r = launcher.start(_req(campaign="curated"))
    assert r.ok and svc.started_configs[-1].coverage == "adaptive"


# -- 3/8. deep reaches ScoutRunConfig, persists to config.json, and overrides a legacy max_pages -----


def test_deep_selection_reaches_scout_run_config(tmp_path):
    launcher, svc = _launcher(tmp_path)
    r = launcher.start(_req(coverage="deep"))
    assert r.ok and svc.started_configs[-1].coverage == "deep"
    assert svc.started_configs[-1].max_pages_per_site == 20   # deep's own ceiling, not the raw default


def test_selected_profile_overrides_a_client_supplied_max_pages(tmp_path):
    launcher, svc = _launcher(tmp_path)
    r = launcher.start(_req(coverage="deep", max_pages=3))
    assert r.ok
    cfg = svc.started_configs[-1]
    assert cfg.coverage == "deep" and cfg.max_pages_per_site == 20   # never the client's 3
    launcher2, svc2 = _launcher(tmp_path / "b")
    r2 = launcher2.start(_req(key="k2", coverage="adaptive", max_pages=50))
    assert r2.ok and svc2.started_configs[-1].max_pages_per_site == 12   # never the client's 50


def test_deep_selection_persists_into_config_json_via_the_real_engine(tmp_path):
    out = str(tmp_path)
    svc = ScoutService(out)
    cfg = ScoutRunConfig(campaign_name="deepcfg", seeds=[_SEED], browser_mode="static",
                         resolve_dns=False, output_dir=out, coverage="deep")

    class _Backend:
        name = "static"
        screenshot_dir = None

        def observe(self, url, timeout_s, max_bytes, *, record_video=False, deep_qa=False):
            return PageObservation(url=url, final_url=url, ok=True, status=200, backend=self.name,
                                   title="T", meta_description="d", html_bytes=1000,
                                   headings=[{"level": 1, "text": "h"}], landmarks={"main": 1},
                                   headers={"content-type": "text/html", "cache-control": "max-age=60"})

    svc.start(cfg, backend=_Backend())
    svc.join(timeout=60)
    store = RunStore(out, svc.run_id)
    persisted = store.load_config()
    assert persisted.get("coverage") == "deep"
    assert persisted.get("max_pages_per_site") == 20


# -- 4. Unknown / non-string coverage: honest 422, no run started -----------------------------------


def test_unknown_coverage_value_is_rejected_and_starts_no_run(tmp_path):
    launcher, svc = _launcher(tmp_path)
    r = launcher.start(_req(coverage="explicit"))
    assert not r.ok and r.status == 422 and not svc.started_configs


def test_arbitrary_unknown_coverage_string_is_rejected(tmp_path):
    launcher, svc = _launcher(tmp_path)
    r = launcher.start(_req(coverage="thorough"))
    assert not r.ok and r.status == 422 and not svc.started_configs


def test_non_string_coverage_is_rejected(tmp_path):
    launcher, svc = _launcher(tmp_path)
    r = launcher.start(_req(coverage=["deep"]))
    assert not r.ok and r.status == 422 and not svc.started_configs


# -- 5. "explicit" is never exposed as an operator UI choice -----------------------------------------


def test_manual_scan_page_exposes_coverage_selector_without_explicit(tmp_path):
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        with urllib.request.urlopen(url + "/scout", timeout=5) as r:
            body = r.read().decode()
    finally:
        server.shutdown()
    assert 'id="coverage"' in body and 'id=impcoverage' in body      # pasted + imported both offer it
    assert 'value="adaptive" selected' in body                       # adaptive is the default choice
    assert 'value=adaptive selected' in body                         # curated-import preview default
    assert 'value="explicit"' not in body and 'value=explicit' not in body   # never an operator choice
    assert body.count("coverage") >= 2                                # both forms actually send it


# -- 6/7. Raw ScoutRunConfig default + historical-config preservation (guards PR-33's core) ---------


def test_raw_scout_run_config_default_coverage_remains_explicit():
    cfg = ScoutRunConfig(campaign_name="c", seeds=["https://ex.com/"])
    assert cfg.coverage == "explicit"


def test_historical_config_without_coverage_key_preserves_legacy_max_pages():
    hist = {"campaign_name": "c", "seeds": ["https://ex.com/"], "max_pages_per_site": 4}
    cfg = ScoutRunConfig.from_dict(hist)
    assert cfg.coverage == "explicit" and cfg.max_pages_per_site == 4


def test_scout_config_error_still_raised_for_a_bad_coverage_value_at_the_dataclass_level():
    try:
        ScoutRunConfig(campaign_name="c", seeds=["https://ex.com/"], coverage="bogus")
        raise AssertionError("expected ScoutConfigError")
    except ScoutConfigError:
        pass


# -- 9/10. Exact-run Target page shows the right prospect's coverage; no cross-leak ------------------


def _seed_prospect_with_coverage(store: RunStore, pid: str, domain: str, coverage: dict) -> None:
    store.save_prospect_artifact(pid, "observation.json", {"status": 200, "final_url": f"https://{domain}/"})
    store.save_prospect_artifact(pid, "findings.json", {"verified": [], "rejected": []})
    store.save_prospect_artifact(pid, "coverage.json", coverage)


def _build_two_prospect_run(out: str, run_id: str):
    from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
    store = RunStore(out, run_id)
    prospects = {"01-alpha": "alpha-cov.example", "02-beta": "beta-cov.example"}
    state = {"status": "COMPLETED", "prospects": {
        pid: {"status": "DONE", "url": f"https://{dom}/"} for pid, dom in prospects.items()}}
    store.save_state(state)
    _seed_prospect_with_coverage(store, "01-alpha", "alpha-cov.example", {
        "coverage": "adaptive", "page_ceiling": 12, "meaningful_pages_tested": 4,
        "pages_skipped_noise": 1, "pages_skipped_near_duplicate": 2,
        "page_stop_reason": "links_exhausted", "flows_detected": 1, "flow_entries_checked": 1,
        "flow_steps_supported": 1, "flow_steps_used": 1, "flow_stop_reason": "single_step_supported"})
    _seed_prospect_with_coverage(store, "02-beta", "beta-cov.example", {
        "coverage": "deep", "page_ceiling": 20, "meaningful_pages_tested": 9,
        "pages_skipped_noise": 0, "pages_skipped_near_duplicate": 0,
        "page_stop_reason": "page_ceiling_reached", "flows_detected": 0, "flow_entries_checked": 1,
        "flow_steps_supported": 1, "flow_steps_used": 0, "flow_stop_reason": "no_flow_entry_detected"})
    ScoutService(out)._register_analyzed_run(store, state)
    for dom in prospects.values():
        AnalyzedSiteRegistry(out).record_analysis(dom, status=ANALYZED, campaign_id=run_id)
    return CampaignService(out)


def test_target_page_shows_the_correct_prospects_own_coverage(tmp_path):
    cs = _build_two_prospect_run(str(tmp_path), "cov-run-1")
    da = cs.target_detail("alpha-cov.example")
    db = cs.target_detail("beta-cov.example")
    assert da["coverage"]["coverage"] == "adaptive" and da["coverage"]["meaningful_pages_tested"] == 4
    assert db["coverage"]["coverage"] == "deep" and db["coverage"]["meaningful_pages_tested"] == 9
    # never leaked / swapped
    assert da["coverage"] != db["coverage"]
    assert da["coverage"]["page_stop_reason"] != db["coverage"]["page_stop_reason"]


# -- 11. Missing coverage.json -> honest legacy/unavailable state, never a fabricated zero -----------


def test_missing_coverage_json_is_reported_as_unavailable_not_zero(tmp_path):
    out = str(tmp_path)
    from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
    store = RunStore(out, "legacy-run")
    state = {"status": "COMPLETED", "prospects": {"01-legacy": {"status": "DONE", "url": "https://legacy.example/"}}}
    store.save_state(state)
    store.save_prospect_artifact("01-legacy", "observation.json", {"status": 200})
    store.save_prospect_artifact("01-legacy", "findings.json", {"verified": [], "rejected": []})
    # deliberately NO coverage.json written (pre-coverage-feature legacy run)
    ScoutService(out)._register_analyzed_run(store, state)
    AnalyzedSiteRegistry(out).record_analysis("legacy.example", status=ANALYZED, campaign_id="legacy-run")
    cs = CampaignService(out)
    det = cs.target_detail("legacy.example")
    assert det.get("coverage") is None
    html = _coverage_card_html(det.get("coverage"))
    assert "not available" in html.lower()
    assert "0" not in html   # never a fabricated zero rendered in its place


# -- 12. UI never claims multi-step flow support or invents a 10/15-step ceiling ---------------------


def test_coverage_card_describes_single_step_flow_honestly():
    html = _coverage_card_html({
        "coverage": "adaptive", "page_ceiling": 12, "meaningful_pages_tested": 5,
        "pages_skipped_noise": 0, "pages_skipped_near_duplicate": 0,
        "page_stop_reason": "no_new_meaningful_coverage", "flows_detected": 1,
        "flow_entries_checked": 1, "flow_steps_supported": 1, "flow_steps_used": 1,
        "flow_stop_reason": "single_step_supported"})
    assert "single-step" in html.lower()
    assert "multi-step" not in html.lower() or "not implemented" in html.lower()
    assert "10-step" not in html and "15-step" not in html
    assert "up to 12 pages" in html   # phrased as a cap, never a quota
    assert "quota" not in html.lower().replace("never a quota", "")


def test_coverage_card_never_implies_the_ceiling_was_fully_consumed():
    html = _coverage_card_html({
        "coverage": "deep", "page_ceiling": 20, "meaningful_pages_tested": 3,
        "pages_skipped_noise": 0, "pages_skipped_near_duplicate": 0,
        "page_stop_reason": "no_new_meaningful_coverage", "flows_detected": 0,
        "flow_entries_checked": 0, "flow_steps_supported": 1, "flow_steps_used": 0,
        "flow_stop_reason": "flow_check_disabled"})
    assert "up to 20" in html
    assert "3" in html   # the honest tested count is still shown, distinct from the ceiling
