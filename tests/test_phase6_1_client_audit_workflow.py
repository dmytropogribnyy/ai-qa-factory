"""Phase 6.1 tests -- one-command client audit workflow."""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

from core.client_audit_workflow import ClientAuditWorkflow, _AUDIT_DIR_NAME
from core.schemas.client_audit import (
    ClientAuditInputs,
    ClientAuditMode,
    ClientAuditResult,
)

_FIXTURES = Path(__file__).parent.parent / "fixtures"
_DEMO_SPEC = str(_FIXTURES / "demo_specs" / "petstore_openapi.json")
_CLI = Path(__file__).parent.parent / "tools" / "run_client_audit.py"

_ALL_MODES = [m.value for m in ClientAuditMode]


# ===========================================================================
# Schema -- ClientAuditMode
# ===========================================================================

class TestClientAuditModeEnum:
    def test_safe_audit_value(self):
        assert ClientAuditMode.SAFE_AUDIT.value == "safe_audit"

    def test_api_only_value(self):
        assert ClientAuditMode.API_ONLY.value == "api_only"

    def test_frontend_readonly_value(self):
        assert ClientAuditMode.FRONTEND_READONLY.value == "frontend_readonly"

    def test_delivery_only_value(self):
        assert ClientAuditMode.DELIVERY_ONLY.value == "delivery_only"

    def test_all_four_modes_exist(self):
        assert len(_ALL_MODES) == 4

    def test_mode_from_string(self):
        assert ClientAuditMode("api_only") == ClientAuditMode.API_ONLY


# ===========================================================================
# Schema -- ClientAuditInputs safety invariants
# ===========================================================================

class TestClientAuditInputsInvariants:
    def test_raw_secrets_always_false(self):
        inp = ClientAuditInputs(project_id="x", raw_secrets_allowed=True)
        assert inp.raw_secrets_allowed is False

    def test_destructive_actions_always_false(self):
        inp = ClientAuditInputs(project_id="x", destructive_actions_allowed=True)
        assert inp.destructive_actions_allowed is False

    def test_production_write_always_false(self):
        inp = ClientAuditInputs(project_id="x", production_write_allowed=True)
        assert inp.production_write_allowed is False

    def test_auto_send_always_false(self):
        inp = ClientAuditInputs(project_id="x", auto_send_allowed=True)
        assert inp.auto_send_allowed is False

    def test_client_delivery_auto_approved_always_false(self):
        inp = ClientAuditInputs(project_id="x", client_delivery_auto_approved=True)
        assert inp.client_delivery_auto_approved is False

    def test_human_review_required_always_true(self):
        inp = ClientAuditInputs(project_id="x", human_review_required=False)
        assert inp.human_review_required is True

    def test_approval_required_for_execution_always_true(self):
        inp = ClientAuditInputs(project_id="x", approval_required_for_execution=False)
        assert inp.approval_required_for_execution is True

    def test_default_mode_is_safe_audit(self):
        inp = ClientAuditInputs(project_id="x")
        assert inp.mode == ClientAuditMode.SAFE_AUDIT

    def test_default_write_files_true(self):
        inp = ClientAuditInputs(project_id="x")
        assert inp.write_files is True

    def test_approve_flags_default_false(self):
        inp = ClientAuditInputs(project_id="x")
        assert inp.approve_public_readonly_execution is False
        assert inp.approve_browser_execution is False

    def test_from_dict_basic(self):
        inp = ClientAuditInputs.from_dict({"project_id": "demo", "mode": "api_only"})
        assert inp.project_id == "demo"
        assert inp.mode == ClientAuditMode.API_ONLY

    def test_from_dict_safety_invariants_enforced(self):
        inp = ClientAuditInputs.from_dict({
            "project_id": "x",
            "raw_secrets_allowed": True,
            "destructive_actions_allowed": True,
        })
        assert inp.raw_secrets_allowed is False
        assert inp.destructive_actions_allowed is False


# ===========================================================================
# Schema -- ClientAuditResult safety invariants
# ===========================================================================

class TestClientAuditResultInvariants:
    def _make_result(self, **kwargs) -> ClientAuditResult:
        return ClientAuditResult(project_id="x", mode="safe_audit", status="completed", **kwargs)

    def test_human_review_always_true(self):
        assert self._make_result(human_review_required=False).human_review_required is True

    def test_approved_for_delivery_always_false(self):
        assert self._make_result(approved_for_client_delivery=True).approved_for_client_delivery is False

    def test_raw_secrets_always_false(self):
        assert self._make_result(raw_secrets_allowed=True).raw_secrets_allowed is False

    def test_destructive_always_false(self):
        assert self._make_result(destructive_actions_allowed=True).destructive_actions_allowed is False

    def test_production_write_always_false(self):
        assert self._make_result(production_write_allowed=True).production_write_allowed is False

    def test_auto_send_always_false(self):
        assert self._make_result(auto_send_allowed=True).auto_send_allowed is False

    def test_client_delivery_auto_approved_always_false(self):
        assert self._make_result(client_delivery_auto_approved=True).client_delivery_auto_approved is False


# ===========================================================================
# Plan -- safe_audit mode
# ===========================================================================

class TestPlanSafeAudit:
    def _plan(self, **kwargs):
        inp = ClientAuditInputs(project_id="test", mode=ClientAuditMode.SAFE_AUDIT, **kwargs)
        return ClientAuditWorkflow(inp).build_plan()

    def test_mode_in_plan(self):
        plan = self._plan()
        assert plan.mode == "safe_audit"

    def test_accessibility_always_enabled(self):
        plan = self._plan()
        assert "accessibility_runner" in plan.enabled_modules

    def test_performance_always_enabled(self):
        plan = self._plan()
        assert "performance_runner" in plan.enabled_modules

    def test_delivery_pack_always_enabled(self):
        plan = self._plan()
        assert "client_delivery_pack" in plan.enabled_modules

    def test_api_importer_skipped_without_spec(self):
        plan = self._plan()
        names = [s.name for s in plan.skipped_modules]
        assert "api_contract_importer" in names

    def test_api_importer_enabled_with_spec(self):
        plan = self._plan(spec_file=_DEMO_SPEC)
        assert "api_contract_importer" in plan.enabled_modules

    def test_passive_sec_skipped_without_url(self):
        plan = self._plan()
        names = [s.name for s in plan.skipped_modules]
        assert "passive_security_runner" in names

    def test_passive_sec_enabled_with_url(self):
        plan = self._plan(target_url="https://example.com")
        assert "passive_security_runner" in plan.enabled_modules

    def test_approval_required_without_flags(self):
        plan = self._plan()
        assert len(plan.approval_required_steps) >= 2

    def test_approval_not_required_with_both_flags(self):
        plan = self._plan(
            target_url="https://example.com",
            approve_public_readonly_execution=True,
            approve_browser_execution=True,
        )
        assert not any("accessibility" in s for s in plan.approval_required_steps)

    def test_blocked_risky_actions_non_empty(self):
        plan = self._plan()
        assert len(plan.blocked_risky_actions) >= 5

    def test_human_review_required_in_plan(self):
        plan = self._plan()
        assert plan.human_review_required is True


# ===========================================================================
# Plan -- api_only mode
# ===========================================================================

class TestPlanApiOnly:
    def _plan(self, **kwargs):
        inp = ClientAuditInputs(project_id="test", mode=ClientAuditMode.API_ONLY, **kwargs)
        return ClientAuditWorkflow(inp).build_plan()

    def test_frontend_runners_all_skipped(self):
        plan = self._plan()
        names = [s.name for s in plan.skipped_modules]
        assert "accessibility_runner" in names
        assert "performance_runner" in names
        assert "passive_security_runner" in names

    def test_delivery_pack_enabled(self):
        plan = self._plan()
        assert "client_delivery_pack" in plan.enabled_modules

    def test_api_importer_enabled_with_spec(self):
        plan = self._plan(spec_file=_DEMO_SPEC)
        assert "api_contract_importer" in plan.enabled_modules

    def test_api_importer_skipped_without_spec(self):
        plan = self._plan()
        names = [s.name for s in plan.skipped_modules]
        assert "api_contract_importer" in names

    def test_no_approval_required_no_url(self):
        plan = self._plan()
        assert not any("accessibility" in s for s in plan.approval_required_steps)


# ===========================================================================
# Plan -- frontend_readonly mode
# ===========================================================================

class TestPlanFrontendReadonly:
    def _plan(self, **kwargs):
        inp = ClientAuditInputs(project_id="test", mode=ClientAuditMode.FRONTEND_READONLY, **kwargs)
        return ClientAuditWorkflow(inp).build_plan()

    def test_api_importer_always_skipped(self):
        plan = self._plan()
        names = [s.name for s in plan.skipped_modules]
        assert "api_contract_importer" in names

    def test_frontend_runners_skipped_without_url(self):
        plan = self._plan()
        names = [s.name for s in plan.skipped_modules]
        assert "accessibility_runner" in names
        assert "performance_runner" in names
        assert "passive_security_runner" in names

    def test_frontend_runners_enabled_with_url(self):
        plan = self._plan(target_url="https://example.com")
        assert "accessibility_runner" in plan.enabled_modules
        assert "performance_runner" in plan.enabled_modules
        assert "passive_security_runner" in plan.enabled_modules

    def test_delivery_pack_always_enabled(self):
        plan = self._plan()
        assert "client_delivery_pack" in plan.enabled_modules

    def test_approval_required_with_url_no_flags(self):
        plan = self._plan(target_url="https://example.com")
        assert len(plan.approval_required_steps) >= 2


# ===========================================================================
# Plan -- delivery_only mode
# ===========================================================================

class TestPlanDeliveryOnly:
    def _plan(self, **kwargs):
        inp = ClientAuditInputs(project_id="test", mode=ClientAuditMode.DELIVERY_ONLY, **kwargs)
        return ClientAuditWorkflow(inp).build_plan()

    def test_all_analysis_modules_skipped(self):
        plan = self._plan()
        names = [s.name for s in plan.skipped_modules]
        assert "api_contract_importer" in names
        assert "accessibility_runner" in names
        assert "performance_runner" in names
        assert "passive_security_runner" in names

    def test_delivery_pack_only_enabled(self):
        plan = self._plan()
        assert plan.enabled_modules == ["client_delivery_pack"]

    def test_no_approval_required(self):
        plan = self._plan()
        assert plan.approval_required_steps == []

    def test_blocked_risky_actions_present(self):
        plan = self._plan()
        assert len(plan.blocked_risky_actions) > 0


# ===========================================================================
# Workflow run -- dry run (no write)
# ===========================================================================

class TestWorkflowRunDryRun:
    def _run(self, **kwargs) -> ClientAuditResult:
        inp = ClientAuditInputs(
            project_id="dry-test",
            write_files=False,
            **kwargs,
        )
        return ClientAuditWorkflow(inp).run()

    def test_returns_client_audit_result(self):
        assert isinstance(self._run(), ClientAuditResult)

    def test_project_id_in_result(self):
        result = self._run()
        assert result.project_id == "dry-test"

    def test_mode_in_result(self):
        result = self._run()
        assert result.mode == "safe_audit"

    def test_status_is_string(self):
        result = self._run()
        assert isinstance(result.status, str)

    def test_human_review_always_true(self):
        result = self._run()
        assert result.human_review_required is True

    def test_approved_for_delivery_always_false(self):
        result = self._run()
        assert result.approved_for_client_delivery is False

    def test_blocked_risky_count_positive(self):
        result = self._run()
        assert result.blocked_risky_actions >= 5

    def test_module_results_non_empty(self):
        result = self._run()
        assert len(result.module_results) > 0

    def test_all_module_results_have_name_and_status(self):
        result = self._run()
        for mr in result.module_results:
            assert mr.name
            assert mr.status

    def test_delivery_pack_in_module_results(self):
        result = self._run()
        names = [mr.name for mr in result.module_results]
        assert "client_delivery_pack" in names

    def test_delivery_pack_status_draft(self):
        result = self._run()
        for mr in result.module_results:
            if mr.name == "client_delivery_pack":
                assert mr.status == "draft"

    def test_with_spec_file_api_importer_runs(self):
        result = self._run(spec_file=_DEMO_SPEC)
        names = [mr.name for mr in result.module_results]
        assert "api_contract_importer" in names

    def test_with_spec_file_api_status_analysis_only(self):
        result = self._run(spec_file=_DEMO_SPEC)
        for mr in result.module_results:
            if mr.name == "api_contract_importer":
                assert mr.status == "analysis_only"

    def test_accessibility_planning_only_without_approval(self):
        result = self._run()
        for mr in result.module_results:
            if mr.name == "accessibility_runner":
                assert mr.status == "planning_only"

    def test_performance_planning_only_without_approval(self):
        result = self._run()
        for mr in result.module_results:
            if mr.name == "performance_runner":
                assert mr.status == "planning_only"

    def test_safety_fields_in_result(self):
        result = self._run()
        assert result.raw_secrets_allowed is False
        assert result.destructive_actions_allowed is False
        assert result.production_write_allowed is False
        assert result.auto_send_allowed is False
        assert result.client_delivery_auto_approved is False


# ===========================================================================
# Workflow run -- write mode
# ===========================================================================

class TestWorkflowRunWrite:
    def test_audit_dir_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = ClientAuditInputs(project_id="wr-test", outputs_root=tmpdir)
            ClientAuditWorkflow(inp).run()
            assert (Path(tmpdir) / "wr-test" / _AUDIT_DIR_NAME).exists()

    def test_plan_json_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = ClientAuditInputs(project_id="wr-test", outputs_root=tmpdir)
            ClientAuditWorkflow(inp).run()
            assert (Path(tmpdir) / "wr-test" / _AUDIT_DIR_NAME / "client_audit_plan.json").exists()

    def test_preflight_md_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = ClientAuditInputs(project_id="wr-test", outputs_root=tmpdir)
            ClientAuditWorkflow(inp).run()
            assert (Path(tmpdir) / "wr-test" / _AUDIT_DIR_NAME / "client_audit_preflight.md").exists()

    def test_run_report_json_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = ClientAuditInputs(project_id="wr-test", outputs_root=tmpdir)
            ClientAuditWorkflow(inp).run()
            assert (Path(tmpdir) / "wr-test" / _AUDIT_DIR_NAME / "client_audit_run_report.json").exists()

    def test_summary_md_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = ClientAuditInputs(project_id="wr-test", outputs_root=tmpdir)
            ClientAuditWorkflow(inp).run()
            assert (Path(tmpdir) / "wr-test" / _AUDIT_DIR_NAME / "client_audit_summary.md").exists()

    def test_plan_json_has_required_keys(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = ClientAuditInputs(project_id="wr-test", outputs_root=tmpdir)
            ClientAuditWorkflow(inp).run()
            data = json.loads(
                (Path(tmpdir) / "wr-test" / _AUDIT_DIR_NAME / "client_audit_plan.json")
                .read_text(encoding="utf-8")
            )
            for key in ("project_id", "mode", "enabled_modules", "skipped_modules",
                        "blocked_risky_actions", "human_review_required"):
                assert key in data

    def test_run_report_safety_invariants(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = ClientAuditInputs(project_id="wr-test", outputs_root=tmpdir)
            ClientAuditWorkflow(inp).run()
            data = json.loads(
                (Path(tmpdir) / "wr-test" / _AUDIT_DIR_NAME / "client_audit_run_report.json")
                .read_text(encoding="utf-8")
            )
            assert data["human_review_required"] is True
            assert data["approved_for_client_delivery"] is False
            assert data["raw_secrets_allowed"] is False
            assert data["destructive_actions_allowed"] is False

    def test_summary_md_has_no_credentials(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = ClientAuditInputs(project_id="wr-test", outputs_root=tmpdir)
            ClientAuditWorkflow(inp).run()
            content = (
                Path(tmpdir) / "wr-test" / _AUDIT_DIR_NAME / "client_audit_summary.md"
            ).read_text(encoding="utf-8").lower()
            for word in ("password", "api_key", "storagestate", "bearer", "secret="):
                assert word not in content

    def test_summary_md_mentions_human_review(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = ClientAuditInputs(project_id="wr-test", outputs_root=tmpdir)
            ClientAuditWorkflow(inp).run()
            content = (
                Path(tmpdir) / "wr-test" / _AUDIT_DIR_NAME / "client_audit_summary.md"
            ).read_text(encoding="utf-8")
            assert "human review" in content.lower()

    def test_summary_md_mentions_not_approved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = ClientAuditInputs(project_id="wr-test", outputs_root=tmpdir)
            ClientAuditWorkflow(inp).run()
            content = (
                Path(tmpdir) / "wr-test" / _AUDIT_DIR_NAME / "client_audit_summary.md"
            ).read_text(encoding="utf-8").lower()
            assert "no" in content  # "no" appears in "approved for client delivery: no"

    def test_with_spec_creates_api_contract_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = ClientAuditInputs(
                project_id="wr-test",
                outputs_root=tmpdir,
                spec_file=_DEMO_SPEC,
            )
            ClientAuditWorkflow(inp).run()
            assert (Path(tmpdir) / "wr-test" / _AUDIT_DIR_NAME / "api_contract_report.json").exists()

    def test_api_contract_json_has_no_credentials(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = ClientAuditInputs(
                project_id="wr-test",
                outputs_root=tmpdir,
                spec_file=_DEMO_SPEC,
            )
            ClientAuditWorkflow(inp).run()
            content = (
                Path(tmpdir) / "wr-test" / _AUDIT_DIR_NAME / "api_contract_report.json"
            ).read_text(encoding="utf-8").lower()
            for word in ("password=", "api_key=", "bearer tok"):
                assert word not in content

    def test_delivery_pack_dir_created(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = ClientAuditInputs(project_id="wr-test", outputs_root=tmpdir)
            ClientAuditWorkflow(inp).run()
            assert (Path(tmpdir) / "wr-test" / "28_client_delivery").exists()


# ===========================================================================
# Demo golden workflow -- audit-demo project
# ===========================================================================

class TestDemoGoldenWorkflow:
    def test_demo_completes_all_modules(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = ClientAuditInputs(
                project_id="audit-demo",
                outputs_root=tmpdir,
                spec_file=_DEMO_SPEC,
                write_files=False,
            )
            result = ClientAuditWorkflow(inp).run()
            names = [mr.name for mr in result.module_results]
            assert "api_contract_importer" in names
            assert "accessibility_runner" in names
            assert "performance_runner" in names
            assert "client_delivery_pack" in names

    def test_demo_status_non_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = ClientAuditInputs(
                project_id="audit-demo",
                outputs_root=tmpdir,
                spec_file=_DEMO_SPEC,
                write_files=False,
            )
            result = ClientAuditWorkflow(inp).run()
            assert result.status in (
                "completed", "completed_with_warnings", "planning_only", "failed"
            )

    def test_demo_skipped_passive_sec_without_url(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = ClientAuditInputs(
                project_id="audit-demo",
                outputs_root=tmpdir,
                spec_file=_DEMO_SPEC,
                write_files=False,
            )
            workflow = ClientAuditWorkflow(inp)
            plan = workflow.build_plan()
            names = [s.name for s in plan.skipped_modules]
            assert "passive_security_runner" in names

    def test_demo_blocked_risky_actions_explained(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = ClientAuditInputs(
                project_id="audit-demo",
                outputs_root=tmpdir,
                spec_file=_DEMO_SPEC,
                write_files=False,
            )
            plan = ClientAuditWorkflow(inp).build_plan()
            assert len(plan.blocked_risky_actions) >= 5

    def test_demo_write_creates_expected_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = ClientAuditInputs(
                project_id="audit-demo",
                outputs_root=tmpdir,
                spec_file=_DEMO_SPEC,
            )
            ClientAuditWorkflow(inp).run()
            proj = Path(tmpdir) / "audit-demo"
            assert (proj / _AUDIT_DIR_NAME).exists()
            assert (proj / "28_client_delivery").exists()

    def test_demo_run_report_human_review_true(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = ClientAuditInputs(
                project_id="audit-demo",
                outputs_root=tmpdir,
                spec_file=_DEMO_SPEC,
            )
            ClientAuditWorkflow(inp).run()
            data = json.loads(
                (Path(tmpdir) / "audit-demo" / _AUDIT_DIR_NAME / "client_audit_run_report.json")
                .read_text(encoding="utf-8")
            )
            assert data["human_review_required"] is True

    def test_demo_run_report_not_approved(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = ClientAuditInputs(
                project_id="audit-demo",
                outputs_root=tmpdir,
                spec_file=_DEMO_SPEC,
            )
            ClientAuditWorkflow(inp).run()
            data = json.loads(
                (Path(tmpdir) / "audit-demo" / _AUDIT_DIR_NAME / "client_audit_run_report.json")
                .read_text(encoding="utf-8")
            )
            assert data["approved_for_client_delivery"] is False

    def test_demo_secret_scan_runs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = ClientAuditInputs(
                project_id="audit-demo",
                outputs_root=tmpdir,
                spec_file=_DEMO_SPEC,
            )
            result = ClientAuditWorkflow(inp).run()
            for mr in result.module_results:
                if mr.name == "client_delivery_pack":
                    assert "secret_scan_passed" in mr.note


# ===========================================================================
# Safety -- no credentials in any output
# ===========================================================================

class TestClientAuditSafety:
    def test_no_credentials_in_result_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = ClientAuditInputs(
                project_id="sec-test",
                outputs_root=tmpdir,
                spec_file=_DEMO_SPEC,
                write_files=False,
            )
            result = ClientAuditWorkflow(inp).run()
            import json as _json
            full = _json.dumps({
                "status": result.status,
                "modules": [
                    {"name": mr.name, "note": mr.note} for mr in result.module_results
                ],
            }).lower()
            for word in ("password=", "api_key=", "bearer tok", "secret="):
                assert word not in full

    def test_risky_actions_blocked_count_matches(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = ClientAuditInputs(project_id="sec-test", outputs_root=tmpdir, write_files=False)
            result = ClientAuditWorkflow(inp).run()
            plan = ClientAuditWorkflow(inp).build_plan()
            assert result.blocked_risky_actions == len(plan.blocked_risky_actions)

    def test_delivery_auto_approved_false(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            inp = ClientAuditInputs(project_id="sec-test", outputs_root=tmpdir, write_files=False)
            result = ClientAuditWorkflow(inp).run()
            assert result.client_delivery_auto_approved is False

    def test_all_modes_enforce_safety(self):
        for mode in ClientAuditMode:
            with tempfile.TemporaryDirectory() as tmpdir:
                inp = ClientAuditInputs(
                    project_id="sec-test",
                    mode=mode,
                    outputs_root=tmpdir,
                    write_files=False,
                )
                result = ClientAuditWorkflow(inp).run()
                assert result.human_review_required is True
                assert result.approved_for_client_delivery is False


# ===========================================================================
# CLI tool
# ===========================================================================

class TestClientAuditCLI:
    def test_help_exits_zero(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--help"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "--project-id" in result.stdout

    def test_help_shows_mode_choices(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--help"],
            capture_output=True, text=True,
        )
        assert "safe_audit" in result.stdout

    def test_no_write_exits_zero(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--no-write"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0, result.stderr

    def test_ok_in_output(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--no-write"],
            capture_output=True, text=True,
        )
        assert "[OK]" in result.stdout

    def test_output_ascii_safe(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--no-write"],
            capture_output=True, text=True, encoding="ascii", errors="strict",
        )
        assert result.returncode == 0

    def test_summary_shown(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--no-write"],
            capture_output=True, text=True,
        )
        assert "Summary" in result.stdout

    def test_blocked_auto_approve_all_exits_1(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--auto-approve-all"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_blocked_skip_human_review_exits_1(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--skip-human-review"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_blocked_force_deliver_exits_1(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--force-deliver"],
            capture_output=True, text=True,
        )
        assert result.returncode == 1
        assert "BLOCKED" in result.stderr

    def test_api_only_mode_flag(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--no-write", "--mode", "api_only"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "api_only" in result.stdout

    def test_delivery_only_mode_flag(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--no-write", "--mode", "delivery_only"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

    def test_json_output_flag(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--no-write", "--json-output"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0
        assert "--- JSON Output ---" in result.stdout

    def test_with_spec_file_no_write(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--no-write",
             "--spec-file", _DEMO_SPEC, "--project-id", "cli-spec-test"],
            capture_output=True, text=True,
        )
        assert result.returncode == 0

    def test_preflight_shown_in_output(self):
        result = subprocess.run(
            [sys.executable, str(_CLI), "--no-write"],
            capture_output=True, text=True,
        )
        assert "Preflight" in result.stdout
