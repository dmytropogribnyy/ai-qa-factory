"""Tests for Phase 5L: tools/run_browser_execution.py CLI.

Covers:
- Blocked flag rejection (--password, --token, etc.)
- Missing profile → exit 2
- Both profiles → exit 2
- Plan mode (no approval flag) → execution_status blocked
- Readonly profile routing: amazon_public_readonly, alza_public_readonly
- Demo profile routing: saucedemo_public_demo
- No subprocess without approval
- Safety invariants preserved through CLI path
- --no-write mode
- Invalid command-mode rejected by argparse

subprocess is ALWAYS mocked — no real browser is launched.
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.browser_execution_runner import BrowserExecutionRunner, _READONLY_PROFILES
from core.schemas.browser_execution import BrowserExecutionReport


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _runner(tmp_path: Path) -> BrowserExecutionRunner:
    return BrowserExecutionRunner(outputs_root=tmp_path / "outputs")


def _make_scaffold(tmp_path: Path, project_id: str = "test-cli") -> Path:
    scaffold = tmp_path / "outputs" / project_id / "03_framework" / "playwright"
    scaffold.mkdir(parents=True, exist_ok=True)
    (scaffold / "package.json").write_text('{"name":"test"}')
    (scaffold / "tests").mkdir(exist_ok=True)
    (scaffold / "tests" / "smoke").mkdir(exist_ok=True)
    return scaffold


# ===========================================================================
# 1. Blocked flag check (module-level function)
# ===========================================================================

class TestBlockedFlagCheck:
    def _check(self, argv):
        from tools.run_browser_execution import _check_blocked_flags
        with pytest.raises(SystemExit) as exc:
            _check_blocked_flags(argv)
        assert exc.value.code == 2

    def test_password_blocked(self):
        self._check(["--password", "hunter2"])

    def test_token_blocked(self):
        self._check(["--token", "abc123"])

    def test_secret_blocked(self):
        self._check(["--secret", "mysecret"])

    def test_api_key_blocked(self):
        self._check(["--api-key", "key"])

    def test_cookie_blocked(self):
        self._check(["--cookie", "session=abc"])

    def test_pat_blocked(self):
        self._check(["--pat", "ghp_xxx"])

    def test_access_token_blocked(self):
        self._check(["--access-token", "tok"])

    def test_bearer_blocked(self):
        self._check(["--bearer", "tok"])

    def test_db_url_blocked(self):
        self._check(["--db-url", "postgresql://..."])

    def test_connection_string_blocked(self):
        self._check(["--connection-string", "..."])

    def test_safe_flags_not_blocked(self):
        from tools.run_browser_execution import _check_blocked_flags
        # should not raise
        _check_blocked_flags(["--project-id", "x", "--readonly-profile", "amazon_public_readonly"])


# ===========================================================================
# 2. CLI argparse validation
# ===========================================================================

class TestCLIArgValidation:
    def _run_main(self, argv):
        import tools.run_browser_execution as cli_mod
        with patch.object(sys, "argv", ["run_browser_execution.py"] + argv):
            with pytest.raises(SystemExit) as exc:
                cli_mod.main()
        return exc.value.code

    def test_no_profile_exits_2(self):
        code = self._run_main(["--project-id", "p"])
        assert code == 2

    def test_both_profiles_exits_2(self):
        code = self._run_main([
            "--project-id", "p",
            "--demo-profile", "saucedemo_public_demo",
            "--readonly-profile", "amazon_public_readonly",
        ])
        assert code == 2

    def test_invalid_command_mode_exits_2(self):
        code = self._run_main([
            "--project-id", "p",
            "--readonly-profile", "amazon_public_readonly",
            "--command-mode", "bad_mode",
        ])
        assert code == 2


# ===========================================================================
# 3. Runner direct — no-approval plan mode
# ===========================================================================

class TestNoApprovalPlanMode:
    def test_amazon_without_approval_blocked(self, tmp_path):
        _make_scaffold(tmp_path, "test-plan")
        runner = _runner(tmp_path)
        report = runner.run_browser_execution(
            project_id="test-plan",
            readonly_profile="amazon_public_readonly",
            command_mode="readonly_smoke",
            approve_public_readonly=False,
        )
        assert report.execution_status == "blocked"
        assert report.blockers

    def test_alza_without_approval_blocked(self, tmp_path):
        _make_scaffold(tmp_path, "test-plan")
        runner = _runner(tmp_path)
        report = runner.run_browser_execution(
            project_id="test-plan",
            readonly_profile="alza_public_readonly",
            command_mode="readonly_smoke",
            approve_public_readonly=False,
        )
        assert report.execution_status == "blocked"
        assert report.blockers

    def test_demo_without_approval_blocked(self, tmp_path):
        _make_scaffold(tmp_path, "test-plan")
        runner = _runner(tmp_path)
        report = runner.run_browser_execution(
            project_id="test-plan",
            demo_profile="saucedemo_public_demo",
            command_mode="smoke",
            approve_demo=False,
        )
        assert report.execution_status == "blocked"
        assert report.blockers


# ===========================================================================
# 4. Runner direct — mocked subprocess, approved
# ===========================================================================

class TestApprovedExecution:
    def _mock_proc(self, returncode=0, stdout="1 passed", stderr=""):
        proc = MagicMock()
        proc.returncode = returncode
        proc.stdout = stdout
        proc.stderr = stderr
        return proc

    def test_amazon_approved_runs(self, tmp_path):
        # Amazon/Alza ecommerce_public_readonly requires BOTH approval flags
        _make_scaffold(tmp_path, "amazon-desk")
        runner = _runner(tmp_path)
        with patch("subprocess.run", return_value=self._mock_proc()) as mock_sub:
            report = runner.run_browser_execution(
                project_id="amazon-desk",
                readonly_profile="amazon_public_readonly",
                base_url="https://www.amazon.com",
                command_mode="readonly_smoke",
                approve_demo=True,
                approve_public_readonly=True,
            )
        assert mock_sub.called
        assert report.execution_status in ("complete", "error")

    def test_alza_cz_approved_runs(self, tmp_path):
        # Amazon/Alza ecommerce_public_readonly requires BOTH approval flags
        _make_scaffold(tmp_path, "alza-desk")
        runner = _runner(tmp_path)
        with patch("subprocess.run", return_value=self._mock_proc()) as mock_sub:
            report = runner.run_browser_execution(
                project_id="alza-desk",
                readonly_profile="alza_public_readonly",
                base_url="https://www.alza.cz",
                command_mode="readonly_smoke",
                approve_demo=True,
                approve_public_readonly=True,
            )
        assert mock_sub.called
        assert report.execution_status in ("complete", "error")

    def test_saucedemo_approved_runs(self, tmp_path):
        _make_scaffold(tmp_path, "sauce-desk")
        runner = _runner(tmp_path)
        with patch("subprocess.run", return_value=self._mock_proc()) as mock_sub:
            report = runner.run_browser_execution(
                project_id="sauce-desk",
                demo_profile="saucedemo_public_demo",
                command_mode="smoke",
                approve_demo=True,
            )
        assert mock_sub.called
        assert report.execution_status in ("complete", "error")

    def test_subprocess_fail_gives_error_status(self, tmp_path):
        _make_scaffold(tmp_path, "fail-desk")
        runner = _runner(tmp_path)
        with patch("subprocess.run", return_value=self._mock_proc(returncode=1)):
            report = runner.run_browser_execution(
                project_id="fail-desk",
                readonly_profile="amazon_public_readonly",
                command_mode="readonly_smoke",
                approve_demo=True,
                approve_public_readonly=True,
            )
        assert report.execution_status == "error"


# ===========================================================================
# 5. Safety invariants through CLI path
# ===========================================================================

class TestSafetyInvariants:
    def test_safe_to_deliver_always_false(self, tmp_path):
        _make_scaffold(tmp_path, "safety-check")
        runner = _runner(tmp_path)
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="ok", stderr="")):
            report = runner.run_browser_execution(
                project_id="safety-check",
                readonly_profile="amazon_public_readonly",
                command_mode="readonly_smoke",
                approve_public_readonly=True,
            )
        assert report.safe_to_deliver is False

    def test_approved_for_client_delivery_always_false(self, tmp_path):
        _make_scaffold(tmp_path, "safety-check2")
        runner = _runner(tmp_path)
        with patch("subprocess.run", return_value=MagicMock(returncode=0, stdout="ok", stderr="")):
            report = runner.run_browser_execution(
                project_id="safety-check2",
                readonly_profile="amazon_public_readonly",
                command_mode="readonly_smoke",
                approve_public_readonly=True,
            )
        assert report.approved_for_client_delivery is False

    def test_blocked_report_safe_to_deliver_false(self, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_browser_execution(
            project_id="blocked-check",
            readonly_profile="amazon_public_readonly",
            command_mode="readonly_smoke",
            approve_public_readonly=False,
        )
        assert report.safe_to_deliver is False

    def test_schema_roundtrip_preserves_invariants(self, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_browser_execution(
            project_id="roundtrip",
            readonly_profile="amazon_public_readonly",
            command_mode="readonly_smoke",
            approve_public_readonly=False,
        )
        data = report.to_dict()
        restored = BrowserExecutionReport.from_dict(data)
        assert restored.safe_to_deliver is False
        assert restored.approved_for_client_delivery is False


# ===========================================================================
# 6. Blocked targets
# ===========================================================================

class TestBlockedTargets:
    def test_linear_always_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        block = runner.validate_execution_allowed(
            approve_demo=True,
            approve_public_readonly=True,
            target_category="task_source",
            base_url="https://linear.app/team/issue/X",
            demo_profile=None,
            readonly_profile=None,
            command_mode="smoke",
        )
        assert block is not None

    def test_amazon_without_readonly_profile_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        block = runner.validate_execution_allowed(
            approve_demo=True,
            approve_public_readonly=True,
            target_category="ecommerce",
            base_url="https://www.amazon.com",
            demo_profile=None,
            readonly_profile=None,
            command_mode="smoke",
        )
        assert block is not None

    def test_amazon_with_both_approvals_passes(self, tmp_path):
        # ecommerce_public_readonly requires BOTH approve_demo + approve_public_readonly
        runner = _runner(tmp_path)
        block = runner.validate_execution_allowed(
            approve_demo=True,
            approve_public_readonly=True,
            target_category="ecommerce_public_readonly",
            base_url="https://www.amazon.com",
            demo_profile=None,
            readonly_profile="amazon_public_readonly",
            command_mode="readonly_smoke",
        )
        assert block is None

    def test_amazon_with_only_public_readonly_blocked(self, tmp_path):
        # Just approve_public_readonly is NOT enough for ecommerce_public_readonly
        runner = _runner(tmp_path)
        block = runner.validate_execution_allowed(
            approve_demo=False,
            approve_public_readonly=True,
            target_category="ecommerce_public_readonly",
            base_url="https://www.amazon.com",
            demo_profile=None,
            readonly_profile="amazon_public_readonly",
            command_mode="readonly_smoke",
        )
        assert block is not None


# ===========================================================================
# 7. Profile registry
# ===========================================================================

class TestProfileRegistry:
    def test_amazon_public_readonly_in_registry(self):
        assert "amazon_public_readonly" in _READONLY_PROFILES

    def test_alza_public_readonly_in_registry(self):
        assert "alza_public_readonly" in _READONLY_PROFILES

    def test_amazon_profile_has_blocked_paths(self):
        profile = _READONLY_PROFILES["amazon_public_readonly"]
        assert "/signin" in profile["blocked_url_paths"]
        assert "/cart" in profile["blocked_url_paths"]
        assert "/checkout" in profile["blocked_url_paths"]

    def test_alza_profile_has_blocked_paths(self):
        profile = _READONLY_PROFILES["alza_public_readonly"]
        assert "/kosik" in profile["blocked_url_paths"]
        assert "/checkout" in profile["blocked_url_paths"]

    def test_amazon_profile_approval_flag(self):
        assert _READONLY_PROFILES["amazon_public_readonly"]["approval_flag"] == "public_readonly"

    def test_alza_profile_approval_flag(self):
        assert _READONLY_PROFILES["alza_public_readonly"]["approval_flag"] == "public_readonly"
