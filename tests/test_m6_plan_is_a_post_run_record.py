"""M6, round 3 — the plan is written after the run, so it may not contradict what the run did.

`CampaignService._persist_brain()` is called on the line *after* `DiscoveryEngine(...).run()`
returns, and it builds a fresh `AdaptiveAllocator` there. That allocator appears nowhere in
`core/scout/engine.py` or `core/scout/discovery/engine.py` — it never gated a single check. So the
depth it produces is a retrospective assessment, and any field derived from it is a statement about
the past, not a plan for the future.

The engine's own gates are the only thing that decided coverage:

    run_checks(obs, ctx, cfg.check_families)                                   # every configured family
    self._explore_flow(obs) if "business_flow" in cfg.check_families else None # engine.py:344

Depth does not appear in either. A plan that removes `business_flow` from `checks_selected` and
files it under `checks_skipped` because a later allocator said "baseline" therefore denies work the
engine already did — twice, across both passes — while `coverage_verified` still reads true.

The same argument reaches one field further than the reported reproduction: gating the *flow*
metadata on depth is the identical mistake, because `engine.py:344` gates on the configured family
and nothing else.

Not in scope: adding executors, letting the plan drive execution, migrating persisted artifacts, or
changing the client ZIP.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.scout.campaign_service import CampaignService
from core.scout.observer_api import ObserverAPI
from core.scout.presets import build_config
from core.scout.store import RunStore
from core.scout.target_planner import plan_target
from core.scout.verticals import profile_for_industry

_RUN_WITH_FLOW = "scout-20260731t090000z-withflow"
_RUN_NO_FLOW = "scout-20260731t090000z-noflow"
_CONFIGURED = ["links", "seo", "business_flow"]


def _seed_run(tmp_path: Path, run_id: str, families: list) -> None:
    """A real run store whose persisted config is what the engine executed."""
    RunStore(str(tmp_path), run_id).write_config({
        "campaign_name": "m6-post-run", "browser_mode": "static", "check_families": list(families)})


def _promoted(domain: str, run_id: str, *, commercial: int, opportunity: int) -> dict:
    return {"promotion_decision": "promoted", "registrable_domain": domain,
            "commercial_score": commercial,
            "commercial_scorecard": {"dimensions": [{"name": "audit_opportunity",
                                                     "value": opportunity}]},
            "country_hint": "US", "business_name": domain.split(".")[0].title(),
            "industry_hint": "ecommerce", "reason_codes": ["pricing_page"],
            "promoted_scout_run": run_id}


def _run_the_real_boundary(tmp_path: Path) -> dict:
    """Drive `_persist_brain` exactly as `start_campaign` does, and return domain -> emitted plan."""
    _seed_run(tmp_path, _RUN_WITH_FLOW, _CONFIGURED)
    _seed_run(tmp_path, _RUN_NO_FLOW, ["links", "seo"])
    svc = CampaignService(output_dir=str(tmp_path))
    cfg = build_config("safe-live-acceptance", provider_allowlist=["tavily"],
                       output_dir=str(tmp_path), overrides={"strategy": "balanced"})
    state = {"candidates": [
        # Low opportunity -> the post-run allocator says baseline / skip, long after the engine ran.
        _promoted("baseline.test", _RUN_WITH_FLOW, commercial=48, opportunity=5),
        _promoted("skipped.test", _RUN_WITH_FLOW, commercial=20, opportunity=0),
        _promoted("noflow.test", _RUN_NO_FLOW, commercial=48, opportunity=5),
    ]}
    svc._persist_brain(cfg, state)
    api = ObserverAPI(str(tmp_path))
    return {d: (api.get_target_test_plan(d).get("plan") or {})
            for d in ("baseline.test", "skipped.test", "noflow.test")}


# --- the fixture must actually reproduce the condition, or it proves nothing ----------------------

def test_the_post_run_allocator_really_does_return_baseline_and_skip(tmp_path):
    """Guard on the setup itself: if these depths drift, the tests below stop testing anything."""
    plans = _run_the_real_boundary(tmp_path)
    assert plans["baseline.test"].get("depth") == "baseline", plans["baseline.test"].get("depth")
    assert plans["skipped.test"].get("depth") == "skip", plans["skipped.test"].get("depth")


# --- blocker: a retrospective depth may not deny executed coverage --------------------------------

def test_a_configured_executor_is_never_reported_skipped_by_a_post_run_depth(tmp_path):
    plan = _run_the_real_boundary(tmp_path)["baseline.test"]
    assert "business_flow" not in (plan.get("checks_skipped") or []), (
        "the plan reports business_flow as skipped, but the engine gates it on "
        "`business_flow in cfg.check_families` alone and ran it on both passes; the depth that "
        f"produced this claim was decided after the run: {plan.get('checks_skipped')}"
    )
    assert "business_flow" in (plan.get("checks_selected") or []), (
        f"the run configured business_flow and the record drops it: {plan.get('checks_selected')}"
    )


def test_a_skip_depth_does_not_erase_the_whole_selection(tmp_path):
    """The broader case: `DEPTH_SKIP` reported every configured executor as skipped."""
    plan = _run_the_real_boundary(tmp_path)["skipped.test"]
    assert sorted(plan.get("checks_selected") or []) == sorted(_CONFIGURED), (
        f"a post-run 'skip' assessment erased the run's whole selection: {plan}"
    )
    assert not (plan.get("checks_skipped") or []), (
        f"every configured executor is reported as skipped after the run already ran them: "
        f"{plan.get('checks_skipped')}"
    )


def test_the_flow_claim_follows_the_configuration_not_the_retrospective_depth(tmp_path):
    """`engine.py:344` gates the flow on the configured family and nothing else."""
    plan = _run_the_real_boundary(tmp_path)["baseline.test"]
    assert plan.get("flow") not in ("", "passive", None), (
        f"business_flow was configured, so the engine explored the vertical flow, but the record "
        f"denies it: flow={plan.get('flow')!r}"
    )
    assert plan.get("stop_boundaries"), "the explored flow's stop boundaries are not recorded"


def test_a_run_that_never_configured_the_flow_still_claims_none(tmp_path):
    """The negative case stays correct — this fix must not turn into a blanket flow claim."""
    plan = _run_the_real_boundary(tmp_path)["noflow.test"]
    assert plan.get("flow") in ("", "passive", None), f"flow={plan.get('flow')!r}"
    assert not plan.get("stop_boundaries")
    assert "business_flow" not in (plan.get("checks_selected") or [])
    assert "business_flow" not in (plan.get("checks_skipped") or [])


def test_the_emitted_record_is_still_current_schema_and_verified(tmp_path):
    """It must be fixed by telling the truth, not by demoting everything to 'unverified'."""
    for domain, plan in _run_the_real_boundary(tmp_path).items():
        assert plan.get("legacy_vocabulary") is False, domain
        assert plan.get("coverage_verified") is True, (domain, plan.get("unresolved_checks"))


def test_the_retrospective_depth_is_recorded_and_labelled_as_not_governing(tmp_path):
    """Keep the allocator's assessment — just stop it from rewriting what happened."""
    plan = _run_the_real_boundary(tmp_path)["skipped.test"]
    assert plan.get("depth") == "skip", "the assessment was deleted rather than explained"
    said = " ".join(str(d) for d in (plan.get("decisions") or []))
    assert "retrospective" in said, (
        f"nothing tells the reader the depth was decided after the run and gated nothing: "
        f"{plan.get('decisions')}"
    )


def test_the_persisted_brain_record_is_written_once_and_not_relabelled_on_disk(tmp_path):
    """The round-2 invariant still holds through this path: the projection stays a projection."""
    _run_the_real_boundary(tmp_path)
    paths = sorted((Path(tmp_path) / "scout" / "_campaigns").glob("*/BRAIN_DECISIONS.json"))
    assert paths, "the real boundary wrote no brain record at all"
    stored = json.loads(paths[0].read_text(encoding="utf-8"))
    for decision in stored["decisions"]:
        assert "legacy_vocabulary" not in decision["plan"], (
            "the derived label leaked into the persisted artifact"
        )


# --- the unit-level rule, independent of the campaign fixture -------------------------------------

def test_no_depth_moves_a_configured_executor_into_skipped():
    """Every depth, stated as a rule rather than as the two the reproduction happened to name."""
    for depth in ("skip", "baseline", "selective", "deep"):
        plan = plan_target(domain="example.test", profile=profile_for_industry("ecommerce"),
                           depth=depth, selected_families=_CONFIGURED).to_dict()
        assert sorted(plan["checks_selected"]) == sorted(_CONFIGURED), f"depth={depth}: {plan}"
        assert plan["checks_skipped"] == [], f"depth={depth}: {plan['checks_skipped']}"
        assert plan["flow"] not in ("", "passive", None), f"depth={depth}: flow was denied"
