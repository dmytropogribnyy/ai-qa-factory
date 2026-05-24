import os
from pathlib import Path

from core.config import Settings, MODEL_PROFILES
from core.llm_router import LLMRouter


def test_v508_docs_exist():
    assert Path("docs/MODEL_ROUTING_PROFILES.md").exists()
    assert Path("docs/REAL_TESTING_PREPARATION.md").exists()
    assert Path("docs/V508_MODEL_ROUTING_NOTES.md").exists()


def test_readme_mentions_v508_model_routing():
    text = Path("README.md").read_text(encoding="utf-8")
    assert "v5.0.8 model routing profiles" in text.lower()
    assert "premium_hybrid" in text


def test_main_version_label_v508():
    text = Path("main.py").read_text(encoding="utf-8")
    assert "v5.0.8" in text


def test_premium_hybrid_profile_routes_expected_models(monkeypatch):
    monkeypatch.setenv("MODEL_PROFILE", "premium_hybrid")
    monkeypatch.setenv("LLM_MODE", "real")
    settings = Settings()
    assert settings.architect_model == "gpt-5.5"
    assert settings.coding_model == "anthropic/claude-sonnet-4-6"
    assert settings.review_model == "anthropic/claude-opus-4-7"
    assert settings.fast_model == "anthropic/claude-sonnet-4-6"
    assert settings.vision_model == "gpt-5.5"
    assert settings.fallback_model == "gpt-5.4-mini"
    assert settings.review_effort == "xhigh"


def test_llm_router_task_aliases_use_role_routing(monkeypatch):
    monkeypatch.setenv("MODEL_PROFILE", "premium_hybrid")
    monkeypatch.setenv("LLM_MODE", "real")
    settings = Settings()
    router = LLMRouter(settings)
    assert router.route("prescreen") == "gpt-5.5"
    assert router.route("playwright") == "anthropic/claude-sonnet-4-6"
    assert router.route("quality_gate") == "anthropic/claude-opus-4-7"
    assert router.route("proposal") == "anthropic/claude-sonnet-4-6"


# ---------------------------------------------------------------------------
# Prompt-profile mapping regression tests
# ---------------------------------------------------------------------------

def test_opportunity_profile_map_covers_all_expected_types():
    from agents.capability_router import CapabilityRouterAgent
    m = CapabilityRouterAgent.OPPORTUNITY_PROFILE_MAP
    assert m["saas_multi_tenant_billing_auth_audit"] == "saas_multi_tenant_billing_auth"
    assert m["ai_native_exploratory_qa"] == "ai_native_exploratory"
    assert m["flaky_regression_automation"] == "flaky_tests"
    assert m["technical_writing"] == "technical_writing"
    assert m["react_native_maestro_qa"] == "mobile_release_qa"
    for skip_type in ("tosca_advisory", "risky_identity_or_deposit_test",
                      "low_value_usability_test", "developer_only_not_core"):
        assert m[skip_type] == "skip_or_not_fit", f"{skip_type} should map to skip_or_not_fit"


def test_saas_billing_job_with_flaky_mention_resolves_correct_profile(tmp_path, monkeypatch):
    """Regression: SaaS billing/auth audit job that also mentions 'flaky' and 'CI'
    must end with prompt_profile=saas_multi_tenant_billing_auth, not flaky_tests."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    from core.config import get_settings
    from core.orchestrator import QAFactoryOrchestrator

    job_text = (
        "We need a Senior QA Automation Engineer to build Playwright tests for our SaaS web "
        "application. Stack: React frontend, REST API, GitHub Actions. We have flaky regression "
        "tests and want reliable smoke coverage for login, dashboard, billing and user management. "
        "TypeScript preferred. Need someone who can review current CI and recommend improvements."
    )
    settings = get_settings()
    state = QAFactoryOrchestrator(settings).run("prescreen", job_text, source_platform_override="upwork")
    assert state.opportunity_type == "saas_multi_tenant_billing_auth_audit", (
        f"opportunity_type was {state.opportunity_type!r}"
    )
    assert state.prompt_profile == "saas_multi_tenant_billing_auth", (
        f"prompt_profile was {state.prompt_profile!r} — expected saas_multi_tenant_billing_auth. "
        "Billing/auth SaaS jobs that mention 'flaky' or 'CI' must not get the flaky_tests profile."
    )


def test_purely_flaky_test_job_still_resolves_flaky_profile(tmp_path, monkeypatch):
    """A job that is specifically about fixing unstable/flaky tests and mentions no billing
    should still resolve to flaky_tests / flaky_regression_automation."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    from core.config import get_settings
    from core.orchestrator import QAFactoryOrchestrator

    job_text = (
        "Our Cypress tests are extremely flaky and unstable. We need someone to audit the "
        "failing test suite, identify root causes of flakiness, and stabilize the most critical "
        "regression flows. Pure test stability work only."
    )
    settings = get_settings()
    state = QAFactoryOrchestrator(settings).run("prescreen", job_text)
    assert state.opportunity_type == "flaky_regression_automation", (
        f"opportunity_type was {state.opportunity_type!r}"
    )
    assert state.prompt_profile == "flaky_tests", (
        f"prompt_profile was {state.prompt_profile!r}"
    )


def test_capability_router_profile_map_is_source_of_truth(tmp_path, monkeypatch):
    """CapabilityRouterAgent.run() must overwrite any first-pass prompt_profile
    set by InitialAnalysisEngine with the value from OPPORTUNITY_PROFILE_MAP."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    from core.config import get_settings
    from core.state import QAFactoryState
    from agents.capability_router import CapabilityRouterAgent

    state = QAFactoryState(
        project_id="test-proj",
        mode="prescreen",
        raw_input="Multi-tenant SaaS billing and stripe integration QA audit",
    )
    state.prompt_profile = "flaky_tests"  # simulate wrong first-pass value
    settings = get_settings()
    agent = CapabilityRouterAgent()
    state = agent.run(state)
    assert state.opportunity_type == "saas_multi_tenant_billing_auth_audit"
    assert state.prompt_profile == "saas_multi_tenant_billing_auth", (
        f"CapabilityRouterAgent did not reconcile prompt_profile; got {state.prompt_profile!r}"
    )


# ---------------------------------------------------------------------------
# P1 / P3 / P4 / P2 regression tests
# ---------------------------------------------------------------------------

def test_api_only_brief_classified_as_api_testing():
    """A REST/OpenAPI API-only brief must get opportunity_type=api_testing (P1)."""
    from agents.capability_router import CapabilityRouterAgent
    text = (
        "REST API testing for a product catalog. OpenAPI 3.0 spec provided. "
        "Endpoints: GET /products, POST /orders. Bearer token auth. "
        "No UI work. Expected output: api test coverage report."
    )
    result = CapabilityRouterAgent._detect_type(text.lower())
    assert result == "api_testing", f"Expected api_testing, got {result!r}"


def test_api_testing_maps_to_qa_automation_profile():
    """OPPORTUNITY_PROFILE_MAP must map api_testing → qa_automation (P1)."""
    from agents.capability_router import CapabilityRouterAgent
    assert CapabilityRouterAgent.OPPORTUNITY_PROFILE_MAP["api_testing"] == "qa_automation"


def test_api_testing_support_level_is_strong():
    """api_testing must have strong_execution support level (P1)."""
    from agents.capability_router import CapabilityRouterAgent
    level = CapabilityRouterAgent._support_level("api_testing", "")
    assert level == "strong_execution", f"Expected strong_execution, got {level!r}"


def test_ecommerce_stripe_not_saas_billing(tmp_path, monkeypatch):
    """E-commerce Stripe checkout brief must NOT become saas_multi_tenant_billing_auth_audit (P3)."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    from core.config import get_settings
    from core.orchestrator import QAFactoryOrchestrator

    brief = (
        "E-commerce QA audit — demo staging only. Checkout uses Stripe in test mode. "
        "Cart, checkout flow, order confirmation. No real payments. Stack: React, Node, PostgreSQL."
    )
    settings = get_settings()
    state = QAFactoryOrchestrator(settings).run("prescreen", brief)
    assert state.opportunity_type != "saas_multi_tenant_billing_auth_audit", (
        f"E-commerce Stripe brief should not be saas_multi_tenant; got {state.opportunity_type!r}"
    )


def test_saas_multitenant_still_detected_after_p3(tmp_path, monkeypatch):
    """SaaS multi-tenant billing brief must still get saas_multi_tenant_billing_auth_audit after P3 (regression)."""
    monkeypatch.setenv("OUTPUT_DIR", str(tmp_path / "outputs"))
    from core.config import get_settings
    from core.orchestrator import QAFactoryOrchestrator

    brief = (
        "Multi-tenant B2B SaaS QA audit. Test tenant isolation, role-based access control (RBAC), "
        "subscription plan enforcement, and billing edge cases. JWT and OAuth used for auth."
    )
    settings = get_settings()
    state = QAFactoryOrchestrator(settings).run("prescreen", brief)
    assert state.opportunity_type == "saas_multi_tenant_billing_auth_audit", (
        f"SaaS multi-tenant billing brief should be saas_multi_tenant_billing_auth_audit; got {state.opportunity_type!r}"
    )


def test_test_design_mode_triggers_strategy_agent():
    """test-design mode must make _should_generate() return True for TestStrategyAgent (P4)."""
    from agents.test_strategy_agent import TestStrategyAgent
    from core.state import QAFactoryState

    state = QAFactoryState(project_id="p", mode="test-design", raw_input="brief with no keywords")
    state.recommended_action = "strong_apply"
    assert TestStrategyAgent._should_generate(state), "TestStrategyAgent must generate in test-design mode"


def test_test_design_mode_triggers_plan_writer():
    """test-design mode must make _should_generate() return True for TestPlanWriterAgent (P4)."""
    from agents.test_plan_writer import TestPlanWriterAgent
    from core.state import QAFactoryState

    state = QAFactoryState(project_id="p", mode="test-design", raw_input="brief with no keywords")
    state.recommended_action = "strong_apply"
    assert TestPlanWriterAgent._should_generate(state), "TestPlanWriterAgent must generate in test-design mode"


def test_test_design_mode_triggers_case_writer():
    """test-design mode must make _should_generate() return True for TestCaseWriterAgent (P4)."""
    from agents.test_case_writer import TestCaseWriterAgent
    from core.state import QAFactoryState

    state = QAFactoryState(project_id="p", mode="test-design", raw_input="brief with no keywords")
    state.recommended_action = "strong_apply"
    assert TestCaseWriterAgent._should_generate(state), "TestCaseWriterAgent must generate in test-design mode"


def test_ecommerce_stripe_first_pass_not_saas_billing_profile():
    """_prompt_profile() must not classify a plain Stripe e-commerce brief as saas_multi_tenant_billing_auth (P3/IAE fix)."""
    from core.initial_analysis_engine import InitialAnalysisEngine
    text = "e-commerce qa. checkout uses stripe in test mode. cart, product listing. no real payments."
    profile = InitialAnalysisEngine._prompt_profile(text, "E-commerce web app", "playwright-ts")
    assert profile != "saas_multi_tenant_billing_auth", (
        f"Plain Stripe e-commerce brief set first-pass profile to {profile!r}; should be qa_automation"
    )
    assert profile == "qa_automation"


def test_mobile_viewport_does_not_trigger_mobile_risk_flag():
    """'mobile viewport' in a web brief must NOT trigger the native-mobile risk flag (P2)."""
    from core.initial_analysis_engine import InitialAnalysisEngine
    text = "responsive layout smoke (desktop + mobile viewport) using playwright"
    risks = InitialAnalysisEngine._detect_risks(text)
    mobile_flags = [r for r in risks if "Mobile testing" in r]
    assert not mobile_flags, f"Mobile viewport falsely triggered mobile risk flag: {mobile_flags}"


def test_react_native_triggers_mobile_risk_flag():
    """React Native / TestFlight / Maestro briefs must still trigger the mobile risk flag (P2)."""
    from core.initial_analysis_engine import InitialAnalysisEngine
    for keyword in ["react native", "testflight", "maestro", "ios simulator", "android"]:
        text = f"we need qa for our {keyword} app"
        risks = InitialAnalysisEngine._detect_risks(text)
        mobile_flags = [r for r in risks if "Mobile testing" in r]
        assert mobile_flags, f"'{keyword}' should trigger mobile risk flag but didn't"
