"""Scout — P1 Golden Path: Manual URL Scan + curated XLSX/CSV import must support Deep Capture.

The Manual URL Scan and curated import launch through the guarded /api/campaign/start
(CampaignLauncher). It previously hard-forced browser_mode="static", so imported/manual runs could
never use the product's real Playwright path (screenshots, axe-core, real perf timing, browser
console/network evidence, qualified reproduction video). These deterministic regressions pin an
explicit, operator-controlled scan mode:

  * Static (default when omitted) and Deep Capture (Playwright) are the ONLY accepted values.
  * The validated mode flows into ScoutRunConfig (no longer forced static).
  * Deep Capture runs a real Chromium preflight and REFUSES honestly when unavailable — it never
    silently downgrades to static.
  * Static never triggers a browser preflight; neither path constructs Tavily/discovery.
  * Deep mode reuses the SAME ScoutEngine and produces the shared operator outputs (History
    registration + domain-scoped Target cards), with no cross-domain leakage.
  * Both launchers (pasted URL + imported list) expose the same selector and send browser_mode.

The real-Chromium proof (an imported target producing a genuine screenshot + axe/perf, and static
producing no browser artifacts) lives in tests/test_phase831_playwright_acceptance.py.
"""
from __future__ import annotations

import urllib.request

from core.scout.backends import PageObservation
from core.scout.campaign_service import CampaignService
from core.scout.campaign_start import CampaignLauncher
from core.scout.config import ScoutRunConfig
from core.scout.dashboard import start_dashboard
from core.scout.discovery.tavily_provider import TavilyDiscoveryProvider
from core.scout.service import ScoutService

_HOST = "127.0.0.1:8933"
_SEED = "http://127.0.0.1:8933/"


class _FakeService:
    """Minimal ScoutService stand-in: records the started config without a real engine."""

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


def _launcher(tmp_path, *, browser_probe=None):
    svc = _FakeService(str(tmp_path))
    kw = {} if browser_probe is None else {"browser_probe": browser_probe}
    launcher = CampaignLauncher(svc, registry_dir=str(tmp_path / "reg"),
                                allowed_local_hosts=frozenset({_HOST}), resolve_dns=False,
                                starter=svc.start, **kw)
    return launcher, svc


def _req(key="k1", **extra):
    body = {"confirm": True, "idempotency_key": key, "seeds": [_SEED]}
    body.update(extra)
    return body


# -- validation: static | playwright | default -----------------------------------------------------


def test_omitted_mode_builds_the_documented_static_default(tmp_path):
    launcher, svc = _launcher(tmp_path)
    r = launcher.start(_req())
    assert r.ok and svc.started_configs[-1].browser_mode == "static"


def test_static_request_builds_static(tmp_path):
    launcher, svc = _launcher(tmp_path)
    r = launcher.start(_req(browser_mode="static"))
    assert r.ok and svc.started_configs[-1].browser_mode == "static"


def test_deep_request_builds_playwright_when_chromium_available(tmp_path):
    launcher, svc = _launcher(tmp_path, browser_probe=lambda: True)
    r = launcher.start(_req(browser_mode="playwright"))
    assert r.ok and svc.started_configs[-1].browser_mode == "playwright"   # never rewritten to static


def test_unknown_mode_is_rejected(tmp_path):
    launcher, svc = _launcher(tmp_path, browser_probe=lambda: True)
    r = launcher.start(_req(browser_mode="chromium"))
    assert not r.ok and r.status == 422 and not svc.started_configs   # arbitrary backend names refused


def test_non_string_mode_is_rejected(tmp_path):
    launcher, svc = _launcher(tmp_path, browser_probe=lambda: True)
    r = launcher.start(_req(browser_mode=["playwright"]))
    assert not r.ok and r.status == 422 and not svc.started_configs


# -- preflight: deep refuses honestly, never downgrades; static never probes ------------------------


def test_deep_refused_when_chromium_unavailable_no_silent_downgrade(tmp_path):
    launcher, svc = _launcher(tmp_path, browser_probe=lambda: False)
    r = launcher.start(_req(browser_mode="playwright"))
    assert not r.ok and not svc.started_configs                       # nothing started, no downgrade
    assert "chromium" in r.message.lower() or "deep capture" in r.message.lower()   # actionable


def test_static_never_runs_a_browser_preflight(tmp_path):
    def _boom():
        raise AssertionError("static must never probe Chromium")
    launcher, svc = _launcher(tmp_path, browser_probe=_boom)
    r = launcher.start(_req(browser_mode="static"))
    assert r.ok and svc.started_configs[-1].browser_mode == "static"


def test_manual_start_constructs_no_tavily(tmp_path, monkeypatch):
    def _no(*a, **k):
        raise AssertionError("Tavily discovery must never be constructed on the manual path")
    monkeypatch.setattr(TavilyDiscoveryProvider, "__init__", _no)
    # A fresh launcher/service per start (the one-active-run guard forbids two concurrent runs).
    l_static, _ = _launcher(tmp_path / "s", browser_probe=lambda: True)
    l_deep, _ = _launcher(tmp_path / "d", browser_probe=lambda: True)
    assert l_static.start(_req(key="a", browser_mode="static")).ok
    assert l_deep.start(_req(key="b", browser_mode="playwright")).ok      # neither path builds Tavily


# -- UI: both launchers expose the same mode selector (Deep Capture default) and send browser_mode --


def test_manual_scan_page_exposes_mode_selector_and_wires_both_launchers(tmp_path):
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        with urllib.request.urlopen(url + "/scout", timeout=5) as r:
            body = r.read().decode()
    finally:
        server.shutdown()
    assert 'id="scanmode"' in body                                   # a scan-mode selector exists
    assert "Deep Capture" in body and "Static" in body               # both modes offered
    assert body.count("browser_mode") >= 2                           # pasted + imported both send it
    assert "axe" in body.lower() and "screenshot" in body.lower()    # brief explainer of Deep Capture


# -- deep mode reuses the SAME engine + shared outputs (History + domain-scoped cards, no leak) ------


class _PerDomainBackend:
    name = "playwright"
    screenshot_dir = None

    def observe(self, url, timeout_s, max_bytes, *, record_video=False, deep_qa=False):
        return PageObservation(url=url, final_url=url, ok=True, status=200, backend=self.name,
                               title="T", meta_description="d", html_bytes=1000,
                               headings=[{"level": 1, "text": "h"}], landmarks={"main": 1},
                               headers={"content-type": "text/html", "cache-control": "max-age=60"})


def test_deep_multi_target_run_registers_history_and_domain_scoped_cards(tmp_path, monkeypatch):
    def _no(*a, **k):
        raise AssertionError("deep manual run must not construct Tavily")
    monkeypatch.setattr(TavilyDiscoveryProvider, "__init__", _no)
    out = str(tmp_path)
    svc = ScoutService(out)
    cfg = ScoutRunConfig(campaign_name="deep", seeds=["https://alpha.example/", "https://beta.example/"],
                         browser_mode="playwright", resolve_dns=False, output_dir=out)
    svc.start(cfg, backend=_PerDomainBackend())
    svc.join(timeout=60)

    cs = CampaignService(out)
    hist = {r["domain"] for r in cs.history()}
    assert {"alpha.example", "beta.example"} <= hist                 # deep run registers History
    da = cs.target_detail("alpha.example")
    db = cs.target_detail("beta.example")
    assert da.get("evidence_status") == "ok" and db.get("evidence_status") == "ok"
    assert da.get("prospect_id") and da.get("prospect_id") != db.get("prospect_id")   # domain-scoped
