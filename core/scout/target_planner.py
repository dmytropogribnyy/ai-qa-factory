"""Adaptive per-target QA planner (v3.3).

Scout does not run the same static checklist against every site. For a promoted target, and given
the depth the adaptive allocator granted, this builds a bounded **Target Test Plan** that explicitly
decides what to test, what NOT to test, why, the depth, a time cap, the allowed interaction, the
stop boundary, cleanup requirements, and evidence requirements. It reuses the vertical profile
(site archetype -> checks + flow + stop boundaries) and stays finite.

Staged model: Stage 1 lightweight baseline -> Stage 3 selective browser exploration (only relevant
flows) -> Stage 4/5 evidence-driven deepening (only when justified). Deepening never weakens a
safety boundary.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence, Tuple

from core.scout.adaptive import DEPTH_DEEP, DEPTH_SKIP
from core.scout.checks import CHECK_REGISTRY
from core.scout.public_action_policy import MODE_PASSIVE
from core.scout.verticals import FLOW_PASSIVE, VerticalProfile

_PLAN_SCHEMA = "scout-target-test-plan/v2"

# The plan used to carry its own vocabulary — ten names, none of which existed in `CHECK_REGISTRY`.
# Nothing in a plan could therefore be joined to what actually ran, and `run_checks()` ignores an
# unknown family without complaint, so no execution path would ever have objected. There is now one
# keyspace: a selected check IS an executor id, and anything else is typed as what it really is.
_PRECONDITIONS = ("reachability",)

# Named in the old baseline with no executor behind either of them, at any depth, ever. They are not
# "skipped" — skipping implies an executor that was not run — and they are not dropped in silence,
# which would quietly narrow the advertised surface instead of admitting the product never had it.
_DECLARED_NOT_COVERED = (
    {"check": "passive_security_headers",
     "reason": "no executor exists in this product; previously advertised in the plan only"},
    {"check": "content_anomalies",
     "reason": "no executor exists in this product; previously advertised in the plan only"},
)


@dataclass
class TargetTestPlan:
    domain: str
    archetype: str
    depth: str
    schema: str = _PLAN_SCHEMA
    # Executor ids only. Both lists join directly against `CHECK_REGISTRY` and against a run's
    # persisted `check_families`, so plan and receipts can be compared mechanically.
    checks_selected: List[str] = field(default_factory=list)
    checks_skipped: List[str] = field(default_factory=list)
    # Gates the run rather than being one of its checks.
    preconditions: List[str] = field(default_factory=lambda: list(_PRECONDITIONS))
    # Advertised once, never executable. Disclosed rather than deleted.
    declared_not_covered: List[Dict[str, str]] = field(
        default_factory=lambda: [dict(item) for item in _DECLARED_NOT_COVERED])
    allowed_interaction_mode: str = MODE_PASSIVE
    flow: str = "passive"
    stop_boundaries: Tuple[str, ...] = ()
    max_duration_s: int = 0
    cleanup_required: bool = False
    evidence_requirements: List[str] = field(default_factory=list)
    decisions: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        d = dict(self.__dict__)
        d["stop_boundaries"] = list(self.stop_boundaries)
        return d


def describe_persisted_plan(plan: Dict[str, Any]) -> Dict[str, Any]:
    """Present a stored plan honestly without editing it.

    Plans written before this change name checks in a vocabulary no executor ever provided. They must
    keep saying exactly what they said — production artifacts are evidence, and rewriting them to
    look correct would be a worse defect than the one being fixed — so the label goes beside them:
    the reader is told the names cannot be resolved to executors and that the coverage is therefore
    unverified, rather than being allowed to read them as coverage.

    Returns a copy. The input mapping is never mutated.
    """
    described = dict(plan)
    selected = [str(c) for c in (plan.get("checks_selected") or [])]
    unresolved = [c for c in selected if c not in CHECK_REGISTRY]
    legacy = str(plan.get("schema") or "") != _PLAN_SCHEMA
    described["legacy_vocabulary"] = legacy
    described["coverage_verified"] = not legacy and not unresolved
    described["unresolved_checks"] = unresolved
    return described


def plan_target(*, domain: str, profile: VerticalProfile, depth: str,
                selected_families: Sequence[str] = (),
                max_target_duration_s: int = 180,
                remaining_budget_s: int = 0) -> TargetTestPlan:
    """Record what one promoted target's run covered, and what the allocator made of it afterwards.

    This is emitted by `CampaignService._persist_brain()` on the line *after*
    `DiscoveryEngine(...).run()` returns, so it is a description of a run that already finished.
    `depth` comes from an `AdaptiveAllocator` built at that moment, which appears nowhere in either
    engine and gated nothing. Coverage is therefore derived from `selected_families` — the promoted
    run's persisted `check_families`, the same list the engine executed — and never from `depth`.

    Deriving coverage from the depth is how this record came to deny work that had already happened:
    a retrospective "baseline" filed `business_flow` under `checks_skipped` after the engine had run
    it on both passes, and a retrospective "skip" did that to the entire selection.

    `qa_focus` / `qa_exclude` used to narrow the result. They had no caller, and on a record written
    after the fact their only possible effect was to subtract coverage that had already been
    executed, so they are gone rather than left as a way to make this artifact lie.

    The plan remains descriptive. It does not, and must not, drive execution.
    """
    plan = TargetTestPlan(domain=domain, archetype=profile.site_type, depth=depth)
    runnable = [f for f in dict.fromkeys(selected_families) if f in CHECK_REGISTRY]
    unrunnable = [f for f in dict.fromkeys(selected_families) if f not in CHECK_REGISTRY]
    if unrunnable:
        plan.decisions.append(
            f"excluded from the plan, no executor: {sorted(unrunnable)}")

    # --- what this run covered. Depth plays no part; it did not exist when the engine ran. --------
    plan.checks_selected = list(runnable)
    # Selection, not outcome. `PROMO_PROMOTED` is assigned while ranking, *before* the target is
    # analysed, so a promoted target may still have turned out unreachable or MANUAL_ACTION_REQUIRED
    # and never reached `run_checks()` at all. Saying "this executed" here would be the same defect
    # pointing the other way, so the record states what the run selected and leaves the per-target
    # outcome to the surface that actually observed it.
    plan.decisions.append(
        "selection: verbatim from the promoted run's persisted check_families — the list "
        "`run_checks()` is driven from. Whether this particular target completed is recorded by its "
        "prospect status, not here")

    # `engine.py` gates the vertical flow on `"business_flow" in cfg.check_families` and on nothing
    # else — no depth is consulted there — so the flow fields follow the same single condition.
    if "business_flow" in runnable:
        plan.flow = profile.flow
        plan.allowed_interaction_mode = profile.interaction_mode
        plan.stop_boundaries = tuple(profile.stop_boundaries)
        # The flow is scenario metadata and lives in `flow`. It used to be appended to the check
        # list as `browser_flow:<name>`, which put a label with no executor into the family
        # keyspace — the same untruth again, in a different disguise.
        plan.cleanup_required = profile.flow == "reversible_cart"
        plan.decisions.append(
            f"vertical_scenario: the run selected business_flow, so the {profile.flow} flow is in "
            f"scope for this target and stops before "
            f"{', '.join(profile.stop_boundaries) or 'no irreversible action'}")
    else:
        plan.flow = FLOW_PASSIVE
        plan.allowed_interaction_mode = MODE_PASSIVE
        # A `FLOW_PASSIVE` archetype has no vertical scenario at all. Naming one anyway would imply
        # something existed and was passed over, which is a different fact from not selecting it.
        scenario = ("no vertical scenario" if profile.flow == FLOW_PASSIVE
                    else f"the {profile.flow} scenario")
        plan.decisions.append(
            "no_interactive_flow: this run's check_families did not select business_flow, so "
            f"{scenario} is claimed here")

    # --- the allocator's verdict, kept as a verdict ------------------------------------------------
    plan.decisions.append(
        f"retrospective_assessment: depth={depth} was decided by an allocator constructed after "
        "this run finished; it grades how much attention the target merited and gated nothing in "
        "this run")

    plan.evidence_requirements = ["screenshots", "console", "network", "dom_state"]
    if depth == DEPTH_DEEP:
        plan.evidence_requirements += ["playwright_trace", "reproduction_steps"]
        plan.decisions.append("stage4_deep: capture trace + reproduction steps for a valuable target")

    # Time cap — a ceiling the assessment would have set, bounded by the per-target limit and any
    # remaining campaign budget. It is not a measurement: at DEPTH_SKIP it is zero because the
    # assessment would have granted no browser budget, which says nothing about what the run spent.
    cap = max_target_duration_s
    if remaining_budget_s > 0:
        cap = min(cap, remaining_budget_s)
    plan.max_duration_s = 0 if depth == DEPTH_SKIP else max(cap, 1)
    plan.decisions.append(f"time_cap={plan.max_duration_s}s")
    return plan
