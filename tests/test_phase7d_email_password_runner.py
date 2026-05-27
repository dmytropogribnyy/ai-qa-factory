"""
Phase 7D — Email/Password Auth Runner tests.

Covers: schema safety invariants, plan building, run logic, env var checks,
URL validation, render_artifacts, format_auth_coverage_section, CLI blocked flags.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch


sys.path.insert(0, str(Path(__file__).parent.parent))

from core.email_password_runner import (
    EmailPasswordRunner,
    _ALLOWED_LOGIN_URL_PREFIXES,
    _ALWAYS_BLOCKED_SUBSTRINGS,
)
from core.schemas.email_password import (
    ORANGEHRM_DEFAULT_LOGIN_URL,
    ORANGEHRM_DEFAULT_SUCCESS_URL,
    SUPPORTED_TARGETS,
    EmailPasswordInputs,
    EmailPasswordModeReadiness,
    EmailPasswordPlan,
    EmailPasswordRunResult,
    EmailPasswordRunStatus,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
TOOL_PATH = Path(__file__).parent.parent / "tools" / "run_email_password_smoke.py"


def _inputs(**kwargs) -> EmailPasswordInputs:
    defaults = dict(
        project_id="test-proj",
        target_name="orangehrm_demo",
        login_url=ORANGEHRM_DEFAULT_LOGIN_URL,
        success_url=ORANGEHRM_DEFAULT_SUCCESS_URL,
        username_env_var="ORANGEHRM_USERNAME",
        password_env_var="ORANGEHRM_PASSWORD",
        dedicated_test_account_confirmed=True,
        approve_execution=False,
    )
    defaults.update(kwargs)
    return EmailPasswordInputs(**defaults)


def _runner(tmp_path: Path) -> EmailPasswordRunner:
    return EmailPasswordRunner(outputs_root=tmp_path)


# ===========================================================================
# 1. Schema — EmailPasswordInputs safety invariants
# ===========================================================================
class TestEmailPasswordInputsSafetyInvariants:
    def test_raw_secrets_always_false(self):
        inp = EmailPasswordInputs(project_id="p", raw_secrets_allowed=True)
        assert inp.raw_secrets_allowed is False

    def test_personal_account_always_false(self):
        inp = EmailPasswordInputs(project_id="p", personal_account_allowed=True)
        assert inp.personal_account_allowed is False

    def test_production_account_always_false(self):
        inp = EmailPasswordInputs(project_id="p", production_account_allowed=True)
        assert inp.production_account_allowed is False

    def test_captcha_bypass_always_false(self):
        inp = EmailPasswordInputs(project_id="p", captcha_bypass_allowed=True)
        assert inp.captcha_bypass_allowed is False

    def test_credential_logging_always_false(self):
        inp = EmailPasswordInputs(project_id="p", credential_logging_allowed=True)
        assert inp.credential_logging_allowed is False

    def test_client_delivery_always_false(self):
        inp = EmailPasswordInputs(project_id="p", client_delivery_allowed=True)
        assert inp.client_delivery_allowed is False

    def test_human_review_always_true(self):
        inp = EmailPasswordInputs(project_id="p", human_review_required=False)
        assert inp.human_review_required is True

    def test_from_dict_cannot_override_safety(self):
        d = {
            "project_id": "p",
            "raw_secrets_allowed": True,
            "captcha_bypass_allowed": True,
            "human_review_required": False,
        }
        inp = EmailPasswordInputs.from_dict(d)
        assert inp.raw_secrets_allowed is False
        assert inp.captcha_bypass_allowed is False
        assert inp.human_review_required is True

    def test_to_dict_contains_safety_block(self):
        d = EmailPasswordInputs(project_id="p").to_dict()
        safety = d["safety"]
        assert safety["raw_secrets_allowed"] is False
        assert safety["human_review_required"] is True

    def test_defaults(self):
        inp = EmailPasswordInputs(project_id="p")
        assert inp.target_name == "orangehrm_demo"
        assert inp.username_env_var == "ORANGEHRM_USERNAME"
        assert inp.password_env_var == "ORANGEHRM_PASSWORD"
        assert inp.dedicated_test_account_confirmed is False
        assert inp.approve_execution is False


# ===========================================================================
# 2. Schema — EmailPasswordPlan safety invariants
# ===========================================================================
class TestEmailPasswordPlanSafetyInvariants:
    def test_plan_raw_secrets_always_false(self):
        plan = EmailPasswordPlan(
            project_id="p",
            target_name="orangehrm_demo",
            login_url="https://x.com",
            success_url="https://x.com/dash",
            username_env_var="U",
            password_env_var="P",
            raw_secrets_allowed=True,
        )
        assert plan.raw_secrets_allowed is False

    def test_plan_human_review_always_true(self):
        plan = EmailPasswordPlan(
            project_id="p",
            target_name="orangehrm_demo",
            login_url="https://x.com",
            success_url="https://x.com/dash",
            username_env_var="U",
            password_env_var="P",
            human_review_required=False,
        )
        assert plan.human_review_required is True

    def test_plan_to_dict_safety_block(self):
        plan = EmailPasswordPlan(
            project_id="p",
            target_name="orangehrm_demo",
            login_url="https://x.com",
            success_url="https://x.com/dash",
            username_env_var="U",
            password_env_var="P",
        )
        d = plan.to_dict()
        assert d["safety"]["raw_secrets_allowed"] is False
        assert d["safety"]["human_review_required"] is True


# ===========================================================================
# 3. Schema — EmailPasswordRunResult safety invariants
# ===========================================================================
class TestEmailPasswordRunResultSafetyInvariants:
    def _result(self, **kwargs) -> EmailPasswordRunResult:
        return EmailPasswordRunResult(
            project_id="p",
            target_name="orangehrm_demo",
            login_url="https://x.com",
            success_url="https://x.com/dash",
            **kwargs,
        )

    def test_approved_for_client_delivery_always_false(self):
        r = self._result(approved_for_client_delivery=True)
        assert r.approved_for_client_delivery is False

    def test_raw_secrets_always_false(self):
        r = self._result(raw_secrets_allowed=True)
        assert r.raw_secrets_allowed is False

    def test_human_review_always_true(self):
        r = self._result(human_review_required=False)
        assert r.human_review_required is True

    def test_to_dict_no_credential_values(self):
        r = self._result()
        d = r.to_dict()
        assert "username" not in json.dumps(d).lower() or "username_env_var" in d
        assert d["approved_for_client_delivery"] is False


# ===========================================================================
# 4. SUPPORTED_TARGETS constant
# ===========================================================================
class TestSupportedTargets:
    def test_orangehrm_demo_in_targets(self):
        assert "orangehrm_demo" in SUPPORTED_TARGETS

    def test_targets_is_set(self):
        assert isinstance(SUPPORTED_TARGETS, set)


# ===========================================================================
# 5. URL validation
# ===========================================================================
class TestUrlValidation:
    def setup_method(self):
        self.runner = EmailPasswordRunner()

    def test_https_allowed(self):
        assert self.runner._is_allowed_url("https://example.com") is True

    def test_localhost_http_allowed(self):
        assert self.runner._is_allowed_url("http://localhost:3000/login") is True

    def test_127_0_0_1_allowed(self):
        assert self.runner._is_allowed_url("http://127.0.0.1:8080") is True

    def test_plain_http_blocked(self):
        assert self.runner._is_allowed_url("http://example.com") is False

    def test_empty_string_blocked(self):
        assert self.runner._is_allowed_url("") is False

    def test_captcha_in_url_blocked(self):
        assert self.runner._is_allowed_url("https://example.com/captcha/login") is False

    def test_recaptcha_in_url_blocked(self):
        assert self.runner._is_allowed_url("https://example.com?recaptcha=1") is False

    def test_anti_bot_in_url_blocked(self):
        assert self.runner._is_allowed_url("https://example.com/anti-bot") is False

    def test_orangehrm_demo_url_allowed(self):
        assert self.runner._is_allowed_url(ORANGEHRM_DEFAULT_LOGIN_URL) is True


# ===========================================================================
# 6. check_env_vars — presence only, no value returned
# ===========================================================================
class TestCheckEnvVars:
    def setup_method(self):
        self.runner = EmailPasswordRunner()

    def test_both_unset(self):
        inp = _inputs(username_env_var="NO_SUCH_VAR_U", password_env_var="NO_SUCH_VAR_P")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("NO_SUCH_VAR_U", None)
            os.environ.pop("NO_SUCH_VAR_P", None)
            u, p = self.runner.check_env_vars(inp)
        assert u is False
        assert p is False

    def test_both_set(self):
        inp = _inputs(username_env_var="TEST_U_7D", password_env_var="TEST_P_7D")
        with patch.dict(os.environ, {"TEST_U_7D": "admin", "TEST_P_7D": "pass"}):
            u, p = self.runner.check_env_vars(inp)
        assert u is True
        assert p is True

    def test_only_username_set(self):
        inp = _inputs(username_env_var="TEST_U_7D", password_env_var="NO_SUCH_7D")
        env = {"TEST_U_7D": "admin"}
        env.pop("NO_SUCH_7D", None)
        with patch.dict(os.environ, env, clear=False):
            os.environ.pop("NO_SUCH_7D", None)
            u, p = self.runner.check_env_vars(inp)
        assert u is True
        assert p is False

    def test_returns_only_bool_not_value(self):
        inp = _inputs(username_env_var="TEST_U_7D2", password_env_var="TEST_P_7D2")
        with patch.dict(os.environ, {"TEST_U_7D2": "secret_value", "TEST_P_7D2": "pw"}):
            result = self.runner.check_env_vars(inp)
        # result must be (bool, bool), no string values
        assert all(isinstance(v, bool) for v in result)
        assert "secret_value" not in str(result)
        assert "pw" not in str(result)


# ===========================================================================
# 7. build_plan — readiness and blockers
# ===========================================================================
class TestBuildPlan:
    def setup_method(self):
        self.runner = EmailPasswordRunner()

    def test_planning_only_when_env_vars_missing(self):
        inp = _inputs(
            username_env_var="MISSING_U_7D",
            password_env_var="MISSING_P_7D",
            dedicated_test_account_confirmed=True,
        )
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MISSING_U_7D", None)
            os.environ.pop("MISSING_P_7D", None)
            plan = self.runner.build_plan(inp)
        assert plan.mode_readiness == EmailPasswordModeReadiness.PLANNING_ONLY
        assert any("MISSING_U_7D" in b for b in plan.blockers)

    def test_planning_only_when_no_confirmation(self):
        inp = _inputs(
            username_env_var="TEST_U_7D",
            password_env_var="TEST_P_7D",
            dedicated_test_account_confirmed=False,
        )
        with patch.dict(os.environ, {"TEST_U_7D": "a", "TEST_P_7D": "b"}):
            plan = self.runner.build_plan(inp)
        assert plan.mode_readiness == EmailPasswordModeReadiness.PLANNING_ONLY
        assert any("dedicated" in b.lower() for b in plan.blockers)

    def test_planning_only_when_unsupported_target(self):
        inp = _inputs(
            target_name="not_a_real_target",
            username_env_var="TEST_U_7D",
            password_env_var="TEST_P_7D",
            dedicated_test_account_confirmed=True,
        )
        with patch.dict(os.environ, {"TEST_U_7D": "a", "TEST_P_7D": "b"}):
            plan = self.runner.build_plan(inp)
        assert plan.mode_readiness == EmailPasswordModeReadiness.PLANNING_ONLY
        assert any("not_a_real_target" in b for b in plan.blockers)

    def test_planning_only_when_bad_url(self):
        inp = _inputs(
            login_url="http://example.com/login",
            username_env_var="TEST_U_7D",
            password_env_var="TEST_P_7D",
            dedicated_test_account_confirmed=True,
        )
        with patch.dict(os.environ, {"TEST_U_7D": "a", "TEST_P_7D": "b"}):
            plan = self.runner.build_plan(inp)
        assert plan.mode_readiness == EmailPasswordModeReadiness.PLANNING_ONLY
        assert any("login_url" in b for b in plan.blockers)

    def test_executable_when_all_conditions_met(self):
        inp = _inputs(
            username_env_var="TEST_U_7D",
            password_env_var="TEST_P_7D",
            dedicated_test_account_confirmed=True,
        )
        with patch.dict(os.environ, {"TEST_U_7D": "a", "TEST_P_7D": "b"}):
            plan = self.runner.build_plan(inp)
        assert plan.mode_readiness == EmailPasswordModeReadiness.EXECUTABLE
        assert plan.blockers == []

    def test_plan_env_set_flags_correct(self):
        inp = _inputs(
            username_env_var="TEST_U_7D",
            password_env_var="TEST_P_7D",
            dedicated_test_account_confirmed=True,
        )
        with patch.dict(os.environ, {"TEST_U_7D": "a", "TEST_P_7D": "b"}):
            plan = self.runner.build_plan(inp)
        assert plan.username_env_set is True
        assert plan.password_env_set is True

    def test_plan_notes_contain_safety_messages(self):
        inp = _inputs(username_env_var="TEST_U_7D", password_env_var="TEST_P_7D",
                      dedicated_test_account_confirmed=True)
        with patch.dict(os.environ, {"TEST_U_7D": "a", "TEST_P_7D": "b"}):
            plan = self.runner.build_plan(inp)
        notes_combined = " ".join(plan.notes).lower()
        assert "credential" in notes_combined

    def test_plan_never_contains_credential_values(self):
        secret = "super_secret_password_xyz"
        inp = _inputs(username_env_var="TEST_U_7D", password_env_var="TEST_P_7D",
                      dedicated_test_account_confirmed=True)
        with patch.dict(os.environ, {"TEST_U_7D": "admin", "TEST_P_7D": secret}):
            plan = self.runner.build_plan(inp)
        plan_str = json.dumps(plan.to_dict())
        assert secret not in plan_str
        assert "admin" not in plan_str


# ===========================================================================
# 8. run — planning-only and blocked states
# ===========================================================================
class TestRunPlanningOnly:
    def setup_method(self):
        self.runner = EmailPasswordRunner()

    def test_run_returns_planning_only_when_prereqs_missing(self):
        inp = _inputs(
            username_env_var="MISSING_U_7D",
            password_env_var="MISSING_P_7D",
            dedicated_test_account_confirmed=False,
        )
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MISSING_U_7D", None)
            os.environ.pop("MISSING_P_7D", None)
            result = self.runner.run(inp)
        assert result.status == EmailPasswordRunStatus.PLANNING_ONLY

    def test_run_blocked_without_approve_execution(self):
        inp = _inputs(
            username_env_var="TEST_U_7D",
            password_env_var="TEST_P_7D",
            dedicated_test_account_confirmed=True,
            approve_execution=False,
        )
        with patch.dict(os.environ, {"TEST_U_7D": "a", "TEST_P_7D": "b"}):
            result = self.runner.run(inp)
        assert result.status == EmailPasswordRunStatus.BLOCKED
        assert any("approve" in b.lower() for b in result.blockers)

    def test_run_result_safety_invariants_always_set(self):
        inp = _inputs(
            username_env_var="MISSING_U_7D2",
            password_env_var="MISSING_P_7D2",
        )
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MISSING_U_7D2", None)
            os.environ.pop("MISSING_P_7D2", None)
            result = self.runner.run(inp)
        assert result.approved_for_client_delivery is False
        assert result.human_review_required is True
        assert result.raw_secrets_allowed is False


# ===========================================================================
# 9. _execute_login_smoke — mocked subprocess
# ===========================================================================
class TestExecuteLoginSmoke:
    def _ready_inputs(self) -> EmailPasswordInputs:
        return _inputs(
            username_env_var="TEST_U_7D",
            password_env_var="TEST_P_7D",
            dedicated_test_account_confirmed=True,
            approve_execution=True,
        )

    def _mock_scaffold(self, tmp_path: Path) -> Path:
        scaffold = tmp_path / "test-proj" / "03_framework" / "playwright"
        nm = scaffold / "node_modules"
        nm.mkdir(parents=True)
        return scaffold

    def test_passed_on_zero_exit(self, tmp_path):
        self._mock_scaffold(tmp_path)
        runner = _runner(tmp_path)
        inp = self._ready_inputs()
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "[7D] login_success=true\n[7D] url=https://x.com/dashboard"
        mock_proc.stderr = ""
        with patch.dict(os.environ, {"TEST_U_7D": "admin", "TEST_P_7D": "pass"}):
            with patch("subprocess.run", return_value=mock_proc):
                result = runner.run(inp)
        assert result.status == EmailPasswordRunStatus.PASSED

    def test_failed_on_nonzero_exit(self, tmp_path):
        self._mock_scaffold(tmp_path)
        runner = _runner(tmp_path)
        inp = self._ready_inputs()
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.stdout = ""
        mock_proc.stderr = "[7D] login_success=false"
        with patch.dict(os.environ, {"TEST_U_7D": "admin", "TEST_P_7D": "pass"}):
            with patch("subprocess.run", return_value=mock_proc):
                result = runner.run(inp)
        assert result.status == EmailPasswordRunStatus.FAILED

    def test_failed_on_timeout(self, tmp_path):
        self._mock_scaffold(tmp_path)
        runner = _runner(tmp_path)
        inp = self._ready_inputs()
        with patch.dict(os.environ, {"TEST_U_7D": "admin", "TEST_P_7D": "pass"}):
            with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="node", timeout=60)):
                result = runner.run(inp)
        assert result.status == EmailPasswordRunStatus.FAILED
        assert any("Timeout" in r for r in result.smoke_results)

    def test_smoke_results_never_contain_credential_values(self, tmp_path):
        self._mock_scaffold(tmp_path)
        runner = _runner(tmp_path)
        inp = self._ready_inputs()
        secret_pw = "my_secret_pw_xyz"
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "[7D] login_success=true"
        mock_proc.stderr = ""
        with patch.dict(os.environ, {"TEST_U_7D": "admin_user", "TEST_P_7D": secret_pw}):
            with patch("subprocess.run", return_value=mock_proc):
                result = runner.run(inp)
        result_str = json.dumps(result.to_dict())
        assert secret_pw not in result_str
        assert "admin_user" not in result_str

    def test_env_vars_names_passed_not_values(self, tmp_path):
        """Verifies subprocess receives EP_USERNAME_ENV_VAR, not the actual credential."""
        self._mock_scaffold(tmp_path)
        runner = _runner(tmp_path)
        inp = self._ready_inputs()
        captured_env = {}
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""

        def capture_call(*args, **kwargs):
            captured_env.update(kwargs.get("env", {}))
            return mock_proc

        with patch.dict(os.environ, {"TEST_U_7D": "admin", "TEST_P_7D": "pw"}):
            with patch("subprocess.run", side_effect=capture_call):
                runner.run(inp)

        assert captured_env.get("EP_USERNAME_ENV_VAR") == "TEST_U_7D"
        assert captured_env.get("EP_PASSWORD_ENV_VAR") == "TEST_P_7D"

    def test_result_approved_for_client_delivery_always_false(self, tmp_path):
        self._mock_scaffold(tmp_path)
        runner = _runner(tmp_path)
        inp = self._ready_inputs()
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        with patch.dict(os.environ, {"TEST_U_7D": "admin", "TEST_P_7D": "pass"}):
            with patch("subprocess.run", return_value=mock_proc):
                result = runner.run(inp)
        assert result.approved_for_client_delivery is False

    def test_duration_seconds_recorded(self, tmp_path):
        self._mock_scaffold(tmp_path)
        runner = _runner(tmp_path)
        inp = self._ready_inputs()
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        with patch.dict(os.environ, {"TEST_U_7D": "admin", "TEST_P_7D": "pass"}):
            with patch("subprocess.run", return_value=mock_proc):
                result = runner.run(inp)
        assert isinstance(result.duration_seconds, float)
        assert result.duration_seconds >= 0.0

    def test_smoke_commands_contain_script_name(self, tmp_path):
        self._mock_scaffold(tmp_path)
        runner = _runner(tmp_path)
        inp = self._ready_inputs()
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = ""
        mock_proc.stderr = ""
        with patch.dict(os.environ, {"TEST_U_7D": "admin", "TEST_P_7D": "pass"}):
            with patch("subprocess.run", return_value=mock_proc):
                result = runner.run(inp)
        assert any("email_password_smoke_7d" in cmd for cmd in result.smoke_commands)


# ===========================================================================
# 10. render_artifacts
# ===========================================================================
class TestRenderArtifacts:
    def _plan(self) -> EmailPasswordPlan:
        return EmailPasswordPlan(
            project_id="test-proj",
            target_name="orangehrm_demo",
            login_url=ORANGEHRM_DEFAULT_LOGIN_URL,
            success_url=ORANGEHRM_DEFAULT_SUCCESS_URL,
            username_env_var="ORANGEHRM_USERNAME",
            password_env_var="ORANGEHRM_PASSWORD",
            mode_readiness=EmailPasswordModeReadiness.PLANNING_ONLY,
        )

    def _result(self) -> EmailPasswordRunResult:
        return EmailPasswordRunResult(
            project_id="test-proj",
            target_name="orangehrm_demo",
            login_url=ORANGEHRM_DEFAULT_LOGIN_URL,
            success_url=ORANGEHRM_DEFAULT_SUCCESS_URL,
            status=EmailPasswordRunStatus.PLANNING_ONLY,
            auth_coverage_summary="planning only",
        )

    def test_three_artifacts_created(self, tmp_path):
        runner = _runner(tmp_path)
        paths = runner.render_artifacts(self._plan(), self._result(), "test-proj")
        assert len(paths) == 3
        assert "email_password_plan_json" in paths
        assert "email_password_report_json" in paths
        assert "email_password_summary_md" in paths

    def test_artifact_files_exist(self, tmp_path):
        runner = _runner(tmp_path)
        paths = runner.render_artifacts(self._plan(), self._result(), "test-proj")
        for p in paths.values():
            assert Path(p).exists()

    def test_plan_json_valid(self, tmp_path):
        runner = _runner(tmp_path)
        paths = runner.render_artifacts(self._plan(), self._result(), "test-proj")
        content = Path(paths["email_password_plan_json"]).read_text()
        data = json.loads(content)
        assert data["project_id"] == "test-proj"
        assert data["safety"]["raw_secrets_allowed"] is False

    def test_report_json_valid(self, tmp_path):
        runner = _runner(tmp_path)
        paths = runner.render_artifacts(self._plan(), self._result(), "test-proj")
        content = Path(paths["email_password_report_json"]).read_text()
        data = json.loads(content)
        assert data["approved_for_client_delivery"] is False

    def test_summary_md_contains_project_id(self, tmp_path):
        runner = _runner(tmp_path)
        paths = runner.render_artifacts(self._plan(), self._result(), "test-proj")
        content = Path(paths["email_password_summary_md"]).read_text()
        assert "test-proj" in content

    def test_summary_md_contains_safety_boundary_table(self, tmp_path):
        runner = _runner(tmp_path)
        paths = runner.render_artifacts(self._plan(), self._result(), "test-proj")
        content = Path(paths["email_password_summary_md"]).read_text()
        assert "Safety Boundary" in content
        assert "False" in content

    def test_artifacts_in_correct_subdirectory(self, tmp_path):
        runner = _runner(tmp_path)
        paths = runner.render_artifacts(self._plan(), self._result(), "test-proj")
        for p in paths.values():
            assert "37_email_password_auth" in p


# ===========================================================================
# 11. format_auth_coverage_section
# ===========================================================================
class TestFormatAuthCoverageSection:
    def test_contains_target(self):
        result = EmailPasswordRunResult(
            project_id="p",
            target_name="orangehrm_demo",
            login_url="https://x.com",
            success_url="https://x.com/dash",
            status=EmailPasswordRunStatus.PASSED,
            auth_coverage_summary="passed",
        )
        section = EmailPasswordRunner().format_auth_coverage_section(result)
        assert "orangehrm_demo" in section

    def test_contains_status(self):
        result = EmailPasswordRunResult(
            project_id="p",
            target_name="orangehrm_demo",
            login_url="https://x.com",
            success_url="https://x.com/dash",
            status=EmailPasswordRunStatus.FAILED,
            auth_coverage_summary="failed",
        )
        section = EmailPasswordRunner().format_auth_coverage_section(result)
        assert "failed" in section

    def test_contains_safety_boundary_note(self):
        result = EmailPasswordRunResult(
            project_id="p",
            target_name="orangehrm_demo",
            login_url="https://x.com",
            success_url="https://x.com/dash",
        )
        section = EmailPasswordRunner().format_auth_coverage_section(result)
        assert "credential values never logged" in section.lower()

    def test_contains_approved_false(self):
        result = EmailPasswordRunResult(
            project_id="p",
            target_name="orangehrm_demo",
            login_url="https://x.com",
            success_url="https://x.com/dash",
        )
        section = EmailPasswordRunner().format_auth_coverage_section(result)
        assert "approved_for_client_delivery=False" in section


# ===========================================================================
# 12. _find_playwright_scaffold
# ===========================================================================
class TestFindPlaywrightScaffold:
    def test_finds_project_specific_scaffold(self, tmp_path):
        scaffold = tmp_path / "my-proj" / "03_framework" / "playwright"
        (scaffold / "node_modules").mkdir(parents=True)
        runner = _runner(tmp_path)
        found = runner._find_playwright_scaffold("my-proj")
        assert found == scaffold

    def test_falls_back_to_other_project_scaffold(self, tmp_path):
        other = tmp_path / "other-proj" / "03_framework" / "playwright"
        (other / "node_modules").mkdir(parents=True)
        runner = _runner(tmp_path)
        found = runner._find_playwright_scaffold("nonexistent-proj")
        assert found == other

    def test_returns_outputs_root_when_no_scaffold(self, tmp_path):
        runner = _runner(tmp_path)
        found = runner._find_playwright_scaffold("no-such-proj")
        assert found == tmp_path


# ===========================================================================
# 13. _build_login_script — content checks
# ===========================================================================
class TestBuildLoginScript:
    def setup_method(self):
        self.runner = EmailPasswordRunner()

    def test_script_reads_env_via_variable_name(self):
        script = self.runner._build_login_script(
            login_url="https://x.com/login",
            success_url="https://x.com/dash",
            username_env_var="MY_USER",
            password_env_var="MY_PASS",
        )
        # Must use EP_USERNAME_ENV_VAR indirection, not hardcoded var name
        assert "EP_USERNAME_ENV_VAR" in script
        assert "EP_PASSWORD_ENV_VAR" in script
        assert "process.env[USERNAME_ENV_VAR]" in script

    def test_script_does_not_hardcode_credentials(self):
        script = self.runner._build_login_script(
            login_url="https://x.com/login",
            success_url="https://x.com/dash",
            username_env_var="MY_USER",
            password_env_var="MY_PASS",
        )
        assert "admin" not in script
        assert "password123" not in script

    def test_script_uses_orangehrm_selectors(self):
        script = self.runner._build_login_script(
            login_url=ORANGEHRM_DEFAULT_LOGIN_URL,
            success_url=ORANGEHRM_DEFAULT_SUCCESS_URL,
            username_env_var="ORANGEHRM_USERNAME",
            password_env_var="ORANGEHRM_PASSWORD",
        )
        assert 'input[name="username"]' in script
        assert 'input[name="password"]' in script
        assert 'button[type="submit"]' in script

    def test_script_exits_nonzero_on_missing_env(self):
        script = self.runner._build_login_script(
            login_url="https://x.com",
            success_url="https://x.com/d",
            username_env_var="U",
            password_env_var="P",
        )
        assert "process.exit(2)" in script

    def test_script_uses_headless_true(self):
        script = self.runner._build_login_script(
            login_url="https://x.com",
            success_url="https://x.com/d",
            username_env_var="U",
            password_env_var="P",
        )
        assert "headless: true" in script


# ===========================================================================
# 14. CLI — blocked flags guard
# ===========================================================================
class TestCliBlockedFlags:
    def _run_cli(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(TOOL_PATH)] + args,
            capture_output=True,
            text=True,
        )

    def test_username_flag_blocked(self):
        result = self._run_cli(["--username", "admin", "--project-id", "p"])
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_password_flag_blocked(self):
        result = self._run_cli(["--password", "secret", "--project-id", "p"])
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_secret_flag_blocked(self):
        result = self._run_cli(["--secret", "xyz", "--project-id", "p"])
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_token_flag_blocked(self):
        result = self._run_cli(["--token", "tok", "--project-id", "p"])
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_cookie_flag_blocked(self):
        result = self._run_cli(["--cookie", "c", "--project-id", "p"])
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_access_token_flag_blocked(self):
        result = self._run_cli(["--access-token", "t", "--project-id", "p"])
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_bearer_flag_blocked(self):
        result = self._run_cli(["--bearer", "b", "--project-id", "p"])
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_client_secret_flag_blocked(self):
        result = self._run_cli(["--client-secret", "s", "--project-id", "p"])
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_plan_only_exits_zero(self):
        result = self._run_cli(["--project-id", "test-p", "--plan-only"])
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "project_id" in data

    def test_no_project_id_exits_nonzero(self):
        result = self._run_cli([])
        assert result.returncode != 0

    def test_plan_json_safety_block_present(self):
        result = self._run_cli(["--project-id", "test-p", "--plan-only"])
        data = json.loads(result.stdout)
        assert data["safety"]["raw_secrets_allowed"] is False
        assert data["safety"]["human_review_required"] is True


# ===========================================================================
# 15. Module-level constants
# ===========================================================================
class TestModuleLevelConstants:
    def test_blocked_url_prefixes_tuple(self):
        assert isinstance(_ALLOWED_LOGIN_URL_PREFIXES, tuple)
        assert "https://" in _ALLOWED_LOGIN_URL_PREFIXES

    def test_always_blocked_substrings_tuple(self):
        assert isinstance(_ALWAYS_BLOCKED_SUBSTRINGS, tuple)
        assert "captcha" in _ALWAYS_BLOCKED_SUBSTRINGS
        assert "recaptcha" in _ALWAYS_BLOCKED_SUBSTRINGS

    def test_orangehrm_default_urls_are_https(self):
        assert ORANGEHRM_DEFAULT_LOGIN_URL.startswith("https://")
        assert ORANGEHRM_DEFAULT_SUCCESS_URL.startswith("https://")
