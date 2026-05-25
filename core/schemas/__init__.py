from __future__ import annotations

from core.schemas.base import SchemaMixin
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
    CREDENTIAL_TYPES,
    CREDENTIAL_STORAGE_MODES,
    AUTH_FLOW_TYPES,
    AUTH_ACTION_RISK_LEVELS,
    SECRET_REDACTION_TARGETS,
    APP_SURFACES,
    AUTH_MECHANISMS,
    AUTH_PROVIDERS,
    MOBILE_AUTH_CONTEXTS,
    MOBILE_EXECUTION_TARGETS,
    MOBILE_TOOLING_OPTIONS,
    INTEGRATION_PROVIDERS,
    INTEGRATION_DIRECTIONS,
    INTEGRATION_EVENT_TYPES,
    DOC_TYPES,
    DOC_STATUSES,
    DOC_UPDATE_TRIGGERS,
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
from core.schemas.safety import SafetyCheck, SafetyReport, SafetyAssessment
from core.schemas.execution_summary import EvidenceItem, ExecutionSummary
from core.schemas.assistance import AssistanceRecord, AssistanceHistory
from core.schemas.activity_log import ActivityEvent, ActivityLog
from core.schemas.blocker import Blocker, BlockerRegister
from core.schemas.progress import ProgressItem, ProgressTracker
from core.schemas.self_assessment import SelfAssessmentFinding, SelfAssessment
from core.schemas.project_status import ProjectStatus
from core.schemas.cleanup import CleanupPolicy, CleanupCandidate, CleanupReport
from core.schemas.ai_resilience import AIProviderStatus, AIFallbackEvent, AIResilienceReport
from core.schemas.admin_feedback import AdminNotification, AdminFeedbackCenter
from core.schemas.media_evidence import MediaEvidenceItem, MediaEvidenceCollection
from core.schemas.analytics import AnalyticsMetric, AnalyticsReport
from core.schemas.mobile_testing import MobileTestTarget, MobileExecutionPlan
from core.schemas.integration import IntegrationEndpoint, IntegrationEvent, IntegrationPolicy
from core.schemas.credentials import CredentialReference, CredentialPolicy, CredentialUseApproval
from core.schemas.auth_flow import AuthFlowStep, AuthFlowPlan, AuthCheckResult
from core.schemas.redaction import SecretRedactionRule, RedactionReport
from core.schemas.documentation import (
    DocumentationRecord,
    DocumentationManifest,
    DocumentationFreshnessCheck,
    DocumentationFreshnessReport,
)
from core.schemas.qa_strategy import (
    QAStrategyArea,
    RiskMatrixItem,
    TestLayerRecommendation,
    TacticalPlanningItem,
    StrategyDecision,
    QAStrategy,
)
from core.schemas.framework_scaffold import (
    FrameworkFile,
    FrameworkScaffold,
    FrameworkScaffoldPlan,
)
from core.schemas.scaffold_validation import (
    ScaffoldValidationCheck,
    ScaffoldValidationReport,
    ToolchainValidationPlan,
)

__all__ = [
    # Base
    "SchemaMixin",
    # Constants
    "INPUT_TYPES",
    "RISK_LEVELS",
    "PROJECT_TYPES",
    "ENVIRONMENT_TYPES",
    "ACTION_STATUSES",
    "ACCESS_LEVELS",
    "ARTIFACT_TYPES",
    "ASSISTANT_TYPES",
    "WORK_DOMAINS",
    "TASK_TYPES",
    "DELIVERABLE_TYPES",
    # Credential / auth constants
    "CREDENTIAL_TYPES",
    "CREDENTIAL_STORAGE_MODES",
    "AUTH_FLOW_TYPES",
    "AUTH_ACTION_RISK_LEVELS",
    "SECRET_REDACTION_TARGETS",
    # Web/mobile auth constants
    "APP_SURFACES",
    "AUTH_MECHANISMS",
    "AUTH_PROVIDERS",
    "MOBILE_AUTH_CONTEXTS",
    # Mobile execution constants
    "MOBILE_EXECUTION_TARGETS",
    "MOBILE_TOOLING_OPTIONS",
    # Integration constants
    "INTEGRATION_PROVIDERS",
    "INTEGRATION_DIRECTIONS",
    "INTEGRATION_EVENT_TYPES",
    # Documentation governance constants
    "DOC_TYPES",
    "DOC_STATUSES",
    "DOC_UPDATE_TRIGGERS",
    # Input/context
    "SourceReference",
    "WorkRequest",
    "TaskClassification",
    "InputSource",
    "InputMap",
    # Project/blueprint
    "ProjectBlueprint",
    "DeliveryItem",
    "DeliveryPlan",
    "QualityCriterion",
    "QualityRubric",
    # Execution
    "AutomationAction",
    "AutomationPlan",
    "ApprovalDecision",
    "ApprovalHistory",
    "ToolRecommendation",
    "ToolSelection",
    "ArtifactRecord",
    "ArtifactManifest",
    "RunContext",
    "SafetyCheck",
    "SafetyReport",
    "SafetyAssessment",
    "EvidenceItem",
    "ExecutionSummary",
    "AssistanceRecord",
    "AssistanceHistory",
    # Monitoring
    "ActivityEvent",
    "ActivityLog",
    "Blocker",
    "BlockerRegister",
    "ProgressItem",
    "ProgressTracker",
    "SelfAssessmentFinding",
    "SelfAssessment",
    "ProjectStatus",
    # Ops
    "CleanupPolicy",
    "CleanupCandidate",
    "CleanupReport",
    "AIProviderStatus",
    "AIFallbackEvent",
    "AIResilienceReport",
    "AdminNotification",
    "AdminFeedbackCenter",
    "MediaEvidenceItem",
    "MediaEvidenceCollection",
    "AnalyticsMetric",
    "AnalyticsReport",
    # Credentials
    "CredentialReference",
    "CredentialPolicy",
    "CredentialUseApproval",
    # Auth flows
    "AuthFlowStep",
    "AuthFlowPlan",
    "AuthCheckResult",
    # Redaction
    "SecretRedactionRule",
    "RedactionReport",
    # Mobile testing
    "MobileTestTarget",
    "MobileExecutionPlan",
    # Integration
    "IntegrationEndpoint",
    "IntegrationEvent",
    "IntegrationPolicy",
    # Documentation governance
    "DocumentationRecord",
    "DocumentationManifest",
    "DocumentationFreshnessCheck",
    "DocumentationFreshnessReport",
    # QA Strategy (Phase 2C)
    "QAStrategyArea",
    "RiskMatrixItem",
    "TestLayerRecommendation",
    "TacticalPlanningItem",
    "StrategyDecision",
    "QAStrategy",
    # Framework Scaffold (Phase 3A)
    "FrameworkFile",
    "FrameworkScaffold",
    "FrameworkScaffoldPlan",
    # Scaffold Validation (Phase 3B)
    "ScaffoldValidationCheck",
    "ScaffoldValidationReport",
    "ToolchainValidationPlan",
]
