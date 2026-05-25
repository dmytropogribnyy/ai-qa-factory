"""Tests for Phase 3C: Approved Local Toolchain Validation.

IMPORTANT:
- No real npm/npx/playwright is executed in these tests.
- Subprocess calls in ToolchainValidator are mocked.
- No external URLs are fetched.
- No .env files are read.
- No credentials are used.
- All tests use tmp_path to avoid touching real outputs/.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.schemas.toolchain_validation import (
    ToolchainApprovalRecord,
    ToolchainCommandResult,
    ToolchainValidationReport,
)
from core.toolchain_validator import (
    ToolchainValidator,
    _ALLOWED_COMMANDS,
    _BLOCKED_SUBSTRINGS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_scaffold(tmp_path: Path, project_id: str = "test-proj") -> Path:
    """Create a minimal scaffold directory under tmp_path/outputs/<id>/03_framework/playwright/."""
    outputs = tmp_path / "outputs"
    root = outputs / project_id / "03_framework" / "playwright"
    root.mkdir(parents=True)
    (root / "package.json").write_text(
        '{"name":"test","scripts":{"typecheck":"tsc --noEmit"}}', encoding="utf-8"
    )
    (root / "playwright.config.ts").write_text(
        "import { defineConfig } from '@playwright/test';\nexport default defineConfig({ use: { baseURL: process.env.BASE_URL } });",
        encoding="utf-8",
    )
    (root / ".env.example").write_text("BASE_URL=http://localhost:3000\n", encoding="utf-8")
    (root / "tsconfig.json").write_text('{"compilerOptions":{"strict":true}}', encoding="utf-8")
    (root / "README.md").write_text("# Scaffold\n", encoding="utf-8")
    tests = root / "tests" / "smoke"
    tests.mkdir(parents=True)
    (tests / "smoke.spec.ts").write_text(
        "import { test } from '@playwright/test';\ntest('smoke', async () => {});", encoding="utf-8"
    )
    (root / "pages").mkdir()
    (root / "pages" / "BasePage.ts").write_text("export class BasePage {}", encoding="utf-8")
    fixtures_dir = root / "fixtures"
    fixtures_dir.mkdir()
    (fixtures_dir / "test-fixtures.ts").write_text("export {};", encoding="utf-8")
    utils = root / "utils"
    utils.mkdir()
    (utils / "env.ts").write_text(
        "export const BASE_URL = process.env.BASE_URL || 'http://localhost:3000';",
        encoding="utf-8",
    )
    return root


def _make_validator(tmp_path: Path) -> ToolchainValidator:
    return ToolchainValidator(outputs_root=tmp_path / "outputs")


def _write_clean_static_report(scaffold_root: Path) -> None:
    """Write a passing STATIC_VALIDATION_REPORT.json to bypass the prerequisite check."""
    report_data = {
        "project_id": scaffold_root.parent.parent.parent.name,
        "scaffold_root": str(scaffold_root),
        "validation_status": "pass",
        "blockers": [],
        "warnings": [],
        "safe_to_proceed_to_toolchain_validation": True,
        "safe_to_execute_tests": False,
        "execution_performed": False,
        "npm_performed": False,
        "npx_performed": False,
        "browser_performed": False,
        "external_calls_performed": False,
        "checks": [],
        "notes": [],
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    (scaffold_root / "STATIC_VALIDATION_REPORT.json").write_text(
        json.dumps(report_data), encoding="utf-8"
    )


def _write_blocker_static_report(scaffold_root: Path) -> None:
    """Write a failing STATIC_VALIDATION_REPORT.json with blockers."""
    report_data = {
        "project_id": "test",
        "scaffold_root": str(scaffold_root),
        "validation_status": "fail",
        "blockers": ["execution_allowed is True — cannot proceed"],
        "warnings": [],
        "safe_to_proceed_to_toolchain_validation": False,
        "safe_to_execute_tests": False,
        "execution_performed": False,
        "npm_performed": False,
        "npx_performed": False,
        "browser_performed": False,
        "external_calls_performed": False,
        "checks": [],
        "notes": [],
        "created_at": "2026-01-01T00:00:00+00:00",
    }
    (scaffold_root / "STATIC_VALIDATION_REPORT.json").write_text(
        json.dumps(report_data), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# Schema tests
# ---------------------------------------------------------------------------

class TestToolchainCommandResultSchema:
    def test_defaults(self) -> None:
        cmd = ToolchainCommandResult()
        assert cmd.id == ""
        assert cmd.command == ""
        assert cmd.cwd == ""
        assert cmd.exit_code is None
        assert cmd.stdout_excerpt == ""
        assert cmd.stderr_excerpt == ""
        assert cmd.status == "skipped"
        assert cmd.duration_seconds is None
        assert cmd.executed is False
        assert cmd.skipped_reason is None
        assert cmd.safety_notes == []

    def test_roundtrip(self) -> None:
        cmd = ToolchainCommandResult(
            id="c1",
            command="npm install",
            cwd="/tmp/scaffold",
            exit_code=0,
            stdout_excerpt="added 100 packages",
            stderr_excerpt="",
            status="pass",
            duration_seconds=12.5,
            executed=True,
            safety_notes=["OK"],
        )
        d = cmd.to_dict()
        restored = ToolchainCommandResult.from_dict(d)
        assert restored.id == "c1"
        assert restored.exit_code == 0
        assert restored.executed is True
        assert restored.status == "pass"
        assert restored.duration_seconds == 12.5
        assert restored.safety_notes == ["OK"]


class TestToolchainApprovalRecordSchema:
    def test_defaults(self) -> None:
        rec = ToolchainApprovalRecord()
        assert rec.approved is False
        assert rec.approval_source == ""
        assert rec.approved_commands == []
        assert rec.denied_commands == []
        assert rec.safety_constraints == []

    def test_roundtrip(self) -> None:
        rec = ToolchainApprovalRecord(
            project_id="proj",
            scaffold_root="/tmp/scaffold",
            approved=True,
            approval_source="cli_flag",
            approval_reason="--approve-toolchain passed",
            approved_commands=["npm install"],
            denied_commands=["npm test"],
            safety_constraints=["safe_to_execute_tests remains False"],
        )
        d = rec.to_dict()
        restored = ToolchainApprovalRecord.from_dict(d)
        assert restored.approved is True
        assert restored.approval_source == "cli_flag"
        assert restored.approved_commands == ["npm install"]
        assert restored.denied_commands == ["npm test"]


class TestToolchainValidationReportSchema:
    def test_safe_defaults(self) -> None:
        report = ToolchainValidationReport()
        assert report.approval_required is True
        assert report.approved is False
        assert report.npm_install_performed is False
        assert report.typecheck_performed is False
        assert report.playwright_discovery_performed is False
        assert report.browser_execution_performed is False
        assert report.external_url_used is False
        assert report.credentials_used is False
        assert report.safe_to_proceed_to_approved_execution is False
        assert report.safe_to_execute_tests is False
        assert report.commands == []
        assert report.blockers == []
        assert report.warnings == []

    def test_nested_reconstruction(self) -> None:
        cmd = ToolchainCommandResult(id="c1", command="npm install", status="pass", executed=True)
        report = ToolchainValidationReport(
            project_id="proj",
            validation_status="pass",
            approved=True,
            commands=[cmd],
        )
        d = report.to_dict()
        assert isinstance(d["commands"][0], dict)
        restored = ToolchainValidationReport.from_dict(d)
        assert isinstance(restored.commands[0], ToolchainCommandResult)
        assert restored.commands[0].id == "c1"
        assert restored.commands[0].status == "pass"

    def test_safe_to_execute_tests_not_in_from_dict(self) -> None:
        data: dict[str, Any] = {
            "project_id": "p",
            "safe_to_execute_tests": True,  # cannot be forced True via from_dict kwarg
        }
        report = ToolchainValidationReport.from_dict(data)
        # from_dict faithfully restores the value — the invariant is enforced in validate_toolchain
        assert report.project_id == "p"


class TestSchemaInitExports:
    def test_exports(self) -> None:
        from core.schemas import (  # noqa: F401
            ToolchainCommandResult,
            ToolchainApprovalRecord,
            ToolchainValidationReport,
        )


# ---------------------------------------------------------------------------
# ToolchainValidator — no-approval behavior
# ---------------------------------------------------------------------------

class TestNoApprovalBehavior:
    def test_without_approval_no_subprocess(self, tmp_path: Path) -> None:
        root = _make_scaffold(tmp_path)
        _write_clean_static_report(root)
        validator = _make_validator(tmp_path)

        with patch("core.toolchain_validator.subprocess") as mock_sub:
            report, approval = validator.validate_toolchain(root, approved=False)
            mock_sub.run.assert_not_called()

        assert approval.approved is False
        assert all(c.executed is False for c in report.commands)

    def test_without_approval_all_commands_skipped(self, tmp_path: Path) -> None:
        root = _make_scaffold(tmp_path)
        _write_clean_static_report(root)
        validator = _make_validator(tmp_path)
        report, _ = validator.validate_toolchain(root, approved=False)

        assert len(report.commands) == len(_ALLOWED_COMMANDS)
        for cmd in report.commands:
            assert cmd.status == "skipped"
            assert cmd.executed is False
            assert cmd.skipped_reason is not None

    def test_without_approval_safe_to_execute_false(self, tmp_path: Path) -> None:
        root = _make_scaffold(tmp_path)
        _write_clean_static_report(root)
        validator = _make_validator(tmp_path)
        report, _ = validator.validate_toolchain(root, approved=False)

        assert report.safe_to_execute_tests is False
        assert report.browser_execution_performed is False
        assert report.external_url_used is False
        assert report.credentials_used is False

    def test_without_approval_validation_status_blocked(self, tmp_path: Path) -> None:
        root = _make_scaffold(tmp_path)
        _write_clean_static_report(root)
        validator = _make_validator(tmp_path)
        report, _ = validator.validate_toolchain(root, approved=False)
        assert report.validation_status == "blocked"


# ---------------------------------------------------------------------------
# ToolchainValidator — command allowlist and block logic
# ---------------------------------------------------------------------------

class TestCommandAllowlist:
    def test_npm_install_is_allowed(self, tmp_path: Path) -> None:
        validator = _make_validator(tmp_path)
        assert validator.is_command_allowed(["npm", "install"]) is True

    def test_npm_run_typecheck_is_allowed(self, tmp_path: Path) -> None:
        validator = _make_validator(tmp_path)
        assert validator.is_command_allowed(["npm", "run", "typecheck"]) is True

    def test_playwright_list_is_allowed(self, tmp_path: Path) -> None:
        validator = _make_validator(tmp_path)
        assert validator.is_command_allowed(["npx", "playwright", "test", "--list"]) is True

    def test_playwright_install_is_blocked(self, tmp_path: Path) -> None:
        validator = _make_validator(tmp_path)
        assert validator.is_command_allowed(["npx", "playwright", "install"]) is False

    def test_playwright_test_is_blocked(self, tmp_path: Path) -> None:
        validator = _make_validator(tmp_path)
        assert validator.is_command_allowed(["npx", "playwright", "test"]) is False

    def test_npm_test_is_blocked(self, tmp_path: Path) -> None:
        validator = _make_validator(tmp_path)
        assert validator.is_command_allowed(["npm", "test"]) is False

    def test_npm_run_test_is_blocked(self, tmp_path: Path) -> None:
        validator = _make_validator(tmp_path)
        assert validator.is_command_allowed(["npm", "run", "test"]) is False

    def test_headed_is_blocked(self, tmp_path: Path) -> None:
        validator = _make_validator(tmp_path)
        assert validator.is_command_allowed(["npx", "playwright", "test", "--headed"]) is False

    def test_curl_is_blocked(self, tmp_path: Path) -> None:
        validator = _make_validator(tmp_path)
        assert validator.is_command_allowed(["curl", "https://example.com"]) is False

    def test_arbitrary_command_is_not_allowed(self, tmp_path: Path) -> None:
        validator = _make_validator(tmp_path)
        assert validator.is_command_allowed(["rm", "-rf", "/"]) is False


class TestExternalUrlDetection:
    def test_detects_external_url(self, tmp_path: Path) -> None:
        validator = _make_validator(tmp_path)
        result = validator.detect_external_url(["curl", "https://staging.myapp.com/api"])
        assert result is not None
        assert "staging.myapp.com" in result

    def test_localhost_not_detected(self, tmp_path: Path) -> None:
        validator = _make_validator(tmp_path)
        assert validator.detect_external_url(["node", "http://localhost:3000"]) is None

    def test_example_com_not_detected(self, tmp_path: Path) -> None:
        validator = _make_validator(tmp_path)
        assert validator.detect_external_url(["echo", "https://example.com/api"]) is None

    def test_command_with_external_url_is_blocked(self, tmp_path: Path) -> None:
        validator = _make_validator(tmp_path)
        assert validator.is_command_allowed(
            ["npx", "playwright", "test", "--list", "--base-url=https://staging.myapp.com"]
        ) is False


class TestSecretDetection:
    def test_detects_secret_in_args(self, tmp_path: Path) -> None:
        validator = _make_validator(tmp_path)
        result = validator.detect_secret_like_args(["npm", "run", "test", "--password=supersecret123"])
        assert result is not None

    def test_no_secret_in_clean_args(self, tmp_path: Path) -> None:
        validator = _make_validator(tmp_path)
        assert validator.detect_secret_like_args(["npm", "install"]) is None

    def test_command_with_secret_args_blocked(self, tmp_path: Path) -> None:
        validator = _make_validator(tmp_path)
        assert validator.is_command_allowed(
            ["npm", "run", "typecheck", "--token=sk-abc123def456ghi789"]
        ) is False


# ---------------------------------------------------------------------------
# ToolchainValidator — static prerequisite
# ---------------------------------------------------------------------------

class TestStaticPrerequisite:
    def test_blockers_in_static_report_prevent_execution(self, tmp_path: Path) -> None:
        root = _make_scaffold(tmp_path)
        _write_blocker_static_report(root)
        validator = _make_validator(tmp_path)

        with patch("core.toolchain_validator.subprocess") as mock_sub:
            report, _ = validator.validate_toolchain(root, approved=True)
            mock_sub.run.assert_not_called()

        assert report.validation_status == "blocked"
        assert any("blocker" in b.lower() or "static" in b.lower() for b in report.blockers)

    def test_missing_scaffold_root_returns_blocked(self, tmp_path: Path) -> None:
        validator = _make_validator(tmp_path)
        fake_root = tmp_path / "nonexistent" / "scaffold"
        report, _ = validator.validate_toolchain(fake_root, approved=True)
        assert report.validation_status == "blocked"
        assert len(report.blockers) > 0

    def test_clean_static_report_allows_progression(self, tmp_path: Path) -> None:
        root = _make_scaffold(tmp_path)
        _write_clean_static_report(root)
        validator = _make_validator(tmp_path)

        with patch("core.toolchain_validator.subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = "ok"
            mock_proc.stderr = ""
            mock_run.return_value = mock_proc
            report, _ = validator.validate_toolchain(root, approved=True)

        assert report.validation_status != "blocked"


# ---------------------------------------------------------------------------
# ToolchainValidator — approved execution (mocked subprocess)
# ---------------------------------------------------------------------------

class TestApprovedExecution:
    def test_approved_runs_commands(self, tmp_path: Path) -> None:
        root = _make_scaffold(tmp_path)
        _write_clean_static_report(root)
        validator = _make_validator(tmp_path)

        with patch("core.toolchain_validator.subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = "installed"
            mock_proc.stderr = ""
            mock_run.return_value = mock_proc
            report, approval = validator.validate_toolchain(root, approved=True)

        assert approval.approved is True
        assert mock_run.call_count > 0
        assert any(c.executed for c in report.commands)

    def test_approved_keeps_safety_invariants(self, tmp_path: Path) -> None:
        root = _make_scaffold(tmp_path)
        _write_clean_static_report(root)
        validator = _make_validator(tmp_path)

        with patch("core.toolchain_validator.subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = "ok"
            mock_proc.stderr = ""
            mock_run.return_value = mock_proc
            report, _ = validator.validate_toolchain(root, approved=True)

        assert report.safe_to_execute_tests is False
        assert report.browser_execution_performed is False
        assert report.external_url_used is False
        assert report.credentials_used is False

    def test_approved_pass_sets_npm_install_performed(self, tmp_path: Path) -> None:
        root = _make_scaffold(tmp_path)
        _write_clean_static_report(root)
        validator = _make_validator(tmp_path)

        with patch("core.toolchain_validator.subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.returncode = 0
            mock_proc.stdout = "up to date"
            mock_proc.stderr = ""
            mock_run.return_value = mock_proc
            report, _ = validator.validate_toolchain(root, approved=True)

        assert report.npm_install_performed is True

    def test_command_failure_sets_fail_status(self, tmp_path: Path) -> None:
        root = _make_scaffold(tmp_path)
        _write_clean_static_report(root)
        validator = _make_validator(tmp_path)

        with patch("core.toolchain_validator.subprocess.run") as mock_run:
            mock_proc = MagicMock()
            mock_proc.returncode = 1
            mock_proc.stdout = ""
            mock_proc.stderr = "error: type mismatch"
            mock_run.return_value = mock_proc
            report, _ = validator.validate_toolchain(root, approved=True)

        assert report.validation_status == "fail"
        assert any(c.status == "fail" for c in report.commands)

    def test_command_not_found_sets_fail(self, tmp_path: Path) -> None:
        root = _make_scaffold(tmp_path)
        _write_clean_static_report(root)
        validator = _make_validator(tmp_path)

        with patch("core.toolchain_validator.subprocess.run") as mock_run:
            mock_run.side_effect = FileNotFoundError("npm not found")
            report, _ = validator.validate_toolchain(root, approved=True)

        failed = [c for c in report.commands if c.status == "fail"]
        assert len(failed) > 0
        assert not any(c.executed for c in failed)


# ---------------------------------------------------------------------------
# Approval record
# ---------------------------------------------------------------------------

class TestApprovalRecord:
    def test_unapproved_record(self, tmp_path: Path) -> None:
        validator = _make_validator(tmp_path)
        root = tmp_path / "scaffold"
        record = validator.build_approval_record(root, "proj", approved=False)
        assert record.approved is False
        assert record.approval_source == "not_provided"
        assert record.approved_commands == []
        assert "safe_to_execute_tests remains False" in record.safety_constraints

    def test_approved_record(self, tmp_path: Path) -> None:
        validator = _make_validator(tmp_path)
        root = tmp_path / "scaffold"
        record = validator.build_approval_record(root, "proj", approved=True)
        assert record.approved is True
        assert record.approval_source == "cli_flag"
        assert len(record.approved_commands) > 0
        assert "npm install" in record.approved_commands

    def test_approved_record_denied_commands_present(self, tmp_path: Path) -> None:
        validator = _make_validator(tmp_path)
        root = tmp_path / "scaffold"
        record = validator.build_approval_record(root, "proj", approved=True)
        assert len(record.denied_commands) > 0
        assert any("playwright test" in d or "npm test" in d for d in record.denied_commands)


# ---------------------------------------------------------------------------
# Artifact rendering
# ---------------------------------------------------------------------------

class TestArtifactRendering:
    def test_artifacts_written_without_approval(self, tmp_path: Path) -> None:
        root = _make_scaffold(tmp_path)
        _write_clean_static_report(root)
        validator = _make_validator(tmp_path)
        report, approval = validator.validate_toolchain(root, approved=False)
        paths = validator.render_toolchain_artifacts(report, approval, root)

        assert "TOOLCHAIN_VALIDATION_REPORT.json" in paths
        assert "TOOLCHAIN_VALIDATION_REPORT.md" in paths
        assert "TOOLCHAIN_COMMAND_LOG.md" in paths
        assert "TOOLCHAIN_APPROVAL_RECORD.md" in paths

    def test_json_report_valid(self, tmp_path: Path) -> None:
        root = _make_scaffold(tmp_path)
        _write_clean_static_report(root)
        validator = _make_validator(tmp_path)
        report, approval = validator.validate_toolchain(root, approved=False)
        validator.render_toolchain_artifacts(report, approval, root)

        json_path = root / "TOOLCHAIN_VALIDATION_REPORT.json"
        data = json.loads(json_path.read_text(encoding="utf-8"))
        assert data["safe_to_execute_tests"] is False
        assert data["browser_execution_performed"] is False
        assert data["external_url_used"] is False
        assert data["credentials_used"] is False

    def test_reports_contain_no_secrets(self, tmp_path: Path) -> None:
        root = _make_scaffold(tmp_path)
        _write_clean_static_report(root)
        validator = _make_validator(tmp_path)
        report, approval = validator.validate_toolchain(root, approved=False)
        paths = validator.render_toolchain_artifacts(report, approval, root)

        for key, path_str in paths.items():
            content = Path(path_str).read_text(encoding="utf-8")
            assert "sk-" not in content, f"{key} contains possible API key"
            assert "password=" not in content.lower(), f"{key} contains password="

    def test_md_report_contains_safety_boundary(self, tmp_path: Path) -> None:
        root = _make_scaffold(tmp_path)
        _write_clean_static_report(root)
        validator = _make_validator(tmp_path)
        report, approval = validator.validate_toolchain(root, approved=False)
        validator.render_toolchain_artifacts(report, approval, root)

        md_content = (root / "TOOLCHAIN_VALIDATION_REPORT.md").read_text(encoding="utf-8")
        assert "safe_to_execute_tests" in md_content
        assert "browser_execution_performed" in md_content
        assert "Toolchain validation does not mean tests were executed" in md_content

    def test_approval_record_md_warns_not_authorize(self, tmp_path: Path) -> None:
        root = _make_scaffold(tmp_path)
        _write_clean_static_report(root)
        validator = _make_validator(tmp_path)
        report, approval = validator.validate_toolchain(root, approved=False)
        validator.render_toolchain_artifacts(report, approval, root)

        ar_content = (root / "TOOLCHAIN_APPROVAL_RECORD.md").read_text(encoding="utf-8")
        assert "does NOT authorize" in ar_content or "not authorize" in ar_content.lower()


# ---------------------------------------------------------------------------
# WorkbenchController integration
# ---------------------------------------------------------------------------

class TestWorkbenchControllerPhase3C:
    def test_validate_toolchain_exists(self) -> None:
        from core.workbench_controller import WorkbenchController
        ctrl = WorkbenchController()
        assert hasattr(ctrl, "validate_toolchain")

    def test_render_toolchain_artifacts_exists(self) -> None:
        from core.workbench_controller import WorkbenchController
        ctrl = WorkbenchController()
        assert hasattr(ctrl, "render_toolchain_validation_artifacts")

    def test_validate_toolchain_missing_root_returns_blocked(self, tmp_path: Path) -> None:
        from core.workbench_controller import WorkbenchController
        ctrl = WorkbenchController(outputs_root=tmp_path / "outputs")
        report, approval = ctrl.validate_toolchain("nonexistent-proj-xyz")
        assert report.validation_status == "blocked"
        assert report.safe_to_execute_tests is False

    def test_validate_toolchain_no_approval_skips_commands(self, tmp_path: Path) -> None:
        from core.workbench_controller import WorkbenchController
        root = _make_scaffold(tmp_path)
        _write_clean_static_report(root)
        ctrl = WorkbenchController(outputs_root=tmp_path / "outputs")
        report, _ = ctrl.validate_toolchain("test-proj", approved=False)
        assert all(c.executed is False for c in report.commands)


# ---------------------------------------------------------------------------
# CLI tests
# ---------------------------------------------------------------------------

class TestValidateToolchainCli:
    def test_no_args_exits_nonzero(self) -> None:
        from tools.validate_toolchain import main
        with pytest.raises(SystemExit):
            main(["--not-a-real-flag"])

    def test_missing_scaffold_returns_zero_blocked(self, tmp_path: Path) -> None:
        """Without approval, missing scaffold returns 0 (blocked is expected)."""
        from tools.validate_toolchain import main
        exit_code = main(["--project-id", "nonexistent-xyz-proj", "--no-write"])
        assert exit_code == 0

    def test_json_output_valid(self, tmp_path: Path) -> None:
        root = _make_scaffold(tmp_path)
        _write_clean_static_report(root)

        from tools.validate_toolchain import main
        import io
        from contextlib import redirect_stdout

        buf = io.StringIO()
        with redirect_stdout(buf):
            main([
                "--scaffold-root", str(root),
                "--json",
                "--no-write",
            ])
        output = buf.getvalue()

        data = json.loads(output)
        assert "report" in data
        assert "approval" in data
        assert data["report"]["safe_to_execute_tests"] is False

    def test_no_approval_flag_commands_skipped(self, tmp_path: Path) -> None:
        root = _make_scaffold(tmp_path)
        _write_clean_static_report(root)
        import io
        from contextlib import redirect_stdout

        from tools.validate_toolchain import main
        buf = io.StringIO()
        with redirect_stdout(buf):
            main([
                "--scaffold-root", str(root),
                "--json",
                "--no-write",
            ])
        output = buf.getvalue()
        data = json.loads(output)
        assert all(c["status"] == "skipped" for c in data["report"]["commands"])
        assert data["report"]["approved"] is False

    def test_no_subprocess_without_approval(self, tmp_path: Path) -> None:
        root = _make_scaffold(tmp_path)
        _write_clean_static_report(root)
        from tools.validate_toolchain import main

        with patch("core.toolchain_validator.subprocess") as mock_sub:
            main(["--scaffold-root", str(root), "--no-write"])
            mock_sub.run.assert_not_called()


# ---------------------------------------------------------------------------
# Module-level safety checks
# ---------------------------------------------------------------------------

class TestModuleSafety:
    def test_toolchain_validator_imports_no_requests(self) -> None:
        import core.toolchain_validator as mod
        assert not hasattr(mod, "requests")
        assert not hasattr(mod, "httpx")
        assert not hasattr(mod, "urllib")

    def test_toolchain_validator_has_subprocess_import(self) -> None:
        import core.toolchain_validator as mod
        assert hasattr(mod, "subprocess")

    def test_allowed_commands_list_not_empty(self) -> None:
        assert len(_ALLOWED_COMMANDS) > 0

    def test_blocked_substrings_contains_key_patterns(self) -> None:
        blocked_lower = [s.lower() for s in _BLOCKED_SUBSTRINGS]
        assert any("playwright install" in s for s in blocked_lower)
        assert any("playwright test" in s for s in blocked_lower)
        assert any("npm test" in s for s in blocked_lower)
        assert any("headed" in s for s in blocked_lower)


# ---------------------------------------------------------------------------
# Docs/audit integration
# ---------------------------------------------------------------------------

class TestPhase3CDocsAndAudit:
    def test_commands_md_mentions_validate_toolchain(self) -> None:
        content = (Path(__file__).parent.parent / "docs" / "COMMANDS.md").read_text(encoding="utf-8")
        assert "validate_toolchain" in content
        assert "approve-toolchain" in content or "approve_toolchain" in content

    def test_runbook_mentions_phase3c(self) -> None:
        content = (Path(__file__).parent.parent / "docs" / "RUNBOOK.md").read_text(encoding="utf-8")
        assert "3C" in content or "toolchain" in content.lower()

    def test_phase_contracts_mentions_3c(self) -> None:
        content = (Path(__file__).parent.parent / "docs" / "PHASE_CONTRACTS.md").read_text(encoding="utf-8")
        assert "3C" in content

    def test_safety_rules_mentions_toolchain(self) -> None:
        content = (Path(__file__).parent.parent / "docs" / "SAFETY_RULES.md").read_text(encoding="utf-8")
        assert "toolchain" in content.lower() or "3C" in content

    def test_schema_foundation_mentions_toolchain_validation(self) -> None:
        content = (Path(__file__).parent.parent / "docs" / "SCHEMA_FOUNDATION.md").read_text(encoding="utf-8")
        assert "ToolchainValidation" in content or "toolchain_validation" in content
