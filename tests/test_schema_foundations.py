"""
Schema foundation tests — Phase 1B.

Covers:
- SchemaMixin.to_dict / from_dict round-trips for all 25 domain schemas
- Explicit nested from_dict reconstruction for all container models
- Constants are non-empty frozensets
- Required fields (project_id) are enforced
- Defaults are sane (dry_run=True on CleanupReport, etc.)
"""
from __future__ import annotations

from core.schemas.constants import (
    INPUT_TYPES,
    RISK_LEVELS,
    PROJECT_TYPES,
    ENVIRONMENT_TYPES,
    ACTION_STATUSES,
    ACCESS_LEVELS,
    ARTIFACT_TYPES,
    ASSISTANT_TYPES,
    WORK_DOMAINS,
    TASK_TYPES,
    DELIVERABLE_TYPES,
)
from core.schemas.source_reference import SourceReference
from core.schemas.work_request import WorkRequest
from core.schemas.task_classification import TaskClassification
from core.schemas.input_map import InputSource, InputMap
from core.schemas.project_blueprint import ProjectBlueprint
from core.schemas.delivery_plan import DeliveryItem, DeliveryPlan
from core.schemas.quality_rubric import QualityCriterion, QualityRubric
from core.schemas.automation_plan import AutomationAction, AutomationPlan
from core.schemas.approval import ApprovalDecision, ApprovalHistory
from core.schemas.tool_selection import ToolRecommendation, ToolSelection
from core.schemas.artifact_manifest import ArtifactRecord, ArtifactManifest
from core.schemas.run_context import RunContext
from core.schemas.safety import SafetyCheck, SafetyReport
from core.schemas.execution_summary import EvidenceItem, ExecutionSummary
from core.schemas.assistance import AssistanceRecord, AssistanceHistory
from core.schemas.activity_log import ActivityEvent, ActivityLog
from core.schemas.blocker import Blocker, BlockerRegister
from core.schemas.progress import ProgressItem, ProgressTracker
from core.schemas.self_assessment import SelfAssessmentFinding, SelfAssessment
from core.schemas.project_status import ProjectStatus
from core.schemas.cleanup import CleanupCandidate, CleanupReport
from core.schemas.ai_resilience import AIProviderStatus, AIFallbackEvent, AIResilienceReport
from core.schemas.admin_feedback import AdminNotification, AdminFeedbackCenter
from core.schemas.media_evidence import MediaEvidenceItem, MediaEvidenceCollection
from core.schemas.analytics import AnalyticsMetric, AnalyticsReport


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestConstants:
    def test_input_types_is_frozenset(self):
        assert isinstance(INPUT_TYPES, frozenset)
        assert len(INPUT_TYPES) > 0

    def test_risk_levels_contains_safe_analysis(self):
        assert "safe_analysis" in RISK_LEVELS
        assert "client_delivery" in RISK_LEVELS

    def test_project_types_contains_known_types(self):
        for t in ("web_saas", "ecommerce", "api_backend", "unknown"):
            assert t in PROJECT_TYPES

    def test_environment_types_has_production(self):
        assert "production" in ENVIRONMENT_TYPES
        assert "staging" in ENVIRONMENT_TYPES

    def test_action_statuses_has_pending(self):
        assert "pending" in ACTION_STATUSES
        assert "approved" in ACTION_STATUSES
        assert "rejected" in ACTION_STATUSES

    def test_all_constant_sets_non_empty(self):
        for s in (
            INPUT_TYPES, RISK_LEVELS, PROJECT_TYPES, ENVIRONMENT_TYPES,
            ACTION_STATUSES, ACCESS_LEVELS, ARTIFACT_TYPES, ASSISTANT_TYPES,
            WORK_DOMAINS, TASK_TYPES, DELIVERABLE_TYPES,
        ):
            assert len(s) > 0


# ---------------------------------------------------------------------------
# SourceReference
# ---------------------------------------------------------------------------

class TestSourceReference:
    def test_default_construction(self):
        s = SourceReference()
        assert s.platform == "unknown"
        assert s.url == ""

    def test_roundtrip(self):
        s = SourceReference(url="https://example.com", platform="upwork", title="Job X")
        d = s.to_dict()
        s2 = SourceReference.from_dict(d)
        assert s2.url == "https://example.com"
        assert s2.platform == "upwork"
        assert s2.title == "Job X"

    def test_from_dict_ignores_unknown_fields(self):
        s = SourceReference.from_dict({"url": "x", "unknown_field": "ignored"})
        assert s.url == "x"


# ---------------------------------------------------------------------------
# WorkRequest
# ---------------------------------------------------------------------------

class TestWorkRequest:
    def test_id_auto_generated(self):
        w = WorkRequest(project_id="proj-1")
        assert len(w.id) > 0

    def test_roundtrip(self):
        w = WorkRequest(project_id="proj-1", title="Build tests", source_platform="upwork")
        d = w.to_dict()
        w2 = WorkRequest.from_dict(d)
        assert w2.project_id == "proj-1"
        assert w2.title == "Build tests"
        assert w2.source_platform == "upwork"

    def test_target_urls_default_empty(self):
        w = WorkRequest(project_id="p")
        assert w.target_urls == []


# ---------------------------------------------------------------------------
# TaskClassification
# ---------------------------------------------------------------------------

class TestTaskClassification:
    def test_default_task_type_is_unknown(self):
        t = TaskClassification()
        assert t.task_type == "unknown"
        assert t.project_type == "unknown"

    def test_roundtrip(self):
        t = TaskClassification(
            project_id="p1",
            task_type="test_design",
            project_type="web_saas",
            confidence=0.9,
            signals=["RBAC", "billing"],
        )
        d = t.to_dict()
        t2 = TaskClassification.from_dict(d)
        assert t2.task_type == "test_design"
        assert t2.confidence == 0.9
        assert "RBAC" in t2.signals


# ---------------------------------------------------------------------------
# InputMap (nested)
# ---------------------------------------------------------------------------

class TestInputMap:
    def test_empty_sources(self):
        m = InputMap(project_id="p1")
        assert m.sources == []

    def test_to_dict_nested(self):
        src = InputSource(input_type="text_brief", label="Brief A")
        m = InputMap(project_id="p1", sources=[src])
        d = m.to_dict()
        assert isinstance(d["sources"], list)
        assert d["sources"][0]["input_type"] == "text_brief"

    def test_from_dict_reconstructs_input_sources(self):
        data = {
            "project_id": "p1",
            "sources": [
                {"input_type": "target_url", "label": "Staging", "raw_value": "https://staging.example.com", "approved": True},
            ],
        }
        m = InputMap.from_dict(data)
        assert len(m.sources) == 1
        assert isinstance(m.sources[0], InputSource)
        assert m.sources[0].input_type == "target_url"
        assert m.sources[0].approved is True

    def test_roundtrip_preserves_sources(self):
        src1 = InputSource(input_type="text_brief", label="Brief")
        src2 = InputSource(input_type="screenshot", label="Screen1")
        m = InputMap(project_id="p1", sources=[src1, src2])
        m2 = InputMap.from_dict(m.to_dict())
        assert len(m2.sources) == 2
        assert all(isinstance(s, InputSource) for s in m2.sources)


# ---------------------------------------------------------------------------
# ProjectBlueprint
# ---------------------------------------------------------------------------

class TestProjectBlueprint:
    def test_required_project_id(self):
        bp = ProjectBlueprint(project_id="p1")
        assert bp.project_id == "p1"

    def test_roundtrip(self):
        bp = ProjectBlueprint(
            project_id="p1",
            project_type="ecommerce",
            tech_stack=["React", "Node.js"],
            risk_areas=["payment", "auth"],
        )
        d = bp.to_dict()
        bp2 = ProjectBlueprint.from_dict(d)
        assert bp2.project_type == "ecommerce"
        assert "React" in bp2.tech_stack


# ---------------------------------------------------------------------------
# DeliveryPlan (nested)
# ---------------------------------------------------------------------------

class TestDeliveryPlan:
    def test_from_dict_reconstructs_delivery_items(self):
        data = {
            "project_id": "p1",
            "items": [{"deliverable_type": "proposal", "title": "Proposal Doc", "status": "pending"}],
        }
        dp = DeliveryPlan.from_dict(data)
        assert len(dp.items) == 1
        assert isinstance(dp.items[0], DeliveryItem)
        assert dp.items[0].deliverable_type == "proposal"

    def test_roundtrip(self):
        item = DeliveryItem(deliverable_type="test_plan", title="Test Plan v1")
        dp = DeliveryPlan(project_id="p1", items=[item])
        dp2 = DeliveryPlan.from_dict(dp.to_dict())
        assert isinstance(dp2.items[0], DeliveryItem)
        assert dp2.items[0].title == "Test Plan v1"


# ---------------------------------------------------------------------------
# QualityRubric (nested)
# ---------------------------------------------------------------------------

class TestQualityRubric:
    def test_from_dict_reconstructs_criteria(self):
        data = {
            "project_id": "p1",
            "criteria": [{"name": "Coverage", "weight": 2.0, "passing_threshold": 0.8}],
        }
        qr = QualityRubric.from_dict(data)
        assert isinstance(qr.criteria[0], QualityCriterion)
        assert qr.criteria[0].weight == 2.0

    def test_roundtrip(self):
        c = QualityCriterion(name="Brittleness", weight=1.5)
        qr = QualityRubric(project_id="p1", criteria=[c])
        qr2 = QualityRubric.from_dict(qr.to_dict())
        assert qr2.criteria[0].name == "Brittleness"


# ---------------------------------------------------------------------------
# AutomationPlan (nested)
# ---------------------------------------------------------------------------

class TestAutomationPlan:
    def test_from_dict_reconstructs_actions(self):
        data = {
            "project_id": "p1",
            "actions": [{"title": "Smoke test", "risk_level": "safe_local", "framework": "playwright_typescript"}],
        }
        ap = AutomationPlan.from_dict(data)
        assert isinstance(ap.actions[0], AutomationAction)
        assert ap.actions[0].risk_level == "safe_local"

    def test_roundtrip(self):
        action = AutomationAction(title="Auth flow", framework="playwright_typescript", priority=1)
        ap = AutomationPlan(project_id="p1", actions=[action])
        ap2 = AutomationPlan.from_dict(ap.to_dict())
        assert ap2.actions[0].title == "Auth flow"
        assert ap2.actions[0].priority == 1


# ---------------------------------------------------------------------------
# ApprovalHistory (nested)
# ---------------------------------------------------------------------------

class TestApprovalHistory:
    def test_from_dict_reconstructs_decisions(self):
        data = {
            "project_id": "p1",
            "decisions": [{"action_key": "run-against-staging", "decision": "approved", "decided_by": "Dmytro"}],
        }
        ah = ApprovalHistory.from_dict(data)
        assert isinstance(ah.decisions[0], ApprovalDecision)
        assert ah.decisions[0].decision == "approved"
        assert ah.decisions[0].decided_by == "Dmytro"

    def test_roundtrip(self):
        d = ApprovalDecision(action_key="run-tests", decision="rejected", reason="Scope unclear")
        ah = ApprovalHistory(project_id="p1", decisions=[d])
        ah2 = ApprovalHistory.from_dict(ah.to_dict())
        assert ah2.decisions[0].reason == "Scope unclear"


# ---------------------------------------------------------------------------
# ToolSelection (nested)
# ---------------------------------------------------------------------------

class TestToolSelection:
    def test_from_dict_reconstructs_recommendations(self):
        data = {
            "project_id": "p1",
            "recommendations": [{"tool_name": "Playwright", "category": "ui", "is_mandatory": True}],
        }
        ts = ToolSelection.from_dict(data)
        assert isinstance(ts.recommendations[0], ToolRecommendation)
        assert ts.recommendations[0].is_mandatory is True

    def test_roundtrip(self):
        r = ToolRecommendation(tool_name="k6", category="performance", rationale="Load testing")
        ts = ToolSelection(project_id="p1", recommendations=[r])
        ts2 = ToolSelection.from_dict(ts.to_dict())
        assert ts2.recommendations[0].tool_name == "k6"


# ---------------------------------------------------------------------------
# ArtifactManifest (nested)
# ---------------------------------------------------------------------------

class TestArtifactManifest:
    def test_from_dict_reconstructs_artifacts(self):
        data = {
            "project_id": "p1",
            "artifacts": [{"artifact_type": "test_strategy", "filename": "TEST_STRATEGY.md", "is_client_facing": True}],
        }
        am = ArtifactManifest.from_dict(data)
        assert isinstance(am.artifacts[0], ArtifactRecord)
        assert am.artifacts[0].is_client_facing is True

    def test_roundtrip(self):
        rec = ArtifactRecord(artifact_type="report", filename="REPORT.md")
        am = ArtifactManifest(project_id="p1", artifacts=[rec])
        am2 = ArtifactManifest.from_dict(am.to_dict())
        assert am2.artifacts[0].filename == "REPORT.md"


# ---------------------------------------------------------------------------
# RunContext
# ---------------------------------------------------------------------------

class TestRunContext:
    def test_defaults(self):
        rc = RunContext(project_id="p1")
        assert rc.mode == "mock"
        assert rc.approved is False
        assert rc.flags == []

    def test_roundtrip(self):
        rc = RunContext(project_id="p1", workflow="test-design", mode="real", approved=True, flags=["--require-real-llm"])
        d = rc.to_dict()
        rc2 = RunContext.from_dict(d)
        assert rc2.workflow == "test-design"
        assert rc2.approved is True
        assert "--require-real-llm" in rc2.flags


# ---------------------------------------------------------------------------
# SafetyReport (nested)
# ---------------------------------------------------------------------------

class TestSafetyReport:
    def test_from_dict_reconstructs_checks(self):
        data = {
            "project_id": "p1",
            "checks": [{"rule_id": "rule-3", "rule_label": "No unapproved URL", "passed": False, "violation_detail": "URL not approved"}],
        }
        sr = SafetyReport.from_dict(data)
        assert isinstance(sr.checks[0], SafetyCheck)
        assert sr.checks[0].passed is False

    def test_default_all_passed_true(self):
        sr = SafetyReport(project_id="p1")
        assert sr.all_passed is True

    def test_roundtrip(self):
        check = SafetyCheck(rule_id="rule-1", passed=True)
        sr = SafetyReport(project_id="p1", all_passed=True, checks=[check])
        sr2 = SafetyReport.from_dict(sr.to_dict())
        assert sr2.all_passed is True
        assert isinstance(sr2.checks[0], SafetyCheck)


# ---------------------------------------------------------------------------
# ExecutionSummary (nested)
# ---------------------------------------------------------------------------

class TestExecutionSummary:
    def test_from_dict_reconstructs_evidence(self):
        data = {
            "project_id": "p1",
            "evidence": [{"evidence_type": "screenshot", "label": "Login page", "file_path": "screenshots/login.png"}],
        }
        es = ExecutionSummary.from_dict(data)
        assert isinstance(es.evidence[0], EvidenceItem)
        assert es.evidence[0].label == "Login page"

    def test_int_defaults_are_zero(self):
        es = ExecutionSummary(project_id="p1")
        assert es.total_tests == 0
        assert es.passed == 0
        assert es.failed == 0

    def test_roundtrip(self):
        ev = EvidenceItem(evidence_type="trace", label="auth-trace")
        es = ExecutionSummary(project_id="p1", total_tests=10, passed=9, failed=1, evidence=[ev])
        es2 = ExecutionSummary.from_dict(es.to_dict())
        assert es2.total_tests == 10
        assert es2.evidence[0].label == "auth-trace"


# ---------------------------------------------------------------------------
# AssistanceHistory (nested)
# ---------------------------------------------------------------------------

class TestAssistanceHistory:
    def test_from_dict_reconstructs_records(self):
        data = {
            "project_id": "p1",
            "records": [{"assistant_type": "scaffold", "workflow": "scaffold", "llm_mode": "real"}],
        }
        ah = AssistanceHistory.from_dict(data)
        assert isinstance(ah.records[0], AssistanceRecord)
        assert ah.records[0].llm_mode == "real"

    def test_roundtrip(self):
        rec = AssistanceRecord(assistant_type="test_design", agents_invoked=["classifier", "test_design_agent"])
        ah = AssistanceHistory(project_id="p1", records=[rec])
        ah2 = AssistanceHistory.from_dict(ah.to_dict())
        assert ah2.records[0].assistant_type == "test_design"
        assert "classifier" in ah2.records[0].agents_invoked


# ---------------------------------------------------------------------------
# ActivityLog (nested)
# ---------------------------------------------------------------------------

class TestActivityLog:
    def test_from_dict_reconstructs_events(self):
        data = {
            "project_id": "p1",
            "events": [{"event_type": "info", "agent": "classifier", "message": "Project classified as web_saas"}],
        }
        al = ActivityLog.from_dict(data)
        assert isinstance(al.events[0], ActivityEvent)
        assert al.events[0].agent == "classifier"

    def test_roundtrip(self):
        ev = ActivityEvent(event_type="warning", message="Sandbox not confirmed")
        al = ActivityLog(project_id="p1", events=[ev])
        al2 = ActivityLog.from_dict(al.to_dict())
        assert al2.events[0].message == "Sandbox not confirmed"


# ---------------------------------------------------------------------------
# BlockerRegister (nested)
# ---------------------------------------------------------------------------

class TestBlockerRegister:
    def test_from_dict_reconstructs_blockers(self):
        data = {
            "project_id": "p1",
            "blockers": [{"title": "No sandbox confirmation", "severity": "high", "status": "open"}],
        }
        br = BlockerRegister.from_dict(data)
        assert isinstance(br.blockers[0], Blocker)
        assert br.blockers[0].severity == "high"

    def test_roundtrip(self):
        b = Blocker(title="Missing credentials", severity="medium")
        br = BlockerRegister(project_id="p1", blockers=[b])
        br2 = BlockerRegister.from_dict(br.to_dict())
        assert br2.blockers[0].title == "Missing credentials"


# ---------------------------------------------------------------------------
# ProgressTracker (nested)
# ---------------------------------------------------------------------------

class TestProgressTracker:
    def test_from_dict_reconstructs_items(self):
        data = {
            "project_id": "p1",
            "items": [{"title": "Test design", "status": "completed", "completion_pct": 100}],
        }
        pt = ProgressTracker.from_dict(data)
        assert isinstance(pt.items[0], ProgressItem)
        assert pt.items[0].completion_pct == 100

    def test_overall_pct_default_zero(self):
        pt = ProgressTracker(project_id="p1")
        assert pt.overall_pct == 0

    def test_roundtrip(self):
        item = ProgressItem(title="Scaffold", status="in_progress", completion_pct=50)
        pt = ProgressTracker(project_id="p1", items=[item], overall_pct=25)
        pt2 = ProgressTracker.from_dict(pt.to_dict())
        assert pt2.overall_pct == 25
        assert pt2.items[0].completion_pct == 50


# ---------------------------------------------------------------------------
# SelfAssessment (nested)
# ---------------------------------------------------------------------------

class TestSelfAssessment:
    def test_from_dict_reconstructs_findings(self):
        data = {
            "project_id": "p1",
            "findings": [{"category": "coverage", "severity": "warning", "finding": "Missing RBAC tests"}],
        }
        sa = SelfAssessment.from_dict(data)
        assert isinstance(sa.findings[0], SelfAssessmentFinding)
        assert sa.findings[0].finding == "Missing RBAC tests"

    def test_roundtrip(self):
        f = SelfAssessmentFinding(category="brittleness", severity="info", recommendation="Use data-testid")
        sa = SelfAssessment(project_id="p1", overall_score=0.85, findings=[f])
        sa2 = SelfAssessment.from_dict(sa.to_dict())
        assert sa2.overall_score == 0.85
        assert sa2.findings[0].recommendation == "Use data-testid"


# ---------------------------------------------------------------------------
# ProjectStatus
# ---------------------------------------------------------------------------

class TestProjectStatus:
    def test_defaults(self):
        ps = ProjectStatus(project_id="p1")
        assert ps.phase == "intake"
        assert ps.overall_status == "in_progress"
        assert ps.pending_approvals == []

    def test_roundtrip(self):
        ps = ProjectStatus(project_id="p1", phase="execution", pending_approvals=["run-against-staging"])
        d = ps.to_dict()
        ps2 = ProjectStatus.from_dict(d)
        assert ps2.phase == "execution"
        assert "run-against-staging" in ps2.pending_approvals


# ---------------------------------------------------------------------------
# CleanupReport (nested)
# ---------------------------------------------------------------------------

class TestCleanupReport:
    def test_dry_run_default_true(self):
        cr = CleanupReport(project_id="p1")
        assert cr.dry_run is True

    def test_from_dict_reconstructs_candidates(self):
        data = {
            "project_id": "p1",
            "candidates": [{"file_path": "outputs/old/state.json", "reason": "stale", "risk": "low"}],
        }
        cr = CleanupReport.from_dict(data)
        assert isinstance(cr.candidates[0], CleanupCandidate)
        assert cr.candidates[0].risk == "low"

    def test_roundtrip_preserves_dry_run(self):
        c = CleanupCandidate(file_path="old.md", reason="stale")
        cr = CleanupReport(project_id="p1", candidates=[c], dry_run=True)
        cr2 = CleanupReport.from_dict(cr.to_dict())
        assert cr2.dry_run is True
        assert cr2.candidates[0].file_path == "old.md"

    def test_approved_for_deletion_default_false(self):
        c = CleanupCandidate()
        assert c.approved_for_deletion is False


# ---------------------------------------------------------------------------
# AIResilienceReport (nested)
# ---------------------------------------------------------------------------

class TestAIResilienceReport:
    def test_from_dict_reconstructs_providers_and_fallbacks(self):
        data = {
            "project_id": "p1",
            "providers": [{"provider": "anthropic", "model_id": "claude-sonnet-4-6", "role": "architect", "available": True}],
            "fallback_events": [{"primary_provider": "anthropic", "fallback_provider": "openai", "reason": "timeout"}],
        }
        rr = AIResilienceReport.from_dict(data)
        assert isinstance(rr.providers[0], AIProviderStatus)
        assert isinstance(rr.fallback_events[0], AIFallbackEvent)
        assert rr.providers[0].available is True
        assert rr.fallback_events[0].reason == "timeout"

    def test_roundtrip(self):
        p = AIProviderStatus(provider="anthropic", model_id="claude-sonnet-4-6", role="coding")
        fe = AIFallbackEvent(primary_provider="anthropic", fallback_provider="mock", reason="no key")
        rr = AIResilienceReport(project_id="p1", providers=[p], fallback_events=[fe])
        rr2 = AIResilienceReport.from_dict(rr.to_dict())
        assert rr2.providers[0].provider == "anthropic"
        assert rr2.fallback_events[0].fallback_provider == "mock"


# ---------------------------------------------------------------------------
# AdminFeedbackCenter (nested)
# ---------------------------------------------------------------------------

class TestAdminFeedbackCenter:
    def test_from_dict_reconstructs_notifications(self):
        data = {
            "project_id": "p1",
            "notifications": [{"category": "security", "severity": "high", "message": "Credentials in test file", "action_required": True}],
        }
        afc = AdminFeedbackCenter.from_dict(data)
        assert isinstance(afc.notifications[0], AdminNotification)
        assert afc.notifications[0].action_required is True

    def test_roundtrip(self):
        n = AdminNotification(category="quality", message="Mock output in report")
        afc = AdminFeedbackCenter(project_id="p1", notifications=[n])
        afc2 = AdminFeedbackCenter.from_dict(afc.to_dict())
        assert afc2.notifications[0].message == "Mock output in report"


# ---------------------------------------------------------------------------
# MediaEvidenceCollection (nested)
# ---------------------------------------------------------------------------

class TestMediaEvidenceCollection:
    def test_from_dict_reconstructs_items(self):
        data = {
            "project_id": "p1",
            "run_id": "run-001",
            "items": [{"media_type": "screenshot", "file_path": "screenshots/login.png", "test_name": "login_test"}],
        }
        mc = MediaEvidenceCollection.from_dict(data)
        assert isinstance(mc.items[0], MediaEvidenceItem)
        assert mc.items[0].media_type == "screenshot"

    def test_roundtrip(self):
        item = MediaEvidenceItem(media_type="trace", file_path="traces/auth.zip")
        mc = MediaEvidenceCollection(project_id="p1", run_id="run-002", items=[item])
        mc2 = MediaEvidenceCollection.from_dict(mc.to_dict())
        assert mc2.run_id == "run-002"
        assert mc2.items[0].file_path == "traces/auth.zip"


# ---------------------------------------------------------------------------
# AnalyticsReport (nested)
# ---------------------------------------------------------------------------

class TestAnalyticsReport:
    def test_from_dict_reconstructs_metrics(self):
        data = {
            "project_id": "p1",
            "metrics": [{"metric_name": "test_pass_rate", "value": 0.95, "unit": "ratio"}],
        }
        ar = AnalyticsReport.from_dict(data)
        assert isinstance(ar.metrics[0], AnalyticsMetric)
        assert ar.metrics[0].value == 0.95

    def test_roundtrip(self):
        m = AnalyticsMetric(metric_name="scaffold_time_seconds", value=4.2, unit="seconds")
        ar = AnalyticsReport(project_id="p1", metrics=[m])
        ar2 = AnalyticsReport.from_dict(ar.to_dict())
        assert ar2.metrics[0].metric_name == "scaffold_time_seconds"


# ---------------------------------------------------------------------------
# __init__ re-exports
# ---------------------------------------------------------------------------

class TestPackageExports:
    def test_all_container_classes_importable_from_package(self):
        import core.schemas as s
        classes = [
            s.InputMap, s.InputSource,
            s.AutomationPlan, s.AutomationAction,
            s.ApprovalHistory, s.ApprovalDecision,
            s.ToolSelection, s.ToolRecommendation,
            s.ArtifactManifest, s.ArtifactRecord,
            s.AssistanceHistory, s.AssistanceRecord,
            s.ActivityLog, s.ActivityEvent,
            s.BlockerRegister, s.Blocker,
            s.ProgressTracker, s.ProgressItem,
            s.SelfAssessment, s.SelfAssessmentFinding,
            s.CleanupReport, s.CleanupCandidate,
            s.AIResilienceReport, s.AIProviderStatus, s.AIFallbackEvent,
            s.AdminFeedbackCenter, s.AdminNotification,
            s.MediaEvidenceCollection, s.MediaEvidenceItem,
            s.AnalyticsReport, s.AnalyticsMetric,
            s.ExecutionSummary, s.EvidenceItem,
            s.DeliveryPlan, s.DeliveryItem,
            s.QualityRubric, s.QualityCriterion,
        ]
        assert all(c is not None for c in classes)

    def test_constants_importable_from_package(self):
        import core.schemas as s
        assert "safe_local" in s.RISK_LEVELS
        assert "web_saas" in s.PROJECT_TYPES
        assert "text_brief" in s.INPUT_TYPES
