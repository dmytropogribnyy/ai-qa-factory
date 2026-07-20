"""Campaign orchestration service (v3.3) — the Dashboard's Scout API.

Ties the operator workflow together over the EXISTING engine: presets -> bounded config ->
readiness preflight -> DiscoveryEngine run (discovery/triage/promotion/ScoutEngine QA) wrapped in
the persisted run-control lifecycle, with the Scout Brain enriching each promoted target
(archetype understanding, adaptive depth, per-target plan, separate + combined scores) so the
Dashboard can show WHY. Reuses AnalyzedSiteRegistry for history and never creates a parallel
engine/store/provider. Live discovery stays operator-gated (approve_live_discovery + Tavily key).
"""
from __future__ import annotations

import json
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.scout.adaptive import AdaptiveAllocator, DiversityCaps, HardCeilings, OutcomeTargets
from core.scout.discovery.analyzed_registry import AnalyzedSiteRegistry
from core.scout.discovery.engine import DiscoveryEngine
from core.scout.discovery.live_registry import build_tavily_registry
from core.scout.discovery.tavily_secret import key_provider
from core.scout.presets import (
    CAMPAIGN_PRESETS,
    DEFAULT_CAMPAIGN_PRESET,
    INDUSTRY_TAXONOMY,
    SESSION_PRESETS,
    SUPPORTED_SITE_TYPES,
    TARGET_TYPE_TAXONOMY,
    build_config,
)
from core.scout.preflight import run_preflight
from core.scout.priority import classify, load_verified_findings
from core.scout.run_control import (
    ANALYZING,
    TRIAGING,
    CampaignRunControl,
    Checkpoint,
)
from core.scout.scout_brain import (
    brain_summary,
    evidence_confidence,
    safety_confidence,
    understand_target,
)
from core.scout.store import RunStore
from core.scout.target_planner import plan_target
from core.scout.verticals import profile_for_industry


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CampaignService:
    def __init__(self, output_dir: str = "outputs") -> None:
        self.output_dir = output_dir

    # -- form catalog ----------------------------------------------------------------------------
    def catalog(self) -> Dict[str, Any]:
        """Everything the campaign form needs (presets, sessions, taxonomies) — data only."""
        return {
            "default_campaign_preset": DEFAULT_CAMPAIGN_PRESET,
            "campaign_presets": [
                {"key": p.key, "label": p.label, "session_preset": p.session_preset,
                 "strategy": p.strategy, "countries": list(p.countries),
                 "site_types": list(p.site_types), "industries": list(p.industries),
                 "min_commercial_threshold": p.min_commercial_threshold,
                 "schedule_mode": p.schedule_mode, "schedule_enabled": p.schedule_enabled,
                 "is_smoke": p.is_smoke, "outcome_targets": dict(p.outcome_targets),
                 "diversity_caps": dict(p.diversity_caps)}
                for p in CAMPAIGN_PRESETS.values()
            ],
            "session_presets": [
                {"key": s.key, "label": s.label, "actionable_target": s.actionable_target,
                 "max_discovered": s.max_discovered, "max_qa_analyzed": s.max_qa_analyzed,
                 "max_pages_per_site": s.max_pages_per_site,
                 "max_duration_min": s.max_duration_s // 60}
                for s in SESSION_PRESETS.values()
            ],
            "site_types": list(SUPPORTED_SITE_TYPES),
            "industries": list(INDUSTRY_TAXONOMY),
            "target_types": list(TARGET_TYPE_TAXONOMY),
            "strategies": ["conservative", "balanced", "opportunity"],
            "country_confidence_levels": ["verified", "probable", "unverified"],
            "interaction_modes": ["observe_only", "public_passive", "public_reversible",
                                  "approved_test_account"],
        }

    # -- preflight -------------------------------------------------------------------------------
    def preflight(self, *, campaign_preset: str = DEFAULT_CAMPAIGN_PRESET,
                  session_preset: Optional[str] = None, overrides: Optional[Dict] = None,
                  probe_browser_launch: bool = True, do_network: bool = True,
                  env: Optional[Dict[str, str]] = None) -> Dict[str, Any]:
        cfg = build_config(campaign_preset, session_preset, provider_allowlist=["tavily"],
                           output_dir=self.output_dir, overrides=overrides)
        report = run_preflight(output_dir=self.output_dir, campaign_config=cfg,
                               probe_browser_launch=probe_browser_launch, do_network=do_network,
                               env=env)
        return {"campaign_preset": campaign_preset, "preflight": report.to_dict()}

    # -- launch ----------------------------------------------------------------------------------
    def launch(self, *, campaign_preset: str = DEFAULT_CAMPAIGN_PRESET,
               session_preset: Optional[str] = None, overrides: Optional[Dict] = None,
               approve_live_discovery: bool = False, transport: Optional[Callable] = None,
               background: bool = True, campaign_name: Optional[str] = None,
               resolve_dns: bool = True) -> Dict[str, Any]:
        """Build a bounded config and run the DiscoveryEngine inside the run-control lifecycle.

        `transport` (test) or the live Tavily key (production) drive the provider. Pause/stop are
        honoured cooperatively at engine event boundaries. Live discovery requires
        approve_live_discovery=True AND a Tavily key."""
        # browser_mode is operator-selectable: "static" (default, no browser) or "playwright"
        # (Deep capture — real screenshots/evidence). Unknown values fail closed to static.
        _ov = dict(overrides or {})
        bmode = str(_ov.pop("browser_mode", "static")).lower()
        if bmode not in ("static", "playwright"):
            bmode = "static"
        cfg = build_config(campaign_preset, session_preset, provider_allowlist=["tavily"],
                           output_dir=self.output_dir, approve_live_discovery=approve_live_discovery,
                           overrides={**_ov, "resolve_dns": resolve_dns},
                           browser_mode=bmode, campaign_name=campaign_name)
        rc = CampaignRunControl(cfg.campaign_id, self.output_dir)
        rc.run_now()                                   # QUEUED -> DISCOVERING (no-overlap guarded)

        def _run() -> None:
            try:
                _, registry = build_tavily_registry(
                    live_approved=True, max_results=cfg.per_provider_result_budget,
                    transport=transport, key_provider_fn=key_provider())
                store = RunStore(self.output_dir, cfg.campaign_id)

                def progress_cb(event: Dict) -> None:
                    # Cooperative pause/stop at event boundaries (finish current op, start no new).
                    rc.reload()                         # pick up a control set by another request
                    if rc.should_stop():
                        raise _StopRequested()
                    if rc.should_pause():
                        rc.enter_paused(Checkpoint(current_company=str(event.get("candidate", ""))))
                        rc.wait_until_resumed()
                    rc.heartbeat()

                rc.advance(TRIAGING)
                rc.advance(ANALYZING)
                state = DiscoveryEngine(cfg, registry, store, progress=progress_cb).run()
                self._persist_brain(cfg, state)
                rc.complete(state.get("stop_reason", "completed"))
            except _StopRequested:
                rc.stop_and_save(Checkpoint())
            except Exception as exc:                   # honest failure, never a fake success
                rc.fail(f"{type(exc).__name__}: {str(exc)[:160]}")

        if background:
            threading.Thread(target=_run, name=f"scout-{cfg.campaign_id}", daemon=True).start()
        else:
            _run()
        return {"campaign_id": cfg.campaign_id, "state": rc.state.state}

    # -- brain enrichment (persisted decision trail) --------------------------------------------
    def _persist_brain(self, cfg, state: Dict[str, Any]) -> None:
        """Attach an explainable brain summary + Target Test Plan per promoted candidate."""
        alloc = AdaptiveAllocator(
            strategy=cfg.strategy,
            ceilings=HardCeilings(max_browser_tested=cfg.max_browser_tested,
                                  max_actionable=cfg.actionable_target),
            outcomes=OutcomeTargets(**{k: v for k, v in (cfg.outcome_targets or {}).items()
                                       if k in OutcomeTargets().__dict__}),
            diversity=DiversityCaps(**{k: v for k, v in (cfg.diversity_caps or {}).items()
                                       if k in DiversityCaps().__dict__}))
        decisions: List[Dict[str, Any]] = []
        for cand in state.get("candidates", []):
            if cand.get("promotion_decision") != "promoted":
                continue
            industry = cand.get("industry_hint") or (cfg.industries[0] if cfg.industries else "")
            profile = profile_for_industry(industry)
            commercial = int(cand.get("commercial_score", 0))
            dims = {d.get("name"): d.get("value")
                    for d in (cand.get("commercial_scorecard", {}) or {}).get("dimensions", [])}
            qa_risk = int(dims.get("audit_opportunity", 40) or 40)
            dec = alloc.decide(domain=cand.get("registrable_domain", ""),
                               commercial_score=commercial, qa_risk=qa_risk, safety_ok=True,
                               country=cand.get("country_hint", ""), industry=industry,
                               target_type=profile.site_type)
            understanding = understand_target(signals={
                "title": cand.get("business_name", ""),
                "markers": cand.get("reason_codes", [])})
            findings = self._load_findings(cand.get("promoted_scout_run", ""))
            prio = classify(commercial, findings)
            ev_conf = evidence_confidence(findings)
            saf_conf = safety_confidence(cleanup_verified=True, crossed_boundary=False,
                                         client_safe_capable=True)
            summary = brain_summary(understanding=understanding, commercial=commercial,
                                    qa_value=prio.qa_value, evidence_conf=ev_conf,
                                    safety_conf=saf_conf)
            plan = plan_target(domain=cand.get("registrable_domain", ""), profile=profile,
                               depth=dec.depth, max_target_duration_s=180)
            alloc.record(dec, country=cand.get("country_hint", ""), industry=industry,
                         target_type=profile.site_type, actionable=(prio.priority == "A"))
            decisions.append({"domain": cand.get("registrable_domain", ""),
                              "priority": prio.priority, "allocation": dec.to_dict(),
                              "brain": summary, "plan": plan.to_dict(),
                              "scout_run": cand.get("promoted_scout_run", "")})
        self._write(cfg.campaign_id, "BRAIN_DECISIONS.json",
                    {"campaign_id": cfg.campaign_id, "at": _now(),
                     "allocator": alloc.snapshot(), "decisions": decisions})

    def _load_findings(self, scout_run_id: str) -> List[Dict[str, Any]]:
        if not scout_run_id:
            return []
        try:
            return load_verified_findings(RunStore(self.output_dir, scout_run_id))
        except Exception:
            return []

    # -- progress / control ----------------------------------------------------------------------
    def progress(self, campaign_id: str) -> Dict[str, Any]:
        rc = CampaignRunControl(campaign_id, self.output_dir)
        state = self._read(campaign_id, "STATE.json") or self._discovery_state(campaign_id)
        counts = (state or {}).get("counts", {})
        brain = self._read(campaign_id, "BRAIN_DECISIONS.json") or {}
        return {
            "campaign_id": campaign_id,
            "run_state": rc.state.state,
            "stop_reason": rc.state.stop_reason or (state or {}).get("stop_reason", ""),
            "requested_control": rc.state.requested_control,
            "current_company": rc.state.checkpoint.current_company,
            "counters": {k: counts.get(k) for k in ("discovered", "eligible", "qa_analyzed",
                         "actionable", "already_analyzed", "rejected", "failed")},
            "budget": (state or {}).get("budget", {}),
            "allocation": brain.get("allocator", {}),
            "decisions": brain.get("decisions", []),
            "updated_at": rc.state.updated_at,
        }

    def control(self, campaign_id: str, action: str) -> Dict[str, Any]:
        rc = CampaignRunControl(campaign_id, self.output_dir)
        if action == "pause":
            rc.request_pause()
        elif action == "resume":
            rc.resume()
        elif action == "stop":
            rc.stop_and_save(Checkpoint())
        else:
            return {"ok": False, "error": f"unknown control action {action!r}"}
        return {"ok": True, "action": action, "run_state": rc.state.state}

    # -- history / target detail -----------------------------------------------------------------
    def history(self, *, filters: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        reg = AnalyzedSiteRegistry(self.output_dir)
        rows = [e.to_dict() for e in reg.all()]
        f = filters or {}
        text = (f.get("text") or "").lower()
        status = f.get("status") or ""
        since = (f.get("since") or "").strip()   # ISO lower bound (inclusive)
        until = (f.get("until") or "").strip()    # ISO upper bound (inclusive-ish)
        if text:
            rows = [r for r in rows if text in json.dumps(r).lower()]
        if status:
            rows = [r for r in rows if r.get("analysis_status") == status]
        if since:
            rows = [r for r in rows if str(r.get("last_analysis_at") or "") >= since]
        if until:
            rows = [r for r in rows if str(r.get("last_analysis_at") or "") <= until]
        return rows

    def target_detail(self, domain: str) -> Dict[str, Any]:
        reg = AnalyzedSiteRegistry(self.output_dir)
        entry = reg.get(domain)
        brain = self._brain_for_domain(domain)
        findings: List[Dict[str, Any]] = []
        contacts: List[str] = []
        media: List[str] = []                 # rel paths under the run, servable via /scout/artifact
        network: Dict[str, Any] = {}          # already-captured Chrome/Playwright network evidence
        scout_run = (brain or {}).get("scout_run", "")
        if not scout_run:
            # Fall back to the most recent headed-replay run for this domain, so a replay's fresh
            # screenshots/evidence show up on the card even without a campaign brain decision.
            try:
                from core.scout.discovery.domain_intel import canonical_domain
                dom = canonical_domain(domain) or domain
                cands = sorted((Path(self.output_dir) / "scout").glob(f"replay-{dom}-*"),
                               reverse=True)
                if cands:
                    scout_run = cands[0].name
            except Exception:
                scout_run = scout_run
        _MEDIA_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".webm", ".mp4", ".har")
        if scout_run:
            from core.scout.outreach.qa_draft import extract_public_emails
            from core.scout.priority import load_verified_findings
            from core.scout.store import RunStore
            try:
                st = RunStore(self.output_dir, scout_run)
                findings = load_verified_findings(st)
                state = st.load_state() or {}
                for pid in list(state.get("prospects", {}).keys())[:1]:
                    obs = st.load_prospect_artifact(pid, "observation.json") or {}
                    contacts = extract_public_emails(obs, domain=domain)
                    network = {"status": obs.get("status"), "timing_ms": obs.get("timing_ms", {}),
                               "console_errors": obs.get("console_errors", [])[:10],
                               "failed_resources": obs.get("failed_resources", [])[:10],
                               "blocked_requests": obs.get("blocked_requests", [])[:10]}
                    try:
                        pdir = st.prospect_dir(pid)
                        media = [f"prospects/{pid}/{fp.name}" for fp in sorted(pdir.iterdir())
                                 if fp.is_file() and fp.suffix.lower() in _MEDIA_EXT]
                    except Exception:
                        media = []
            except Exception:
                findings, contacts = findings, contacts
        # Copy-only outreach draft from the target's problems (the system never sends it).
        # A cheap model (Haiku) polishes the prose only when LLM is live; else deterministic ($0).
        from core.scout.outreach.qa_draft import build_review_draft
        understanding = (brain or {}).get("brain", {})
        draft = build_review_draft(domain=domain,
                                   business_name=(entry.domain if entry else domain),
                                   understanding=understanding, findings=findings,
                                   contact=(contacts[0] if contacts else ""),
                                   router=self._llm_router())
        return {"domain": domain, "entry": entry.to_dict() if entry else None, "brain": brain,
                "scout_run": scout_run, "media": media, "network": network,
                "findings": [{"severity": f.get("severity"), "category": f.get("category"),
                              "title": f.get("title"), "business_impact": f.get("business_impact"),
                              "url": f.get("url"), "evidence_refs": f.get("evidence_refs", [])}
                             for f in findings],
                "contacts": contacts, "draft": draft}

    def _llm_router(self):
        """Lazy, cached LLMRouter. Returns None in mock mode so drafts stay deterministic ($0).

        Set LLM_MODE=live and MODEL_PROFILE=anthropic_budget (Haiku/Sonnet, no Opus) to enable
        the cheap outreach-prose polish. Any construction error degrades silently to deterministic."""
        if getattr(self, "_router_cached", "unset") != "unset":
            return self._router_cached
        router = None
        try:
            from core.config import get_settings
            settings = get_settings()
            if not settings.is_mock:
                from core.llm_router import LLMRouter
                router = LLMRouter(settings)
        except Exception:
            router = None
        self._router_cached = router
        return router

    def _brain_for_domain(self, domain: str) -> Optional[Dict[str, Any]]:
        base = Path(self.output_dir) / "scout" / "_campaigns"
        if not base.exists():
            return None
        for bp in base.glob("*/BRAIN_DECISIONS.json"):
            try:
                data = json.loads(bp.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for d in data.get("decisions", []):
                if d.get("domain") == domain:
                    return d
        return None

    # -- evidence export -------------------------------------------------------------------------
    def export_bundle(self, campaign_id: str) -> str:
        rc = CampaignRunControl(campaign_id, self.output_dir)
        manifest = {
            "schema": "scout-evidence-bundle/v1", "campaign_id": campaign_id, "exported_at": _now(),
            "run_state": rc.state.state, "stop_reason": rc.state.stop_reason,
            "discovery_state": self._discovery_state(campaign_id),
            "brain_decisions": self._read(campaign_id, "BRAIN_DECISIONS.json"),
        }
        out = Path(self.output_dir) / "scout" / "_bundles" / campaign_id
        out.mkdir(parents=True, exist_ok=True)
        path = out / "EVIDENCE_BUNDLE.json"
        path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
        return str(path)

    # -- storage helpers -------------------------------------------------------------------------
    def _campaign_dir(self, campaign_id: str) -> Path:
        d = Path(self.output_dir) / "scout" / "_campaigns" / campaign_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _write(self, campaign_id: str, name: str, obj: Any) -> None:
        p = self._campaign_dir(campaign_id) / name
        p.write_text(json.dumps(obj, indent=2, sort_keys=True), encoding="utf-8")

    def _read(self, campaign_id: str, name: str) -> Optional[Dict[str, Any]]:
        p = self._campaign_dir(campaign_id) / name
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None

    def _discovery_state(self, campaign_id: str) -> Optional[Dict[str, Any]]:
        try:
            return RunStore(self.output_dir, campaign_id).load_state()
        except Exception:
            return None


class _StopRequested(Exception):
    pass
