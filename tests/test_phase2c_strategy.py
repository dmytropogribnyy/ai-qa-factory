"""tests/test_phase2c_strategy.py — Phase 2C: QA Strategy Planner tests.

Verifies:
- QAStrategy schema serialization, nested reconstruction, safe defaults
- __init__.py exports
- QAStrategyPlanner per project type strategy areas
- Risk matrix coverage (auth/payment/prod/mobile/integration risks)
- Test layer recommendations per project type
- Tactical planning outline completeness
- Strategy decisions content
- Blueprint carry-forward (blocked_actions, required_approvals, missing_information)
- Safety boundary (no execution, no secrets, no external calls)
- WorkbenchController Phase 2C integration
- CLI / build_strategy.py basic operation
- Docs audit / agent readiness audit pass
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.schemas.project_blueprint import ProjectBlueprint  # noqa: E402
from core.schemas.qa_strategy import (  # noqa: E402
    QAStrategy,
    QAStrategyArea,
    RiskMatrixItem,
    StrategyDecision,
    TacticalPlanningItem,
    TestLayerRecommendation as LayerRec,
)
from core.qa_strategy_planner import QAStrategyPlanner  # noqa: E402
from core.workbench_controller import WorkbenchController  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_blueprint(
    project_type: str = "web_saas",
    environment: str = "staging",
    confidence: str = "medium",
    risk_areas: list | None = None,
    missing_info: list | None = None,
    blocked_actions: list | None = None,
    required_approvals: list | None = None,
    client_goal: str = "",
    scope_notes: str = "",
) -> ProjectBlueprint:
    return ProjectBlueprint(
        project_id="test-project",
        project_type=project_type,
        environment=environment,
        confidence_level=confidence,
        risk_areas=risk_areas or ["auth/session handling", "form validation"],
        missing_information=missing_info or ["Target URL", "Test credentials"],
        blocked_actions=blocked_actions or ["Execute browser tests — BLOCKED."],
        required_approvals=required_approvals or ["Target URL approval", "Staging approval"],
        client_goal=client_goal or "Ensure core application works correctly.",
        scope_notes=scope_notes,
        recommended_strategy="Focus on critical paths first.",
        tactical_test_focus=["auth/login smoke", "dashboard load"],
    )


_PLANNER = QAStrategyPlanner()


# ---------------------------------------------------------------------------
# TestQAStrategySchema
# ---------------------------------------------------------------------------

class TestQAStrategySchema:
    def test_qa_strategy_safe_defaults(self):
        s = QAStrategy(project_id="p1")
        assert s.project_type == "unknown"
        assert s.environment_type == "unknown"
        assert s.client_ready is False
        assert s.confidence_level == "medium"
        assert s.strategy_areas == []
        assert s.risk_matrix == []
        assert s.test_layers == []
        assert s.tactical_plan_outline == []
        assert s.strategy_decisions == []

    def test_qa_strategy_area_defaults(self):
        a = QAStrategyArea()
        assert a.blocked is False
        assert a.blocked_reason is None
        assert a.notes == []
        assert a.related_surfaces == []

    def test_risk_matrix_item_defaults(self):
        r = RiskMatrixItem()
        assert r.blocked is False
        assert r.approval_required is False
        assert r.notes == []

    def test_test_layer_defaults(self):
        t = LayerRec()
        assert t.recommended is True
        assert t.blocked is False
        assert t.blocked_reason is None
        assert t.examples == []

    def test_tactical_item_defaults(self):
        t = TacticalPlanningItem()
        assert t.blocked is False
        assert t.requires_approval is False
        assert t.future_artifact is None

    def test_strategy_decision_defaults(self):
        d = StrategyDecision()
        assert d.alternatives_considered == []
        assert d.notes == []

    def test_qa_strategy_serialization_roundtrip(self):
        s = QAStrategy(
            project_id="p1",
            project_type="web_saas",
            strategy_areas=[QAStrategyArea(id="sa-01", name="Smoke")],
            risk_matrix=[RiskMatrixItem(id="r-01", risk_area="Auth risk", severity="high")],
            test_layers=[LayerRec(id="l-01", layer="smoke", recommended=True)],
            tactical_plan_outline=[TacticalPlanningItem(id="tp-01", title="Plan auth tests")],
            strategy_decisions=[StrategyDecision(id="sd-01", decision="Playwright first")],
        )
        d = s.to_dict()
        s2 = QAStrategy.from_dict(d)
        assert s2.project_id == "p1"
        assert s2.project_type == "web_saas"
        assert len(s2.strategy_areas) == 1
        assert s2.strategy_areas[0].id == "sa-01"
        assert len(s2.risk_matrix) == 1
        assert s2.risk_matrix[0].severity == "high"
        assert len(s2.test_layers) == 1
        assert s2.test_layers[0].layer == "smoke"
        assert len(s2.tactical_plan_outline) == 1
        assert len(s2.strategy_decisions) == 1

    def test_nested_reconstruction_preserves_optional_none(self):
        s = QAStrategy(
            project_id="p1",
            strategy_areas=[QAStrategyArea(id="sa-01", blocked=True, blocked_reason=None)],
        )
        d = s.to_dict()
        s2 = QAStrategy.from_dict(d)
        assert s2.strategy_areas[0].blocked_reason is None
        assert s2.strategy_areas[0].blocked is True

    def test_client_ready_always_serializes_false(self):
        s = QAStrategy(project_id="p1", client_ready=False)
        d = s.to_dict()
        assert d["client_ready"] is False


# ---------------------------------------------------------------------------
# TestSchemaInitExports
# ---------------------------------------------------------------------------

class TestSchemaInitExports:
    def test_qa_strategy_exported(self):
        from core.schemas import QAStrategy as QAS
        assert QAS is QAStrategy

    def test_qa_strategy_area_exported(self):
        from core.schemas import QAStrategyArea as QASA
        assert QASA is QAStrategyArea

    def test_risk_matrix_item_exported(self):
        from core.schemas import RiskMatrixItem as RMI
        assert RMI is RiskMatrixItem

    def test_test_layer_recommendation_exported(self):
        from core.schemas.qa_strategy import TestLayerRecommendation
        from core.schemas import TestLayerRecommendation as TLR
        assert TLR is TestLayerRecommendation

    def test_tactical_planning_item_exported(self):
        from core.schemas import TacticalPlanningItem as TPI
        assert TPI is TacticalPlanningItem

    def test_strategy_decision_exported(self):
        from core.schemas import StrategyDecision as SD
        assert SD is StrategyDecision


# ---------------------------------------------------------------------------
# TestQAStrategyPlannerWebSaas
# ---------------------------------------------------------------------------

class TestQAStrategyPlannerWebSaas:
    _bp = _make_blueprint("web_saas", scope_notes="SaaS dashboard with login and user settings")

    def test_builds_strategy(self):
        st = _PLANNER.build_strategy(self._bp)
        assert st.project_type == "web_saas"
        assert st.project_id == "test-project"

    def test_has_smoke_area(self):
        st = _PLANNER.build_strategy(self._bp)
        names = [a.name.lower() for a in st.strategy_areas]
        assert any("smoke" in n or "critical" in n for n in names)

    def test_has_auth_area(self):
        st = _PLANNER.build_strategy(self._bp)
        names = [a.name.lower() for a in st.strategy_areas]
        assert any("auth" in n or "session" in n for n in names)

    def test_has_regression_area(self):
        st = _PLANNER.build_strategy(self._bp)
        names = [a.name.lower() for a in st.strategy_areas]
        assert any("regression" in n for n in names)

    def test_client_ready_false(self):
        st = _PLANNER.build_strategy(self._bp)
        assert st.client_ready is False

    def test_smoke_layer_recommended(self):
        st = _PLANNER.build_strategy(self._bp)
        layers = {t.layer: t for t in st.test_layers}
        assert "smoke" in layers
        assert layers["smoke"].recommended is True
        assert layers["smoke"].priority == "high"

    def test_mobile_native_blocked(self):
        st = _PLANNER.build_strategy(self._bp)
        layers = {t.layer: t for t in st.test_layers}
        assert "mobile_native" in layers
        assert layers["mobile_native"].blocked is True


# ---------------------------------------------------------------------------
# TestQAStrategyPlannerEcommerce
# ---------------------------------------------------------------------------

class TestQAStrategyPlannerEcommerce:
    _bp = _make_blueprint(
        "ecommerce",
        scope_notes="ecommerce shop with checkout and payment via Stripe",
        risk_areas=["checkout flow integrity", "payment flow (sandbox required)"],
    )

    def test_builds_strategy(self):
        st = _PLANNER.build_strategy(self._bp)
        assert st.project_type == "ecommerce"

    def test_has_payment_blocked_area(self):
        st = _PLANNER.build_strategy(self._bp)
        payment_areas = [a for a in st.strategy_areas if "payment" in a.name.lower()]
        assert len(payment_areas) >= 1
        assert all(a.blocked for a in payment_areas)

    def test_payment_risk_is_blocked(self):
        st = _PLANNER.build_strategy(self._bp)
        payment_risks = [r for r in st.risk_matrix if "payment" in r.risk_area.lower()]
        assert len(payment_risks) >= 1
        assert any(r.blocked or r.approval_required for r in payment_risks)

    def test_manual_exploratory_recommended(self):
        st = _PLANNER.build_strategy(self._bp)
        layers = {t.layer: t for t in st.test_layers}
        assert "manual_exploratory" in layers
        assert layers["manual_exploratory"].recommended is True


# ---------------------------------------------------------------------------
# TestQAStrategyPlannerApiBackend
# ---------------------------------------------------------------------------

class TestQAStrategyPlannerApiBackend:
    _bp = _make_blueprint(
        "api_backend",
        scope_notes="REST API backend with OpenAPI spec and JWT auth",
        risk_areas=["auth header validation", "schema contracts", "destructive endpoints"],
    )

    def test_builds_strategy(self):
        st = _PLANNER.build_strategy(self._bp)
        assert st.project_type == "api_backend"

    def test_has_contract_area(self):
        st = _PLANNER.build_strategy(self._bp)
        names = [a.name.lower() for a in st.strategy_areas]
        assert any("contract" in n or "schema" in n for n in names)

    def test_api_layer_recommended(self):
        st = _PLANNER.build_strategy(self._bp)
        layers = {t.layer: t for t in st.test_layers}
        assert "api" in layers
        assert layers["api"].recommended is True
        assert layers["api"].priority == "high"

    def test_contract_layer_recommended(self):
        st = _PLANNER.build_strategy(self._bp)
        layers = {t.layer: t for t in st.test_layers}
        assert "contract" in layers
        assert layers["contract"].recommended is True

    def test_destructive_endpoint_area_blocked(self):
        st = _PLANNER.build_strategy(self._bp)
        blocked_areas = [a for a in st.strategy_areas if a.blocked]
        assert len(blocked_areas) >= 1
        names = [a.name.lower() for a in blocked_areas]
        assert any("destructive" in n or "auth" in n for n in names)


# ---------------------------------------------------------------------------
# TestQAStrategyPlannerAiGeneratedApp
# ---------------------------------------------------------------------------

class TestQAStrategyPlannerAiGeneratedApp:
    _bp = _make_blueprint(
        "ai_generated_app",
        scope_notes="Lovable.dev generated app with auth and dashboard",
        risk_areas=["broken auth flows", "generated code fragility", "data persistence failures"],
    )

    def test_builds_strategy(self):
        st = _PLANNER.build_strategy(self._bp)
        assert st.project_type == "ai_generated_app"

    def test_has_exploratory_area(self):
        st = _PLANNER.build_strategy(self._bp)
        names = [a.name.lower() for a in st.strategy_areas]
        assert any("exploratory" in n or "edge" in n for n in names)

    def test_has_broken_route_area(self):
        st = _PLANNER.build_strategy(self._bp)
        names = [a.name.lower() for a in st.strategy_areas]
        assert any("broken" in n or "route" in n or "navigation" in n for n in names)

    def test_generated_code_fragility_risk(self):
        st = _PLANNER.build_strategy(self._bp)
        risk_areas = [r.risk_area.lower() for r in st.risk_matrix]
        assert any("generated" in r or "fragility" in r or "fragile" in r for r in risk_areas)


# ---------------------------------------------------------------------------
# TestQAStrategyPlannerAdminPanel
# ---------------------------------------------------------------------------

class TestQAStrategyPlannerAdminPanel:
    _bp = _make_blueprint(
        "admin_panel",
        scope_notes="admin panel with CRUD and role-based access control",
        risk_areas=["permission leaks", "destructive CRUD actions", "production data modification risk"],
    )

    def test_builds_strategy(self):
        st = _PLANNER.build_strategy(self._bp)
        assert st.project_type == "admin_panel"

    def test_has_role_access_area(self):
        st = _PLANNER.build_strategy(self._bp)
        names = [a.name.lower() for a in st.strategy_areas]
        assert any("role" in n or "access" in n for n in names)

    def test_destructive_action_blocked(self):
        st = _PLANNER.build_strategy(self._bp)
        blocked_areas = [a for a in st.strategy_areas if a.blocked]
        assert len(blocked_areas) >= 2

    def test_permission_leak_risk_is_critical(self):
        st = _PLANNER.build_strategy(self._bp)
        perm_risks = [r for r in st.risk_matrix if "permission" in r.risk_area.lower()]
        assert len(perm_risks) >= 1
        assert any(r.severity in ("high", "critical") for r in perm_risks)


# ---------------------------------------------------------------------------
# TestQAStrategyPlannerAuthHeavy
# ---------------------------------------------------------------------------

class TestQAStrategyPlannerAuthHeavy:
    _bp = _make_blueprint(
        "auth_heavy",
        scope_notes="login with 2FA TOTP and OAuth2 SSO, password reset via email",
        risk_areas=["credential safety", "2FA/email dependency", "account state changes"],
    )

    def test_builds_strategy(self):
        st = _PLANNER.build_strategy(self._bp)
        assert st.project_type == "auth_heavy"

    def test_has_2fa_blocked_area(self):
        st = _PLANNER.build_strategy(self._bp)
        blocked_areas = [a for a in st.strategy_areas if a.blocked]
        names_lower = [a.name.lower() for a in blocked_areas]
        assert any("2fa" in n or "otp" in n for n in names_lower)

    def test_credential_risk_is_blocked(self):
        st = _PLANNER.build_strategy(self._bp)
        cred_risks = [r for r in st.risk_matrix if "credential" in r.risk_area.lower()]
        assert len(cred_risks) >= 1
        assert all(r.blocked or r.approval_required for r in cred_risks)

    def test_auth_layer_is_recommended(self):
        st = _PLANNER.build_strategy(self._bp)
        layers = {t.layer: t for t in st.test_layers}
        assert "auth" in layers
        assert layers["auth"].recommended is True
        assert layers["auth"].priority == "high"

    def test_password_reset_area_blocked(self):
        st = _PLANNER.build_strategy(self._bp)
        names = [(a.name.lower(), a.blocked) for a in st.strategy_areas]
        reset_areas = [(n, b) for n, b in names if "password" in n or "reset" in n]
        assert len(reset_areas) >= 1
        assert all(b for _, b in reset_areas)


# ---------------------------------------------------------------------------
# TestQAStrategyPlannerMixedUiApi
# ---------------------------------------------------------------------------

class TestQAStrategyPlannerMixedUiApi:
    _bp = _make_blueprint(
        "mixed_ui_api",
        scope_notes="SaaS dashboard with REST API and UI sharing auth session",
        risk_areas=["UI/API data mismatch", "auth token reuse failure"],
    )

    def test_builds_strategy(self):
        st = _PLANNER.build_strategy(self._bp)
        assert st.project_type == "mixed_ui_api"

    def test_has_consistency_area(self):
        st = _PLANNER.build_strategy(self._bp)
        names = [a.name.lower() for a in st.strategy_areas]
        assert any("consistency" in n or "api" in n for n in names)

    def test_api_and_ui_layers_recommended(self):
        st = _PLANNER.build_strategy(self._bp)
        layers = {t.layer: t for t in st.test_layers}
        assert layers.get("api", LayerRec()).recommended is True
        assert layers.get("ui", LayerRec()).recommended is True

    def test_contract_layer_recommended(self):
        st = _PLANNER.build_strategy(self._bp)
        layers = {t.layer: t for t in st.test_layers}
        assert layers.get("contract", LayerRec()).recommended is True


# ---------------------------------------------------------------------------
# TestQAStrategyPlannerUnknown
# ---------------------------------------------------------------------------

class TestQAStrategyPlannerUnknown:
    _bp = _make_blueprint("unknown", scope_notes="")

    def test_builds_strategy(self):
        st = _PLANNER.build_strategy(self._bp)
        assert st.project_type == "unknown"

    def test_all_areas_blocked(self):
        st = _PLANNER.build_strategy(self._bp)
        assert all(a.blocked for a in st.strategy_areas)

    def test_manual_exploratory_in_layers(self):
        st = _PLANNER.build_strategy(self._bp)
        layers = {t.layer: t for t in st.test_layers}
        assert "manual_exploratory" in layers

    def test_strategy_confidence_low(self):
        bp = _make_blueprint("unknown", environment="unknown", confidence="low")
        st = _PLANNER.build_strategy(bp)
        assert st.confidence_level in ("low", "medium")


# ---------------------------------------------------------------------------
# TestRiskMatrix
# ---------------------------------------------------------------------------

class TestRiskMatrix:
    def test_missing_credentials_risk_always_present(self):
        for pt in ["web_saas", "ecommerce", "api_backend", "auth_heavy"]:
            bp = _make_blueprint(pt)
            st = _PLANNER.build_strategy(bp)
            areas = [r.risk_area.lower() for r in st.risk_matrix]
            assert any("credential" in a or "test account" in a for a in areas), pt

    def test_production_risk_when_env_is_production(self):
        bp = _make_blueprint("web_saas", environment="production")
        st = _PLANNER.build_strategy(bp)
        prod_risks = [r for r in st.risk_matrix if "production" in r.risk_area.lower()]
        assert len(prod_risks) >= 1
        assert any(r.severity in ("high", "critical") for r in prod_risks)

    def test_payment_risk_for_ecommerce_with_payment_signals(self):
        bp = _make_blueprint("ecommerce", scope_notes="checkout with Stripe payment")
        st = _PLANNER.build_strategy(bp)
        payment_risks = [r for r in st.risk_matrix if "payment" in r.risk_area.lower()]
        assert len(payment_risks) >= 1
        assert any(r.severity in ("high", "critical") for r in payment_risks)

    def test_mobile_risk_when_mobile_signals_present(self):
        bp = _make_blueprint("web_saas", scope_notes="ios android mobile app")
        st = _PLANNER.build_strategy(bp)
        mobile_risks = [r for r in st.risk_matrix if "mobile" in r.risk_area.lower()]
        assert len(mobile_risks) >= 1
        assert all(r.blocked or r.approval_required for r in mobile_risks)

    def test_integration_risk_when_integration_signals_present(self):
        bp = _make_blueprint("web_saas", scope_notes="n8n webhook integration")
        st = _PLANNER.build_strategy(bp)
        int_risks = [r for r in st.risk_matrix if "integration" in r.risk_area.lower()]
        assert len(int_risks) >= 1

    def test_security_risk_when_security_signals_present(self):
        bp = _make_blueprint("web_saas", scope_notes="security owasp xss sql injection testing")
        st = _PLANNER.build_strategy(bp)
        sec_risks = [r for r in st.risk_matrix if "security" in r.risk_area.lower()]
        assert len(sec_risks) >= 1
        assert all(r.blocked for r in sec_risks)

    def test_auth_risk_high_severity(self):
        bp = _make_blueprint("auth_heavy", scope_notes="login session oauth2")
        st = _PLANNER.build_strategy(bp)
        auth_risks = [r for r in st.risk_matrix if "auth" in r.risk_area.lower() or "credential" in r.risk_area.lower()]
        assert len(auth_risks) >= 1
        severities = {r.severity for r in auth_risks}
        assert "high" in severities or "critical" in severities


# ---------------------------------------------------------------------------
# TestTestLayers
# ---------------------------------------------------------------------------

class TestTestLayers:
    def test_web_saas_recommends_smoke_ui_regression(self):
        bp = _make_blueprint("web_saas")
        st = _PLANNER.build_strategy(bp)
        layers = {t.layer: t for t in st.test_layers}
        for required in ["smoke", "ui", "regression"]:
            assert required in layers, f"Missing layer: {required}"
            assert layers[required].recommended is True

    def test_api_backend_recommends_api_contract_smoke(self):
        bp = _make_blueprint("api_backend")
        st = _PLANNER.build_strategy(bp)
        layers = {t.layer: t for t in st.test_layers}
        for required in ["api", "contract", "smoke"]:
            assert required in layers, f"Missing layer: {required}"
            assert layers[required].recommended is True

    def test_auth_heavy_recommends_auth_layer_first(self):
        bp = _make_blueprint("auth_heavy")
        st = _PLANNER.build_strategy(bp)
        layers = {t.layer: t for t in st.test_layers}
        assert "auth" in layers
        assert layers["auth"].recommended is True
        assert layers["auth"].priority == "high"

    def test_mobile_native_always_blocked(self):
        for pt in ["web_saas", "ecommerce", "api_backend", "auth_heavy", "mixed_ui_api"]:
            bp = _make_blueprint(pt)
            st = _PLANNER.build_strategy(bp)
            layers = {t.layer: t for t in st.test_layers}
            if "mobile_native" in layers:
                assert layers["mobile_native"].blocked is True, f"mobile_native not blocked for {pt}"

    def test_unknown_blocks_most_layers(self):
        bp = _make_blueprint("unknown")
        st = _PLANNER.build_strategy(bp)
        blocked_count = sum(1 for t in st.test_layers if t.blocked)
        assert blocked_count >= 2

    def test_layers_have_examples(self):
        bp = _make_blueprint("web_saas")
        st = _PLANNER.build_strategy(bp)
        for t in st.test_layers:
            assert len(t.examples) >= 1, f"Layer {t.layer} has no examples"


# ---------------------------------------------------------------------------
# TestTacticalPlanOutline
# ---------------------------------------------------------------------------

class TestTacticalPlanOutline:
    def test_always_has_missing_info_item(self):
        for pt in ["web_saas", "ecommerce", "api_backend"]:
            bp = _make_blueprint(pt)
            st = _PLANNER.build_strategy(bp)
            titles = [i.title.lower() for i in st.tactical_plan_outline]
            assert any("missing" in t or "clarif" in t for t in titles), pt

    def test_always_has_credentials_item(self):
        for pt in ["web_saas", "ecommerce", "auth_heavy"]:
            bp = _make_blueprint(pt)
            st = _PLANNER.build_strategy(bp)
            items_blocked = [i for i in st.tactical_plan_outline if i.blocked]
            titles = [i.title.lower() for i in items_blocked]
            assert any("credential" in t or "test account" in t for t in titles), pt

    def test_ecommerce_has_payment_sandbox_item(self):
        bp = _make_blueprint("ecommerce", scope_notes="stripe payment checkout")
        st = _PLANNER.build_strategy(bp)
        titles = [i.title.lower() for i in st.tactical_plan_outline]
        assert any("payment" in t or "sandbox" in t for t in titles)

    def test_tactical_items_have_phases(self):
        bp = _make_blueprint("web_saas")
        st = _PLANNER.build_strategy(bp)
        for item in st.tactical_plan_outline:
            assert item.phase, f"Tactical item '{item.title}' has no phase"

    def test_always_has_evidence_item(self):
        bp = _make_blueprint("web_saas")
        st = _PLANNER.build_strategy(bp)
        titles = [i.title.lower() for i in st.tactical_plan_outline]
        assert any("evidence" in t for t in titles)

    def test_always_has_delivery_item(self):
        bp = _make_blueprint("web_saas")
        st = _PLANNER.build_strategy(bp)
        titles = [i.title.lower() for i in st.tactical_plan_outline]
        assert any("delivery" in t or "client" in t for t in titles)


# ---------------------------------------------------------------------------
# TestStrategyDecisions
# ---------------------------------------------------------------------------

class TestStrategyDecisions:
    def test_playwright_first_decision_present(self):
        bp = _make_blueprint("web_saas")
        st = _PLANNER.build_strategy(bp)
        decisions = [d.decision.lower() for d in st.strategy_decisions]
        assert any("playwright" in d for d in decisions)

    def test_no_execution_decision_present(self):
        bp = _make_blueprint("web_saas")
        st = _PLANNER.build_strategy(bp)
        decisions = [d.decision.lower() for d in st.strategy_decisions]
        assert any("no execution" in d or "planning" in d for d in decisions)

    def test_client_ready_decision_present(self):
        bp = _make_blueprint("web_saas")
        st = _PLANNER.build_strategy(bp)
        decisions = [d.decision.lower() for d in st.strategy_decisions]
        assert any("client" in d and ("ready" in d or "delivery" in d) for d in decisions)

    def test_decisions_have_rationale(self):
        bp = _make_blueprint("web_saas")
        st = _PLANNER.build_strategy(bp)
        for d in st.strategy_decisions:
            assert d.rationale, f"Decision '{d.decision}' has no rationale"

    def test_decisions_have_impact(self):
        bp = _make_blueprint("web_saas")
        st = _PLANNER.build_strategy(bp)
        for d in st.strategy_decisions:
            assert d.impact, f"Decision '{d.decision}' has no impact"


# ---------------------------------------------------------------------------
# TestCarryForward
# ---------------------------------------------------------------------------

class TestCarryForward:
    def test_missing_info_carried_forward(self):
        missing = ["Custom missing info A", "Custom missing info B"]
        bp = _make_blueprint("web_saas", missing_info=missing)
        st = _PLANNER.build_strategy(bp)
        for m in missing:
            assert m in st.missing_information

    def test_blocked_actions_carried_forward(self):
        blocked = ["Execute browser tests — BLOCKED.", "Use credentials — BLOCKED."]
        bp = _make_blueprint("web_saas", blocked_actions=blocked)
        st = _PLANNER.build_strategy(bp)
        for b in blocked:
            assert b in st.blocked_actions

    def test_required_approvals_carried_forward(self):
        approvals = ["Target URL approval", "Staging approval", "Sandbox payment"]
        bp = _make_blueprint("web_saas", required_approvals=approvals)
        st = _PLANNER.build_strategy(bp)
        for a in approvals:
            assert a in st.required_approvals


# ---------------------------------------------------------------------------
# TestSafetyBoundary
# ---------------------------------------------------------------------------

class TestSafetyBoundary:
    def test_client_ready_always_false(self):
        for pt in ["web_saas", "ecommerce", "api_backend", "auth_heavy", "unknown"]:
            bp = _make_blueprint(pt)
            st = _PLANNER.build_strategy(bp)
            assert st.client_ready is False, f"client_ready should be False for {pt}"

    def test_no_execution_claimed_in_summary(self):
        for pt in ["web_saas", "ecommerce", "api_backend"]:
            bp = _make_blueprint(pt)
            st = _PLANNER.build_strategy(bp)
            assert "test result" not in st.strategy_summary.lower()
            assert "tests passed" not in st.strategy_summary.lower()
            assert "ran " not in st.strategy_summary.lower()

    def test_no_execution_in_notes(self):
        bp = _make_blueprint("web_saas")
        st = _PLANNER.build_strategy(bp)
        notes_text = " ".join(st.notes).lower()
        assert "no execution" in notes_text

    def test_planner_generated_fields_contain_no_execution_claims(self):
        bp = _make_blueprint("web_saas")
        st = _PLANNER.build_strategy(bp)
        # Strategy planner must not claim any tests were run or passed
        planner_text = (
            st.strategy_summary + " " +
            " ".join(d.decision for d in st.strategy_decisions) + " " +
            " ".join(n for n in st.notes)
        ).lower()
        assert "tests passed" not in planner_text
        assert "test run complete" not in planner_text
        assert "executed successfully" not in planner_text

    def test_mobile_native_never_executable(self):
        for pt in ["web_saas", "ecommerce", "auth_heavy"]:
            bp = _make_blueprint(pt)
            st = _PLANNER.build_strategy(bp)
            layers = {t.layer: t for t in st.test_layers}
            if "mobile_native" in layers:
                assert layers["mobile_native"].blocked, f"mobile_native should be blocked for {pt}"
                assert layers["mobile_native"].recommended is False

    def test_planner_does_not_import_requests(self):
        source = (_ROOT / "core" / "qa_strategy_planner.py").read_text(encoding="utf-8")
        forbidden = ["import requests", "import httpx", "import aiohttp",
                     "urllib.request.urlopen", "subprocess.run", "subprocess.call"]
        for f in forbidden:
            assert f not in source, f"qa_strategy_planner.py must not use {f}"


# ---------------------------------------------------------------------------
# TestWorkbenchControllerPhase2C
# ---------------------------------------------------------------------------

class TestWorkbenchControllerPhase2C:
    def test_build_qa_strategy_returns_qa_strategy(self):
        c = WorkbenchController()
        bp = _make_blueprint("web_saas")
        st = c.build_qa_strategy(bp)
        assert isinstance(st, QAStrategy)
        assert st.project_type == "web_saas"

    def test_build_qa_strategy_does_not_import_orchestrator(self):
        import core.workbench_controller as wc_mod
        source = Path(wc_mod.__file__).read_text(encoding="utf-8")
        assert "from core.orchestrator" not in source
        assert "import orchestrator" not in source

    def test_update_project_status_returns_strategy_phase(self):
        c = WorkbenchController()
        bp = _make_blueprint("web_saas")
        st = c.build_qa_strategy(bp)
        status = c.update_project_status_for_strategy("test-project", st)
        assert status.phase == "strategy"
        assert status.overall_status == "in_progress"

    def test_update_project_status_completed_phases_includes_blueprint(self):
        c = WorkbenchController()
        bp = _make_blueprint("web_saas")
        st = c.build_qa_strategy(bp)
        status = c.update_project_status_for_strategy("test-project", st)
        assert "blueprint" in status.completed_phases

    def test_render_strategy_artifacts_writes_files(self, tmp_path):
        c = WorkbenchController(outputs_root=tmp_path)
        bp = _make_blueprint("web_saas")
        bp.project_id = "proj-test"
        st = c.build_qa_strategy(bp)
        status = c.update_project_status_for_strategy("proj-test", st)
        paths = c.render_strategy_artifacts(st, "proj-test", status)
        assert "qa_strategy_json" in paths
        assert "qa_strategy_md" in paths
        assert "risk_matrix_md" in paths
        assert "test_layers_md" in paths
        assert "tactical_plan_outline_md" in paths
        assert "quality_rubric_md" in paths
        assert "strategy_decisions_md" in paths
        assert "updated_project_status_json" in paths

    def test_artifacts_written_under_02_strategy(self, tmp_path):
        c = WorkbenchController(outputs_root=tmp_path)
        bp = _make_blueprint("web_saas")
        bp.project_id = "proj-dir"
        st = c.build_qa_strategy(bp)
        paths = c.render_strategy_artifacts(st, "proj-dir")
        for p in paths.values():
            assert "02_strategy" in str(p), f"Expected 02_strategy in path: {p}"

    def test_build_context_with_strategy_returns_all_keys(self, tmp_path):
        c = WorkbenchController(outputs_root=tmp_path)
        result = c.build_context_with_strategy(
            ["Need Playwright tests for SaaS dashboard with login"],
            project_id="ctx-test",
        )
        assert "strategy" in result
        assert "strategy_status" in result
        assert "strategy_artifact_paths" in result
        assert isinstance(result["strategy"], QAStrategy)

    def test_strategy_artifacts_no_secrets(self, tmp_path):
        c = WorkbenchController(outputs_root=tmp_path)
        result = c.build_context_with_strategy(
            ["Need login tests for https://demo.example.com username=test@example.com password=FakeSecret123"],
            project_id="secret-test",
        )
        st = result["strategy"]
        full = json.dumps(st.to_dict())
        assert "FakeSecret123" not in full


# ---------------------------------------------------------------------------
# TestBuildStrategyArtifactsContent
# ---------------------------------------------------------------------------

class TestBuildStrategyArtifactsContent:
    def test_qa_strategy_md_contains_no_execution_notice(self, tmp_path):
        c = WorkbenchController(outputs_root=tmp_path)
        bp = _make_blueprint("web_saas")
        bp.project_id = "content-test"
        st = c.build_qa_strategy(bp)
        paths = c.render_strategy_artifacts(st, "content-test")
        md = Path(paths["qa_strategy_md"]).read_text(encoding="utf-8")
        assert "no execution" in md.lower() or "planning artifact" in md.lower()

    def test_qa_strategy_md_client_ready_false(self, tmp_path):
        c = WorkbenchController(outputs_root=tmp_path)
        bp = _make_blueprint("web_saas")
        bp.project_id = "cr-test"
        st = c.build_qa_strategy(bp)
        paths = c.render_strategy_artifacts(st, "cr-test")
        md = Path(paths["qa_strategy_md"]).read_text(encoding="utf-8")
        assert "client_ready" in md.lower() or "client ready" in md.lower()

    def test_risk_matrix_md_contains_blocked(self, tmp_path):
        c = WorkbenchController(outputs_root=tmp_path)
        bp = _make_blueprint("auth_heavy", scope_notes="2fa login session")
        bp.project_id = "risk-test"
        st = c.build_qa_strategy(bp)
        paths = c.render_strategy_artifacts(st, "risk-test")
        md = Path(paths["risk_matrix_md"]).read_text(encoding="utf-8")
        assert "blocked" in md.lower() or "BLOCKED" in md

    def test_qa_strategy_json_is_valid_json(self, tmp_path):
        c = WorkbenchController(outputs_root=tmp_path)
        bp = _make_blueprint("ecommerce")
        bp.project_id = "json-test"
        st = c.build_qa_strategy(bp)
        paths = c.render_strategy_artifacts(st, "json-test")
        data = json.loads(Path(paths["qa_strategy_json"]).read_text(encoding="utf-8"))
        assert data["project_type"] == "ecommerce"
        assert data["client_ready"] is False

    def test_quality_rubric_md_mentions_client_ready_false(self, tmp_path):
        c = WorkbenchController(outputs_root=tmp_path)
        bp = _make_blueprint("web_saas")
        bp.project_id = "rubric-test"
        st = c.build_qa_strategy(bp)
        paths = c.render_strategy_artifacts(st, "rubric-test")
        md = Path(paths["quality_rubric_md"]).read_text(encoding="utf-8")
        assert "client_ready" in md or "human review" in md.lower()


# ---------------------------------------------------------------------------
# TestBuildStrategyCLI
# ---------------------------------------------------------------------------

class TestBuildStrategyCLI:
    def _load_tool(self):
        spec = importlib.util.spec_from_file_location(
            "build_strategy", _ROOT / "tools" / "build_strategy.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_tool_is_importable(self):
        mod = self._load_tool()
        assert hasattr(mod, "main")

    def test_tool_returns_zero_on_simple_input(self, monkeypatch, tmp_path):
        monkeypatch.chdir(_ROOT)
        mod = self._load_tool()
        result = mod.main([
            "--input", "Need Playwright tests for a SaaS dashboard with login",
            "--project-id", "cli-test",
            "--no-write",
        ])
        assert result == 0

    def test_tool_returns_zero_with_json_flag(self, monkeypatch, capsys):
        monkeypatch.chdir(_ROOT)
        mod = self._load_tool()
        result = mod.main([
            "--input", "API tests for REST backend",
            "--project-id", "cli-json-test",
            "--json",
        ])
        assert result == 0
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert "strategy" in data
        assert data["strategy"]["client_ready"] is False

    def test_tool_no_url_fetch_in_source(self):
        source = (_ROOT / "tools" / "build_strategy.py").read_text(encoding="utf-8")
        forbidden = ["import requests", "import httpx", "urllib.request.urlopen"]
        for f in forbidden:
            assert f not in source, f"build_strategy.py must not use {f}"

    def test_classify_inputs_with_strategy_flag(self, monkeypatch, tmp_path):
        monkeypatch.chdir(_ROOT)
        spec = importlib.util.spec_from_file_location(
            "classify_inputs", _ROOT / "tools" / "classify_inputs.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        result = mod.main([
            "--input", "Need login tests for a SaaS dashboard",
            "--project-id", "classify-strategy-test",
            "--with-strategy",
            "--no-write",
        ])
        assert result == 0

    def test_from_output_returns_error_without_blueprint_json(self, tmp_path, monkeypatch):
        monkeypatch.chdir(_ROOT)
        mod = self._load_tool()
        result = mod.main([
            "--from-output", str(tmp_path),
            "--no-write",
        ])
        assert result == 1


# ---------------------------------------------------------------------------
# TestPhase2CDocsAudit
# ---------------------------------------------------------------------------

class TestPhase2CDocsAudit:
    def test_docs_audit_passes(self, monkeypatch):
        monkeypatch.chdir(_ROOT)
        monkeypatch.setattr("sys.argv", ["docs_audit.py"])
        spec = importlib.util.spec_from_file_location(
            "docs_audit", _ROOT / "tools" / "docs_audit.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        result = mod.main()
        assert result == 0, "docs_audit must return 0 (PASS)"

    def test_agent_readiness_audit_passes(self, monkeypatch):
        monkeypatch.chdir(_ROOT)
        spec = importlib.util.spec_from_file_location(
            "agent_readiness_audit", _ROOT / "tools" / "agent_readiness_audit.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        result = mod.main(["--no-write"])
        assert result == 0, "agent_readiness_audit must return 0 (PASS)"
