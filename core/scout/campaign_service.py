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


# Known per-prospect structured evidence artifacts the engine may persist, with readable labels.
# target_detail() only exposes an entry when the file genuinely exists on disk (never a dead link).
_STRUCTURED_EVIDENCE_ARTIFACTS: tuple = (
    ("observation.json", "Page observation (redacted)"),
    ("evidence.json", "Sanitized fact sheet"),
    ("browser_trace.json", "Browser trace (redacted)"),
    ("evidence_manifest.json", "Evidence manifest + integrity hashes"),
    ("findings.json", "Findings (raw)"),
    ("scorecard.json", "Scorecard (raw)"),
    ("coverage.json", "Coverage (raw)"),
    ("reproduction.json", "Reproduction (raw)"),
    ("manual_action.json", "Manual-action record (raw)"),
)

# campaign_name values that are positive evidence of a manual/operator-initiated scan (single-URL
# CLI scan, the built-in demo, or a headed replay launched from the Dashboard). Any OTHER value —
# including an unknown/legacy/custom campaign_name — must NOT be guessed as "manual"; source_kind
# stays "" (genuinely unknown) so the UI never mislabels an unrecognised run type.
KNOWN_MANUAL_CAMPAIGN_NAMES = frozenset({"adhoc", "scout-demo", "headed-replay"})


def _project_target_finding(f: Dict[str, Any]) -> Dict[str, Any]:
    """Whitelist one finding for the /target card read-model.

    Carries ``confidence`` and ``reproduction_steps`` alongside the existing public fields so the
    page can render a confidence label and a one-line repro hint. Values are passed through as-is
    (never invented); the page layer is responsible for HTML-escaping, newline-collapsing, and the
    neutral placeholder for absent fields. This never widens beyond these sanitized public fields."""
    return {
        "severity": f.get("severity"),
        "category": f.get("category"),
        "title": f.get("title"),
        "business_impact": f.get("business_impact"),
        "url": f.get("url"),
        "evidence_refs": f.get("evidence_refs", []),
        "confidence": f.get("confidence"),
        "reproduction_steps": f.get("reproduction_steps", []),
    }


def _resolve_prospect(prospects: Dict[str, Any], want_domain: str) -> str:
    """Return the prospect_id in a run store whose canonical domain EXACTLY matches ``want_domain``.

    A manual / imported (curated-list) run may analyze many domains in one store, each registering the
    same run_id as its History campaign. The Target card for a domain must therefore bind to that
    domain's own prospect — never the first prospect and never the whole-run aggregate — or client
    evidence (findings, screenshots, network, a reproduction video) from one company leaks onto
    another's card. Empty string when no prospect canonicalises to the domain: the caller then fails
    honestly (``prospect_not_found``) rather than borrowing another prospect's evidence."""
    if not want_domain:
        return ""
    from core.scout.discovery.domain_intel import canonical_domain
    for pid, p in (prospects or {}).items():
        rec = p if isinstance(p, dict) else {}
        for key in ("url", "final_url", "domain"):  # url is authoritative (matches registration)
            val = rec.get(key)
            if val and canonical_domain(val) == want_domain:
                return pid
    return ""


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
        self._register_analyzed(cfg.campaign_id, [d.get("domain", "") for d in decisions])

    def _register_analyzed(self, campaign_id: str, domains: List[str]) -> List[str]:
        """P1 Golden-Path fix: every promoted/QA-analyzed domain must appear in the History registry
        (/scout/history reads AnalyzedSiteRegistry; target-detail findings come from the brain). Only
        promoted domains are passed here — rejected/failed/merely-discovered are never registered.
        Idempotent: a new domain is added; a re-analysis updates the timestamp + appends the campaign;
        no duplicate row is created. Never fails the run.

        Returns the domains actually PERSISTED — a suppressed write error is reflected by absence, so a
        caller (reconcile) can report attempted-vs-persisted honestly rather than assume success."""
        from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
        persisted: List[str] = []
        try:
            reg = AnalyzedSiteRegistry(self.output_dir)
        except Exception:  # noqa: BLE001 - registry open must never crash a completed campaign
            return persisted
        for dom in domains:
            d = str(dom or "").strip()
            if not d:
                continue
            try:
                reg.record_analysis(d, status=ANALYZED, evidence_ref=f"scout/{d}/qa",
                                    campaign_id=campaign_id)
                persisted.append(d)
            except Exception:  # noqa: BLE001 - one bad domain never blocks the rest; reported by absence
                continue
        return persisted

    def reconcile_history(self) -> Dict[str, Any]:
        """Self-heal History from persisted brain decisions. Campaigns that ran before the
        registration fix wrote ``BRAIN_DECISIONS.json`` but never registered their promoted domains,
        so those analyzed companies are invisible in ``/scout/history``. This replays every saved
        campaign's promoted domains through the SAME ``record_analysis`` path (never hardcoded);
        already-registered domains are updated in place, never duplicated. Safe to run repeatedly.
        Reports domains ACTUALLY persisted (not merely attempted) and counts malformed brain files it
        defensively skipped, so the result is honest even when a file or a write is bad."""
        base = Path(self.output_dir) / "scout" / "_campaigns"
        campaigns_scanned = 0
        registered: set = set()
        skipped_malformed = 0
        if base.is_dir():
            for brain_path in sorted(base.glob("*/BRAIN_DECISIONS.json")):
                try:
                    data = json.loads(brain_path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    skipped_malformed += 1                # unreadable / not JSON
                    continue
                decisions = data.get("decisions") if isinstance(data, dict) else None
                if not isinstance(decisions, list):
                    skipped_malformed += 1                # wrong shape (not a decisions list)
                    continue
                cid = str((data.get("campaign_id") if isinstance(data, dict) else "")
                          or brain_path.parent.name)
                domains = [str(d.get("domain", "")).strip()
                           for d in decisions if isinstance(d, dict)]
                domains = [d for d in domains if d]
                if domains:
                    persisted = self._register_analyzed(cid, domains)   # actually-persisted subset
                    campaigns_scanned += 1
                    registered.update(persisted)
        return {"campaigns_scanned": campaigns_scanned, "domains_registered": sorted(registered),
                "skipped_malformed": skipped_malformed}

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

    def target_detail(self, domain: str, run: str = "") -> Dict[str, Any]:
        """Resolve one target's operator detail. When ``run`` is given the EXACT run store is pinned
        (never a newer run, never the first prospect) so a run's Details link opens that run's own
        evidence; otherwise the brain/replay/registry chain resolves the most relevant run. Surfaces
        prospect_status / analysis_complete / manual_action so a MANUAL_ACTION_REQUIRED target renders
        an honest incomplete-analysis state instead of a false '0 defects' healthy conclusion."""
        reg = AnalyzedSiteRegistry(self.output_dir)
        entry = reg.get(domain)
        brain = self._brain_for_domain(domain)
        findings: List[Dict[str, Any]] = []
        contacts: List[str] = []
        media: List[str] = []                 # rel paths under the run, servable via /scout/artifact
        network: Dict[str, Any] = {}          # already-captured Chrome/Playwright network evidence
        reproduction: Optional[Dict[str, Any]] = None   # this domain's reproduction record, if any
        manual_action: Optional[Dict[str, Any]] = None  # persisted fail-closed record, if any
        prospect_id = ""                      # the exact prospect this card is bound to
        prospect_status = ""                  # DONE | MANUAL_ACTION_REQUIRED | FAILED | ...
        analysis_complete: Optional[bool] = None
        evidence_status = "not_scanned"       # ok | prospect_not_found | error | not_scanned
        # Truthful provenance + capture-policy fields (never invented — "" means genuinely unknown).
        source_kind = ""                      # discovery | curated | manual | "" (unknown)
        video_mode = ""                       # off | manual | qualified_auto | "" (unknown)
        # This prospect's persisted within-site coverage record (coverage.json), or None when a
        # historical/legacy run never wrote one — never fabricated (see coverage.py / engine.py).
        coverage: Optional[Dict[str, Any]] = None
        # Raw evidence files that ACTUALLY exist on disk for this prospect, so the UI never links to
        # an artifact that isn't there. Each entry is safely servable via /scout/artifact.
        evidence_files: List[Dict[str, str]] = []
        # Normalize the caller-supplied run EXACTLY ONCE: a whitespace-only value must behave like
        # "no run given" (registry resolution), never pin an empty/whitespace run id. Only
        # normalized_run drives exact-run pinning, fallback decisions, and the returned run identity.
        normalized_run = str(run or "").strip()
        # An explicit run pins that exact store; otherwise resolve via brain/replay/registry.
        scout_run = normalized_run or (brain or {}).get("scout_run", "")
        if not scout_run and not normalized_run:
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
        if not scout_run and not normalized_run and entry is not None:
            # A manual / imported run registers its run_id as the domain's campaign — resolve the
            # findings/evidence from that run store so an imported target opens a working detail card
            # (the discovery path uses the brain; this covers the manual Scout path).
            from core.scout.store import RunStore as _RunStore
            for cid in reversed(list(getattr(entry, "campaign_ids", []) or [])):
                try:
                    if _RunStore(self.output_dir, cid).exists():
                        scout_run = cid
                        break
                except Exception:
                    continue
        _MEDIA_EXT = (".png", ".jpg", ".jpeg", ".webp", ".gif", ".webm", ".mp4", ".har")
        if scout_run:
            from core.scout.discovery.domain_intel import canonical_domain
            from core.scout.outreach.qa_draft import extract_public_emails
            from core.scout.store import RunStore, StoreError
            try:
                st = RunStore(self.output_dir, scout_run)
                state = st.load_state() or {}
                # config.json is missing for some historical/legacy or test-built run stores; a
                # missing config must never abort prospect resolution — fall back to "unknown".
                try:
                    cfg = st.load_config() or {}
                except StoreError:
                    cfg = {}
                video_mode = str(cfg.get("video_mode") or "") or video_mode
                # Truthful source label: only assign a label when we have POSITIVE evidence of it. A
                # brain decision means adaptive discovery ran; a curated import and a known manual
                # campaign_name are each recognised explicitly. Any other/unknown campaign_name (a
                # legacy run, a future campaign type, a typo, etc.) must stay "" — never guessed —
                # so the UI falls back to the genuinely-unknown state instead of mislabelling it.
                run_campaign_name = str(cfg.get("campaign_name") or "")
                if brain:
                    source_kind = "discovery"
                elif run_campaign_name == "curated":
                    source_kind = "curated"
                elif run_campaign_name in KNOWN_MANUAL_CAMPAIGN_NAMES:
                    source_kind = "manual"
                else:
                    source_kind = ""
                want = canonical_domain(domain) or domain
                # Bind to THIS domain's prospect only. A shared multi-target run must never surface
                # another prospect's findings/screenshots/network/reproduction on this card, so we
                # resolve the exact prospect and load only its artifacts (no whole-run aggregate, no
                # first-prospect fallback).
                prospect_id = _resolve_prospect(state.get("prospects", {}), want)
                if prospect_id:
                    evidence_status = "ok"
                    pstate = (state.get("prospects", {}) or {}).get(prospect_id, {}) or {}
                    prospect_status = pstate.get("status", "")
                    # An EXPLICIT terminal non-DONE status means the analysis did not complete; an
                    # empty/unknown status (legacy seed data) keeps the prior "load findings" behaviour.
                    incomplete = prospect_status in ("MANUAL_ACTION_REQUIRED", "FAILED")
                    analysis_complete = (prospect_status == "DONE") if prospect_status else None
                    if incomplete:
                        analysis_complete = False
                    manual_action = st.load_prospect_artifact(prospect_id, "manual_action.json") or None
                    if manual_action is None and prospect_status == "MANUAL_ACTION_REQUIRED":
                        # Legacy/historical runs pre-date manual_action.json. Build a MINIMAL read
                        # model from persisted prospect state — surface pstate.reason EXACTLY and
                        # invent nothing (stage / stop_boundary / chromium_started / landing_loaded
                        # stay genuinely absent so the UI renders them as unavailable, not guessed).
                        legacy_reason = str(pstate.get("reason", "") or "").strip()
                        if legacy_reason:
                            manual_action = {"reason": legacy_reason}
                    # Within-site coverage (coverage.json) — exact-run/exact-prospect confined. A
                    # historical/legacy run (or one stopped before any page finished, e.g. manual
                    # action) never wrote one; that stays None — never a fabricated zero. A
                    # present-but-corrupted artifact (valid JSON that isn't a dict, e.g. a list or
                    # string) is also treated as unavailable rather than crashing the read model.
                    _raw_coverage = st.load_prospect_artifact(prospect_id, "coverage.json")
                    coverage = _raw_coverage if isinstance(_raw_coverage, dict) else None
                    obs = st.load_prospect_artifact(prospect_id, "observation.json") or {}
                    contacts = extract_public_emails(obs, domain=domain)
                    network = {"status": obs.get("status"), "timing_ms": obs.get("timing_ms", {}),
                               "console_errors": obs.get("console_errors", [])[:10],
                               "failed_resources": obs.get("failed_resources", [])[:10],
                               "blocked_requests": obs.get("blocked_requests", [])[:10],
                               # "" = not attempted (static backend / not deep-capture), "ok" = ran
                               # (violations may be empty), "unavailable" = deep-capture ran but axe
                               # itself could not run. Never invented — surfaced exactly as captured.
                               "axe_status": obs.get("axe_status", ""),
                               "axe_violations": (obs.get("axe_violations") or [])[:20],
                               "perf": obs.get("perf", {})}
                    # Confirmed findings exist only for a completed analysis. A manual/failed target
                    # has 0 confirmed findings — never surface a healthy conclusion for it.
                    if not incomplete:
                        fdata = st.load_prospect_artifact(prospect_id, "findings.json") or {}
                        findings = list(fdata.get("verified", []))
                        reproduction = st.load_prospect_artifact(prospect_id, "reproduction.json") or None
                    try:
                        pdir = st.prospect_dir(prospect_id)
                        media = [f"prospects/{prospect_id}/{fp.name}" for fp in sorted(pdir.iterdir())
                                 if fp.is_file() and fp.suffix.lower() in _MEDIA_EXT]
                        # Structured diagnostic evidence files: only listed when they genuinely
                        # exist on disk, so the operator UI never links to an artifact that isn't
                        # there.
                        # Labels are human-readable; the rel path is exact-run/exact-prospect
                        # confined and servable via the SAME safe /scout/artifact route as media.
                        for _name, _label in _STRUCTURED_EVIDENCE_ARTIFACTS:
                            if (pdir / _name).is_file():
                                evidence_files.append({
                                    "name": _name, "label": _label,
                                    "rel": f"prospects/{prospect_id}/{_name}"})
                    except Exception:
                        media = []
                else:
                    # The run exists but no prospect canonicalises to this domain: fail honestly rather
                    # than borrow another company's evidence.
                    evidence_status = "prospect_not_found"
            except Exception:
                evidence_status = "error"
        # Copy-only outreach draft from the target's problems (the system never sends it).
        # A READ is $0: the draft is always deterministic here (router=None). AI prose polish is an
        # explicit, operator-triggered mutation (see ``polish_draft``) — never a page/refresh read.
        from core.scout.outreach.qa_draft import build_review_draft
        understanding = (brain or {}).get("brain", {})
        draft = build_review_draft(domain=domain,
                                   business_name=(entry.domain if entry else domain),
                                   understanding=understanding, findings=findings,
                                   contact=(contacts[0] if contacts else ""),
                                   router=None)
        from core.scout.outreach.fixability import classify_fixability
        # Cold prospect: no repo/staging access yet, so nothing is 'fix_ready' (honest scoping).
        fixability = classify_fixability(
            [{"severity": f.get("severity"), "category": f.get("category"),
              "title": f.get("title"), "business_impact": f.get("business_impact")}
             for f in findings], access_available=False)
        return {"domain": domain, "entry": entry.to_dict() if entry else None, "brain": brain,
                "scout_run": scout_run, "run": scout_run, "prospect_id": prospect_id,
                "prospect_status": prospect_status, "analysis_complete": analysis_complete,
                "manual_action": manual_action, "source_kind": source_kind,
                "video_mode": video_mode, "evidence_files": evidence_files, "coverage": coverage,
                "evidence_status": evidence_status, "media": media, "network": network,
                "reproduction": reproduction,
                "findings": [_project_target_finding(f) for f in findings],
                "contacts": contacts, "draft": draft, "fixability": fixability}

    def polish_draft(self, domain: str) -> Dict[str, Any]:
        """Explicit, operator-triggered AI polish of the outreach draft. This is the ONLY draft path
        that may make a paid model call (a cheap-model reword), and only when a live LLM is
        configured; it is never reached from a read/GET, and it is $0/deterministic otherwise.

        NOTE: per-campaign/daily/monthly budget controls and a persistent no-repeat cache arrive in
        Slice 3 — until then a repeat invocation may repeat the call. Reuses the deterministic read
        for facts (findings/understanding/contact), then rebuilds the prose WITH the live router.
        Falls back to deterministic on any failure/mock/zero-config."""
        det = self.target_detail(domain)
        from core.scout.outreach.qa_draft import build_review_draft
        understanding = ((det.get("brain") or {}).get("brain") or {})
        contacts = det.get("contacts") or []
        return build_review_draft(domain=domain, business_name=domain,
                                  understanding=understanding, findings=(det.get("findings") or []),
                                  contact=(contacts[0] if contacts else ""),
                                  router=self._llm_router())

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
        best: Optional[tuple] = None
        for bp in sorted(base.glob("*/BRAIN_DECISIONS.json")):
            try:
                data = json.loads(bp.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict) or not isinstance(data.get("decisions"), list):
                continue
            raw_at = str(data.get("at") or "").strip()
            try:
                parsed_at = datetime.fromisoformat(raw_at.replace("Z", "+00:00"))
                if parsed_at.tzinfo is None:
                    parsed_at = parsed_at.replace(tzinfo=timezone.utc)
                timestamp = parsed_at.timestamp()
                has_timestamp = True
            except (OSError, OverflowError, TypeError, ValueError):
                timestamp = float("-inf")
                has_timestamp = False
            for index, decision in enumerate(data["decisions"]):
                if not isinstance(decision, dict) or decision.get("domain") != domain:
                    continue
                # Persisted campaign completion time is authoritative. Legacy records without a
                # valid `at` remain deterministic via campaign id + decision position, rather than
                # depending on filesystem/glob order (which differs across machines and restores).
                key = (has_timestamp, timestamp, bp.parent.name, index)
                if best is None or key > best[0]:
                    best = (key, decision)
        return best[1] if best is not None else None

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
