"""
Auth and credential schema tests — Phase 1B-auth addendum.

Covers:
- CredentialReference / CredentialPolicy / CredentialUseApproval safe defaults
- AuthFlowStep / AuthFlowPlan / AuthCheckResult safe defaults
- SecretRedactionRule / RedactionReport safe defaults
- Explicit nested from_dict reconstruction (AuthFlowPlan.steps, RedactionReport.rules_applied)
- to_dict / from_dict round-trips for all new schemas
- New auth/credential constants
- __init__.py exports all new classes
- Confirms no raw secret values are stored by default
"""
from __future__ import annotations

from core.schemas.credentials import CredentialReference, CredentialPolicy, CredentialUseApproval
from core.schemas.auth_flow import AuthFlowStep, AuthFlowPlan, AuthCheckResult
from core.schemas.redaction import SecretRedactionRule, RedactionReport
from core.schemas.mobile_testing import MobileTestTarget, MobileExecutionPlan
from core.schemas.constants import (
    CREDENTIAL_TYPES,
    CREDENTIAL_STORAGE_MODES,
    AUTH_FLOW_TYPES,
    AUTH_ACTION_RISK_LEVELS,
    SECRET_REDACTION_TARGETS,
    MOBILE_EXECUTION_TARGETS,
    MOBILE_TOOLING_OPTIONS,
)


# ---------------------------------------------------------------------------
# New constants
# ---------------------------------------------------------------------------

class TestAuthConstants:
    def test_credential_types_non_empty_frozenset(self):
        assert isinstance(CREDENTIAL_TYPES, frozenset)
        assert "username_password" in CREDENTIAL_TYPES
        assert "api_key" in CREDENTIAL_TYPES
        assert "unknown" in CREDENTIAL_TYPES

    def test_credential_storage_modes(self):
        assert "env_var" in CREDENTIAL_STORAGE_MODES
        assert "not_stored" in CREDENTIAL_STORAGE_MODES
        assert "secure_prompt" in CREDENTIAL_STORAGE_MODES

    def test_auth_flow_types(self):
        assert "login" in AUTH_FLOW_TYPES
        assert "two_factor_auth" in AUTH_FLOW_TYPES
        assert "password_reset" in AUTH_FLOW_TYPES
        assert "unknown" in AUTH_FLOW_TYPES

    def test_auth_action_risk_levels(self):
        assert "safe_auth_smoke" in AUTH_ACTION_RISK_LEVELS
        assert "destructive_account_action" in AUTH_ACTION_RISK_LEVELS
        assert "payment_or_auth" in AUTH_ACTION_RISK_LEVELS
        assert "production_read_only" in AUTH_ACTION_RISK_LEVELS

    def test_secret_redaction_targets(self):
        assert "logs" in SECRET_REDACTION_TARGETS
        assert "client_reports" in SECRET_REDACTION_TARGETS
        assert "traces" in SECRET_REDACTION_TARGETS
        assert "screenshots" in SECRET_REDACTION_TARGETS


# ---------------------------------------------------------------------------
# CredentialReference
# ---------------------------------------------------------------------------

class TestCredentialReference:
    def test_safe_defaults(self):
        cr = CredentialReference()
        assert cr.raw_value_stored is False
        assert cr.requires_approval_before_use is True
        assert cr.approved_for_use is False
        assert cr.expires_after_run is True
        assert cr.masked_in_logs is True
        assert cr.storage_mode == "not_stored"
        assert cr.credential_type == "unknown"
        assert cr.environment_type == "unknown"
        assert cr.secret_names == []

    def test_id_auto_generated(self):
        cr = CredentialReference()
        assert len(cr.id) > 0

    def test_raw_value_stored_is_false_by_default(self):
        cr = CredentialReference(label="Test user login")
        assert cr.raw_value_stored is False

    def test_secret_names_holds_env_var_names_not_values(self):
        cr = CredentialReference(secret_names=["TEST_USER_EMAIL", "TEST_USER_PASSWORD"])
        assert "TEST_USER_EMAIL" in cr.secret_names
        assert "TEST_USER_PASSWORD" in cr.secret_names
        # Confirm these are names (strings starting with reasonable label chars)
        for name in cr.secret_names:
            assert isinstance(name, str)
            assert len(name) > 0

    def test_roundtrip(self):
        cr = CredentialReference(
            credential_type="username_password",
            label="Admin test account",
            environment_type="staging",
            storage_mode="env_var",
            secret_names=["ADMIN_EMAIL", "ADMIN_PASSWORD"],
            notes=["Created specifically for QA testing"],
        )
        d = cr.to_dict()
        cr2 = CredentialReference.from_dict(d)
        assert cr2.credential_type == "username_password"
        assert cr2.environment_type == "staging"
        assert cr2.storage_mode == "env_var"
        assert "ADMIN_EMAIL" in cr2.secret_names
        assert cr2.raw_value_stored is False
        assert cr2.approved_for_use is False

    def test_from_dict_ignores_unknown_fields(self):
        cr = CredentialReference.from_dict({"label": "x", "nonexistent_field": "ignored"})
        assert cr.label == "x"


# ---------------------------------------------------------------------------
# CredentialPolicy
# ---------------------------------------------------------------------------

class TestCredentialPolicy:
    def test_safe_defaults(self):
        cp = CredentialPolicy(project_id="p1")
        assert cp.allow_credential_use is False
        assert cp.allow_production_credentials is False
        assert cp.require_explicit_approval is True
        assert cp.require_test_account is True
        assert cp.require_sandbox_for_payment is True
        assert cp.prohibit_destructive_account_actions is True
        assert cp.mask_secrets_in_outputs is True
        assert cp.block_client_delivery_if_secrets_detected is True

    def test_allowed_storage_modes_default(self):
        cp = CredentialPolicy(project_id="p1")
        assert "env_var" in cp.allowed_storage_modes
        assert "not_stored" in cp.allowed_storage_modes
        assert "secure_prompt" in cp.allowed_storage_modes

    def test_roundtrip(self):
        cp = CredentialPolicy(
            project_id="p1",
            allow_credential_use=True,
            allowed_storage_modes=["env_var", "env_file"],
            notes=["Approved for staging only"],
        )
        d = cp.to_dict()
        cp2 = CredentialPolicy.from_dict(d)
        assert cp2.allow_credential_use is True
        assert cp2.allow_production_credentials is False
        assert cp2.notes == ["Approved for staging only"]
        assert "env_var" in cp2.allowed_storage_modes


# ---------------------------------------------------------------------------
# CredentialUseApproval
# ---------------------------------------------------------------------------

class TestCredentialUseApproval:
    def test_defaults_to_not_approved(self):
        cua = CredentialUseApproval()
        assert cua.approved is False
        assert cua.approved_by is None
        assert cua.approved_at is None
        assert cua.approval_scope == "none"
        assert cua.allowed_actions == []

    def test_forbidden_actions_pre_populated(self):
        cua = CredentialUseApproval()
        assert "change_password" in cua.forbidden_actions
        assert "delete_account" in cua.forbidden_actions
        assert "change_billing" in cua.forbidden_actions
        assert "create_real_payment" in cua.forbidden_actions
        assert "modify_production_data" in cua.forbidden_actions

    def test_roundtrip(self):
        cua = CredentialUseApproval(
            credential_ref_id="cred-001",
            action_id="run-auth-smoke",
            approved=True,
            approved_by="Dmytro",
            approval_scope="staging_login_only",
            allowed_actions=["login", "view_dashboard"],
        )
        d = cua.to_dict()
        cua2 = CredentialUseApproval.from_dict(d)
        assert cua2.approved is True
        assert cua2.approved_by == "Dmytro"
        assert cua2.approval_scope == "staging_login_only"
        assert "login" in cua2.allowed_actions
        assert "change_password" in cua2.forbidden_actions


# ---------------------------------------------------------------------------
# AuthFlowStep
# ---------------------------------------------------------------------------

class TestAuthFlowStep:
    def test_safe_defaults(self):
        step = AuthFlowStep()
        assert step.risk_level == "payment_or_auth"
        assert step.requires_credentials is True
        assert step.requires_approval is True
        assert step.destructive is False
        assert step.allowed_in_production is False
        assert step.expected_evidence == []

    def test_id_auto_generated(self):
        step = AuthFlowStep()
        assert len(step.id) > 0

    def test_roundtrip(self):
        step = AuthFlowStep(
            title="Login with valid credentials",
            flow_type="login",
            risk_level="payment_or_auth",
            expected_evidence=["screenshot_login_success"],
            notes=["Standard happy path"],
        )
        d = step.to_dict()
        step2 = AuthFlowStep.from_dict(d)
        assert step2.title == "Login with valid credentials"
        assert step2.flow_type == "login"
        assert step2.destructive is False
        assert "screenshot_login_success" in step2.expected_evidence


# ---------------------------------------------------------------------------
# AuthFlowPlan (nested)
# ---------------------------------------------------------------------------

class TestAuthFlowPlan:
    def test_safe_defaults(self):
        plan = AuthFlowPlan(project_id="p1")
        assert plan.approval_required is True
        assert plan.approved is False
        assert plan.blocked is True
        assert plan.safe_to_execute is False
        assert plan.environment_type == "unknown"
        assert plan.steps == []
        assert plan.credential_ref_ids == []

    def test_from_dict_reconstructs_steps(self):
        data = {
            "project_id": "p1",
            "steps": [
                {"title": "Login", "flow_type": "login", "risk_level": "payment_or_auth"},
                {"title": "View dashboard", "flow_type": "protected_route_access", "destructive": False},
            ],
        }
        plan = AuthFlowPlan.from_dict(data)
        assert len(plan.steps) == 2
        assert all(isinstance(s, AuthFlowStep) for s in plan.steps)
        assert plan.steps[0].title == "Login"
        assert plan.steps[1].flow_type == "protected_route_access"

    def test_roundtrip_preserves_blocked_and_safe_flags(self):
        step = AuthFlowStep(title="Login", flow_type="login")
        plan = AuthFlowPlan(
            project_id="p1",
            environment_type="staging",
            steps=[step],
            blocked=True,
            safe_to_execute=False,
        )
        plan2 = AuthFlowPlan.from_dict(plan.to_dict())
        assert plan2.blocked is True
        assert plan2.safe_to_execute is False
        assert plan2.environment_type == "staging"
        assert isinstance(plan2.steps[0], AuthFlowStep)

    def test_target_ref_id_optional(self):
        plan = AuthFlowPlan(project_id="p1")
        assert plan.target_ref_id is None
        d = plan.to_dict()
        plan2 = AuthFlowPlan.from_dict(d)
        assert plan2.target_ref_id is None


# ---------------------------------------------------------------------------
# AuthCheckResult
# ---------------------------------------------------------------------------

class TestAuthCheckResult:
    def test_safe_defaults(self):
        result = AuthCheckResult(project_id="p1")
        assert result.executed is False
        assert result.auth_success is None
        assert result.secrets_redacted is True
        assert result.client_safe is False
        assert result.evidence_refs == []
        assert result.blocked_reason is None

    def test_auth_success_none_means_not_executed(self):
        result = AuthCheckResult(project_id="p1", executed=False)
        assert result.auth_success is None

    def test_roundtrip(self):
        result = AuthCheckResult(
            project_id="p1",
            action_id="run-auth-smoke",
            executed=True,
            execution_mode="mock",
            auth_success=True,
            evidence_refs=["screenshot_001"],
            secrets_redacted=True,
            client_safe=False,
            notes=["Mock run only — no real credentials used"],
        )
        d = result.to_dict()
        result2 = AuthCheckResult.from_dict(d)
        assert result2.executed is True
        assert result2.auth_success is True
        assert result2.secrets_redacted is True
        assert result2.client_safe is False
        assert "screenshot_001" in result2.evidence_refs

    def test_no_secret_fields_in_schema(self):
        result = AuthCheckResult(project_id="p1")
        d = result.to_dict()
        forbidden_keys = {"password", "token", "cookie", "session", "jwt", "secret", "credential"}
        for key in d:
            assert key.lower() not in forbidden_keys, f"Forbidden field found in AuthCheckResult: {key}"


# ---------------------------------------------------------------------------
# SecretRedactionRule
# ---------------------------------------------------------------------------

class TestSecretRedactionRule:
    def test_safe_defaults(self):
        rule = SecretRedactionRule()
        assert rule.replacement == "[REDACTED]"
        assert rule.enabled is True
        assert rule.pattern_type == "generic_secret"
        assert rule.notes == []

    def test_id_auto_generated(self):
        rule = SecretRedactionRule()
        assert len(rule.id) > 0

    def test_roundtrip(self):
        rule = SecretRedactionRule(
            target="client_reports",
            pattern_type="api_key",
            replacement="[API_KEY_REDACTED]",
            enabled=True,
        )
        d = rule.to_dict()
        rule2 = SecretRedactionRule.from_dict(d)
        assert rule2.target == "client_reports"
        assert rule2.pattern_type == "api_key"
        assert rule2.replacement == "[API_KEY_REDACTED]"
        assert rule2.enabled is True


# ---------------------------------------------------------------------------
# RedactionReport (nested)
# ---------------------------------------------------------------------------

class TestRedactionReport:
    def test_safe_defaults(self):
        rr = RedactionReport(project_id="p1")
        assert rr.redaction_performed is False
        assert rr.possible_secret_leaks_found is False
        assert rr.blocked_client_delivery is False
        assert rr.rules_applied == []
        assert rr.summary == ""

    def test_from_dict_reconstructs_rules_applied(self):
        data = {
            "project_id": "p1",
            "rules_applied": [
                {"target": "logs", "pattern_type": "password", "replacement": "[REDACTED]", "enabled": True},
                {"target": "client_reports", "pattern_type": "bearer_token", "enabled": True},
            ],
        }
        rr = RedactionReport.from_dict(data)
        assert len(rr.rules_applied) == 2
        assert all(isinstance(r, SecretRedactionRule) for r in rr.rules_applied)
        assert rr.rules_applied[0].target == "logs"
        assert rr.rules_applied[1].pattern_type == "bearer_token"

    def test_roundtrip(self):
        rule = SecretRedactionRule(target="traces", pattern_type="jwt")
        rr = RedactionReport(
            project_id="p1",
            rules_applied=[rule],
            redaction_performed=True,
            possible_secret_leaks_found=False,
            summary="JWT pattern redacted from trace files",
        )
        rr2 = RedactionReport.from_dict(rr.to_dict())
        assert rr2.redaction_performed is True
        assert rr2.summary == "JWT pattern redacted from trace files"
        assert isinstance(rr2.rules_applied[0], SecretRedactionRule)
        assert rr2.rules_applied[0].target == "traces"

    def test_blocked_client_delivery_default_false(self):
        rr = RedactionReport(project_id="p1")
        assert rr.blocked_client_delivery is False


# ---------------------------------------------------------------------------
# __init__.py re-exports
# ---------------------------------------------------------------------------

class TestAuthPackageExports:
    def test_all_auth_classes_importable_from_package(self):
        import core.schemas as s
        classes = [
            s.CredentialReference,
            s.CredentialPolicy,
            s.CredentialUseApproval,
            s.AuthFlowStep,
            s.AuthFlowPlan,
            s.AuthCheckResult,
            s.SecretRedactionRule,
            s.RedactionReport,
        ]
        assert all(c is not None for c in classes)

    def test_auth_constants_importable_from_package(self):
        import core.schemas as s
        assert "username_password" in s.CREDENTIAL_TYPES
        assert "env_var" in s.CREDENTIAL_STORAGE_MODES
        assert "login" in s.AUTH_FLOW_TYPES
        assert "safe_auth_smoke" in s.AUTH_ACTION_RISK_LEVELS
        assert "logs" in s.SECRET_REDACTION_TARGETS

    def test_web_mobile_constants_importable_from_package(self):
        import core.schemas as s
        assert "web" in s.APP_SURFACES
        assert "ios_app" in s.APP_SURFACES
        assert "username_password" in s.AUTH_MECHANISMS
        assert "oauth2" in s.AUTH_MECHANISMS
        assert "google" in s.AUTH_PROVIDERS
        assert "auth0" in s.AUTH_PROVIDERS
        assert "native_ios" in s.MOBILE_AUTH_CONTEXTS
        assert "biometric_prompt" in s.MOBILE_AUTH_CONTEXTS


# ---------------------------------------------------------------------------
# Web/mobile auth constants
# ---------------------------------------------------------------------------

class TestWebMobileAuthConstants:
    def test_app_surfaces_complete(self):
        from core.schemas.constants import APP_SURFACES
        for s in ("web", "mobile_web", "ios_app", "android_app", "desktop", "api", "unknown"):
            assert s in APP_SURFACES

    def test_auth_mechanisms_complete(self):
        from core.schemas.constants import AUTH_MECHANISMS
        for m in ("username_password", "oauth2", "social_login", "email_magic_link",
                  "email_otp", "sms_otp", "totp", "two_factor_auth", "passkey",
                  "biometric", "session_cookie", "api_token", "sso", "unknown"):
            assert m in AUTH_MECHANISMS

    def test_auth_providers_complete(self):
        from core.schemas.constants import AUTH_PROVIDERS
        for p in ("local", "google", "apple", "microsoft", "github", "facebook",
                  "custom_oauth2", "auth0", "okta", "firebase_auth", "cognito",
                  "supabase_auth", "unknown"):
            assert p in AUTH_PROVIDERS

    def test_mobile_auth_contexts_complete(self):
        from core.schemas.constants import MOBILE_AUTH_CONTEXTS
        for c in ("mobile_web", "native_ios", "native_android", "deep_link",
                  "universal_link", "app_link", "biometric_prompt", "push_approval", "unknown"):
            assert c in MOBILE_AUTH_CONTEXTS

    def test_extended_auth_flow_types_present(self):
        from core.schemas.constants import AUTH_FLOW_TYPES
        for t in ("oauth2_redirect", "email_link_open", "email_code_read",
                  "totp_code_generate", "sms_code_manual_input", "mobile_deep_link_open",
                  "session_storage_state", "protected_screen_access", "biometric_prompt_check"):
            assert t in AUTH_FLOW_TYPES


# ---------------------------------------------------------------------------
# CredentialReference — web/mobile surface fields
# ---------------------------------------------------------------------------

class TestCredentialReferenceWebMobile:
    def test_surface_fields_default_to_unknown(self):
        cr = CredentialReference()
        assert cr.app_surface == "unknown"
        assert cr.auth_mechanism == "unknown"
        assert cr.auth_provider is None
        assert cr.mobile_auth_context is None

    def test_web_credential_roundtrip(self):
        cr = CredentialReference(
            credential_type="oauth",
            label="Google OAuth test account",
            app_surface="web",
            auth_mechanism="oauth2",
            auth_provider="google",
            secret_names=["GOOGLE_TEST_CLIENT_ID", "GOOGLE_TEST_CLIENT_SECRET"],
        )
        d = cr.to_dict()
        cr2 = CredentialReference.from_dict(d)
        assert cr2.app_surface == "web"
        assert cr2.auth_mechanism == "oauth2"
        assert cr2.auth_provider == "google"
        assert cr2.mobile_auth_context is None
        assert cr2.raw_value_stored is False

    def test_mobile_credential_roundtrip(self):
        cr = CredentialReference(
            credential_type="username_password",
            label="iOS app test account",
            app_surface="ios_app",
            auth_mechanism="username_password",
            mobile_auth_context="native_ios",
            secret_names=["IOS_TEST_EMAIL", "IOS_TEST_PASSWORD"],
        )
        d = cr.to_dict()
        cr2 = CredentialReference.from_dict(d)
        assert cr2.app_surface == "ios_app"
        assert cr2.mobile_auth_context == "native_ios"
        assert cr2.raw_value_stored is False

    def test_totp_credential_never_stores_seed(self):
        cr = CredentialReference(
            credential_type="otp",
            label="TOTP test seed reference",
            auth_mechanism="totp",
            secret_names=["TOTP_TEST_SEED_ENV_VAR"],  # env var name only, not the seed
        )
        assert cr.raw_value_stored is False
        for name in cr.secret_names:
            assert name == name.upper() or "_" in name  # looks like an env var name


# ---------------------------------------------------------------------------
# AuthFlowPlan — web/mobile surface fields
# ---------------------------------------------------------------------------

class TestAuthFlowPlanWebMobile:
    def test_surface_fields_default_to_unknown(self):
        plan = AuthFlowPlan(project_id="p1")
        assert plan.app_surface == "unknown"
        assert plan.auth_mechanism == "unknown"
        assert plan.auth_provider is None
        assert plan.mobile_auth_context is None

    def test_web_oauth_plan_roundtrip(self):
        step = AuthFlowStep(title="OAuth2 redirect", flow_type="oauth2_redirect")
        plan = AuthFlowPlan(
            project_id="p1",
            app_surface="web",
            auth_mechanism="oauth2",
            auth_provider="google",
            steps=[step],
        )
        d = plan.to_dict()
        plan2 = AuthFlowPlan.from_dict(d)
        assert plan2.app_surface == "web"
        assert plan2.auth_mechanism == "oauth2"
        assert plan2.auth_provider == "google"
        assert plan2.mobile_auth_context is None
        assert isinstance(plan2.steps[0], AuthFlowStep)
        assert plan2.steps[0].flow_type == "oauth2_redirect"

    def test_mobile_deep_link_plan_roundtrip(self):
        step = AuthFlowStep(title="Deep link open", flow_type="mobile_deep_link_open")
        plan = AuthFlowPlan(
            project_id="p1",
            app_surface="android_app",
            auth_mechanism="email_magic_link",
            mobile_auth_context="deep_link",
            steps=[step],
        )
        d = plan.to_dict()
        plan2 = AuthFlowPlan.from_dict(d)
        assert plan2.app_surface == "android_app"
        assert plan2.mobile_auth_context == "deep_link"
        assert plan2.blocked is True
        assert plan2.safe_to_execute is False

    def test_biometric_plan_defaults_to_blocked(self):
        step = AuthFlowStep(
            title="Biometric prompt",
            flow_type="biometric_prompt_check",
            risk_level="payment_or_auth",
            allowed_in_production=False,
        )
        plan = AuthFlowPlan(
            project_id="p1",
            app_surface="ios_app",
            auth_mechanism="biometric",
            mobile_auth_context="biometric_prompt",
            steps=[step],
        )
        assert plan.blocked is True
        assert plan.safe_to_execute is False
        assert plan.steps[0].allowed_in_production is False


# ---------------------------------------------------------------------------
# Mobile execution constants
# ---------------------------------------------------------------------------

class TestMobileExecutionConstants:
    def test_mobile_execution_targets_complete(self):
        for t in ("playwright_mobile_web_emulation", "android_emulator", "android_real_device",
                  "ios_simulator", "ios_real_device", "cloud_device_farm",
                  "manual_client_device", "unknown"):
            assert t in MOBILE_EXECUTION_TARGETS

    def test_mobile_tooling_options_complete(self):
        for t in ("playwright", "appium_optional", "maestro_optional",
                  "browserstack_optional", "sauce_labs_optional",
                  "local_android_emulator", "local_android_usb_device",
                  "macos_ios_simulator", "unknown"):
            assert t in MOBILE_TOOLING_OPTIONS


# ---------------------------------------------------------------------------
# MobileTestTarget
# ---------------------------------------------------------------------------

class TestMobileTestTarget:
    def test_safe_defaults(self):
        t = MobileTestTarget()
        assert t.app_surface == "unknown"
        assert t.execution_target == "unknown"
        assert t.platform_name == "unknown"
        assert t.requires_real_device is False
        assert t.requires_cloud_device is False
        assert t.requires_macos is False
        assert t.requires_approval is True
        assert t.device_name is None
        assert t.app_path is None

    def test_playwright_mobile_web_does_not_require_macos(self):
        t = MobileTestTarget(
            app_surface="mobile_web",
            execution_target="playwright_mobile_web_emulation",
            platform_name="chromium",
            browser_name="chromium",
        )
        assert t.requires_macos is False
        assert t.requires_real_device is False
        assert t.requires_cloud_device is False

    def test_ios_simulator_requires_macos(self):
        t = MobileTestTarget(
            app_surface="ios_app",
            execution_target="ios_simulator",
            platform_name="iOS",
            requires_macos=True,
        )
        assert t.requires_macos is True
        assert t.requires_real_device is False

    def test_cloud_device_farm_requires_cloud_and_approval(self):
        t = MobileTestTarget(
            app_surface="android_app",
            execution_target="cloud_device_farm",
            platform_name="Android",
            requires_cloud_device=True,
            requires_approval=True,
        )
        assert t.requires_cloud_device is True
        assert t.requires_approval is True

    def test_roundtrip(self):
        t = MobileTestTarget(
            app_surface="ios_app",
            execution_target="ios_real_device",
            platform_name="iOS",
            device_name="iPhone 15 Pro",
            os_version="17.0",
            requires_real_device=True,
            requires_macos=True,
            notes=["Requires physical device connected via USB"],
        )
        d = t.to_dict()
        t2 = MobileTestTarget.from_dict(d)
        assert t2.app_surface == "ios_app"
        assert t2.device_name == "iPhone 15 Pro"
        assert t2.requires_macos is True
        assert t2.requires_real_device is True


# ---------------------------------------------------------------------------
# MobileExecutionPlan (nested)
# ---------------------------------------------------------------------------

class TestMobileExecutionPlan:
    def test_safe_defaults(self):
        plan = MobileExecutionPlan(project_id="p1")
        assert plan.can_run_from_current_desktop is False
        assert plan.approval_required is True
        assert plan.safe_to_execute is False
        assert plan.targets == []
        assert plan.recommended_tooling == []

    def test_from_dict_reconstructs_targets(self):
        data = {
            "project_id": "p1",
            "targets": [
                {"app_surface": "mobile_web", "execution_target": "playwright_mobile_web_emulation", "platform_name": "chromium"},
                {"app_surface": "android_app", "execution_target": "android_emulator", "platform_name": "Android"},
            ],
        }
        plan = MobileExecutionPlan.from_dict(data)
        assert len(plan.targets) == 2
        assert all(isinstance(t, MobileTestTarget) for t in plan.targets)
        assert plan.targets[0].execution_target == "playwright_mobile_web_emulation"
        assert plan.targets[1].app_surface == "android_app"

    def test_roundtrip(self):
        target = MobileTestTarget(
            app_surface="mobile_web",
            execution_target="playwright_mobile_web_emulation",
        )
        plan = MobileExecutionPlan(
            project_id="p1",
            targets=[target],
            recommended_tooling=["playwright"],
            can_run_from_current_desktop=True,
            desktop_limitations=["Android real device requires USB cable"],
            safe_to_execute=False,
        )
        plan2 = MobileExecutionPlan.from_dict(plan.to_dict())
        assert plan2.can_run_from_current_desktop is True
        assert plan2.safe_to_execute is False
        assert isinstance(plan2.targets[0], MobileTestTarget)
        assert plan2.targets[0].execution_target == "playwright_mobile_web_emulation"
        assert "Android real device requires USB cable" in plan2.desktop_limitations

    def test_importable_from_package(self):
        import core.schemas as s
        assert s.MobileTestTarget is not None
        assert s.MobileExecutionPlan is not None
        assert "playwright_mobile_web_emulation" in s.MOBILE_EXECUTION_TARGETS
        assert "playwright" in s.MOBILE_TOOLING_OPTIONS
