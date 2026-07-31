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

from core.scout.adaptive import DEPTH_DEEP, DEPTH_SELECTIVE, DEPTH_SKIP
from core.scout.checks import CHECK_REGISTRY
from core.scout.public_action_policy import MODE_PASSIVE
from core.scout.verticals import VerticalProfile

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
                qa_focus: Tuple[str, ...] = (), qa_exclude: Tuple[str, ...] = (),
                max_target_duration_s: int = 180,
                remaining_budget_s: int = 0) -> TargetTestPlan:
    """Build a bounded Target Test Plan for one promoted target at the granted depth.

    `selected_families` is the promoted run's persisted `check_families`. It is required in spirit:
    deriving the plan from the whole registry instead would still overstate a run configured with a
    subset — a tidier claim about coverage that did not happen. Ids that no executor provides are
    dropped here rather than published, because the plan is read as coverage.

    The plan remains a descriptive record. It does not, and must not, drive execution.
    """
    plan = TargetTestPlan(domain=domain, archetype=profile.site_type, depth=depth)
    runnable = [f for f in dict.fromkeys(selected_families) if f in CHECK_REGISTRY]
    unrunnable = [f for f in dict.fromkeys(selected_families) if f not in CHECK_REGISTRY]
    if unrunnable:
        plan.decisions.append(
            f"excluded from the plan, no executor: {sorted(unrunnable)}")

    if depth == DEPTH_SKIP:
        plan.decisions.append("skip: allocator granted no browser budget for this target")
        plan.checks_skipped = list(runnable)
        plan.max_duration_s = 0
        return plan

    # Stage 1 — exactly what this run selected, never more.
    selected = list(runnable)
    # Optional focus/exclusion (never adds an unsupported check).
    if qa_focus:
        focus = set(qa_focus)
        kept = [c for c in selected if any(f in c for f in focus)] or selected
        plan.decisions.append(f"focus applied: {sorted(focus)}")
        selected = kept
    if qa_exclude:
        excl = set(qa_exclude)
        removed = [c for c in selected if any(x in c for x in excl)]
        selected = [c for c in selected if c not in removed]
        plan.checks_skipped.extend(removed)
        if removed:
            plan.decisions.append(f"excluded by operator focus: {removed}")
    plan.decisions.append("stage1_baseline: lightweight checks on a sufficiently promising target")

    # Stage 3 — selective browser exploration. Depth alone is not enough: `engine.py` calls
    # `_explore_flow()` only when `business_flow` is in the run's `check_families`, so the flow
    # fields are a coverage claim under exactly the same condition as any check id. Setting them
    # from the profile whenever the depth allowed it described a scenario the runtime would never
    # attempt — the same untruth as an unexecutable check name, one field over.
    reaches_stage3 = depth in (DEPTH_SELECTIVE, DEPTH_DEEP)
    runs_flow = "business_flow" in selected
    if reaches_stage3 and runs_flow:
        plan.flow = profile.flow
        plan.allowed_interaction_mode = profile.interaction_mode
        plan.stop_boundaries = tuple(profile.stop_boundaries)
        # The flow is scenario metadata and lives in `flow`. It used to be appended to the check
        # list as `browser_flow:<name>`, which put a label with no executor into the family
        # keyspace — the same untruth again, in a different disguise.
        plan.cleanup_required = profile.flow == "reversible_cart"
        plan.decisions.append(
            f"stage3_selective: explore only the {profile.flow} flow; stop before "
            f"{', '.join(profile.stop_boundaries) or 'no irreversible action'}")
    else:
        plan.flow = "passive"
        plan.allowed_interaction_mode = MODE_PASSIVE
        if not reaches_stage3 and runs_flow:
            # The executor was selected but this depth does not reach it. That is a real skip, and
            # it is named by its real id: the old code appended the literal "browser_flow", which
            # no executor provides, so the skip named something that could never have run either
            # way.
            selected.remove("business_flow")
            plan.checks_skipped.append("business_flow")
            plan.decisions.append("baseline_only: passive checks; no interactive flow at this depth")
        elif reaches_stage3:
            # A silently passive plan reads as "this vertical has no interactive scenario", which
            # is a different claim from "the executor for it is not in this selection". Name the
            # actual cause: an operator focus/exclusion that dropped `business_flow` is not the
            # same fact as a run that never selected it, and asserting either one blindly would put
            # a false explanation next to a true absence.
            cause = ("the operator's focus/exclusion removed business_flow from this target"
                     if "business_flow" in runnable
                     else "this run's check_families did not select business_flow")
            plan.decisions.append(
                f"no_interactive_flow: {cause}, so the {profile.flow} scenario is not claimed")
        else:
            plan.decisions.append("baseline_only: passive checks; no interactive flow at this depth")

    # Stage 4/5 — evidence-driven deepening (DEEP only).
    plan.evidence_requirements = ["screenshots", "console", "network", "dom_state"]
    if depth == DEPTH_DEEP:
        plan.evidence_requirements += ["playwright_trace", "reproduction_steps"]
        plan.decisions.append("stage4_deep: capture trace + reproduction steps for a valuable target")

    plan.checks_selected = selected

    # Time cap — bounded by the per-target ceiling and any remaining campaign budget.
    cap = max_target_duration_s
    if remaining_budget_s > 0:
        cap = min(cap, remaining_budget_s)
    plan.max_duration_s = max(cap, 1)
    plan.decisions.append(f"time_cap={plan.max_duration_s}s")
    return plan
