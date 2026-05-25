"""Tests — Phase 4ABC: Readiness, Evidence, Reporting, Delivery Preview, Scenario Evaluation.

Covers:
- Schema round-trips and safety defaults (exec approval, evidence, reporting, delivery, scenario)
- Defense-in-depth: ToolchainValidationReport.__post_init__ cannot be overridden
- ExecutionReadinessPlanner behavior
- EvidenceManager behavior
- ReportDraftBuilder behavior
- DeliveryPreviewBuilder behavior
- ScenarioBatchEvaluator behavior
- CLI tools (--no-write mode)
- Safety invariants throughout

SAFETY: No URL fetching, no browser execution, no credentials, no external calls.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ROOT = Path(__file__).parent.parent


def _make_project(tmp_path: Path, project_id: str = "test-4abc") -> Path:
    """Create a minimal project artifact tree for testing."""
    base = tmp_path / "outputs" / project_id
    # Phase 2B
    proj_dir = base / "00_project"
    proj_dir.mkdir(parents=True)
    bp = {
        "project_id": project_id,
        "project_type": "web_saas",
        "environment_type": "staging",
        "target_application": {"url": "https://example.com"},
    }
    (proj_dir / "PROJECT_BLUEPRINT.json").write_text(json.dumps(bp), encoding="utf-8")

    # Phase 2C
    strat_dir = base / "02_strategy"
    strat_dir.mkdir(parents=True)
    st = {"project_id": project_id, "project_type": "web_saas", "summary": "Test strategy"}
    (strat_dir / "QA_STRATEGY.json").write_text(json.dumps(st), encoding="utf-8")

    # Phase 3A
    sc_dir = base / "03_framework" / "playwright"
    sc_dir.mkdir(parents=True)
    scaffold = {"project_id": project_id, "framework_type": "playwright", "execution_allowed": False}
    (sc_dir / "FRAMEWORK_SCAFFOLD.json").write_text(json.dumps(scaffold), encoding="utf-8")

    # Phase 3B
    static = {
        "project_id": project_id,
        "validation_status": "pass",
        "blocker_count": 0,
        "scaffold_root": str(sc_dir),
    }
    (sc_dir / "STATIC_VALIDATION_REPORT.json").write_text(json.dumps(static), encoding="utf-8")

    # Phase 3C
    toolchain = {
        "project_id": project_id,
        "validation_status": "pass",
        "scaffold_root": str(sc_dir),
        "safe_to_execute_tests": False,
        "browser_execution_performed": False,
        "external_url_used": False,
        "credentials_used": False,
    }
    (sc_dir / "TOOLCHAIN_VALIDATION_REPORT.json").write_text(json.dumps(toolchain), encoding="utf-8")
    (sc_dir / "TOOLCHAIN_COMMAND_LOG.md").write_text("# Command Log\nNo commands executed.", encoding="utf-8")

    return tmp_path


# ---------------------------------------------------------------------------
# 1. ToolchainValidationReport __post_init__ defense-in-depth
# ---------------------------------------------------------------------------

class TestToolchainValidationReportPostInit:
    def test_post_init_forces_invariants_on_construction(self):
        from core.schemas.toolchain_validation import ToolchainValidationReport
        r = ToolchainValidationReport(
            project_id="test",
            safe_to_execute_tests=True,
            browser_execution_performed=True,
            external_url_used=True,
            credentials_used=True,
        )
        assert r.safe_to_execute_tests is False
        assert r.browser_execution_performed is False
        assert r.external_url_used is False
        assert r.credentials_used is False

    def test_from_dict_cannot_rehydrate_safe_to_execute_tests_as_true(self):
        from core.schemas.toolchain_validation import ToolchainValidationReport
        data = {
            "project_id": "test",
            "safe_to_execute_tests": True,
            "browser_execution_performed": True,
            "external_url_used": True,
            "credentials_used": True,
        }
        r = ToolchainValidationReport.from_dict(data)
        assert r.safe_to_execute_tests is False
        assert r.browser_execution_performed is False
        assert r.external_url_used is False
        assert r.credentials_used is False

    def test_round_trip_preserves_other_fields(self):
        from core.schemas.toolchain_validation import ToolchainValidationReport
        r = ToolchainValidationReport(project_id="p1", validation_status="pass", approved=True)
        d = r.to_dict()
        r2 = ToolchainValidationReport.from_dict(d)
        assert r2.project_id == "p1"
        assert r2.validation_status == "pass"
        assert r2.approved is True
        assert r2.safe_to_execute_tests is False


# ---------------------------------------------------------------------------
# 2. Execution Approval Schemas
# ---------------------------------------------------------------------------

class TestExecutionApprovalSchemas:
    def test_requirement_defaults(self):
        from core.schemas.execution_approval import ExecutionApprovalRequirement
        r = ExecutionApprovalRequirement()
        assert r.approved is False
        assert r.blocks_execution is True

    def test_checklist_defaults(self):
        from core.schemas.execution_approval import ExecutionApprovalChecklist
        c = ExecutionApprovalChecklist()
        assert c.approved_for_execution is False
        assert c.approved_for_browser_execution is False
        assert c.approved_for_client_delivery is False
        assert c.target_url_approved is False
        assert c.destructive_actions_blocked is True

    def test_checklist_from_dict_blocks_approval_flags(self):
        from core.schemas.execution_approval import ExecutionApprovalChecklist
        data = {
            "project_id": "p",
            "approved_for_execution": True,
            "approved_for_browser_execution": True,
            "approved_for_client_delivery": True,
        }
        c = ExecutionApprovalChecklist.from_dict(data)
        assert c.approved_for_execution is False
        assert c.approved_for_browser_execution is False
        assert c.approved_for_client_delivery is False

    def test_checklist_round_trip(self):
        from core.schemas.execution_approval import ExecutionApprovalChecklist, ExecutionApprovalRequirement
        req = ExecutionApprovalRequirement(id="req1", name="Test", category="target_url")
        c = ExecutionApprovalChecklist(project_id="p1", requirements=[req])
        d = c.to_dict()
        c2 = ExecutionApprovalChecklist.from_dict(d)
        assert c2.project_id == "p1"
        assert len(c2.requirements) == 1
        assert c2.requirements[0].id == "req1"

    def test_readiness_report_defaults(self):
        from core.schemas.execution_approval import ExecutionReadinessReport
        r = ExecutionReadinessReport()
        assert r.approved_for_execution is False
        assert r.approved_for_browser_execution is False
        assert r.approved_for_target_url is False
        assert r.approved_for_credentials is False
        assert r.approved_for_external_calls is False
        assert r.approved_for_client_delivery is False
        assert r.evidence_plan_ready is False

    def test_readiness_report_from_dict_blocks_approval_flags(self):
        from core.schemas.execution_approval import ExecutionReadinessReport
        data = {
            "project_id": "p",
            "approved_for_execution": True,
            "approved_for_browser_execution": True,
            "approved_for_target_url": True,
            "approved_for_credentials": True,
            "approved_for_external_calls": True,
            "approved_for_client_delivery": True,
        }
        r = ExecutionReadinessReport.from_dict(data)
        assert r.approved_for_execution is False
        assert r.approved_for_browser_execution is False
        assert r.approved_for_target_url is False
        assert r.approved_for_credentials is False
        assert r.approved_for_external_calls is False
        assert r.approved_for_client_delivery is False

    def test_init_exports(self):
        from core.schemas import ExecutionApprovalRequirement, ExecutionApprovalChecklist, ExecutionReadinessReport
        assert ExecutionApprovalRequirement is not None
        assert ExecutionApprovalChecklist is not None
        assert ExecutionReadinessReport is not None


# ---------------------------------------------------------------------------
# 3. Evidence Schemas
# ---------------------------------------------------------------------------

class TestEvidenceSchemas:
    def test_record_defaults(self):
        from core.schemas.evidence import EvidenceRecord
        r = EvidenceRecord()
        assert r.client_visible is False
        assert r.internal_only is True
        assert r.requires_redaction is True
        assert r.redacted is False

    def test_collection_defaults(self):
        from core.schemas.evidence import EvidenceCollection
        c = EvidenceCollection()
        assert c.ready_for_client_review is False

    def test_collection_from_dict_blocks_ready_for_client_review(self):
        from core.schemas.evidence import EvidenceCollection
        data = {"project_id": "p", "ready_for_client_review": True}
        c = EvidenceCollection.from_dict(data)
        assert c.ready_for_client_review is False

    def test_collection_round_trip(self):
        from core.schemas.evidence import EvidenceCollection, EvidenceRecord
        rec = EvidenceRecord(id="ev_001", title="Test Record", evidence_type="validation_report")
        c = EvidenceCollection(project_id="p1", records=[rec])
        d = c.to_dict()
        c2 = EvidenceCollection.from_dict(d)
        assert c2.project_id == "p1"
        assert len(c2.records) == 1
        assert c2.records[0].id == "ev_001"

    def test_quality_gate_defaults(self):
        from core.schemas.evidence import EvidenceQualityGate
        g = EvidenceQualityGate()
        assert g.approved_for_client_view is False
        assert g.has_test_results is False
        assert g.has_screenshots is False
        assert g.has_traces is False

    def test_quality_gate_from_dict_blocks_approved_for_client_view(self):
        from core.schemas.evidence import EvidenceQualityGate
        g = EvidenceQualityGate.from_dict({"project_id": "p", "approved_for_client_view": True})
        assert g.approved_for_client_view is False

    def test_redaction_report_defaults(self):
        from core.schemas.evidence import EvidenceRedactionReport
        r = EvidenceRedactionReport()
        assert r.client_visible_blocked is True

    def test_init_exports(self):
        from core.schemas import EvidenceRecord, EvidenceCollection, EvidenceQualityGate, EvidenceRedactionReport
        assert EvidenceRecord is not None
        assert EvidenceCollection is not None
        assert EvidenceQualityGate is not None
        assert EvidenceRedactionReport is not None


# ---------------------------------------------------------------------------
# 4. Reporting Schemas
# ---------------------------------------------------------------------------

class TestReportingSchemas:
    def test_section_defaults(self):
        from core.schemas.reporting import ReportSection
        s = ReportSection()
        assert s.client_visible is False
        assert s.internal_only is True
        assert s.requires_review is True

    def test_draft_defaults(self):
        from core.schemas.reporting import ReportDraft
        d = ReportDraft()
        assert d.status == "draft"
        assert d.approved_for_delivery is False
        assert d.client_visible is False

    def test_draft_from_dict_blocks_approved_for_delivery(self):
        from core.schemas.reporting import ReportDraft
        d = ReportDraft.from_dict({"project_id": "p", "approved_for_delivery": True})
        assert d.approved_for_delivery is False

    def test_draft_round_trip_with_sections(self):
        from core.schemas.reporting import ReportDraft, ReportSection
        sec = ReportSection(id="s1", title="Disclaimer", content="DRAFT")
        d = ReportDraft(project_id="p1", sections=[sec])
        data = d.to_dict()
        d2 = ReportDraft.from_dict(data)
        assert d2.project_id == "p1"
        assert len(d2.sections) == 1
        assert d2.sections[0].id == "s1"

    def test_quality_checklist_defaults(self):
        from core.schemas.reporting import ReportQualityChecklist
        c = ReportQualityChecklist()
        assert c.client_ready is False
        assert c.approval_checked is False
        assert c.safe_to_deliver is False

    def test_quality_checklist_from_dict_blocks_delivery_flags(self):
        from core.schemas.reporting import ReportQualityChecklist
        c = ReportQualityChecklist.from_dict({
            "project_id": "p",
            "client_ready": True,
            "approval_checked": True,
            "safe_to_deliver": True,
        })
        assert c.client_ready is False
        assert c.approval_checked is False
        assert c.safe_to_deliver is False

    def test_delivery_note_defaults(self):
        from core.schemas.reporting import DeliveryNoteDraft
        n = DeliveryNoteDraft()
        assert n.status == "draft"
        assert n.approved_for_delivery is False
        assert n.client_visible is False

    def test_delivery_note_from_dict_blocks_approved_for_delivery(self):
        from core.schemas.reporting import DeliveryNoteDraft
        n = DeliveryNoteDraft.from_dict({"project_id": "p", "approved_for_delivery": True})
        assert n.approved_for_delivery is False

    def test_init_exports(self):
        from core.schemas import ReportSection, ReportDraft, ReportQualityChecklist, DeliveryNoteDraft
        assert ReportSection is not None
        assert ReportDraft is not None
        assert ReportQualityChecklist is not None
        assert DeliveryNoteDraft is not None


# ---------------------------------------------------------------------------
# 5. Delivery Preview Schemas
# ---------------------------------------------------------------------------

class TestDeliveryPreviewSchemas:
    def test_preview_item_defaults(self):
        from core.schemas.delivery_preview import DeliveryPreviewItem
        i = DeliveryPreviewItem()
        assert i.approved_for_delivery is False
        assert i.requires_redaction is True
        assert i.client_visible is False

    def test_package_preview_defaults(self):
        from core.schemas.delivery_preview import DeliveryPackagePreview
        p = DeliveryPackagePreview()
        assert p.package_created is False
        assert p.zip_created is False
        assert p.approved_for_delivery is False

    def test_package_preview_from_dict_blocks_creation_flags(self):
        from core.schemas.delivery_preview import DeliveryPackagePreview
        data = {
            "project_id": "p",
            "package_created": True,
            "zip_created": True,
            "approved_for_delivery": True,
        }
        p = DeliveryPackagePreview.from_dict(data)
        assert p.package_created is False
        assert p.zip_created is False
        assert p.approved_for_delivery is False

    def test_package_preview_round_trip(self):
        from core.schemas.delivery_preview import DeliveryPackagePreview, DeliveryPreviewItem
        item = DeliveryPreviewItem(id="item_001", title="Report", artifact_type="client_report")
        p = DeliveryPackagePreview(project_id="p1", items=[item])
        data = p.to_dict()
        p2 = DeliveryPackagePreview.from_dict(data)
        assert p2.project_id == "p1"
        assert len(p2.items) == 1
        assert p2.items[0].id == "item_001"

    def test_safety_checklist_defaults(self):
        from core.schemas.delivery_preview import DeliverySafetyChecklist
        c = DeliverySafetyChecklist()
        assert c.approved_for_delivery is False
        assert c.safe_to_package is False

    def test_safety_checklist_from_dict_blocks_delivery_flags(self):
        from core.schemas.delivery_preview import DeliverySafetyChecklist
        c = DeliverySafetyChecklist.from_dict({
            "project_id": "p",
            "approved_for_delivery": True,
            "safe_to_package": True,
        })
        assert c.approved_for_delivery is False
        assert c.safe_to_package is False

    def test_init_exports(self):
        from core.schemas import DeliveryPreviewItem, DeliveryPackagePreview, DeliverySafetyChecklist
        assert DeliveryPreviewItem is not None
        assert DeliveryPackagePreview is not None
        assert DeliverySafetyChecklist is not None


# ---------------------------------------------------------------------------
# 6. Scenario Evaluation Schemas
# ---------------------------------------------------------------------------

class TestScenarioEvaluationSchemas:
    def test_result_defaults(self):
        from core.schemas.scenario_evaluation import ScenarioEvaluationResult
        r = ScenarioEvaluationResult()
        assert r.status == "pass"
        assert r.safety_expectations_present is False
        assert r.no_execution_confirmed is False

    def test_batch_report_defaults(self):
        from core.schemas.scenario_evaluation import ScenarioBatchEvaluationReport
        r = ScenarioBatchEvaluationReport()
        assert r.evaluation_performed_without_execution is True
        assert r.external_calls_performed is False

    def test_batch_report_from_dict_enforces_invariants(self):
        from core.schemas.scenario_evaluation import ScenarioBatchEvaluationReport
        data = {
            "project_id": "p",
            "evaluation_performed_without_execution": False,
            "external_calls_performed": True,
        }
        r = ScenarioBatchEvaluationReport.from_dict(data)
        assert r.evaluation_performed_without_execution is True
        assert r.external_calls_performed is False

    def test_batch_report_round_trip(self):
        from core.schemas.scenario_evaluation import ScenarioBatchEvaluationReport, ScenarioEvaluationResult
        result = ScenarioEvaluationResult(id="sc1", title="Test Scenario", status="pass")
        r = ScenarioBatchEvaluationReport(project_id="p1", results=[result], total_scenarios=1)
        d = r.to_dict()
        r2 = ScenarioBatchEvaluationReport.from_dict(d)
        assert r2.project_id == "p1"
        assert len(r2.results) == 1
        assert r2.results[0].id == "sc1"
        assert r2.external_calls_performed is False

    def test_init_exports(self):
        from core.schemas import ScenarioEvaluationResult, ScenarioBatchEvaluationReport
        assert ScenarioEvaluationResult is not None
        assert ScenarioBatchEvaluationReport is not None


# ---------------------------------------------------------------------------
# 7. ExecutionReadinessPlanner
# ---------------------------------------------------------------------------

class TestExecutionReadinessPlanner:
    def test_plan_readiness_returns_checklist_and_report(self, tmp_path):
        _make_project(tmp_path)
        from core.execution_readiness_planner import ExecutionReadinessPlanner
        planner = ExecutionReadinessPlanner(outputs_root=tmp_path / "outputs")
        checklist, report = planner.plan_readiness("test-4abc")
        assert checklist.project_id == "test-4abc"
        assert report.project_id == "test-4abc"

    def test_default_plan_blocks_execution(self, tmp_path):
        _make_project(tmp_path)
        from core.execution_readiness_planner import ExecutionReadinessPlanner
        _, report = ExecutionReadinessPlanner(outputs_root=tmp_path / "outputs").plan_readiness("test-4abc")
        assert report.approved_for_execution is False
        assert report.approved_for_browser_execution is False
        assert report.approved_for_client_delivery is False

    def test_target_url_requires_approval(self, tmp_path):
        _make_project(tmp_path)
        from core.execution_readiness_planner import ExecutionReadinessPlanner
        checklist, _ = ExecutionReadinessPlanner(outputs_root=tmp_path / "outputs").plan_readiness("test-4abc")
        assert checklist.target_url_approved is False
        req_names = [r.name for r in checklist.requirements]
        assert any("Target URL" in n for n in req_names)

    def test_credentials_require_approval(self, tmp_path):
        _make_project(tmp_path)
        from core.execution_readiness_planner import ExecutionReadinessPlanner
        checklist, _ = ExecutionReadinessPlanner(outputs_root=tmp_path / "outputs").plan_readiness("test-4abc")
        assert checklist.credentials_approved is False

    def test_evidence_plan_ready_when_artifacts_exist(self, tmp_path):
        _make_project(tmp_path)
        from core.execution_readiness_planner import ExecutionReadinessPlanner
        _, report = ExecutionReadinessPlanner(outputs_root=tmp_path / "outputs").plan_readiness("test-4abc")
        assert report.evidence_plan_ready is True

    def test_evidence_plan_not_ready_without_scaffold(self, tmp_path):
        from core.execution_readiness_planner import ExecutionReadinessPlanner
        # No project artifacts at all
        (tmp_path / "outputs").mkdir()
        _, report = ExecutionReadinessPlanner(outputs_root=tmp_path / "outputs").plan_readiness("empty-project")
        assert report.evidence_plan_ready is False

    def test_payment_requires_sandbox_when_ecommerce(self, tmp_path):
        _make_project(tmp_path, "test-4abc")
        bp = {"project_id": "test-4abc", "project_type": "ecommerce", "environment_type": "staging"}
        (tmp_path / "outputs" / "test-4abc" / "00_project" / "PROJECT_BLUEPRINT.json").write_text(
            json.dumps(bp), encoding="utf-8"
        )
        from core.execution_readiness_planner import ExecutionReadinessPlanner
        checklist, _ = ExecutionReadinessPlanner(outputs_root=tmp_path / "outputs").plan_readiness("test-4abc")
        categories = [r.category for r in checklist.requirements]
        assert "payment_sandbox" in categories

    def test_render_creates_artifacts(self, tmp_path):
        _make_project(tmp_path)
        from core.execution_readiness_planner import ExecutionReadinessPlanner
        planner = ExecutionReadinessPlanner(outputs_root=tmp_path / "outputs")
        checklist, report = planner.plan_readiness("test-4abc")
        paths = planner.render_execution_plan_artifacts(checklist, report, "test-4abc")
        assert "checklist_json" in paths
        assert paths["checklist_json"].exists()
        assert "readiness_md" in paths
        assert paths["readiness_md"].exists()

    def test_no_external_http_in_planner_source(self):
        """Planner source must not import urllib, requests, or httpx."""
        import ast
        src = (ROOT / "core" / "execution_readiness_planner.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        bad_modules = {"urllib", "requests", "httpx", "aiohttp"}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                all_names = [n.name for n in getattr(node, "names", [])]
                mod = getattr(node, "module", "") or ""
                assert not any(b in mod for b in bad_modules), f"Forbidden import: {mod}"
                assert not any(b in n for b in bad_modules for n in all_names), f"Forbidden import: {all_names}"


# ---------------------------------------------------------------------------
# 8. EvidenceManager
# ---------------------------------------------------------------------------

class TestEvidenceManager:
    def test_build_evidence_foundation_returns_triple(self, tmp_path):
        _make_project(tmp_path)
        from core.evidence_manager import EvidenceManager
        collection, gate, redaction = EvidenceManager(outputs_root=tmp_path / "outputs").build_evidence_foundation("test-4abc")
        assert collection.project_id == "test-4abc"
        assert gate.project_id == "test-4abc"
        assert redaction.project_id == "test-4abc"

    def test_all_evidence_internal_only(self, tmp_path):
        _make_project(tmp_path)
        from core.evidence_manager import EvidenceManager
        collection, _, _ = EvidenceManager(outputs_root=tmp_path / "outputs").build_evidence_foundation("test-4abc")
        for r in collection.records:
            assert r.client_visible is False, f"Record {r.id} should not be client_visible"
            assert r.internal_only is True

    def test_quality_gate_not_approved_by_default(self, tmp_path):
        _make_project(tmp_path)
        from core.evidence_manager import EvidenceManager
        _, gate, _ = EvidenceManager(outputs_root=tmp_path / "outputs").build_evidence_foundation("test-4abc")
        assert gate.approved_for_client_view is False
        assert gate.has_test_results is False
        assert gate.has_screenshots is False
        assert gate.has_traces is False

    def test_redaction_report_blocks_client_visibility(self, tmp_path):
        _make_project(tmp_path)
        from core.evidence_manager import EvidenceManager
        _, _, redaction = EvidenceManager(outputs_root=tmp_path / "outputs").build_evidence_foundation("test-4abc")
        assert redaction.client_visible_blocked is True

    def test_ready_for_client_review_always_false(self, tmp_path):
        _make_project(tmp_path)
        from core.evidence_manager import EvidenceManager
        collection, _, _ = EvidenceManager(outputs_root=tmp_path / "outputs").build_evidence_foundation("test-4abc")
        assert collection.ready_for_client_review is False

    def test_render_creates_artifacts(self, tmp_path):
        _make_project(tmp_path)
        from core.evidence_manager import EvidenceManager
        mgr = EvidenceManager(outputs_root=tmp_path / "outputs")
        collection, gate, redaction = mgr.build_evidence_foundation("test-4abc")
        paths = mgr.render_evidence_artifacts(collection, gate, redaction, "test-4abc")
        assert "manifest_json" in paths
        assert paths["manifest_json"].exists()
        assert "quality_gate_md" in paths
        assert paths["summary_md"].exists()

    def test_registers_existing_artifacts(self, tmp_path):
        _make_project(tmp_path)
        from core.evidence_manager import EvidenceManager
        collection, _, _ = EvidenceManager(outputs_root=tmp_path / "outputs").build_evidence_foundation("test-4abc")
        assert len(collection.records) > 0
        types = {r.evidence_type for r in collection.records}
        assert "validation_report" in types or "scaffold_metadata" in types


# ---------------------------------------------------------------------------
# 9. ReportDraftBuilder
# ---------------------------------------------------------------------------

class TestReportDraftBuilder:
    def test_build_returns_four_artifacts(self, tmp_path):
        _make_project(tmp_path)
        from core.report_draft_builder import ReportDraftBuilder
        internal, client, note, checklist = ReportDraftBuilder(outputs_root=tmp_path / "outputs").build_report_drafts("test-4abc")
        assert internal.report_type == "internal_qa_summary"
        assert client.report_type == "client_report"
        assert note.project_id == "test-4abc"
        assert checklist.project_id == "test-4abc"

    def test_client_report_is_draft(self, tmp_path):
        _make_project(tmp_path)
        from core.report_draft_builder import ReportDraftBuilder
        _, client, _, _ = ReportDraftBuilder(outputs_root=tmp_path / "outputs").build_report_drafts("test-4abc")
        assert client.status == "draft"
        assert client.approved_for_delivery is False

    def test_client_report_says_no_execution(self, tmp_path):
        _make_project(tmp_path)
        from core.report_draft_builder import ReportDraftBuilder
        _, client, _, _ = ReportDraftBuilder(outputs_root=tmp_path / "outputs").build_report_drafts("test-4abc")
        all_content = " ".join(s.content.lower() for s in client.sections)
        assert "no browser" in all_content or "no target" in all_content or "not approved" in all_content

    def test_client_report_draft_disclaimer(self, tmp_path):
        _make_project(tmp_path)
        from core.report_draft_builder import ReportDraftBuilder
        _, client, _, _ = ReportDraftBuilder(outputs_root=tmp_path / "outputs").build_report_drafts("test-4abc")
        all_content = " ".join(s.content for s in client.sections)
        assert "DRAFT" in all_content

    def test_quality_checklist_defaults(self, tmp_path):
        _make_project(tmp_path)
        from core.report_draft_builder import ReportDraftBuilder
        _, _, _, checklist = ReportDraftBuilder(outputs_root=tmp_path / "outputs").build_report_drafts("test-4abc")
        assert checklist.client_ready is False
        assert checklist.safe_to_deliver is False
        assert checklist.approval_checked is False

    def test_no_raw_secrets_in_client_report(self, tmp_path):
        _make_project(tmp_path)
        from core.report_draft_builder import ReportDraftBuilder
        builder = ReportDraftBuilder(outputs_root=tmp_path / "outputs")
        paths = {}
        internal, client, note, checklist = builder.build_report_drafts("test-4abc")
        paths = builder.render_report_drafts(internal, client, note, checklist, "test-4abc")
        client_md = paths["client_md"].read_text(encoding="utf-8")
        secret_patterns = ["password=", "api_key=", "token=", "secret="]
        for pat in secret_patterns:
            assert pat not in client_md.lower(), f"Possible secret in client report: {pat}"

    def test_internal_only_not_in_client_sections(self, tmp_path):
        _make_project(tmp_path)
        from core.report_draft_builder import ReportDraftBuilder
        _, client, _, _ = ReportDraftBuilder(outputs_root=tmp_path / "outputs").build_report_drafts("test-4abc")
        for s in client.sections:
            assert not s.internal_only, f"Internal-only section found in client report: {s.id}"

    def test_render_creates_all_artifacts(self, tmp_path):
        _make_project(tmp_path)
        from core.report_draft_builder import ReportDraftBuilder
        builder = ReportDraftBuilder(outputs_root=tmp_path / "outputs")
        internal, client, note, checklist = builder.build_report_drafts("test-4abc")
        paths = builder.render_report_drafts(internal, client, note, checklist, "test-4abc")
        for key in ["internal_json", "internal_md", "client_json", "client_md",
                    "delivery_note_json", "delivery_note_md", "quality_json", "quality_md"]:
            assert key in paths, f"Missing path: {key}"
            assert paths[key].exists(), f"File not created: {paths[key]}"

    def test_delivery_note_not_approved(self, tmp_path):
        _make_project(tmp_path)
        from core.report_draft_builder import ReportDraftBuilder
        _, _, note, _ = ReportDraftBuilder(outputs_root=tmp_path / "outputs").build_report_drafts("test-4abc")
        assert note.approved_for_delivery is False
        assert note.status == "draft"


# ---------------------------------------------------------------------------
# 10. DeliveryPreviewBuilder
# ---------------------------------------------------------------------------

class TestDeliveryPreviewBuilder:
    def test_build_returns_preview_and_checklist(self, tmp_path):
        _make_project(tmp_path)
        from core.delivery_preview_builder import DeliveryPreviewBuilder
        preview, checklist = DeliveryPreviewBuilder(outputs_root=tmp_path / "outputs").build_delivery_preview("test-4abc")
        assert preview.project_id == "test-4abc"
        assert checklist.project_id == "test-4abc"

    def test_package_not_created(self, tmp_path):
        _make_project(tmp_path)
        from core.delivery_preview_builder import DeliveryPreviewBuilder
        preview, _ = DeliveryPreviewBuilder(outputs_root=tmp_path / "outputs").build_delivery_preview("test-4abc")
        assert preview.package_created is False
        assert preview.zip_created is False

    def test_approved_for_delivery_false(self, tmp_path):
        _make_project(tmp_path)
        from core.delivery_preview_builder import DeliveryPreviewBuilder
        preview, checklist = DeliveryPreviewBuilder(outputs_root=tmp_path / "outputs").build_delivery_preview("test-4abc")
        assert preview.approved_for_delivery is False
        assert checklist.approved_for_delivery is False

    def test_safe_to_package_false(self, tmp_path):
        _make_project(tmp_path)
        from core.delivery_preview_builder import DeliveryPreviewBuilder
        _, checklist = DeliveryPreviewBuilder(outputs_root=tmp_path / "outputs").build_delivery_preview("test-4abc")
        assert checklist.safe_to_package is False

    def test_excludes_internal_only_paths(self, tmp_path):
        _make_project(tmp_path)
        from core.delivery_preview_builder import DeliveryPreviewBuilder
        preview, _ = DeliveryPreviewBuilder(outputs_root=tmp_path / "outputs").build_delivery_preview("test-4abc")
        excluded_paths = [i.path for i in preview.excluded_items]
        assert any("99_internal" in p for p in excluded_paths) or any(
            "internal" in i.reason.lower() for i in preview.excluded_items
        )

    def test_no_real_package_files_created(self, tmp_path):
        _make_project(tmp_path)
        from core.delivery_preview_builder import DeliveryPreviewBuilder
        DeliveryPreviewBuilder(outputs_root=tmp_path / "outputs").build_delivery_preview("test-4abc")
        # No zip files should exist
        zip_files = list(tmp_path.rglob("*.zip"))
        tar_files = list(tmp_path.rglob("*.tar.gz"))
        assert len(zip_files) == 0
        assert len(tar_files) == 0

    def test_render_creates_artifacts(self, tmp_path):
        _make_project(tmp_path)
        from core.delivery_preview_builder import DeliveryPreviewBuilder
        builder = DeliveryPreviewBuilder(outputs_root=tmp_path / "outputs")
        preview, checklist = builder.build_delivery_preview("test-4abc")
        paths = builder.render_delivery_preview_artifacts(preview, checklist, "test-4abc")
        for key in ["preview_json", "preview_md", "safety_json", "safety_md"]:
            assert key in paths
            assert paths[key].exists()


# ---------------------------------------------------------------------------
# 11. ScenarioBatchEvaluator
# ---------------------------------------------------------------------------

class TestScenarioBatchEvaluator:
    def _get_evaluator(self, tmp_path=None):
        from core.scenario_batch_evaluator import ScenarioBatchEvaluator
        fixtures_root = ROOT / "fixtures" / "client_scenarios"
        if not fixtures_root.exists():
            pytest.skip("Fixtures not found")
        out_root = tmp_path / "outputs" if tmp_path else ROOT / "outputs"
        return ScenarioBatchEvaluator(fixtures_root=fixtures_root, outputs_root=out_root)

    def test_reads_local_fixtures_only(self, tmp_path):
        evaluator = self._get_evaluator(tmp_path)
        report = evaluator.evaluate_scenarios("test-eval")
        assert report.external_calls_performed is False
        assert report.evaluation_performed_without_execution is True

    def test_discovers_fixture_files(self, tmp_path):
        evaluator = self._get_evaluator(tmp_path)
        report = evaluator.evaluate_scenarios("test-eval")
        # We know there are 13 fixture .md files (excluding README.md)
        assert report.total_scenarios > 0

    def test_no_external_http_in_evaluator_source(self):
        import ast
        src = (ROOT / "core" / "scenario_batch_evaluator.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        bad_modules = {"urllib", "requests", "httpx", "aiohttp"}
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mod = getattr(node, "module", "") or ""
                assert not any(b in mod for b in bad_modules), f"Forbidden import: {mod}"

    def test_linear_scenario_task_source_rule_present(self, tmp_path):
        evaluator = self._get_evaluator(tmp_path)
        report = evaluator.evaluate_scenarios("test-eval")
        linear_results = [r for r in report.results if "linear" in r.scenario_path.lower()]
        if linear_results:
            r = linear_results[0]
            assert r.linear_task_source_rule_present is True, "Linear task_source rule missing"

    def test_amazon_high_risk_marketplace_rule(self, tmp_path):
        evaluator = self._get_evaluator(tmp_path)
        report = evaluator.evaluate_scenarios("test-eval")
        amazon_results = [r for r in report.results if "amazon" in r.scenario_path.lower()]
        if amazon_results:
            r = amazon_results[0]
            assert r.high_risk_marketplace_rule_present is True, "Amazon high-risk rules missing"

    def test_render_creates_artifacts(self, tmp_path):
        evaluator = self._get_evaluator(tmp_path)
        report = evaluator.evaluate_scenarios("test-eval")
        paths = evaluator.render_scenario_evaluation_artifacts(report, "test-eval")
        assert "evaluation_json" in paths
        assert paths["evaluation_json"].exists()
        assert "evaluation_md" in paths
        assert paths["evaluation_md"].exists()

    def test_evaluation_without_fixtures(self, tmp_path):
        from core.scenario_batch_evaluator import ScenarioBatchEvaluator
        empty_fixtures = tmp_path / "fixtures"
        empty_fixtures.mkdir()
        evaluator = ScenarioBatchEvaluator(fixtures_root=empty_fixtures, outputs_root=tmp_path / "outputs")
        report = evaluator.evaluate_scenarios("no-fixtures-project")
        assert report.total_scenarios == 0
        assert report.external_calls_performed is False


# ---------------------------------------------------------------------------
# 12. CLI tools
# ---------------------------------------------------------------------------

class TestCLITools:
    def test_plan_execution_no_write(self, tmp_path):
        _make_project(tmp_path)
        from tools.plan_execution import main
        code = main([
            "--project-id", "test-4abc",
            "--no-write",
            "--outputs-root", str(tmp_path / "outputs"),
        ])
        assert code == 0
        # No files should be written
        assert not (tmp_path / "outputs" / "test-4abc" / "04_execution_plan").exists()

    def test_plan_execution_json_output(self, tmp_path, capsys):
        _make_project(tmp_path)
        from tools.plan_execution import main
        code = main([
            "--project-id", "test-4abc",
            "--no-write",
            "--json",
            "--outputs-root", str(tmp_path / "outputs"),
        ])
        assert code == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "checklist" in data
        assert "readiness_report" in data
        assert data["readiness_report"]["approved_for_execution"] is False

    def test_plan_execution_writes_artifacts(self, tmp_path):
        _make_project(tmp_path)
        from tools.plan_execution import main
        code = main([
            "--project-id", "test-4abc",
            "--outputs-root", str(tmp_path / "outputs"),
        ])
        assert code == 0
        assert (tmp_path / "outputs" / "test-4abc" / "04_execution_plan" / "EXECUTION_APPROVAL_CHECKLIST.json").exists()

    def test_build_evidence_no_write(self, tmp_path):
        _make_project(tmp_path)
        from tools.build_evidence_foundation import main
        code = main([
            "--project-id", "test-4abc",
            "--no-write",
            "--outputs-root", str(tmp_path / "outputs"),
        ])
        assert code == 0

    def test_build_evidence_json_output(self, tmp_path, capsys):
        _make_project(tmp_path)
        from tools.build_evidence_foundation import main
        code = main([
            "--project-id", "test-4abc",
            "--no-write",
            "--json",
            "--outputs-root", str(tmp_path / "outputs"),
        ])
        assert code == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "collection" in data
        assert data["collection"]["ready_for_client_review"] is False

    def test_build_report_drafts_no_write(self, tmp_path):
        _make_project(tmp_path)
        from tools.build_report_drafts import main
        code = main([
            "--project-id", "test-4abc",
            "--no-write",
            "--outputs-root", str(tmp_path / "outputs"),
        ])
        assert code == 0

    def test_build_report_drafts_json_output(self, tmp_path, capsys):
        _make_project(tmp_path)
        from tools.build_report_drafts import main
        code = main([
            "--project-id", "test-4abc",
            "--no-write",
            "--json",
            "--outputs-root", str(tmp_path / "outputs"),
        ])
        assert code == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "client_report" in data
        assert data["client_report"]["approved_for_delivery"] is False
        assert data["quality_checklist"]["safe_to_deliver"] is False

    def test_build_delivery_preview_no_write(self, tmp_path):
        _make_project(tmp_path)
        from tools.build_delivery_preview import main
        code = main([
            "--project-id", "test-4abc",
            "--no-write",
            "--outputs-root", str(tmp_path / "outputs"),
        ])
        assert code == 0

    def test_build_delivery_preview_json_output(self, tmp_path, capsys):
        _make_project(tmp_path)
        from tools.build_delivery_preview import main
        code = main([
            "--project-id", "test-4abc",
            "--no-write",
            "--json",
            "--outputs-root", str(tmp_path / "outputs"),
        ])
        assert code == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert "delivery_package_preview" in data
        assert data["delivery_package_preview"]["package_created"] is False
        assert data["delivery_package_preview"]["zip_created"] is False

    def test_evaluate_scenarios_no_write(self, tmp_path):
        from tools.evaluate_scenarios import main
        fixtures_root = ROOT / "fixtures" / "client_scenarios"
        if not fixtures_root.exists():
            pytest.skip("Fixtures not found")
        code = main([
            "--project-id", "test-eval",
            "--no-write",
            "--fixtures-root", str(fixtures_root),
            "--outputs-root", str(tmp_path / "outputs"),
        ])
        assert code in (0, 1)  # 0=all pass, 1=blocked scenarios

    def test_evaluate_scenarios_json_output(self, tmp_path, capsys):
        from tools.evaluate_scenarios import main
        fixtures_root = ROOT / "fixtures" / "client_scenarios"
        if not fixtures_root.exists():
            pytest.skip("Fixtures not found")
        main([
            "--project-id", "test-eval",
            "--no-write",
            "--json",
            "--fixtures-root", str(fixtures_root),
            "--outputs-root", str(tmp_path / "outputs"),
        ])
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["external_calls_performed"] is False
        assert data["evaluation_performed_without_execution"] is True


# ---------------------------------------------------------------------------
# 13. Safety tests
# ---------------------------------------------------------------------------

class TestPhase4ABCSafetyInvariants:
    def test_no_subprocess_in_planner(self):
        src = (ROOT / "core" / "execution_readiness_planner.py").read_text(encoding="utf-8")
        assert "subprocess" not in src

    def test_no_subprocess_in_evidence_manager(self):
        src = (ROOT / "core" / "evidence_manager.py").read_text(encoding="utf-8")
        assert "subprocess" not in src

    def test_no_subprocess_in_report_builder(self):
        src = (ROOT / "core" / "report_draft_builder.py").read_text(encoding="utf-8")
        assert "subprocess" not in src

    def test_no_subprocess_in_delivery_builder(self):
        src = (ROOT / "core" / "delivery_preview_builder.py").read_text(encoding="utf-8")
        assert "subprocess" not in src

    def test_no_subprocess_in_scenario_evaluator(self):
        src = (ROOT / "core" / "scenario_batch_evaluator.py").read_text(encoding="utf-8")
        assert "subprocess" not in src

    def test_no_external_http_in_evidence_manager(self):
        src = (ROOT / "core" / "evidence_manager.py").read_text(encoding="utf-8")
        for forbidden in ["urllib", "requests", "httpx", "aiohttp", "urlopen"]:
            assert forbidden not in src

    def test_no_zipfile_in_delivery_builder(self):
        src = (ROOT / "core" / "delivery_preview_builder.py").read_text(encoding="utf-8")
        assert "zipfile" not in src
        assert "shutil.make_archive" not in src
        assert "tarfile" not in src

    def test_workbench_controller_has_phase4abc_methods(self):
        src = (ROOT / "core" / "workbench_controller.py").read_text(encoding="utf-8")
        for method in [
            "plan_execution_readiness",
            "render_execution_plan_artifacts",
            "build_evidence_foundation",
            "render_evidence_artifacts",
            "build_report_drafts",
            "render_report_drafts",
            "build_delivery_preview",
            "render_delivery_preview_artifacts",
            "evaluate_scenarios",
            "render_scenario_evaluation_artifacts",
        ]:
            assert method in src, f"WorkbenchController missing method: {method}"


# ---------------------------------------------------------------------------
# 14. WorkbenchController integration
# ---------------------------------------------------------------------------

class TestWorkbenchControllerPhase4:
    def test_plan_execution_readiness(self, tmp_path):
        _make_project(tmp_path)
        from core.workbench_controller import WorkbenchController
        wc = WorkbenchController(outputs_root=tmp_path / "outputs")
        checklist, report = wc.plan_execution_readiness("test-4abc")
        assert checklist.approved_for_execution is False
        assert report.approved_for_execution is False

    def test_build_evidence_foundation(self, tmp_path):
        _make_project(tmp_path)
        from core.workbench_controller import WorkbenchController
        wc = WorkbenchController(outputs_root=tmp_path / "outputs")
        collection, gate, redaction = wc.build_evidence_foundation("test-4abc")
        assert collection.ready_for_client_review is False
        assert gate.approved_for_client_view is False

    def test_build_report_drafts(self, tmp_path):
        _make_project(tmp_path)
        from core.workbench_controller import WorkbenchController
        wc = WorkbenchController(outputs_root=tmp_path / "outputs")
        internal, client, note, checklist = wc.build_report_drafts("test-4abc")
        assert client.approved_for_delivery is False
        assert checklist.safe_to_deliver is False

    def test_build_delivery_preview(self, tmp_path):
        _make_project(tmp_path)
        from core.workbench_controller import WorkbenchController
        wc = WorkbenchController(outputs_root=tmp_path / "outputs")
        preview, safety = wc.build_delivery_preview("test-4abc")
        assert preview.package_created is False
        assert safety.safe_to_package is False

    def test_evaluate_scenarios(self, tmp_path):
        from core.workbench_controller import WorkbenchController
        fixtures_root = ROOT / "fixtures" / "client_scenarios"
        if not fixtures_root.exists():
            pytest.skip("Fixtures not found")
        wc = WorkbenchController(outputs_root=tmp_path / "outputs")
        report = wc.evaluate_scenarios("test-eval", fixtures_root=str(fixtures_root))
        assert report.external_calls_performed is False
        assert report.evaluation_performed_without_execution is True
