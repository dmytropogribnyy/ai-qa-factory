"""Phase 6.3 tests -- Client Delivery Report generator.

Tests cover:
  - generate_client_delivery_report() output structure and content
  - All 12 required sections present
  - Safety notice always present
  - No findings case: explains what was not tested
  - Findings rendered with correct severity language
  - Multiple severity levels handled correctly
  - Skipped modules listed in Section 5 and Section 10
  - Risk Matrix section populated from structured findings
  - write_client_delivery_report() writes to path
  - approved_for_client_delivery invariants
  - Backward compat: existing Phase 6.1/6.2 behavior unchanged
  - CLI integration: client_report.md path printed on write run
"""
from __future__ import annotations

import tempfile
from pathlib import Path


from core.reporting.client_delivery_report import (
    generate_client_delivery_report,
    write_client_delivery_report,
)
from core.schemas.client_audit import (
    ClientAuditPlan,
    ClientAuditResult,
    ModuleResult,
    SkippedModule,
)
from core.schemas.finding import (
    Confidence,
    Finding,
    FindingCategory,
    FindingStatus,
    Severity,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_finding(
    fid: str = "F-001",
    severity: Severity = Severity.HIGH,
    category: FindingCategory = FindingCategory.API,
    source_module: str = "api_contract_importer",
    confidence: Confidence = Confidence.HIGH,
    status: FindingStatus = FindingStatus.NEEDS_REVIEW,
    title: str = "Test finding",
    client_impact: str = "Some client impact",
    evidence: str = "evidence here",
    recommendation: str = "fix it",
    affected_area: str = "spec.json",
) -> Finding:
    return Finding(
        id=fid,
        title=title,
        description="A test finding",
        severity=severity,
        category=category,
        source_module=source_module,
        confidence=confidence,
        status=status,
        client_impact=client_impact,
        evidence=evidence,
        recommendation=recommendation,
        affected_area=affected_area,
    )


def _make_plan(
    project_id: str = "demo",
    mode: str = "safe_audit",
    skipped: list[SkippedModule] | None = None,
    enabled: list[str] | None = None,
) -> ClientAuditPlan:
    return ClientAuditPlan(
        project_id=project_id,
        mode=mode,
        detected_inputs={
            "target_url": False,
            "spec_file": True,
            "postman_collection": False,
            "task_source_report": False,
            "scaffold_root": False,
            "approve_browser": False,
            "approve_public_readonly": False,
        },
        enabled_modules=enabled or ["api_contract_importer", "client_delivery_pack"],
        skipped_modules=skipped or [],
        blocked_risky_actions=["raw_secrets_allowed=False"],
        approval_required_steps=[],
        expected_artifact_paths=[],
        human_review_required=True,
    )


def _make_result(
    project_id: str = "demo",
    mode: str = "safe_audit",
    status: str = "planning_only",
    findings: list[Finding] | None = None,
    module_results: list[ModuleResult] | None = None,
) -> ClientAuditResult:
    all_findings = findings or []
    from core.risk.risk_matrix import RiskMatrix
    rm = RiskMatrix(all_findings)
    rs = rm.summary()
    return ClientAuditResult(
        project_id=project_id,
        mode=mode,
        status=status,
        modules_executed=len([mr for mr in (module_results or []) if mr.status != "planning_only"]),
        modules_planning_only=len([mr for mr in (module_results or []) if mr.status == "planning_only"]),
        blocked_risky_actions=3,
        findings=len(all_findings),
        artifacts_root=f"outputs/{project_id}",
        delivery_dir=f"outputs/{project_id}/28_client_delivery",
        module_results=module_results or [],
        structured_findings=all_findings,
        total_findings=len(all_findings),
        findings_by_severity=rs.get("by_severity", {}),
        findings_by_category=rs.get("by_category", {}),
        top_risks=rs.get("top_risks", []),
        risk_summary=rs,
    )


def _report(
    findings: list[Finding] | None = None,
    skipped: list[SkippedModule] | None = None,
    module_results: list[ModuleResult] | None = None,
    project_id: str = "demo",
) -> str:
    result = _make_result(project_id=project_id, findings=findings, module_results=module_results)
    plan = _make_plan(project_id=project_id, skipped=skipped)
    return generate_client_delivery_report(result, plan)


# ---------------------------------------------------------------------------
# TestReportStructure -- all sections present
# ---------------------------------------------------------------------------

class TestReportStructure:
    def test_has_title(self) -> None:
        r = _report()
        assert "# QA Audit Report" in r

    def test_has_executive_summary(self) -> None:
        r = _report()
        assert "## 1. Executive Summary" in r

    def test_has_audit_scope(self) -> None:
        r = _report()
        assert "## 2. Audit Scope" in r

    def test_has_inputs_provided(self) -> None:
        r = _report()
        assert "## 3. Inputs Provided" in r

    def test_has_modules_executed(self) -> None:
        r = _report()
        assert "## 4. Modules Executed" in r

    def test_has_modules_not_executed(self) -> None:
        r = _report()
        assert "## 5. Modules Not Executed" in r

    def test_has_risk_matrix(self) -> None:
        r = _report()
        assert "## 6. Risk Matrix" in r

    def test_has_key_findings(self) -> None:
        r = _report()
        assert "## 7. Key Findings" in r

    def test_has_evidence_summary(self) -> None:
        r = _report()
        assert "## 8. Evidence Summary" in r

    def test_has_recommended_actions(self) -> None:
        r = _report()
        assert "## 9. Recommended Actions" in r

    def test_has_what_not_tested(self) -> None:
        r = _report()
        assert "## 10. What Was Not Tested" in r

    def test_has_assumptions(self) -> None:
        r = _report()
        assert "## 11. Assumptions and Limitations" in r

    def test_has_next_steps(self) -> None:
        r = _report()
        assert "## 12. Next Steps" in r

    def test_has_review_approval_footer(self) -> None:
        r = _report()
        assert "## Review and Approval" in r

    def test_returns_string(self) -> None:
        r = _report()
        assert isinstance(r, str)
        assert len(r) > 100


# ---------------------------------------------------------------------------
# TestSafetyNotice -- always present, always draft
# ---------------------------------------------------------------------------

class TestSafetyNotice:
    def test_draft_notice_present(self) -> None:
        r = _report()
        assert "DRAFT" in r

    def test_pending_human_review_notice(self) -> None:
        r = _report()
        assert "PENDING HUMAN REVIEW" in r or "human review" in r.lower()

    def test_approved_for_client_delivery_false_stated(self) -> None:
        r = _report()
        assert "approved_for_client_delivery = False" in r

    def test_human_review_required_in_footer(self) -> None:
        r = _report()
        assert "human review" in r.lower()

    def test_not_auto_approved_language(self) -> None:
        r = _report()
        assert "not been approved for external distribution" in r or "not automatically approved" in r.lower()

    def test_checkbox_review_present(self) -> None:
        r = _report()
        assert "QA engineer reviewed" in r

    def test_checkbox_approve_delivery_present(self) -> None:
        r = _report()
        assert "approved for client delivery" in r.lower()


# ---------------------------------------------------------------------------
# TestNoFindingsCase
# ---------------------------------------------------------------------------

class TestNoFindingsCase:
    def test_no_findings_says_no_findings(self) -> None:
        r = _report(findings=[])
        assert "No findings" in r or "no findings" in r.lower()

    def test_no_findings_explains_not_tested(self) -> None:
        r = _report(findings=[])
        assert "planning-only" in r or "planning_only" in r or "no execution" in r.lower()

    def test_no_findings_suggests_improvements(self) -> None:
        r = _report(findings=[])
        assert "API spec" in r or "api spec" in r.lower() or "target URL" in r or "coverage" in r.lower()

    def test_no_findings_executive_summary_reflects_it(self) -> None:
        r = _report(findings=[])
        assert "No findings" in r or "no detectable issues" in r or "no findings" in r.lower()

    def test_no_findings_recommended_actions_present(self) -> None:
        r = _report(findings=[])
        assert "## 9. Recommended Actions" in r

    def test_no_findings_risk_matrix_shows_zero(self) -> None:
        r = _report(findings=[])
        assert "Total Findings | 0" in r or "Total findings" in r


# ---------------------------------------------------------------------------
# TestFindingRendering
# ---------------------------------------------------------------------------

class TestFindingRendering:
    def test_finding_title_in_report(self) -> None:
        f = _make_finding(title="Missing security header")
        r = _report(findings=[f])
        assert "Missing security header" in r

    def test_finding_severity_label_rendered(self) -> None:
        f = _make_finding(severity=Severity.CRITICAL, title="Critical bug")
        r = _report(findings=[f])
        assert "Critical" in r

    def test_finding_high_severity_label(self) -> None:
        f = _make_finding(severity=Severity.HIGH)
        r = _report(findings=[f])
        assert "High" in r

    def test_finding_medium_severity_label(self) -> None:
        f = _make_finding(severity=Severity.MEDIUM)
        r = _report(findings=[f])
        assert "Medium" in r

    def test_finding_low_severity_label(self) -> None:
        f = _make_finding(severity=Severity.LOW)
        r = _report(findings=[f])
        assert "Low" in r

    def test_finding_info_severity_label(self) -> None:
        f = _make_finding(severity=Severity.INFO)
        r = _report(findings=[f])
        assert "Informational" in r

    def test_client_impact_rendered(self) -> None:
        f = _make_finding(client_impact="Users may be exposed to XSS")
        r = _report(findings=[f])
        assert "Users may be exposed to XSS" in r

    def test_evidence_rendered(self) -> None:
        f = _make_finding(evidence="blocked_count=3")
        r = _report(findings=[f])
        assert "blocked_count=3" in r

    def test_recommendation_rendered(self) -> None:
        f = _make_finding(recommendation="Add Content-Security-Policy header")
        r = _report(findings=[f])
        assert "Add Content-Security-Policy header" in r

    def test_affected_area_rendered(self) -> None:
        f = _make_finding(affected_area="login endpoint")
        r = _report(findings=[f])
        assert "login endpoint" in r

    def test_finding_numbered(self) -> None:
        f = _make_finding()
        r = _report(findings=[f])
        assert "### Finding 1:" in r

    def test_multiple_findings_numbered(self) -> None:
        f1 = _make_finding("F-001", title="First")
        f2 = _make_finding("F-002", severity=Severity.LOW, title="Second")
        r = _report(findings=[f1, f2])
        assert "### Finding 1:" in r
        assert "### Finding 2:" in r

    def test_findings_sorted_critical_first(self) -> None:
        f_low = _make_finding("L-001", severity=Severity.LOW, title="Low finding")
        f_crit = _make_finding("C-001", severity=Severity.CRITICAL, title="Critical finding")
        r = _report(findings=[f_low, f_crit])
        assert r.index("Critical finding") < r.index("Low finding")

    def test_finding_source_module_label(self) -> None:
        f = _make_finding(source_module="passive_security_runner")
        r = _report(findings=[f])
        assert "Security Header Check" in r


# ---------------------------------------------------------------------------
# TestSeverityLanguage
# ---------------------------------------------------------------------------

class TestSeverityLanguage:
    def test_critical_language_immediate_attention(self) -> None:
        f = _make_finding(severity=Severity.CRITICAL)
        r = _report(findings=[f])
        assert "immediate attention" in r or "Immediate" in r

    def test_high_language_before_release(self) -> None:
        f = _make_finding(severity=Severity.HIGH)
        r = _report(findings=[f])
        assert "release" in r.lower()

    def test_medium_language_upcoming_iteration(self) -> None:
        f = _make_finding(severity=Severity.MEDIUM)
        r = _report(findings=[f])
        assert "iteration" in r.lower() or "upcoming" in r.lower()

    def test_low_language_observation(self) -> None:
        f = _make_finding(severity=Severity.LOW)
        r = _report(findings=[f])
        assert "observation" in r.lower() or "improvement" in r.lower()


# ---------------------------------------------------------------------------
# TestRecommendedActions
# ---------------------------------------------------------------------------

class TestRecommendedActions:
    def test_critical_triggers_immediate_action(self) -> None:
        f = _make_finding(severity=Severity.CRITICAL)
        r = _report(findings=[f])
        assert "Immediate action required" in r

    def test_high_triggers_sprint_planning(self) -> None:
        f = _make_finding(severity=Severity.HIGH)
        r = _report(findings=[f])
        assert "next sprint" in r.lower() or "Plan for next sprint" in r

    def test_medium_triggers_schedule(self) -> None:
        f = _make_finding(severity=Severity.MEDIUM)
        r = _report(findings=[f])
        assert "Schedule" in r or "upcoming iterations" in r

    def test_low_triggers_backlog(self) -> None:
        f = _make_finding(severity=Severity.LOW)
        r = _report(findings=[f])
        assert "Backlog" in r or "backlog" in r

    def test_no_findings_expand_coverage_message(self) -> None:
        r = _report(findings=[])
        assert "expand" in r.lower() or "coverage" in r.lower() or "api spec" in r.lower()


# ---------------------------------------------------------------------------
# TestSkippedModules
# ---------------------------------------------------------------------------

class TestSkippedModules:
    def test_skipped_module_in_section_5(self) -> None:
        skipped = [SkippedModule(name="accessibility_runner", reason="no target URL")]
        r = _report(skipped=skipped)
        assert "Accessibility Check" in r
        assert "no target URL" in r

    def test_skipped_module_in_not_tested(self) -> None:
        skipped = [SkippedModule(name="performance_runner", reason="no browser approval")]
        r = _report(skipped=skipped)
        assert "Performance Check" in r

    def test_no_skipped_modules_message(self) -> None:
        r = _report(skipped=[])
        assert "All planned modules were executed" in r

    def test_multiple_skipped(self) -> None:
        skipped = [
            SkippedModule(name="accessibility_runner", reason="no url"),
            SkippedModule(name="performance_runner", reason="no browser"),
        ]
        r = _report(skipped=skipped)
        assert "Accessibility Check" in r
        assert "Performance Check" in r


# ---------------------------------------------------------------------------
# TestRiskMatrixSection
# ---------------------------------------------------------------------------

class TestRiskMatrixSection:
    def test_total_findings_count(self) -> None:
        f1 = _make_finding("F-001")
        f2 = _make_finding("F-002", severity=Severity.CRITICAL)
        r = _report(findings=[f1, f2])
        assert "Total Findings | 2" in r or "Total findings" in r

    def test_zero_total_findings(self) -> None:
        r = _report(findings=[])
        assert "Total Findings | 0" in r or "Total findings" in r

    def test_severity_counts_shown(self) -> None:
        f = _make_finding(severity=Severity.HIGH)
        r = _report(findings=[f])
        assert "High" in r

    def test_top_risks_shown(self) -> None:
        f = _make_finding("TT-001", severity=Severity.CRITICAL, title="Big risk")
        r = _report(findings=[f])
        assert "Big risk" in r


# ---------------------------------------------------------------------------
# TestModuleResults
# ---------------------------------------------------------------------------

class TestModuleResults:
    def test_module_analysis_only_label(self) -> None:
        mr = ModuleResult(name="api_contract_importer", status="analysis_only")
        r = _report(module_results=[mr])
        assert "Analyzed (read-only)" in r or "API Contract Analysis" in r

    def test_module_planning_only_label(self) -> None:
        mr = ModuleResult(name="accessibility_runner", status="planning_only")
        r = _report(module_results=[mr])
        assert "Planned only" in r or "planning" in r.lower()

    def test_module_failed_label(self) -> None:
        mr = ModuleResult(name="accessibility_runner", status="failed", note="timeout")
        r = _report(module_results=[mr])
        assert "Failed" in r

    def test_no_modules_message(self) -> None:
        r = _report(module_results=[])
        assert "No modules were executed" in r

    def test_module_note_shown(self) -> None:
        mr = ModuleResult(name="api_contract_importer", status="analysis_only", note="no spec file")
        r = _report(module_results=[mr])
        assert "no spec file" in r


# ---------------------------------------------------------------------------
# TestWhatWasNotTested
# ---------------------------------------------------------------------------

class TestWhatWasNotTested:
    def test_auth_not_tested(self) -> None:
        r = _report()
        assert "Authentication" in r or "login flows" in r.lower()

    def test_destructive_always_blocked(self) -> None:
        r = _report()
        assert "destructive" in r.lower() or "Checkout" in r

    def test_load_testing_out_of_scope(self) -> None:
        r = _report()
        assert "Load testing" in r or "load test" in r.lower()

    def test_captcha_always_blocked(self) -> None:
        r = _report()
        assert "CAPTCHA" in r or "captcha" in r.lower()


# ---------------------------------------------------------------------------
# TestWriteClientDeliveryReport
# ---------------------------------------------------------------------------

class TestWriteClientDeliveryReport:
    def test_writes_file(self) -> None:
        result = _make_result()
        plan = _make_plan()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "client_report.md"
            write_client_delivery_report(path, result, plan)
            assert path.exists()

    def test_written_file_is_utf8_markdown(self) -> None:
        result = _make_result()
        plan = _make_plan()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "client_report.md"
            write_client_delivery_report(path, result, plan)
            content = path.read_text(encoding="utf-8")
            assert "# QA Audit Report" in content

    def test_written_file_has_draft_notice(self) -> None:
        result = _make_result()
        plan = _make_plan()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "client_report.md"
            write_client_delivery_report(path, result, plan)
            content = path.read_text(encoding="utf-8")
            assert "DRAFT" in content

    def test_written_file_with_findings(self) -> None:
        f = _make_finding(title="Security gap found")
        result = _make_result(findings=[f])
        plan = _make_plan()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "client_report.md"
            write_client_delivery_report(path, result, plan)
            content = path.read_text(encoding="utf-8")
            assert "Security gap found" in content


# ---------------------------------------------------------------------------
# TestSafetyInvariantsPreserved
# ---------------------------------------------------------------------------

class TestSafetyInvariantsPreserved:
    def test_result_approved_for_delivery_always_false(self) -> None:
        result = _make_result()
        assert result.approved_for_client_delivery is False

    def test_result_human_review_always_true(self) -> None:
        result = _make_result()
        assert result.human_review_required is True

    def test_result_raw_secrets_always_false(self) -> None:
        result = _make_result()
        assert result.raw_secrets_allowed is False

    def test_generate_report_does_not_change_result(self) -> None:
        result = _make_result()
        plan = _make_plan()
        generate_client_delivery_report(result, plan)
        assert result.approved_for_client_delivery is False
        assert result.human_review_required is True

    def test_write_report_does_not_grant_approval(self) -> None:
        result = _make_result()
        plan = _make_plan()
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "client_report.md"
            write_client_delivery_report(path, result, plan)
        assert result.approved_for_client_delivery is False


# ---------------------------------------------------------------------------
# TestWorkflowIntegration -- client_report.md generated in run()
# ---------------------------------------------------------------------------

class TestWorkflowIntegration:
    def test_workflow_generates_client_report(self) -> None:
        from core.client_audit_workflow import ClientAuditWorkflow
        from core.schemas.client_audit import ClientAuditInputs

        with tempfile.TemporaryDirectory() as tmpdir:
            inputs = ClientAuditInputs(
                project_id="integration-test",
                outputs_root=tmpdir,
                write_files=True,
            )
            workflow = ClientAuditWorkflow(inputs)
            workflow.run()
            report_path = Path(tmpdir) / "integration-test" / "33_client_audit" / "client_report.md"
            assert report_path.exists()

    def test_workflow_client_report_has_required_sections(self) -> None:
        from core.client_audit_workflow import ClientAuditWorkflow
        from core.schemas.client_audit import ClientAuditInputs

        with tempfile.TemporaryDirectory() as tmpdir:
            inputs = ClientAuditInputs(
                project_id="integration-test-2",
                outputs_root=tmpdir,
                write_files=True,
            )
            workflow = ClientAuditWorkflow(inputs)
            workflow.run()
            report_path = Path(tmpdir) / "integration-test-2" / "33_client_audit" / "client_report.md"
            content = report_path.read_text(encoding="utf-8")
            for section in [
                "# QA Audit Report",
                "## 1. Executive Summary",
                "## 6. Risk Matrix",
                "## 7. Key Findings",
                "## 9. Recommended Actions",
                "## 12. Next Steps",
                "DRAFT",
            ]:
                assert section in content, f"Missing section: {section}"

    def test_workflow_no_write_does_not_create_client_report(self) -> None:
        from core.client_audit_workflow import ClientAuditWorkflow
        from core.schemas.client_audit import ClientAuditInputs

        with tempfile.TemporaryDirectory() as tmpdir:
            inputs = ClientAuditInputs(
                project_id="no-write-test",
                outputs_root=tmpdir,
                write_files=False,
            )
            workflow = ClientAuditWorkflow(inputs)
            workflow.run()
            report_path = Path(tmpdir) / "no-write-test" / "33_client_audit" / "client_report.md"
            assert not report_path.exists()

    def test_result_dict_includes_client_report_path(self) -> None:
        from core.client_audit_workflow import _result_to_dict, ClientAuditWorkflow
        from core.schemas.client_audit import ClientAuditInputs

        with tempfile.TemporaryDirectory() as tmpdir:
            inputs = ClientAuditInputs(
                project_id="dict-test",
                outputs_root=tmpdir,
                write_files=False,
            )
            workflow = ClientAuditWorkflow(inputs)
            result = workflow.run()
            d = _result_to_dict(result)
            assert "client_report_path" in d
            assert "client_report.md" in d["client_report_path"]


# ---------------------------------------------------------------------------
# TestProjectIdInReport
# ---------------------------------------------------------------------------

class TestProjectIdInReport:
    def test_project_id_in_header(self) -> None:
        r = _report(project_id="acme-corp")
        assert "acme-corp" in r

    def test_project_id_in_executive_summary(self) -> None:
        r = _report(project_id="client-xyz")
        assert "client-xyz" in r
