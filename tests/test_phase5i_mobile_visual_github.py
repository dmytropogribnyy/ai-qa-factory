"""
Phase 5I tests — Mobile Viewport + Visual Regression + GitHub OAuth.

Tests cover:
1. Mobile viewport schemas and device registry
2. Mobile ecommerce readonly profiles (Amazon/Alza mobile web)
3. Mobile viewport runner gates and safety invariants
4. Visual regression schemas and safety invariants
5. Visual regression runner gates
6. GitHub auth schemas and hardcoded safety
7. GitHub auth runner capability planner
8. GitHub auth runner execution decision
9. Schema exports (__init__.py)
10. CLI safety (blocked flags)
"""
from __future__ import annotations

import sys

import pytest


# ---------------------------------------------------------------------------
# 1. Mobile viewport schemas
# ---------------------------------------------------------------------------

class TestMobileViewportSchemas:
    def test_device_list_non_empty(self):
        from core.schemas.mobile_viewport import MOBILE_VIEWPORT_DEVICES
        assert len(MOBILE_VIEWPORT_DEVICES) >= 8
        assert "iPhone 14" in MOBILE_VIEWPORT_DEVICES
        assert "Pixel 7" in MOBILE_VIEWPORT_DEVICES
        assert "iPad Pro" in MOBILE_VIEWPORT_DEVICES

    def test_ecommerce_readonly_profiles_defined(self):
        from core.schemas.mobile_viewport import MOBILE_ECOMMERCE_READONLY_PROFILES
        assert "amazon_mobile_readonly" in MOBILE_ECOMMERCE_READONLY_PROFILES
        assert "alza_mobile_readonly" in MOBILE_ECOMMERCE_READONLY_PROFILES

    def test_viewport_modes_defined(self):
        from core.schemas.mobile_viewport import MOBILE_VIEWPORT_MODES
        assert "list" in MOBILE_VIEWPORT_MODES
        assert "viewport_smoke" in MOBILE_VIEWPORT_MODES

    def test_execution_report_safety_hardcoded(self):
        from core.schemas.mobile_viewport import MobileViewportExecutionReport
        r = MobileViewportExecutionReport()
        assert r.credentials_used is False
        assert r.auth_performed is False
        assert r.safe_to_deliver is False
        assert r.approved_for_client_delivery is False
        assert r.human_review_required is True

    def test_execution_report_from_dict_enforces_safety(self):
        from core.schemas.mobile_viewport import MobileViewportExecutionReport
        r = MobileViewportExecutionReport.from_dict({
            "credentials_used": True,
            "auth_performed": True,
            "safe_to_deliver": True,
            "approved_for_client_delivery": True,
            "human_review_required": False,
        })
        assert r.credentials_used is False
        assert r.auth_performed is False
        assert r.safe_to_deliver is False
        assert r.approved_for_client_delivery is False
        assert r.human_review_required is True

    def test_viewport_profile_from_dict(self):
        from core.schemas.mobile_viewport import MobileViewportProfile
        p = MobileViewportProfile.from_dict({
            "device_name": "iPhone 14",
            "viewport_width": 390,
            "viewport_height": 844,
            "is_mobile": True,
        })
        assert p.device_name == "iPhone 14"
        assert p.viewport_width == 390
        assert p.is_mobile is True


# ---------------------------------------------------------------------------
# 2. Mobile viewport runner — device registry and gates
# ---------------------------------------------------------------------------

class TestMobileViewportRunner:
    def test_known_devices_in_registry(self):
        from core.mobile_viewport_runner import _PLAYWRIGHT_DEVICES
        assert "iPhone 14" in _PLAYWRIGHT_DEVICES
        assert "Pixel 7" in _PLAYWRIGHT_DEVICES
        assert "Galaxy S22" in _PLAYWRIGHT_DEVICES
        assert "iPad Pro" in _PLAYWRIGHT_DEVICES

    def test_mobile_ecommerce_profiles_in_registry(self):
        from core.mobile_viewport_runner import _MOBILE_ECOMMERCE_PROFILES
        assert "amazon_mobile_readonly" in _MOBILE_ECOMMERCE_PROFILES
        assert "alza_mobile_readonly" in _MOBILE_ECOMMERCE_PROFILES

    def test_gate1_no_approval_blocks(self):
        from core.mobile_viewport_runner import MobileViewportRunner
        runner = MobileViewportRunner()
        report = runner.run(
            project_id="p1",
            device_name="iPhone 14",
            approve_mobile_execution=False,
        )
        assert report.execution_status == "blocked"
        assert any("approve-mobile-execution" in b for b in report.blockers)

    def test_gate2_unknown_device_blocks(self):
        from core.mobile_viewport_runner import MobileViewportRunner
        runner = MobileViewportRunner()
        report = runner.run(
            project_id="p1",
            device_name="Samsung Galaxy Z Fold 9",
            approve_mobile_execution=True,
        )
        assert report.execution_status == "blocked"
        assert any("Unknown device" in b for b in report.blockers)

    def test_gate3_unknown_mode_blocks(self):
        from core.mobile_viewport_runner import MobileViewportRunner
        runner = MobileViewportRunner()
        report = runner.run(
            project_id="p1",
            device_name="iPhone 14",
            command_mode="full_regression",
            approve_mobile_execution=True,
        )
        assert report.execution_status == "blocked"
        assert any("command_mode" in b for b in report.blockers)

    def test_gate4_amazon_mobile_blocked_path(self):
        from core.mobile_viewport_runner import MobileViewportRunner
        runner = MobileViewportRunner()
        report = runner.run(
            project_id="p1",
            device_name="iPhone 14",
            readonly_profile="amazon_mobile_readonly",
            target_url="https://www.amazon.com/cart",
            approve_mobile_execution=True,
        )
        assert report.execution_status == "blocked"
        assert any("/cart" in b for b in report.blockers)

    def test_gate4_alza_mobile_blocked_path(self):
        from core.mobile_viewport_runner import MobileViewportRunner
        runner = MobileViewportRunner()
        report = runner.run(
            project_id="p1",
            device_name="Pixel 7",
            readonly_profile="alza_mobile_readonly",
            target_url="https://www.alza.sk/kosik",
            approve_mobile_execution=True,
        )
        assert report.execution_status == "blocked"
        assert any("kosik" in b or "alza" in b.lower() for b in report.blockers)

    def test_get_device_profile_returns_profile(self):
        from core.mobile_viewport_runner import MobileViewportRunner
        runner = MobileViewportRunner()
        profile = runner.get_device_profile("iPhone 14")
        assert profile is not None
        assert profile.device_name == "iPhone 14"
        assert profile.viewport_width == 390
        assert profile.is_mobile is True

    def test_get_device_profile_unknown_returns_none(self):
        from core.mobile_viewport_runner import MobileViewportRunner
        runner = MobileViewportRunner()
        assert runner.get_device_profile("Nokia 3310") is None

    def test_safety_invariants_on_blocked_report(self):
        from core.mobile_viewport_runner import MobileViewportRunner
        runner = MobileViewportRunner()
        report = runner.run(
            project_id="p1",
            device_name="iPhone 14",
            approve_mobile_execution=False,
        )
        assert report.credentials_used is False
        assert report.auth_performed is False
        assert report.safe_to_deliver is False
        assert report.approved_for_client_delivery is False
        assert report.human_review_required is True

    def test_ecommerce_dangerous_patterns_exist(self):
        from core.mobile_viewport_runner import _ECOMMERCE_DANGEROUS_PATTERNS
        assert "add-to-cart" in _ECOMMERCE_DANGEROUS_PATTERNS
        assert "/checkout" in _ECOMMERCE_DANGEROUS_PATTERNS
        assert "password" in _ECOMMERCE_DANGEROUS_PATTERNS

    def test_scan_blocks_dangerous_selector(self, tmp_path):
        from core.mobile_viewport_runner import MobileViewportRunner
        runner = MobileViewportRunner()
        tests_dir = tmp_path / "tests" / "smoke"
        tests_dir.mkdir(parents=True)
        (tests_dir / "bad.spec.ts").write_text(
            "await page.click('[data-id=\"add-to-cart\"]');",
            encoding="utf-8",
        )
        result = runner._scan_ecommerce_test_files(tmp_path)
        assert result is not None
        assert "dangerous pattern" in result

    def test_build_mobile_config_contains_viewport(self):
        from core.mobile_viewport_runner import MobileViewportRunner, _PLAYWRIGHT_DEVICES
        runner = MobileViewportRunner()
        meta = _PLAYWRIGHT_DEVICES["iPhone 14"]
        config = runner._build_mobile_config(meta, "https://example.com")
        assert "390" in config
        assert "844" in config
        assert "isMobile: true" in config
        assert "example.com" in config


# ---------------------------------------------------------------------------
# 3. Visual regression schemas
# ---------------------------------------------------------------------------

class TestVisualRegressionSchemas:
    def test_modes_defined(self):
        from core.schemas.visual_regression import VISUAL_REGRESSION_MODES
        assert "capture" in VISUAL_REGRESSION_MODES
        assert "compare" in VISUAL_REGRESSION_MODES
        assert "update" in VISUAL_REGRESSION_MODES

    def test_verdicts_defined(self):
        from core.schemas.visual_regression import VISUAL_DIFF_VERDICTS
        assert "pass" in VISUAL_DIFF_VERDICTS
        assert "fail" in VISUAL_DIFF_VERDICTS
        assert "new" in VISUAL_DIFF_VERDICTS

    def test_report_safety_hardcoded(self):
        from core.schemas.visual_regression import VisualRegressionReport
        r = VisualRegressionReport()
        assert r.credentials_used is False
        assert r.auth_performed is False
        assert r.safe_to_deliver is False
        assert r.approved_for_client_delivery is False
        assert r.human_review_required is True
        assert r.baselines_committed is False

    def test_report_from_dict_enforces_safety(self):
        from core.schemas.visual_regression import VisualRegressionReport
        r = VisualRegressionReport.from_dict({
            "safe_to_deliver": True,
            "approved_for_client_delivery": True,
            "human_review_required": False,
            "baselines_committed": True,
        })
        assert r.safe_to_deliver is False
        assert r.approved_for_client_delivery is False
        assert r.human_review_required is True
        assert r.baselines_committed is False

    def test_diff_result_from_dict(self):
        from core.schemas.visual_regression import VisualDiffResult
        d = VisualDiffResult.from_dict({
            "test_name": "homepage",
            "verdict": "fail",
            "pixel_diff_count": 150,
            "diff_ratio": 0.05,
        })
        assert d.test_name == "homepage"
        assert d.verdict == "fail"
        assert d.pixel_diff_count == 150

    def test_baseline_record_from_dict(self):
        from core.schemas.visual_regression import VisualBaselineRecord
        b = VisualBaselineRecord.from_dict({
            "test_name": "homepage",
            "screenshot_filename": "homepage.png",
            "file_size_bytes": 12345,
        })
        assert b.screenshot_filename == "homepage.png"
        assert b.file_size_bytes == 12345


# ---------------------------------------------------------------------------
# 4. Visual regression runner — gates
# ---------------------------------------------------------------------------

class TestVisualRegressionRunner:
    def test_gate1_no_approval_blocks(self):
        from core.visual_regression_runner import VisualRegressionRunner
        runner = VisualRegressionRunner()
        report = runner.run(
            project_id="p1",
            target_url="https://www.saucedemo.com",
            approve_visual_regression=False,
        )
        assert report.execution_status == "blocked"
        assert any("approve-visual-regression" in b for b in report.blockers)

    def test_gate2_unknown_mode_blocks(self):
        from core.visual_regression_runner import VisualRegressionRunner
        runner = VisualRegressionRunner()
        report = runner.run(
            project_id="p1",
            target_url="https://www.saucedemo.com",
            mode="full_diff",
            approve_visual_regression=True,
        )
        assert report.execution_status == "blocked"
        assert any("mode" in b.lower() for b in report.blockers)

    def test_gate3_url_not_in_allowlist_blocks(self):
        from core.visual_regression_runner import VisualRegressionRunner
        runner = VisualRegressionRunner()
        report = runner.run(
            project_id="p1",
            target_url="https://example-random-site.com",
            approve_visual_regression=True,
        )
        assert report.execution_status == "blocked"
        assert any("allowlist" in b for b in report.blockers)

    def test_gate4_blocked_path_in_url(self):
        from core.visual_regression_runner import VisualRegressionRunner
        runner = VisualRegressionRunner()
        report = runner.run(
            project_id="p1",
            target_url="https://www.saucedemo.com/checkout",
            approve_visual_regression=True,
        )
        assert report.execution_status == "blocked"
        assert any("/checkout" in b for b in report.blockers)

    def test_amazon_url_in_allowlist(self):
        from core.visual_regression_runner import _ALLOWED_URL_PREFIXES
        assert "https://www.amazon.com" in _ALLOWED_URL_PREFIXES

    def test_alza_url_in_allowlist(self):
        from core.visual_regression_runner import _ALLOWED_URL_PREFIXES
        assert "https://www.alza.sk" in _ALLOWED_URL_PREFIXES

    def test_safety_invariants_on_blocked_report(self):
        from core.visual_regression_runner import VisualRegressionRunner
        runner = VisualRegressionRunner()
        report = runner.run(
            project_id="p1",
            target_url="https://www.saucedemo.com",
            approve_visual_regression=False,
        )
        assert report.safe_to_deliver is False
        assert report.approved_for_client_delivery is False
        assert report.human_review_required is True
        assert report.baselines_committed is False

    def test_parse_counts_from_output(self):
        from core.visual_regression_runner import VisualRegressionRunner
        runner = VisualRegressionRunner()
        passed, failed = runner._parse_counts("2 passed\n1 failed")
        assert passed == 2
        assert failed == 1


# ---------------------------------------------------------------------------
# 5. GitHub auth schemas
# ---------------------------------------------------------------------------

class TestGitHubAuthSchemas:
    def test_modes_defined(self):
        from core.schemas.github_auth import GITHUB_AUTH_MODES
        assert "manual_storage_state_capture" in GITHUB_AUTH_MODES
        assert "storage_state_reuse" in GITHUB_AUTH_MODES
        assert "github_api_token_future" in GITHUB_AUTH_MODES

    def test_executable_modes(self):
        from core.schemas.github_auth import GITHUB_AUTH_MODES_EXECUTABLE_5I
        assert "manual_storage_state_capture" in GITHUB_AUTH_MODES_EXECUTABLE_5I
        assert "storage_state_reuse" in GITHUB_AUTH_MODES_EXECUTABLE_5I

    def test_planning_only_modes(self):
        from core.schemas.github_auth import GITHUB_AUTH_MODES_PLANNING_ONLY_5I
        assert "github_api_token_future" in GITHUB_AUTH_MODES_PLANNING_ONLY_5I
        assert "github_app_future" in GITHUB_AUTH_MODES_PLANNING_ONLY_5I

    def test_target_kinds(self):
        from core.schemas.github_auth import GITHUB_TARGET_KINDS
        assert "github_login_ui" in GITHUB_TARGET_KINDS

    def test_capability_safety_hardcoded(self):
        from core.schemas.github_auth import GitHubAuthCapability
        cap = GitHubAuthCapability()
        assert cap.personal_account_always_blocked is True
        assert cap.production_account_always_blocked is True
        assert cap.captcha_bypass_allowed is False
        assert cap.raw_secrets_allowed is False
        assert cap.storage_state_content_read is False
        assert cap.client_delivery_allowed is False

    def test_capability_from_dict_enforces_safety(self):
        from core.schemas.github_auth import GitHubAuthCapability
        cap = GitHubAuthCapability.from_dict({
            "personal_account_always_blocked": False,
            "captcha_bypass_allowed": True,
            "client_delivery_allowed": True,
        })
        assert cap.personal_account_always_blocked is True
        assert cap.captcha_bypass_allowed is False
        assert cap.client_delivery_allowed is False

    def test_evidence_report_safety_hardcoded(self):
        from core.schemas.github_auth import GitHubAuthEvidenceReport
        ev = GitHubAuthEvidenceReport()
        assert ev.raw_credentials_logged is False
        assert ev.cookies_logged is False
        assert ev.tokens_logged is False
        assert ev.storage_state_content_read is False
        assert ev.personal_account_used is False
        assert ev.production_account_used is False
        assert ev.safe_to_deliver is False
        assert ev.approved_for_client_delivery is False
        assert ev.internal_only is True
        assert ev.human_review_required is True

    def test_evidence_report_from_dict_enforces_safety(self):
        from core.schemas.github_auth import GitHubAuthEvidenceReport
        ev = GitHubAuthEvidenceReport.from_dict({
            "personal_account_used": True,
            "safe_to_deliver": True,
            "internal_only": False,
            "human_review_required": False,
        })
        assert ev.personal_account_used is False
        assert ev.safe_to_deliver is False
        assert ev.internal_only is True
        assert ev.human_review_required is True

    def test_test_account_profile_blocks_personal(self):
        from core.schemas.github_auth import GitHubTestAccountProfile
        p = GitHubTestAccountProfile.from_dict({"is_personal_account": True})
        assert p.is_personal_account is False

    def test_storage_state_policy_hardcoded(self):
        from core.schemas.github_auth import GitHubStorageStatePolicy
        sp = GitHubStorageStatePolicy.from_dict({
            "internal_only": False,
            "approved_for_commit": True,
            "client_visible": True,
            "storage_state_content_read": True,
        })
        assert sp.internal_only is True
        assert sp.approved_for_commit is False
        assert sp.client_visible is False
        assert sp.storage_state_content_read is False

    def test_allowed_url_prefixes(self):
        from core.schemas.github_auth import GITHUB_ALLOWED_URL_PREFIXES
        assert "https://github.com" in GITHUB_ALLOWED_URL_PREFIXES

    def test_blocked_url_patterns(self):
        from core.schemas.github_auth import GITHUB_BLOCKED_URL_PATTERNS
        assert "/settings/" in GITHUB_BLOCKED_URL_PATTERNS
        assert "/admin/" in GITHUB_BLOCKED_URL_PATTERNS


# ---------------------------------------------------------------------------
# 6. GitHub auth runner
# ---------------------------------------------------------------------------

class TestGitHubAuthRunner:
    def test_plan_capability_blocks_personal_account(self):
        from core.github_auth_runner import GitHubAuthRunner
        runner = GitHubAuthRunner()
        cap = runner.plan_capability(
            project_id="p1",
            account_label="qa_bot_github",
            target_url="https://github.com",
            target_kind="github_login_ui",
            personal_account_confirmed=True,
        )
        assert any("personal" in b.lower() for b in cap.blockers)

    def test_plan_capability_blocks_production_account(self):
        from core.github_auth_runner import GitHubAuthRunner
        runner = GitHubAuthRunner()
        cap = runner.plan_capability(
            project_id="p1",
            account_label="qa_bot_github",
            target_url="https://github.com",
            target_kind="github_login_ui",
            production_account_confirmed=True,
        )
        assert any("production" in b.lower() for b in cap.blockers)

    def test_plan_capability_requires_approval_flag(self):
        from core.github_auth_runner import GitHubAuthRunner
        runner = GitHubAuthRunner()
        cap = runner.plan_capability(
            project_id="p1",
            account_label="qa_bot_github",
            target_url="https://github.com",
            target_kind="github_login_ui",
            approve_github_test_account=False,
        )
        assert any("approve-github-test-account" in b for b in cap.blockers)

    def test_plan_capability_requires_dedicated_confirmed(self):
        from core.github_auth_runner import GitHubAuthRunner
        runner = GitHubAuthRunner()
        cap = runner.plan_capability(
            project_id="p1",
            account_label="qa_bot_github",
            target_url="https://github.com",
            target_kind="github_login_ui",
            approve_github_test_account=True,
            dedicated_test_account_confirmed=False,
        )
        assert any("dedicated" in b.lower() for b in cap.blockers)

    def test_plan_capability_blocks_non_github_url(self):
        from core.github_auth_runner import GitHubAuthRunner
        runner = GitHubAuthRunner()
        cap = runner.plan_capability(
            project_id="p1",
            account_label="qa_bot_github",
            target_url="https://google.com",
            target_kind="github_login_ui",
            approve_github_test_account=True,
            dedicated_test_account_confirmed=True,
        )
        assert any("github.com" in b for b in cap.blockers)

    def test_plan_capability_blocks_settings_url(self):
        from core.github_auth_runner import GitHubAuthRunner
        runner = GitHubAuthRunner()
        cap = runner.plan_capability(
            project_id="p1",
            account_label="qa_bot_github",
            target_url="https://github.com/settings/profile",
            target_kind="github_login_ui",
            approve_github_test_account=True,
            dedicated_test_account_confirmed=True,
        )
        assert any("/settings/" in b for b in cap.blockers)

    def test_plan_capability_planning_only_modes_blocked(self):
        from core.github_auth_runner import GitHubAuthRunner
        from core.schemas.github_auth import GITHUB_AUTH_MODES_PLANNING_ONLY_5I
        runner = GitHubAuthRunner()
        cap = runner.plan_capability(
            project_id="p1",
            account_label="qa_bot_github",
            target_url="https://github.com",
            target_kind="github_login_ui",
            approve_github_test_account=True,
            dedicated_test_account_confirmed=True,
        )
        for policy in cap.mode_policies:
            if policy.mode in GITHUB_AUTH_MODES_PLANNING_ONLY_5I:
                assert policy.allowed_now is False

    def test_decide_execution_planning_mode_blocked(self):
        from core.github_auth_runner import GitHubAuthRunner
        runner = GitHubAuthRunner()
        dec = runner.decide_execution(
            project_id="p1",
            auth_mode="cdp_attach",
            target_url="https://github.com",
            target_kind="github_login_ui",
            approve_github_test_account=True,
            dedicated_test_account_confirmed=True,
        )
        assert dec.allowed_now is False
        assert any("planning-only" in b for b in dec.blockers)

    def test_decide_execution_storage_state_reuse_needs_path(self):
        from core.github_auth_runner import GitHubAuthRunner
        runner = GitHubAuthRunner()
        dec = runner.decide_execution(
            project_id="p1",
            auth_mode="storage_state_reuse",
            target_url="https://github.com",
            target_kind="github_login_ui",
            approve_github_test_account=True,
            dedicated_test_account_confirmed=True,
            storage_state_path=None,
        )
        assert dec.allowed_now is False
        assert any("storage-state-path" in b for b in dec.blockers)

    def test_safety_invariants_on_capability(self):
        from core.github_auth_runner import GitHubAuthRunner
        runner = GitHubAuthRunner()
        cap = runner.plan_capability(
            project_id="p1",
            account_label="",
            target_url="https://github.com",
            target_kind="github_login_ui",
            approve_github_test_account=True,
            dedicated_test_account_confirmed=True,
        )
        assert cap.personal_account_always_blocked is True
        assert cap.captcha_bypass_allowed is False
        assert cap.client_delivery_allowed is False


# ---------------------------------------------------------------------------
# 7. Schema exports
# ---------------------------------------------------------------------------

class TestPhase5ISchemaExports:
    def test_mobile_viewport_exports(self):
        from core.schemas import (
            MOBILE_VIEWPORT_DEVICES,
            MOBILE_VIEWPORT_MODES,
            MobileViewportExecutionReport,
        )
        assert "iPhone 14" in MOBILE_VIEWPORT_DEVICES
        assert "viewport_smoke" in MOBILE_VIEWPORT_MODES
        r = MobileViewportExecutionReport()
        assert r.safe_to_deliver is False

    def test_visual_regression_exports(self):
        from core.schemas import (
            VISUAL_REGRESSION_MODES,
            VISUAL_DIFF_VERDICTS,
            VisualRegressionReport,
        )
        assert "capture" in VISUAL_REGRESSION_MODES
        assert "pass" in VISUAL_DIFF_VERDICTS
        r = VisualRegressionReport()
        assert r.human_review_required is True

    def test_github_auth_exports(self):
        from core.schemas import (
            GITHUB_AUTH_MODES_EXECUTABLE_5I,
            GitHubAuthCapability,
            GitHubAuthEvidenceReport,
        )
        assert "storage_state_reuse" in GITHUB_AUTH_MODES_EXECUTABLE_5I
        cap = GitHubAuthCapability()
        assert cap.captcha_bypass_allowed is False
        ev = GitHubAuthEvidenceReport()
        assert ev.safe_to_deliver is False


# ---------------------------------------------------------------------------
# 8. CLI safety — blocked flags
# ---------------------------------------------------------------------------

class TestPhase5ICLISafety:
    def test_mobile_viewport_cli_blocks_password(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            sys, "argv",
            ["run_mobile_viewport_smoke.py", "--project-id", "p1",
             "--device", "iPhone 14", "--password", "secret123",
             "--approve-mobile-execution"],
        )
        from tools.run_mobile_viewport_smoke import _check_blocked_flags
        with pytest.raises(SystemExit) as exc:
            _check_blocked_flags(["--password", "secret123"])
        assert exc.value.code == 2

    def test_visual_regression_cli_blocks_token(self):
        from tools.run_visual_regression import _check_blocked_flags
        with pytest.raises(SystemExit) as exc:
            _check_blocked_flags(["--token=abc123"])
        assert exc.value.code == 2

    def test_github_auth_cli_blocks_pat(self):
        from tools.run_github_auth_smoke import _check_blocked_flags
        with pytest.raises(SystemExit) as exc:
            _check_blocked_flags(["--pat", "ghp_abc123"])
        assert exc.value.code == 2

    def test_github_auth_cli_allows_token_env_var_name(self):
        # --approve-github-test-account is NOT in blocked list
        from tools.run_github_auth_smoke import _check_blocked_flags
        # Should not raise
        _check_blocked_flags(["--approve-github-test-account", "--dedicated-test-account-confirmed"])

    def test_mobile_allows_readonly_profile(self):
        from tools.run_mobile_viewport_smoke import _check_blocked_flags
        # Should not raise
        _check_blocked_flags(["--readonly-profile", "amazon_mobile_readonly",
                               "--approve-mobile-execution"])
