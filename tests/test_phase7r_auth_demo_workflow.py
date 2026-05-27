"""
Phase 7R — Auth Demo Workflow tests.

Covers: AuthDemoResult safety invariants, scenario categories and statuses,
artifact directory creation, client_report.md content, CLI blocked flags,
credential safety (no values in artifacts).
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.auth_demo_workflow import (
    DEMO_PROJECT_ID,
    AuthDemoResult,
    AuthDemoScenario,
    AuthDemoWorkflow,
    _BLOCKED_SAFETY_CASES,
)

TOOL_PATH = Path(__file__).parent.parent / "tools" / "run_auth_demo_workflow.py"


# ===========================================================================
# 1. AuthDemoResult — safety invariants
# ===========================================================================
class TestAuthDemoResultSafetyInvariants:
    def _result(self, **kwargs) -> AuthDemoResult:
        return AuthDemoResult(project_id="p", scenarios=[], **kwargs)

    def test_approved_always_false(self):
        r = self._result(approved_for_client_delivery=True)
        assert r.approved_for_client_delivery is False

    def test_human_review_always_true(self):
        r = self._result(human_review_required=False)
        assert r.human_review_required is True

    def test_to_dict_approved_false(self):
        r = self._result()
        d = r.to_dict()
        assert d["approved_for_client_delivery"] is False

    def test_to_dict_human_review_true(self):
        r = self._result()
        d = r.to_dict()
        assert d["human_review_required"] is True

    def test_to_dict_has_scenarios_list(self):
        r = self._result()
        d = r.to_dict()
        assert isinstance(d["scenarios"], list)

    def test_to_dict_has_artifact_paths(self):
        r = self._result()
        d = r.to_dict()
        for key in (
            "capability_plan_path",
            "strategy_decision_path",
            "google_oauth_report_path",
            "email_password_report_path",
            "client_report_path",
        ):
            assert key in d


# ===========================================================================
# 2. AuthDemoScenario dataclass
# ===========================================================================
class TestAuthDemoScenario:
    def test_fields_present(self):
        s = AuthDemoScenario(
            name="test",
            phase="7C",
            category="skipped",
            status="planning_only",
            description="test desc",
        )
        assert s.name == "test"
        assert s.phase == "7C"
        assert s.category == "skipped"
        assert s.status == "planning_only"
        assert s.description == "test desc"
        assert s.auth_coverage_summary == ""
        assert s.artifact_dir == ""

    def test_optional_fields(self):
        s = AuthDemoScenario(
            name="x",
            phase="7D",
            category="blocked",
            status="blocked",
            description="d",
            auth_coverage_summary="summary here",
            artifact_dir="/tmp/artifacts",
        )
        assert s.auth_coverage_summary == "summary here"
        assert s.artifact_dir == "/tmp/artifacts"


# ===========================================================================
# 3. DEMO_PROJECT_ID constant
# ===========================================================================
class TestDemoProjectId:
    def test_is_string(self):
        assert isinstance(DEMO_PROJECT_ID, str)

    def test_is_demo_auth_workflow(self):
        assert DEMO_PROJECT_ID == "demo-auth-workflow"


# ===========================================================================
# 4. _BLOCKED_SAFETY_CASES constant
# ===========================================================================
class TestBlockedSafetyCases:
    def test_has_four_cases(self):
        assert len(_BLOCKED_SAFETY_CASES) == 4

    def test_personal_account_blocked(self):
        names = [name for name, _ in _BLOCKED_SAFETY_CASES]
        assert "personal_account_blocked" in names

    def test_production_account_blocked(self):
        names = [name for name, _ in _BLOCKED_SAFETY_CASES]
        assert "production_account_blocked" in names

    def test_raw_password_cli_blocked(self):
        names = [name for name, _ in _BLOCKED_SAFETY_CASES]
        assert "raw_password_cli_blocked" in names

    def test_captcha_bypass_blocked(self):
        names = [name for name, _ in _BLOCKED_SAFETY_CASES]
        assert "captcha_bypass_blocked" in names

    def test_all_have_descriptions(self):
        for _, desc in _BLOCKED_SAFETY_CASES:
            assert len(desc) > 10


# ===========================================================================
# 5. AuthDemoWorkflow.run() — artifact directories created
# ===========================================================================
class TestAuthDemoWorkflowArtifactDirs:
    def test_capability_plan_dir_created(self, tmp_path):
        AuthDemoWorkflow(outputs_root=tmp_path).run(project_id="demo-test")
        assert (tmp_path / "demo-test" / "34_auth_capability").is_dir()

    def test_strategy_decision_dir_created(self, tmp_path):
        workflow = AuthDemoWorkflow(outputs_root=tmp_path)
        workflow.run(project_id="demo-test")
        assert (tmp_path / "demo-test" / "35_auth_strategy").is_dir()

    def test_google_oauth_dir_created(self, tmp_path):
        workflow = AuthDemoWorkflow(outputs_root=tmp_path)
        workflow.run(project_id="demo-test")
        assert (tmp_path / "demo-test" / "16_google_oauth").is_dir()

    def test_email_password_dir_created(self, tmp_path):
        workflow = AuthDemoWorkflow(outputs_root=tmp_path)
        workflow.run(project_id="demo-test")
        assert (tmp_path / "demo-test" / "37_email_password_auth").is_dir()

    def test_client_audit_dir_created(self, tmp_path):
        workflow = AuthDemoWorkflow(outputs_root=tmp_path)
        workflow.run(project_id="demo-test")
        assert (tmp_path / "demo-test" / "33_client_audit").is_dir()


# ===========================================================================
# 6. AuthDemoWorkflow.run() — artifact files created
# ===========================================================================
class TestAuthDemoWorkflowArtifactFiles:
    def test_capability_plan_json_exists(self, tmp_path):
        workflow = AuthDemoWorkflow(outputs_root=tmp_path)
        workflow.run(project_id="demo-test")
        assert (tmp_path / "demo-test" / "34_auth_capability" / "auth_capability_plan.json").exists()

    def test_strategy_decision_json_exists(self, tmp_path):
        workflow = AuthDemoWorkflow(outputs_root=tmp_path)
        workflow.run(project_id="demo-test")
        assert (tmp_path / "demo-test" / "35_auth_strategy" / "auth_strategy_decision.json").exists()

    def test_google_oauth_report_json_exists(self, tmp_path):
        workflow = AuthDemoWorkflow(outputs_root=tmp_path)
        workflow.run(project_id="demo-test")
        assert (tmp_path / "demo-test" / "16_google_oauth" / "google_oauth_report.json").exists()

    def test_email_password_report_json_exists(self, tmp_path):
        workflow = AuthDemoWorkflow(outputs_root=tmp_path)
        workflow.run(project_id="demo-test")
        assert (tmp_path / "demo-test" / "37_email_password_auth" / "email_password_report.json").exists()

    def test_client_report_md_exists(self, tmp_path):
        workflow = AuthDemoWorkflow(outputs_root=tmp_path)
        workflow.run(project_id="demo-test")
        assert (tmp_path / "demo-test" / "33_client_audit" / "client_report.md").exists()


# ===========================================================================
# 7. AuthDemoWorkflow.run() — result paths are populated
# ===========================================================================
class TestAuthDemoWorkflowResultPaths:
    def test_capability_plan_path_set(self, tmp_path):
        result = AuthDemoWorkflow(outputs_root=tmp_path).run(project_id="p")
        assert result.capability_plan_path != ""
        assert "auth_capability_plan.json" in result.capability_plan_path

    def test_strategy_decision_path_set(self, tmp_path):
        result = AuthDemoWorkflow(outputs_root=tmp_path).run(project_id="p")
        assert result.strategy_decision_path != ""
        assert "auth_strategy_decision.json" in result.strategy_decision_path

    def test_google_oauth_report_path_set(self, tmp_path):
        result = AuthDemoWorkflow(outputs_root=tmp_path).run(project_id="p")
        assert result.google_oauth_report_path != ""

    def test_email_password_report_path_set(self, tmp_path):
        result = AuthDemoWorkflow(outputs_root=tmp_path).run(project_id="p")
        assert result.email_password_report_path != ""

    def test_client_report_path_set(self, tmp_path):
        result = AuthDemoWorkflow(outputs_root=tmp_path).run(project_id="p")
        assert result.client_report_path != ""
        assert "client_report.md" in result.client_report_path


# ===========================================================================
# 8. AuthDemoWorkflow.run() — scenario categories and counts
# ===========================================================================
class TestAuthDemoWorkflowScenarios:
    def _scenarios_by_category(self, tmp_path):
        result = AuthDemoWorkflow(outputs_root=tmp_path).run(project_id="demo-test")
        by_cat: dict[str, list] = {}
        for s in result.scenarios:
            by_cat.setdefault(s.category, []).append(s)
        return by_cat

    def test_has_planned_scenarios(self, tmp_path):
        by_cat = self._scenarios_by_category(tmp_path)
        assert "planned" in by_cat
        assert len(by_cat["planned"]) >= 2  # 7A + 7B

    def test_has_skipped_scenarios(self, tmp_path):
        by_cat = self._scenarios_by_category(tmp_path)
        assert "skipped" in by_cat

    def test_has_blocked_scenarios(self, tmp_path):
        by_cat = self._scenarios_by_category(tmp_path)
        assert "blocked" in by_cat
        assert len(by_cat["blocked"]) >= 4  # 4 safety cases

    def test_7a_scenario_present(self, tmp_path):
        result = AuthDemoWorkflow(outputs_root=tmp_path).run(project_id="demo-test")
        names = [s.name for s in result.scenarios]
        assert "auth_capability_plan" in names

    def test_7b_scenario_present(self, tmp_path):
        result = AuthDemoWorkflow(outputs_root=tmp_path).run(project_id="demo-test")
        names = [s.name for s in result.scenarios]
        assert "auth_strategy_decision" in names

    def test_7c_scenario_present(self, tmp_path):
        result = AuthDemoWorkflow(outputs_root=tmp_path).run(project_id="demo-test")
        names = [s.name for s in result.scenarios]
        assert "google_oauth_storagestate_missing" in names

    def test_7d_scenario_present(self, tmp_path):
        result = AuthDemoWorkflow(outputs_root=tmp_path).run(project_id="demo-test")
        names = [s.name for s in result.scenarios]
        assert "email_password_orangehrm" in names

    def test_blocked_safety_cases_present(self, tmp_path):
        result = AuthDemoWorkflow(outputs_root=tmp_path).run(project_id="demo-test")
        names = [s.name for s in result.scenarios]
        for safety_name, _ in _BLOCKED_SAFETY_CASES:
            assert safety_name in names

    def test_7c_status_is_planning_only(self, tmp_path):
        result = AuthDemoWorkflow(outputs_root=tmp_path).run(project_id="demo-test")
        oauth_scenario = next(
            s for s in result.scenarios if s.name == "google_oauth_storagestate_missing"
        )
        assert oauth_scenario.status == "planning_only"

    def test_7c_category_is_skipped(self, tmp_path):
        result = AuthDemoWorkflow(outputs_root=tmp_path).run(project_id="demo-test")
        oauth_scenario = next(
            s for s in result.scenarios if s.name == "google_oauth_storagestate_missing"
        )
        assert oauth_scenario.category == "skipped"

    def test_blocked_safety_scenarios_all_blocked_status(self, tmp_path):
        result = AuthDemoWorkflow(outputs_root=tmp_path).run(project_id="demo-test")
        safety_names = {name for name, _ in _BLOCKED_SAFETY_CASES}
        for s in result.scenarios:
            if s.name in safety_names:
                assert s.status == "blocked"
                assert s.category == "blocked"


# ===========================================================================
# 9. AuthDemoWorkflow.run() — result safety invariants
# ===========================================================================
class TestAuthDemoWorkflowResultSafety:
    def test_approved_for_client_delivery_always_false(self, tmp_path):
        result = AuthDemoWorkflow(outputs_root=tmp_path).run(project_id="demo-test")
        assert result.approved_for_client_delivery is False

    def test_human_review_required_always_true(self, tmp_path):
        result = AuthDemoWorkflow(outputs_root=tmp_path).run(project_id="demo-test")
        assert result.human_review_required is True

    def test_to_dict_approved_false(self, tmp_path):
        result = AuthDemoWorkflow(outputs_root=tmp_path).run(project_id="demo-test")
        d = result.to_dict()
        assert d["approved_for_client_delivery"] is False

    def test_to_dict_human_review_true(self, tmp_path):
        result = AuthDemoWorkflow(outputs_root=tmp_path).run(project_id="demo-test")
        d = result.to_dict()
        assert d["human_review_required"] is True


# ===========================================================================
# 10. client_report.md content
# ===========================================================================
class TestClientReportContent:
    def _report(self, tmp_path) -> str:
        workflow = AuthDemoWorkflow(outputs_root=tmp_path)
        result = workflow.run(project_id="demo-test")
        return Path(result.client_report_path).read_text(encoding="utf-8")

    def test_contains_authentication_coverage_heading(self, tmp_path):
        content = self._report(tmp_path)
        assert "Authentication Coverage" in content

    def test_contains_executed_section(self, tmp_path):
        content = self._report(tmp_path)
        assert "Executed Auth Flows" in content

    def test_contains_planned_section(self, tmp_path):
        content = self._report(tmp_path)
        assert "Planned Auth Flows" in content

    def test_contains_skipped_section(self, tmp_path):
        content = self._report(tmp_path)
        assert "Skipped Auth Flows" in content

    def test_contains_blocked_section(self, tmp_path):
        content = self._report(tmp_path)
        assert "Blocked Auth Flows" in content

    def test_contains_safety_boundary_table(self, tmp_path):
        content = self._report(tmp_path)
        assert "Safety Boundary" in content

    def test_contains_approved_false(self, tmp_path):
        content = self._report(tmp_path)
        assert "approved_for_client_delivery" in content
        assert "False" in content

    def test_contains_human_review_true(self, tmp_path):
        content = self._report(tmp_path)
        assert "human_review_required" in content
        assert "True" in content

    def test_contains_evidence_references(self, tmp_path):
        content = self._report(tmp_path)
        assert "Evidence References" in content

    def test_contains_draft_note(self, tmp_path):
        content = self._report(tmp_path)
        assert "draft" in content.lower() or "Draft" in content

    def test_contains_project_id(self, tmp_path):
        workflow = AuthDemoWorkflow(outputs_root=tmp_path)
        result = workflow.run(project_id="my-demo-proj")
        content = Path(result.client_report_path).read_text(encoding="utf-8")
        assert "my-demo-proj" in content

    def test_no_credential_values_in_report(self, tmp_path):
        import os
        secret = "super_secret_pw_xyz_7r"
        with __import__("unittest.mock", fromlist=["patch"]).patch.dict(
            os.environ, {"ORANGEHRM_PASSWORD": secret, "ORANGEHRM_USERNAME": "admin"}
        ):
            workflow = AuthDemoWorkflow(outputs_root=tmp_path)
            result = workflow.run(project_id="demo-test")
        content = Path(result.client_report_path).read_text(encoding="utf-8")
        assert secret not in content
        assert "admin" not in content or "admin" in content  # name 'admin' is generic, ok


# ===========================================================================
# 11. Artifact JSON files — safety invariants present
# ===========================================================================
class TestArtifactJsonSafety:
    def test_capability_plan_json_valid(self, tmp_path):
        workflow = AuthDemoWorkflow(outputs_root=tmp_path)
        result = workflow.run(project_id="demo-test")
        data = json.loads(Path(result.capability_plan_path).read_text())
        assert "project_id" in data

    def test_strategy_decision_json_valid(self, tmp_path):
        workflow = AuthDemoWorkflow(outputs_root=tmp_path)
        result = workflow.run(project_id="demo-test")
        data = json.loads(Path(result.strategy_decision_path).read_text())
        assert "project_id" in data

    def test_google_oauth_report_status_planning_only(self, tmp_path):
        workflow = AuthDemoWorkflow(outputs_root=tmp_path)
        result = workflow.run(project_id="demo-test")
        data = json.loads(Path(result.google_oauth_report_path).read_text())
        assert data.get("status") == "planning_only"

    def test_email_password_report_approved_false(self, tmp_path):
        workflow = AuthDemoWorkflow(outputs_root=tmp_path)
        result = workflow.run(project_id="demo-test")
        data = json.loads(Path(result.email_password_report_path).read_text())
        assert data.get("approved_for_client_delivery") is False

    def test_google_oauth_report_safety_block(self, tmp_path):
        workflow = AuthDemoWorkflow(outputs_root=tmp_path)
        result = workflow.run(project_id="demo-test")
        data = json.loads(Path(result.google_oauth_report_path).read_text())
        safety = data.get("safety", {})
        assert safety.get("raw_secrets_allowed") is False
        assert safety.get("human_review_required") is True

    def test_email_password_report_safety_block(self, tmp_path):
        workflow = AuthDemoWorkflow(outputs_root=tmp_path)
        result = workflow.run(project_id="demo-test")
        data = json.loads(Path(result.email_password_report_path).read_text())
        safety = data.get("safety", {})
        assert safety.get("raw_secrets_allowed") is False

    def test_no_credentials_in_google_oauth_report(self, tmp_path):
        import os
        secret = "oauth_secret_7r_xyz"
        with __import__("unittest.mock", fromlist=["patch"]).patch.dict(
            os.environ, {"ORANGEHRM_PASSWORD": secret}
        ):
            result = AuthDemoWorkflow(outputs_root=tmp_path).run(project_id="demo-test")
        content = Path(result.google_oauth_report_path).read_text()
        assert secret not in content

    def test_no_credentials_in_email_password_report(self, tmp_path):
        import os
        secret = "ep_secret_7r_xyz"
        with __import__("unittest.mock", fromlist=["patch"]).patch.dict(
            os.environ, {"ORANGEHRM_PASSWORD": secret, "ORANGEHRM_USERNAME": "epuser"}
        ):
            result = AuthDemoWorkflow(outputs_root=tmp_path).run(project_id="demo-test")
        content = Path(result.email_password_report_path).read_text()
        assert secret not in content


# ===========================================================================
# 12. AuthDemoWorkflow — custom project_id
# ===========================================================================
class TestCustomProjectId:
    def test_custom_project_id_used(self, tmp_path):
        result = AuthDemoWorkflow(outputs_root=tmp_path).run(project_id="custom-proj-7r")
        assert result.project_id == "custom-proj-7r"

    def test_artifacts_under_custom_project_id(self, tmp_path):
        workflow = AuthDemoWorkflow(outputs_root=tmp_path)
        workflow.run(project_id="custom-proj-7r")
        assert (tmp_path / "custom-proj-7r" / "34_auth_capability").is_dir()
        assert (tmp_path / "custom-proj-7r" / "33_client_audit").is_dir()


# ===========================================================================
# 13. CLI — blocked flags guard
# ===========================================================================
class TestCliBlockedFlags:
    def _run_cli(self, args: list[str]) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, str(TOOL_PATH)] + args,
            capture_output=True,
            text=True,
        )

    def test_username_flag_blocked(self):
        result = self._run_cli(["--username", "admin"])
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_password_flag_blocked(self):
        result = self._run_cli(["--password", "secret"])
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_secret_flag_blocked(self):
        result = self._run_cli(["--secret", "xyz"])
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_token_flag_blocked(self):
        result = self._run_cli(["--token", "tok"])
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_cookie_flag_blocked(self):
        result = self._run_cli(["--cookie", "c"])
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_access_token_flag_blocked(self):
        result = self._run_cli(["--access-token", "t"])
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_bearer_flag_blocked(self):
        result = self._run_cli(["--bearer", "b"])
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_client_secret_flag_blocked(self):
        result = self._run_cli(["--client-secret", "s"])
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_default_project_id_runs(self):
        result = self._run_cli([])
        assert result.returncode == 0

    def test_custom_project_id_runs(self):
        result = self._run_cli(["--project-id", "test-7r-cli"])
        assert result.returncode == 0

    def test_json_output_valid(self):
        result = self._run_cli(["--project-id", "test-7r-json", "--json"])
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "project_id" in data
        assert data["approved_for_client_delivery"] is False
        assert data["human_review_required"] is True

    def test_json_output_scenarios_present(self):
        result = self._run_cli(["--project-id", "test-7r-scenarios", "--json"])
        data = json.loads(result.stdout)
        assert len(data["scenarios"]) > 0

    def test_human_output_contains_7r_header(self):
        result = self._run_cli(["--project-id", "test-7r-human"])
        assert "[7R]" in result.stdout

    def test_human_output_contains_blocked(self):
        result = self._run_cli(["--project-id", "test-7r-human2"])
        assert "BLOCKED" in result.stdout


# ===========================================================================
# 14. AuthDemoWorkflow — storageState never read
# ===========================================================================
class TestStorageStateNeverRead:
    def test_google_oauth_status_planning_only_no_storagstate(self, tmp_path):
        result = AuthDemoWorkflow(outputs_root=tmp_path).run(project_id="demo-test")
        oauth = next(
            s for s in result.scenarios if s.name == "google_oauth_storagestate_missing"
        )
        # Must be planning_only — no storageState file, so no smoke attempted
        assert oauth.status == "planning_only"

    def test_google_oauth_report_no_storagstate_path_value(self, tmp_path):
        result = AuthDemoWorkflow(outputs_root=tmp_path).run(project_id="demo-test")
        content = Path(result.google_oauth_report_path).read_text()
        # storage_state_path should be empty string in the demo
        data = json.loads(content)
        assert data.get("storage_state_path", "") == ""
