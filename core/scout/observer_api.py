"""Project Observer API (v3.3) — a versioned, READ-ONLY facade over the SAME persisted
source-of-truth the Dashboard uses (no second data model, no duplicated logic).

An external AI assistant (or the MCP adapter, or the Dashboard) can inspect campaigns, targets,
Scout Brain decisions, scores, stop reasons, and storage — plus export a self-contained **AI Review
Bundle** (JSON + Markdown) for environments where MCP is not yet connected. Everything is bounded,
secret-redacted, and evidence-root path-confined. This module performs NO control actions.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.scout.campaign_service import CampaignService
from core.scout.discovery.analyzed_registry import AnalyzedSiteRegistry
from core.scout.preflight import run_preflight
from core.scout.presets import build_config

OBSERVER_API_VERSION = "observer/v1"

# Keys whose values are always redacted from any Observer payload (defense in depth).
_SECRET_KEY_RE = re.compile(
    r"(tavily|api[_-]?key|secret|token|password|cookie|authorization|credential|bearer)", re.I)
_SECRET_VALUE_RE = re.compile(r"tvly-[A-Za-z0-9._-]+")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def redact(obj: Any) -> Any:
    """Recursively redact secret-looking keys/values from any payload."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if isinstance(k, str) and _SECRET_KEY_RE.search(k):
                out[k] = "[redacted]"
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    if isinstance(obj, str):
        return _SECRET_VALUE_RE.sub("[redacted]", obj)
    return obj


class ObserverError(RuntimeError):
    pass


class ObserverAPI:
    def __init__(self, output_dir: str = "outputs") -> None:
        self.output_dir = output_dir
        self.svc = CampaignService(output_dir)
        self._root = Path(output_dir).resolve()
        self._evidence_root = (self._root / "scout").resolve()

    # -- path confinement ------------------------------------------------------------------------
    def _confine(self, rel_or_abs: str) -> Path:
        """Resolve a path and refuse anything escaping the evidence root."""
        p = (self._evidence_root / rel_or_abs).resolve() if not Path(rel_or_abs).is_absolute() \
            else Path(rel_or_abs).resolve()
        try:
            p.relative_to(self._evidence_root)
        except ValueError:
            raise ObserverError("path escapes the evidence root") from None
        return p

    # -- overview / readiness --------------------------------------------------------------------
    def get_project_overview(self) -> Dict[str, Any]:
        camps = self.list_campaigns(limit=1000)["campaigns"]
        reg = AnalyzedSiteRegistry(self.output_dir)
        return redact({
            "api_version": OBSERVER_API_VERSION, "at": _now(),
            "campaign_count": len(camps),
            "active_campaigns": [c["campaign_id"] for c in camps
                                 if c["run_state"] in ("discovering", "triaging", "analyzing",
                                                       "pausing", "paused")],
            "analyzed_sites": reg.counts(),
        })

    def get_system_readiness(self, *, deep: bool = False) -> Dict[str, Any]:
        cfg = build_config("safe-live-acceptance", "quick", provider_allowlist=["tavily"],
                           output_dir=self.output_dir)
        report = run_preflight(output_dir=self.output_dir, campaign_config=cfg,
                               probe_browser_launch=deep, do_network=deep)
        return redact({"api_version": OBSERVER_API_VERSION, "deep": deep,
                       "readiness": report.to_dict()})

    def get_release_readiness(self) -> Dict[str, Any]:
        return {"api_version": OBSERVER_API_VERSION,
                "deterministically_verified": True, "ci_verified": "see_pull_request_checks",
                "live_desktop_acceptance_required": True,
                "runbook": "docs/LIVE_SCOUT_ACCEPTANCE_V33.md"}

    def get_storage_status(self) -> Dict[str, Any]:
        total = 0
        count = 0
        if self._evidence_root.exists():
            for f in self._evidence_root.rglob("*"):
                if f.is_file():
                    count += 1
                    try:
                        total += f.stat().st_size
                    except OSError:
                        pass
        return {"api_version": OBSERVER_API_VERSION, "evidence_root": str(self._evidence_root),
                "file_count": count, "total_bytes": total}

    # -- campaigns -------------------------------------------------------------------------------
    def _campaign_ids(self) -> List[str]:
        rc_dir = self._root / "scout" / "_runcontrol"
        ids = sorted(p.stem for p in rc_dir.glob("*.json")) if rc_dir.exists() else []
        return ids

    def list_campaigns(self, *, limit: int = 50, offset: int = 0) -> Dict[str, Any]:
        ids = self._campaign_ids()
        page = ids[offset:offset + max(1, min(limit, 500))]
        rows = []
        for cid in page:
            prog = self.svc.progress(cid)
            rows.append({"campaign_id": cid, "run_state": prog["run_state"],
                         "stop_reason": prog["stop_reason"], "counters": prog["counters"]})
        return {"api_version": OBSERVER_API_VERSION, "total": len(ids), "offset": offset,
                "limit": limit, "campaigns": redact(rows)}

    def get_campaign(self, campaign_id: str) -> Dict[str, Any]:
        return redact({"api_version": OBSERVER_API_VERSION, **self.svc.progress(campaign_id)})

    def get_run_progress(self, campaign_id: str) -> Dict[str, Any]:
        return redact(self.svc.progress(campaign_id))

    def get_run_stop_reason(self, campaign_id: str) -> Dict[str, Any]:
        p = self.svc.progress(campaign_id)
        return {"campaign_id": campaign_id, "run_state": p["run_state"],
                "stop_reason": p["stop_reason"]}

    def get_updates_since(self, campaign_id: str, cursor: str = "") -> Dict[str, Any]:
        """Coarse incremental updates: returns the current snapshot + a stable content cursor only
        when it changed since the caller's cursor (else an empty delta)."""
        snap = self.svc.progress(campaign_id)
        digest = hashlib.sha256(json.dumps(snap, sort_keys=True, default=str)
                                .encode("utf-8")).hexdigest()[:16]
        if cursor == digest:
            return {"api_version": OBSERVER_API_VERSION, "cursor": digest, "changed": False,
                    "snapshot": None}
        return {"api_version": OBSERVER_API_VERSION, "cursor": digest, "changed": True,
                "snapshot": redact(snap)}

    # -- targets ---------------------------------------------------------------------------------
    def list_targets(self, *, filters: Optional[Dict[str, str]] = None, limit: int = 50,
                     offset: int = 0) -> Dict[str, Any]:
        rows = self.svc.history(filters=filters)
        total = len(rows)
        page = rows[offset:offset + max(1, min(limit, 500))]
        return {"api_version": OBSERVER_API_VERSION, "total": total, "offset": offset,
                "limit": limit, "targets": redact(page)}

    def get_target(self, domain: str) -> Dict[str, Any]:
        return redact({"api_version": OBSERVER_API_VERSION, **self.svc.target_detail(domain)})

    def get_target_test_plan(self, domain: str) -> Dict[str, Any]:
        det = self.svc.target_detail(domain)
        brain = det.get("brain") or {}
        return redact({"api_version": OBSERVER_API_VERSION, "domain": domain,
                       "plan": brain.get("plan"), "allocation": brain.get("allocation"),
                       "brain": brain.get("brain")})

    def get_target_decision_history(self, domain: str) -> Dict[str, Any]:
        det = self.svc.target_detail(domain)
        entry = det.get("entry") or {}
        return redact({"api_version": OBSERVER_API_VERSION, "domain": domain,
                       "campaign_ids": entry.get("campaign_ids", []),
                       "analysis_status": entry.get("analysis_status"),
                       "first_seen": entry.get("first_seen"),
                       "last_analysis_at": entry.get("last_analysis_at"),
                       "decision": det.get("brain")})

    # -- AI review bundle (MCP-independent fallback) ---------------------------------------------
    def export_ai_review_bundle(self, campaign_id: str) -> Dict[str, str]:
        """Write a self-contained JSON + Markdown review bundle with a schema + integrity manifest."""
        prog = redact(self.svc.progress(campaign_id))
        brain = redact(self.svc._read(campaign_id, "BRAIN_DECISIONS.json") or {})
        targets = redact(self.svc.history())
        payload = {
            "schema": "ai-review-bundle/v1", "api_version": OBSERVER_API_VERSION,
            "exported_at": _now(), "campaign_id": campaign_id,
            "progress": prog, "brain_decisions": brain, "targets": targets,
            "release_readiness": self.get_release_readiness(),
        }
        body = json.dumps(payload, indent=2, sort_keys=True)
        integrity = hashlib.sha256(body.encode("utf-8")).hexdigest()
        payload["integrity_sha256"] = integrity
        out = self._root / "scout" / "_bundles" / campaign_id
        out.mkdir(parents=True, exist_ok=True)
        json_path = out / "AI_REVIEW_BUNDLE.json"
        json_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        md_path = out / "AI_REVIEW_BUNDLE.md"
        md_path.write_text(self._bundle_markdown(campaign_id, prog, brain, targets, integrity),
                           encoding="utf-8")
        return {"json": str(json_path), "markdown": str(md_path), "integrity_sha256": integrity}

    @staticmethod
    def _bundle_markdown(cid, prog, brain, targets, integrity) -> str:
        c = prog.get("counters", {})
        lines = [f"# AI Review Bundle — {cid}", "", f"- Run state: **{prog.get('run_state')}**",
                 f"- Stop reason: **{prog.get('stop_reason') or '—'}**",
                 f"- Counters: discovered {c.get('discovered')}, eligible {c.get('eligible')}, "
                 f"QA analyzed {c.get('qa_analyzed')}, actionable {c.get('actionable')}, "
                 f"rejected {c.get('rejected')}, failed {c.get('failed')}", "",
                 "## Adaptive decisions", ""]
        for d in (brain.get("decisions") or [])[:50]:
            b = d.get("brain", {})
            lines.append(f"- **{d.get('domain')}** — priority {d.get('priority')}, depth "
                         f"{(d.get('allocation') or {}).get('depth')}, {b.get('business_model','')}")
        lines += ["", f"## Targets ({len(targets)})", ""]
        for t in targets[:100]:
            lines.append(f"- {t.get('domain')} — {t.get('analysis_status')}")
        lines += ["", f"_integrity sha256: {integrity}_"]
        return "\n".join(lines)
