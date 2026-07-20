"""v3.3 — Project Observer API (read-only). Deterministic (fake transport).

Proves Dashboard/service ↔ Observer source-of-truth parity, read-only behaviour, pagination,
secret redaction, cursor-based incremental updates, evidence-root path confinement, and the
MCP-independent AI Review Bundle (JSON + Markdown + integrity hash).
"""
from __future__ import annotations

import json

import pytest

from core.scout.campaign_service import CampaignService
from core.scout.observer_api import ObserverAPI, ObserverError, redact


def _transport(results):
    def _t(body, key):
        return {"results": results}
    return _t


def _launch(tmp_path, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-TESTKEY")
    svc = CampaignService(output_dir=str(tmp_path))
    res = svc.launch(campaign_preset="safe-live-acceptance", approve_live_discovery=True,
                     transport=_transport([{"url": "https://acme-saas.com", "title": "Acme",
                                            "content": "b2b saas pricing"}]),
                     background=False, resolve_dns=False)
    return svc, res["campaign_id"]


def test_source_of_truth_parity(tmp_path, monkeypatch):
    svc, cid = _launch(tmp_path, monkeypatch)
    obs = ObserverAPI(str(tmp_path))
    # Observer returns the SAME persisted state the service/Dashboard use.
    assert obs.get_run_progress(cid)["run_state"] == svc.progress(cid)["run_state"]
    assert obs.get_run_stop_reason(cid)["stop_reason"] == svc.progress(cid)["stop_reason"]
    assert cid in [c["campaign_id"] for c in obs.list_campaigns()["campaigns"]]


def test_redaction_never_leaks_secrets():
    payload = {"tavily_api_key": "tvly-abc123", "note": "key tvly-XYZ789 inside", "ok": 1,
               "nested": {"authorization": "Bearer zzz"}}
    r = redact(payload)
    assert r["tavily_api_key"] == "[redacted]"
    assert "tvly-XYZ789" not in json.dumps(r)
    assert r["nested"]["authorization"] == "[redacted]"
    assert r["ok"] == 1


def test_pagination_and_release_readiness(tmp_path, monkeypatch):
    _launch(tmp_path, monkeypatch)
    obs = ObserverAPI(str(tmp_path))
    page = obs.list_campaigns(limit=1, offset=0)
    assert page["limit"] == 1 and "total" in page and len(page["campaigns"]) <= 1
    rr = obs.get_release_readiness()
    assert rr["live_desktop_acceptance_required"] is True


def test_cursor_is_a_real_event_feed(tmp_path, monkeypatch):
    _, cid = _launch(tmp_path, monkeypatch)
    obs = ObserverAPI(str(tmp_path))
    first = obs.get_updates_since(cid, cursor="")
    # a completed discovery run persisted events; the feed returns them with stable ids
    assert first["changed"] is True and int(first["cursor"]) == first["count"] >= 1
    assert all("event_id" in e and "event_type" in e for e in first["events"])
    # asking again from the new cursor yields no new events (true incremental, not a snapshot hash)
    again = obs.get_updates_since(cid, cursor=first["cursor"])
    assert again["changed"] is False and again["count"] == 0


def test_ai_review_bundle_is_campaign_scoped_and_relative(tmp_path, monkeypatch):
    _, cid = _launch(tmp_path, monkeypatch)
    obs = ObserverAPI(str(tmp_path))
    out = obs.export_ai_review_bundle(cid)
    data = json.loads(open(out["json"], encoding="utf-8").read())
    # every target in the bundle belongs to THIS campaign (no cross-campaign leakage)
    for t in data["targets"]:
        assert cid in (t.get("campaign_ids") or [])
    # evidence refs are relative (no absolute drive/root path leakage)
    for e in data["evidence_manifest"]:
        assert not str(e["ref"]).startswith(str(tmp_path))
        assert ":" not in str(e["ref"])[:3]          # no 'C:' / 'D:' drive prefix


def test_evidence_item_refuses_traversal(tmp_path, monkeypatch):
    _, cid = _launch(tmp_path, monkeypatch)
    obs = ObserverAPI(str(tmp_path))
    with pytest.raises(ObserverError):
        obs.get_evidence_item("../../../etc/passwd")
    assert "findings" in obs.list_findings(cid)      # findings tool returns structured result


def test_path_confinement_rejects_escape(tmp_path):
    obs = ObserverAPI(str(tmp_path))
    with pytest.raises(ObserverError):
        obs._confine("../../etc/passwd")
    # a legitimate in-root path resolves
    ok = obs._confine("_bundles/x/AI_REVIEW_BUNDLE.json")
    assert "_bundles" in str(ok)


def test_ai_review_bundle_json_and_markdown(tmp_path, monkeypatch):
    _, cid = _launch(tmp_path, monkeypatch)
    obs = ObserverAPI(str(tmp_path))
    out = obs.export_ai_review_bundle(cid)
    data = json.loads(open(out["json"], encoding="utf-8").read())
    assert data["schema"] == "ai-review-bundle/v1"
    assert data["integrity_sha256"] == out["integrity_sha256"]
    assert "tvly-" not in json.dumps(data)                            # redacted
    md = open(out["markdown"], encoding="utf-8").read()
    assert md.startswith("# AI Review Bundle")
    assert "integrity sha256" in md
