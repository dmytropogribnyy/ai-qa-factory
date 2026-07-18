"""Phase 7A tests -- Auth Capability Planner.

~90 tests covering:
  - AuthMethodType (15 methods) and AuthReadiness (7 states) enums
  - AuthMethodCapability: construction, to_dict, from_dict
  - AuthCapabilityInputs: construction, safety invariants via __post_init__
  - AuthCapabilityPlan: safety invariants via __post_init__
  - AuthCapabilityPlanner.build_plan(): per-method classification
  - Email/password, Google OAuth, GitHub OAuth, Microsoft OAuth
  - SSO/SAML, magic link, email OTP, TOTP, storageState, CDP, API token, bearer, basic auth, session cookie
  - Safety: invariants enforced regardless of caller input
  - CLI: blocked flags exit 1, --no-write, --json-output
  - Artifacts: JSON and MD written correctly
  - Recommended next steps logic
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from core.auth_capability_planner import AuthCapabilityPlanner, _plan_to_dict
from core.schemas.auth_capability import (
    AuthCapabilityInputs,
    AuthCapabilityPlan,
    AuthMethodCapability,
    AuthMethodType,
    AuthReadiness,
)

# Repository root, derived from this file's location so the CLI subprocess runs
# from the project root on any machine/OS (never a hardcoded absolute path).
_REPO_ROOT = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _inputs(
    project_id: str = "test-proj",
    has_dedicated_test_account: bool = False,
    password_env_var: str = "",
    api_token_env_var: str = "",
    bearer_token_env_var: str = "",
    totp_seed_env_var: str = "",
    storage_state_file: str = "",
    has_storage_state: bool = False,
    has_google_account: bool = False,
    has_github_account: bool = False,
    has_microsoft_account: bool = False,
    target_url: str = "",
    write_files: bool = False,
    outputs_root: str = "outputs",
) -> AuthCapabilityInputs:
    return AuthCapabilityInputs(
        project_id=project_id,
        target_url=target_url,
        has_dedicated_test_account=has_dedicated_test_account,
        password_env_var=password_env_var,
        api_token_env_var=api_token_env_var,
        bearer_token_env_var=bearer_token_env_var,
        totp_seed_env_var=totp_seed_env_var,
        storage_state_file=storage_state_file,
        has_storage_state=has_storage_state,
        has_google_account=has_google_account,
        has_github_account=has_github_account,
        has_microsoft_account=has_microsoft_account,
        outputs_root=outputs_root,
        write_files=write_files,
    )


def _plan(inp: AuthCapabilityInputs) -> AuthCapabilityPlan:
    return AuthCapabilityPlanner(inp).build_plan()


def _cap(plan: AuthCapabilityPlan, method: AuthMethodType) -> AuthMethodCapability:
    return next(c for c in plan.capabilities if c.method == method)


# ---------------------------------------------------------------------------
# TestAuthMethodTypeEnum
# ---------------------------------------------------------------------------

class TestAuthMethodTypeEnum:
    def test_fifteen_methods(self) -> None:
        assert len(list(AuthMethodType)) == 15

    def test_all_expected_values(self) -> None:
        expected = {
            "email_password", "google_oauth", "github_oauth", "microsoft_oauth",
            "sso_saml_oidc", "magic_link", "email_otp", "totp_mfa",
            "storage_state_reuse", "cdp_attach", "dedicated_profile_context",
            "api_token", "bearer_token", "basic_auth", "session_cookie_reuse",
        }
        assert {m.value for m in AuthMethodType} == expected

    def test_str_subclass(self) -> None:
        assert isinstance(AuthMethodType.EMAIL_PASSWORD, str)
        assert AuthMethodType.GOOGLE_OAUTH == "google_oauth"


# ---------------------------------------------------------------------------
# TestAuthReadinessEnum
# ---------------------------------------------------------------------------

class TestAuthReadinessEnum:
    def test_seven_states(self) -> None:
        assert len(list(AuthReadiness)) == 7

    def test_all_values(self) -> None:
        expected = {
            "allowed_now", "planning_only", "blocked",
            "requires_manual_step", "requires_test_account",
            "requires_env_var_secret", "requires_client_confirmation",
        }
        assert {r.value for r in AuthReadiness} == expected

    def test_str_subclass(self) -> None:
        assert isinstance(AuthReadiness.ALLOWED_NOW, str)


# ---------------------------------------------------------------------------
# TestAuthMethodCapability
# ---------------------------------------------------------------------------

class TestAuthMethodCapability:
    def test_construction(self) -> None:
        cap = AuthMethodCapability(
            method=AuthMethodType.EMAIL_PASSWORD,
            readiness=AuthReadiness.ALLOWED_NOW,
            reason="Test",
        )
        assert cap.method == AuthMethodType.EMAIL_PASSWORD
        assert cap.readiness == AuthReadiness.ALLOWED_NOW

    def test_defaults(self) -> None:
        cap = AuthMethodCapability(
            method=AuthMethodType.API_TOKEN,
            readiness=AuthReadiness.PLANNING_ONLY,
        )
        assert cap.reason == ""
        assert cap.required_inputs == []
        assert cap.blocked_reasons == []
        assert cap.notes == ""

    def test_to_dict_keys(self) -> None:
        cap = AuthMethodCapability(
            method=AuthMethodType.GOOGLE_OAUTH,
            readiness=AuthReadiness.REQUIRES_MANUAL_STEP,
            reason="manual capture",
            required_inputs=["storageState"],
        )
        d = cap.to_dict()
        assert set(d.keys()) == {"method", "readiness", "reason", "required_inputs", "blocked_reasons", "notes"}

    def test_to_dict_values_serialized(self) -> None:
        cap = AuthMethodCapability(
            method=AuthMethodType.TOTP_MFA,
            readiness=AuthReadiness.REQUIRES_ENV_VAR_SECRET,
        )
        d = cap.to_dict()
        assert d["method"] == "totp_mfa"
        assert d["readiness"] == "requires_env_var_secret"

    def test_from_dict_roundtrip(self) -> None:
        cap = AuthMethodCapability(
            method=AuthMethodType.STORAGE_STATE_REUSE,
            readiness=AuthReadiness.ALLOWED_NOW,
            reason="file present",
            required_inputs=["path"],
            notes="ok",
        )
        cap2 = AuthMethodCapability.from_dict(cap.to_dict())
        assert cap2.method == cap.method
        assert cap2.readiness == cap.readiness
        assert cap2.reason == cap.reason

    def test_from_dict_defaults(self) -> None:
        cap = AuthMethodCapability.from_dict({})
        assert cap.method == AuthMethodType.EMAIL_PASSWORD
        assert cap.readiness == AuthReadiness.PLANNING_ONLY


# ---------------------------------------------------------------------------
# TestAuthCapabilityInputsSafetyInvariants
# ---------------------------------------------------------------------------

class TestAuthCapabilityInputsSafetyInvariants:
    def test_personal_account_always_false(self) -> None:
        inp = AuthCapabilityInputs(project_id="p", personal_account_allowed=True)
        assert inp.personal_account_allowed is False

    def test_production_account_always_false(self) -> None:
        inp = AuthCapabilityInputs(project_id="p", production_account_allowed=True)
        assert inp.production_account_allowed is False

    def test_captcha_bypass_always_false(self) -> None:
        inp = AuthCapabilityInputs(project_id="p", captcha_bypass_allowed=True)
        assert inp.captcha_bypass_allowed is False

    def test_storage_state_content_read_always_false(self) -> None:
        inp = AuthCapabilityInputs(project_id="p", storage_state_content_read=True)
        assert inp.storage_state_content_read is False

    def test_auth_bypass_always_false(self) -> None:
        inp = AuthCapabilityInputs(project_id="p", auth_bypass_allowed=True)
        assert inp.auth_bypass_allowed is False

    def test_client_delivery_auto_approved_always_false(self) -> None:
        inp = AuthCapabilityInputs(project_id="p", client_delivery_auto_approved=True)
        assert inp.client_delivery_auto_approved is False

    def test_human_review_always_true(self) -> None:
        inp = AuthCapabilityInputs(project_id="p", human_review_required=False)
        assert inp.human_review_required is True

    def test_from_dict_ignores_security_flags(self) -> None:
        data = {"project_id": "p", "personal_account_allowed": True, "captcha_bypass_allowed": True}
        inp = AuthCapabilityInputs.from_dict(data)
        assert inp.personal_account_allowed is False
        assert inp.captcha_bypass_allowed is False


# ---------------------------------------------------------------------------
# TestAuthCapabilityPlanSafetyInvariants
# ---------------------------------------------------------------------------

class TestAuthCapabilityPlanSafetyInvariants:
    def test_personal_account_always_false(self) -> None:
        plan = AuthCapabilityPlan(project_id="p", personal_account_allowed=True)
        assert plan.personal_account_allowed is False

    def test_production_account_always_false(self) -> None:
        plan = AuthCapabilityPlan(project_id="p", production_account_allowed=True)
        assert plan.production_account_allowed is False

    def test_captcha_bypass_always_false(self) -> None:
        plan = AuthCapabilityPlan(project_id="p", captcha_bypass_allowed=True)
        assert plan.captcha_bypass_allowed is False

    def test_auth_bypass_always_false(self) -> None:
        plan = AuthCapabilityPlan(project_id="p", auth_bypass_allowed=True)
        assert plan.auth_bypass_allowed is False

    def test_human_review_always_true(self) -> None:
        plan = AuthCapabilityPlan(project_id="p", human_review_required=False)
        assert plan.human_review_required is True


# ---------------------------------------------------------------------------
# TestEmailPasswordClassification
# ---------------------------------------------------------------------------

class TestEmailPasswordClassification:
    def test_allowed_now_with_account_and_env_var(self) -> None:
        inp = _inputs(has_dedicated_test_account=True, password_env_var="QA_PASS")
        cap = _cap(_plan(inp), AuthMethodType.EMAIL_PASSWORD)
        assert cap.readiness == AuthReadiness.ALLOWED_NOW

    def test_requires_env_var_with_account_no_env(self) -> None:
        inp = _inputs(has_dedicated_test_account=True)
        cap = _cap(_plan(inp), AuthMethodType.EMAIL_PASSWORD)
        assert cap.readiness == AuthReadiness.REQUIRES_ENV_VAR_SECRET

    def test_requires_test_account_when_no_account(self) -> None:
        inp = _inputs()
        cap = _cap(_plan(inp), AuthMethodType.EMAIL_PASSWORD)
        assert cap.readiness == AuthReadiness.REQUIRES_TEST_ACCOUNT

    def test_required_inputs_contain_env_var_name(self) -> None:
        inp = _inputs(has_dedicated_test_account=True, password_env_var="MY_PASSWORD")
        cap = _cap(_plan(inp), AuthMethodType.EMAIL_PASSWORD)
        assert any("MY_PASSWORD" in r for r in cap.required_inputs)

    def test_blocked_reasons_mention_personal_account(self) -> None:
        inp = _inputs()
        cap = _cap(_plan(inp), AuthMethodType.EMAIL_PASSWORD)
        assert any("personal" in r.lower() for r in cap.blocked_reasons)


# ---------------------------------------------------------------------------
# TestGoogleOAuthClassification
# ---------------------------------------------------------------------------

class TestGoogleOAuthClassification:
    def test_allowed_now_with_account_and_storage_state(self) -> None:
        inp = _inputs(has_google_account=True, has_storage_state=True)
        cap = _cap(_plan(inp), AuthMethodType.GOOGLE_OAUTH)
        assert cap.readiness == AuthReadiness.ALLOWED_NOW

    def test_allowed_now_with_storage_state_file(self) -> None:
        inp = _inputs(has_google_account=True, storage_state_file="/tmp/ss.json")
        cap = _cap(_plan(inp), AuthMethodType.GOOGLE_OAUTH)
        assert cap.readiness == AuthReadiness.ALLOWED_NOW

    def test_requires_manual_step_with_account_no_storage(self) -> None:
        inp = _inputs(has_google_account=True)
        cap = _cap(_plan(inp), AuthMethodType.GOOGLE_OAUTH)
        assert cap.readiness == AuthReadiness.REQUIRES_MANUAL_STEP

    def test_requires_test_account_when_no_google_account(self) -> None:
        inp = _inputs()
        cap = _cap(_plan(inp), AuthMethodType.GOOGLE_OAUTH)
        assert cap.readiness == AuthReadiness.REQUIRES_TEST_ACCOUNT


# ---------------------------------------------------------------------------
# TestGitHubOAuthClassification
# ---------------------------------------------------------------------------

class TestGitHubOAuthClassification:
    def test_allowed_now_with_account_and_storage_state(self) -> None:
        inp = _inputs(has_github_account=True, has_storage_state=True)
        cap = _cap(_plan(inp), AuthMethodType.GITHUB_OAUTH)
        assert cap.readiness == AuthReadiness.ALLOWED_NOW

    def test_requires_manual_step_with_account_no_storage(self) -> None:
        inp = _inputs(has_github_account=True)
        cap = _cap(_plan(inp), AuthMethodType.GITHUB_OAUTH)
        assert cap.readiness == AuthReadiness.REQUIRES_MANUAL_STEP

    def test_requires_test_account_when_no_github_account(self) -> None:
        inp = _inputs()
        cap = _cap(_plan(inp), AuthMethodType.GITHUB_OAUTH)
        assert cap.readiness == AuthReadiness.REQUIRES_TEST_ACCOUNT


# ---------------------------------------------------------------------------
# TestMicrosoftOAuthClassification
# ---------------------------------------------------------------------------

class TestMicrosoftOAuthClassification:
    def test_allowed_now_with_account_and_storage_state(self) -> None:
        inp = _inputs(has_microsoft_account=True, has_storage_state=True)
        cap = _cap(_plan(inp), AuthMethodType.MICROSOFT_OAUTH)
        assert cap.readiness == AuthReadiness.ALLOWED_NOW

    def test_requires_manual_step_with_account_no_storage(self) -> None:
        inp = _inputs(has_microsoft_account=True)
        cap = _cap(_plan(inp), AuthMethodType.MICROSOFT_OAUTH)
        assert cap.readiness == AuthReadiness.REQUIRES_MANUAL_STEP

    def test_requires_test_account_when_no_microsoft_account(self) -> None:
        inp = _inputs()
        cap = _cap(_plan(inp), AuthMethodType.MICROSOFT_OAUTH)
        assert cap.readiness == AuthReadiness.REQUIRES_TEST_ACCOUNT

    def test_notes_mention_personal_blocked(self) -> None:
        inp = _inputs(has_microsoft_account=True)
        cap = _cap(_plan(inp), AuthMethodType.MICROSOFT_OAUTH)
        assert "personal" in cap.notes.lower() or "blocked" in " ".join(cap.blocked_reasons).lower() or "Personal" in cap.notes


# ---------------------------------------------------------------------------
# TestSSOSAMLClassification
# ---------------------------------------------------------------------------

class TestSSOSAMLClassification:
    def test_always_requires_client_confirmation(self) -> None:
        inp = _inputs()
        cap = _cap(_plan(inp), AuthMethodType.SSO_SAML_OIDC)
        assert cap.readiness == AuthReadiness.REQUIRES_CLIENT_CONFIRMATION

    def test_still_requires_confirmation_with_all_inputs(self) -> None:
        inp = _inputs(has_dedicated_test_account=True, has_storage_state=True)
        cap = _cap(_plan(inp), AuthMethodType.SSO_SAML_OIDC)
        assert cap.readiness == AuthReadiness.REQUIRES_CLIENT_CONFIRMATION


# ---------------------------------------------------------------------------
# TestTOTPClassification
# ---------------------------------------------------------------------------

class TestTOTPClassification:
    def test_allowed_now_with_seed_env_var(self) -> None:
        inp = _inputs(totp_seed_env_var="TEST_TOTP_SEED")
        cap = _cap(_plan(inp), AuthMethodType.TOTP_MFA)
        assert cap.readiness == AuthReadiness.ALLOWED_NOW

    def test_requires_env_var_with_account_no_seed_var(self) -> None:
        inp = _inputs(has_dedicated_test_account=True)
        cap = _cap(_plan(inp), AuthMethodType.TOTP_MFA)
        assert cap.readiness == AuthReadiness.REQUIRES_ENV_VAR_SECRET

    def test_requires_test_account_when_no_account(self) -> None:
        inp = _inputs()
        cap = _cap(_plan(inp), AuthMethodType.TOTP_MFA)
        assert cap.readiness == AuthReadiness.REQUIRES_TEST_ACCOUNT

    def test_notes_mention_no_raw_seed(self) -> None:
        inp = _inputs(totp_seed_env_var="TOTP_SEED")
        cap = _cap(_plan(inp), AuthMethodType.TOTP_MFA)
        assert "raw" in cap.notes.lower() or "never" in cap.notes.lower()


# ---------------------------------------------------------------------------
# TestStorageStateReuse
# ---------------------------------------------------------------------------

class TestStorageStateReuse:
    def test_allowed_now_with_has_storage_state(self) -> None:
        inp = _inputs(has_storage_state=True)
        cap = _cap(_plan(inp), AuthMethodType.STORAGE_STATE_REUSE)
        assert cap.readiness == AuthReadiness.ALLOWED_NOW

    def test_allowed_now_with_storage_state_file(self) -> None:
        inp = _inputs(storage_state_file="/tmp/state.json")
        cap = _cap(_plan(inp), AuthMethodType.STORAGE_STATE_REUSE)
        assert cap.readiness == AuthReadiness.ALLOWED_NOW

    def test_requires_manual_step_when_no_state(self) -> None:
        inp = _inputs()
        cap = _cap(_plan(inp), AuthMethodType.STORAGE_STATE_REUSE)
        assert cap.readiness == AuthReadiness.REQUIRES_MANUAL_STEP

    def test_notes_say_content_not_read(self) -> None:
        inp = _inputs(has_storage_state=True)
        cap = _cap(_plan(inp), AuthMethodType.STORAGE_STATE_REUSE)
        assert "content" in cap.notes.lower() or "never read" in cap.notes.lower()


# ---------------------------------------------------------------------------
# TestApiTokenAndBearerToken
# ---------------------------------------------------------------------------

class TestApiTokenAndBearerToken:
    def test_api_token_allowed_now_with_env_var(self) -> None:
        inp = _inputs(api_token_env_var="QA_API_TOKEN")
        cap = _cap(_plan(inp), AuthMethodType.API_TOKEN)
        assert cap.readiness == AuthReadiness.ALLOWED_NOW

    def test_api_token_requires_env_var_without_it(self) -> None:
        inp = _inputs()
        cap = _cap(_plan(inp), AuthMethodType.API_TOKEN)
        assert cap.readiness == AuthReadiness.REQUIRES_ENV_VAR_SECRET

    def test_bearer_token_allowed_now_with_env_var(self) -> None:
        inp = _inputs(bearer_token_env_var="QA_BEARER")
        cap = _cap(_plan(inp), AuthMethodType.BEARER_TOKEN)
        assert cap.readiness == AuthReadiness.ALLOWED_NOW

    def test_bearer_token_requires_env_var_without_it(self) -> None:
        inp = _inputs()
        cap = _cap(_plan(inp), AuthMethodType.BEARER_TOKEN)
        assert cap.readiness == AuthReadiness.REQUIRES_ENV_VAR_SECRET

    def test_api_token_env_var_name_in_required_inputs(self) -> None:
        inp = _inputs(api_token_env_var="MY_API_TOKEN")
        cap = _cap(_plan(inp), AuthMethodType.API_TOKEN)
        assert any("MY_API_TOKEN" in r for r in cap.required_inputs)


# ---------------------------------------------------------------------------
# TestCDPAttachAndProfileContext
# ---------------------------------------------------------------------------

class TestCDPAttachAndProfileContext:
    def test_cdp_attach_requires_manual_with_url(self) -> None:
        inp = _inputs(target_url="https://example.com")
        cap = _cap(_plan(inp), AuthMethodType.CDP_ATTACH)
        assert cap.readiness == AuthReadiness.REQUIRES_MANUAL_STEP

    def test_cdp_attach_planning_only_without_url(self) -> None:
        inp = _inputs()
        cap = _cap(_plan(inp), AuthMethodType.CDP_ATTACH)
        assert cap.readiness == AuthReadiness.PLANNING_ONLY

    def test_dedicated_profile_allowed_with_url(self) -> None:
        inp = _inputs(target_url="https://example.com")
        cap = _cap(_plan(inp), AuthMethodType.DEDICATED_PROFILE_CONTEXT)
        assert cap.readiness == AuthReadiness.ALLOWED_NOW

    def test_dedicated_profile_planning_without_url(self) -> None:
        inp = _inputs()
        cap = _cap(_plan(inp), AuthMethodType.DEDICATED_PROFILE_CONTEXT)
        assert cap.readiness == AuthReadiness.PLANNING_ONLY


# ---------------------------------------------------------------------------
# TestPlanAggregate
# ---------------------------------------------------------------------------

class TestPlanAggregate:
    def test_plan_has_15_capabilities(self) -> None:
        plan = _plan(_inputs())
        assert len(plan.capabilities) == 15

    def test_all_methods_classified(self) -> None:
        plan = _plan(_inputs())
        classified = {c.method for c in plan.capabilities}
        assert classified == set(AuthMethodType)

    def test_allowed_now_empty_by_default(self) -> None:
        plan = _plan(_inputs())
        assert plan.allowed_now_methods == []

    def test_allowed_now_with_api_token(self) -> None:
        plan = _plan(_inputs(api_token_env_var="TOKEN"))
        assert "api_token" in plan.allowed_now_methods

    def test_requires_action_populated(self) -> None:
        plan = _plan(_inputs())
        assert len(plan.requires_action_methods) > 0

    def test_next_steps_present(self) -> None:
        plan = _plan(_inputs())
        assert len(plan.recommended_next_steps) > 0

    def test_project_id_in_plan(self) -> None:
        plan = _plan(_inputs(project_id="acme"))
        assert plan.project_id == "acme"

    def test_safety_invariants_in_plan(self) -> None:
        plan = _plan(_inputs())
        assert plan.personal_account_allowed is False
        assert plan.captcha_bypass_allowed is False
        assert plan.human_review_required is True


# ---------------------------------------------------------------------------
# TestPlanToDict
# ---------------------------------------------------------------------------

class TestPlanToDict:
    def test_dict_has_required_keys(self) -> None:
        plan = _plan(_inputs())
        d = _plan_to_dict(plan)
        assert "project_id" in d
        assert "capabilities" in d
        assert "allowed_now_methods" in d
        assert "planning_only_methods" in d
        assert "requires_action_methods" in d
        assert "blocked_methods" in d
        assert "recommended_next_steps" in d
        assert "human_review_required" in d
        assert "personal_account_allowed" in d
        assert "captcha_bypass_allowed" in d

    def test_capabilities_serialized_as_list_of_dicts(self) -> None:
        plan = _plan(_inputs())
        d = _plan_to_dict(plan)
        assert isinstance(d["capabilities"], list)
        assert all(isinstance(c, dict) for c in d["capabilities"])

    def test_safety_invariants_false_in_dict(self) -> None:
        plan = _plan(_inputs())
        d = _plan_to_dict(plan)
        assert d["personal_account_allowed"] is False
        assert d["captcha_bypass_allowed"] is False
        assert d["auth_bypass_allowed"] is False

    def test_json_serializable(self) -> None:
        plan = _plan(_inputs())
        d = _plan_to_dict(plan)
        serialized = json.dumps(d)
        assert len(serialized) > 100


# ---------------------------------------------------------------------------
# TestWriteArtifacts
# ---------------------------------------------------------------------------

class TestWriteArtifacts:
    def test_write_creates_plan_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = _inputs(outputs_root=tmpdir, write_files=True)
            AuthCapabilityPlanner(inp).run()
            path = Path(tmpdir) / "test-proj" / "34_auth_capability" / "auth_capability_plan.json"
            assert path.exists()

    def test_write_creates_summary_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = _inputs(outputs_root=tmpdir, write_files=True)
            AuthCapabilityPlanner(inp).run()
            path = Path(tmpdir) / "test-proj" / "34_auth_capability" / "auth_capability_summary.md"
            assert path.exists()

    def test_json_valid(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = _inputs(outputs_root=tmpdir, write_files=True)
            AuthCapabilityPlanner(inp).run()
            path = Path(tmpdir) / "test-proj" / "34_auth_capability" / "auth_capability_plan.json"
            data = json.loads(path.read_text(encoding="utf-8"))
            assert "capabilities" in data
            assert len(data["capabilities"]) == 15

    def test_no_write_produces_no_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = _inputs(outputs_root=tmpdir, write_files=False)
            AuthCapabilityPlanner(inp).run()
            path = Path(tmpdir) / "test-proj" / "34_auth_capability"
            assert not path.exists()

    def test_summary_md_contains_safety_invariants(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = _inputs(outputs_root=tmpdir, write_files=True)
            AuthCapabilityPlanner(inp).run()
            path = Path(tmpdir) / "test-proj" / "34_auth_capability" / "auth_capability_summary.md"
            content = path.read_text(encoding="utf-8")
            assert "personal_account_allowed" in content
            assert "captcha_bypass_allowed" in content

    def test_summary_md_contains_all_methods(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = _inputs(outputs_root=tmpdir, write_files=True)
            AuthCapabilityPlanner(inp).run()
            path = Path(tmpdir) / "test-proj" / "34_auth_capability" / "auth_capability_summary.md"
            content = path.read_text(encoding="utf-8")
            for method in AuthMethodType:
                assert method.value in content


# ---------------------------------------------------------------------------
# TestCLIBlockedFlags
# ---------------------------------------------------------------------------

class TestCLIBlockedFlags:
    def _run_cli(self, extra_args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(_REPO_ROOT / "tools" / "plan_auth_capability.py")] + extra_args,
            capture_output=True, text=True, cwd=str(_REPO_ROOT),
        )

    def test_blocked_password_flag(self) -> None:
        result = self._run_cli(["--password", "secret123"])
        assert result.returncode == 1
        assert "blocked" in result.stdout.lower() or "Forbidden" in result.stdout

    def test_blocked_secret_flag(self) -> None:
        result = self._run_cli(["--secret", "mysecret"])
        assert result.returncode == 1

    def test_blocked_token_flag(self) -> None:
        result = self._run_cli(["--token", "mytoken"])
        assert result.returncode == 1

    def test_blocked_totp_seed_flag(self) -> None:
        result = self._run_cli(["--totp-seed", "123456"])
        assert result.returncode == 1

    def test_blocked_bearer_flag(self) -> None:
        result = self._run_cli(["--bearer", "mybearer"])
        assert result.returncode == 1

    def test_blocked_client_secret_flag(self) -> None:
        result = self._run_cli(["--client-secret", "secret"])
        assert result.returncode == 1

    def test_no_write_dry_run(self) -> None:
        result = self._run_cli(["--project-id", "cli-test", "--no-write"])
        assert result.returncode == 0
        assert "[OK]" in result.stdout

    def test_json_output_flag(self) -> None:
        result = self._run_cli(["--project-id", "json-test", "--no-write", "--json-output"])
        assert result.returncode == 0
        assert "capabilities" in result.stdout

    def test_default_run_prints_summary(self) -> None:
        result = self._run_cli(["--project-id", "default-test", "--no-write"])
        assert result.returncode == 0
        assert "Auth Capability Plan" in result.stdout

    def test_allowed_env_var_flag_not_blocked(self) -> None:
        result = self._run_cli([
            "--project-id", "env-test",
            "--password-env-var", "QA_PASSWORD",
            "--has-dedicated-test-account",
            "--no-write",
        ])
        assert result.returncode == 0
