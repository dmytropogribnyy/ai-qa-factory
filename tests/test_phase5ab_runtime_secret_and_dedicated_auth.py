"""Tests for Phase 5AB: Runtime Secret Routing and Dedicated Test-Account Auth Execution."""
from __future__ import annotations

import ast
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.schemas.runtime_secret_routing import (
    DedicatedAuthExecutionCommand,
    DedicatedAuthExecutionReport,
    DedicatedAuthSessionArtifact,
    RuntimeSecretReference,
    TestAccountIntakeRequest,
    TestAccountValidationResult,
)
from core.dedicated_auth_runner import DedicatedAuthRunner


# ===========================================================================
# Helpers
# ===========================================================================

def _runner(tmp_path: Path) -> DedicatedAuthRunner:
    return DedicatedAuthRunner(outputs_root=tmp_path)


def _make_scaffold(tmp_path: Path, project_id: str) -> Path:
    root = tmp_path / project_id / "03_framework" / "playwright"
    (root / "node_modules").mkdir(parents=True)
    (root / "tests" / "auth").mkdir(parents=True)
    (root / "tests" / "auth" / "login.spec.ts").write_text("// auth test")
    return root


# ===========================================================================
# 1. Schema: RuntimeSecretReference invariants
# ===========================================================================

class TestRuntimeSecretReference:
    def test_unsafe_flags_forced_false(self):
        ref = RuntimeSecretReference(
            id="r1", label="pw",
            raw_value_present=True,
            value_materialized=True,
            safe_to_persist=True,
            safe_to_log=True,
            safe_for_client_visibility=True,
        )
        assert ref.raw_value_present is False
        assert ref.value_materialized is False
        assert ref.safe_to_persist is False
        assert ref.safe_to_log is False
        assert ref.safe_for_client_visibility is False
        assert ref.requires_redaction is True

    def test_from_dict_forces_unsafe_false(self):
        ref = RuntimeSecretReference.from_dict({
            "id": "r1", "label": "pw",
            "raw_value_present": True,
            "value_materialized": True,
            "safe_to_persist": True,
            "safe_to_log": True,
            "safe_for_client_visibility": True,
        })
        assert ref.raw_value_present is False
        assert ref.safe_to_persist is False
        assert ref.safe_to_log is False

    def test_roundtrip(self):
        ref = RuntimeSecretReference(
            id="r1", label="username ref",
            env_var_name="QA_TEST_USERNAME",
            secret_type="username",
            source_route="runtime_env_reference",
        )
        d = ref.to_dict()
        ref2 = RuntimeSecretReference.from_dict(d)
        assert ref2.env_var_name == "QA_TEST_USERNAME"
        assert ref2.raw_value_present is False


# ===========================================================================
# 2. Schema: TestAccountIntakeRequest
# ===========================================================================

class TestTestAccountIntakeRequest:
    def test_roundtrip(self):
        req = TestAccountIntakeRequest(
            project_id="p1",
            scenario_lane="dedicated_test_account_auth_future",
            target_category="staging",
            username_env_var="QA_TEST_USERNAME",
            password_env_var="QA_TEST_PASSWORD",
            dedicated_test_account_confirmed=True,
            staging_environment_confirmed=True,
        )
        d = req.to_dict()
        req2 = TestAccountIntakeRequest.from_dict(d)
        assert req2.username_env_var == "QA_TEST_USERNAME"
        assert req2.dedicated_test_account_confirmed is True


# ===========================================================================
# 3. Schema: TestAccountValidationResult invariants
# ===========================================================================

class TestTestAccountValidationResult:
    def test_approved_for_execution_now_always_false(self):
        r = TestAccountValidationResult(
            project_id="p1", approved_for_execution_now=True
        )
        assert r.approved_for_execution_now is False

    def test_from_dict_forces_approved_false(self):
        r = TestAccountValidationResult.from_dict({
            "project_id": "p1",
            "approved_for_execution_now": True,
            "status": "valid",
        })
        assert r.approved_for_execution_now is False

    def test_nested_reconstruction(self):
        r = TestAccountValidationResult.from_dict({
            "project_id": "p1",
            "status": "valid",
            "intake_request": {
                "project_id": "p1",
                "scenario_lane": "dedicated_test_account_auth_future",
            },
            "accepted_secret_references": [
                {"id": "r1", "label": "username", "safe_to_log": True}
            ],
            "rejected_secret_references": [],
        })
        assert isinstance(r.intake_request, TestAccountIntakeRequest)
        assert r.accepted_secret_references[0].safe_to_log is False
        assert r.approved_for_execution_now is False


# ===========================================================================
# 4. Schema: DedicatedAuthSessionArtifact invariants
# ===========================================================================

class TestDedicatedAuthSessionArtifact:
    def test_safety_flags_always_forced(self):
        a = DedicatedAuthSessionArtifact(
            id="a1", artifact_type="storage_state", path="/some/path",
            internal_only=False,
            client_visible=True,
            requires_redaction=False,
            approved_for_commit=True,
            approved_for_client_view=True,
        )
        assert a.internal_only is True
        assert a.client_visible is False
        assert a.requires_redaction is True
        assert a.approved_for_commit is False
        assert a.approved_for_client_view is False

    def test_from_dict_forces_safety(self):
        a = DedicatedAuthSessionArtifact.from_dict({
            "id": "a1", "artifact_type": "storage_state", "path": "/p",
            "internal_only": False,
            "client_visible": True,
            "approved_for_commit": True,
            "approved_for_client_view": True,
        })
        assert a.internal_only is True
        assert a.approved_for_commit is False


# ===========================================================================
# 5. Schema: DedicatedAuthExecutionReport invariants
# ===========================================================================

class TestDedicatedAuthExecutionReport:
    def test_credential_flags_always_false(self):
        r = DedicatedAuthExecutionReport(
            project_id="p1",
            raw_credentials_logged=True,
            raw_credentials_serialized=True,
            personal_account_used=True,
            production_account_used=True,
            safe_to_deliver=True,
            approved_for_client_delivery=True,
        )
        assert r.raw_credentials_logged is False
        assert r.raw_credentials_serialized is False
        assert r.personal_account_used is False
        assert r.production_account_used is False
        assert r.safe_to_deliver is False
        assert r.approved_for_client_delivery is False

    def test_from_dict_forces_safety(self):
        r = DedicatedAuthExecutionReport.from_dict({
            "project_id": "p1",
            "raw_credentials_logged": True,
            "raw_credentials_serialized": True,
            "personal_account_used": True,
            "production_account_used": True,
            "safe_to_deliver": True,
            "approved_for_client_delivery": True,
            "commands": [{"id": "c1", "command": "npx playwright test", "cwd": "/",
                          "status": "passed", "executed": True}],
            "session_artifacts": [{"id": "a1", "artifact_type": "storage_state",
                                   "path": "/p", "approved_for_commit": True}],
        })
        assert r.raw_credentials_logged is False
        assert r.personal_account_used is False
        assert r.safe_to_deliver is False
        assert r.approved_for_client_delivery is False
        # Nested artifact safety also forced
        assert r.session_artifacts[0].approved_for_commit is False

    def test_nested_reconstruction(self):
        r = DedicatedAuthExecutionReport.from_dict({
            "project_id": "p1",
            "commands": [{"id": "c1", "command": "npx playwright test tests/auth --reporter=list",
                          "cwd": "/sc", "status": "passed", "executed": True}],
            "session_artifacts": [],
        })
        assert isinstance(r.commands[0], DedicatedAuthExecutionCommand)
        assert r.commands[0].command == "npx playwright test tests/auth --reporter=list"


# ===========================================================================
# 6. Schema __init__.py exports
# ===========================================================================

class TestSchemaExports:
    def test_all_classes_exported(self):
        from core.schemas import (
            RuntimeSecretReference,
            DedicatedAuthExecutionReport,
        )
        assert RuntimeSecretReference is not None
        assert DedicatedAuthExecutionReport is not None


# ===========================================================================
# 7. DedicatedAuthRunner: gate 1 — no approval
# ===========================================================================

class TestRunnerNoApproval:
    def test_blocked_without_approval(self, tmp_path):
        r = _runner(tmp_path).run_dedicated_auth(
            project_id="p1",
            approve_dedicated_auth_execution=False,
        )
        assert r.execution_status == "blocked"
        assert r.approved is False
        assert any("--approve-dedicated-auth-execution" in b for b in r.blockers)

    def test_no_env_lookup_without_approval(self, tmp_path):
        with patch.dict(os.environ, {"QA_TEST_PASSWORD": "secret"}, clear=False):
            r = _runner(tmp_path).run_dedicated_auth(
                project_id="p1",
                approve_dedicated_auth_execution=False,
                username_env_var="QA_TEST_USERNAME",
                password_env_var="QA_TEST_PASSWORD",
            )
        assert r.execution_status == "blocked"
        assert r.credentials_used is False


# ===========================================================================
# 8. DedicatedAuthRunner: gate 2 — personal/production account
# ===========================================================================

class TestRunnerAccountGates:
    def test_personal_account_blocked(self, tmp_path):
        r = _runner(tmp_path).run_dedicated_auth(
            project_id="p1",
            approve_dedicated_auth_execution=True,
            personal_account_confirmed=True,
        )
        assert r.execution_status == "blocked"
        assert any("Personal" in b for b in r.blockers)

    def test_production_account_blocked(self, tmp_path):
        r = _runner(tmp_path).run_dedicated_auth(
            project_id="p1",
            approve_dedicated_auth_execution=True,
            production_account_confirmed=True,
        )
        assert r.execution_status == "blocked"
        assert any("Production" in b for b in r.blockers)


# ===========================================================================
# 9. DedicatedAuthRunner: gate 3 — scenario lane
# ===========================================================================

class TestRunnerLaneGate:
    def test_strictly_blocked_lane_rejected(self, tmp_path):
        r = _runner(tmp_path).run_dedicated_auth(
            project_id="p1",
            approve_dedicated_auth_execution=True,
            scenario_lane="strictly_blocked",
        )
        assert r.execution_status == "blocked"
        assert any("strictly_blocked" in b or "Credentials cannot" in b for b in r.blockers)

    def test_demo_auth_smoke_lane_rejected(self, tmp_path):
        r = _runner(tmp_path).run_dedicated_auth(
            project_id="p1",
            approve_dedicated_auth_execution=True,
            scenario_lane="demo_auth_smoke",
        )
        assert r.execution_status == "blocked"

    def test_no_auth_lane_rejected(self, tmp_path):
        r = _runner(tmp_path).run_dedicated_auth(
            project_id="p1",
            approve_dedicated_auth_execution=True,
            scenario_lane="no_auth_demo_smoke",
        )
        assert r.execution_status == "blocked"

    def test_valid_dedicated_lane_passes_gate(self, tmp_path):
        # Will be blocked at later gate (target_category) but not at lane gate
        r = _runner(tmp_path).run_dedicated_auth(
            project_id="p1",
            approve_dedicated_auth_execution=True,
            scenario_lane="dedicated_test_account_auth_future",
            target_category="INVALID_CATEGORY",
        )
        assert r.execution_status == "blocked"
        assert not any("lane" in b.lower() for b in r.blockers)


# ===========================================================================
# 10. DedicatedAuthRunner: gate 4 — target category
# ===========================================================================

class TestRunnerTargetCategoryGate:
    def test_production_category_blocked(self, tmp_path):
        r = _runner(tmp_path).run_dedicated_auth(
            project_id="p1",
            approve_dedicated_auth_execution=True,
            scenario_lane="dedicated_test_account_auth_future",
            target_category="production",
        )
        assert r.execution_status == "blocked"
        assert any("target_category" in b or "Target category" in b for b in r.blockers)

    def test_orangehrm_category_accepted(self, tmp_path):
        # Blocked at later gate (URL or env vars) but not at category gate
        r = _runner(tmp_path).run_dedicated_auth(
            project_id="p1",
            approve_dedicated_auth_execution=True,
            scenario_lane="dedicated_test_account_auth_future",
            target_category="orangehrm_demo_auth",
            target_url="https://opensource-demo.orangehrmlive.com",
            username_env_var="QA_TEST_USERNAME",
            password_env_var="QA_TEST_PASSWORD",
            dedicated_test_account_confirmed=True,
            staging_environment_confirmed=True,
        )
        # Blocked at missing env vars gate, not at category gate
        assert r.execution_status == "blocked"
        assert not any("Target category" in b for b in r.blockers)


# ===========================================================================
# 11. DedicatedAuthRunner: gate 5 — blocked URLs
# ===========================================================================

class TestRunnerBlockedUrlGate:
    @pytest.mark.parametrize("url", [
        "https://accounts.google.com",
        "https://accounts.google.com/o/oauth2/auth",
        "https://www.amazon.com",
        "https://www.alza.sk",
        "https://www.linkedin.com",
        "https://www.upwork.com",
        "https://pay.amazon.com",
    ])
    def test_blocked_urls(self, tmp_path, url):
        r = _runner(tmp_path).run_dedicated_auth(
            project_id="p1",
            approve_dedicated_auth_execution=True,
            scenario_lane="dedicated_test_account_auth_future",
            target_category="staging",
            target_url=url,
        )
        assert r.execution_status == "blocked"
        assert any("blocked" in b.lower() or "strictly" in b.lower() for b in r.blockers)


# ===========================================================================
# 12. DedicatedAuthRunner: gate 7 — env var name format
# ===========================================================================

class TestRunnerEnvVarNameGate:
    @pytest.mark.parametrize("bad_name", [
        "danrobinson.artist@gmail.com",  # email — looks like raw value
        "my password",                   # spaces
        "secret_value",                  # lowercase
        "QA TEST USERNAME",              # spaces
        "a" * 81,                        # too long
    ])
    def test_bad_env_var_name_blocked(self, tmp_path, bad_name):
        r = _runner(tmp_path).run_dedicated_auth(
            project_id="p1",
            approve_dedicated_auth_execution=True,
            scenario_lane="dedicated_test_account_auth_future",
            target_category="staging",
            target_url="https://staging.example.com",
            username_env_var=bad_name,
            dedicated_test_account_confirmed=True,
            staging_environment_confirmed=True,
        )
        assert r.execution_status == "blocked"

    @pytest.mark.parametrize("good_name", [
        "QA_TEST_USERNAME",
        "QA_TEST_PASSWORD",
        "TEST_USERNAME",
        "MY_APP_TOKEN",
    ])
    def test_good_env_var_name_passes_format(self, tmp_path, good_name):
        runner = _runner(tmp_path)
        valid, _ = runner._validate_env_var_name(good_name)
        assert valid is True


# ===========================================================================
# 13. DedicatedAuthRunner: gate 8 — missing env vars
# ===========================================================================

class TestRunnerMissingEnvVars:
    def test_missing_env_vars_blocked_before_subprocess(self, tmp_path):
        # Ensure env vars are NOT set
        env_without = {k: v for k, v in os.environ.items()
                       if k not in ("QA_TEST_USERNAME_MISSING", "QA_TEST_PASSWORD_MISSING")}
        with patch.dict(os.environ, env_without, clear=True):
            r = _runner(tmp_path).run_dedicated_auth(
                project_id="p1",
                approve_dedicated_auth_execution=True,
                scenario_lane="dedicated_test_account_auth_future",
                target_category="staging",
                target_url="https://staging.example.com",
                username_env_var="QA_TEST_USERNAME_MISSING",
                password_env_var="QA_TEST_PASSWORD_MISSING",
                dedicated_test_account_confirmed=True,
                staging_environment_confirmed=True,
            )
        assert r.execution_status == "blocked"
        assert any("env var" in b.lower() or "not found" in b.lower() for b in r.blockers)
        assert r.credentials_used is False


# ===========================================================================
# 14. DedicatedAuthRunner: gate 9 — scaffold checks
# ===========================================================================

class TestRunnerScaffoldGate:
    def test_missing_scaffold_blocked(self, tmp_path):
        with patch.dict(os.environ,
                        {"QA_TEST_U": "user", "QA_TEST_P": "pass"}, clear=False):
            r = _runner(tmp_path).run_dedicated_auth(
                project_id="p1",
                approve_dedicated_auth_execution=True,
                scenario_lane="dedicated_test_account_auth_future",
                target_category="staging",
                target_url="https://staging.example.com",
                username_env_var="QA_TEST_U",
                password_env_var="QA_TEST_P",
                dedicated_test_account_confirmed=True,
                staging_environment_confirmed=True,
                scaffold_root=tmp_path / "nonexistent",
            )
        assert r.execution_status == "blocked"
        assert any("scaffold" in b.lower() or "Scaffold" in b for b in r.blockers)

    def test_missing_node_modules_blocked(self, tmp_path):
        scaffold = tmp_path / "scaffold"
        (scaffold / "tests" / "auth").mkdir(parents=True)
        # No node_modules
        with patch.dict(os.environ,
                        {"QA_TEST_U": "user", "QA_TEST_P": "pass"}, clear=False):
            r = _runner(tmp_path).run_dedicated_auth(
                project_id="p1",
                approve_dedicated_auth_execution=True,
                scenario_lane="dedicated_test_account_auth_future",
                target_category="staging",
                target_url="https://staging.example.com",
                username_env_var="QA_TEST_U",
                password_env_var="QA_TEST_P",
                dedicated_test_account_confirmed=True,
                staging_environment_confirmed=True,
                scaffold_root=scaffold,
            )
        assert r.execution_status == "blocked"
        assert any("node_modules" in b for b in r.blockers)

    def test_missing_tests_auth_blocked(self, tmp_path):
        scaffold = tmp_path / "scaffold"
        (scaffold / "node_modules").mkdir(parents=True)
        # No tests/auth
        with patch.dict(os.environ,
                        {"QA_TEST_U": "user", "QA_TEST_P": "pass"}, clear=False):
            r = _runner(tmp_path).run_dedicated_auth(
                project_id="p1",
                approve_dedicated_auth_execution=True,
                scenario_lane="dedicated_test_account_auth_future",
                target_category="staging",
                target_url="https://staging.example.com",
                username_env_var="QA_TEST_U",
                password_env_var="QA_TEST_P",
                dedicated_test_account_confirmed=True,
                staging_environment_confirmed=True,
                scaffold_root=scaffold,
            )
        assert r.execution_status == "blocked"
        assert any("tests/auth" in b for b in r.blockers)


# ===========================================================================
# 15. DedicatedAuthRunner: approved path (mocked subprocess)
# ===========================================================================

class TestRunnerApprovedPath:
    def _run_approved(self, tmp_path, exit_code=0):
        scaffold = _make_scaffold(tmp_path, "p1")
        mock_result = MagicMock()
        mock_result.returncode = exit_code
        mock_result.stdout = "Running auth tests...\nPassed 1"
        mock_result.stderr = ""

        with patch("core.dedicated_auth_runner.subprocess.run",
                   return_value=mock_result) as mock_sub, \
             patch.dict(os.environ,
                        {"QA_TEST_U": "user_value", "QA_TEST_P": "pass_value"},
                        clear=False):
            r = _runner(tmp_path).run_dedicated_auth(
                project_id="p1",
                approve_dedicated_auth_execution=True,
                scenario_lane="dedicated_test_account_auth_future",
                target_category="staging",
                target_url="https://staging.example.com",
                username_env_var="QA_TEST_U",
                password_env_var="QA_TEST_P",
                dedicated_test_account_confirmed=True,
                staging_environment_confirmed=True,
                scaffold_root=scaffold,
            )
        return r, mock_sub

    def test_subprocess_called_on_approved_path(self, tmp_path):
        r, mock_sub = self._run_approved(tmp_path)
        assert mock_sub.called

    def test_secrets_not_in_command_args(self, tmp_path):
        _, mock_sub = self._run_approved(tmp_path)
        call_args = mock_sub.call_args
        cmd = call_args[0][0]  # first positional arg is the command list
        cmd_str = " ".join(str(c) for c in cmd)
        assert "user_value" not in cmd_str
        assert "pass_value" not in cmd_str

    def test_approved_report_flags(self, tmp_path):
        r, _ = self._run_approved(tmp_path)
        assert r.approved is True
        assert r.auth_execution_performed is True
        assert r.raw_credentials_logged is False
        assert r.raw_credentials_serialized is False
        assert r.personal_account_used is False
        assert r.production_account_used is False
        assert r.safe_to_deliver is False
        assert r.approved_for_client_delivery is False

    def test_stdout_secrets_masked(self, tmp_path):
        scaffold = _make_scaffold(tmp_path, "p1")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Login with user_value and pass_value succeeded"
        mock_result.stderr = ""

        with patch("core.dedicated_auth_runner.subprocess.run",
                   return_value=mock_result), \
             patch.dict(os.environ,
                        {"QA_TEST_U": "user_value", "QA_TEST_P": "pass_value"},
                        clear=False):
            r = _runner(tmp_path).run_dedicated_auth(
                project_id="p1",
                approve_dedicated_auth_execution=True,
                scenario_lane="dedicated_test_account_auth_future",
                target_category="staging",
                target_url="https://staging.example.com",
                username_env_var="QA_TEST_U",
                password_env_var="QA_TEST_P",
                dedicated_test_account_confirmed=True,
                staging_environment_confirmed=True,
                scaffold_root=scaffold,
            )
        assert "user_value" not in r.commands[0].stdout_excerpt
        assert "pass_value" not in r.commands[0].stdout_excerpt
        assert "[REDACTED]" in r.commands[0].stdout_excerpt

    def test_storage_state_artifact_safety(self, tmp_path):
        scaffold = _make_scaffold(tmp_path, "p1")
        storage_state = (tmp_path / "p1" / "12_dedicated_auth" / ".auth" / "storageState.json")
        storage_state.parent.mkdir(parents=True, exist_ok=True)
        storage_state.write_text('{"cookies":[]}')

        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("core.dedicated_auth_runner.subprocess.run",
                   return_value=mock_result), \
             patch.dict(os.environ,
                        {"QA_TEST_U": "u", "QA_TEST_P": "p"}, clear=False):
            r = _runner(tmp_path).run_dedicated_auth(
                project_id="p1",
                approve_dedicated_auth_execution=True,
                scenario_lane="dedicated_test_account_auth_future",
                target_category="staging",
                target_url="https://staging.example.com",
                username_env_var="QA_TEST_U",
                password_env_var="QA_TEST_P",
                dedicated_test_account_confirmed=True,
                staging_environment_confirmed=True,
                scaffold_root=scaffold,
            )
        assert r.storage_state_created is True
        for artifact in r.session_artifacts:
            if artifact.artifact_type == "storage_state":
                assert artifact.approved_for_commit is False
                assert artifact.client_visible is False
                assert artifact.internal_only is True

    def test_artifacts_written(self, tmp_path):
        r, _ = self._run_approved(tmp_path)
        out_dir = tmp_path / "p1" / "12_dedicated_auth"
        assert (out_dir / "DEDICATED_AUTH_EXECUTION_REPORT.json").exists()
        assert (out_dir / "DEDICATED_AUTH_EXECUTION_REPORT.md").exists()
        assert (out_dir / "DEDICATED_AUTH_COMMAND_LOG.md").exists()
        assert (out_dir / "DEDICATED_AUTH_REDACTION_CHECKLIST.md").exists()

    def test_report_json_no_raw_secrets(self, tmp_path):
        scaffold = _make_scaffold(tmp_path, "p1")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        mock_result.stderr = ""

        with patch("core.dedicated_auth_runner.subprocess.run",
                   return_value=mock_result), \
             patch.dict(os.environ,
                        {"QA_TEST_U": "supersecretuser", "QA_TEST_P": "supersecretpass"},
                        clear=False):
            _runner(tmp_path).run_dedicated_auth(
                project_id="p1",
                approve_dedicated_auth_execution=True,
                scenario_lane="dedicated_test_account_auth_future",
                target_category="staging",
                target_url="https://staging.example.com",
                username_env_var="QA_TEST_U",
                password_env_var="QA_TEST_P",
                dedicated_test_account_confirmed=True,
                staging_environment_confirmed=True,
                scaffold_root=scaffold,
            )

        report_json = (tmp_path / "p1" / "12_dedicated_auth" /
                       "DEDICATED_AUTH_EXECUTION_REPORT.json").read_text()
        assert "supersecretuser" not in report_json
        assert "supersecretpass" not in report_json


# ===========================================================================
# 16. DedicatedAuthRunner: blocked command patterns
# ===========================================================================

class TestRunnerBlockedCommands:
    def test_npm_install_blocked(self, tmp_path):
        from core.dedicated_auth_runner import _BLOCKED_COMMAND_PATTERNS
        assert any("npm install" in p for p in _BLOCKED_COMMAND_PATTERNS)

    def test_npx_playwright_install_blocked(self, tmp_path):
        from core.dedicated_auth_runner import _BLOCKED_COMMAND_PATTERNS
        assert any("npx playwright install" in p for p in _BLOCKED_COMMAND_PATTERNS)

    def test_unrestricted_playwright_blocked(self, tmp_path):
        from core.dedicated_auth_runner import _ALLOWED_COMMAND_BASES
        # Unrestricted "npx playwright test" (no path restriction) must NOT be in allowlist
        assert not any(b == "npx playwright test" for b in _ALLOWED_COMMAND_BASES)


# ===========================================================================
# 17. DedicatedAuthRunner.validate_intake
# ===========================================================================

class TestRunnerValidateIntake:
    def test_valid_intake(self, tmp_path):
        r = _runner(tmp_path).validate_intake(
            project_id="p1",
            scenario_lane="dedicated_test_account_auth_future",
            target_category="staging",
            target_url="https://staging.example.com",
            username_env_var="QA_TEST_USERNAME",
            password_env_var="QA_TEST_PASSWORD",
            dedicated_test_account_confirmed=True,
            staging_environment_confirmed=True,
        )
        assert r.status == "valid"
        assert not r.blockers
        assert r.approved_for_execution_now is False
        assert any(ref.env_var_name == "QA_TEST_USERNAME"
                   for ref in r.accepted_secret_references)

    def test_personal_account_blocked(self, tmp_path):
        r = _runner(tmp_path).validate_intake(
            project_id="p1",
            personal_account_confirmed=True,
            username_env_var="QA_TEST_USERNAME",
            dedicated_test_account_confirmed=True,
            staging_environment_confirmed=True,
        )
        assert r.status == "blocked"
        assert any("Personal" in b for b in r.blockers)

    def test_strictly_blocked_lane(self, tmp_path):
        r = _runner(tmp_path).validate_intake(
            project_id="p1",
            scenario_lane="strictly_blocked",
            target_category="production",
            username_env_var="QA_TEST_USERNAME",
            dedicated_test_account_confirmed=True,
            staging_environment_confirmed=True,
        )
        assert r.status == "blocked"

    def test_no_env_values_read(self, tmp_path):
        # Even with valid config, validate_intake MUST NOT read env var values
        with patch.dict(os.environ, {"QA_TEST_USERNAME": "shouldnotberead"}, clear=False):
            r = _runner(tmp_path).validate_intake(
                project_id="p1",
                scenario_lane="dedicated_test_account_auth_future",
                target_category="staging",
                username_env_var="QA_TEST_USERNAME",
                dedicated_test_account_confirmed=True,
                staging_environment_confirmed=True,
            )
        # Result must not contain the env var value anywhere
        serialized = json.dumps(r.to_dict())
        assert "shouldnotberead" not in serialized
        assert r.approved_for_execution_now is False


# ===========================================================================
# 18. CLI: plan_runtime_secrets
# ===========================================================================

class TestPlanRuntimeSecretsCLI:
    def test_no_write_works(self, tmp_path, capsys):
        from tools.plan_runtime_secrets import main
        rc = main(["--project-id", "demo-5ab", "--no-write",
                   "--outputs-root", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "Safety boundary" in out

    def test_json_output_valid(self, tmp_path, capsys):
        from tools.plan_runtime_secrets import main
        rc = main(["--project-id", "demo-5ab", "--json", "--no-write",
                   "--outputs-root", str(tmp_path)])
        assert rc == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "project_id" in data

    def test_blocked_personal_account(self, tmp_path, capsys):
        from tools.plan_runtime_secrets import main
        rc = main([
            "--project-id", "demo-5ab", "--no-write",
            "--personal-account-confirmed",
            "--username-env-var", "QA_TEST_USERNAME",
            "--outputs-root", str(tmp_path),
        ])
        assert rc == 0  # CLI returns 0 (shows result); validation itself shows BLOCKED
        out = capsys.readouterr().out
        assert "BLOCKED" in out

    def test_write_creates_artifacts(self, tmp_path):
        from tools.plan_runtime_secrets import main
        main([
            "--project-id", "demo-5ab",
            "--scenario-lane", "dedicated_test_account_auth_future",
            "--target-category", "staging",
            "--username-env-var", "QA_TEST_USERNAME",
            "--password-env-var", "QA_TEST_PASSWORD",
            "--dedicated-test-account-confirmed",
            "--staging-environment-confirmed",
            "--outputs-root", str(tmp_path),
        ])
        out_dir = tmp_path / "demo-5ab" / "11_runtime_secrets"
        assert (out_dir / "TEST_ACCOUNT_INTAKE_VALIDATION.json").exists()
        assert (out_dir / "RUNTIME_SECRET_ROUTING_PLAN.md").exists()


# ===========================================================================
# 19. CLI: run_dedicated_auth
# ===========================================================================

class TestRunDedicatedAuthCLI:
    def test_no_approval_blocked(self, tmp_path, capsys):
        from tools.run_dedicated_auth import main
        rc = main(["--project-id", "demo-5ab",
                   "--outputs-root", str(tmp_path)])
        assert rc == 1  # blocked
        out = capsys.readouterr().out
        assert "BLOCKED" in out

    def test_blocked_google_target(self, tmp_path, capsys):
        from tools.run_dedicated_auth import main
        rc = main([
            "--project-id", "demo-5ab",
            "--approve-dedicated-auth-execution",
            "--scenario-lane", "dedicated_test_account_auth_future",
            "--target-category", "staging",
            "--target-url", "https://accounts.google.com",
            "--username-env-var", "QA_TEST_USERNAME",
            "--password-env-var", "QA_TEST_PASSWORD",
            "--dedicated-test-account-confirmed",
            "--staging-environment-confirmed",
            "--outputs-root", str(tmp_path),
        ])
        assert rc == 1
        out = capsys.readouterr().out
        assert "BLOCKED" in out

    def test_missing_env_vars_blocked(self, tmp_path, capsys):
        from tools.run_dedicated_auth import main
        env_clean = {k: v for k, v in os.environ.items()
                     if k not in ("QA_MISSING_USER", "QA_MISSING_PASS")}
        with patch.dict(os.environ, env_clean, clear=True):
            rc = main([
                "--project-id", "demo-5ab",
                "--approve-dedicated-auth-execution",
                "--scenario-lane", "dedicated_test_account_auth_future",
                "--target-category", "staging",
                "--target-url", "https://staging.example.com",
                "--username-env-var", "QA_MISSING_USER",
                "--password-env-var", "QA_MISSING_PASS",
                "--dedicated-test-account-confirmed",
                "--staging-environment-confirmed",
                "--outputs-root", str(tmp_path),
            ])
        assert rc == 1
        out = capsys.readouterr().out
        assert "BLOCKED" in out

    def test_json_output_no_execution(self, tmp_path, capsys):
        from tools.run_dedicated_auth import main
        rc = main(["--project-id", "demo-5ab", "--json",
                   "--outputs-root", str(tmp_path)])
        assert rc == 1
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["execution_status"] == "blocked"
        assert data["raw_credentials_logged"] is False

    def test_approved_path_mocked(self, tmp_path, capsys):
        from tools.run_dedicated_auth import main
        scaffold = _make_scaffold(tmp_path, "demo-5ab")
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "All tests passed"
        mock_result.stderr = ""

        with patch("core.dedicated_auth_runner.subprocess.run",
                   return_value=mock_result), \
             patch.dict(os.environ,
                        {"QA_TEST_U": "testuser", "QA_TEST_P": "testpass"},
                        clear=False):
            rc = main([
                "--project-id", "demo-5ab",
                "--approve-dedicated-auth-execution",
                "--scenario-lane", "dedicated_test_account_auth_future",
                "--target-category", "staging",
                "--target-url", "https://staging.example.com",
                "--username-env-var", "QA_TEST_U",
                "--password-env-var", "QA_TEST_P",
                "--dedicated-test-account-confirmed",
                "--staging-environment-confirmed",
                f"--scaffold-root={scaffold}",
                "--outputs-root", str(tmp_path),
            ])
        assert rc == 0
        out = capsys.readouterr().out
        assert "testuser" not in out
        assert "testpass" not in out


# ===========================================================================
# 20. Static safety inspection
# ===========================================================================

class TestPhase5ABStaticSafety:
    def _get_imports(self, path: str) -> set:
        source = Path(path).read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.add(alias.name.split(".")[0])
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.add(node.module.split(".")[0])
        return imports

    def test_no_requests_in_runner(self):
        imports = self._get_imports("core/dedicated_auth_runner.py")
        assert "requests" not in imports
        assert "httpx" not in imports
        assert "aiohttp" not in imports
        assert "urllib" not in imports

    def test_no_dotenv_in_runner(self):
        imports = self._get_imports("core/dedicated_auth_runner.py")
        assert "dotenv" not in imports

    def test_subprocess_only_in_runner_not_cli(self):
        plan_imports = self._get_imports("tools/plan_runtime_secrets.py")
        assert "subprocess" not in plan_imports

    def test_no_requests_in_plan_cli(self):
        imports = self._get_imports("tools/plan_runtime_secrets.py")
        assert "requests" not in imports

    def test_no_dotenv_in_run_cli(self):
        imports = self._get_imports("tools/run_dedicated_auth.py")
        assert "dotenv" not in imports

    def test_no_raw_secret_flags_in_cli(self):
        # Check that raw-value secret flags are not registered as argparse arguments.
        # The file may contain these strings in blocker detection logic — that's expected.
        run_source = Path("tools/run_dedicated_auth.py").read_text()
        assert 'add_argument("--password"' not in run_source
        assert 'add_argument("--username"' not in run_source
        assert 'add_argument("--token"' not in run_source
        assert 'add_argument("--secret"' not in run_source
        assert 'add_argument("--api-key"' not in run_source
        # Env-var-name flags are allowed:
        assert "--username-env-var" in run_source
        assert "--password-env-var" in run_source

    def test_no_raw_secret_flags_in_plan_cli(self):
        plan_source = Path("tools/plan_runtime_secrets.py").read_text()
        assert '"--password"' not in plan_source
        assert '"--username"' not in plan_source
        assert '"--secret"' not in plan_source


# ===========================================================================
# 21. Docs governance
# ===========================================================================

class TestPhase5ABDocsGovernance:
    def _read(self, rel: str) -> str:
        return (Path("docs") / rel).read_text(encoding="utf-8")

    def test_commands_md_mentions_phase5ab(self):
        assert "5AB" in self._read("COMMANDS.md") or \
               "plan_runtime_secrets" in self._read("COMMANDS.md")

    def test_runbook_md_mentions_phase5ab(self):
        assert "5AB" in self._read("RUNBOOK.md") or \
               "dedicated_auth" in self._read("RUNBOOK.md")

    def test_safety_rules_mentions_phase5ab(self):
        src = self._read("SAFETY_RULES.md")
        assert "5AB" in src or "runtime_env_reference" in src

    def test_phase_contracts_mentions_phase5ab(self):
        src = self._read("PHASE_CONTRACTS.md")
        assert "5AB" in src or "dedicated_auth" in src.lower()

    def test_schema_foundation_mentions_phase5ab(self):
        src = self._read("SCHEMA_FOUNDATION.md")
        assert "5AB" in src or "RuntimeSecretReference" in src

    def test_docs_manifest_mentions_11_runtime_secrets(self):
        assert "11_runtime_secrets" in self._read("DOCS_MANIFEST.md")

    def test_artifact_contracts_mentions_12_dedicated_auth(self):
        assert "12_dedicated_auth" in self._read("ARTIFACT_CONTRACTS.md")

    def test_agent_contract_mentions_phase5ab(self):
        src = self._read("AGENT_CONTRACT.md")
        assert "5AB" in src or "runtime_env" in src
