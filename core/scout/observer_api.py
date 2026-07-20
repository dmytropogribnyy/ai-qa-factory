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


# A campaign id must be a single safe path segment (no separators/traversal). Real ids are
# generated as campaign-<slug>-<stamp>-<hex>, so this never rejects a legitimate id.
_VALID_CAMPAIGN_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class ObserverAPI:
    def __init__(self, output_dir: str = "outputs") -> None:
        self.output_dir = output_dir
        self.svc = CampaignService(output_dir)
        self._root = Path(output_dir).resolve()
        self._evidence_root = (self._root / "scout").resolve()

    def _cid(self, campaign_id: str) -> str:
        """Validate a campaign id used as a path segment (fail closed on traversal/separators).
        This is the authoritative boundary check for every campaign-scoped tool (MCP + direct)."""
        cid = str(campaign_id or "")
        if not _VALID_CAMPAIGN_ID.match(cid):
            raise ObserverError("invalid campaign_id (must match [A-Za-z0-9._-]{1,128})")
        return cid

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
        campaign_id = self._cid(campaign_id)
        return redact({"api_version": OBSERVER_API_VERSION, **self.svc.progress(campaign_id)})

    def get_run_progress(self, campaign_id: str) -> Dict[str, Any]:
        campaign_id = self._cid(campaign_id)
        return redact(self.svc.progress(campaign_id))

    def get_run_stop_reason(self, campaign_id: str) -> Dict[str, Any]:
        campaign_id = self._cid(campaign_id)
        p = self.svc.progress(campaign_id)
        return {"campaign_id": campaign_id, "run_state": p["run_state"],
                "stop_reason": p["stop_reason"]}

    _MAX_EVENTS = 200

    def _events(self, campaign_id: str) -> List[Dict[str, Any]]:
        try:
            from core.scout.store import RunStore
            return RunStore(self.output_dir, campaign_id).read_events()
        except Exception:
            return []

    def get_updates_since(self, campaign_id: str, cursor: str = "") -> Dict[str, Any]:
        """TRUE incremental event feed: returns only newly-persisted events after the cursor (an
        index into the append-only campaign event log), each with a stable event id, bounded and
        redacted. The new cursor is the caller's next starting index."""
        campaign_id = self._cid(campaign_id)
        events = self._events(campaign_id)
        try:
            start = max(0, int(cursor)) if cursor else 0
        except (TypeError, ValueError):
            start = 0
        window = events[start:start + self._MAX_EVENTS]
        out = []
        for i, ev in enumerate(window, start=start):
            out.append({"event_id": f"{campaign_id}#{i}", "at": ev.get("at"),
                        "event_type": ev.get("event"),
                        "target": ev.get("candidate") or ev.get("prospect") or "",
                        "reason": ev.get("reason", ""),
                        "detail": redact({k: v for k, v in ev.items()
                                          if k not in ("at", "event")})})
        return {"api_version": OBSERVER_API_VERSION, "campaign_id": campaign_id,
                "cursor": str(start + len(window)), "changed": bool(window),
                "count": len(window), "has_more": (start + len(window)) < len(events),
                "events": out}

    def get_activity_log(self, campaign_id: str, *, limit: int = 200, offset: int = 0) -> Dict[str, Any]:
        campaign_id = self._cid(campaign_id)
        events = self._events(campaign_id)
        page = events[offset:offset + max(1, min(limit, self._MAX_EVENTS))]
        return {"api_version": OBSERVER_API_VERSION, "campaign_id": campaign_id,
                "total": len(events), "offset": offset, "activity": redact(page)}

    # -- findings + evidence (campaign-scoped, path-confined) -------------------------------------
    def _promoted_runs(self, campaign_id: str) -> List[str]:
        state = self.svc._discovery_state(campaign_id) or {}
        return [c.get("promoted_scout_run") for c in state.get("candidates", [])
                if c.get("promoted_scout_run")]

    def list_findings(self, campaign_id: str, *, limit: int = 100, offset: int = 0) -> Dict[str, Any]:
        campaign_id = self._cid(campaign_id)
        from core.scout.priority import load_verified_findings
        from core.scout.store import RunStore
        rows: List[Dict[str, Any]] = []
        for run_id in self._promoted_runs(campaign_id):
            try:
                for f in load_verified_findings(RunStore(self.output_dir, run_id)):
                    rows.append({"finding_id": f.get("finding_id"), "scout_run": run_id,
                                 "url": f.get("url"), "severity": f.get("severity"),
                                 "category": f.get("category"), "title": f.get("title")})
            except Exception:
                continue
        total = len(rows)
        page = rows[offset:offset + max(1, min(limit, 500))]
        return {"api_version": OBSERVER_API_VERSION, "campaign_id": campaign_id, "total": total,
                "offset": offset, "findings": redact(page)}

    def get_finding(self, campaign_id: str, finding_id: str) -> Dict[str, Any]:
        campaign_id = self._cid(campaign_id)
        from core.scout.priority import load_verified_findings
        from core.scout.store import RunStore
        for run_id in self._promoted_runs(campaign_id):
            try:
                for f in load_verified_findings(RunStore(self.output_dir, run_id)):
                    if f.get("finding_id") == finding_id:
                        return {"api_version": OBSERVER_API_VERSION, "finding": redact(f)}
            except Exception:
                continue
        return {"api_version": OBSERVER_API_VERSION, "error": "finding_not_found",
                "finding_id": finding_id}

    def get_evidence_manifest(self, campaign_id: str) -> Dict[str, Any]:
        """List evidence artifacts for a campaign as RELATIVE paths under the evidence root."""
        campaign_id = self._cid(campaign_id)
        items = []
        for run_id in self._promoted_runs(campaign_id):
            run_dir = (self._evidence_root.parent / run_id)
            if not run_dir.exists():
                continue
            for f in run_dir.rglob("*.json"):
                try:
                    rel = f.resolve().relative_to(self._root)
                except ValueError:
                    continue
                items.append({"ref": str(rel).replace("\\", "/"), "bytes": f.stat().st_size})
        return {"api_version": OBSERVER_API_VERSION, "campaign_id": campaign_id,
                "count": len(items), "evidence": items[:500]}

    def get_evidence_item(self, ref: str) -> Dict[str, Any]:
        """Return bounded metadata + integrity hash for one confined evidence artifact (never raw
        arbitrary bytes; refuses any path escaping the output root)."""
        p = (self._root / ref).resolve()
        try:
            p.relative_to(self._root)
        except ValueError:
            raise ObserverError("path escapes the output root") from None
        if not p.is_file():
            return {"api_version": OBSERVER_API_VERSION, "error": "not_found", "ref": ref}
        data = p.read_bytes()[:200_000]
        return {"api_version": OBSERVER_API_VERSION, "ref": ref, "bytes": p.stat().st_size,
                "sha256": hashlib.sha256(data).hexdigest(), "truncated": p.stat().st_size > 200_000}

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
        campaign_id = self._cid(campaign_id)
        prog = redact(self.svc.progress(campaign_id))
        brain = redact(self.svc._read(campaign_id, "BRAIN_DECISIONS.json") or {})
        # Campaign-SCOPED targets only (no cross-campaign leakage into this campaign's bundle).
        targets = redact([t for t in self.svc.history()
                          if campaign_id in (t.get("campaign_ids") or [])])
        payload = {
            "schema": "ai-review-bundle/v1", "api_version": OBSERVER_API_VERSION,
            "exported_at": _now(), "campaign_id": campaign_id,
            "progress": prog, "brain_decisions": brain, "targets": targets,
            "findings": self.list_findings(campaign_id).get("findings", []),
            "evidence_manifest": self.get_evidence_manifest(campaign_id).get("evidence", []),
            "release_readiness": self.get_release_readiness(),
        }
        body = json.dumps(payload, indent=2, sort_keys=True)
        integrity = hashlib.sha256(body.encode("utf-8")).hexdigest()
        payload["integrity_sha256"] = integrity
        out = (self._root / "scout" / "_bundles" / campaign_id).resolve()
        # Defense in depth: refuse to create/write anywhere outside the evidence root even if id
        # validation were ever bypassed.
        try:
            out.relative_to(self._evidence_root)
        except ValueError:
            raise ObserverError("bundle path escapes the evidence root") from None
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
