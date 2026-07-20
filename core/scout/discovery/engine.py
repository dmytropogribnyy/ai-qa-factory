"""Discovery orchestration engine (Phase 8.4).

campaign -> matrix -> providers (budget-enforced) -> candidates -> normalize -> dedup ->
suppression -> cheap technical eligibility -> commercial triage -> explainable top-N ->
bounded promotion into the EXISTING Scout v1.0.1 QA engine -> persistence + artifacts.

Every fetch and promotion is gated: duplicates, NO_SCAN suppression, and invalid/private URLs
are never fetched; terms-blocked/disabled providers never execute; budgets fail closed; the
commercial score never authorizes outreach; and a promoted candidate never bypasses Scout
safety (the Scout engine independently re-validates every URL).
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from core.schemas.prospect_governance import SuppressionPolicy
from core.scout.backends import PageObservation, make_backend
from core.scout.config import ScoutRunConfig
from core.scout.discovery.candidate import (
    COMM_ELIGIBLE,
    DUP_UNCERTAIN,
    PROMO_HELD,
    PROMO_NOT_PROMOTED,
    PROMO_PROMOTED,
    TECH_OK,
    CandidateRecord,
)
from core.scout.discovery.config import DiscoveryCampaignConfig
from core.scout.discovery.matrix import build_matrix
from core.scout.discovery.normalize import normalize_candidates
from core.scout.discovery.providers import DiscoveryCandidate, DiscoveryError, ProviderRegistry
from core.scout.discovery.suppression import apply_suppression
from core.scout.discovery.triage import TriageContext, assess_commercial, assess_technical
from core.scout.engine import ScoutEngine
from core.scout.report import build_report as build_scout_report
from core.scout.run_counters import actionable_target_reached, counters_from_records
from core.scout.store import RunStore


def _default_actionable(rec: CandidateRecord, _scout_store: Any) -> bool:
    """Default actionability: the explainable commercial priority is 'A'. Increment 2 replaces
    this with a QA-finding-aware classifier (strong commercial fit AND an evidence-backed
    medium/high public finding)."""
    return (rec.commercial_scorecard or {}).get("priority") == "A"

RUN_PLANNED, RUN_RUNNING, RUN_COMPLETED, RUN_FAILED = "PLANNED", "RUNNING", "COMPLETED", "FAILED"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DiscoveryEngine:
    def __init__(self, config: DiscoveryCampaignConfig, registry: ProviderRegistry,
                 store: RunStore, suppression_policies: Optional[List[SuppressionPolicy]] = None,
                 clock: Callable[[], str] = _now, profiler=None, scout_backend=None,
                 progress: Optional[Callable[[Dict], None]] = None,
                 sample: Optional[int] = None,
                 actionable_predicate: Optional[Callable[[CandidateRecord, Any], bool]] = None
                 ) -> None:
        self.config = config
        self.registry = registry
        self.store = store
        self.suppression_policies = suppression_policies or []
        self.clock = clock
        self.progress = progress
        self.sample = sample
        # Cheap static profiler (never Playwright for discovery triage).
        self.profiler = profiler or make_backend("static", policy=config.url_policy())
        # Optional explicit backend for promoted Scout runs (fixtures/E2E inject a host-mapped
        # backend; production leaves this None so the Scout engine builds its own real backend).
        self.scout_backend = scout_backend
        # Predicate deciding whether a promoted+analyzed candidate is "actionable" (Priority A).
        # Increment 2 replaces the default with a QA-finding-aware classifier; here it is the
        # explainable commercial priority so the actionable-target stop is real and testable.
        self.actionable_predicate = actionable_predicate or _default_actionable
        self._start = time.monotonic()
        self._budget = {"provider_calls": 0, "results": 0, "cost_usd": 0.0,
                        "profiled": 0, "eligible": 0, "promoted": 0,
                        "actionable": 0, "already_analyzed": 0, "failed": 0}
        # Machine-readable reason the run finished (shown in the Dashboard). "" until set.
        self._stop_reason = ""
        self._consecutive_failures = 0

    # ------------------------------------------------------------------
    def plan(self) -> Dict[str, Any]:
        """Dry-run: build + validate the campaign and matrix and return the plan artifacts."""
        campaign = self.config.build_campaign()
        provider_ids = self._resolved_provider_ids()
        matrix = build_matrix(self.config, provider_ids, sample=self.sample)
        return {
            "campaign_id": self.config.campaign_id,
            "PROSPECT_CAMPAIGN.json": campaign.to_dict(),
            "MARKET_POLICY.json": self.config.build_market_policy().to_dict(),
            "CAMPAIGN_MATRIX.json": matrix.to_dict(),
            "PROVIDER_BUDGET.json": self._budget_plan(matrix),
            "PROVIDER_REGISTRY_SNAPSHOT.json": self.registry.snapshot(),
            "DISCOVERY_PLAN.json": {
                "campaign_id": self.config.campaign_id,
                "providers": provider_ids,
                "planned_provider_calls": matrix.planned_provider_calls,
                "matrix_full_size": matrix.full_size,
                "sampled": matrix.sampled,
                "max_promoted": self.config.max_promoted,
                "min_commercial_threshold": self.config.min_commercial_threshold,
                "dry_run": self.config.dry_run,
            },
        }

    def run(self) -> Dict[str, Any]:
        cfg = self.config
        # Fail closed on campaign-directory reuse (no stale-artifact mixing). The bundled demo
        # resets its own confined dir first; fresh runs get a unique campaign id.
        if self.store.exists():
            raise DiscoveryError(
                f"campaign {cfg.campaign_id!r} already exists; refusing to overwrite it "
                "(use a fresh campaign id, or reset the campaign directory explicitly)")
        plan = self.plan()
        state: Dict[str, Any] = {
            "campaign_id": cfg.campaign_id, "status": RUN_RUNNING,
            "started_at": self.clock(), "config": cfg.to_dict(),
            "matrix": plan["CAMPAIGN_MATRIX.json"], "budget": dict(self._budget),
        }
        self.store.write_config(cfg.to_dict())
        self.store.save_state(state)
        self._event("campaign_started", campaign_id=cfg.campaign_id)

        # 1. discovery (budget-enforced)
        raw_candidates = self._discover(plan["CAMPAIGN_MATRIX.json"]["cells"])
        # 2. normalize + dedup
        records, norm_report = normalize_candidates(raw_candidates, cfg.campaign_id,
                                                    cfg.url_policy())
        # 3. suppression (before any fetch)
        supp_report = apply_suppression(
            records, self.suppression_policies,
            allow_readonly_when_no_outreach=cfg.allow_readonly_profiling_when_no_outreach)
        # 4. technical eligibility (cheap static profiling; never fetch dup/NO_SCAN/invalid)
        ctx = TriageContext(languages=list(cfg.languages), countries=list(cfg.countries),
                            min_commercial_threshold=cfg.min_commercial_threshold)
        self._triage(records, ctx)
        # 5. promotion decision (explainable top-N; uncertain identity held for review)
        promoted = self._decide_promotions(records)
        # Any remaining candidate is explicitly kept (never promoted) for review/history.
        for r in records:
            if r.promotion_decision == "pending":
                r.promotion_decision = PROMO_NOT_PROMOTED
        # 6. promote into the existing Scout engine
        self._promote_into_scout(promoted)

        state.update({
            "status": RUN_COMPLETED, "finished_at": self.clock(),
            "budget": dict(self._budget),
            "counts": self._counts(records),
            "stop_reason": self._stop_reason or "completed",
            "candidates": [r.to_dict() for r in records],
        })
        self.store.save_state(state)
        self._persist_artifacts(plan, records, norm_report, supp_report)
        self._event("campaign_finished", campaign_id=cfg.campaign_id,
                    promoted=self._budget["promoted"])
        return state

    # ------------------------------------------------------------------
    def _resolved_provider_ids(self) -> List[str]:
        ids = [pid for pid in self.config.provider_allowlist if pid in self.registry.ids()]
        if not ids:
            raise DiscoveryError("no allow-listed provider is registered")
        return ids

    def _discover(self, cells: List[Dict[str, str]]) -> List[Any]:
        cfg = self.config
        out: List[Any] = []
        for cell in cells:
            if self._over_time_budget():
                self._stop_reason = self._stop_reason or "time_budget"
                self._event("budget_stop", reason="time_budget")
                break
            if self._budget["provider_calls"] >= cfg.max_provider_calls:
                self._stop_reason = self._stop_reason or "max_provider_calls"
                self._event("budget_stop", reason="max_provider_calls")
                break
            if self._budget["results"] >= cfg.max_candidates:
                self._stop_reason = self._stop_reason or "max_discovered"
                self._event("budget_stop", reason="max_candidates")
                break
            provider = self.registry.get(cell["provider_id"])
            allowed, reason = provider.metadata.can_execute(cfg.approve_live_discovery)
            if not allowed:
                self._event("provider_skipped", provider=cell["provider_id"], reason=reason)
                continue
            self._budget["provider_calls"] += 1
            limit = min(cfg.per_provider_result_budget,
                        cfg.max_candidates - self._budget["results"])
            try:
                results = provider.discover(cell, limit)
            except DiscoveryError as exc:
                self._event("provider_error", provider=cell["provider_id"], error=str(exc)[:160])
                continue
            # Cost ceiling (fail closed).
            cost = provider.metadata.cost_per_result_usd * len(results)
            if cfg.cost_ceiling_usd and self._budget["cost_usd"] + cost > cfg.cost_ceiling_usd:
                self._stop_reason = self._stop_reason or "cost_ceiling"
                self._event("budget_stop", reason="cost_ceiling", provider=cell["provider_id"])
                break
            self._budget["cost_usd"] = round(self._budget["cost_usd"] + cost, 6)
            for cand in results:
                if self._budget["results"] >= cfg.max_candidates:
                    break
                # Fail closed on provider result type confusion: a provider that returns a
                # non-DiscoveryCandidate is skipped and recorded, never crashing the run.
                if not isinstance(cand, DiscoveryCandidate):
                    self._event("provider_bad_result", provider=cell["provider_id"],
                                got=type(cand).__name__)
                    continue
                out.append(cand)
                self._budget["results"] += 1
        return out

    def _triage(self, records: List[CandidateRecord], ctx: TriageContext) -> None:
        for rec in records:
            # Never fetch: duplicates, NO_SCAN-suppressed, invalid/private URL, or already skipped.
            if not rec.is_scannable or not rec.normalized_url or rec.eligibility_status == "skipped":
                continue
            obs = self._profile(rec.normalized_url)
            self._budget["profiled"] += 1
            assess_technical(rec, obs, ctx)
            if rec.eligibility_status == TECH_OK:
                assess_commercial(rec, obs, ctx)
                if rec.commercial_status == COMM_ELIGIBLE:
                    self._budget["eligible"] += 1

    def _profile(self, url: str) -> PageObservation:
        return self.profiler.observe(url, 15.0, 1_000_000)

    def _decide_promotions(self, records: List[CandidateRecord]) -> List[CandidateRecord]:
        cfg = self.config
        # Eligible, confirmed-identity, non-suppressed candidates ranked by commercial score.
        # A suppressed candidate stays visible but is never promoted (never outreach-ready).
        eligible = [r for r in records
                    if r.commercial_status == COMM_ELIGIBLE and r.eligibility_status == TECH_OK
                    and r.suppression_status == "none"]
        # Uncertain identity is never auto-promoted — it is held for human review.
        for r in eligible:
            if r.duplicate_status == DUP_UNCERTAIN:
                r.promotion_decision = PROMO_HELD
                r.add_reason("held_uncertain_identity")
        rankable = [r for r in eligible if r.promotion_decision != PROMO_HELD]
        rankable.sort(key=lambda r: (-r.commercial_score, r.candidate_id))
        rankable = rankable[: cfg.max_eligible]
        # The QA-analysis budget is the effective promotion cap (never exceeds max_promoted).
        qa_cap = min(cfg.max_promoted, cfg.max_qa_analyzed) if cfg.max_qa_analyzed else cfg.max_promoted
        promoted: List[CandidateRecord] = []
        for r in rankable:
            if len(promoted) < qa_cap:
                r.promotion_decision = PROMO_PROMOTED
                r.add_reason("promoted_top_n")
                promoted.append(r)
            else:
                r.promotion_decision = PROMO_NOT_PROMOTED
                r.add_reason("below_top_n_kept_for_history")
        return promoted

    def _promote_into_scout(self, promoted: List[CandidateRecord]) -> None:
        cfg = self.config
        for idx, rec in enumerate(promoted, start=1):
            # Actionable-target stop: finish as soon as enough Priority-A prospects are found so
            # the run never continues indefinitely. A target of 0 disables this stop.
            if actionable_target_reached(found=self._budget["actionable"],
                                         target=cfg.actionable_target):
                rec.promotion_decision = PROMO_NOT_PROMOTED
                rec.add_reason("actionable_target_reached")
                self._stop_reason = self._stop_reason or "actionable_target_reached"
                self._event("actionable_target_reached", target=cfg.actionable_target)
                continue
            # Whole-run duration ceiling also bounds the QA phase (not only discovery).
            if self._over_time_budget():
                rec.promotion_decision = PROMO_NOT_PROMOTED
                rec.add_reason("time_budget_reached")
                self._stop_reason = self._stop_reason or "time_budget"
                self._event("budget_stop", reason="time_budget_qa")
                continue
            # Consecutive-failure circuit breaker (0 => disabled).
            if (cfg.max_consecutive_failures
                    and self._consecutive_failures >= cfg.max_consecutive_failures):
                rec.promotion_decision = PROMO_NOT_PROMOTED
                rec.add_reason("max_consecutive_failures")
                self._stop_reason = self._stop_reason or "max_consecutive_failures"
                self._event("budget_stop", reason="max_consecutive_failures",
                            failures=self._consecutive_failures)
                continue
            scout_run_id = f"{cfg.campaign_id}-promo-{idx:02d}"
            scout_cfg = ScoutRunConfig(
                campaign_name=cfg.campaign_id, seeds=[rec.normalized_url],
                allowed_local_hosts=cfg.allowed_local_hosts, browser_mode=cfg.browser_mode,
                output_dir=cfg.output_dir, run_id=scout_run_id, resolve_dns=cfg.resolve_dns,
                max_pages_per_site=cfg.max_pages_per_site)
            scout_store = RunStore(cfg.output_dir, scout_run_id)
            try:
                # The Scout engine independently re-validates URL safety — a discovery candidate
                # never bypasses Scout safety because a provider marked it trusted.
                ScoutEngine(scout_cfg, scout_store, clock=self.clock,
                            backend=self.scout_backend).run()
                build_scout_report(scout_store, clock=self.clock)
            except Exception as exc:   # a failed QA run is counted honestly, never silently dropped
                rec.promotion_decision = PROMO_NOT_PROMOTED
                rec.add_reason("qa_run_failed")
                self._budget["failed"] += 1
                self._consecutive_failures += 1
                self._event("qa_run_failed", candidate=rec.candidate_id, error=str(exc)[:160])
                continue
            self._consecutive_failures = 0            # a successful QA run resets the breaker
            rec.promoted_scout_run = scout_run_id
            self._budget["promoted"] += 1
            if self.actionable_predicate(rec, scout_store):
                self._budget["actionable"] += 1
                rec.add_reason("actionable")
            self._event("promoted_to_scout", candidate=rec.candidate_id, scout_run=scout_run_id)

    # ------------------------------------------------------------------
    def _counts(self, records: List[CandidateRecord]) -> Dict[str, int]:
        def n(pred) -> int:
            return sum(1 for r in records if pred(r))
        # Seven operator-facing counters (the honest funnel) merged with the detailed tallies.
        operator = counters_from_records(
            records, qa_analyzed=self._budget["promoted"],
            actionable=self._budget["actionable"],
            already_analyzed=self._budget["already_analyzed"],
            failed=self._budget["failed"]).to_dict()
        return {
            **operator,
            "candidates": len(records),
            "unique": n(lambda r: r.duplicate_status == "unique"),
            "duplicates": n(lambda r: r.duplicate_status in ("duplicate_url", "duplicate_domain")),
            "uncertain_identity": n(lambda r: r.duplicate_status == DUP_UNCERTAIN),
            "suppressed": n(lambda r: r.suppression_status != "none"),
            "no_scan": n(lambda r: r.suppression_status == "NO_SCAN"),
            "technical_ok": n(lambda r: r.eligibility_status == TECH_OK),
            "commercial_eligible": n(lambda r: r.commercial_status == COMM_ELIGIBLE),
            "promoted": n(lambda r: r.promotion_decision == PROMO_PROMOTED),
            "held_for_review": n(lambda r: r.promotion_decision == PROMO_HELD),
        }

    def _budget_plan(self, matrix) -> Dict[str, Any]:
        cfg = self.config
        return {
            "matrix_hard_max": cfg.matrix_hard_max,
            "max_provider_calls": cfg.max_provider_calls,
            "per_provider_result_budget": cfg.per_provider_result_budget,
            "max_candidates": cfg.max_candidates,
            "max_eligible": cfg.max_eligible,
            "max_promoted": cfg.max_promoted,
            "time_budget_s": cfg.time_budget_s,
            "cost_ceiling_usd": cfg.cost_ceiling_usd,
            "planned_provider_calls": matrix.planned_provider_calls,
        }

    def _persist_artifacts(self, plan, records, norm_report, supp_report) -> None:
        from core.scout.discovery.report import publish_discovery_report
        publish_discovery_report(self.store, plan, records, norm_report, supp_report,
                                 self._counts(records), dict(self._budget), clock=self.clock)

    def _over_time_budget(self) -> bool:
        return (time.monotonic() - self._start) > self.config.time_budget_s

    def _event(self, kind: str, **fields) -> None:
        event = {"at": self.clock(), "event": kind, **fields}
        self.store.append_event(event)
        if self.progress:
            self.progress(event)
