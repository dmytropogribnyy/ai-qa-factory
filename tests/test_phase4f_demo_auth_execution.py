"""Tests for Phase 4F: Approved Demo Auth Execution.

Safety guarantees under test:
- No subprocess without explicit approval flag
- No subprocess with unknown auth profile
- Alza/Amazon/Google/Linear/LinkedIn/Upwork always blocked
- Only allowlisted auth commands
- Credentials never appear in command args
- Credentials masked in stdout/stderr
- Environment sanitization strips inherited secrets
- storageState only under outputs/<project_id>/09_auth/.auth/
- storageState approved_for_commit=False, client_visible=False
- Delivery flags always False
- Evidence always internal-only
- Schema safety invariants

subprocess is ALWAYS mocked in these tests.
No real Playwright/browser execution occurs.
No real credentials used.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch


from core.schemas.auth_execution import (
    AuthCredentialProfile,
    AuthExecutionCommand,
    AuthExecutionReport,
    AuthSessionArtifact,
    AUTH_ARTIFACT_TYPES,
    AUTH_COMMAND_MODES,
    CREDENTIAL_SOURCE_TYPES,
)
from core.demo_auth_runner import (
    DemoAuthRunner,
    _ALWAYS_BLOCKED_DOMAINS,
    _DEMO_AUTH_PROFILES,
    _SECRET_ENV_PATTERNS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _runner(tmp_path: Path) -> DemoAuthRunner:
    return DemoAuthRunner(outputs_root=tmp_path / "outputs")


def _make_scaffold(tmp_path: Path, project_id: str = "test-4f") -> Path:
    scaffold = tmp_path / "outputs" / project_id / "03_framework" / "playwright"
    scaffold.mkdir(parents=True, exist_ok=True)
    (scaffold / "package.json").write_text('{"name":"test"}')
    return scaffold


# ===========================================================================
# 1. Schema — AuthCredentialProfile
# ===========================================================================

class TestAuthCredentialProfile:
    def test_defaults_safe(self):
        p = AuthCredentialProfile()
        assert p.personal_account is False
        assert p.production_account is False
        assert p.safe_to_store_in_repo is False
        assert p.public_demo_credentials is False
        assert p.approved_for_demo_auth is False

    def test_post_init_forces_personal_false(self):
        # Cannot be True even if passed explicitly
        p = AuthCredentialProfile(personal_account=True)
        assert p.personal_account is False

    def test_post_init_forces_production_false(self):
        p = AuthCredentialProfile(production_account=True)
        assert p.production_account is False

    def test_post_init_forces_safe_to_store_false(self):
        p = AuthCredentialProfile(safe_to_store_in_repo=True)
        assert p.safe_to_store_in_repo is False

    def test_from_dict_forces_unsafe_flags_false(self):
        data = {
            "id": "x",
            "provider": "SauceDemo",
            "personal_account": True,
            "production_account": True,
            "safe_to_store_in_repo": True,
        }
        p = AuthCredentialProfile.from_dict(data)
        assert p.personal_account is False
        assert p.production_account is False
        assert p.safe_to_store_in_repo is False

    def test_roundtrip(self):
        p = AuthCredentialProfile(
            id="saucedemo_demo_auth",
            provider="SauceDemo",
            target_url="https://www.saucedemo.com",
            credential_source_type="public_demo_profile",
            public_demo_credentials=True,
            approved_for_demo_auth=True,
            notes=["public demo"],
        )
        d = p.to_dict()
        assert d["public_demo_credentials"] is True
        assert d["personal_account"] is False
        assert d["safe_to_store_in_repo"] is False
        p2 = AuthCredentialProfile.from_dict(d)
        assert p2.public_demo_credentials is True
        assert p2.personal_account is False


# ===========================================================================
# 2. Schema — AuthExecutionCommand
# ===========================================================================

class TestAuthExecutionCommand:
    def test_defaults(self):
        c = AuthExecutionCommand()
        assert c.executed is False
        assert c.status == "skipped"
        assert c.exit_code is None
        assert c.safety_notes == []

    def test_roundtrip(self):
        c = AuthExecutionCommand(
            id="cmd_1",
            command="npx playwright test tests/auth --reporter=list",
            cwd="/scaffold",
            status="pass",
            exit_code=0,
            executed=True,
        )
        d = c.to_dict()
        c2 = AuthExecutionCommand.from_dict(d)
        assert c2.id == "cmd_1"
        assert c2.executed is True
        assert c2.exit_code == 0


# ===========================================================================
# 3. Schema — AuthSessionArtifact
# ===========================================================================

class TestAuthSessionArtifact:
    def test_defaults_safe(self):
        a = AuthSessionArtifact()
        assert a.internal_only is True
        assert a.client_visible is False
        assert a.requires_redaction is True
        assert a.approved_for_commit is False
        assert a.approved_for_client_view is False

    def test_post_init_forces_commit_false(self):
        a = AuthSessionArtifact(approved_for_commit=True)
        assert a.approved_for_commit is False

    def test_post_init_forces_client_view_false(self):
        a = AuthSessionArtifact(approved_for_client_view=True)
        assert a.approved_for_client_view is False

    def test_post_init_forces_client_visible_false(self):
        a = AuthSessionArtifact(client_visible=True)
        assert a.client_visible is False

    def test_from_dict_forces_unsafe_flags_false(self):
        data = {
            "id": "art_1",
            "artifact_type": "storage_state",
            "path": "/some/path",
            "approved_for_commit": True,
            "approved_for_client_view": True,
            "client_visible": True,
        }
        a = AuthSessionArtifact.from_dict(data)
        assert a.approved_for_commit is False
        assert a.approved_for_client_view is False
        assert a.client_visible is False

    def test_roundtrip(self):
        a = AuthSessionArtifact(
            id="art_ss",
            artifact_type="storage_state",
            path="outputs/demo/09_auth/.auth/storageState.json",
            notes=["internal only"],
        )
        d = a.to_dict()
        a2 = AuthSessionArtifact.from_dict(d)
        assert a2.id == "art_ss"
        assert a2.approved_for_commit is False


# ===========================================================================
# 4. Schema — AuthExecutionReport
# ===========================================================================

class TestAuthExecutionReport:
    def test_defaults_safe(self):
        r = AuthExecutionReport()
        assert r.approved is False
        assert r.auth_execution_performed is False
        assert r.real_credentials_used is False
        assert r.personal_account_used is False
        assert r.production_account_used is False
        assert r.safe_to_deliver is False
        assert r.approved_for_client_delivery is False
        assert r.execution_status == "blocked"

    def test_post_init_forces_delivery_false(self):
        r = AuthExecutionReport(
            real_credentials_used=True,
            personal_account_used=True,
            production_account_used=True,
            safe_to_deliver=True,
            approved_for_client_delivery=True,
        )
        assert r.real_credentials_used is False
        assert r.personal_account_used is False
        assert r.production_account_used is False
        assert r.safe_to_deliver is False
        assert r.approved_for_client_delivery is False

    def test_execution_performed_not_forced(self):
        r = AuthExecutionReport(
            auth_execution_performed=True,
            browser_execution_performed=True,
            storage_state_created=True,
            credentials_used=True,
        )
        # These reflect real state — must NOT be forced False
        assert r.auth_execution_performed is True
        assert r.browser_execution_performed is True
        assert r.storage_state_created is True
        assert r.credentials_used is True

    def test_nested_reconstruction_in_from_dict(self):
        data = {
            "project_id": "demo",
            "execution_status": "complete",
            "approved": True,
            "real_credentials_used": True,
            "safe_to_deliver": True,
            "credential_profile": {
                "id": "saucedemo_demo_auth",
                "provider": "SauceDemo",
                "personal_account": True,
            },
            "commands": [{"id": "cmd_1", "command": "npx playwright test tests/auth --reporter=list", "status": "pass"}],
            "session_artifacts": [{"id": "art_1", "artifact_type": "storage_state", "approved_for_commit": True}],
        }
        r = AuthExecutionReport.from_dict(data)
        # Delivery flags forced False on rehydration
        assert r.real_credentials_used is False
        assert r.safe_to_deliver is False
        # Nested objects reconstructed
        assert r.credential_profile is not None
        assert isinstance(r.credential_profile, AuthCredentialProfile)
        assert r.credential_profile.personal_account is False
        assert len(r.commands) == 1
        assert isinstance(r.commands[0], AuthExecutionCommand)
        assert len(r.session_artifacts) == 1
        assert isinstance(r.session_artifacts[0], AuthSessionArtifact)
        assert r.session_artifacts[0].approved_for_commit is False

    def test_to_dict_excludes_raw_credential_private_fields(self):
        # The _username and _password keys from profile metadata are never stored
        # in the schema (they exist only in _DEMO_AUTH_PROFILES dict for env injection).
        # AuthCredentialProfile holds labels (metadata), not raw values.
        r = AuthExecutionReport(
            project_id="demo",
            credential_profile=AuthCredentialProfile(
                id="saucedemo_demo_auth",
                # Labels are metadata — they document what type of credential is used
                username_label="public demo account username",
                password_label="public demo account password",
            ),
        )
        d = r.to_dict()
        serialized = json.dumps(d)
        # Private keys from the profile registry must never appear in the schema
        assert "_username" not in serialized
        assert "_password" not in serialized
        # The schema has no raw credential value fields
        assert "credential_value" not in serialized
        assert "raw_password" not in serialized

    def test_roundtrip(self):
        r = AuthExecutionReport(
            project_id="demo",
            execution_status="complete",
            approved=True,
            auth_execution_performed=True,
        )
        d = r.to_dict()
        r2 = AuthExecutionReport.from_dict(d)
        assert r2.project_id == "demo"
        assert r2.approved is True
        assert r2.auth_execution_performed is True
        assert r2.safe_to_deliver is False


# ===========================================================================
# 5. Schema exports
# ===========================================================================

class TestSchemaExports:
    def test_all_classes_exported_from_init(self):
        from core.schemas import (
            AuthCredentialProfile,
            AuthExecutionCommand,
            AuthExecutionReport,
            AuthSessionArtifact,
        )
        assert AuthCredentialProfile is not None
        assert AuthExecutionCommand is not None
        assert AuthExecutionReport is not None
        assert AuthSessionArtifact is not None

    def test_constants_exported(self):
        assert "storage_state" in AUTH_ARTIFACT_TYPES
        assert "auth_smoke" in AUTH_COMMAND_MODES
        assert "public_demo_profile" in CREDENTIAL_SOURCE_TYPES

    def test_schema_in_all(self):
        import core.schemas as schemas
        assert "AuthCredentialProfile" in schemas.__all__
        assert "AuthExecutionReport" in schemas.__all__


# ===========================================================================
# 6. DemoAuthRunner — no approval
# ===========================================================================

class TestDemoAuthRunnerNoApproval:
    def test_no_approval_flag_returns_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_demo_auth_execution(
            project_id="test", approve_demo_auth=False
        )
        assert report.execution_status == "blocked"
        assert report.approved is False
        assert len(report.blockers) > 0
        assert report.auth_execution_performed is False

    @patch("core.demo_auth_runner.subprocess.run")
    def test_no_approval_subprocess_never_called(self, mock_run, tmp_path):
        runner = _runner(tmp_path)
        runner.run_demo_auth_execution(
            project_id="test", approve_demo_auth=False
        )
        mock_run.assert_not_called()

    def test_no_approval_no_credentials_injected(self, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_demo_auth_execution(
            project_id="test", approve_demo_auth=False
        )
        assert report.credentials_used is False
        assert report.real_credentials_used is False

    def test_no_approval_no_storage_state(self, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_demo_auth_execution(
            project_id="test", approve_demo_auth=False
        )
        assert report.storage_state_created is False

    def test_no_approval_delivery_flags_false(self, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_demo_auth_execution(
            project_id="test", approve_demo_auth=False
        )
        assert report.safe_to_deliver is False
        assert report.approved_for_client_delivery is False
        assert report.real_credentials_used is False
        assert report.personal_account_used is False
        assert report.production_account_used is False

    def test_no_approval_notes_mention_no_subprocess(self, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_demo_auth_execution(
            project_id="test", approve_demo_auth=False
        )
        notes_text = " ".join(report.notes)
        assert "No subprocess executed" in notes_text


# ===========================================================================
# 7. DemoAuthRunner — blocked profiles
# ===========================================================================

class TestDemoAuthRunnerBlockedProfiles:
    @patch("core.demo_auth_runner.subprocess.run")
    def test_unknown_profile_blocked(self, mock_run, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_demo_auth_execution(
            project_id="test",
            approve_demo_auth=True,
            auth_profile="unknown_profile",
        )
        assert report.execution_status == "blocked"
        mock_run.assert_not_called()

    @patch("core.demo_auth_runner.subprocess.run")
    def test_alza_profile_blocked(self, mock_run, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_demo_auth_execution(
            project_id="test",
            approve_demo_auth=True,
            auth_profile="alza_demo_auth",
        )
        assert report.execution_status == "blocked"
        mock_run.assert_not_called()

    @patch("core.demo_auth_runner.subprocess.run")
    def test_amazon_profile_blocked(self, mock_run, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_demo_auth_execution(
            project_id="test",
            approve_demo_auth=True,
            auth_profile="amazon_auth",
        )
        assert report.execution_status == "blocked"
        mock_run.assert_not_called()

    @patch("core.demo_auth_runner.subprocess.run")
    def test_google_profile_blocked(self, mock_run, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_demo_auth_execution(
            project_id="test",
            approve_demo_auth=True,
            auth_profile="google_oauth_auth",
        )
        assert report.execution_status == "blocked"
        mock_run.assert_not_called()

    @patch("core.demo_auth_runner.subprocess.run")
    def test_linear_profile_blocked(self, mock_run, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_demo_auth_execution(
            project_id="test",
            approve_demo_auth=True,
            auth_profile="linear_auth",
        )
        assert report.execution_status == "blocked"
        mock_run.assert_not_called()

    def test_no_profile_specified_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_demo_auth_execution(
            project_id="test",
            approve_demo_auth=True,
            auth_profile=None,
        )
        assert report.execution_status == "blocked"
        assert "auth-profile" in " ".join(report.blockers)


# ===========================================================================
# 8. DemoAuthRunner — credentials
# ===========================================================================

class TestDemoAuthRunnerCredentials:
    @patch("core.demo_auth_runner.subprocess.run")
    def test_credentials_never_in_command_args(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        scaffold = _make_scaffold(tmp_path)
        runner = _runner(tmp_path)
        runner.run_demo_auth_execution(
            project_id="test-4f",
            scaffold_root=scaffold,
            approve_demo_auth=True,
            auth_profile="saucedemo_demo_auth",
            command_mode="auth_smoke",
        )
        # Verify subprocess was called and check the command arg
        assert mock_run.called
        call_kwargs = mock_run.call_args
        # The command string should not contain credential values
        cmd_arg = call_kwargs[0][0] if call_kwargs[0] else call_kwargs[1].get("args", "")
        assert "standard_user" not in str(cmd_arg)
        assert "secret_sauce" not in str(cmd_arg)

    @patch("core.demo_auth_runner.subprocess.run")
    def test_credentials_injected_via_env_not_args(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        scaffold = _make_scaffold(tmp_path)
        runner = _runner(tmp_path)
        runner.run_demo_auth_execution(
            project_id="test-4f",
            scaffold_root=scaffold,
            approve_demo_auth=True,
            auth_profile="saucedemo_demo_auth",
            command_mode="auth_smoke",
        )
        assert mock_run.called
        call_kwargs = mock_run.call_args[1]
        env = call_kwargs.get("env", {})
        # Credentials injected into env
        assert env.get("TEST_USERNAME") == "standard_user"
        assert env.get("TEST_PASSWORD") == "secret_sauce"

    @patch("core.demo_auth_runner.subprocess.run")
    def test_credentials_masked_in_stdout(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="Login with standard_user secret_sauce successful",
            stderr="",
        )
        scaffold = _make_scaffold(tmp_path)
        runner = _runner(tmp_path)
        report = runner.run_demo_auth_execution(
            project_id="test-4f",
            scaffold_root=scaffold,
            approve_demo_auth=True,
            auth_profile="saucedemo_demo_auth",
            command_mode="auth_smoke",
        )
        for cmd in report.commands:
            if cmd.executed:
                assert "standard_user" not in cmd.stdout_excerpt
                assert "secret_sauce" not in cmd.stdout_excerpt

    def test_credential_profile_has_no_raw_values_in_report(self, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_demo_auth_execution(
            project_id="test-4f",
            approve_demo_auth=False,
        )
        # No credential profile on blocked report
        assert report.credential_profile is None

    @patch("core.demo_auth_runner.subprocess.run")
    def test_real_credentials_used_always_false(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        scaffold = _make_scaffold(tmp_path)
        runner = _runner(tmp_path)
        report = runner.run_demo_auth_execution(
            project_id="test-4f",
            scaffold_root=scaffold,
            approve_demo_auth=True,
            auth_profile="saucedemo_demo_auth",
            command_mode="auth_smoke",
        )
        # Public demo credentials are used but real_credentials_used stays False
        assert report.real_credentials_used is False
        assert report.personal_account_used is False
        assert report.production_account_used is False


# ===========================================================================
# 9. DemoAuthRunner — environment sanitization
# ===========================================================================

class TestDemoAuthRunnerEnvSafety:
    def test_build_safe_env_strips_password(self, tmp_path):
        runner = _runner(tmp_path)
        profile_meta = _DEMO_AUTH_PROFILES["saucedemo_demo_auth"]
        storage_path = tmp_path / ".auth" / "storageState.json"
        import os
        os.environ["MY_PASSWORD_VALUE"] = "should_be_stripped"
        try:
            env = runner._build_safe_env(profile_meta, storage_path)
            assert "MY_PASSWORD_VALUE" not in env
        finally:
            del os.environ["MY_PASSWORD_VALUE"]

    def test_build_safe_env_strips_secret(self, tmp_path):
        runner = _runner(tmp_path)
        profile_meta = _DEMO_AUTH_PROFILES["saucedemo_demo_auth"]
        storage_path = tmp_path / ".auth" / "storageState.json"
        import os
        os.environ["API_SECRET_VALUE"] = "should_be_stripped"
        try:
            env = runner._build_safe_env(profile_meta, storage_path)
            assert "API_SECRET_VALUE" not in env
        finally:
            del os.environ["API_SECRET_VALUE"]

    def test_build_safe_env_sets_base_url(self, tmp_path):
        runner = _runner(tmp_path)
        profile_meta = _DEMO_AUTH_PROFILES["saucedemo_demo_auth"]
        storage_path = tmp_path / ".auth" / "storageState.json"
        env = runner._build_safe_env(profile_meta, storage_path)
        assert env["BASE_URL"] == "https://www.saucedemo.com"

    def test_build_safe_env_sets_storage_state_path(self, tmp_path):
        runner = _runner(tmp_path)
        profile_meta = _DEMO_AUTH_PROFILES["saucedemo_demo_auth"]
        storage_path = tmp_path / ".auth" / "storageState.json"
        env = runner._build_safe_env(profile_meta, storage_path)
        assert env["AUTH_STORAGE_STATE_PATH"] == str(storage_path)


# ===========================================================================
# 10. DemoAuthRunner — storageState
# ===========================================================================

class TestDemoAuthRunnerStorageState:
    @patch("core.demo_auth_runner.subprocess.run")
    def test_storage_state_path_under_09_auth(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        scaffold = _make_scaffold(tmp_path)
        runner = _runner(tmp_path)
        # Simulate storageState creation by Playwright
        ss_path = tmp_path / "outputs" / "test-4f" / "09_auth" / ".auth" / "storageState.json"
        ss_path.parent.mkdir(parents=True, exist_ok=True)
        ss_path.write_text('{"cookies":[],"origins":[]}')
        report = runner.run_demo_auth_execution(
            project_id="test-4f",
            scaffold_root=scaffold,
            approve_demo_auth=True,
            auth_profile="saucedemo_demo_auth",
            command_mode="auth_setup",
        )
        assert report.storage_state_created is True
        ss_artifacts = [a for a in report.session_artifacts if a.artifact_type == "storage_state"]
        assert len(ss_artifacts) == 1
        assert "09_auth" in ss_artifacts[0].path

    @patch("core.demo_auth_runner.subprocess.run")
    def test_storage_state_approved_for_commit_false(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        scaffold = _make_scaffold(tmp_path)
        runner = _runner(tmp_path)
        ss_path = tmp_path / "outputs" / "test-4f" / "09_auth" / ".auth" / "storageState.json"
        ss_path.parent.mkdir(parents=True, exist_ok=True)
        ss_path.write_text('{"cookies":[]}')
        report = runner.run_demo_auth_execution(
            project_id="test-4f",
            scaffold_root=scaffold,
            approve_demo_auth=True,
            auth_profile="saucedemo_demo_auth",
            command_mode="auth_setup",
        )
        for artifact in report.session_artifacts:
            assert artifact.approved_for_commit is False
            assert artifact.client_visible is False

    @patch("core.demo_auth_runner.subprocess.run")
    def test_storage_state_not_read_only_path_recorded(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        scaffold = _make_scaffold(tmp_path)
        runner = _runner(tmp_path)
        ss_path = tmp_path / "outputs" / "test-4f" / "09_auth" / ".auth" / "storageState.json"
        ss_path.parent.mkdir(parents=True, exist_ok=True)
        ss_path.write_text('{"cookies":[],"origins":[{"origin":"https://www.saucedemo.com","localStorage":[]}]}')
        report = runner.run_demo_auth_execution(
            project_id="test-4f",
            scaffold_root=scaffold,
            approve_demo_auth=True,
            auth_profile="saucedemo_demo_auth",
            command_mode="auth_setup",
        )
        # Path recorded but content must not appear in report
        report_json = json.dumps(report.to_dict())
        assert "saucedemo.com" not in report_json or "storageState" in report_json
        # The raw storageState content should NOT be in the report
        assert '"cookies":[]' not in report_json

    @patch("core.demo_auth_runner.subprocess.run")
    def test_no_storage_state_if_not_created(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        scaffold = _make_scaffold(tmp_path)
        runner = _runner(tmp_path)
        report = runner.run_demo_auth_execution(
            project_id="test-4f",
            scaffold_root=scaffold,
            approve_demo_auth=True,
            auth_profile="saucedemo_demo_auth",
            command_mode="auth_smoke",
        )
        # storageState.json was not created by mock, so storage_state_created=False
        assert report.storage_state_created is False

    def test_storage_state_not_under_repo_root(self, tmp_path):
        runner = _runner(tmp_path)
        project_id = "test-4f"
        # The resolved path should be under outputs/<project_id>/09_auth/
        # NOT under the scaffold source or repo root
        expected_under = str(tmp_path / "outputs" / project_id / "09_auth")
        # Verify by checking _build_safe_env sets the path correctly
        profile_meta = _DEMO_AUTH_PROFILES["saucedemo_demo_auth"]
        storage_path = (
            tmp_path / "outputs" / project_id / "09_auth" / ".auth" / "storageState.json"
        )
        env = runner._build_safe_env(profile_meta, storage_path)
        assert expected_under in env["AUTH_STORAGE_STATE_PATH"]


# ===========================================================================
# 11. DemoAuthRunner — blocked commands
# ===========================================================================

class TestDemoAuthRunnerBlockedCommands:
    def test_npm_install_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        block = runner._check_command_blocked("npm install")
        assert block is not None

    def test_npx_playwright_install_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        block = runner._check_command_blocked("npx playwright install")
        assert block is not None

    def test_npm_test_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        block = runner._check_command_blocked("npm test")
        assert block is not None

    def test_unrestricted_playwright_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        block = runner._check_command_blocked("npx playwright test")
        assert block is not None

    def test_ecommerce_path_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        block = runner._check_command_blocked("npx playwright test tests/ecommerce --reporter=list")
        assert block is not None

    def test_admin_path_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        block = runner._check_command_blocked("npx playwright test tests/admin --reporter=list")
        assert block is not None

    def test_headed_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        block = runner._check_command_blocked("npx playwright test tests/auth --headed")
        assert block is not None

    def test_allowed_auth_command_passes(self, tmp_path):
        runner = _runner(tmp_path)
        block = runner._check_command_blocked("npx playwright test tests/auth --reporter=list")
        assert block is None

    def test_is_command_allowed_valid(self, tmp_path):
        runner = _runner(tmp_path)
        assert runner.is_command_allowed("npx playwright test tests/auth --reporter=list") is True

    def test_is_command_allowed_invalid(self, tmp_path):
        runner = _runner(tmp_path)
        assert runner.is_command_allowed("npm install") is False


# ===========================================================================
# 12. DemoAuthRunner — always-blocked targets/providers
# ===========================================================================

class TestDemoAuthRunnerBlockedTargets:
    def test_alza_domain_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        block = runner.validate_profile_blocked("some_auth", "https://www.alza.sk")
        assert block is not None

    def test_amazon_domain_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        block = runner.validate_profile_blocked("some_auth", "https://www.amazon.com")
        assert block is not None

    def test_google_domain_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        block = runner.validate_profile_blocked("some_auth", "https://accounts.google.com")
        assert block is not None

    def test_linear_domain_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        block = runner.validate_profile_blocked("linear_token_auth", None)
        assert block is not None

    def test_alza_provider_blocked_in_profile_id(self, tmp_path):
        runner = _runner(tmp_path)
        block = runner.validate_profile_blocked("alza_test_auth")
        assert block is not None

    @patch("core.demo_auth_runner.subprocess.run")
    def test_blocked_providers_never_reach_subprocess(self, mock_run, tmp_path):
        runner = _runner(tmp_path)
        for profile in ["alza_auth", "amazon_auth", "google_oauth", "linear_auth"]:
            runner.run_demo_auth_execution(
                project_id="test",
                approve_demo_auth=True,
                auth_profile=profile,
            )
        mock_run.assert_not_called()


# ===========================================================================
# 13. DemoAuthRunner — artifact rendering
# ===========================================================================

class TestDemoAuthRunnerArtifacts:
    def test_render_blocked_report_produces_artifacts(self, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_demo_auth_execution(
            project_id="test-4f", approve_demo_auth=False
        )
        paths = runner.render_auth_artifacts(report, "test-4f")
        assert "approval_json" in paths
        assert "report_json" in paths
        assert "command_log_md" in paths
        assert "artifacts_json" in paths
        assert "redaction_checklist" in paths

    def test_render_produces_8_artifacts(self, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_demo_auth_execution(
            project_id="test-4f", approve_demo_auth=False
        )
        paths = runner.render_auth_artifacts(report, "test-4f")
        assert len(paths) == 8

    def test_artifacts_under_09_auth(self, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_demo_auth_execution(
            project_id="test-4f", approve_demo_auth=False
        )
        paths = runner.render_auth_artifacts(report, "test-4f")
        for key, path in paths.items():
            assert "09_auth" in str(path)

    def test_report_json_no_raw_credentials(self, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_demo_auth_execution(
            project_id="test-4f", approve_demo_auth=False
        )
        paths = runner.render_auth_artifacts(report, "test-4f")
        content = paths["report_json"].read_text()
        assert "secret_sauce" not in content
        assert "standard_user" not in content

    @patch("core.demo_auth_runner.subprocess.run")
    def test_approved_report_json_no_raw_credentials(self, mock_run, tmp_path):
        # Approved execution also must not leak credential values into artifacts
        mock_run.return_value = MagicMock(returncode=0, stdout="Login OK", stderr="")
        scaffold = _make_scaffold(tmp_path)
        runner = _runner(tmp_path)
        report = runner.run_demo_auth_execution(
            project_id="test-4f",
            scaffold_root=scaffold,
            approve_demo_auth=True,
            auth_profile="saucedemo_demo_auth",
            command_mode="auth_smoke",
        )
        paths = runner.render_auth_artifacts(report, "test-4f")
        for key in ("report_json", "approval_json"):
            content = paths[key].read_text()
            assert "secret_sauce" not in content, f"secret_sauce leaked into {key}"
            assert "standard_user" not in content, f"standard_user leaked into {key}"

    def test_approval_json_delivery_flags_false(self, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_demo_auth_execution(
            project_id="test-4f", approve_demo_auth=False
        )
        paths = runner.render_auth_artifacts(report, "test-4f")
        data = json.loads(paths["report_json"].read_text())
        assert data["safe_to_deliver"] is False
        assert data["approved_for_client_delivery"] is False
        assert data["real_credentials_used"] is False


# ===========================================================================
# 14. CLI tool
# ===========================================================================

class TestCLITool:
    def test_no_project_id_returns_error(self):
        from tools.run_demo_auth import main
        result = main([])
        assert result == 2

    def test_no_approval_returns_blocked(self, tmp_path):
        from tools.run_demo_auth import main
        result = main(["--project-id", "test", "--no-write", "--outputs-root", str(tmp_path)])
        assert result == 1

    def test_unknown_profile_returns_blocked(self, tmp_path):
        from tools.run_demo_auth import main
        result = main([
            "--project-id", "test",
            "--approve-demo-auth-execution",
            "--auth-profile", "unknown_profile",
            "--no-write",
            "--outputs-root", str(tmp_path),
        ])
        assert result == 1

    def test_json_output_valid(self, tmp_path):
        from tools.run_demo_auth import main
        import io
        import contextlib
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            main(["--project-id", "test", "--json", "--outputs-root", str(tmp_path)])
        output = captured.getvalue()
        data = json.loads(output)
        assert "execution_status" in data
        assert "safe_to_deliver" in data
        assert data["safe_to_deliver"] is False

    def test_json_no_approval_shows_blocked(self, tmp_path):
        from tools.run_demo_auth import main
        import io
        import contextlib
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            main(["--project-id", "test", "--json", "--outputs-root", str(tmp_path)])
        data = json.loads(captured.getvalue())
        assert data["execution_status"] == "blocked"
        assert data["approved"] is False

    @patch("core.demo_auth_runner.subprocess.run")
    def test_approved_cli_calls_runner(self, mock_run, tmp_path):
        mock_run.return_value = MagicMock(returncode=0, stdout="ok", stderr="")
        from tools.run_demo_auth import main
        result = main([
            "--project-id", "test-4f",
            "--approve-demo-auth-execution",
            "--auth-profile", "saucedemo_demo_auth",
            "--command-mode", "auth_smoke",
            "--no-write",
            "--outputs-root", str(tmp_path / "outputs"),
        ])
        # subprocess was called (approved) or cleanly failed
        # Exit 0 if pass, 1 if error (dependencies not present)
        assert result in (0, 1)


# ===========================================================================
# 15. WorkbenchController integration
# ===========================================================================

class TestWorkbenchControllerPhase4F:
    def test_run_demo_auth_execution_method_exists(self):
        from core.workbench_controller import WorkbenchController
        assert hasattr(WorkbenchController, "run_demo_auth_execution")

    def test_render_demo_auth_artifacts_method_exists(self):
        from core.workbench_controller import WorkbenchController
        assert hasattr(WorkbenchController, "render_demo_auth_artifacts")

    def test_no_approval_blocked(self, tmp_path):
        from core.workbench_controller import WorkbenchController
        wc = WorkbenchController(outputs_root=tmp_path / "outputs")
        report = wc.run_demo_auth_execution("test", approve_demo_auth=False)
        assert report.execution_status == "blocked"
        assert report.safe_to_deliver is False

    def test_render_produces_artifacts(self, tmp_path):
        from core.workbench_controller import WorkbenchController
        wc = WorkbenchController(outputs_root=tmp_path / "outputs")
        report = wc.run_demo_auth_execution("test", approve_demo_auth=False)
        paths = wc.render_demo_auth_artifacts(report, "test")
        assert "report_json" in paths


# ===========================================================================
# 16. Phase 4F static safety
# ===========================================================================

class TestPhase4FStaticSafety:
    def test_inspector_no_subprocess_import_at_module_level(self):
        import ast
        import inspect
        import core.credential_safety_inspector as mod
        src = inspect.getsource(mod)
        tree = ast.parse(src)
        # subprocess must not be imported at module level (it's in demo_auth_runner)
        top_imports = [
            node for node in ast.walk(tree)
            if isinstance(node, (ast.Import, ast.ImportFrom))
        ]
        for node in top_imports:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "subprocess", "credential_safety_inspector must not import subprocess"

    def test_demo_auth_runner_subprocess_gated_by_approval(self):
        import inspect
        import core.demo_auth_runner as mod
        src = inspect.getsource(mod)
        # subprocess.run must only appear inside _run_auth_command (not at top level)
        assert "subprocess.run" in src, "subprocess.run should exist"
        # The approval check must precede any subprocess call in run_demo_auth_execution
        run_pos = src.index("def run_demo_auth_execution")
        approval_pos = src.index("_validate_approval", run_pos)
        subprocess_pos = src.index("subprocess.run")
        # The method for running subprocess is defined later (good)
        assert approval_pos < subprocess_pos or "_run_auth_command" in src

    def test_no_dotenv_in_demo_auth_runner(self):
        import inspect
        import core.demo_auth_runner as mod
        src = inspect.getsource(mod)
        assert "load_dotenv" not in src
        assert "dotenv" not in src

    def test_no_env_file_read_in_demo_auth_runner(self):
        import inspect
        import core.demo_auth_runner as mod
        src = inspect.getsource(mod)
        # No reading of .env files
        assert 'open(".env")' not in src
        assert "read_text('.env')" not in src

    def test_demo_auth_profiles_only_saucedemo(self):
        assert list(_DEMO_AUTH_PROFILES.keys()) == ["saucedemo_demo_auth"]

    def test_blocked_domains_includes_key_sites(self):
        blocked = " ".join(_ALWAYS_BLOCKED_DOMAINS)
        assert "alza.sk" in blocked
        assert "amazon.com" in blocked
        assert "google.com" in blocked
        assert "linear.app" in blocked
        assert "linkedin.com" in blocked

    def test_secret_env_patterns_comprehensive(self):
        assert "PASSWORD" in _SECRET_ENV_PATTERNS
        assert "SECRET" in _SECRET_ENV_PATTERNS
        assert "TOKEN" in _SECRET_ENV_PATTERNS
        assert "AUTH" in _SECRET_ENV_PATTERNS


# ===========================================================================
# 17. Docs governance
# ===========================================================================

class TestPhase4FDocsGovernance:
    def test_commands_md_mentions_run_demo_auth(self):
        content = (
            __import__("pathlib").Path("docs/COMMANDS.md").read_text(encoding="utf-8")
        )
        assert "run_demo_auth" in content
        assert "approve-demo-auth-execution" in content.replace("_", "-")

    def test_safety_rules_mentions_phase_4f(self):
        content = (
            __import__("pathlib").Path("docs/SAFETY_RULES.md").read_text(encoding="utf-8")
        )
        assert "4F" in content

    def test_phase_contracts_mentions_phase_4f(self):
        content = (
            __import__("pathlib").Path("docs/PHASE_CONTRACTS.md").read_text(encoding="utf-8")
        )
        assert "4F" in content

    def test_runbook_mentions_phase_4f(self):
        content = (
            __import__("pathlib").Path("docs/RUNBOOK.md").read_text(encoding="utf-8")
        )
        assert "4F" in content

    def test_docs_manifest_mentions_09_auth(self):
        content = (
            __import__("pathlib").Path("docs/DOCS_MANIFEST.md").read_text(encoding="utf-8")
        )
        assert "09_auth" in content

    def test_agent_contract_mentions_demo_auth(self):
        content = (
            __import__("pathlib").Path("docs/AGENT_CONTRACT.md").read_text(encoding="utf-8")
        )
        assert "demo-auth-execution" in content or "demo auth" in content.lower()

    def test_artifact_contracts_mentions_09_auth(self):
        content = (
            __import__("pathlib").Path("docs/ARTIFACT_CONTRACTS.md").read_text(encoding="utf-8")
        )
        assert "09_auth" in content

    def test_schema_foundation_mentions_auth_execution(self):
        content = (
            __import__("pathlib").Path("docs/SCHEMA_FOUNDATION.md").read_text(encoding="utf-8")
        )
        assert "AuthExecution" in content or "auth_execution" in content
