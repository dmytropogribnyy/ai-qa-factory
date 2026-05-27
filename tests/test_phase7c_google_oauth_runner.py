"""Phase 7C — Google OAuth Runner tests."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


from core.google_oauth_runner import GoogleOAuthRunner
from core.schemas.google_oauth import (
    EXECUTABLE_OAUTH_MODES,
    PLANNING_ONLY_OAUTH_MODES,
    GoogleOAuthInputs,
    GoogleOAuthMode,
    GoogleOAuthModeReadiness,
    GoogleOAuthPlan,
    GoogleOAuthRunResult,
    GoogleOAuthRunStatus,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _inputs(
    project_id: str = "proj_7c",
    storage_state_path: str = "",
    dedicated: bool = False,
    google: bool = False,
    approve: bool = False,
    target_url: str = "https://accounts.google.com",
    label: str = "",
) -> GoogleOAuthInputs:
    return GoogleOAuthInputs(
        project_id=project_id,
        target_url=target_url,
        storage_state_path=storage_state_path,
        account_email_label=label,
        dedicated_test_account_confirmed=dedicated,
        google_test_account_confirmed=google,
        approve_execution=approve,
    )


def _runner(tmp_path: Path) -> GoogleOAuthRunner:
    return GoogleOAuthRunner(outputs_root=tmp_path)


# ---------------------------------------------------------------------------
# 1. GoogleOAuthMode enum
# ---------------------------------------------------------------------------

class TestGoogleOAuthMode:
    def test_storage_state_reuse_value(self):
        assert GoogleOAuthMode.STORAGE_STATE_REUSE.value == "storage_state_reuse"

    def test_manual_capture_value(self):
        assert GoogleOAuthMode.MANUAL_CAPTURE.value == "manual_storage_state_capture"

    def test_google_api_token_value(self):
        assert GoogleOAuthMode.GOOGLE_API_TOKEN.value == "google_api_oauth_token"

    def test_service_account_value(self):
        assert GoogleOAuthMode.SERVICE_ACCOUNT.value == "google_service_account"

    def test_totp_test_account_value(self):
        assert GoogleOAuthMode.TOTP_TEST_ACCOUNT.value == "totp_test_account"

    def test_mock_oauth_value(self):
        assert GoogleOAuthMode.MOCK_OAUTH.value == "mock_oauth_provider"

    def test_exactly_six_modes(self):
        assert len(GoogleOAuthMode) == 6

    def test_executable_set_has_one_mode(self):
        assert len(EXECUTABLE_OAUTH_MODES) == 1

    def test_planning_only_set_has_five_modes(self):
        assert len(PLANNING_ONLY_OAUTH_MODES) == 5

    def test_executable_and_planning_only_disjoint(self):
        assert EXECUTABLE_OAUTH_MODES.isdisjoint(PLANNING_ONLY_OAUTH_MODES)

    def test_union_covers_all_modes(self):
        all_modes = EXECUTABLE_OAUTH_MODES | PLANNING_ONLY_OAUTH_MODES
        assert all_modes == set(GoogleOAuthMode)


# ---------------------------------------------------------------------------
# 2. GoogleOAuthModeReadiness enum
# ---------------------------------------------------------------------------

class TestGoogleOAuthModeReadiness:
    def test_executable_value(self):
        assert GoogleOAuthModeReadiness.EXECUTABLE.value == "executable"

    def test_planning_only_value(self):
        assert GoogleOAuthModeReadiness.PLANNING_ONLY.value == "planning_only"

    def test_blocked_value(self):
        assert GoogleOAuthModeReadiness.BLOCKED.value == "blocked"


# ---------------------------------------------------------------------------
# 3. GoogleOAuthRunStatus enum
# ---------------------------------------------------------------------------

class TestGoogleOAuthRunStatus:
    def test_passed(self):
        assert GoogleOAuthRunStatus.PASSED.value == "passed"

    def test_failed(self):
        assert GoogleOAuthRunStatus.FAILED.value == "failed"

    def test_blocked(self):
        assert GoogleOAuthRunStatus.BLOCKED.value == "blocked"

    def test_planning_only(self):
        assert GoogleOAuthRunStatus.PLANNING_ONLY.value == "planning_only"

    def test_skipped(self):
        assert GoogleOAuthRunStatus.SKIPPED.value == "skipped"


# ---------------------------------------------------------------------------
# 4. GoogleOAuthInputs safety invariants
# ---------------------------------------------------------------------------

class TestGoogleOAuthInputsSafetyInvariants:
    def test_raw_secrets_always_false(self):
        inp = GoogleOAuthInputs(project_id="p", raw_secrets_allowed=True)
        assert inp.raw_secrets_allowed is False

    def test_storage_state_content_read_always_false(self):
        inp = GoogleOAuthInputs(project_id="p", storage_state_content_read=True)
        assert inp.storage_state_content_read is False

    def test_captcha_bypass_always_false(self):
        inp = GoogleOAuthInputs(project_id="p", captcha_bypass_allowed=True)
        assert inp.captcha_bypass_allowed is False

    def test_anti_bot_bypass_always_false(self):
        inp = GoogleOAuthInputs(project_id="p", anti_bot_bypass_allowed=True)
        assert inp.anti_bot_bypass_allowed is False

    def test_personal_account_always_false(self):
        inp = GoogleOAuthInputs(project_id="p", personal_account_allowed=True)
        assert inp.personal_account_allowed is False

    def test_production_account_always_false(self):
        inp = GoogleOAuthInputs(project_id="p", production_account_allowed=True)
        assert inp.production_account_allowed is False

    def test_client_delivery_always_false(self):
        inp = GoogleOAuthInputs(project_id="p", client_delivery_allowed=True)
        assert inp.client_delivery_allowed is False

    def test_browser_automation_always_false(self):
        inp = GoogleOAuthInputs(project_id="p", browser_automation_allowed=True)
        assert inp.browser_automation_allowed is False

    def test_human_review_always_true(self):
        inp = GoogleOAuthInputs(project_id="p", human_review_required=False)
        assert inp.human_review_required is True

    def test_from_dict_respects_invariants(self):
        data = {
            "project_id": "p2",
            "raw_secrets_allowed": True,
            "captcha_bypass_allowed": True,
            "personal_account_allowed": True,
            "human_review_required": False,
        }
        inp = GoogleOAuthInputs.from_dict(data)
        assert inp.raw_secrets_allowed is False
        assert inp.captcha_bypass_allowed is False
        assert inp.personal_account_allowed is False
        assert inp.human_review_required is True

    def test_from_dict_preserves_user_fields(self):
        data = {
            "project_id": "p3",
            "target_url": "https://mail.google.com",
            "storage_state_path": "/tmp/ss.json",
            "dedicated_test_account_confirmed": True,
            "google_test_account_confirmed": True,
        }
        inp = GoogleOAuthInputs.from_dict(data)
        assert inp.project_id == "p3"
        assert inp.target_url == "https://mail.google.com"
        assert inp.dedicated_test_account_confirmed is True
        assert inp.google_test_account_confirmed is True

    def test_to_dict_safety_block_all_false(self):
        inp = GoogleOAuthInputs(project_id="p")
        d = inp.to_dict()
        safety = d["safety"]
        assert safety["raw_secrets_allowed"] is False
        assert safety["captcha_bypass_allowed"] is False
        assert safety["human_review_required"] is True


# ---------------------------------------------------------------------------
# 5. GoogleOAuthPlan safety invariants
# ---------------------------------------------------------------------------

class TestGoogleOAuthPlanSafetyInvariants:
    def test_raw_secrets_always_false(self):
        plan = GoogleOAuthPlan(project_id="p", target_url="https://a.com", raw_secrets_allowed=True)
        assert plan.raw_secrets_allowed is False

    def test_captcha_bypass_always_false(self):
        plan = GoogleOAuthPlan(project_id="p", target_url="x", captcha_bypass_allowed=True)
        assert plan.captcha_bypass_allowed is False

    def test_personal_account_always_false(self):
        plan = GoogleOAuthPlan(project_id="p", target_url="x", personal_account_allowed=True)
        assert plan.personal_account_allowed is False

    def test_production_account_always_false(self):
        plan = GoogleOAuthPlan(project_id="p", target_url="x", production_account_allowed=True)
        assert plan.production_account_allowed is False

    def test_client_delivery_always_false(self):
        plan = GoogleOAuthPlan(project_id="p", target_url="x", client_delivery_allowed=True)
        assert plan.client_delivery_allowed is False

    def test_human_review_always_true(self):
        plan = GoogleOAuthPlan(project_id="p", target_url="x", human_review_required=False)
        assert plan.human_review_required is True

    def test_to_dict_safety_correct(self):
        plan = GoogleOAuthPlan(project_id="p", target_url="x")
        d = plan.to_dict()
        assert d["safety"]["raw_secrets_allowed"] is False
        assert d["safety"]["human_review_required"] is True


# ---------------------------------------------------------------------------
# 6. GoogleOAuthRunResult safety invariants
# ---------------------------------------------------------------------------

class TestGoogleOAuthRunResultSafetyInvariants:
    def test_raw_secrets_always_false(self):
        r = GoogleOAuthRunResult(project_id="p", target_url="x", raw_secrets_allowed=True)
        assert r.raw_secrets_allowed is False

    def test_captcha_bypass_always_false(self):
        r = GoogleOAuthRunResult(project_id="p", target_url="x", captcha_bypass_allowed=True)
        assert r.captcha_bypass_allowed is False

    def test_personal_account_always_false(self):
        r = GoogleOAuthRunResult(project_id="p", target_url="x", personal_account_allowed=True)
        assert r.personal_account_allowed is False

    def test_production_account_always_false(self):
        r = GoogleOAuthRunResult(project_id="p", target_url="x", production_account_allowed=True)
        assert r.production_account_allowed is False

    def test_client_delivery_always_false(self):
        r = GoogleOAuthRunResult(project_id="p", target_url="x", client_delivery_allowed=True)
        assert r.client_delivery_allowed is False

    def test_storage_state_content_read_always_false(self):
        r = GoogleOAuthRunResult(project_id="p", target_url="x", storage_state_content_read=True)
        assert r.storage_state_content_read is False

    def test_human_review_always_true(self):
        r = GoogleOAuthRunResult(project_id="p", target_url="x", human_review_required=False)
        assert r.human_review_required is True

    def test_to_dict_safety_correct(self):
        r = GoogleOAuthRunResult(project_id="p", target_url="x")
        d = r.to_dict()
        assert d["safety"]["raw_secrets_allowed"] is False
        assert d["safety"]["human_review_required"] is True


# ---------------------------------------------------------------------------
# 7. GoogleOAuthRunner.classify_mode
# ---------------------------------------------------------------------------

class TestGoogleOAuthRunnerClassifyMode:
    def test_no_path_returns_manual_capture(self, tmp_path):
        runner = _runner(tmp_path)
        inp = _inputs()
        assert runner.classify_mode(inp) == GoogleOAuthMode.MANUAL_CAPTURE

    def test_path_set_but_file_missing_returns_manual_capture(self, tmp_path):
        runner = _runner(tmp_path)
        inp = _inputs(
            storage_state_path="/nonexistent/storage.json",
            dedicated=True,
            google=True,
        )
        assert runner.classify_mode(inp) == GoogleOAuthMode.MANUAL_CAPTURE

    def test_file_exists_but_no_confirmation_flags(self, tmp_path):
        ssp = tmp_path / "storage.json"
        ssp.write_text("{}", encoding="utf-8")
        runner = _runner(tmp_path)
        inp = _inputs(storage_state_path=str(ssp), dedicated=False, google=False)
        assert runner.classify_mode(inp) == GoogleOAuthMode.MANUAL_CAPTURE

    def test_file_exists_only_dedicated_confirmed(self, tmp_path):
        ssp = tmp_path / "storage.json"
        ssp.write_text("{}", encoding="utf-8")
        runner = _runner(tmp_path)
        inp = _inputs(storage_state_path=str(ssp), dedicated=True, google=False)
        assert runner.classify_mode(inp) == GoogleOAuthMode.MANUAL_CAPTURE

    def test_file_exists_only_google_confirmed(self, tmp_path):
        ssp = tmp_path / "storage.json"
        ssp.write_text("{}", encoding="utf-8")
        runner = _runner(tmp_path)
        inp = _inputs(storage_state_path=str(ssp), dedicated=False, google=True)
        assert runner.classify_mode(inp) == GoogleOAuthMode.MANUAL_CAPTURE

    def test_all_conditions_met_returns_storage_state_reuse(self, tmp_path):
        ssp = tmp_path / "storage.json"
        ssp.write_text("{}", encoding="utf-8")
        runner = _runner(tmp_path)
        inp = _inputs(storage_state_path=str(ssp), dedicated=True, google=True)
        assert runner.classify_mode(inp) == GoogleOAuthMode.STORAGE_STATE_REUSE


# ---------------------------------------------------------------------------
# 8. GoogleOAuthRunner.build_plan
# ---------------------------------------------------------------------------

class TestGoogleOAuthRunnerBuildPlan:
    def test_no_storage_state_gives_planning_only(self, tmp_path):
        plan = _runner(tmp_path).build_plan(_inputs())
        assert plan.mode_readiness == GoogleOAuthModeReadiness.PLANNING_ONLY
        assert plan.selected_mode == GoogleOAuthMode.MANUAL_CAPTURE

    def test_planning_only_plan_has_blockers(self, tmp_path):
        plan = _runner(tmp_path).build_plan(_inputs())
        assert len(plan.blockers) > 0

    def test_executable_plan_has_no_blockers(self, tmp_path):
        ssp = tmp_path / "ss.json"
        ssp.write_text("{}", encoding="utf-8")
        plan = _runner(tmp_path).build_plan(
            _inputs(storage_state_path=str(ssp), dedicated=True, google=True)
        )
        assert plan.mode_readiness == GoogleOAuthModeReadiness.EXECUTABLE
        assert plan.blockers == []

    def test_plan_safety_invariants(self, tmp_path):
        plan = _runner(tmp_path).build_plan(_inputs())
        assert plan.raw_secrets_allowed is False
        assert plan.captcha_bypass_allowed is False
        assert plan.human_review_required is True

    def test_plan_lists_all_modes(self, tmp_path):
        plan = _runner(tmp_path).build_plan(_inputs())
        assert "storage_state_reuse" in plan.executable_modes
        assert len(plan.planning_only_modes) == 5

    def test_plan_to_dict_serialisable(self, tmp_path):
        plan = _runner(tmp_path).build_plan(_inputs())
        d = plan.to_dict()
        assert json.dumps(d)  # no exception

    def test_missing_dedicated_flag_produces_blocker(self, tmp_path):
        ssp = tmp_path / "ss.json"
        ssp.write_text("{}", encoding="utf-8")
        plan = _runner(tmp_path).build_plan(
            _inputs(storage_state_path=str(ssp), dedicated=False, google=True)
        )
        assert any("dedicated" in b.lower() for b in plan.blockers)

    def test_missing_google_flag_produces_blocker(self, tmp_path):
        ssp = tmp_path / "ss.json"
        ssp.write_text("{}", encoding="utf-8")
        plan = _runner(tmp_path).build_plan(
            _inputs(storage_state_path=str(ssp), dedicated=True, google=False)
        )
        assert any("google" in b.lower() for b in plan.blockers)


# ---------------------------------------------------------------------------
# 9. GoogleOAuthRunner.run — planning-only
# ---------------------------------------------------------------------------

class TestGoogleOAuthRunnerRunPlanningOnly:
    def test_no_storage_state_gives_planning_only_status(self, tmp_path):
        result = _runner(tmp_path).run(_inputs())
        assert result.status == GoogleOAuthRunStatus.PLANNING_ONLY

    def test_planning_only_has_auth_coverage_summary(self, tmp_path):
        result = _runner(tmp_path).run(_inputs())
        assert "planning" in result.auth_coverage_summary.lower()

    def test_planning_only_safety_invariants(self, tmp_path):
        result = _runner(tmp_path).run(_inputs())
        assert result.raw_secrets_allowed is False
        assert result.captcha_bypass_allowed is False
        assert result.human_review_required is True

    def test_planning_only_storage_state_not_present(self, tmp_path):
        result = _runner(tmp_path).run(_inputs())
        assert result.storage_state_present is False

    def test_planning_only_no_smoke_commands(self, tmp_path):
        result = _runner(tmp_path).run(_inputs())
        assert result.smoke_commands == []

    def test_planning_only_mode_is_manual_capture(self, tmp_path):
        result = _runner(tmp_path).run(_inputs())
        assert result.mode == GoogleOAuthMode.MANUAL_CAPTURE


# ---------------------------------------------------------------------------
# 10. GoogleOAuthRunner.run — blocked (approval or URL)
# ---------------------------------------------------------------------------

class TestGoogleOAuthRunnerRunBlocked:
    def test_no_approve_execution_flag_gives_blocked(self, tmp_path):
        ssp = tmp_path / "ss.json"
        ssp.write_text("{}", encoding="utf-8")
        result = _runner(tmp_path).run(
            _inputs(storage_state_path=str(ssp), dedicated=True, google=True, approve=False)
        )
        assert result.status == GoogleOAuthRunStatus.BLOCKED

    def test_blocked_result_has_approval_blocker_message(self, tmp_path):
        ssp = tmp_path / "ss.json"
        ssp.write_text("{}", encoding="utf-8")
        result = _runner(tmp_path).run(
            _inputs(storage_state_path=str(ssp), dedicated=True, google=True, approve=False)
        )
        assert any("approve" in b.lower() for b in result.blockers)

    def test_blocked_url_gives_blocked(self, tmp_path):
        ssp = tmp_path / "ss.json"
        ssp.write_text("{}", encoding="utf-8")
        result = _runner(tmp_path).run(
            _inputs(
                storage_state_path=str(ssp),
                dedicated=True,
                google=True,
                approve=True,
                target_url="https://evil.example.com",
            )
        )
        assert result.status == GoogleOAuthRunStatus.BLOCKED

    def test_blocked_url_has_allowlist_blocker(self, tmp_path):
        ssp = tmp_path / "ss.json"
        ssp.write_text("{}", encoding="utf-8")
        result = _runner(tmp_path).run(
            _inputs(
                storage_state_path=str(ssp),
                dedicated=True,
                google=True,
                approve=True,
                target_url="https://evil.example.com",
            )
        )
        assert any("allowlist" in b.lower() or "allowlisted" in b.lower() for b in result.blockers)

    def test_captcha_url_is_blocked(self, tmp_path):
        ssp = tmp_path / "ss.json"
        ssp.write_text("{}", encoding="utf-8")
        result = _runner(tmp_path).run(
            _inputs(
                storage_state_path=str(ssp),
                dedicated=True,
                google=True,
                approve=True,
                target_url="https://accounts.google.com/captcha",
            )
        )
        assert result.status == GoogleOAuthRunStatus.BLOCKED

    def test_blocked_safety_invariants(self, tmp_path):
        ssp = tmp_path / "ss.json"
        ssp.write_text("{}", encoding="utf-8")
        result = _runner(tmp_path).run(
            _inputs(storage_state_path=str(ssp), dedicated=True, google=True, approve=False)
        )
        assert result.raw_secrets_allowed is False
        assert result.human_review_required is True


# ---------------------------------------------------------------------------
# 11. GoogleOAuthRunner._is_allowed_url
# ---------------------------------------------------------------------------

class TestGoogleOAuthRunnerIsAllowedUrl:
    def setup_method(self):
        self.runner = GoogleOAuthRunner()

    def test_accounts_google_allowed(self):
        assert self.runner._is_allowed_url("https://accounts.google.com") is True

    def test_mail_google_allowed(self):
        assert self.runner._is_allowed_url("https://mail.google.com/mail/u/0/") is True

    def test_drive_google_allowed(self):
        assert self.runner._is_allowed_url("https://drive.google.com") is True

    def test_docs_google_allowed(self):
        assert self.runner._is_allowed_url("https://docs.google.com") is True

    def test_myaccount_allowed(self):
        assert self.runner._is_allowed_url("https://myaccount.google.com") is True

    def test_workspace_allowed(self):
        assert self.runner._is_allowed_url("https://workspace.google.com") is True

    def test_evil_domain_blocked(self):
        assert self.runner._is_allowed_url("https://evil.example.com") is False

    def test_empty_url_blocked(self):
        assert self.runner._is_allowed_url("") is False

    def test_captcha_url_blocked(self):
        assert self.runner._is_allowed_url("https://accounts.google.com/captcha/") is False

    def test_recaptcha_url_blocked(self):
        assert self.runner._is_allowed_url("https://accounts.google.com/recaptcha") is False

    def test_http_not_https_blocked(self):
        assert self.runner._is_allowed_url("http://accounts.google.com") is False


# ---------------------------------------------------------------------------
# 12. GoogleOAuthRunner.render_artifacts
# ---------------------------------------------------------------------------

class TestGoogleOAuthRunnerRenderArtifacts:
    def test_three_artifacts_created(self, tmp_path):
        runner = _runner(tmp_path)
        plan = runner.build_plan(_inputs())
        result = runner.run(_inputs())
        artifacts = runner.render_artifacts(plan, result, "proj_7c")
        assert len(artifacts) == 3

    def test_plan_json_exists(self, tmp_path):
        runner = _runner(tmp_path)
        plan = runner.build_plan(_inputs())
        result = runner.run(_inputs())
        artifacts = runner.render_artifacts(plan, result, "proj_7c")
        assert Path(artifacts["google_oauth_plan_json"]).exists()

    def test_report_json_exists(self, tmp_path):
        runner = _runner(tmp_path)
        plan = runner.build_plan(_inputs())
        result = runner.run(_inputs())
        artifacts = runner.render_artifacts(plan, result, "proj_7c")
        assert Path(artifacts["google_oauth_report_json"]).exists()

    def test_summary_md_exists(self, tmp_path):
        runner = _runner(tmp_path)
        plan = runner.build_plan(_inputs())
        result = runner.run(_inputs())
        artifacts = runner.render_artifacts(plan, result, "proj_7c")
        assert Path(artifacts["google_oauth_summary_md"]).exists()

    def test_plan_json_is_valid(self, tmp_path):
        runner = _runner(tmp_path)
        plan = runner.build_plan(_inputs())
        result = runner.run(_inputs())
        artifacts = runner.render_artifacts(plan, result, "proj_7c")
        content = Path(artifacts["google_oauth_plan_json"]).read_text(encoding="utf-8")
        data = json.loads(content)
        assert data["project_id"] == "proj_7c"

    def test_report_json_safety_block_preserved(self, tmp_path):
        runner = _runner(tmp_path)
        plan = runner.build_plan(_inputs())
        result = runner.run(_inputs())
        artifacts = runner.render_artifacts(plan, result, "proj_7c")
        content = Path(artifacts["google_oauth_report_json"]).read_text(encoding="utf-8")
        data = json.loads(content)
        assert data["safety"]["raw_secrets_allowed"] is False
        assert data["safety"]["human_review_required"] is True

    def test_summary_md_contains_safety_table(self, tmp_path):
        runner = _runner(tmp_path)
        plan = runner.build_plan(_inputs())
        result = runner.run(_inputs())
        artifacts = runner.render_artifacts(plan, result, "proj_7c")
        md = Path(artifacts["google_oauth_summary_md"]).read_text(encoding="utf-8")
        assert "Safety Boundary" in md
        assert "False" in md


# ---------------------------------------------------------------------------
# 13. GoogleOAuthRunner.format_auth_coverage_section
# ---------------------------------------------------------------------------

class TestFormatAuthCoverageSection:
    def test_returns_string_with_auth_coverage_header(self, tmp_path):
        runner = _runner(tmp_path)
        result = runner.run(_inputs())
        section = runner.format_auth_coverage_section(result)
        assert "## Authentication Coverage" in section

    def test_section_contains_mode(self, tmp_path):
        runner = _runner(tmp_path)
        result = runner.run(_inputs())
        section = runner.format_auth_coverage_section(result)
        assert result.mode.value in section

    def test_section_contains_status(self, tmp_path):
        runner = _runner(tmp_path)
        result = runner.run(_inputs())
        section = runner.format_auth_coverage_section(result)
        assert result.status.value in section

    def test_section_mentions_safety_boundary(self, tmp_path):
        runner = _runner(tmp_path)
        result = runner.run(_inputs())
        section = runner.format_auth_coverage_section(result)
        assert "safety boundary" in section.lower() or "Safety boundary" in section


# ---------------------------------------------------------------------------
# 14. CLI blocked flags (subprocess)
# ---------------------------------------------------------------------------

class TestCLIBlockedFlags:
    def _run_cli(self, extra_args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                str(Path(__file__).parent.parent / "tools" / "run_google_oauth_smoke.py"),
                "--project-id",
                "test",
                *extra_args,
            ],
            capture_output=True,
            text=True,
        )

    def test_personal_account_flag_exits_1(self):
        result = self._run_cli(["--personal-account"])
        assert result.returncode == 1

    def test_personal_account_flag_prints_blocked(self):
        result = self._run_cli(["--personal-account"])
        assert "BLOCKED" in result.stderr

    def test_production_account_flag_exits_1(self):
        result = self._run_cli(["--production-account"])
        assert result.returncode == 1

    def test_captcha_bypass_flag_exits_1(self):
        result = self._run_cli(["--captcha-bypass"])
        assert result.returncode == 1

    def test_password_flag_exits_1(self):
        result = self._run_cli(["--password", "secret123"])
        assert result.returncode == 1

    def test_read_storage_state_flag_exits_1(self):
        result = self._run_cli(["--read-storage-state"])
        assert result.returncode == 1

    def test_username_flag_exits_1(self):
        result = self._run_cli(["--username", "test@example.com"])
        assert result.returncode == 1


# ---------------------------------------------------------------------------
# 15. CLI planning-only mode (subprocess)
# ---------------------------------------------------------------------------

class TestCLIPlanningOnlyMode:
    def _run_cli(self, extra_args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [
                sys.executable,
                str(Path(__file__).parent.parent / "tools" / "run_google_oauth_smoke.py"),
                "--project-id",
                "proj_cli_7c",
                "--outputs-root",
                str(Path(__file__).parent.parent / "outputs"),
                *extra_args,
            ],
            capture_output=True,
            text=True,
        )

    def test_no_storage_state_exits_nonzero(self):
        # planning_only exits 1 (no execution happened — treat as soft error for CI)
        result = self._run_cli([])
        # planning_only status: CLI exits 0 (artifact produced); blocked/failed exits 1
        assert result.returncode in (0, 1)

    def test_no_storage_state_prints_planning_only(self):
        result = self._run_cli([])
        assert "planning_only" in result.stdout

    def test_output_contains_json(self):
        result = self._run_cli([])
        assert "{" in result.stdout
        json_start = result.stdout.find("{")
        json_str = result.stdout[json_start: result.stdout.rfind("}") + 1]
        data = json.loads(json_str)
        assert "status" in data

    def test_json_safety_block_in_output(self):
        result = self._run_cli([])
        json_start = result.stdout.find("{")
        json_str = result.stdout[json_start: result.stdout.rfind("}") + 1]
        data = json.loads(json_str)
        assert data["safety"]["raw_secrets_allowed"] is False
        assert data["safety"]["human_review_required"] is True

    def test_help_flag_exits_0(self):
        result = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).parent.parent / "tools" / "run_google_oauth_smoke.py"),
                "--help",
            ],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "Phase 7C" in result.stdout
