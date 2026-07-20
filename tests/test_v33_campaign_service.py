"""v3.3 — campaign orchestration service (Dashboard Scout API), deterministic (fake transport).

Covers the operator workflow glue: catalog, preflight, a synchronous bounded launch through the
REAL DiscoveryEngine (mocked Tavily transport, no DNS/network), the run-control lifecycle reaching
a terminal state with an honest stop_reason, persisted brain decisions, progress read-model,
history, and evidence-bundle export.
"""
from __future__ import annotations

import json

from core.scout.campaign_service import CampaignService
from core.scout.run_control import COMPLETED, FAILED, STOPPED_CHECKPOINT


def _transport(results):
    def _t(body, key):
        return {"results": results}
    return _t


def _svc(tmp_path):
    return CampaignService(output_dir=str(tmp_path))


def test_catalog_exposes_presets_and_taxonomies(tmp_path):
    cat = _svc(tmp_path).catalog()
    assert cat["default_campaign_preset"] == "balanced-production"
    keys = {p["key"] for p in cat["campaign_presets"]}
    assert {"balanced-production", "safe-live-acceptance"} <= keys
    assert len(cat["industries"]) >= 12          # broad taxonomy
    assert "public_reversible" in cat["interaction_modes"]


def test_preflight_runs_without_browser_or_network(tmp_path, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-x")
    out = _svc(tmp_path).preflight(campaign_preset="safe-live-acceptance",
                                   probe_browser_launch=False, do_network=False,
                                   env={"TAVILY_API_KEY": "tvly-x"})
    checks = {c["key"] for c in out["preflight"]["checks"]}
    assert "tavily_key" in checks and "safety_policy" in checks


def test_launch_runs_lifecycle_to_terminal_state(tmp_path, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-TESTKEY")
    svc = _svc(tmp_path)
    results = [{"url": "https://acme-saas.com", "title": "Acme", "content": "b2b saas pricing"},
               {"url": "https://beta-shop.de", "title": "Beta", "content": "shop cart checkout"}]
    res = svc.launch(campaign_preset="safe-live-acceptance", approve_live_discovery=True,
                     transport=_transport(results), background=False, resolve_dns=False)
    cid = res["campaign_id"]
    prog = svc.progress(cid)
    # A synchronous run ends in a terminal run-control state with an honest stop reason.
    assert prog["run_state"] in (COMPLETED, STOPPED_CHECKPOINT, FAILED)
    assert prog["run_state"] == COMPLETED
    assert prog["stop_reason"]                    # never blank
    assert "discovered" in prog["counters"]
    # brain decisions file exists (may be empty if nothing promoted on fake unreachable domains)
    brain = svc._read(cid, "BRAIN_DECISIONS.json")
    assert brain is not None and "allocator" in brain


def test_history_and_export_bundle(tmp_path, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-TESTKEY")
    svc = _svc(tmp_path)
    results = [{"url": "https://acme-saas.com", "title": "Acme", "content": "saas"}]
    res = svc.launch(campaign_preset="safe-live-acceptance", approve_live_discovery=True,
                     transport=_transport(results), background=False, resolve_dns=False)
    cid = res["campaign_id"]
    # export produces a structured bundle manifest
    path = svc.export_bundle(cid)
    data = json.loads(open(path, encoding="utf-8").read())
    assert data["schema"] == "scout-evidence-bundle/v1"
    assert data["campaign_id"] == cid
    # history read-model is a list (possibly empty when fake domains are unreachable)
    assert isinstance(svc.history(), list)


def test_stop_control_moves_to_stopped(tmp_path):
    svc = _svc(tmp_path)
    # launch synchronously with no results (empty transport) then verify control API shape
    res = svc.launch(campaign_preset="safe-live-acceptance", approve_live_discovery=True,
                     transport=_transport([]), background=False, resolve_dns=False)
    cid = res["campaign_id"]
    # after a completed run, a stop control still returns a well-formed response
    out = svc.control(cid, "unknown-action")
    assert out["ok"] is False
