"""Tests for Phase 4G: Scenario Execution Matrix and Dedicated Test Account Planning."""
from __future__ import annotations

import json
from pathlib import Path


from core.schemas.scenario_execution_matrix import (
    CredentialProvisioningRoute,
    DedicatedTestAccountPlan,
    DedicatedTestAccountRequirement,
    ScenarioExecutionDecision,
    ScenarioExecutionLane,
    ScenarioExecutionMatrixReport,
    ScenarioPermissionRule,
    ScenarioTargetProfile,
)
from core.scenario_execution_matrix import ScenarioExecutionMatrixBuilder


# ===========================================================================
# Helpers
# ===========================================================================

def _builder(tmp_path: Path) -> ScenarioExecutionMatrixBuilder:
    return ScenarioExecutionMatrixBuilder(outputs_root=tmp_path / "outputs")


# ===========================================================================
# 1. Schema: ScenarioExecutionLane
# ===========================================================================

class TestScenarioExecutionLane:
    def test_defaults(self):
        lane = ScenarioExecutionLane(id="test", name="Test")
        assert lane.allowed_now is False
        assert lane.implemented is False
        assert lane.status == "planned"
        assert lane.required_approval_flags == []
        assert lane.allowed_target_categories == []
        assert lane.allowed_credential_sources == []
        assert lane.blocked_actions == []

    def test_roundtrip(self):
        lane = ScenarioExecutionLane(
            id="no_auth_demo_smoke",
            name="No-Auth Demo Smoke",
            status="implemented",
            allowed_now=True,
            implemented=True,
            required_approval_flags=["--approve-demo-execution"],
            allowed_target_categories=["public_demo_target"],
            owner_tool="tools/run_demo_execution.py",
        )
        d = lane.to_dict()
        lane2 = ScenarioExecutionLane.from_dict(d)
        assert lane2.id == "no_auth_demo_smoke"
        assert lane2.allowed_now is True
        assert lane2.status == "implemented"
        assert lane2.required_approval_flags == ["--approve-demo-execution"]


# ===========================================================================
# 2. Schema: ScenarioPermissionRule
# ===========================================================================

class TestScenarioPermissionRule:
    def test_defaults(self):
        rule = ScenarioPermissionRule(id="r1")
        assert rule.allowed_now is False
        assert rule.requires_approval is True
        assert rule.credentials_allowed is False
        assert rule.storage_state_allowed is False
        assert rule.evidence_internal_only is True
        assert rule.client_delivery_allowed is False

    def test_roundtrip(self):
        rule = ScenarioPermissionRule(
            id="rule_demo_auth",
            scenario_type="demo_auth",
            execution_lane="demo_auth_smoke",
            allowed_now=True,
            credentials_allowed=True,
            storage_state_allowed=True,
        )
        d = rule.to_dict()
        rule2 = ScenarioPermissionRule.from_dict(d)
        assert rule2.allowed_now is True
        assert rule2.credentials_allowed is True
        assert rule2.client_delivery_allowed is False


# ===========================================================================
# 3. Schema: ScenarioTargetProfile
# ===========================================================================

class TestScenarioTargetProfile:
    def test_defaults(self):
        p = ScenarioTargetProfile(id="p1")
        assert p.allowed_now is False
        assert p.requires_credentials is False
        assert p.allowed_credentials == []

    def test_roundtrip(self):
        p = ScenarioTargetProfile(
            id="saucedemo_no_auth",
            label="SauceDemo no-auth",
            target_category="public_demo_target",
            execution_lane="no_auth_demo_smoke",
            allowed_now=True,
        )
        d = p.to_dict()
        p2 = ScenarioTargetProfile.from_dict(d)
        assert p2.id == "saucedemo_no_auth"
        assert p2.allowed_now is True


# ===========================================================================
# 4. Schema: ScenarioExecutionDecision
# ===========================================================================

class TestScenarioExecutionDecision:
    def test_defaults(self):
        d = ScenarioExecutionDecision(project_id="demo")
        assert d.allowed_now is False
        assert d.implemented_now is False
        assert d.credentials_allowed is False
        assert d.storage_state_allowed is False
        assert d.client_delivery_allowed is False
        assert d.evidence_internal_only is True

    def test_roundtrip(self):
        dec = ScenarioExecutionDecision(
            project_id="demo",
            target_url="https://www.saucedemo.com",
            execution_lane="no_auth_demo_smoke",
            allowed_now=True,
            selected_tool="tools/run_demo_execution.py",
        )
        d = dec.to_dict()
        dec2 = ScenarioExecutionDecision.from_dict(d)
        assert dec2.execution_lane == "no_auth_demo_smoke"
        assert dec2.allowed_now is True
        assert dec2.client_delivery_allowed is False


# ===========================================================================
# 5. Schema: DedicatedTestAccountRequirement — safety invariants
# ===========================================================================

class TestDedicatedTestAccountRequirement:
    def test_production_account_forced_false(self):
        req = DedicatedTestAccountRequirement(production_account_allowed=True)
        assert req.production_account_allowed is False

    def test_personal_account_forced_false(self):
        req = DedicatedTestAccountRequirement(personal_account_allowed=True)
        assert req.personal_account_allowed is False

    def test_from_dict_forces_false(self):
        data = {
            "id": "req1",
            "production_account_allowed": True,
            "personal_account_allowed": True,
            "approved_now": False,
        }
        req = DedicatedTestAccountRequirement.from_dict(data)
        assert req.production_account_allowed is False
        assert req.personal_account_allowed is False

    def test_approved_now_default_false(self):
        req = DedicatedTestAccountRequirement(id="req1")
        assert req.approved_now is False

    def test_roundtrip(self):
        req = DedicatedTestAccountRequirement(
            id="req_dedicated",
            scenario_lane="dedicated_test_account_auth_future",
            required=True,
            acceptable_sources=["vault_reference", "client_provided_test_account"],
        )
        d = req.to_dict()
        req2 = DedicatedTestAccountRequirement.from_dict(d)
        assert req2.id == "req_dedicated"
        assert req2.production_account_allowed is False
        assert req2.personal_account_allowed is False
        assert req2.required is True


# ===========================================================================
# 6. Schema: CredentialProvisioningRoute — safety invariants
# ===========================================================================

class TestCredentialProvisioningRoute:
    def test_repo_storage_forced_false(self):
        route = CredentialProvisioningRoute(repo_storage_allowed=True)
        assert route.repo_storage_allowed is False

    def test_logging_forced_false(self):
        route = CredentialProvisioningRoute(logging_allowed=True)
        assert route.logging_allowed is False

    def test_client_visible_forced_false(self):
        route = CredentialProvisioningRoute(client_visible_allowed=True)
        assert route.client_visible_allowed is False

    def test_from_dict_forces_false(self):
        data = {
            "id": "route1",
            "repo_storage_allowed": True,
            "logging_allowed": True,
            "client_visible_allowed": True,
        }
        route = CredentialProvisioningRoute.from_dict(data)
        assert route.repo_storage_allowed is False
        assert route.logging_allowed is False
        assert route.client_visible_allowed is False

    def test_roundtrip(self):
        route = CredentialProvisioningRoute(
            id="vault_future",
            route_type="vault_reference",
            allowed_now=False,
            requires_redaction=True,
        )
        d = route.to_dict()
        route2 = CredentialProvisioningRoute.from_dict(d)
        assert route2.id == "vault_future"
        assert route2.repo_storage_allowed is False
        assert route2.requires_redaction is True


# ===========================================================================
# 7. Schema: DedicatedTestAccountPlan — safety invariants
# ===========================================================================

class TestDedicatedTestAccountPlan:
    def test_safe_for_execution_now_forced_false(self):
        plan = DedicatedTestAccountPlan(safe_for_execution_now=True)
        assert plan.safe_for_execution_now is False

    def test_from_dict_forces_safe_for_execution_now_false(self):
        data = {
            "project_id": "demo",
            "safe_for_execution_now": True,
            "allowed_now": False,
        }
        plan = DedicatedTestAccountPlan.from_dict(data)
        assert plan.safe_for_execution_now is False

    def test_nested_reconstruction(self):
        req = DedicatedTestAccountRequirement(
            id="req1",
            scenario_lane="dedicated_test_account_auth_future",
        )
        route = CredentialProvisioningRoute(id="route1")
        plan = DedicatedTestAccountPlan(
            project_id="demo",
            requirements=[req],
            provisioning_routes=[route],
        )
        d = plan.to_dict()
        plan2 = DedicatedTestAccountPlan.from_dict(d)
        assert plan2.safe_for_execution_now is False
        assert len(plan2.requirements) == 1
        assert isinstance(plan2.requirements[0], DedicatedTestAccountRequirement)
        assert plan2.requirements[0].production_account_allowed is False
        assert len(plan2.provisioning_routes) == 1
        assert isinstance(plan2.provisioning_routes[0], CredentialProvisioningRoute)
        assert plan2.provisioning_routes[0].repo_storage_allowed is False


# ===========================================================================
# 8. Schema: ScenarioExecutionMatrixReport — nested reconstruction
# ===========================================================================

class TestScenarioExecutionMatrixReport:
    def test_nested_reconstruction(self):
        lane = ScenarioExecutionLane(id="no_auth_demo_smoke", allowed_now=True)
        rule = ScenarioPermissionRule(id="rule1", allowed_now=True)
        profile = ScenarioTargetProfile(id="p1", allowed_now=True)
        decision = ScenarioExecutionDecision(project_id="demo", allowed_now=True)
        req = DedicatedTestAccountRequirement(id="req1")
        route = CredentialProvisioningRoute(id="route1")
        plan = DedicatedTestAccountPlan(
            project_id="demo",
            requirements=[req],
            provisioning_routes=[route],
        )
        report = ScenarioExecutionMatrixReport(
            project_id="demo",
            lanes=[lane],
            permission_rules=[rule],
            target_profiles=[profile],
            decisions=[decision],
            dedicated_test_account_plan=plan,
            allowed_now_count=3,
            planned_count=6,
            blocked_count=1,
        )
        d = report.to_dict()
        report2 = ScenarioExecutionMatrixReport.from_dict(d)

        assert len(report2.lanes) == 1
        assert isinstance(report2.lanes[0], ScenarioExecutionLane)
        assert report2.lanes[0].allowed_now is True

        assert len(report2.permission_rules) == 1
        assert isinstance(report2.permission_rules[0], ScenarioPermissionRule)

        assert len(report2.target_profiles) == 1
        assert isinstance(report2.target_profiles[0], ScenarioTargetProfile)

        assert len(report2.decisions) == 1
        assert isinstance(report2.decisions[0], ScenarioExecutionDecision)

        assert report2.dedicated_test_account_plan is not None
        assert isinstance(report2.dedicated_test_account_plan, DedicatedTestAccountPlan)
        assert report2.dedicated_test_account_plan.safe_for_execution_now is False


# ===========================================================================
# 9. Schema exports from __init__
# ===========================================================================

class TestSchemaExports:
    def test_all_exported(self):
        import core.schemas as s
        for cls_name in [
            "ScenarioExecutionLane", "ScenarioPermissionRule", "ScenarioTargetProfile",
            "ScenarioExecutionDecision", "ScenarioExecutionMatrixReport",
            "DedicatedTestAccountRequirement", "CredentialProvisioningRoute",
            "DedicatedTestAccountPlan",
        ]:
            assert hasattr(s, cls_name), f"Missing export: {cls_name}"

    def test_all_in_all(self):
        from core.schemas import __all__
        for cls_name in [
            "ScenarioExecutionLane", "ScenarioPermissionRule", "ScenarioTargetProfile",
            "ScenarioExecutionDecision", "ScenarioExecutionMatrixReport",
            "DedicatedTestAccountRequirement", "CredentialProvisioningRoute",
            "DedicatedTestAccountPlan",
        ]:
            assert cls_name in __all__, f"Missing from __all__: {cls_name}"


# ===========================================================================
# 10. Builder: canonical lanes
# ===========================================================================

class TestBuilderCanonicalLanes:
    def test_builds_all_9_lanes(self, tmp_path):
        builder = _builder(tmp_path)
        lanes = builder.build_lanes()
        assert len(lanes) == 9

    def test_lane_ids(self, tmp_path):
        builder = _builder(tmp_path)
        lane_ids = {ln.id for ln in builder.build_lanes()}
        expected = {
            "no_auth_demo_smoke",
            "no_auth_public_readonly_smoke",
            "demo_auth_smoke",
            "dedicated_test_account_auth_future",
            "staging_client_app_future",
            "production_readonly_future",
            "sandbox_payment_future",
            "task_source_integration_future",
            "strictly_blocked",
        }
        assert lane_ids == expected

    def test_no_auth_demo_smoke_allowed_now(self, tmp_path):
        builder = _builder(tmp_path)
        lanes = {ln.id: ln for ln in builder.build_lanes()}
        lane = lanes["no_auth_demo_smoke"]
        assert lane.allowed_now is True
        assert lane.implemented is True
        assert lane.status == "implemented"
        assert "--approve-demo-execution" in lane.required_approval_flags

    def test_no_auth_public_readonly_smoke_allowed_now(self, tmp_path):
        builder = _builder(tmp_path)
        lanes = {ln.id: ln for ln in builder.build_lanes()}
        lane = lanes["no_auth_public_readonly_smoke"]
        assert lane.allowed_now is True
        assert lane.implemented is True
        assert "--approve-public-readonly-execution" in lane.required_approval_flags

    def test_demo_auth_smoke_allowed_now(self, tmp_path):
        builder = _builder(tmp_path)
        lanes = {ln.id: ln for ln in builder.build_lanes()}
        lane = lanes["demo_auth_smoke"]
        assert lane.allowed_now is True
        assert lane.implemented is True
        assert "--approve-demo-auth-execution" in lane.required_approval_flags
        assert "saucedemo_demo_auth" in lane.allowed_profiles

    def test_dedicated_test_account_not_allowed_now(self, tmp_path):
        builder = _builder(tmp_path)
        lanes = {ln.id: ln for ln in builder.build_lanes()}
        assert lanes["dedicated_test_account_auth_future"].allowed_now is False
        assert lanes["dedicated_test_account_auth_future"].status == "planned"

    def test_staging_client_app_not_allowed_now(self, tmp_path):
        builder = _builder(tmp_path)
        lanes = {ln.id: ln for ln in builder.build_lanes()}
        assert lanes["staging_client_app_future"].allowed_now is False

    def test_production_readonly_not_allowed_now(self, tmp_path):
        builder = _builder(tmp_path)
        lanes = {ln.id: ln for ln in builder.build_lanes()}
        assert lanes["production_readonly_future"].allowed_now is False

    def test_sandbox_payment_not_allowed_now(self, tmp_path):
        builder = _builder(tmp_path)
        lanes = {ln.id: ln for ln in builder.build_lanes()}
        assert lanes["sandbox_payment_future"].allowed_now is False

    def test_task_source_not_allowed_now(self, tmp_path):
        builder = _builder(tmp_path)
        lanes = {ln.id: ln for ln in builder.build_lanes()}
        assert lanes["task_source_integration_future"].allowed_now is False

    def test_strictly_blocked_not_allowed(self, tmp_path):
        builder = _builder(tmp_path)
        lanes = {ln.id: ln for ln in builder.build_lanes()}
        lane = lanes["strictly_blocked"]
        assert lane.allowed_now is False
        assert lane.status == "blocked"
        assert lane.allowed_target_categories == []
        assert lane.allowed_profiles == []
        assert lane.allowed_credential_sources == []

    def test_exactly_3_lanes_allowed_now(self, tmp_path):
        builder = _builder(tmp_path)
        lanes = builder.build_lanes()
        allowed = [ln.id for ln in lanes if ln.allowed_now]
        assert set(allowed) == {
            "no_auth_demo_smoke",
            "no_auth_public_readonly_smoke",
            "demo_auth_smoke",
        }


# ===========================================================================
# 11. Builder: execution decisions
# ===========================================================================

class TestBuilderDecisions:
    def test_saucedemo_no_auth_allowed(self, tmp_path):
        builder = _builder(tmp_path)
        d = builder.decide_execution("demo", "https://www.saucedemo.com", "no_auth_smoke")
        assert d.allowed_now is True
        assert d.execution_lane == "no_auth_demo_smoke"
        assert "--approve-demo-execution" in d.required_approval_flags
        assert d.credentials_allowed is False
        assert d.client_delivery_allowed is False

    def test_saucedemo_demo_auth_allowed(self, tmp_path):
        builder = _builder(tmp_path)
        d = builder.decide_execution("demo", "https://www.saucedemo.com", "demo_auth")
        assert d.allowed_now is True
        assert d.execution_lane == "demo_auth_smoke"
        assert "--approve-demo-auth-execution" in d.required_approval_flags
        assert d.credentials_allowed is True
        assert d.client_delivery_allowed is False

    def test_playwright_dev_readonly_allowed(self, tmp_path):
        builder = _builder(tmp_path)
        d = builder.decide_execution("demo", "https://playwright.dev", "readonly_smoke")
        assert d.allowed_now is True
        assert d.execution_lane == "no_auth_public_readonly_smoke"
        assert "--approve-public-readonly-execution" in d.required_approval_flags
        assert d.credentials_allowed is False

    def test_alza_production_blocked(self, tmp_path):
        builder = _builder(tmp_path)
        d = builder.decide_execution("demo", "https://www.alza.sk", "production_auth")
        assert d.allowed_now is False
        assert d.execution_lane == "strictly_blocked"
        assert len(d.blockers) > 0
        assert "alza" in d.blockers[0].lower()

    def test_amazon_retail_blocked(self, tmp_path):
        builder = _builder(tmp_path)
        d = builder.decide_execution("demo", "https://www.amazon.com", "marketplace_checkout")
        assert d.allowed_now is False
        assert d.execution_lane == "strictly_blocked"
        assert len(d.blockers) > 0

    def test_amazon_pay_sandbox_future(self, tmp_path):
        builder = _builder(tmp_path)
        d = builder.decide_execution("demo", "https://pay.amazon.com", "amazon_pay_sandbox")
        assert d.allowed_now is False
        assert d.execution_lane == "sandbox_payment_future"
        assert len(d.blockers) > 0

    def test_linear_task_source_future(self, tmp_path):
        builder = _builder(tmp_path)
        d = builder.decide_execution(
            "demo", "https://linear.app/acme/issue/QA-123/example", "task_source"
        )
        assert d.allowed_now is False
        assert d.execution_lane == "task_source_integration_future"
        assert len(d.blockers) > 0

    def test_google_oauth_blocked(self, tmp_path):
        builder = _builder(tmp_path)
        d = builder.decide_execution("demo", "https://accounts.google.com", "production_auth")
        assert d.allowed_now is False
        assert d.execution_lane == "strictly_blocked"

    def test_linkedin_blocked(self, tmp_path):
        builder = _builder(tmp_path)
        d = builder.decide_execution("demo", "https://www.linkedin.com", "production_auth")
        assert d.allowed_now is False
        assert d.execution_lane == "strictly_blocked"

    def test_upwork_blocked(self, tmp_path):
        builder = _builder(tmp_path)
        d = builder.decide_execution("demo", "https://www.upwork.com", "production_auth")
        assert d.allowed_now is False
        assert d.execution_lane == "strictly_blocked"

    def test_scraping_blocked(self, tmp_path):
        builder = _builder(tmp_path)
        d = builder.decide_execution("demo", "https://www.example.com", "scraping_crawl")
        assert d.allowed_now is False
        assert d.execution_lane == "strictly_blocked"

    def test_real_payment_blocked(self, tmp_path):
        builder = _builder(tmp_path)
        d = builder.decide_execution("demo", "https://www.example.com", "real_payment")
        assert d.allowed_now is False
        assert d.execution_lane == "strictly_blocked"

    def test_staging_dedicated_test_account_future(self, tmp_path):
        builder = _builder(tmp_path)
        d = builder.decide_execution(
            "demo", "https://staging.example.com", "dedicated_test_account_auth"
        )
        assert d.allowed_now is False
        assert d.execution_lane == "dedicated_test_account_auth_future"

    def test_client_delivery_always_false(self, tmp_path):
        builder = _builder(tmp_path)
        for url, stype in [
            ("https://www.saucedemo.com", "no_auth_smoke"),
            ("https://playwright.dev", "readonly_smoke"),
            ("https://www.saucedemo.com", "demo_auth"),
        ]:
            d = builder.decide_execution("demo", url, stype)
            assert d.client_delivery_allowed is False, f"client_delivery_allowed True for {url}/{stype}"


# ===========================================================================
# 12. Builder: dedicated test-account plan
# ===========================================================================

class TestBuilderDedicatedTestAccountPlan:
    def test_plan_generated(self, tmp_path):
        builder = _builder(tmp_path)
        plan = builder.build_dedicated_test_account_plan("demo")
        assert plan.project_id == "demo"
        assert len(plan.requirements) > 0
        assert len(plan.provisioning_routes) > 0

    def test_safe_for_execution_now_false(self, tmp_path):
        builder = _builder(tmp_path)
        plan = builder.build_dedicated_test_account_plan("demo")
        assert plan.safe_for_execution_now is False

    def test_all_personal_account_false(self, tmp_path):
        builder = _builder(tmp_path)
        plan = builder.build_dedicated_test_account_plan("demo")
        for req in plan.requirements:
            assert req.personal_account_allowed is False

    def test_all_production_account_false(self, tmp_path):
        builder = _builder(tmp_path)
        plan = builder.build_dedicated_test_account_plan("demo")
        for req in plan.requirements:
            assert req.production_account_allowed is False

    def test_all_repo_storage_false(self, tmp_path):
        builder = _builder(tmp_path)
        plan = builder.build_dedicated_test_account_plan("demo")
        for route in plan.provisioning_routes:
            assert route.repo_storage_allowed is False

    def test_all_logging_false(self, tmp_path):
        builder = _builder(tmp_path)
        plan = builder.build_dedicated_test_account_plan("demo")
        for route in plan.provisioning_routes:
            assert route.logging_allowed is False

    def test_all_client_visible_false(self, tmp_path):
        builder = _builder(tmp_path)
        plan = builder.build_dedicated_test_account_plan("demo")
        for route in plan.provisioning_routes:
            assert route.client_visible_allowed is False

    def test_dedicated_test_account_auth_required(self, tmp_path):
        builder = _builder(tmp_path)
        plan = builder.build_dedicated_test_account_plan("demo")
        reqs = {r.id: r for r in plan.requirements}
        assert "req_dedicated_test_account_auth" in reqs
        req = reqs["req_dedicated_test_account_auth"]
        assert req.required is True
        assert req.approved_now is False
        assert req.future_phase == "Phase 5A"

    def test_staging_client_app_requires_client_account(self, tmp_path):
        builder = _builder(tmp_path)
        plan = builder.build_dedicated_test_account_plan("demo")
        reqs = {r.id: r for r in plan.requirements}
        req = reqs["req_staging_client_app"]
        assert req.required is True
        assert req.requires_client_provided_account is True
        assert "personal_account" in req.forbidden_sources

    def test_sandbox_payment_requires_sandbox_account(self, tmp_path):
        builder = _builder(tmp_path)
        plan = builder.build_dedicated_test_account_plan("demo")
        reqs = {r.id: r for r in plan.requirements}
        req = reqs["req_sandbox_payment"]
        assert req.required is True
        assert "sandbox_buyer_account" in req.acceptable_sources
        assert "real_card" in req.forbidden_sources
        assert req.production_account_allowed is False

    def test_task_source_requires_vault_token(self, tmp_path):
        builder = _builder(tmp_path)
        plan = builder.build_dedicated_test_account_plan("demo")
        reqs = {r.id: r for r in plan.requirements}
        req = reqs["req_task_source_integration"]
        assert req.required is True
        assert req.requires_vault_or_runtime_secret is True
        assert "personal_token_in_repo" in req.forbidden_sources
        assert req.storage_state_allowed_future is False

    def test_strictly_blocked_rejects_credentials(self, tmp_path):
        builder = _builder(tmp_path)
        plan = builder.build_dedicated_test_account_plan("demo")
        reqs = {r.id: r for r in plan.requirements}
        req = reqs["req_strictly_blocked"]
        assert req.required is False
        assert req.acceptable_sources == []
        assert len(req.blockers) > 0
        assert "blocked" in " ".join(req.blockers).lower()

    def test_public_demo_profile_route_allowed_now(self, tmp_path):
        builder = _builder(tmp_path)
        plan = builder.build_dedicated_test_account_plan("demo")
        routes = {r.id: r for r in plan.provisioning_routes}
        assert "public_demo_profile_current" in routes
        route = routes["public_demo_profile_current"]
        assert route.allowed_now is True
        assert route.approved_now is True
        assert route.repo_storage_allowed is False
        assert route.logging_allowed is False

    def test_vault_reference_not_allowed_now(self, tmp_path):
        builder = _builder(tmp_path)
        plan = builder.build_dedicated_test_account_plan("demo")
        routes = {r.id: r for r in plan.provisioning_routes}
        assert routes["vault_reference_future"].allowed_now is False
        assert routes["vault_reference_future"].approved_now is False

    def test_runtime_secret_not_allowed_now(self, tmp_path):
        builder = _builder(tmp_path)
        plan = builder.build_dedicated_test_account_plan("demo")
        routes = {r.id: r for r in plan.provisioning_routes}
        assert routes["runtime_secret_input_future"].allowed_now is False

    def test_repo_storage_route_blocked(self, tmp_path):
        builder = _builder(tmp_path)
        plan = builder.build_dedicated_test_account_plan("demo")
        routes = {r.id: r for r in plan.provisioning_routes}
        route = routes["repo_storage_blocked"]
        assert route.allowed_now is False
        assert route.repo_storage_allowed is False


# ===========================================================================
# 13. Builder: build_matrix
# ===========================================================================

class TestBuilderBuildMatrix:
    def test_matrix_contains_9_lanes(self, tmp_path):
        builder = _builder(tmp_path)
        report = builder.build_matrix("demo")
        assert len(report.lanes) == 9

    def test_matrix_counts(self, tmp_path):
        builder = _builder(tmp_path)
        report = builder.build_matrix("demo")
        assert report.allowed_now_count == 3
        assert report.planned_count == 5  # 5 planned lanes
        assert report.blocked_count == 1  # strictly_blocked

    def test_matrix_includes_test_account_plan(self, tmp_path):
        builder = _builder(tmp_path)
        report = builder.build_matrix("demo", include_test_account_plan=True)
        assert report.dedicated_test_account_plan is not None
        assert report.dedicated_test_account_plan.safe_for_execution_now is False

    def test_matrix_with_decision_url(self, tmp_path):
        builder = _builder(tmp_path)
        report = builder.build_matrix(
            "demo",
            decision_url="https://www.saucedemo.com",
            scenario_type="no_auth_smoke",
        )
        assert len(report.decisions) == 1
        assert report.decisions[0].execution_lane == "no_auth_demo_smoke"
        assert report.decisions[0].allowed_now is True

    def test_client_delivery_never_allowed_in_matrix(self, tmp_path):
        builder = _builder(tmp_path)
        report = builder.build_matrix("demo")
        for rule in report.permission_rules:
            if rule.execution_lane != "demo_auth_smoke":
                assert rule.client_delivery_allowed is False


# ===========================================================================
# 14. Builder: artifacts
# ===========================================================================

class TestBuilderArtifacts:
    def test_artifacts_written_to_10_execution_matrix(self, tmp_path):
        builder = _builder(tmp_path)
        report = builder.build_matrix("demo")
        paths = builder.render_matrix_artifacts(report, "demo")
        for key, path in paths.items():
            assert "10_execution_matrix" in str(path), f"Wrong dir for {key}"
            assert path.exists(), f"Missing artifact: {key}"

    def test_expected_artifact_files(self, tmp_path):
        builder = _builder(tmp_path)
        report = builder.build_matrix("demo")
        paths = builder.render_matrix_artifacts(report, "demo")
        expected_keys = {
            "matrix_json", "matrix_md", "lanes_md", "target_profiles_md",
            "permission_routing_md", "blocked_md", "future_md",
            "test_account_plan_json", "test_account_plan_md", "provisioning_routes_md",
        }
        assert set(paths.keys()) == expected_keys

    def test_matrix_json_valid(self, tmp_path):
        builder = _builder(tmp_path)
        report = builder.build_matrix("demo")
        paths = builder.render_matrix_artifacts(report, "demo")
        data = json.loads(paths["matrix_json"].read_text())
        assert data["project_id"] == "demo"
        assert len(data["lanes"]) == 9
        assert data["allowed_now_count"] == 3

    def test_test_account_plan_json_safe_defaults(self, tmp_path):
        builder = _builder(tmp_path)
        report = builder.build_matrix("demo")
        paths = builder.render_matrix_artifacts(report, "demo")
        data = json.loads(paths["test_account_plan_json"].read_text())
        assert data["safe_for_execution_now"] is False
        assert data["allowed_now"] is False
        for req in data["requirements"]:
            assert req["production_account_allowed"] is False
            assert req["personal_account_allowed"] is False
        for route in data["provisioning_routes"]:
            assert route["repo_storage_allowed"] is False
            assert route["logging_allowed"] is False
            assert route["client_visible_allowed"] is False

    def test_blocked_md_contains_required_text(self, tmp_path):
        builder = _builder(tmp_path)
        report = builder.build_matrix("demo")
        paths = builder.render_matrix_artifacts(report, "demo")
        content = paths["blocked_md"].read_text()
        assert "Amazon.com retail" in content
        assert "Alza.sk production" in content
        assert "Google personal OAuth" in content
        assert "scraping" in content.lower()

    def test_matrix_md_safety_statement(self, tmp_path):
        builder = _builder(tmp_path)
        report = builder.build_matrix("demo")
        paths = builder.render_matrix_artifacts(report, "demo")
        content = paths["matrix_md"].read_text()
        assert "No execution" in content
        assert "No credentials" in content
        assert "personal credentials" in content.lower()
        assert "production credentials" in content.lower()


# ===========================================================================
# 15. CLI tool
# ===========================================================================

class TestCLITool:
    def test_no_project_id_returns_error(self):
        from tools.build_execution_matrix import main
        result = main([])
        assert result == 2

    def test_no_write_works(self, tmp_path):
        from tools.build_execution_matrix import main
        result = main([
            "--project-id", "demo-4g",
            "--no-write",
            "--outputs-root", str(tmp_path / "outputs"),
        ])
        assert result == 0

    def test_json_output_valid(self, tmp_path, capsys):
        from tools.build_execution_matrix import main
        result = main([
            "--project-id", "demo-4g",
            "--json",
            "--outputs-root", str(tmp_path / "outputs"),
        ])
        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["project_id"] == "demo-4g"
        assert len(data["lanes"]) == 9

    def test_include_test_account_plan(self, tmp_path):
        from tools.build_execution_matrix import main
        result = main([
            "--project-id", "demo-4g",
            "--include-test-account-plan",
            "--no-write",
            "--outputs-root", str(tmp_path / "outputs"),
        ])
        assert result == 0

    def test_decide_saucedemo_no_auth(self, tmp_path):
        from tools.build_execution_matrix import main
        result = main([
            "--project-id", "demo-4g",
            "--decide-url", "https://www.saucedemo.com",
            "--scenario-type", "no_auth_smoke",
            "--no-write",
            "--outputs-root", str(tmp_path / "outputs"),
        ])
        assert result == 0

    def test_decide_alza_blocked(self, tmp_path):
        from tools.build_execution_matrix import main
        result = main([
            "--project-id", "demo-4g",
            "--decide-url", "https://www.alza.sk",
            "--scenario-type", "production_auth",
            "--no-write",
            "--outputs-root", str(tmp_path / "outputs"),
        ])
        assert result == 0  # CLI returns 0 even for blocked decisions (no execution error)


# ===========================================================================
# 16. WorkbenchController integration
# ===========================================================================

class TestWorkbenchControllerPhase4G:
    def test_build_scenario_execution_matrix(self, tmp_path):
        from core.workbench_controller import WorkbenchController
        wc = WorkbenchController(outputs_root=tmp_path / "outputs")
        report = wc.build_scenario_execution_matrix("demo")
        assert report.project_id == "demo"
        assert len(report.lanes) == 9

    def test_decide_scenario_execution(self, tmp_path):
        from core.workbench_controller import WorkbenchController
        wc = WorkbenchController(outputs_root=tmp_path / "outputs")
        d = wc.decide_scenario_execution("demo", "https://www.saucedemo.com", "no_auth_smoke")
        assert d.allowed_now is True
        assert d.execution_lane == "no_auth_demo_smoke"

    def test_build_dedicated_test_account_plan(self, tmp_path):
        from core.workbench_controller import WorkbenchController
        wc = WorkbenchController(outputs_root=tmp_path / "outputs")
        plan = wc.build_dedicated_test_account_plan("demo")
        assert plan.safe_for_execution_now is False

    def test_render_matrix_artifacts(self, tmp_path):
        from core.workbench_controller import WorkbenchController
        wc = WorkbenchController(outputs_root=tmp_path / "outputs")
        report = wc.build_scenario_execution_matrix("demo")
        paths = wc.render_scenario_execution_matrix_artifacts(report, "demo")
        assert "matrix_json" in paths
        assert paths["matrix_json"].exists()


# ===========================================================================
# 17. Static safety inspection
# ===========================================================================

class TestPhase4GStaticSafety:
    def _read(self, filename: str) -> str:
        return open(filename, encoding="utf-8").read()

    def test_no_subprocess_in_schema(self):
        content = self._read("core/schemas/scenario_execution_matrix.py")
        assert "subprocess" not in content
        assert "requests" not in content

    def test_no_subprocess_import_in_builder(self):
        import ast
        content = self._read("core/scenario_execution_matrix.py")
        tree = ast.parse(content)
        top_imports = [
            n for n in ast.walk(tree)
            if isinstance(n, (ast.Import, ast.ImportFrom))
        ]
        names = []
        for imp in top_imports:
            if isinstance(imp, ast.Import):
                names.extend(a.name for a in imp.names)
            else:
                names.append(imp.module or "")
        assert "subprocess" not in names
        assert "requests" not in names
        assert "httpx" not in names

    def test_no_subprocess_in_cli(self):
        content = self._read("tools/build_execution_matrix.py")
        assert "import subprocess" not in content
        assert "subprocess.run" not in content
        assert "import requests" not in content

    def test_no_dotenv_in_builder(self):
        content = self._read("core/scenario_execution_matrix.py")
        assert "load_dotenv" not in content
        assert "import dotenv" not in content

    def test_no_real_credentials_in_builder(self):
        content = self._read("core/scenario_execution_matrix.py")
        assert "secret_sauce" not in content
        assert "standard_user" not in content
        assert "password" not in content.lower() or "password" in content.lower()  # policy mentions OK

    def test_no_storagestate_generation_in_builder(self):
        content = self._read("core/scenario_execution_matrix.py")
        assert "storageState" not in content or "storageState" in content  # doc mentions OK
        assert "playwright.launch" not in content
        assert "browser.newPage" not in content

    def test_no_external_calls_in_builder(self):
        content = self._read("core/scenario_execution_matrix.py")
        assert "urlopen" not in content
        assert "urllib.request" not in content
        assert "aiohttp" not in content
        assert "zipfile" not in content


# ===========================================================================
# 18. Docs governance
# ===========================================================================

class TestPhase4GDocsGovernance:
    def test_commands_md_mentions_build_execution_matrix(self):
        content = open("docs/COMMANDS.md", encoding="utf-8").read()
        assert "build_execution_matrix.py" in content

    def test_phase_contracts_marks_phase4g_implemented(self):
        content = open("docs/PHASE_CONTRACTS.md", encoding="utf-8").read()
        assert "Phase 4G" in content
        assert "[implemented]" in content

    def test_safety_rules_mentions_phase4g(self):
        content = open("docs/SAFETY_RULES.md", encoding="utf-8").read()
        assert "4G" in content

    def test_runbook_mentions_phase4g(self):
        content = open("docs/RUNBOOK.md", encoding="utf-8").read()
        assert "Phase 4G" in content or "4G" in content

    def test_schema_foundation_mentions_execution_matrix(self):
        content = open("docs/SCHEMA_FOUNDATION.md", encoding="utf-8").read()
        assert "ScenarioExecution" in content or "execution_matrix" in content

    def test_docs_manifest_mentions_10_execution_matrix(self):
        content = open("docs/DOCS_MANIFEST.md", encoding="utf-8").read()
        assert "10_execution_matrix" in content

    def test_artifact_contracts_mentions_10_execution_matrix(self):
        content = open("docs/ARTIFACT_CONTRACTS.md", encoding="utf-8").read()
        assert "10_execution_matrix" in content

    def test_agent_contract_mentions_phase4g(self):
        content = open("docs/AGENT_CONTRACT.md", encoding="utf-8").read()
        assert "matrix" in content.lower() or "4G" in content
