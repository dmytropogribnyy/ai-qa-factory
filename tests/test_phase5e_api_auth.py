"""
Phase 5E — API Auth Smoke tests.

All network calls are mocked — no real HTTP in pytest.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch


from core.api_auth_runner import APIAuthRunner, _API_TARGET_PROFILES
from core.schemas.api_auth import (
    APIAuthExecutionReport,
    APIAuthSessionArtifact,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_runner(tmp_path: Path) -> APIAuthRunner:
    return APIAuthRunner(outputs_root=tmp_path)


def _mock_urlopen_ok(token: str = "abc123token"):
    """Return a context manager that yields a mock HTTP response with a token."""
    body = json.dumps({"token": token}).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.status = 200
    mock_resp.read.return_value = body
    return mock_resp


def _mock_urlopen_read_ok():
    """Mock GET /booking response."""
    body = json.dumps([{"bookingid": 1}, {"bookingid": 2}]).encode("utf-8")
    mock_resp = MagicMock()
    mock_resp.__enter__ = lambda s: s
    mock_resp.__exit__ = MagicMock(return_value=False)
    mock_resp.status = 200
    mock_resp.read.return_value = body
    return mock_resp


def _env_with(**kwargs):
    return {**os.environ, **kwargs}


# ---------------------------------------------------------------------------
# Schema invariant tests
# ---------------------------------------------------------------------------

class TestAPIAuthSchemaInvariants:
    def test_report_safety_invariants_hardcoded_false(self):
        report = APIAuthExecutionReport(
            raw_credentials_logged=True,
            raw_credentials_serialized=True,
            token_logged=True,
            token_serialized=True,
            safe_to_deliver=True,
            approved_for_client_delivery=True,
            personal_account_used=True,
            production_account_used=True,
        )
        assert report.raw_credentials_logged is False
        assert report.raw_credentials_serialized is False
        assert report.token_logged is False
        assert report.token_serialized is False
        assert report.safe_to_deliver is False
        assert report.approved_for_client_delivery is False
        assert report.personal_account_used is False
        assert report.production_account_used is False

    def test_report_from_dict_safety_invariants(self):
        report = APIAuthExecutionReport.from_dict({
            "raw_credentials_logged": True,
            "token_logged": True,
            "safe_to_deliver": True,
            "approved_for_client_delivery": True,
        })
        assert report.raw_credentials_logged is False
        assert report.token_logged is False
        assert report.safe_to_deliver is False
        assert report.approved_for_client_delivery is False

    def test_session_artifact_internal_only_always_true(self):
        artifact = APIAuthSessionArtifact(internal_only=False, approved_for_commit=True)
        assert artifact.internal_only is True
        assert artifact.approved_for_commit is False

    def test_session_artifact_from_dict_forced(self):
        artifact = APIAuthSessionArtifact.from_dict({"internal_only": False, "approved_for_commit": True})
        assert artifact.internal_only is True
        assert artifact.approved_for_commit is False


# ---------------------------------------------------------------------------
# Gate tests
# ---------------------------------------------------------------------------

class TestAPIAuthRunnerGates:
    def test_gate1_no_approval_blocks(self, tmp_path):
        runner = _make_runner(tmp_path)
        report = runner.run_api_auth(
            project_id="test",
            approve_api_auth_execution=False,
        )
        assert report.execution_status == "blocked"
        assert report.approved is False
        assert any("approve-api-auth-execution" in b for b in report.blockers)

    def test_gate2_personal_account_blocks(self, tmp_path):
        runner = _make_runner(tmp_path)
        report = runner.run_api_auth(
            project_id="test",
            approve_api_auth_execution=True,
            personal_account_confirmed=True,
        )
        assert report.execution_status == "blocked"
        assert any("Personal" in b for b in report.blockers)

    def test_gate3_production_account_blocks(self, tmp_path):
        runner = _make_runner(tmp_path)
        report = runner.run_api_auth(
            project_id="test",
            approve_api_auth_execution=True,
            production_account_confirmed=True,
        )
        assert report.execution_status == "blocked"
        assert any("Production" in b for b in report.blockers)

    def test_gate4_unknown_profile_blocks(self, tmp_path):
        runner = _make_runner(tmp_path)
        report = runner.run_api_auth(
            project_id="test",
            approve_api_auth_execution=True,
            target_profile="nonexistent_profile",
        )
        assert report.execution_status == "blocked"
        assert any("Unknown target profile" in b for b in report.blockers)

    def test_gate5_blocked_url_blocks(self, tmp_path):
        runner = _make_runner(tmp_path)
        for blocked_url in [
            "https://accounts.google.com",
            "https://amazon.com",
            "https://alza.sk",
            "https://linkedin.com",
            "https://upwork.com",
        ]:
            report = runner.run_api_auth(
                project_id="test",
                approve_api_auth_execution=True,
                target_profile="restful_booker_public_api",
                base_url=blocked_url,
            )
            assert report.execution_status == "blocked", f"Should block {blocked_url}"
            assert any("blocked" in b.lower() for b in report.blockers)

    def test_gate6_invalid_env_var_name_blocks(self, tmp_path):
        runner = _make_runner(tmp_path)
        for bad_name in ["lowercase", "has space", "123start", ""]:
            report = runner.run_api_auth(
                project_id="test",
                approve_api_auth_execution=True,
                target_profile="restful_booker_public_api",
                username_env_var=bad_name,
            )
            assert report.execution_status == "blocked", f"Should block name: {bad_name!r}"

    def test_gate7_missing_env_var_blocks(self, tmp_path):
        runner = _make_runner(tmp_path)
        with patch.dict(os.environ, {}, clear=False):
            # Ensure PHASE5D_MISSING_VAR not in env
            os.environ.pop("PHASE5D_MISSING_VAR", None)
            report = runner.run_api_auth(
                project_id="test",
                approve_api_auth_execution=True,
                target_profile="restful_booker_public_api",
                username_env_var="PHASE5D_MISSING_VAR",
            )
        assert report.execution_status == "blocked"
        assert any("PHASE5D_MISSING_VAR" in b for b in report.blockers)

    def test_gate1_no_env_lookup_before_approval(self, tmp_path):
        """Gate 1 must block before touching env vars at all."""
        runner = _make_runner(tmp_path)
        # Even if env var is set, without approval it must block immediately
        with patch.dict(os.environ, {"SOME_VAR": "somevalue"}):
            report = runner.run_api_auth(
                project_id="test",
                approve_api_auth_execution=False,
                target_profile="restful_booker_public_api",
                username_env_var="SOME_VAR",
            )
        assert report.execution_status == "blocked"
        # Verify no commands were executed
        assert len(report.commands) == 0


# ---------------------------------------------------------------------------
# Happy path tests (mocked network)
# ---------------------------------------------------------------------------

class TestAPIAuthRunnerExecution:
    def test_happy_path_token_returned(self, tmp_path):
        runner = _make_runner(tmp_path)
        mock_auth_resp = _mock_urlopen_ok(token="secret_token_value")
        mock_read_resp = _mock_urlopen_read_ok()

        with patch.dict(os.environ, {
            "RESTFUL_BOOKER_USERNAME": "admin",
            "RESTFUL_BOOKER_PASSWORD": "password123",
        }):
            with patch("urllib.request.urlopen", side_effect=[mock_auth_resp, mock_read_resp]):
                report = runner.run_api_auth(
                    project_id="test-api-smoke",
                    approve_api_auth_execution=True,
                    target_profile="restful_booker_public_api",
                    username_env_var="RESTFUL_BOOKER_USERNAME",
                    password_env_var="RESTFUL_BOOKER_PASSWORD",
                )

        assert report.execution_status == "passed"
        assert report.approved is True
        assert len(report.commands) >= 1
        auth_cmd = report.commands[0]
        assert auth_cmd.token_present is True
        assert auth_cmd.status == "passed"

    def test_safety_flags_always_false_in_execution(self, tmp_path):
        runner = _make_runner(tmp_path)
        mock_auth_resp = _mock_urlopen_ok()
        mock_read_resp = _mock_urlopen_read_ok()

        with patch.dict(os.environ, {
            "RB_USER": "admin",
            "RB_PASS": "password123",
        }):
            with patch("urllib.request.urlopen", side_effect=[mock_auth_resp, mock_read_resp]):
                report = runner.run_api_auth(
                    project_id="test",
                    approve_api_auth_execution=True,
                    target_profile="restful_booker_public_api",
                    username_env_var="RB_USER",
                    password_env_var="RB_PASS",
                )

        assert report.raw_credentials_logged is False
        assert report.raw_credentials_serialized is False
        assert report.token_logged is False
        assert report.token_serialized is False
        assert report.safe_to_deliver is False
        assert report.approved_for_client_delivery is False
        assert report.personal_account_used is False
        assert report.production_account_used is False

    def test_token_value_masked_in_stdout_excerpt(self, tmp_path):
        runner = _make_runner(tmp_path)
        token = "super_secret_token_xyz"
        mock_auth_resp = _mock_urlopen_ok(token=token)
        mock_read_resp = _mock_urlopen_read_ok()

        with patch.dict(os.environ, {
            "RB_USER": "admin",
            "RB_PASS": "password123",
        }):
            with patch("urllib.request.urlopen", side_effect=[mock_auth_resp, mock_read_resp]):
                report = runner.run_api_auth(
                    project_id="test",
                    approve_api_auth_execution=True,
                    target_profile="restful_booker_public_api",
                    username_env_var="RB_USER",
                    password_env_var="RB_PASS",
                )

        # Token value must not appear in any stdout excerpt
        for cmd in report.commands:
            assert token not in cmd.stdout_excerpt, f"Token leaked in {cmd.id} stdout_excerpt"
            assert token not in cmd.stderr_excerpt, f"Token leaked in {cmd.id} stderr_excerpt"

    def test_credentials_masked_in_stdout_excerpt(self, tmp_path):
        runner = _make_runner(tmp_path)
        mock_auth_resp = _mock_urlopen_ok()
        mock_read_resp = _mock_urlopen_read_ok()

        with patch.dict(os.environ, {
            "RB_USER": "admin_test_user_xyz",
            "RB_PASS": "password_xyz_secret",
        }):
            with patch("urllib.request.urlopen", side_effect=[mock_auth_resp, mock_read_resp]):
                report = runner.run_api_auth(
                    project_id="test",
                    approve_api_auth_execution=True,
                    target_profile="restful_booker_public_api",
                    username_env_var="RB_USER",
                    password_env_var="RB_PASS",
                )

        for cmd in report.commands:
            assert "admin_test_user_xyz" not in cmd.stdout_excerpt
            assert "password_xyz_secret" not in cmd.stdout_excerpt

    def test_no_read_check_skips_step2(self, tmp_path):
        runner = _make_runner(tmp_path)
        mock_auth_resp = _mock_urlopen_ok()

        with patch.dict(os.environ, {"RB_USER": "admin", "RB_PASS": "pw"}):
            with patch("urllib.request.urlopen", return_value=mock_auth_resp) as mock_open:
                report = runner.run_api_auth(
                    project_id="test",
                    approve_api_auth_execution=True,
                    target_profile="restful_booker_public_api",
                    username_env_var="RB_USER",
                    password_env_var="RB_PASS",
                    run_safe_read_check=False,
                )

        # Only 1 command (no step2)
        assert len(report.commands) == 1
        assert "step1" in report.commands[0].id
        assert mock_open.call_count == 1

    def test_failed_auth_returns_failed_status(self, tmp_path):
        import urllib.error
        runner = _make_runner(tmp_path)

        with patch.dict(os.environ, {"RB_USER": "admin", "RB_PASS": "wrongpw"}):
            with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
                url="https://restful-booker.herokuapp.com/auth",
                code=403,
                msg="Forbidden",
                hdrs=None,
                fp=None,
            )):
                report = runner.run_api_auth(
                    project_id="test",
                    approve_api_auth_execution=True,
                    target_profile="restful_booker_public_api",
                    username_env_var="RB_USER",
                    password_env_var="RB_PASS",
                    run_safe_read_check=False,
                )

        assert report.execution_status in ("failed", "error")
        assert report.commands[0].token_present is False


# ---------------------------------------------------------------------------
# Artifact secret scan
# ---------------------------------------------------------------------------

class TestAPIAuthArtifactScan:
    def test_artifacts_contain_no_raw_credentials(self, tmp_path):
        runner = _make_runner(tmp_path)
        mock_auth_resp = _mock_urlopen_ok(token="artifact_secret_token")
        mock_read_resp = _mock_urlopen_read_ok()

        username = "artifact_test_user_xyz"
        password = "artifact_test_pass_xyz"

        with patch.dict(os.environ, {"ART_USER": username, "ART_PASS": password}):
            with patch("urllib.request.urlopen", side_effect=[mock_auth_resp, mock_read_resp]):
                runner.run_api_auth(
                    project_id="artifact-scan-test",
                    approve_api_auth_execution=True,
                    target_profile="restful_booker_public_api",
                    username_env_var="ART_USER",
                    password_env_var="ART_PASS",
                )

        # Scan all produced artifacts
        out_dir = tmp_path / "artifact-scan-test" / "13_api_auth"
        assert out_dir.exists(), "Artifact directory must be created"

        for artifact_file in out_dir.rglob("*"):
            if not artifact_file.is_file():
                continue
            content = artifact_file.read_text(encoding="utf-8")
            assert username not in content, f"Raw username in {artifact_file.name}"
            assert password not in content, f"Raw password in {artifact_file.name}"
            assert "artifact_secret_token" not in content, f"Raw token in {artifact_file.name}"

    def test_artifacts_safety_flags_in_json(self, tmp_path):
        runner = _make_runner(tmp_path)
        mock_auth_resp = _mock_urlopen_ok()
        mock_read_resp = _mock_urlopen_read_ok()

        with patch.dict(os.environ, {"RB_USER": "admin", "RB_PASS": "password123"}):
            with patch("urllib.request.urlopen", side_effect=[mock_auth_resp, mock_read_resp]):
                runner.run_api_auth(
                    project_id="flag-check",
                    approve_api_auth_execution=True,
                    target_profile="restful_booker_public_api",
                    username_env_var="RB_USER",
                    password_env_var="RB_PASS",
                )

        report_json = (tmp_path / "flag-check" / "13_api_auth" / "API_AUTH_EXECUTION_REPORT.json").read_text()
        data = json.loads(report_json)
        assert data["raw_credentials_logged"] is False
        assert data["raw_credentials_serialized"] is False
        assert data["token_logged"] is False
        assert data["token_serialized"] is False
        assert data["safe_to_deliver"] is False
        assert data["approved_for_client_delivery"] is False


# ---------------------------------------------------------------------------
# CLI flag safety
# ---------------------------------------------------------------------------

class TestAPIAuthCLISafety:
    def test_no_raw_secret_flags_in_cli(self):
        run_source = Path("tools/run_api_auth_smoke.py").read_text(encoding="utf-8")
        # These should NOT be registered as actual argument flags
        assert 'add_argument("--password"' not in run_source
        assert 'add_argument("--username"' not in run_source
        assert 'add_argument("--token"' not in run_source
        assert 'add_argument("--secret"' not in run_source
        # These SHOULD be present
        assert "--username-env-var" in run_source
        assert "--password-env-var" in run_source

    def test_allowed_profile_names(self):
        assert "restful_booker_public_api" in _API_TARGET_PROFILES
        profile = _API_TARGET_PROFILES["restful_booker_public_api"]
        assert profile.auth_endpoint == "/auth"
        assert "restful-booker" in profile.base_url
        assert profile.safe_read_endpoint is not None

    def test_blocked_url_patterns_cover_google_amazon_alza(self):
        runner = APIAuthRunner()
        for url in [
            "https://accounts.google.com",
            "https://amazon.com/login",
            "https://alza.sk",
            "https://linkedin.com",
            "https://upwork.com",
        ]:
            assert runner._is_blocked_url(url), f"Should block: {url}"

    def test_valid_env_var_names_accepted(self):
        runner = APIAuthRunner()
        for name in ["RESTFUL_BOOKER_USERNAME", "QA_TEST_USERNAME", "STAGING_USER", "A"]:
            ok, _ = runner._validate_env_var_name(name)
            assert ok, f"Should accept: {name}"

    def test_invalid_env_var_names_rejected(self):
        runner = APIAuthRunner()
        for name in ["lowercase", "has space", "123start", "", "TOO" + "O" * 62]:
            ok, _ = runner._validate_env_var_name(name)
            assert not ok, f"Should reject: {name!r}"

    def test_mask_replaces_secret_values(self):
        runner = APIAuthRunner()
        text = 'response body with username=admin and password=secret123 token=tok_xyz'
        masked = runner._mask(text, ["admin", "secret123", "tok_xyz"])
        assert "admin" not in masked
        assert "secret123" not in masked
        assert "tok_xyz" not in masked
        assert "[REDACTED]" in masked
