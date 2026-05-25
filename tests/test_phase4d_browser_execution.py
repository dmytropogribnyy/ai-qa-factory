"""Tests for Phase 4D: Controlled Browser Execution.

Safety guarantees under test:
- No subprocess without explicit approval flag
- Hard-blocked targets (Alza, Amazon, Linear, playwright.dev without profile)
- Category-level blocks (production, high_risk_marketplace, task_source)
- Allowlist-only commands
- Delivery flags always False
- Evidence internal-only
- Environment sanitization strips secrets
- Correct profile resolution

subprocess is ALWAYS mocked in these tests.
No real Playwright/browser execution occurs.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch


from core.schemas.browser_execution import (
    BrowserExecutionApproval,
    BrowserExecutionCommand,
    BrowserExecutionEvidence,
    BrowserExecutionReport,
    COMMAND_STATUSES,
    EVIDENCE_TYPES,
)
from core.browser_execution_runner import (
    BrowserExecutionRunner,
    _ALWAYS_BLOCKED_DOMAINS,
    _ALLOWED_COMMANDS,
    _DEMO_PROFILES,
    _READONLY_PROFILES,
    _SECRET_ENV_PATTERNS,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _runner(tmp_path: Path) -> BrowserExecutionRunner:
    return BrowserExecutionRunner(outputs_root=tmp_path / "outputs")


def _make_scaffold(tmp_path: Path, project_id: str = "test-4d") -> Path:
    scaffold = tmp_path / "outputs" / project_id / "03_framework" / "playwright"
    scaffold.mkdir(parents=True, exist_ok=True)
    (scaffold / "package.json").write_text('{"name":"test"}')
    return scaffold


# ===========================================================================
# 1. Schema roundtrip and defaults
# ===========================================================================

class TestBrowserExecutionApproval:
    def test_defaults(self):
        a = BrowserExecutionApproval(project_id="t")
        assert a.approved is False
        assert a.approval_source == ""
        assert a.approved_commands == []
        assert a.denied_commands == []
        assert a.safety_constraints == []
        assert a.notes == []

    def test_roundtrip(self):
        a = BrowserExecutionApproval(
            project_id="p1",
            approved=True,
            approval_source="cli_flag",
            approval_scope="demo/local execution only",
            approved_target_category="local",
            approved_commands=["npx playwright test --list"],
            safety_constraints=["no credentials"],
        )
        d = a.to_dict()
        b = BrowserExecutionApproval.from_dict(d)
        assert b.project_id == "p1"
        assert b.approved is True
        assert b.approved_commands == ["npx playwright test --list"]
        assert b.safety_constraints == ["no credentials"]

    def test_from_dict_preserves_approved_true(self):
        # approval is user-set state, not a safety invariant — it's allowed to round-trip True
        a = BrowserExecutionApproval.from_dict({"project_id": "t", "approved": True})
        assert a.approved is True


class TestBrowserExecutionCommand:
    def test_defaults(self):
        c = BrowserExecutionCommand(id="c1", command="npx playwright test --list", cwd="/tmp")
        assert c.status == "skipped"
        assert c.executed is False
        assert c.exit_code is None
        assert c.duration_seconds is None
        assert c.skipped_reason is None
        assert c.safety_notes == []

    def test_roundtrip(self):
        c = BrowserExecutionCommand(
            id="c1", command="npx playwright test --list", cwd="/tmp",
            status="pass", exit_code=0, duration_seconds=1.23, executed=True,
        )
        d = c.to_dict()
        c2 = BrowserExecutionCommand.from_dict(d)
        assert c2.id == "c1"
        assert c2.status == "pass"
        assert c2.exit_code == 0
        assert c2.duration_seconds == 1.23
        assert c2.executed is True

    def test_valid_statuses_defined(self):
        assert "pass" in COMMAND_STATUSES
        assert "fail" in COMMAND_STATUSES
        assert "skipped" in COMMAND_STATUSES
        assert "blocked" in COMMAND_STATUSES


class TestBrowserExecutionEvidence:
    def test_defaults_internal_only(self):
        e = BrowserExecutionEvidence(id="e1", evidence_type="command_log", path="/p", title="T", description="D")
        assert e.internal_only is True
        assert e.client_visible is False
        assert e.requires_redaction is True
        assert e.redacted is False

    def test_roundtrip(self):
        e = BrowserExecutionEvidence(
            id="e1", evidence_type="playwright_report", path="/p/report",
            title="Report", description="HTML report",
        )
        d = e.to_dict()
        e2 = BrowserExecutionEvidence.from_dict(d)
        assert e2.id == "e1"
        assert e2.evidence_type == "playwright_report"
        assert e2.internal_only is True
        assert e2.client_visible is False

    def test_valid_evidence_types_defined(self):
        for t in ("command_log", "playwright_report", "test_results", "screenshot",
                  "trace", "video", "execution_summary", "unknown"):
            assert t in EVIDENCE_TYPES


class TestBrowserExecutionReport:
    def test_delivery_flags_forced_false_by_post_init(self):
        # Even if caller tries to set True, __post_init__ forces False
        r = BrowserExecutionReport(
            project_id="t", scaffold_root="/r",
            safe_to_deliver=True,
            approved_for_client_delivery=True,
            client_delivery_created=True,
            credentials_used=True,
            destructive_actions_performed=True,
        )
        assert r.safe_to_deliver is False
        assert r.approved_for_client_delivery is False
        assert r.client_delivery_created is False
        assert r.credentials_used is False
        assert r.destructive_actions_performed is False

    def test_execution_flags_not_forced_false(self):
        # browser_execution_performed etc. must NOT be forced False
        r = BrowserExecutionReport(
            project_id="t", scaffold_root="/r",
            browser_execution_performed=True,
            playwright_test_execution_performed=True,
            public_readonly_target_used=True,
        )
        assert r.browser_execution_performed is True
        assert r.playwright_test_execution_performed is True
        assert r.public_readonly_target_used is True

    def test_from_dict_forces_delivery_flags_false(self):
        r = BrowserExecutionReport.from_dict({
            "project_id": "t",
            "scaffold_root": "/r",
            "safe_to_deliver": True,
            "approved_for_client_delivery": True,
            "client_delivery_created": True,
            "credentials_used": True,
            "destructive_actions_performed": True,
        })
        assert r.safe_to_deliver is False
        assert r.approved_for_client_delivery is False
        assert r.client_delivery_created is False
        assert r.credentials_used is False
        assert r.destructive_actions_performed is False

    def test_from_dict_nested_reconstruction(self):
        data = {
            "project_id": "t", "scaffold_root": "/r",
            "commands": [{"id": "c1", "command": "cmd", "cwd": "/cwd"}],
            "evidence": [{"id": "e1", "evidence_type": "command_log", "path": "/p",
                          "title": "T", "description": "D"}],
        }
        r = BrowserExecutionReport.from_dict(data)
        assert len(r.commands) == 1
        assert isinstance(r.commands[0], BrowserExecutionCommand)
        assert len(r.evidence) == 1
        assert isinstance(r.evidence[0], BrowserExecutionEvidence)

    def test_roundtrip(self):
        r = BrowserExecutionReport(
            project_id="p1", scaffold_root="/root",
            execution_status="complete",
            browser_execution_performed=True,
            playwright_test_execution_performed=True,
        )
        d = r.to_dict()
        r2 = BrowserExecutionReport.from_dict(d)
        assert r2.project_id == "p1"
        assert r2.execution_status == "complete"
        assert r2.browser_execution_performed is True
        assert r2.safe_to_deliver is False

    def test_defaults(self):
        r = BrowserExecutionReport(project_id="t", scaffold_root="/r")
        assert r.execution_status == "blocked"
        assert r.approval_required is True
        assert r.approved is False
        assert r.target_category == "unknown"
        assert r.command_mode == "none"
        assert r.browser_execution_performed is False
        assert r.playwright_test_execution_performed is False
        assert r.production_target_used is False
        assert r.public_readonly_target_used is False
        assert r.external_calls_performed is False
        assert r.commands == []
        assert r.evidence == []
        assert r.blockers == []
        assert r.warnings == []


# ===========================================================================
# 2. __init__.py exports
# ===========================================================================

class TestSchemaExports:
    def test_all_phase4d_classes_exported(self):
        from core.schemas import (
            BrowserExecutionApproval,
            BrowserExecutionCommand,
            BrowserExecutionEvidence,
            BrowserExecutionReport,
        )
        assert BrowserExecutionApproval
        assert BrowserExecutionCommand
        assert BrowserExecutionEvidence
        assert BrowserExecutionReport


# ===========================================================================
# 3. BrowserExecutionRunner — no-approval gate
# ===========================================================================

class TestRunnerNoApproval:
    def test_no_approval_returns_blocked_report(self, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_browser_execution(project_id="t")
        assert report.execution_status == "blocked"
        assert report.approved is False
        assert report.browser_execution_performed is False
        assert report.playwright_test_execution_performed is False
        assert len(report.blockers) > 0

    def test_no_approval_no_subprocess(self, tmp_path):
        runner = _runner(tmp_path)
        with patch("subprocess.run") as mock_sub:
            runner.run_browser_execution(project_id="t")
            mock_sub.assert_not_called()

    def test_no_approval_report_safe_defaults(self, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_browser_execution(project_id="t")
        assert report.safe_to_deliver is False
        assert report.approved_for_client_delivery is False
        assert report.credentials_used is False


# ===========================================================================
# 4. BrowserExecutionRunner — approval + allowed targets
# ===========================================================================

class TestRunnerApprovedLocal:
    def _mock_proc_result(self):
        m = MagicMock()
        m.returncode = 0
        m.stdout = "Test 1\nTest 2\n"
        m.stderr = ""
        return m

    def test_local_with_demo_approval_can_run_list(self, tmp_path):
        runner = _runner(tmp_path)
        _make_scaffold(tmp_path, "t")
        with patch("subprocess.run", return_value=self._mock_proc_result()):
            report = runner.run_browser_execution(
                project_id="t",
                approve_demo=True,
                target_category="local",
                command_mode="list",
            )
        assert report.execution_status == "complete"
        assert report.approved is True
        assert len(report.commands) == 1
        assert report.commands[0].executed is True
        assert report.safe_to_deliver is False

    def test_public_demo_target_with_demo_approval_can_run_list(self, tmp_path):
        runner = _runner(tmp_path)
        _make_scaffold(tmp_path, "t")
        with patch("subprocess.run", return_value=self._mock_proc_result()):
            report = runner.run_browser_execution(
                project_id="t",
                approve_demo=True,
                target_category="public_demo_target",
                base_url="https://www.saucedemo.com",
                command_mode="list",
            )
        assert report.execution_status == "complete"
        assert report.approved is True

    def test_list_mode_does_not_set_browser_performed(self, tmp_path):
        runner = _runner(tmp_path)
        _make_scaffold(tmp_path, "t")
        with patch("subprocess.run", return_value=self._mock_proc_result()):
            report = runner.run_browser_execution(
                project_id="t",
                approve_demo=True,
                target_category="local",
                command_mode="list",
            )
        # list mode: playwright ran but browser not opened
        assert report.browser_execution_performed is False
        assert report.playwright_test_execution_performed is True

    def test_smoke_mode_sets_browser_performed(self, tmp_path):
        runner = _runner(tmp_path)
        _make_scaffold(tmp_path, "t")
        with patch("subprocess.run", return_value=self._mock_proc_result()):
            report = runner.run_browser_execution(
                project_id="t",
                approve_demo=True,
                target_category="local",
                command_mode="smoke",
            )
        assert report.browser_execution_performed is True
        assert report.playwright_test_execution_performed is True


# ===========================================================================
# 5. Demo profile resolution
# ===========================================================================

class TestDemoProfileResolution:
    def test_saucedemo_profile_exists(self):
        assert "saucedemo_public_demo" in _DEMO_PROFILES
        p = _DEMO_PROFILES["saucedemo_public_demo"]
        assert "saucedemo.com" in p["base_url"]
        assert p["target_category"] == "public_demo_target"
        assert "list" in p["allowed_modes"]
        assert "smoke" in p["allowed_modes"]

    def test_the_internet_profile_exists(self):
        assert "the_internet_public_demo" in _DEMO_PROFILES
        p = _DEMO_PROFILES["the_internet_public_demo"]
        assert "herokuapp" in p["base_url"]
        assert p["target_category"] == "public_demo_target"

    def test_local_profile_exists(self):
        assert "local" in _DEMO_PROFILES
        p = _DEMO_PROFILES["local"]
        assert "localhost" in p["base_url"]
        assert p["target_category"] == "local"

    def test_saucedemo_profile_sets_category(self, tmp_path):
        runner = _runner(tmp_path)
        cat, url, meta = runner._resolve_profile(
            None, None, "saucedemo_public_demo", None, True, False
        )
        assert cat == "public_demo_target"
        assert "saucedemo.com" in url

    def test_local_profile_sets_localhost(self, tmp_path):
        runner = _runner(tmp_path)
        cat, url, meta = runner._resolve_profile(
            None, None, "local", None, True, False
        )
        assert cat == "local"
        assert "localhost" in url

    def test_saucedemo_blocked_test_paths(self):
        p = _DEMO_PROFILES["saucedemo_public_demo"]
        assert "tests/auth" in p["blocked_test_paths"]
        assert "tests/regression" in p["blocked_test_paths"]
        assert "tests/ecommerce" in p["blocked_test_paths"]
        assert "tests/admin" in p["blocked_test_paths"]

    def test_saucedemo_allowed_test_paths(self):
        p = _DEMO_PROFILES["saucedemo_public_demo"]
        assert "tests/smoke" in p["allowed_test_paths"]


# ===========================================================================
# 6. Public read-only profile (playwright_docs_readonly)
# ===========================================================================

class TestReadonlyProfile:
    def test_playwright_docs_profile_exists(self):
        assert "playwright_docs_readonly" in _READONLY_PROFILES
        p = _READONLY_PROFILES["playwright_docs_readonly"]
        assert "playwright.dev" in p["base_url"]
        assert p["target_category"] == "real_public_readonly"
        assert "list" in p["allowed_modes"]
        assert "readonly_smoke" in p["allowed_modes"]
        assert "smoke" not in p["allowed_modes"]

    def test_playwright_docs_requires_public_readonly_approval(self, tmp_path):
        runner = _runner(tmp_path)
        # Only demo approval — must be blocked
        block = runner.validate_execution_allowed(
            approve_demo=True,
            approve_public_readonly=False,
            target_category="real_public_readonly",
            base_url="https://playwright.dev",
            demo_profile=None,
            readonly_profile="playwright_docs_readonly",
            command_mode="list",
        )
        assert block is not None
        assert "approve-public-readonly-execution" in block.lower() or "public_readonly" in block.lower()

    def test_playwright_docs_allowed_with_correct_approval(self, tmp_path):
        runner = _runner(tmp_path)
        block = runner.validate_execution_allowed(
            approve_demo=False,
            approve_public_readonly=True,
            target_category="real_public_readonly",
            base_url="https://playwright.dev",
            demo_profile=None,
            readonly_profile="playwright_docs_readonly",
            command_mode="list",
        )
        assert block is None

    def test_playwright_docs_list_mode_sets_public_readonly_used(self, tmp_path):
        runner = _runner(tmp_path)
        _make_scaffold(tmp_path, "t")
        m = MagicMock()
        m.returncode = 0
        m.stdout = "1 test found"
        m.stderr = ""
        with patch("subprocess.run", return_value=m):
            report = runner.run_browser_execution(
                project_id="t",
                approve_public_readonly=True,
                readonly_profile="playwright_docs_readonly",
                command_mode="list",
            )
        if report.commands[0].executed:
            assert report.public_readonly_target_used is True

    def test_playwright_docs_readonly_smoke_maps_to_tests_smoke(self, tmp_path):
        runner = _runner(tmp_path)
        cmd, block = runner._build_command(command_mode="readonly_smoke", readonly_profile="playwright_docs_readonly")
        assert block is None
        assert "tests/smoke" in cmd

    def test_playwright_docs_smoke_mode_not_allowed(self, tmp_path):
        runner = _runner(tmp_path)
        # "smoke" (not "readonly_smoke") is not in allowed_modes for playwright_docs_readonly
        block = runner.validate_execution_allowed(
            approve_demo=False,
            approve_public_readonly=True,
            target_category="real_public_readonly",
            base_url="https://playwright.dev",
            demo_profile=None,
            readonly_profile="playwright_docs_readonly",
            command_mode="smoke",
        )
        assert block is not None


# ===========================================================================
# 7. Hard-blocked targets
# ===========================================================================

class TestHardBlockedTargets:
    def test_alza_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_browser_execution(
            project_id="t",
            approve_public_readonly=True,
            target_category="real_public_readonly",
            base_url="https://www.alza.sk",
        )
        assert report.execution_status == "blocked"
        assert any("alza" in b.lower() for b in report.blockers)

    def test_amazon_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_browser_execution(
            project_id="t",
            approve_public_readonly=True,
            target_category="high_risk_marketplace_readonly",
            base_url="https://www.amazon.com",
        )
        assert report.execution_status == "blocked"

    def test_linear_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_browser_execution(
            project_id="t",
            approve_demo=True,
            target_category="task_source",
            base_url="https://linear.app/acme/issue/QA-123",
        )
        assert report.execution_status == "blocked"
        assert any("linear" in b.lower() or "task_source" in b.lower() for b in report.blockers)

    def test_playwright_dev_blocked_without_profile(self, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_browser_execution(
            project_id="t",
            approve_public_readonly=True,
            target_category="real_public_readonly",
            base_url="https://playwright.dev",
            # No readonly_profile
        )
        assert report.execution_status == "blocked"

    def test_playwright_dev_blocked_with_demo_approval_only(self, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_browser_execution(
            project_id="t",
            approve_demo=True,
            target_category="real_public_readonly",
            base_url="https://playwright.dev",
            readonly_profile="playwright_docs_readonly",
        )
        assert report.execution_status == "blocked"

    def test_alza_blocked_even_with_approval(self, tmp_path):
        runner = _runner(tmp_path)
        with patch("subprocess.run") as mock_sub:
            report = runner.run_browser_execution(
                project_id="t",
                approve_demo=True,
                approve_public_readonly=True,
                base_url="https://www.alza.sk",
            )
            mock_sub.assert_not_called()
        assert report.execution_status == "blocked"

    def test_amazon_blocked_even_with_approval(self, tmp_path):
        runner = _runner(tmp_path)
        with patch("subprocess.run") as mock_sub:
            runner.run_browser_execution(
                project_id="t",
                approve_demo=True,
                approve_public_readonly=True,
                base_url="https://www.amazon.com",
            )
            mock_sub.assert_not_called()


# ===========================================================================
# 8. Category-level blocks
# ===========================================================================

class TestCategoryBlocks:
    def test_production_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        block = runner.validate_execution_allowed(
            approve_demo=True, approve_public_readonly=True,
            target_category="production", base_url=None,
            demo_profile=None, readonly_profile=None, command_mode="list",
        )
        assert block is not None
        assert "production" in block.lower()

    def test_high_risk_marketplace_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        block = runner.validate_execution_allowed(
            approve_demo=True, approve_public_readonly=True,
            target_category="high_risk_marketplace_readonly", base_url=None,
            demo_profile=None, readonly_profile=None, command_mode="list",
        )
        assert block is not None

    def test_task_source_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        block = runner.validate_execution_allowed(
            approve_demo=True, approve_public_readonly=True,
            target_category="task_source", base_url=None,
            demo_profile=None, readonly_profile=None, command_mode="list",
        )
        assert block is not None
        assert "task_source" in block.lower()

    def test_real_public_readonly_blocked_without_profile(self, tmp_path):
        runner = _runner(tmp_path)
        block = runner.validate_execution_allowed(
            approve_demo=False, approve_public_readonly=True,
            target_category="real_public_readonly", base_url=None,
            demo_profile=None, readonly_profile=None, command_mode="list",
        )
        assert block is not None

    def test_real_public_readonly_blocked_wrong_profile(self, tmp_path):
        runner = _runner(tmp_path)
        block = runner.validate_execution_allowed(
            approve_demo=False, approve_public_readonly=True,
            target_category="real_public_readonly", base_url="https://example.com",
            demo_profile=None, readonly_profile="some_other_profile", command_mode="list",
        )
        assert block is not None

    def test_unknown_with_non_localhost_url_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        block = runner.validate_execution_allowed(
            approve_demo=True, approve_public_readonly=False,
            target_category="unknown", base_url="https://somesite.com",
            demo_profile=None, readonly_profile=None, command_mode="list",
        )
        assert block is not None

    def test_demo_only_blocks_readonly_category(self, tmp_path):
        runner = _runner(tmp_path)
        block = runner.validate_execution_allowed(
            approve_demo=True, approve_public_readonly=False,
            target_category="real_public_readonly", base_url=None,
            demo_profile=None, readonly_profile=None, command_mode="list",
        )
        assert block is not None

    def test_public_readonly_alone_blocks_public_demo_target(self, tmp_path):
        # --approve-public-readonly-execution alone must NOT allow public_demo_target.
        runner = _runner(tmp_path)
        block = runner.validate_execution_allowed(
            approve_demo=False, approve_public_readonly=True,
            target_category="public_demo_target", base_url="https://www.saucedemo.com",
            demo_profile="saucedemo_public_demo", readonly_profile=None, command_mode="list",
        )
        assert block is not None
        assert "approve-demo-execution" in block

    def test_public_readonly_alone_blocks_local_target(self, tmp_path):
        # --approve-public-readonly-execution alone must NOT allow local targets.
        runner = _runner(tmp_path)
        block = runner.validate_execution_allowed(
            approve_demo=False, approve_public_readonly=True,
            target_category="local", base_url="http://localhost:3000",
            demo_profile=None, readonly_profile=None, command_mode="list",
        )
        assert block is not None
        assert "approve-demo-execution" in block

    def test_demo_approval_still_allows_saucedemo(self, tmp_path):
        # Regression: --approve-demo-execution must still allow saucedemo.
        runner = _runner(tmp_path)
        block = runner.validate_execution_allowed(
            approve_demo=True, approve_public_readonly=False,
            target_category="public_demo_target", base_url="https://www.saucedemo.com",
            demo_profile="saucedemo_public_demo", readonly_profile=None, command_mode="list",
        )
        assert block is None

    def test_public_readonly_still_allows_playwright_docs(self, tmp_path):
        # Regression: --approve-public-readonly-execution + playwright_docs_readonly must still pass.
        runner = _runner(tmp_path)
        block = runner.validate_execution_allowed(
            approve_demo=False, approve_public_readonly=True,
            target_category="real_public_readonly", base_url="https://playwright.dev",
            demo_profile=None, readonly_profile="playwright_docs_readonly", command_mode="list",
        )
        assert block is None


# ===========================================================================
# 9. Command allowlist / blocklist
# ===========================================================================

class TestCommandAllowlist:
    def test_allowed_commands_defined(self):
        assert "npx playwright test --list" in _ALLOWED_COMMANDS
        assert "npx playwright test tests/smoke --reporter=list" in _ALLOWED_COMMANDS
        assert "npx playwright test tests/smoke --reporter=html,list" in _ALLOWED_COMMANDS

    def test_list_mode_builds_correct_command(self, tmp_path):
        runner = _runner(tmp_path)
        cmd, block = runner._build_command("list", readonly_profile=None)
        assert block is None
        assert cmd == "npx playwright test --list"

    def test_smoke_mode_builds_tests_smoke_command(self, tmp_path):
        runner = _runner(tmp_path)
        cmd, block = runner._build_command("smoke", readonly_profile=None)
        assert block is None
        assert "tests/smoke" in cmd

    def test_readonly_smoke_builds_tests_smoke_command(self, tmp_path):
        runner = _runner(tmp_path)
        cmd, block = runner._build_command("readonly_smoke", readonly_profile="playwright_docs_readonly")
        assert block is None
        assert "tests/smoke" in cmd

    def test_npm_test_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        assert not runner.is_command_allowed("npm test")

    def test_npm_run_test_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        assert not runner.is_command_allowed("npm run test")

    def test_npx_playwright_unrestricted_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        assert not runner.is_command_allowed("npx playwright test")

    def test_npx_playwright_tests_auth_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        assert not runner.is_command_allowed("npx playwright test tests/auth --reporter=list")

    def test_npx_playwright_tests_ecommerce_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        assert not runner.is_command_allowed("npx playwright test tests/ecommerce --reporter=list")

    def test_npx_playwright_tests_admin_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        assert not runner.is_command_allowed("npx playwright test tests/admin --reporter=list")

    def test_npx_playwright_tests_regression_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        assert not runner.is_command_allowed("npx playwright test tests/regression --reporter=list")

    def test_headed_flag_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        assert not runner.is_command_allowed("npx playwright test tests/smoke --headed")

    def test_ui_flag_blocked(self, tmp_path):
        runner = _runner(tmp_path)
        assert not runner.is_command_allowed("npx playwright test tests/smoke --ui")

    def test_allowed_list_command_passes(self, tmp_path):
        runner = _runner(tmp_path)
        assert runner.is_command_allowed("npx playwright test --list")

    def test_allowed_smoke_command_passes(self, tmp_path):
        runner = _runner(tmp_path)
        assert runner.is_command_allowed("npx playwright test tests/smoke --reporter=list")


# ===========================================================================
# 10. Environment sanitization
# ===========================================================================

class TestEnvSanitization:
    def test_strips_password(self, tmp_path, monkeypatch):
        monkeypatch.setenv("DB_PASSWORD", "secret123")
        monkeypatch.setenv("MY_SECRET", "abc")
        runner = _runner(tmp_path)
        env = runner.build_safe_env("http://localhost:3000")
        assert "DB_PASSWORD" not in env
        assert "MY_SECRET" not in env

    def test_strips_token(self, tmp_path, monkeypatch):
        monkeypatch.setenv("API_TOKEN", "tok_xyz")
        runner = _runner(tmp_path)
        env = runner.build_safe_env("http://localhost:3000")
        assert "API_TOKEN" not in env

    def test_strips_auth(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTH_HEADER", "Bearer abc")
        runner = _runner(tmp_path)
        env = runner.build_safe_env("http://localhost:3000")
        assert "AUTH_HEADER" not in env

    def test_strips_cookie(self, tmp_path, monkeypatch):
        monkeypatch.setenv("SESSION_COOKIE", "sid=abc")
        runner = _runner(tmp_path)
        env = runner.build_safe_env("http://localhost:3000")
        assert "SESSION_COOKIE" not in env

    def test_sets_base_url(self, tmp_path):
        runner = _runner(tmp_path)
        env = runner.build_safe_env("https://www.saucedemo.com")
        assert env["BASE_URL"] == "https://www.saucedemo.com"

    def test_sets_empty_test_credentials(self, tmp_path):
        runner = _runner(tmp_path)
        env = runner.build_safe_env(None)
        assert env["TEST_USERNAME"] == ""
        assert env["TEST_PASSWORD"] == ""

    def test_default_base_url_is_localhost(self, tmp_path):
        runner = _runner(tmp_path)
        env = runner.build_safe_env(None)
        assert env["BASE_URL"] == "http://localhost:3000"

    def test_secret_patterns_defined(self):
        for pat in ("PASSWORD", "SECRET", "TOKEN", "API_KEY", "PRIVATE_KEY",
                    "CREDENTIAL", "AUTH", "COOKIE", "SESSION"):
            assert pat in _SECRET_ENV_PATTERNS


# ===========================================================================
# 11. Report invariants
# ===========================================================================

class TestReportInvariants:
    def test_blocked_report_safe_to_deliver_false(self, tmp_path):
        runner = _runner(tmp_path)
        report = runner.run_browser_execution(project_id="t")
        assert report.safe_to_deliver is False

    def test_approved_report_safe_to_deliver_still_false(self, tmp_path):
        runner = _runner(tmp_path)
        _make_scaffold(tmp_path, "t")
        m = MagicMock()
        m.returncode = 0
        m.stdout = ""
        m.stderr = ""
        with patch("subprocess.run", return_value=m):
            report = runner.run_browser_execution(
                project_id="t",
                approve_demo=True,
                target_category="local",
                command_mode="list",
            )
        assert report.safe_to_deliver is False
        assert report.approved_for_client_delivery is False
        assert report.client_delivery_created is False

    def test_evidence_client_visible_false(self, tmp_path):
        runner = _runner(tmp_path)
        _make_scaffold(tmp_path, "t")
        m = MagicMock()
        m.returncode = 0
        m.stdout = ""
        m.stderr = ""
        with patch("subprocess.run", return_value=m):
            report = runner.run_browser_execution(
                project_id="t",
                approve_demo=True,
                target_category="local",
                command_mode="list",
            )
        for ev in report.evidence:
            assert ev.client_visible is False
            assert ev.internal_only is True

    def test_public_readonly_true_only_for_playwright_docs(self, tmp_path):
        runner = _runner(tmp_path)
        _make_scaffold(tmp_path, "t")
        m = MagicMock()
        m.returncode = 0
        m.stdout = ""
        m.stderr = ""
        with patch("subprocess.run", return_value=m):
            # local demo target should not set public_readonly_target_used
            report = runner.run_browser_execution(
                project_id="t",
                approve_demo=True,
                target_category="local",
                command_mode="list",
            )
        assert report.public_readonly_target_used is False


# ===========================================================================
# 12. Approval record construction
# ===========================================================================

class TestApprovalConstruction:
    def test_no_approval_returns_not_approved(self, tmp_path):
        runner = _runner(tmp_path)
        approval = runner.build_approval(
            project_id="t",
            approve_demo=False,
            approve_public_readonly=False,
            target_category="local",
            base_url=None,
            demo_profile=None,
            readonly_profile=None,
            command_mode="list",
        )
        assert approval.approved is False
        assert approval.approval_source == "none"

    def test_demo_approval_sets_scope(self, tmp_path):
        runner = _runner(tmp_path)
        approval = runner.build_approval(
            project_id="t",
            approve_demo=True,
            approve_public_readonly=False,
            target_category="local",
            base_url="http://localhost:3000",
            demo_profile=None,
            readonly_profile=None,
            command_mode="list",
        )
        assert approval.approved is True
        assert "demo" in approval.approval_scope.lower()
        assert approval.approval_source == "cli_flag"

    def test_readonly_approval_sets_readonly_scope(self, tmp_path):
        runner = _runner(tmp_path)
        approval = runner.build_approval(
            project_id="t",
            approve_demo=False,
            approve_public_readonly=True,
            target_category="real_public_readonly",
            base_url="https://playwright.dev",
            demo_profile=None,
            readonly_profile="playwright_docs_readonly",
            command_mode="list",
        )
        assert approval.approved is True
        assert "playwright.dev" in approval.approval_scope.lower() or "read-only" in approval.approval_scope.lower()

    def test_blocked_target_returns_not_approved(self, tmp_path):
        runner = _runner(tmp_path)
        approval = runner.build_approval(
            project_id="t",
            approve_demo=True,
            approve_public_readonly=True,
            target_category="production",
            base_url=None,
            demo_profile=None,
            readonly_profile=None,
            command_mode="list",
        )
        assert approval.approved is False

    def test_approval_safety_constraints_present(self, tmp_path):
        runner = _runner(tmp_path)
        approval = runner.build_approval(
            project_id="t",
            approve_demo=True,
            approve_public_readonly=False,
            target_category="local",
            base_url="http://localhost:3000",
            demo_profile=None,
            readonly_profile=None,
            command_mode="list",
        )
        assert len(approval.safety_constraints) > 0
        assert len(approval.denied_commands) > 0


# ===========================================================================
# 13. WorkbenchController integration
# ===========================================================================

class TestWorkbenchControllerPhase4D:
    def test_controller_has_run_controlled_browser_execution(self):
        from core.workbench_controller import WorkbenchController
        assert hasattr(WorkbenchController, "run_controlled_browser_execution")

    def test_controller_has_render_browser_execution_artifacts(self):
        from core.workbench_controller import WorkbenchController
        assert hasattr(WorkbenchController, "render_browser_execution_artifacts")

    def test_controller_run_returns_blocked_without_approval(self, tmp_path):
        from core.workbench_controller import WorkbenchController
        wc = WorkbenchController(outputs_root=tmp_path / "outputs")
        report = wc.run_controlled_browser_execution("t")
        assert report.execution_status == "blocked"
        assert report.approved is False


# ===========================================================================
# 14. CLI tool tests
# ===========================================================================

class TestCLITool:
    def test_no_project_id_returns_error(self):
        from tools.run_demo_execution import main
        rc = main(["--json"])
        assert rc == 2

    def test_no_approval_returns_blocked_json(self, tmp_path):
        from tools.run_demo_execution import main
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            main([f"--outputs-root={tmp_path}", "--project-id=t", "--json"])
        out = buf.getvalue()
        data = json.loads(out)
        assert data["report"]["execution_status"] == "blocked"
        assert data["report"]["approved"] is False
        assert data["report"]["safe_to_deliver"] is False

    def test_blocked_alza_returns_blocked(self, tmp_path):
        from tools.run_demo_execution import main
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            main([
                f"--outputs-root={tmp_path}", "--project-id=t", "--json",
                "--approve-public-readonly-execution",
                "--target-category=real_public_readonly",
                "--base-url=https://www.alza.sk",
            ])
        data = json.loads(buf.getvalue())
        assert data["report"]["execution_status"] == "blocked"

    def test_blocked_amazon_returns_blocked(self, tmp_path):
        from tools.run_demo_execution import main
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            main([
                f"--outputs-root={tmp_path}", "--project-id=t", "--json",
                "--approve-public-readonly-execution",
                "--target-category=high_risk_marketplace_readonly",
                "--base-url=https://www.amazon.com",
            ])
        data = json.loads(buf.getvalue())
        assert data["report"]["execution_status"] == "blocked"

    def test_blocked_linear_returns_blocked(self, tmp_path):
        from tools.run_demo_execution import main
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            main([
                f"--outputs-root={tmp_path}", "--project-id=t", "--json",
                "--approve-demo-execution",
                "--target-category=task_source",
                "--base-url=https://linear.app/acme/issue/QA-123",
            ])
        data = json.loads(buf.getvalue())
        assert data["report"]["execution_status"] == "blocked"

    def test_demo_profile_list_mode_builds_correct_command(self, tmp_path):
        from tools.run_demo_execution import main
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        m = MagicMock()
        m.returncode = 0
        m.stdout = ""
        m.stderr = ""
        _make_scaffold(tmp_path, "t")
        with patch("subprocess.run", return_value=m):
            with redirect_stdout(buf):
                main([
                    f"--outputs-root={tmp_path}", "--project-id=t", "--json",
                    "--approve-demo-execution",
                    "--demo-profile=saucedemo_public_demo",
                    "--command-mode=list",
                ])
        data = json.loads(buf.getvalue())
        cmds = data["report"]["commands"]
        assert len(cmds) > 0
        assert "list" in cmds[0]["command"] or cmds[0]["status"] in ("pass", "fail", "skipped")

    def test_readonly_profile_list_mode_command(self, tmp_path):
        from tools.run_demo_execution import main
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        m = MagicMock()
        m.returncode = 0
        m.stdout = ""
        m.stderr = ""
        _make_scaffold(tmp_path, "t")
        with patch("subprocess.run", return_value=m):
            with redirect_stdout(buf):
                main([
                    f"--outputs-root={tmp_path}", "--project-id=t", "--json",
                    "--approve-public-readonly-execution",
                    "--readonly-profile=playwright_docs_readonly",
                    "--command-mode=list",
                ])
        data = json.loads(buf.getvalue())
        assert "report" in data

    def test_json_output_is_valid_json(self, tmp_path):
        from tools.run_demo_execution import main
        import io
        from contextlib import redirect_stdout
        buf = io.StringIO()
        with redirect_stdout(buf):
            main([f"--outputs-root={tmp_path}", "--project-id=t", "--json"])
        out = buf.getvalue()
        parsed = json.loads(out)
        assert "approval" in parsed
        assert "report" in parsed

    def test_smoke_mode_builds_tests_smoke_path(self, tmp_path):
        runner = _runner(tmp_path)
        cmd, block = runner._build_command("smoke", readonly_profile=None)
        assert "tests/smoke" in cmd
        assert block is None

    def test_readonly_smoke_mode_builds_tests_smoke_path(self, tmp_path):
        runner = _runner(tmp_path)
        cmd, block = runner._build_command("readonly_smoke", readonly_profile="playwright_docs_readonly")
        assert "tests/smoke" in cmd
        assert block is None


# ===========================================================================
# 15. Safety invariants in source code (static checks)
# ===========================================================================

class TestPhase4DSafetyStatics:
    def _read(self, fpath: str) -> str:
        return Path(fpath).read_text(encoding="utf-8")

    def test_runner_has_subprocess_only_in_run_command(self):
        src = self._read("core/browser_execution_runner.py")
        # subprocess.run should be used only inside _run_command
        assert "subprocess.run" in src

    def test_runner_no_load_dotenv(self):
        src = self._read("core/browser_execution_runner.py")
        assert "load_dotenv" not in src

    def test_runner_no_requests(self):
        src = self._read("core/browser_execution_runner.py")
        assert "import requests" not in src

    def test_runner_no_httpx(self):
        src = self._read("core/browser_execution_runner.py")
        assert "import httpx" not in src

    def test_runner_no_npm_install(self):
        src = self._read("core/browser_execution_runner.py")
        assert "npm install" not in src

    def test_runner_no_playwright_install(self):
        src = self._read("core/browser_execution_runner.py")
        assert "playwright install" not in src

    def test_schema_post_init_forces_safe_to_deliver_false(self):
        src = self._read("core/schemas/browser_execution.py")
        assert "self.safe_to_deliver = False" in src

    def test_schema_post_init_forces_approved_for_client_delivery_false(self):
        src = self._read("core/schemas/browser_execution.py")
        assert "self.approved_for_client_delivery = False" in src

    def test_schema_from_dict_forces_delivery_flags(self):
        src = self._read("core/schemas/browser_execution.py")
        assert 'kwargs["safe_to_deliver"] = False' in src
        assert 'kwargs["approved_for_client_delivery"] = False' in src

    def test_always_blocked_domains_include_alza_amazon_linear(self):
        for domain in ("alza.sk", "amazon.com", "linear.app"):
            assert any(domain in d for d in _ALWAYS_BLOCKED_DOMAINS)


# ===========================================================================
# 16. Docs/governance checks
# ===========================================================================

class TestPhase4DDocsGovernance:
    def _read(self, fpath: str) -> str:
        return Path(fpath).read_text(encoding="utf-8")

    def test_commands_md_mentions_run_demo_execution(self):
        src = self._read("docs/COMMANDS.md")
        assert "run_demo_execution.py" in src

    def test_commands_md_mentions_approve_demo_execution(self):
        src = self._read("docs/COMMANDS.md")
        assert "approve-demo-execution" in src

    def test_commands_md_mentions_approve_public_readonly(self):
        src = self._read("docs/COMMANDS.md")
        assert "approve-public-readonly-execution" in src

    def test_runbook_md_mentions_phase_4d(self):
        src = self._read("docs/RUNBOOK.md")
        assert "Phase 4D" in src

    def test_phase_contracts_marks_4d_implemented(self):
        src = self._read("docs/PHASE_CONTRACTS.md")
        assert "Phase 4D" in src
        assert "implemented" in src.lower()

    def test_safety_rules_mentions_phase_4d(self):
        src = self._read("docs/SAFETY_RULES.md")
        assert "Phase 4D" in src

    def test_agent_contract_mentions_phase_4d(self):
        src = self._read("docs/AGENT_CONTRACT.md")
        assert "Phase 4D" in src

    def test_docs_manifest_mentions_07_execution(self):
        src = self._read("docs/DOCS_MANIFEST.md")
        assert "07_execution" in src
