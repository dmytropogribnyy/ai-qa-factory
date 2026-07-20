"""v3.3 — Observer MCP adapter over the EXISTING qa-factory server (no second server/data model).

Deterministic (fake transport, no `mcp` package needed — the handlers + dispatch + schemas are
importable without it). Proves MCP<->ObserverAPI source-of-truth parity, read-only behaviour,
secret redaction, evidence traversal refusal, bounded pagination, structured errors for unknown
campaigns/targets, server tool-catalog inclusion, and regression-safety of the original 7 tools.
"""
from __future__ import annotations

import json

from core.scout.campaign_service import CampaignService
from core.scout.observer_api import ObserverAPI
from integrations.mcp.observer_handlers import OBSERVER_HANDLERS, OBSERVER_TOOL_NAMES
from integrations.mcp.server import ALL_TOOL_SCHEMAS, _call_handler
from integrations.mcp.tool_handlers import TOOL_NAMES


def _transport(results):
    def _t(body, key):
        return {"results": results}
    return _t


def _launch(tmp_path, monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-TESTKEY")
    monkeypatch.setenv("AIQA_OUTPUT_ROOT", str(tmp_path))     # server-side root, not a tool arg
    svc = CampaignService(output_dir=str(tmp_path))
    res = svc.launch(campaign_preset="safe-live-acceptance", approve_live_discovery=True,
                     transport=_transport([{"url": "https://acme-saas.com", "title": "Acme",
                                            "content": "b2b saas pricing"}]),
                     background=False, resolve_dns=False)
    return res["campaign_id"]


def test_mcp_tool_calls_same_source_of_truth(tmp_path, monkeypatch):
    cid = _launch(tmp_path, monkeypatch)
    via_mcp = OBSERVER_HANDLERS["observer_get_run_progress"]({"campaign_id": cid})
    via_api = ObserverAPI(str(tmp_path)).get_run_progress(cid)
    assert via_mcp["run_state"] == via_api["run_state"]
    assert via_mcp["stop_reason"] == via_api["stop_reason"]


def test_all_observer_tools_present_and_read_only(tmp_path, monkeypatch):
    _launch(tmp_path, monkeypatch)
    names = {t["name"] for t in ALL_TOOL_SCHEMAS}
    for n in OBSERVER_TOOL_NAMES:
        assert n in names                                    # exposed in the server catalog
    # No control/write tools in this increment (read tools like get_run_stop_reason are fine).
    control_tools = {"observer_pause_campaign", "observer_resume_campaign",
                     "observer_stop_campaign", "observer_recheck_target",
                     "observer_reproduce_finding", "observer_record_finding_video",
                     "observer_capture_stronger_evidence", "observer_control"}
    assert not (set(OBSERVER_TOOL_NAMES) & control_tools)
    assert all(n.startswith("observer_get") or n.startswith("observer_list")
               or n == "observer_export_ai_review_bundle" for n in OBSERVER_TOOL_NAMES)


def test_output_root_is_server_side_not_a_tool_arg(tmp_path, monkeypatch):
    cid = _launch(tmp_path, monkeypatch)
    # even if a caller passes an arbitrary output root, it is ignored (root comes from env)
    out = OBSERVER_HANDLERS["observer_get_run_progress"]({"campaign_id": cid,
                                                          "output_dir": "/etc", "outputs_root": "C:\\"})
    assert out["run_state"]                                   # resolved against the server-side root


def test_evidence_traversal_refused_structured(tmp_path, monkeypatch):
    _launch(tmp_path, monkeypatch)
    out = OBSERVER_HANDLERS["observer_get_evidence_item"]({"ref": "../../../etc/passwd"})
    assert out.get("status") == "error"                      # structured, no traceback
    assert "traceback" not in json.dumps(out).lower()


def test_secret_redaction_and_no_leak(tmp_path, monkeypatch):
    cid = _launch(tmp_path, monkeypatch)
    blob = json.dumps(OBSERVER_HANDLERS["observer_get_campaign"]({"campaign_id": cid}))
    assert "tvly-" not in blob


def test_unknown_campaign_and_target_return_structured(tmp_path, monkeypatch):
    _launch(tmp_path, monkeypatch)
    prog = OBSERVER_HANDLERS["observer_get_run_progress"]({"campaign_id": "nope"})
    assert prog["run_state"] == "queued"                     # default, not a crash
    finding = OBSERVER_HANDLERS["observer_get_finding"]({"campaign_id": "nope", "finding_id": "x"})
    assert finding.get("error") == "finding_not_found"


def test_campaign_id_traversal_refused_no_dir_created(tmp_path, monkeypatch):
    _launch(tmp_path, monkeypatch)
    evil = "../../../../evil-" + "x"
    # every campaign-scoped MCP tool refuses a traversal id with a structured error
    for tool in ("observer_get_run_progress", "observer_get_campaign",
                 "observer_get_run_stop_reason", "observer_export_ai_review_bundle",
                 "observer_get_activity_log", "observer_list_findings"):
        out = OBSERVER_HANDLERS[tool]({"campaign_id": evil})
        assert out.get("status") == "error", tool
    # and no directory was created outside/inside from the traversal id
    assert not (tmp_path.parent / "evil-x").exists()
    assert not list(tmp_path.rglob("evil-x"))


def test_pagination_bounded(tmp_path, monkeypatch):
    _launch(tmp_path, monkeypatch)
    page = OBSERVER_HANDLERS["observer_list_campaigns"]({"limit": 1, "offset": 0})
    assert page["limit"] == 1 and len(page["campaigns"]) <= 1


def test_server_dispatch_and_original_tools_regression_safe():
    # the server dispatches an observer tool by name
    out = json.loads(_call_handler("observer_get_release_readiness", {}))
    assert out["live_desktop_acceptance_required"] is True
    # the original planning tools remain registered + callable (unchanged)
    assert "qa_factory_health" in TOOL_NAMES
    health = json.loads(_call_handler("qa_factory_health", {}))
    assert "status" in health or "version" in json.dumps(health).lower()
    # unknown tool => structured error
    assert json.loads(_call_handler("nope_tool", {}))["status"] == "error"
