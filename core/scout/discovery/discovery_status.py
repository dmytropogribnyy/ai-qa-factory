"""Live-discovery status read-model (v3.3) — the minimum data the Dashboard needs to show live
discovery + the analyzed-site history, built entirely from persisted artifacts (no secrets).

Surfaces: provider, active/last campaign + filters, last query, status, discovered/deduplicated/
rejected counts, request/credit budget consumption, provider/rate-limit/auth errors, last-run time,
next-run time (when a schedule is registered), evidence links, the external-send kill-switch state,
and the analyzed-site history (bounded). Read-only; reused identically by CLI + Dashboard.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.scout.discovery.analyzed_registry import AnalyzedSiteRegistry


def _kill_switch_state(env: Optional[Dict[str, str]] = None) -> str:
    e = env if env is not None else os.environ
    return "disabled" if e.get("PROSPECT_RADAR_EXTERNAL_SEND_DISABLED") else "disabled (default)"


def _latest_live_campaign(output_dir: str) -> Optional[Dict[str, Any]]:
    base = Path(output_dir) / "scout"
    best: Optional[Path] = None
    best_mtime = -1.0
    if base.is_dir():
        for recon in base.glob("*/REGISTRY_RECONCILIATION.json"):
            m = recon.stat().st_mtime
            if m > best_mtime:
                best_mtime, best = m, recon
    if best is None:
        return None
    camp_dir = best.parent
    try:
        recon = json.loads(best.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        recon = {}
    state, cfg = {}, {}
    try:
        state = json.loads((camp_dir / "state.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    try:
        cfg = json.loads((camp_dir / "config.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    errors = [ev for ev in state.get("events", [])
              if str(ev.get("event", "")).endswith("error") or "budget_stop" in str(ev.get("event", ""))]
    counts = state.get("counts", {})
    return {
        "campaign_id": recon.get("campaign_id") or camp_dir.name,
        "provider": recon.get("provider", ""),
        "status": state.get("status", "unknown"),
        "filters": {k: cfg.get(k) for k in ("countries", "languages", "industries",
                                            "business_types", "keywords") if cfg.get(k)},
        "counts": {"discovered": counts.get("candidates", 0), "unique": counts.get("unique", 0),
                   "duplicates": counts.get("duplicates", 0), "promoted": counts.get("promoted", 0),
                   "newly_discovered": len(recon.get("newly_discovered", [])),
                   "already_analyzed_skipped": len(recon.get("skipped_already_analyzed", []))},
        "budget": state.get("budget", {}),
        "errors": errors[:10],
        "evidence": f"scout/{camp_dir.name}/",
        "last_run": state.get("finished_at") or state.get("started_at", ""),
    }


def discovery_status(output_dir: str = "outputs", *, env: Optional[Dict[str, str]] = None,
                     schedule_status: Optional[Dict[str, Any]] = None,
                     history_limit: int = 200) -> Dict[str, Any]:
    reg = AnalyzedSiteRegistry(output_dir)
    sites: List[Dict[str, Any]] = [
        {k: e.to_dict()[k] for k in ("domain", "analysis_status", "campaign_ids", "first_seen",
                                     "last_seen", "first_analysis_at", "last_analysis_at",
                                     "evidence_ref", "reason", "next_rescan_at")}
        for e in reg.all()[:history_limit]]
    last = _latest_live_campaign(output_dir)
    return {
        "schema": "discovery-status/v1",
        "kill_switch": _kill_switch_state(env),
        "provider": (last or {}).get("provider", "tavily"),
        "last_campaign": last,
        "next_run": (schedule_status or {}).get("next_run", ""),
        "schedule": schedule_status or {"enabled": False},
        "analyzed_counts": reg.counts(),
        "analyzed_sites": sites,
    }
