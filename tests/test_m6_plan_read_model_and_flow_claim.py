"""M6, round 2 — the two seams where the plan still overstates what ran.

Both blockers share the shape of the original defect, which is why they survived the first pass:

1. `describe_persisted_plan()` computed the right labels and no production code called it. A helper
   that is green in its own unit test changes nothing a reader can see; the requirement is about
   what Observer and the operator Dashboard actually surface, so the proof has to go through the
   real read path and end at a real persisted file.
2. The check-id keyspace was unified while `flow`, `allowed_interaction_mode`, `stop_boundaries`
   and the `stage3_selective` decision kept asserting an interactive vertical scenario. `engine.py`
   runs `_explore_flow()` only when `business_flow` is in the run's `check_families`, so for a run
   configured without it the plan claims a scenario the runtime never attempts — the same untruth,
   one field over.

The legacy fixture below is not invented: it is the exact `to_dict()` of the base commit's own
planner (`9196efb`, `plan_target(depth="selective")` for a hospitality profile).

Not in scope: adding the two missing executors, migrating persisted artifacts, letting a plan drive
execution, or changing the client ZIP.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.scout.campaign_service import CampaignService
from core.scout.checks import CHECK_REGISTRY
from core.scout.observer_api import ObserverAPI
from core.scout.target_planner import plan_target
from core.scout.verticals import profile_for_industry

_CAMPAIGN = "campaign-m6legacy-20260731t120000z-aa11bb"
_DOMAIN = "legacy.test"

# Produced by the pre-M6 planner itself, not hand-written. Every selected name is foreign to
# `CHECK_REGISTRY`, and one of them is a flow label wearing a check-family identifier.
_LEGACY_PLAN = {
    "allowed_interaction_mode": "public_reversible",
    "archetype": "commercial_product_company",
    "checks_selected": [
        "reachability", "navigation_links", "console_errors", "network_failures",
        "accessibility_axe", "rendered_performance", "seo_metadata",
        "passive_security_headers", "mobile_responsive", "content_anomalies",
        "browser_flow:form_validation",
    ],
    "checks_skipped": [],
    "cleanup_required": False,
    "decisions": [
        "stage1_baseline: lightweight checks on a sufficiently promising target",
        "stage3_selective: explore only the form_validation flow; stop before submit, send message",
        "time_cap=180s",
    ],
    "depth": "selective",
    "domain": _DOMAIN,
    "evidence_requirements": ["screenshots", "console", "network", "dom_state"],
    "flow": "form_validation",
    "max_duration_s": 180,
    "stop_boundaries": ["submit", "send message"],
}


def _seed_legacy_brain(tmp_path: Path, plan: dict | None = None) -> Path:
    """Write a real `BRAIN_DECISIONS.json` exactly where the product looks for one."""
    path = Path(tmp_path) / "scout" / "_campaigns" / _CAMPAIGN / "BRAIN_DECISIONS.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "campaign_id": _CAMPAIGN,
        "at": "2026-07-30T12:00:00+00:00",
        "allocator": {"browser_tested": 1, "deep_tested": 0},
        "decisions": [{
            "domain": _DOMAIN,
            "priority": "A",
            "allocation": {"depth": "selective", "reasons": ["opportunity"]},
            "brain": {"summary": "legacy record"},
            "plan": dict(_LEGACY_PLAN if plan is None else plan),
            "scout_run": "scout-20260730t120000z-legacy",
        }],
    }
    path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _assert_labelled(plan: object, where: str) -> None:
    assert isinstance(plan, dict), f"{where}: no plan was surfaced at all ({plan!r})"
    assert plan.get("legacy_vocabulary") is True, (
        f"{where}: a pre-M6 plan is surfaced without `legacy_vocabulary`, so a reviewer reads its "
        f"eleven unexecutable names as coverage. Surfaced: {sorted(plan)}"
    )
    assert plan.get("coverage_verified") is False, (
        f"{where}: the plan is not marked unverified, so the names read as checks that ran"
    )
    unresolved = plan.get("unresolved_checks") or []
    assert set(unresolved) == set(_LEGACY_PLAN["checks_selected"]), (
        f"{where}: the gap is not surfaced as the gap it is: {unresolved}"
    )


# --- blocker 1: the label must exist on the product read path, not only in a helper ---------------

def test_target_detail_surfaces_a_legacy_plan_as_unverified(tmp_path):
    """`CampaignService.target_detail()` is what the Dashboard target card is built from."""
    _seed_legacy_brain(tmp_path)
    detail = CampaignService(str(tmp_path)).target_detail(_DOMAIN)
    _assert_labelled((detail.get("brain") or {}).get("plan"), "CampaignService.target_detail")


def test_observer_get_target_test_plan_surfaces_a_legacy_plan_as_unverified(tmp_path):
    """The MCP surface an external reviewer reads. This is the one the audit is really about."""
    _seed_legacy_brain(tmp_path)
    payload = ObserverAPI(str(tmp_path)).get_target_test_plan(_DOMAIN)
    _assert_labelled(payload.get("plan"), "ObserverAPI.get_target_test_plan")


def test_observer_target_and_decision_history_surface_the_same_label(tmp_path):
    """Two more readers of the same decision; a label on one surface only is a half-fix."""
    _seed_legacy_brain(tmp_path)
    api = ObserverAPI(str(tmp_path))
    _assert_labelled(((api.get_target(_DOMAIN).get("brain")) or {}).get("plan"),
                     "ObserverAPI.get_target")
    _assert_labelled(((api.get_target_decision_history(_DOMAIN).get("decision")) or {}).get("plan"),
                     "ObserverAPI.get_target_decision_history")


def test_the_exported_review_bundles_carry_the_label_too(tmp_path):
    """The campaign-wide readers go through a second physical loader, so they need proving too."""
    _seed_legacy_brain(tmp_path)
    svc = CampaignService(str(tmp_path))

    bundle = json.loads(Path(svc.export_bundle(_CAMPAIGN)).read_text(encoding="utf-8"))
    decisions = (bundle.get("brain_decisions") or {}).get("decisions") or []
    assert decisions, "the evidence bundle carried no decisions to check"
    _assert_labelled(decisions[0].get("plan"), "CampaignService.export_bundle")

    # The returned path is deliberately relative to the output root: `ObserverAPI._relativize`
    # never hands an absolute local path to an MCP client.
    written = ObserverAPI(str(tmp_path)).export_ai_review_bundle(_CAMPAIGN)
    payload = json.loads((Path(tmp_path) / written["json"]).read_text(encoding="utf-8"))
    ai_decisions = (payload.get("brain_decisions") or {}).get("decisions") or []
    assert ai_decisions, "the AI review bundle carried no decisions to check"
    _assert_labelled(ai_decisions[0].get("plan"), "ObserverAPI.export_ai_review_bundle")


def test_labelling_never_edits_the_persisted_record(tmp_path):
    """History is evidence. Reading it through every surface must not move a single byte."""
    path = _seed_legacy_brain(tmp_path)
    before, before_mtime = path.read_bytes(), path.stat().st_mtime_ns

    svc, api = CampaignService(str(tmp_path)), ObserverAPI(str(tmp_path))
    svc.target_detail(_DOMAIN)
    api.get_target(_DOMAIN)
    api.get_target_test_plan(_DOMAIN)
    api.get_target_decision_history(_DOMAIN)
    svc.export_bundle(_CAMPAIGN)
    api.export_ai_review_bundle(_CAMPAIGN)

    assert path.read_bytes() == before, "the persisted brain record was rewritten"
    assert path.stat().st_mtime_ns == before_mtime, "the persisted brain record was re-written"
    stored = json.loads(before.decode("utf-8"))["decisions"][0]["plan"]
    assert stored["checks_selected"] == _LEGACY_PLAN["checks_selected"]
    assert "legacy_vocabulary" not in stored, (
        "the derived label leaked into the stored artifact; it belongs to the projection only"
    )


def test_a_current_plan_read_back_is_not_labelled_legacy(tmp_path):
    """The counterpart, so 'unverified' cannot quietly become a blanket disclaimer on everything."""
    fresh = plan_target(domain=_DOMAIN, profile=profile_for_industry("hospitality"),
                        depth="selective",
                        selected_families=["links", "seo", "business_flow"]).to_dict()
    _seed_legacy_brain(tmp_path, plan=fresh)
    surfaced = ObserverAPI(str(tmp_path)).get_target_test_plan(_DOMAIN).get("plan") or {}
    assert surfaced.get("legacy_vocabulary") is False, "a v2 plan is disclaimed as legacy"
    assert surfaced.get("coverage_verified") is True
    assert not (surfaced.get("unresolved_checks") or [])


# --- blocker 2: flow metadata is a coverage claim and obeys the same rule -------------------------

def _flow_is_claimed(plan: dict) -> bool:
    """Any assertion in the plan that an interactive vertical scenario is part of this run."""
    return bool(
        plan.get("flow") not in ("", "passive", None)
        or plan.get("stop_boundaries")
        or plan.get("cleanup_required")
        or plan.get("allowed_interaction_mode") not in ("public_passive", "", None)
        or any(str(d).startswith("vertical_scenario") for d in plan.get("decisions", []))
    )


@pytest.mark.parametrize("industry", ["hospitality", "ecommerce", "saas"])
@pytest.mark.parametrize("depth", ["baseline", "selective", "deep"])
@pytest.mark.parametrize("families", [
    [], ["links"], ["links", "seo"], sorted(set(CHECK_REGISTRY) - {"business_flow"}),
    ["links", "business_flow"], sorted(CHECK_REGISTRY),
])
def test_an_interactive_flow_is_claimed_only_when_its_executor_was_selected(industry, depth,
                                                                           families):
    """The general rule, not two examples.

    `engine.py` calls `_explore_flow()` iff `business_flow` is in the run's `check_families`. The
    plan may therefore describe a vertical scenario under exactly the same condition — at a depth
    that reaches stage 3. Anything else is a coverage claim about something that will not happen.
    """
    plan = plan_target(domain="example.test", profile=profile_for_industry(industry), depth=depth,
                       selected_families=families).to_dict()
    runs_flow = "business_flow" in plan.get("checks_selected", [])
    assert _flow_is_claimed(plan) == runs_flow, (
        f"{industry}/{depth}/{families}: the plan claims flow="
        f"{plan.get('flow')!r} boundaries={plan.get('stop_boundaries')} "
        f"mode={plan.get('allowed_interaction_mode')!r} cleanup={plan.get('cleanup_required')} "
        f"while checks_selected={plan.get('checks_selected')}"
    )


def test_a_selective_run_without_business_flow_claims_no_scenario():
    """The reviewer's exact reproduction, pinned as its own case."""
    plan = plan_target(domain="example.test", profile=profile_for_industry("hospitality"),
                       depth="selective", selected_families=["links", "seo"]).to_dict()
    assert plan["checks_selected"] == ["links", "seo"]
    assert plan["flow"] == "passive"
    assert plan["stop_boundaries"] == []
    assert plan["cleanup_required"] is False
    assert plan["allowed_interaction_mode"] == "public_passive"
    assert not [d for d in plan["decisions"] if str(d).startswith("vertical_scenario")], (
        f"the plan still narrates a vertical scenario: {plan['decisions']}"
    )


def test_the_absent_flow_is_explained_rather_than_left_blank():
    """A silently passive plan reads as 'this vertical has no flow', which is a different claim."""
    plan = plan_target(domain="example.test", profile=profile_for_industry("ecommerce"),
                       depth="deep", selected_families=["links"]).to_dict()
    assert any("business_flow" in str(d) for d in plan["decisions"]), (
        f"nothing says why a deep target has no interactive flow: {plan['decisions']}"
    )


def test_a_passive_archetype_is_not_described_as_having_skipped_a_scenario():
    """A third distinct cause. `FLOW_PASSIVE` verticals never had an interactive scenario at all."""
    from core.scout.presets import SITE_TYPE_PERSONAL
    from core.scout.verticals import select_profile

    plan = plan_target(domain="example.test", profile=select_profile(SITE_TYPE_PERSONAL),
                       depth="selective", selected_families=["links"]).to_dict()
    assert not _flow_is_claimed(plan)
    said = " ".join(str(d) for d in plan["decisions"])
    assert "the passive scenario" not in said, (
        f"the plan names a 'passive scenario' as though one existed and was passed over: "
        f"{plan['decisions']}"
    )
    assert "no vertical scenario" in said, f"the real state is not stated: {plan['decisions']}"


# The round-2 case for an operator `qa_exclude` that removed `business_flow` is gone with the
# parameter itself. On a record written after the run, subtracting a family the engine had already
# executed could only make the artifact lie, and nothing in the product ever passed it — see
# `plan_target`'s docstring and round 3's `test_m6_plan_is_a_post_run_record`.


def test_a_selective_run_with_business_flow_still_gets_its_vertical_scenario():
    """The positive counterpart: this fix must not silently disable the feature it bounds."""
    profile = profile_for_industry("ecommerce")
    plan = plan_target(domain="example.test", profile=profile, depth="selective",
                       selected_families=["links", "business_flow"]).to_dict()
    assert plan["flow"] == profile.flow
    assert plan["stop_boundaries"] == list(profile.stop_boundaries)
    assert plan["allowed_interaction_mode"] == profile.interaction_mode
    assert any(str(d).startswith("vertical_scenario") for d in plan["decisions"])
    assert plan["cleanup_required"] is (profile.flow == "reversible_cart")
