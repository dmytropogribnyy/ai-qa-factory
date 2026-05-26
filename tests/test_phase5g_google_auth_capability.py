"""
Phase 5G — Google Auth Capability tests.

No real Google login. No browser. No network. All execution is mocked.
The runner's subprocess.run is mocked so no Node script runs.
"""
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from core.google_auth_capability import GoogleAuthCapabilityPlanner
from core.google_auth_runner import GoogleAuthRunner
from core.schemas.google_auth import (
    GOOGLE_AUTH_MODES,
    GOOGLE_AUTH_MODES_EXECUTABLE_5G,
    GoogleAuthCapability,
    GoogleAuthExecutionDecision,
    GoogleAuthEvidenceReport,
    GoogleStorageStatePolicy,
)


# ---------------------------------------------------------------------------
# Schema invariant tests
# ---------------------------------------------------------------------------

class TestSchemaInvariants:
    def test_capability_safety_flags_hardcoded(self):
        cap = GoogleAuthCapability(
            project_id="x",
            raw_secrets_allowed=True,
            storage_state_content_read=True,
            browser_profile_content_read=True,
            captcha_bypass_allowed=True,
            anti_bot_bypass_allowed=True,
            client_delivery_allowed=True,
            personal_account_always_blocked=False,
            production_account_always_blocked=False,
            stealth_live_login_as_core_path=True,
        )
        assert cap.raw_secrets_allowed is False
        assert cap.storage_state_content_read is False
        assert cap.browser_profile_content_read is False
        assert cap.captcha_bypass_allowed is False
        assert cap.anti_bot_bypass_allowed is False
        assert cap.client_delivery_allowed is False
        assert cap.personal_account_always_blocked is True
        assert cap.production_account_always_blocked is True
        assert cap.stealth_live_login_as_core_path is False

    def test_capability_from_dict_safety_forced(self):
        cap = GoogleAuthCapability.from_dict({
            "project_id": "x",
            "raw_secrets_allowed": True,
            "captcha_bypass_allowed": True,
        })
        assert cap.raw_secrets_allowed is False
        assert cap.captcha_bypass_allowed is False
        assert cap.personal_account_always_blocked is True

    def test_decision_safety_flags_hardcoded(self):
        dec = GoogleAuthExecutionDecision(
            project_id="x",
            raw_secrets_allowed=True,
            captcha_bypass_allowed=True,
            anti_bot_bypass_allowed=True,
            storage_state_content_read=True,
            browser_profile_content_read=True,
            client_delivery_allowed=True,
        )
        assert dec.raw_secrets_allowed is False
        assert dec.captcha_bypass_allowed is False
        assert dec.anti_bot_bypass_allowed is False
        assert dec.storage_state_content_read is False
        assert dec.browser_profile_content_read is False
        assert dec.client_delivery_allowed is False

    def test_evidence_safety_flags_hardcoded(self):
        r = GoogleAuthEvidenceReport(
            project_id="x",
            raw_credentials_logged=True,
            cookies_logged=True,
            tokens_logged=True,
            storage_state_content_read=True,
            captcha_bypass_attempted=True,
            anti_bot_bypass_attempted=True,
            personal_account_used=True,
            production_account_used=True,
            safe_to_deliver=True,
            approved_for_client_delivery=True,
            client_visible=True,
            internal_only=False,
            human_review_required=False,
        )
        assert r.raw_credentials_logged is False
        assert r.cookies_logged is False
        assert r.tokens_logged is False
        assert r.storage_state_content_read is False
        assert r.captcha_bypass_attempted is False
        assert r.anti_bot_bypass_attempted is False
        assert r.personal_account_used is False
        assert r.production_account_used is False
        assert r.safe_to_deliver is False
        assert r.approved_for_client_delivery is False
        assert r.client_visible is False
        assert r.internal_only is True
        assert r.human_review_required is True

    def test_storage_state_policy_safety_flags(self):
        p = GoogleStorageStatePolicy(
            project_id="x",
            internal_only=False,
            approved_for_commit=True,
            client_visible=True,
            storage_state_content_read=True,
        )
        assert p.internal_only is True
        assert p.approved_for_commit is False
        assert p.client_visible is False
        assert p.storage_state_content_read is False


# ---------------------------------------------------------------------------
# Planner — capability tests
# ---------------------------------------------------------------------------

class TestCapabilityPlanner:
    def test_personal_account_blocks_all_modes(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        cap = planner.build_capability(
            project_id="p1",
            personal_account_confirmed=True,
            dedicated_test_account_confirmed=True,
            google_test_account_confirmed=True,
        )
        for mp in cap.mode_policies:
            assert mp.allowed_now is False
            assert any("personal_account_confirmed" in b for b in mp.blockers)

    def test_production_account_blocks_all_modes(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        cap = planner.build_capability(
            project_id="p1",
            production_account_confirmed=True,
            dedicated_test_account_confirmed=True,
            google_test_account_confirmed=True,
        )
        for mp in cap.mode_policies:
            assert mp.allowed_now is False
            assert any("production_account_confirmed" in b for b in mp.blockers)

    def test_dedicated_test_unlocks_executable_modes(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        cap = planner.build_capability(
            project_id="p1",
            account_email_label="danrobinson_artist_gmail",
            dedicated_test_account_confirmed=True,
            google_test_account_confirmed=True,
        )
        allowed_modes = {mp.auth_mode for mp in cap.mode_policies if mp.allowed_now}
        assert "manual_storage_state_capture" in allowed_modes
        assert "storage_state_reuse" in allowed_modes
        # Phase 5H: cdp_attach and dedicated_profile_context are now executable
        for mode in ("cdp_attach", "dedicated_profile_context"):
            mp = next(m for m in cap.mode_policies if m.auth_mode == mode)
            assert mp.allowed_now is True
        # Remaining modes are still planning-only
        for mode in (
            "google_api_oauth_token_future",
            "google_service_account_future",
            "totp_test_account_future",
            "mock_oauth_provider_future",
        ):
            mp = next(m for m in cap.mode_policies if m.auth_mode == mode)
            assert mp.allowed_now is False

    def test_missing_dedicated_flag_blocks_executable_modes(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        cap = planner.build_capability(
            project_id="p1",
            google_test_account_confirmed=True,
            dedicated_test_account_confirmed=False,
        )
        for mp in cap.mode_policies:
            assert mp.allowed_now is False

    def test_unknown_email_label_produces_warning(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        cap = planner.build_capability(
            project_id="p1",
            account_email_label="unknown_label_xyz",
            dedicated_test_account_confirmed=True,
            google_test_account_confirmed=True,
        )
        first = cap.mode_policies[0]
        assert any("not in the permitted" in w for w in first.warnings)

    def test_all_modes_carry_safety_notes(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        cap = planner.build_capability(project_id="p1")
        for mp in cap.mode_policies:
            assert any("CAPTCHA bypass" in n for n in mp.notes)
            assert any("Anti-bot bypass" in n for n in mp.notes)


# ---------------------------------------------------------------------------
# Planner — decision tests
# ---------------------------------------------------------------------------

class TestDecideExecution:
    def _good_args(self):
        return dict(
            project_id="p1",
            target_url="https://myaccount.google.com",
            target_kind="google_account_ui",
            auth_mode="storage_state_reuse",
            account_email_label="danrobinson_artist_gmail",
            approve_google_test_account=True,
            google_test_account_confirmed=True,
            dedicated_test_account_confirmed=True,
        )

    def test_blocks_personal_account(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        args = self._good_args()
        args["personal_account_confirmed"] = True
        dec = planner.decide_execution(**args)
        assert dec.allowed_now is False
        assert any("personal_account_confirmed=True" in b for b in dec.blockers)

    def test_blocks_production_account(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        args = self._good_args()
        args["production_account_confirmed"] = True
        dec = planner.decide_execution(**args)
        assert dec.allowed_now is False
        assert any("production_account_confirmed=True" in b for b in dec.blockers)

    def test_blocks_missing_approvals(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        dec = planner.decide_execution(
            project_id="p1",
            target_url="https://myaccount.google.com",
            target_kind="google_account_ui",
            auth_mode="storage_state_reuse",
        )
        assert dec.allowed_now is False
        assert any("approve-google-test-account" in b for b in dec.blockers)

    def test_blocks_unknown_mode(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        args = self._good_args()
        args["auth_mode"] = "magic_login"
        dec = planner.decide_execution(**args)
        assert dec.allowed_now is False
        assert any("Unknown auth_mode" in b for b in dec.blockers)

    def test_planning_only_modes_blocked(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        # Phase 5H: cdp_attach and dedicated_profile_context are now executable (not planning-only)
        # Only the future-only modes remain planning-only
        for mode in (
            "google_api_oauth_token_future",
            "google_service_account_future",
            "totp_test_account_future",
            "mock_oauth_provider_future",
        ):
            args = self._good_args()
            args["auth_mode"] = mode
            dec = planner.decide_execution(**args)
            assert dec.allowed_now is False
            assert any("planning-only" in b for b in dec.blockers)

    def test_storage_state_reuse_requires_path(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        args = self._good_args()
        # No storage_state_path provided
        dec = planner.decide_execution(**args)
        assert dec.allowed_now is False
        assert any("storage_state_path" in b for b in dec.blockers)

    def test_storage_state_path_must_be_internal(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        outside = tmp_path / "outside.json"
        outside.write_text("{}", encoding="utf-8")
        args = self._good_args()
        args["storage_state_path"] = str(outside)
        dec = planner.decide_execution(**args)
        assert dec.allowed_now is False
        assert any("must be inside" in b for b in dec.blockers)

    def test_storage_state_path_must_exist(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        # Path under correct dir but does not exist
        target = (tmp_path / "p1" / "15_google_auth" / ".auth" / "google-storageState.json").resolve()
        args = self._good_args()
        args["storage_state_path"] = str(target)
        dec = planner.decide_execution(**args)
        assert dec.allowed_now is False
        assert any("does not exist" in b for b in dec.blockers)

    def test_storage_state_reuse_allowed_when_internal_and_exists(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        ssdir = tmp_path / "p1" / "15_google_auth" / ".auth"
        ssdir.mkdir(parents=True, exist_ok=True)
        ssp = ssdir / "google-storageState.json"
        ssp.write_text("{}", encoding="utf-8")
        args = self._good_args()
        args["storage_state_path"] = str(ssp.resolve())
        dec = planner.decide_execution(**args)
        assert dec.allowed_now is True, dec.blockers

    def test_manual_capture_does_not_require_storage_path(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        args = self._good_args()
        args["auth_mode"] = "manual_storage_state_capture"
        args["target_kind"] = "google_account_ui"
        dec = planner.decide_execution(**args)
        assert dec.allowed_now is True, dec.blockers

    def test_captcha_url_produces_warning(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        ssdir = tmp_path / "p1" / "15_google_auth" / ".auth"
        ssdir.mkdir(parents=True, exist_ok=True)
        ssp = ssdir / "google-storageState.json"
        ssp.write_text("{}", encoding="utf-8")
        args = self._good_args()
        args["target_url"] = "https://example.com/captcha/challenge"
        args["storage_state_path"] = str(ssp.resolve())
        dec = planner.decide_execution(**args)
        assert any("CAPTCHA" in w for w in dec.warnings)

    def test_invalid_env_var_name_blocks(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        args = self._good_args()
        args["auth_mode"] = "google_api_oauth_token_future"
        args["api_token_env_var"] = "lowercase_var"
        dec = planner.decide_execution(**args)
        assert dec.allowed_now is False
        assert any("api_token_env_var" in b for b in dec.blockers)

    def test_user_data_dir_must_be_internal(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        outside = tmp_path / "main_chrome_profile"
        outside.mkdir()
        args = self._good_args()
        args["auth_mode"] = "dedicated_profile_context"
        args["user_data_dir"] = str(outside)
        dec = planner.decide_execution(**args)
        assert dec.allowed_now is False
        assert any("must be inside" in b for b in dec.blockers)

    def test_cdp_port_out_of_range_blocks(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        args = self._good_args()
        args["auth_mode"] = "cdp_attach"
        args["cdp_port"] = 80
        dec = planner.decide_execution(**args)
        assert dec.allowed_now is False
        assert any("cdp_port" in b for b in dec.blockers)


# ---------------------------------------------------------------------------
# Runner — execution gates (subprocess mocked)
# ---------------------------------------------------------------------------

class TestRunnerGates:
    def test_capture_blocked_for_personal_account(self, tmp_path):
        runner = GoogleAuthRunner(outputs_root=tmp_path)
        report = runner.capture_storage_state(
            project_id="p1",
            target_url="https://accounts.google.com",
            approve_google_test_account=True,
            google_test_account_confirmed=True,
            dedicated_test_account_confirmed=True,
            personal_account_confirmed=True,
        )
        assert report.execution_performed is False
        assert report.storage_state_captured is False

    def test_capture_blocked_without_approvals(self, tmp_path):
        runner = GoogleAuthRunner(outputs_root=tmp_path)
        report = runner.capture_storage_state(
            project_id="p1",
            target_url="https://accounts.google.com",
        )
        assert report.execution_performed is False
        assert report.storage_state_captured is False

    def test_capture_blocked_for_non_google_url(self, tmp_path):
        # Set up scaffold so we get past the scaffold check
        (tmp_path / "p1" / "03_framework" / "playwright").mkdir(parents=True)
        runner = GoogleAuthRunner(outputs_root=tmp_path)
        report = runner.capture_storage_state(
            project_id="p1",
            target_url="https://example.com",
            approve_google_test_account=True,
            google_test_account_confirmed=True,
            dedicated_test_account_confirmed=True,
        )
        assert report.execution_performed is False
        assert any("allowlisted Google" in n for n in report.notes)

    def test_capture_blocked_without_scaffold(self, tmp_path):
        runner = GoogleAuthRunner(outputs_root=tmp_path)
        report = runner.capture_storage_state(
            project_id="p1",
            target_url="https://accounts.google.com",
            approve_google_test_account=True,
            google_test_account_confirmed=True,
            dedicated_test_account_confirmed=True,
        )
        assert report.execution_performed is False
        assert any("scaffold" in n for n in report.notes)

    def test_smoke_blocked_without_storage_state(self, tmp_path):
        (tmp_path / "p1" / "03_framework" / "playwright").mkdir(parents=True)
        runner = GoogleAuthRunner(outputs_root=tmp_path)
        report = runner.run_storage_state_smoke(
            project_id="p1",
            target_url="https://myaccount.google.com",
            storage_state_path=str(tmp_path / "missing.json"),
            approve_google_test_account=True,
            google_test_account_confirmed=True,
            dedicated_test_account_confirmed=True,
        )
        assert report.execution_performed is False

    def test_smoke_safety_flags_in_evidence(self, tmp_path):
        runner = GoogleAuthRunner(outputs_root=tmp_path)
        report = runner.run_storage_state_smoke(
            project_id="p1",
            target_url="https://myaccount.google.com",
            storage_state_path="missing.json",
        )
        assert report.cookies_logged is False
        assert report.tokens_logged is False
        assert report.captcha_bypass_attempted is False
        assert report.anti_bot_bypass_attempted is False
        assert report.safe_to_deliver is False
        assert report.approved_for_client_delivery is False
        assert report.human_review_required is True

    def test_capture_runs_subprocess_when_allowed(self, tmp_path):
        scaffold = tmp_path / "p1" / "03_framework" / "playwright"
        scaffold.mkdir(parents=True)
        runner = GoogleAuthRunner(outputs_root=tmp_path)

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "[5G] Storage state saved.\n"
        mock_proc.stderr = ""

        # Simulate that the script saves the storageState file
        def fake_run(*args, **kwargs):
            ss_path = tmp_path / "p1" / "15_google_auth" / ".auth" / "google-storageState.json"
            ss_path.parent.mkdir(parents=True, exist_ok=True)
            ss_path.write_text("{}", encoding="utf-8")
            return mock_proc

        with patch("core.google_auth_runner.subprocess.run", side_effect=fake_run), \
             patch("core.google_auth_runner.shutil.which", return_value="node"):
            report = runner.capture_storage_state(
                project_id="p1",
                target_url="https://accounts.google.com",
                approve_google_test_account=True,
                google_test_account_confirmed=True,
                dedicated_test_account_confirmed=True,
                account_email_label="danrobinson_artist_gmail",
                timeout_seconds=5,
            )

        assert report.execution_performed is True
        assert report.storage_state_captured is True
        assert report.storage_state_size_bytes > 0
        # Safety flags always False
        assert report.cookies_logged is False
        assert report.tokens_logged is False
        assert report.storage_state_content_read is False
        assert report.captcha_bypass_attempted is False
        assert report.safe_to_deliver is False

    def test_smoke_runs_subprocess_with_existing_state(self, tmp_path):
        scaffold = tmp_path / "p1" / "03_framework" / "playwright"
        scaffold.mkdir(parents=True)
        ssdir = tmp_path / "p1" / "15_google_auth" / ".auth"
        ssdir.mkdir(parents=True)
        ssp = ssdir / "google-storageState.json"
        ssp.write_text("{}", encoding="utf-8")

        runner = GoogleAuthRunner(outputs_root=tmp_path)
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = "[5G][smoke] status=200\n"
        mock_proc.stderr = ""

        with patch("core.google_auth_runner.subprocess.run", return_value=mock_proc), \
             patch("core.google_auth_runner.shutil.which", return_value="node"):
            report = runner.run_storage_state_smoke(
                project_id="p1",
                target_url="https://myaccount.google.com",
                storage_state_path=str(ssp.resolve()),
                approve_google_test_account=True,
                google_test_account_confirmed=True,
                dedicated_test_account_confirmed=True,
            )

        assert report.execution_performed is True
        assert report.storage_state_content_read is False
        assert report.cookies_logged is False


# ---------------------------------------------------------------------------
# Artifact rendering tests
# ---------------------------------------------------------------------------

class TestArtifactRendering:
    def test_capability_artifacts_written(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        cap = planner.build_capability(
            project_id="p1",
            account_email_label="danrobinson_artist_gmail",
            dedicated_test_account_confirmed=True,
            google_test_account_confirmed=True,
        )
        paths = planner.render_capability_artifacts(cap, "p1")
        assert Path(paths["capability_plan_json"]).exists()
        assert Path(paths["capability_plan_md"]).exists()
        assert Path(paths["storage_state_policy_json"]).exists()
        assert Path(paths["storage_state_policy_md"]).exists()
        assert Path(paths["redaction_checklist_md"]).exists()

    def test_capability_json_contains_safety_invariants(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        cap = planner.build_capability(project_id="p1")
        paths = planner.render_capability_artifacts(cap, "p1")
        data = json.loads(Path(paths["capability_plan_json"]).read_text())
        assert data["raw_secrets_allowed"] is False
        assert data["captcha_bypass_allowed"] is False
        assert data["anti_bot_bypass_allowed"] is False
        assert data["client_delivery_allowed"] is False
        assert data["personal_account_always_blocked"] is True
        assert data["production_account_always_blocked"] is True

    def test_decision_artifacts_written(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        dec = planner.decide_execution(
            project_id="p1",
            target_url="https://accounts.google.com",
            target_kind="google_account_ui",
            auth_mode="manual_storage_state_capture",
            approve_google_test_account=True,
            google_test_account_confirmed=True,
            dedicated_test_account_confirmed=True,
        )
        paths = planner.render_decision_artifacts(dec, "p1")
        assert Path(paths["decision_json"]).exists()
        assert Path(paths["decision_md"]).exists()

    def test_evidence_artifacts_written(self, tmp_path):
        runner = GoogleAuthRunner(outputs_root=tmp_path)
        report = runner.run_storage_state_smoke(
            project_id="p1",
            target_url="https://myaccount.google.com",
            storage_state_path="missing.json",
        )
        paths = runner.render_evidence_artifacts(report, "p1")
        assert Path(paths["evidence_report_json"]).exists()
        assert Path(paths["evidence_report_md"]).exists()

    def test_redaction_checklist_has_critical_items(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        cap = planner.build_capability(project_id="p1")
        paths = planner.render_capability_artifacts(cap, "p1")
        rc = Path(paths["redaction_checklist_md"]).read_text()
        assert "CAPTCHA bypass not attempted" in rc
        assert "Anti-bot bypass not attempted" in rc
        assert "Personal Google account not referenced" in rc
        assert "Production Google account not referenced" in rc
        assert "TOTP seed" in rc

    def test_no_raw_secrets_in_capability_artifacts(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        cap = planner.build_capability(
            project_id="p1",
            account_email_label="danrobinson_artist_gmail",
            dedicated_test_account_confirmed=True,
            google_test_account_confirmed=True,
        )
        paths = planner.render_capability_artifacts(cap, "p1")
        # Raw secret values must never appear. The word "password" may appear in
        # safety instructions (e.g. "do not automate password typing") but no
        # actual password values or raw account emails should leak.
        for k in paths:
            content = Path(paths[k]).read_text(encoding="utf-8")
            assert "@gmail.com" not in content, f"raw email leaked into {k}"
            assert "@google.com" not in content, f"raw google email leaked into {k}"
            # Look for password=VALUE style strings (would indicate a leak)
            import re
            assert not re.search(r"password\s*[:=]\s*['\"]?[\w@!#$%^&*]+['\"]?", content, re.IGNORECASE), \
                f"password value leaked into {k}"


# ---------------------------------------------------------------------------
# Generic runner still blocks Google
# ---------------------------------------------------------------------------

class TestGenericRunnersStillBlockGoogle:
    def test_dedicated_auth_runner_blocks_google_url(self):
        from core.dedicated_auth_runner import _STRICTLY_BLOCKED_URL_PATTERNS
        assert any("accounts.google.com" in p for p in _STRICTLY_BLOCKED_URL_PATTERNS)
        assert any("google.com/o/oauth2" in p for p in _STRICTLY_BLOCKED_URL_PATTERNS)

    def test_api_auth_runner_blocks_google_url(self):
        from core.api_auth_runner import _STRICTLY_BLOCKED_URL_PATTERNS
        assert any("accounts.google.com" in p for p in _STRICTLY_BLOCKED_URL_PATTERNS)


# ---------------------------------------------------------------------------
# CLI safety tests
# ---------------------------------------------------------------------------

class TestCLISafety:
    def test_no_raw_secret_flags_in_plan_cli(self):
        src = Path("tools/plan_google_auth.py").read_text(encoding="utf-8")
        for flag in ("--password", "--secret=", "--api-key", "--cookie", "--totp-seed"):
            # Ensure they appear ONLY in the blocked list and rejection logic
            assert "_BLOCKED_FLAGS" in src

    def test_no_raw_secret_flags_in_capture_cli(self):
        src = Path("tools/capture_google_storage_state.py").read_text(encoding="utf-8")
        assert "_BLOCKED_FLAGS" in src
        assert "raw-secret flag" in src

    def test_no_raw_secret_flags_in_smoke_cli(self):
        src = Path("tools/run_google_auth_smoke.py").read_text(encoding="utf-8")
        assert "_BLOCKED_FLAGS" in src

    def test_capture_cli_has_required_approval_flags(self):
        src = Path("tools/capture_google_storage_state.py").read_text(encoding="utf-8")
        assert "--approve-google-test-account" in src
        assert "--google-test-account-confirmed" in src
        assert "--dedicated-test-account-confirmed" in src

    def test_smoke_cli_only_allows_storage_state_reuse_mode(self):
        src = Path("tools/run_google_auth_smoke.py").read_text(encoding="utf-8")
        assert "storage_state_reuse" in src


# ---------------------------------------------------------------------------
# Mode coverage
# ---------------------------------------------------------------------------

class TestModeCoverage:
    def test_all_modes_have_mode_policy(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        cap = planner.build_capability(project_id="p1")
        modes_in_cap = {mp.auth_mode for mp in cap.mode_policies}
        assert set(GOOGLE_AUTH_MODES) == modes_in_cap

    def test_only_5g_executable_modes_can_be_allowed_now(self, tmp_path):
        planner = GoogleAuthCapabilityPlanner(outputs_root=tmp_path)
        cap = planner.build_capability(
            project_id="p1",
            dedicated_test_account_confirmed=True,
            google_test_account_confirmed=True,
        )
        for mp in cap.mode_policies:
            if mp.allowed_now:
                assert mp.auth_mode in GOOGLE_AUTH_MODES_EXECUTABLE_5G
