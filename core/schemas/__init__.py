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
from core.schemas.toolchain_validation import (
    ToolchainCommandResult,
    ToolchainApprovalRecord,
    ToolchainValidationReport,
)
from core.schemas.execution_approval import (
    ExecutionApprovalRequirement,
    ExecutionApprovalChecklist,
    ExecutionReadinessReport,
)
from core.schemas.evidence import (
    EvidenceRecord,
    EvidenceCollection,
    EvidenceQualityGate,
    EvidenceRedactionReport,
)
from core.schemas.reporting import (
    ReportSection,
    ReportDraft,
    ReportQualityChecklist,
    DeliveryNoteDraft,
)
from core.schemas.delivery_preview import (
    DeliveryPreviewItem,
    DeliveryPackagePreview,
    DeliverySafetyChecklist,
)
from core.schemas.scenario_evaluation import (
    ScenarioEvaluationResult,
    ScenarioBatchEvaluationReport,
)
from core.schemas.browser_execution import (
    BrowserExecutionApproval,
    BrowserExecutionCommand,
    BrowserExecutionEvidence,
    BrowserExecutionReport,
)
from core.schemas.credential_safety import (
    CredentialReference as CredentialSafetyReference,
    CredentialPolicy as CredentialSafetyPolicy,
    CredentialSafetyReport,
    TestAccountProfile,
    StorageStatePolicy,
    AuthExecutionApproval,
    SandboxProfileClassification,
)
from core.schemas.auth_execution import (
    AuthCredentialProfile,
    AuthExecutionCommand,
    AuthExecutionReport,
    AuthSessionArtifact,
)
from core.schemas.scenario_execution_matrix import (
    ScenarioExecutionLane,
    ScenarioPermissionRule,
    ScenarioTargetProfile,
    ScenarioExecutionDecision,
    ScenarioExecutionMatrixReport,
    DedicatedTestAccountRequirement,
    CredentialProvisioningRoute,
    DedicatedTestAccountPlan,
)
from core.schemas.runtime_secret_routing import (
    RuntimeSecretReference,
    TestAccountIntakeRequest,
    TestAccountValidationResult,
    DedicatedAuthExecutionCommand,
    DedicatedAuthSessionArtifact,
    DedicatedAuthExecutionReport,
)
from core.schemas.api_auth import (
    APIAuthTarget,
    APIAuthCommand,
    APIAuthSessionArtifact,
    APIAuthExecutionReport,
)
from core.schemas.qa_report import (
    QAEvidenceItem,
    QAEvidenceSource,
    QACoverageSummary,
    QASecretScanResult,
    QAEvidenceReport,
)
from core.schemas.google_auth import (
    GOOGLE_AUTH_MODES,
    GOOGLE_AUTH_MODES_EXECUTABLE_5G,
    GOOGLE_AUTH_MODES_PLANNING_ONLY_5G,
    GOOGLE_TARGET_KINDS,
    GoogleTestAccountProfile,
    GoogleAuthModePolicy,
    GoogleStorageStatePolicy,
    GoogleAuthCapability,
    GoogleAuthExecutionDecision,
    GoogleAuthEvidenceReport,
)
# Phase 5H — Task Source Integration
from core.schemas.task_source import (
    TASK_SOURCE_PROVIDERS,
    TASK_SOURCE_PROVIDERS_EXECUTABLE_5H,
    TASK_SOURCE_PROVIDERS_PLANNING_ONLY_5H,
    TaskSourceToken,
    TaskSourceIssue,
    TaskSourceFetchPolicy,
    TaskSourceScenario,
    TaskSourceFetchReport,
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
    # Toolchain Validation (Phase 3C)
    "ToolchainCommandResult",
    "ToolchainApprovalRecord",
    "ToolchainValidationReport",
    # Execution Approval (Phase 4A)
    "ExecutionApprovalRequirement",
    "ExecutionApprovalChecklist",
    "ExecutionReadinessReport",
    # Evidence (Phase 4B)
    "EvidenceRecord",
    "EvidenceCollection",
    "EvidenceQualityGate",
    "EvidenceRedactionReport",
    # Reporting (Phase 4C)
    "ReportSection",
    "ReportDraft",
    "ReportQualityChecklist",
    "DeliveryNoteDraft",
    # Delivery Preview (Phase 4C)
    "DeliveryPreviewItem",
    "DeliveryPackagePreview",
    "DeliverySafetyChecklist",
    # Scenario Evaluation (Phase 4ABC)
    "ScenarioEvaluationResult",
    "ScenarioBatchEvaluationReport",
    # Browser Execution (Phase 4D)
    "BrowserExecutionApproval",
    "BrowserExecutionCommand",
    "BrowserExecutionEvidence",
    "BrowserExecutionReport",
    # Credential Safety (Phase 4E)
    # Note: exported with Safety prefix to avoid conflict with Phase 2A credential schemas
    "CredentialSafetyReference",
    "CredentialSafetyPolicy",
    "CredentialSafetyReport",
    "TestAccountProfile",
    "StorageStatePolicy",
    "AuthExecutionApproval",
    "SandboxProfileClassification",
    # Auth Execution (Phase 4F)
    "AuthCredentialProfile",
    "AuthExecutionCommand",
    "AuthExecutionReport",
    "AuthSessionArtifact",
    # Scenario Execution Matrix (Phase 4G)
    "ScenarioExecutionLane",
    "ScenarioPermissionRule",
    "ScenarioTargetProfile",
    "ScenarioExecutionDecision",
    "ScenarioExecutionMatrixReport",
    "DedicatedTestAccountRequirement",
    "CredentialProvisioningRoute",
    "DedicatedTestAccountPlan",
    # Runtime Secret Routing + Dedicated Auth (Phase 5AB)
    "RuntimeSecretReference",
    "TestAccountIntakeRequest",
    "TestAccountValidationResult",
    "DedicatedAuthExecutionCommand",
    "DedicatedAuthSessionArtifact",
    "DedicatedAuthExecutionReport",
    # Phase 5E — API Auth Smoke
    "APIAuthTarget",
    "APIAuthCommand",
    "APIAuthSessionArtifact",
    "APIAuthExecutionReport",
    # Phase 5F — QA Evidence Report
    "QAEvidenceItem",
    "QAEvidenceSource",
    "QACoverageSummary",
    "QASecretScanResult",
    "QAEvidenceReport",
    # Phase 5G — Google/OAuth Test Account Capability
    "GOOGLE_AUTH_MODES",
    "GOOGLE_AUTH_MODES_EXECUTABLE_5G",
    "GOOGLE_AUTH_MODES_PLANNING_ONLY_5G",
    "GOOGLE_TARGET_KINDS",
    "GoogleTestAccountProfile",
    "GoogleAuthModePolicy",
    "GoogleStorageStatePolicy",
    "GoogleAuthCapability",
    "GoogleAuthExecutionDecision",
    "GoogleAuthEvidenceReport",
    # Phase 5H — Task Source Integration
    "TASK_SOURCE_PROVIDERS",
    "TASK_SOURCE_PROVIDERS_EXECUTABLE_5H",
    "TASK_SOURCE_PROVIDERS_PLANNING_ONLY_5H",
    "TaskSourceToken",
    "TaskSourceIssue",
    "TaskSourceFetchPolicy",
    "TaskSourceScenario",
    "TaskSourceFetchReport",
]
