"""Adaptive allocation — the bounded "smart Scout" brain (v3.3).

Three SEPARATE concepts (never fixed ratios):

1. **Hard ceilings** — absolute maximums that are never exceeded (from the campaign config). They
   are caps, not quotas that must be consumed.
2. **Outcome targets** — optional goals (desired actionable / A-priority / findings / diversity).
   The campaign may stop EARLY when they are met.
3. **Adaptive allocation** — spend cheap discovery/triage first, then spend browser/deep budget
   only on sufficiently promising, safe targets. Depth per target is decided from commercial
   value, QA risk, safety, remaining budget and strategy — so 100 discovered may mean 3 or 40
   deeply inspected, and no ceiling must be fully consumed.

Every decision is explainable (reasons) and diversity-capped so one company / country / industry /
target-type cannot dominate a run. Nothing here weakens a safety or authorization boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Tuple

# Per-target QA depth (what the allocator grants).
DEPTH_SKIP = "skip"
DEPTH_BASELINE = "baseline"        # lightweight Stage-1 checks only
DEPTH_SELECTIVE = "selective"      # + selected browser exploration
DEPTH_DEEP = "deep"                # + evidence-driven deepening

# Strategy modes.
STRATEGY_CONSERVATIVE = "conservative"
STRATEGY_BALANCED = "balanced"
STRATEGY_OPPORTUNITY = "opportunity"
STRATEGIES = frozenset({STRATEGY_CONSERVATIVE, STRATEGY_BALANCED, STRATEGY_OPPORTUNITY})


@dataclass
class OutcomeTargets:
    """Optional goals; a value of 0 means 'not a goal'. The run may stop early once met."""
    actionable: int = 0
    a_priority: int = 0
    verified_findings: int = 0
    high_value_findings: int = 0
    min_industries: int = 0
    min_countries: int = 0
    min_issue_types: int = 0

    def any_set(self) -> bool:
        return any(v > 0 for v in self.__dict__.values())


@dataclass
class DiversityCaps:
    """Per-dimension caps (0 = uncapped) so no single dimension dominates a run."""
    per_company: int = 0
    per_country: int = 0
    per_industry: int = 0
    per_target_type: int = 0
    per_finding_type: int = 0


@dataclass
class HardCeilings:
    """Absolute maximums for the adaptive phase (mirrors the campaign config's browser/deep caps)."""
    max_browser_tested: int = 0
    max_deep_tested: int = 0
    max_interactive: int = 0
    max_actionable: int = 0


@dataclass
class AllocationDecision:
    domain: str
    depth: str
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


# (commercial_min, qa_risk_min) thresholds per strategy for each depth grant.
_THRESHOLDS = {
    STRATEGY_CONSERVATIVE: {DEPTH_DEEP: (80, 60), DEPTH_SELECTIVE: (72, 40), DEPTH_BASELINE: (60, 0)},
    STRATEGY_BALANCED: {DEPTH_DEEP: (70, 45), DEPTH_SELECTIVE: (60, 25), DEPTH_BASELINE: (45, 0)},
    STRATEGY_OPPORTUNITY: {DEPTH_DEEP: (60, 35), DEPTH_SELECTIVE: (48, 15), DEPTH_BASELINE: (35, 0)},
}


class AdaptiveAllocator:
    """Decides per-target QA depth under hard ceilings, diversity caps and a strategy, and reports
    when optional outcome targets are met. Pure/in-memory; the caller persists the decisions."""

    def __init__(self, *, strategy: str = STRATEGY_BALANCED,
                 ceilings: HardCeilings = None, outcomes: OutcomeTargets = None,
                 diversity: DiversityCaps = None) -> None:
        if strategy not in STRATEGIES:
            raise ValueError(f"unknown strategy: {strategy!r}")
        self.strategy = strategy
        self.ceilings = ceilings or HardCeilings()
        self.outcomes = outcomes or OutcomeTargets()
        self.diversity = diversity or DiversityCaps()
        self.tally = {"browser_opened": 0, "deep_tested": 0, "interactive": 0, "actionable": 0,
                      "a_priority": 0, "verified_findings": 0, "high_value_findings": 0}
        self._by_company: Dict[str, int] = {}
        self._by_country: Dict[str, int] = {}
        self._by_industry: Dict[str, int] = {}
        self._by_target_type: Dict[str, int] = {}
        self._industries_seen: set = set()
        self._countries_seen: set = set()
        self._issue_types_seen: set = set()

    # -- allocation ------------------------------------------------------------------------------
    def decide(self, *, domain: str, commercial_score: int, qa_risk: int, safety_ok: bool,
               country: str = "", industry: str = "", target_type: str = "") -> AllocationDecision:
        reasons: List[str] = []
        # 1) Safety first — an unsafe/ambiguous target is never browser-tested.
        if not safety_ok:
            return AllocationDecision(domain, DEPTH_SKIP, ["unsafe_or_ambiguous_target"])
        # 2) Hard ceiling — browser budget is a cap, not a quota.
        if self.ceilings.max_browser_tested and \
                self.tally["browser_opened"] >= self.ceilings.max_browser_tested:
            return AllocationDecision(domain, DEPTH_SKIP, ["max_browser_tested_reached"])
        # 3) Diversity caps — do not let one dimension dominate.
        for label, key, seen in (("company", domain, self._by_company),
                                 ("country", country, self._by_country),
                                 ("industry", industry, self._by_industry),
                                 ("target_type", target_type, self._by_target_type)):
            cap = getattr(self.diversity, f"per_{label}")
            if cap and key and seen.get(key, 0) >= cap:
                return AllocationDecision(domain, DEPTH_SKIP, [f"diversity_cap_{label}:{key}"])
        # 4) Opportunity — grant the deepest depth whose thresholds are met by this strategy.
        depth = self._depth_for(commercial_score, qa_risk, reasons)
        # 5) Deep ceiling (a cap on the *deep* grants specifically).
        if depth == DEPTH_DEEP and self.ceilings.max_deep_tested and \
                self.tally["deep_tested"] >= self.ceilings.max_deep_tested:
            depth = DEPTH_SELECTIVE
            reasons.append("deep_ceiling_reached_downgraded_to_selective")
        return AllocationDecision(domain, depth, reasons)

    def _depth_for(self, commercial: int, qa_risk: int, reasons: List[str]) -> str:
        th = _THRESHOLDS[self.strategy]
        for depth in (DEPTH_DEEP, DEPTH_SELECTIVE, DEPTH_BASELINE):
            cmin, rmin = th[depth]
            if commercial >= cmin and qa_risk >= rmin:
                reasons.append(f"{depth}:commercial>={cmin},qa_risk>={rmin} ({self.strategy})")
                return depth
        reasons.append(f"below_baseline_threshold ({self.strategy})")
        return DEPTH_SKIP

    # -- recording -------------------------------------------------------------------------------
    def record(self, decision: AllocationDecision, *, country: str = "", industry: str = "",
               target_type: str = "", actionable: bool = False, a_priority: bool = False,
               verified_findings: int = 0, high_value_findings: int = 0,
               issue_types: Tuple[str, ...] = ()) -> None:
        if decision.depth == DEPTH_SKIP:
            return
        self.tally["browser_opened"] += 1
        if decision.depth == DEPTH_DEEP:
            self.tally["deep_tested"] += 1
        self._by_company[decision.domain] = self._by_company.get(decision.domain, 0) + 1
        if country:
            self._by_country[country] = self._by_country.get(country, 0) + 1
            self._countries_seen.add(country)
        if industry:
            self._by_industry[industry] = self._by_industry.get(industry, 0) + 1
            self._industries_seen.add(industry)
        if target_type:
            self._by_target_type[target_type] = self._by_target_type.get(target_type, 0) + 1
        self.tally["actionable"] += int(actionable)
        self.tally["a_priority"] += int(a_priority)
        self.tally["verified_findings"] += verified_findings
        self.tally["high_value_findings"] += high_value_findings
        self._issue_types_seen.update(issue_types)

    # -- outcome-target early stop ---------------------------------------------------------------
    def outcome_reached(self) -> Tuple[bool, str]:
        o = self.outcomes
        if not o.any_set():
            return False, ""
        checks = [
            (o.actionable, self.tally["actionable"], "actionable_target_reached"),
            (o.a_priority, self.tally["a_priority"], "a_priority_target_reached"),
            (o.verified_findings, self.tally["verified_findings"], "verified_findings_target_reached"),
            (o.high_value_findings, self.tally["high_value_findings"],
             "high_value_findings_target_reached"),
            (o.min_industries, len(self._industries_seen), "industry_diversity_target_reached"),
            (o.min_countries, len(self._countries_seen), "country_diversity_target_reached"),
            (o.min_issue_types, len(self._issue_types_seen), "issue_type_diversity_target_reached"),
        ]
        # All *set* goals must be satisfied for an early, honest completion.
        set_goals = [(want, have, why) for (want, have, why) in checks if want > 0]
        if set_goals and all(have >= want for (want, have, _why) in set_goals):
            return True, "all_outcome_targets_reached"
        return False, ""

    def snapshot(self) -> Dict[str, Any]:
        return {"strategy": self.strategy, "tally": dict(self.tally),
                "industries_seen": sorted(self._industries_seen),
                "countries_seen": sorted(self._countries_seen),
                "issue_types_seen": sorted(self._issue_types_seen)}
