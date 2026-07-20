"""Read-only Observer MCP handlers (v3.3) — a THIN adapter over core.scout.observer_api.ObserverAPI.

Reused by the existing qa-factory MCP server (integrations/mcp/server.py); this is NOT a second
server or a second data model. Every tool is read-only, returns the same persisted source-of-truth
the Dashboard uses, is secret-redacted and evidence-root path-confined by ObserverAPI, and bounds
its output. The project/output root is configured SERVER-SIDE (env AIQA_OUTPUT_ROOT, default
"outputs") — it is never taken from an unrestricted arbitrary tool argument. No control/write tools
are exposed in this increment; errors are returned structured (no tracebacks, no secrets).
"""
from __future__ import annotations

import os
from typing import Any, Callable, Dict, List

from core.scout.observer_api import ObserverAPI, ObserverError


def _output_root() -> str:
    return os.environ.get("AIQA_OUTPUT_ROOT", "outputs")


def _api() -> ObserverAPI:
    return ObserverAPI(_output_root())


def _int(args: Dict[str, Any], key: str, default: int) -> int:
    try:
        return max(0, int(args.get(key, default)))
    except (TypeError, ValueError):
        return default


def _wrap(fn: Callable[[ObserverAPI, Dict[str, Any]], Any]) -> Callable[[Dict[str, Any]], Any]:
    def handler(args: Dict[str, Any]) -> Any:
        try:
            return fn(_api(), args or {})
        except ObserverError as exc:
            return {"status": "error", "error": "input_or_path_confinement", "message": str(exc)}
        except Exception as exc:                       # structured error, never a traceback/secret
            return {"status": "error", "message": f"{type(exc).__name__}: {str(exc)[:200]}"}
    return handler


# tool name -> handler
OBSERVER_HANDLERS: Dict[str, Callable[[Dict[str, Any]], Any]] = {
    "observer_get_project_overview": _wrap(lambda a, args: a.get_project_overview()),
    "observer_get_system_readiness": _wrap(lambda a, args: a.get_system_readiness(
        deep=bool(args.get("deep", False)))),
    "observer_get_release_readiness": _wrap(lambda a, args: a.get_release_readiness()),
    "observer_get_storage_status": _wrap(lambda a, args: a.get_storage_status()),
    "observer_list_campaigns": _wrap(lambda a, args: a.list_campaigns(
        limit=_int(args, "limit", 50), offset=_int(args, "offset", 0))),
    "observer_get_campaign": _wrap(lambda a, args: a.get_campaign(str(args.get("campaign_id", "")))),
    "observer_get_run_progress": _wrap(lambda a, args: a.get_run_progress(
        str(args.get("campaign_id", "")))),
    "observer_get_run_stop_reason": _wrap(lambda a, args: a.get_run_stop_reason(
        str(args.get("campaign_id", "")))),
    "observer_get_updates_since": _wrap(lambda a, args: a.get_updates_since(
        str(args.get("campaign_id", "")), str(args.get("cursor", "")))),
    "observer_list_targets": _wrap(lambda a, args: a.list_targets(
        filters={"text": str(args.get("text", "")), "status": str(args.get("status", ""))},
        limit=_int(args, "limit", 50), offset=_int(args, "offset", 0))),
    "observer_get_target": _wrap(lambda a, args: a.get_target(str(args.get("domain", "")))),
    "observer_get_target_test_plan": _wrap(lambda a, args: a.get_target_test_plan(
        str(args.get("domain", "")))),
    "observer_get_target_decision_history": _wrap(lambda a, args: a.get_target_decision_history(
        str(args.get("domain", "")))),
    "observer_list_findings": _wrap(lambda a, args: a.list_findings(
        str(args.get("campaign_id", "")), limit=_int(args, "limit", 100),
        offset=_int(args, "offset", 0))),
    "observer_get_finding": _wrap(lambda a, args: a.get_finding(
        str(args.get("campaign_id", "")), str(args.get("finding_id", "")))),
    "observer_get_evidence_manifest": _wrap(lambda a, args: a.get_evidence_manifest(
        str(args.get("campaign_id", "")))),
    "observer_get_evidence_item": _wrap(lambda a, args: a.get_evidence_item(str(args.get("ref", "")))),
    "observer_get_activity_log": _wrap(lambda a, args: a.get_activity_log(
        str(args.get("campaign_id", "")), limit=_int(args, "limit", 200),
        offset=_int(args, "offset", 0))),
    "observer_export_ai_review_bundle": _wrap(lambda a, args: a.export_ai_review_bundle(
        str(args.get("campaign_id", "")))),
}

OBSERVER_TOOL_NAMES: List[str] = sorted(OBSERVER_HANDLERS.keys())

_CAMPAIGN = {"campaign_id": {"type": "string", "description": "Campaign id"}}
_PAGE = {"limit": {"type": "integer"}, "offset": {"type": "integer"}}


def _schema(name: str, desc: str, props: Dict[str, Any], required=None) -> Dict[str, Any]:
    return {"name": name, "description": desc,
            "inputSchema": {"type": "object", "properties": props, "required": required or []}}


# Read-only tool schemas exposed to MCP clients.
OBSERVER_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    _schema("observer_get_project_overview", "Read-only project overview (campaigns + analyzed-site counts).", {}),
    _schema("observer_get_system_readiness", "Read-only readiness probes (installed != ready). deep=true launches Chromium + network.", {"deep": {"type": "boolean"}}),
    _schema("observer_get_release_readiness", "Read-only release-readiness summary.", {}),
    _schema("observer_get_storage_status", "Read-only evidence storage usage.", {}),
    _schema("observer_list_campaigns", "Read-only paginated list of campaigns with run state + counters.", _PAGE),
    _schema("observer_get_campaign", "Read-only campaign snapshot.", _CAMPAIGN, ["campaign_id"]),
    _schema("observer_get_run_progress", "Read-only run progress (state, counters, decisions).", _CAMPAIGN, ["campaign_id"]),
    _schema("observer_get_run_stop_reason", "Read-only campaign stop reason.", _CAMPAIGN, ["campaign_id"]),
    _schema("observer_get_updates_since", "Read-only incremental event feed since a cursor index.", {**_CAMPAIGN, "cursor": {"type": "string"}}, ["campaign_id"]),
    _schema("observer_list_targets", "Read-only paginated analyzed-site history (text/status filter).", {**_PAGE, "text": {"type": "string"}, "status": {"type": "string"}}),
    _schema("observer_get_target", "Read-only target detail + brain decision.", {"domain": {"type": "string"}}, ["domain"]),
    _schema("observer_get_target_test_plan", "Read-only generated Target Test Plan + allocation + brain.", {"domain": {"type": "string"}}, ["domain"]),
    _schema("observer_get_target_decision_history", "Read-only per-target decision/campaign history.", {"domain": {"type": "string"}}, ["domain"]),
    _schema("observer_list_findings", "Read-only paginated findings for a campaign.", {**_CAMPAIGN, **_PAGE}, ["campaign_id"]),
    _schema("observer_get_finding", "Read-only single finding.", {**_CAMPAIGN, "finding_id": {"type": "string"}}, ["campaign_id", "finding_id"]),
    _schema("observer_get_evidence_manifest", "Read-only campaign evidence manifest (relative refs).", _CAMPAIGN, ["campaign_id"]),
    _schema("observer_get_evidence_item", "Read-only bounded evidence metadata + sha256 for one confined ref.", {"ref": {"type": "string"}}, ["ref"]),
    _schema("observer_get_activity_log", "Read-only paginated campaign activity log.", {**_CAMPAIGN, **_PAGE}, ["campaign_id"]),
    _schema("observer_export_ai_review_bundle", "Write a campaign-scoped AI Review Bundle (JSON+MD) and return its paths + integrity hash.", _CAMPAIGN, ["campaign_id"]),
]
