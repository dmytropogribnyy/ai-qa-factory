"""M6 — a persisted Target Test Plan may not name coverage that cannot run.

`target_planner._BASELINE_CHECKS` and `checks.CHECK_REGISTRY` share **no identifier at all**. The
audit reported two unexecutable names; the real state is that all ten planned names are foreign to
the executor keyspace, so nothing in a plan can be mechanically tied to what ran. `run_checks()`
silently ignores an unknown family, so the executor absorbs a bad name without complaint, and the
plan is published read-only through Observer — where a reviewer reads it as coverage.

Two further points, both from review rather than from me: deriving the plan from the whole registry
would only produce a tidier overstatement, because a run configured with a subset would still claim
families it never selected — the plan must bind to the promoted run's persisted `check_families`;
and `VerticalProfile.check_families` is a third vocabulary that must not stay unchecked.

Not in scope here: adding the two missing executors, making the plan drive execution, or migrating
any persisted artifact.
"""
from __future__ import annotations

import pytest

from core.scout.checks import CHECK_REGISTRY
from core.scout.config import CHECK_FAMILIES
from core.scout.target_planner import plan_target
from core.scout.verticals import profile_for_industry

_UNSUPPORTED = ("passive_security_headers", "content_anomalies")


def _plan(**kw):
    profile = profile_for_industry("hospitality")
    args = {"domain": "example.test", "profile": profile, "depth": "selective",
            "max_target_duration_s": 180}
    args.update(kw)
    return plan_target(**args)


# --- one executable keyspace ---------------------------------------------------------------------

def test_every_selected_check_resolves_to_a_real_executor():
    """The headline defect: a plan naming checks nothing can run reads as coverage that never was."""
    plan = _plan(selected_families=sorted(CHECK_REGISTRY)).to_dict()
    unknown = [c for c in plan.get("checks_selected", []) if c not in CHECK_REGISTRY]
    assert not unknown, (
        f"the plan selects checks with no executor: {unknown}. `run_checks()` ignores an unknown "
        "family silently, so nothing downstream would ever have complained"
    )


def test_a_run_configured_with_a_subset_is_reflected_exactly():
    """Binding to the registry instead of the run would be a tidier overstatement, not a fix."""
    subset = ["links", "seo"]
    plan = _plan(selected_families=subset).to_dict()
    assert sorted(plan.get("checks_selected", [])) == sorted(subset), (
        f"the plan claims {sorted(plan.get('checks_selected', []))} for a run that selected "
        f"{sorted(subset)}; a plan that overstates the run it describes is the same defect in a "
        "neater vocabulary"
    )


def test_the_unsupported_pair_is_declared_not_covered_rather_than_selected_or_skipped():
    """No executor exists, so "skipped" would be a second untruth — and dropping it hides a gap."""
    plan = _plan(selected_families=sorted(CHECK_REGISTRY)).to_dict()
    for name in _UNSUPPORTED:
        assert name not in plan.get("checks_selected", []), f"{name} is claimed as coverage"
        assert name not in plan.get("checks_skipped", []), (
            f"{name} is reported as skipped, which says an executor exists and was not run"
        )
    declared = plan.get("declared_not_covered") or []
    names = {d.get("check") if isinstance(d, dict) else d for d in declared}
    assert set(_UNSUPPORTED) <= names, (
        f"the gap is not disclosed anywhere: {declared}. Silently dropping the pair narrows the "
        "advertised surface without admitting the product never had it"
    )


def test_a_precondition_is_not_dressed_up_as_a_check_family():
    """`reachability` gates the run; typing it as a selected family invents a check."""
    plan = _plan(selected_families=sorted(CHECK_REGISTRY)).to_dict()
    assert "reachability" not in plan.get("checks_selected", []), (
        "reachability is listed among executable checks, but it is a precondition and has no "
        "executor"
    )


def test_flow_metadata_never_enters_the_family_keyspace():
    """A vertical flow is scenario metadata; encoding it as a family id makes the keyspace lie again."""
    plan = _plan(selected_families=sorted(CHECK_REGISTRY)).to_dict()
    for value in plan.get("checks_selected", []):
        assert ":" not in value, f"{value!r} is a flow label wearing a check-family identifier"
        assert value in CHECK_REGISTRY


# --- drift guard: preventive, and it already passes ----------------------------------------------

def test_the_config_vocabulary_and_the_executor_registry_agree():
    """Guard, not part of the red proof — these two agree today.

    It exists because they are declared in different modules and nothing tied them together, which is
    precisely how the planner's third vocabulary drifted out of sight in the first place.
    """
    assert set(CHECK_FAMILIES) == set(CHECK_REGISTRY), (
        f"config-only: {sorted(set(CHECK_FAMILIES) - set(CHECK_REGISTRY))}; "
        f"registry-only: {sorted(set(CHECK_REGISTRY) - set(CHECK_FAMILIES))}"
    )


def test_the_vertical_profile_vocabulary_is_executable_or_absent():
    """The third vocabulary. Whatever it holds must resolve, or it must not claim to be families."""
    for industry in ("hospitality", "ecommerce", "saas"):
        profile = profile_for_industry(industry)
        families = tuple(getattr(profile, "check_families", ()) or ())
        unknown = [f for f in families if f not in CHECK_REGISTRY]
        assert not unknown, (
            f"{industry}: VerticalProfile.check_families names {unknown}, which no executor "
            "provides — a third vocabulary nobody checks"
        )


# --- history stays true without being rewritten --------------------------------------------------

def test_a_legacy_plan_is_labelled_unverified_rather_than_reinterpreted():
    """Persisted plans must not be silently re-read as executable coverage, nor rewritten."""
    from core.scout.target_planner import describe_persisted_plan

    legacy = {"domain": "old.test", "archetype": "hospitality", "depth": "selective",
              "checks_selected": ["accessibility_axe", "seo_metadata"], "checks_skipped": []}
    described = describe_persisted_plan(dict(legacy))

    assert described.get("coverage_verified") is False, (
        "a plan written in the pre-M6 vocabulary is presented as verified coverage"
    )
    assert described.get("legacy_vocabulary") is True
    unresolved = described.get("unresolved_checks") or []
    assert set(unresolved) == {"accessibility_axe", "seo_metadata"}, (
        f"the unexecutable names are not surfaced as the gap they are: {described}"
    )
    assert described.get("checks_selected") == legacy["checks_selected"], (
        "the persisted plan was rewritten; history must be labelled, never edited"
    )


def test_a_current_plan_is_not_labelled_legacy():
    """The counterpart, so 'legacy' cannot become a blanket disclaimer on everything."""
    from core.scout.target_planner import describe_persisted_plan

    fresh = _plan(selected_families=["links", "seo"]).to_dict()
    described = describe_persisted_plan(fresh)
    assert described.get("legacy_vocabulary") is False
    assert described.get("coverage_verified") is True
    assert not (described.get("unresolved_checks") or [])


def test_the_campaign_binds_the_plan_to_the_promoted_run_not_to_the_registry(tmp_path):
    """The substance of the fix: the plan describes THIS run, read from what that run persisted."""
    from core.scout.campaign_service import CampaignService
    from core.scout.store import RunStore

    run_id = "campaign-m6-20260731t180000z-aa11bb"
    store = RunStore(str(tmp_path), run_id)
    store.write_config({"campaign_name": "m6", "browser_mode": "static",
                        "check_families": ["links", "seo"]})

    families = CampaignService(str(tmp_path))._run_check_families(run_id)
    assert sorted(families) == ["links", "seo"], (
        f"the campaign did not read the promoted run's persisted selection: {families}"
    )
    plan = _plan(selected_families=families).to_dict()
    assert sorted(plan["checks_selected"]) == ["links", "seo"], (
        "the plan claims families the promoted run never selected"
    )


def test_an_unreadable_run_reports_an_unknown_selection_not_an_empty_one(tmp_path):
    """M6 round 4 — this used to assert `== []` and stop there, which was the whole problem.

    An empty list is a selection that was read and turned out empty; an unreadable config is the
    absence of any selection. Returning `[]` for both let a plan built from a config nobody could
    read be published as verified coverage of nothing. The helper now distinguishes them, and the
    product-level consequence is proved through `_persist_brain` -> Observer in
    `test_m6_unknown_selection_fails_closed`.
    """
    from core.scout.campaign_service import CampaignService
    from core.scout.store import RunStore

    svc = CampaignService(str(tmp_path))
    assert svc._run_check_families("no-such-run") is None
    assert svc._run_check_families("") is None

    run_id = "campaign-m6empty-20260731t180000z-aa11bb"
    RunStore(str(tmp_path), run_id).write_config(
        {"campaign_name": "m6", "browser_mode": "static", "check_families": []})
    assert svc._run_check_families(run_id) == [], (
        "a run that really did select nothing must stay distinguishable from one that could not be "
        "read at all"
    )


@pytest.mark.parametrize("depth", ["skip", "selective", "deep"])
def test_no_depth_produces_an_unexecutable_selection(depth):
    """Every depth, not just the one the happy path exercises."""
    plan = _plan(depth=depth, selected_families=sorted(CHECK_REGISTRY)).to_dict()
    for key in ("checks_selected", "checks_skipped"):
        unknown = [c for c in plan.get(key, []) if c not in CHECK_REGISTRY]
        assert not unknown, f"depth={depth}: {key} names non-executors {unknown}"
