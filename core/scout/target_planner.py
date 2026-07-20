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
from typing import Any, Dict, List, Tuple

from core.scout.adaptive import DEPTH_DEEP, DEPTH_SELECTIVE, DEPTH_SKIP
from core.scout.public_action_policy import MODE_PASSIVE
from core.scout.verticals import VerticalProfile

# Stage-1 baseline checks (lightweight, low-cost) — the honest default surface.
_BASELINE_CHECKS = (
    "reachability", "navigation_links", "console_errors", "network_failures",
    "accessibility_axe", "rendered_performance", "seo_metadata",
    "passive_security_headers", "mobile_responsive", "content_anomalies",
)


@dataclass
class TargetTestPlan:
    domain: str
    archetype: str
    depth: str
    checks_selected: List[str] = field(default_factory=list)
    checks_skipped: List[str] = field(default_factory=list)
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


def plan_target(*, domain: str, profile: VerticalProfile, depth: str,
                qa_focus: Tuple[str, ...] = (), qa_exclude: Tuple[str, ...] = (),
                max_target_duration_s: int = 180,
                remaining_budget_s: int = 0) -> TargetTestPlan:
    """Build a bounded Target Test Plan for one promoted target at the granted depth."""
    plan = TargetTestPlan(domain=domain, archetype=profile.site_type, depth=depth)

    if depth == DEPTH_SKIP:
        plan.decisions.append("skip: allocator granted no browser budget for this target")
        plan.checks_skipped = list(_BASELINE_CHECKS)
        plan.max_duration_s = 0
        return plan

    # Stage 1 — lightweight baseline (all non-skip depths).
    selected = list(_BASELINE_CHECKS)
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

    # Stage 3 — selective browser exploration (SELECTIVE and DEEP only).
    if depth in (DEPTH_SELECTIVE, DEPTH_DEEP):
        plan.flow = profile.flow
        plan.allowed_interaction_mode = profile.interaction_mode
        plan.stop_boundaries = tuple(profile.stop_boundaries)
        selected.append(f"browser_flow:{profile.flow}")
        plan.cleanup_required = profile.flow == "reversible_cart"
        plan.decisions.append(
            f"stage3_selective: explore only the {profile.flow} flow; stop before "
            f"{', '.join(profile.stop_boundaries) or 'no irreversible action'}")
    else:
        plan.flow = "passive"
        plan.allowed_interaction_mode = MODE_PASSIVE
        plan.checks_skipped.append("browser_flow")
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
