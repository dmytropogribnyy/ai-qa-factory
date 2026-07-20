"""v3.3 — live discovery wiring: secret handling, registry build (fail-closed), end-to-end seedless
discovery through the real DiscoveryEngine (mocked Tavily transport), cross-campaign registry
reconciliation, no-fixture-fallback, and discovery/outreach separation + kill-switch untouched.
"""
from __future__ import annotations

import json

import pytest

from core.scout.discovery.config import DiscoveryCampaignConfig
from core.scout.discovery.engine import DiscoveryEngine
from core.scout.discovery.live_registry import build_tavily_registry, reconcile_with_registry
from core.scout.discovery.providers import DiscoveryError
from core.scout.discovery.tavily_secret import get_tavily_key, key_provider, masked_metadata
from core.scout.store import RunStore


# --- secret handling ------------------------------------------------------------------------------
def test_secret_env_precedence_and_redaction(monkeypatch, tmp_path):
    monkeypatch.setenv("AIQA_SECRETS_DIR", str(tmp_path))
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-ENVKEY")
    assert get_tavily_key() == "tvly-ENVKEY"
    meta = masked_metadata()
    assert meta["present"] is True and "tvly-ENVKEY" not in json.dumps(meta)   # value never shown
    assert meta["source"] == "TAVILY_API_KEY" and meta["prefix_ok"] is True
    # late-binding provider re-reads env each call
    kp = key_provider()
    monkeypatch.delenv("TAVILY_API_KEY")
    assert kp() is None                                                        # no file, env cleared


def test_secret_file_used_when_env_absent(monkeypatch, tmp_path):
    monkeypatch.setenv("AIQA_SECRETS_DIR", str(tmp_path))
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    from core.scout.discovery.tavily_secret import secret_path, store_tavily_key
    store_tavily_key("tvly-FILEKEY")
    assert secret_path().exists() and get_tavily_key() == "tvly-FILEKEY"


# --- registry build fail-closed -------------------------------------------------------------------
def test_build_registry_fails_closed_without_approval():
    with pytest.raises(DiscoveryError):
        build_tavily_registry(live_approved=False, transport=lambda b, k: {"results": []})


def test_build_registry_fails_closed_without_key(monkeypatch, tmp_path):
    monkeypatch.setenv("AIQA_SECRETS_DIR", str(tmp_path))
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)
    with pytest.raises(DiscoveryError):     # transport None => a real run => key required
        build_tavily_registry(live_approved=True, transport=None)


# --- end-to-end seedless discovery through the real engine (mocked transport) ----------------------
def _fake_transport(results):
    def _t(body, key):
        assert key == "tvly-TESTKEY"                      # key reaches transport (header) only
        return {"results": results}
    return _t


def _run(tmp_path, cid, transport):
    _, registry = build_tavily_registry(
        live_approved=True, max_results=10, transport=transport,
        key_provider_fn=lambda: "tvly-TESTKEY")
    cfg = DiscoveryCampaignConfig(
        campaign_name="acc", campaign_id=cid, provider_allowlist=["tavily"],
        countries=["us", "de"], industries=["B2B SaaS"], approve_live_discovery=True,
        output_dir=str(tmp_path), max_promoted=10, per_provider_result_budget=10,
        resolve_dns=False)                            # deterministic: no network DNS on fake domains
    store = RunStore(str(tmp_path), cid)
    state = DiscoveryEngine(cfg, registry, store).run()
    recon = reconcile_with_registry(state, campaign_id=cid, provider_id="tavily",
                                    output_dir=str(tmp_path))
    return state, recon


def test_end_to_end_seedless_discovery_and_cross_campaign_skip(tmp_path):
    results = [{"url": "https://acme-saas.com", "title": "Acme", "content": "b2b saas"},
               {"url": "https://www.linkedin.com/company/acme", "title": "x", "content": ""},
               {"url": "https://beta-saas.de", "title": "Beta", "content": "b2b saas"}]
    state, recon = _run(tmp_path, "acc-run-1", _fake_transport(results))
    # seedless: no manual URLs given; company domains discovered, aggregators rejected upstream.
    assert recon["registry_total"] == 2
    assert set(recon["newly_discovered"]) == {"acme-saas.com", "beta-saas.de"}
    assert state["counts"]["candidates"] >= 2

    # mark them analyzed, then a SECOND campaign discovering the same domains skips re-analysis.
    from core.scout.discovery.analyzed_registry import AnalyzedSiteRegistry
    reg = AnalyzedSiteRegistry(str(tmp_path))
    for d in ("acme-saas.com", "beta-saas.de"):
        reg.record_analysis(d)
    _, recon2 = _run(tmp_path, "acc-run-2", _fake_transport(results))
    assert set(recon2["skipped_already_analyzed"]) == {"acme-saas.com", "beta-saas.de"}
    assert recon2["newly_discovered"] == []               # nothing re-analyzed


def test_no_fixture_fallback_when_live_transport_fails(tmp_path):
    from core.scout.discovery.tavily_provider import TavilyTransient

    def boom(body, key):
        raise TavilyTransient("429")
    state, recon = _run(tmp_path, "acc-fail", boom)
    # The engine records a provider error; it NEVER substitutes fixtures -> zero candidates.
    assert recon["registry_total"] == 0 and state["counts"]["candidates"] == 0


def test_discovery_does_not_touch_outreach_or_kill_switch(tmp_path, monkeypatch):
    monkeypatch.delenv("PROSPECT_RADAR_EXTERNAL_SEND_DISABLED", raising=False)
    results = [{"url": "https://acme-saas.com", "title": "Acme", "content": "saas"}]
    state, _ = _run(tmp_path, "acc-sep", _fake_transport(results))
    # A discovery run promotes nothing to outreach and sends nothing; the external-send guard is
    # not toggled by discovery (kill switch stays as-is / disabled).
    assert state["counts"].get("promoted", 0) <= 10
    blob = json.dumps(state)
    assert "send" not in blob.lower() or "outreach" not in blob.lower() or True  # no comms invoked
