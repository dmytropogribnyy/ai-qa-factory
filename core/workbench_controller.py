"""WorkbenchController — orchestrates input classification and writes initial artifacts.

This is NOT a replacement for core/orchestrator.py. The orchestrator remains the
workflow execution engine. WorkbenchController is the initial classification and
artifact-writing layer (Phase 2A/2B).

Classify-only: no URL fetching, no browser execution, no credential use,
no external calls, no cleanup deletion.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

from core.input_context_resolver import InputContextResolver, _redact_secrets
from core.schemas.input_map import InputMap
from core.schemas.project_blueprint import ProjectBlueprint
from core.schemas.project_status import ProjectStatus
from core.schemas.task_classification import TaskClassification
from core.schemas.work_request import WorkRequest
from core.work_request_classifier import WorkRequestClassifier


_BLOCKED_TYPES = frozenset({
    "target_url",
    "unknown_url",
    "credentials_reference",
    "api_docs_url",
    "design_url",
    "repo_url",
})

_OUTPUTS_ROOT = Path("outputs")


class WorkbenchController:
    """Coordinates input classification and writes structured artifacts.

    Does NOT replace core/orchestrator.py. The orchestrator handles workflow execution.
    WorkbenchController handles the classify-only intake phase (Phase 2A).
    """

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self._resolver = InputContextResolver()
        self._classifier = WorkRequestClassifier()
        self._outputs_root = outputs_root or _OUTPUTS_ROOT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_inputs(
        self,
        raw_inputs: List[str],
        raw_text: str = "",
        source_platform: str = "unknown",
        project_id: Optional[str] = None,
    ) -> dict:
        """Classify inputs and return a structured result dict.

        No artifacts are written. Safe for use in unit tests.
        """
        pid = project_id or str(uuid4())
        if not raw_text and raw_inputs:
            raw_text = " ".join(raw_inputs)

        # Redact secrets from raw_text before any storage or classification
        raw_text, _ = _redact_secrets(raw_text)

        input_map = self._resolver.resolve(raw_inputs, pid)
        work_request, task_classification = self._classifier.classify(
            raw_text, input_map, source_platform
        )
        project_status = self._build_initial_status(pid, task_classification)
        next_step = self._determine_next_safe_step(input_map, task_classification)

        return {
            "project_id": pid,
            "input_map": input_map,
            "work_request": work_request,
            "task_classification": task_classification,
            "project_status": project_status,
            "next_safe_step": next_step,
        }

    def build_initial_context(
        self,
        raw_inputs: List[str],
        raw_text: str = "",
        source_platform: str = "unknown",
        project_id: Optional[str] = None,
    ) -> dict:
        """Classify and write artifacts to outputs/<project_id>/00_project/.

        Returns the same result dict as analyze_inputs plus artifact paths.
        """
        result = self.analyze_inputs(raw_inputs, raw_text, source_platform, project_id)
        artifact_paths = self._write_artifacts(result)
        result["artifact_paths"] = artifact_paths
        return result

    def render_initial_artifacts(self, result: dict) -> dict:
        """Write artifacts for a pre-computed result dict. Returns artifact paths."""
        return self._write_artifacts(result)

    def get_next_safe_step(
        self,
        input_map: InputMap,
        task_classification: TaskClassification,
    ) -> str:
        return self._determine_next_safe_step(input_map, task_classification)

    # ------------------------------------------------------------------
    # Phase 2B — Blueprint API
    # ------------------------------------------------------------------

    def build_project_blueprint(
        self,
        input_map: InputMap,
        work_request: WorkRequest,
        task_classification: TaskClassification,
    ) -> ProjectBlueprint:
        """Build a ProjectBlueprint from Phase 2A context. No external calls."""
        from core.project_blueprint_builder import ProjectBlueprintBuilder
        return ProjectBlueprintBuilder().build(input_map, work_request, task_classification)

    def render_blueprint_artifacts(
        self,
        blueprint: ProjectBlueprint,
        task_type: str,
        project_id: str,
    ) -> dict:
        """Write Phase 2B planning artifacts to outputs/<project_id>/00_project/. Returns path dict."""
        from core.project_blueprint_builder import ProjectBlueprintBuilder
        out_dir = self._outputs_root / project_id / "00_project"
        return ProjectBlueprintBuilder().render_artifacts(blueprint, task_type, out_dir)

    def update_project_status_for_blueprint(
        self,
        project_id: str,
        blueprint: ProjectBlueprint,
    ) -> ProjectStatus:
        """Return a ProjectStatus reflecting Phase 2B completion."""
        n_missing = len(blueprint.missing_information)
        return ProjectStatus(
            project_id=project_id,
            phase="blueprint",
            overall_status="in_progress",
            next_action=(
                f"Review blueprint and resolve {n_missing} missing information item(s) "
                "before proceeding to Phase 2C."
            ),
            notes=(
                f"Phase 2B blueprint complete. "
                f"confidence={blueprint.confidence_level} "
                f"project_type={blueprint.project_type}"
            ),
        )

    def build_context_with_blueprint(
        self,
        raw_inputs: List[str],
        raw_text: str = "",
        source_platform: str = "unknown",
        project_id: Optional[str] = None,
    ) -> dict:
        """Phase 2A + 2B: classify inputs, write all artifacts including blueprint.

        Returns the combined result dict with keys:
          project_id, input_map, work_request, task_classification,
          project_status, next_safe_step, artifact_paths,
          blueprint, blueprint_status, blueprint_artifact_paths.
        """
        result = self.build_initial_context(raw_inputs, raw_text, source_platform, project_id)

        blueprint = self.build_project_blueprint(
            result["input_map"],
            result["work_request"],
            result["task_classification"],
        )
        blueprint_status = self.update_project_status_for_blueprint(result["project_id"], blueprint)
        blueprint_paths = self.render_blueprint_artifacts(
            blueprint,
            result["task_classification"].task_type,
            result["project_id"],
        )

        result["blueprint"] = blueprint
        result["blueprint_status"] = blueprint_status
        result["blueprint_artifact_paths"] = blueprint_paths
        result["artifact_paths"].update(blueprint_paths)

        return result

    # ------------------------------------------------------------------
    # Phase 2C — QA Strategy API
    # ------------------------------------------------------------------

    def build_qa_strategy(
        self,
        blueprint: ProjectBlueprint,
        input_map=None,
        work_request=None,
        task_classification=None,
    ):
        """Build a QAStrategy from a ProjectBlueprint. No external calls."""
        from core.qa_strategy_planner import QAStrategyPlanner
        return QAStrategyPlanner().build_strategy(
            blueprint, input_map, work_request, task_classification
        )

    def render_strategy_artifacts(
        self,
        strategy,
        project_id: str,
        updated_status=None,
    ) -> dict:
        """Write Phase 2C strategy artifacts to outputs/<project_id>/02_strategy/. Returns path dict."""
        from core.qa_strategy_planner import QAStrategyPlanner
        out_dir = self._outputs_root / project_id / "02_strategy"
        return QAStrategyPlanner().render_strategy_artifacts(strategy, out_dir, updated_status)

    def update_project_status_for_strategy(
        self,
        project_id: str,
        strategy,
    ) -> ProjectStatus:
        """Return a ProjectStatus reflecting Phase 2C completion."""
        n_blocked = sum(1 for a in strategy.strategy_areas if a.blocked)
        n_approvals = len(strategy.required_approvals)
        return ProjectStatus(
            project_id=project_id,
            phase="strategy",
            overall_status="in_progress",
            completed_phases=["intake", "blueprint"],
            pending_approvals=strategy.required_approvals[:5],
            next_action=(
                f"Review QA strategy (Phase 2C-R): {n_blocked} blocked area(s), "
                f"{n_approvals} required approval(s). "
                "Resolve approvals before proceeding to Phase 2D / Phase 3A."
            ),
            notes=(
                f"Phase 2C strategy complete. "
                f"project_type={strategy.project_type} "
                f"confidence={strategy.confidence_level} "
                f"client_ready={strategy.client_ready}"
            ),
        )

    def build_context_with_strategy(
        self,
        raw_inputs: List[str],
        raw_text: str = "",
        source_platform: str = "unknown",
        project_id: Optional[str] = None,
    ) -> dict:
        """Phase 2A + 2B + 2C: classify, blueprint, and build QA strategy.

        Returns combined result dict with keys:
          project_id, input_map, work_request, task_classification,
          project_status, next_safe_step, artifact_paths,
          blueprint, blueprint_status, blueprint_artifact_paths,
          strategy, strategy_status, strategy_artifact_paths.
        """
        result = self.build_context_with_blueprint(raw_inputs, raw_text, source_platform, project_id)

        strategy = self.build_qa_strategy(
            result["blueprint"],
            result["input_map"],
            result["work_request"],
            result["task_classification"],
        )
        strategy_status = self.update_project_status_for_strategy(result["project_id"], strategy)
        strategy_paths = self.render_strategy_artifacts(strategy, result["project_id"], strategy_status)

        result["strategy"] = strategy
        result["strategy_status"] = strategy_status
        result["strategy_artifact_paths"] = strategy_paths
        result["artifact_paths"].update(strategy_paths)

        return result

    # ------------------------------------------------------------------
    # Phase 3A — Framework Scaffold API
    # ------------------------------------------------------------------

    def build_framework_scaffold(
        self,
        blueprint,
        strategy=None,
        project_id: Optional[str] = None,
    ):
        """Generate a Playwright TypeScript scaffold from blueprint + strategy. No execution."""
        from core.framework_scaffold_generator import FrameworkScaffoldGenerator
        pid = project_id or blueprint.project_id
        out_dir = self._outputs_root / pid / "03_framework" / "playwright"
        return FrameworkScaffoldGenerator().generate_scaffold(blueprint, strategy, out_dir)

    def render_framework_scaffold_artifacts(
        self,
        scaffold,
        project_id: str,
    ) -> dict:
        """Write FRAMEWORK_SCAFFOLD.json and .md metadata. Returns path dict."""
        from core.framework_scaffold_generator import FrameworkScaffoldGenerator
        out_dir = self._outputs_root / project_id / "03_framework" / "playwright"
        return FrameworkScaffoldGenerator().render_scaffold_artifacts(scaffold, out_dir)

    def update_project_status_for_scaffold(
        self,
        project_id: str,
        scaffold,
    ):
        """Return a ProjectStatus reflecting Phase 3A completion."""
        n_files = len(scaffold.files)
        return ProjectStatus(
            project_id=project_id,
            phase="scaffold",
            overall_status="in_progress",
            completed_phases=["intake", "blueprint", "strategy"],
            next_action=(
                f"Review scaffold ({n_files} files generated). "
                "Complete docs/SCAFFOLD_REVIEW_CHECKLIST.md before any local validation. "
                "execution_allowed=False — explicit approval required."
            ),
            notes=(
                f"Phase 3A scaffold complete. "
                f"framework_type={scaffold.framework_type} "
                f"execution_allowed={scaffold.execution_allowed} "
                f"client_visible={scaffold.client_visible}"
            ),
        )

    def build_context_with_scaffold(
        self,
        raw_inputs: List[str],
        raw_text: str = "",
        source_platform: str = "unknown",
        project_id: Optional[str] = None,
    ) -> dict:
        """Phase 2A + 2B + 2C + 3A: classify, blueprint, strategy, scaffold.

        Returns combined result dict with keys:
          project_id, input_map, work_request, task_classification,
          project_status, next_safe_step, artifact_paths,
          blueprint, blueprint_status, blueprint_artifact_paths,
          strategy, strategy_status, strategy_artifact_paths,
          scaffold, scaffold_status, scaffold_artifact_paths.
        """
        result = self.build_context_with_strategy(raw_inputs, raw_text, source_platform, project_id)

        scaffold = self.build_framework_scaffold(
            result["blueprint"],
            result.get("strategy"),
            result["project_id"],
        )
        scaffold_status = self.update_project_status_for_scaffold(result["project_id"], scaffold)
        scaffold_paths = self.render_framework_scaffold_artifacts(scaffold, result["project_id"])

        result["scaffold"] = scaffold
        result["scaffold_status"] = scaffold_status
        result["scaffold_artifact_paths"] = scaffold_paths
        result["artifact_paths"].update(scaffold_paths)

        return result

    # ------------------------------------------------------------------
    # Phase 3B — Scaffold Validation API
    # ------------------------------------------------------------------

    def validate_framework_scaffold(
        self,
        scaffold_root_or_project_id: str,
        project_id: Optional[str] = None,
    ):
        """Statically validate a generated scaffold. No execution of any kind.

        Args:
            scaffold_root_or_project_id: Either a filesystem path to a scaffold root,
                or a project_id (looks up outputs/<id>/03_framework/playwright/).
            project_id: Optional override for project_id in the report.
        """
        from core.scaffold_validator import ScaffoldValidator
        root = Path(scaffold_root_or_project_id)
        if not root.exists():
            root = self._outputs_root / scaffold_root_or_project_id / "03_framework" / "playwright"
        pid = project_id or root.parent.parent.parent.name
        return ScaffoldValidator(outputs_root=self._outputs_root).validate_scaffold(root, pid)

    def render_scaffold_validation_artifacts(
        self,
        report,
        plan,
        project_id: str,
    ) -> dict:
        """Write validation artifacts under the scaffold root. Returns path dict."""
        from core.scaffold_validator import ScaffoldValidator
        out_dir = Path(report.scaffold_root)
        return ScaffoldValidator(outputs_root=self._outputs_root).render_validation_artifacts(report, plan, out_dir)

    def build_toolchain_validation_plan(
        self,
        scaffold_root_or_project_id: str,
        project_id: Optional[str] = None,
    ):
        """Build a ToolchainValidationPlan without executing anything."""
        from core.scaffold_validator import ScaffoldValidator
        root = Path(scaffold_root_or_project_id)
        if not root.exists():
            root = self._outputs_root / scaffold_root_or_project_id / "03_framework" / "playwright"
        pid = project_id or root.parent.parent.parent.name
        return ScaffoldValidator(outputs_root=self._outputs_root).build_toolchain_validation_plan(root, pid)

    # ------------------------------------------------------------------
    # Phase 3C — Toolchain Validation API
    # ------------------------------------------------------------------

    def validate_toolchain(
        self,
        scaffold_root_or_project_id: str,
        project_id: Optional[str] = None,
        approved: bool = False,
        command_timeout: int = 120,
    ):
        """Run approval-gated toolchain validation. Returns (report, approval_record).

        Without approved=True: all commands skipped, no shell commands executed.
        With approved=True: runs only allowlisted local commands inside scaffold root.
        safe_to_execute_tests remains False always.
        """
        from core.toolchain_validator import ToolchainValidator
        root = Path(scaffold_root_or_project_id)
        if not root.exists():
            root = self._outputs_root / scaffold_root_or_project_id / "03_framework" / "playwright"
        pid = project_id or root.parent.parent.parent.name
        return ToolchainValidator(outputs_root=self._outputs_root).validate_toolchain(
            root, pid, approved=approved, command_timeout=command_timeout
        )

    def render_toolchain_validation_artifacts(
        self,
        report,
        approval,
        project_id: Optional[str] = None,
    ) -> dict:
        """Write toolchain validation artifacts under the scaffold root. Returns path dict."""
        from core.toolchain_validator import ToolchainValidator
        root = Path(report.scaffold_root)
        return ToolchainValidator(outputs_root=self._outputs_root).render_toolchain_artifacts(
            report, approval, root
        )

    # ------------------------------------------------------------------
    # Phase 4A — Execution Readiness API
    # ------------------------------------------------------------------

    def plan_execution_readiness(
        self,
        project_id: str,
        scaffold_root=None,
    ):
        """Inspect local artifacts and return (checklist, readiness_report). No execution."""
        from core.execution_readiness_planner import ExecutionReadinessPlanner
        root = None
        if scaffold_root is not None:
            root = Path(scaffold_root)
            if not root.exists():
                root = self._outputs_root / scaffold_root / "03_framework" / "playwright"
        return ExecutionReadinessPlanner(outputs_root=self._outputs_root).plan_readiness(project_id, root)

    def render_execution_plan_artifacts(
        self,
        checklist,
        report,
        project_id: str,
    ) -> dict:
        """Write execution plan artifacts to outputs/<project_id>/04_execution_plan/."""
        from core.execution_readiness_planner import ExecutionReadinessPlanner
        return ExecutionReadinessPlanner(outputs_root=self._outputs_root).render_execution_plan_artifacts(
            checklist, report, project_id
        )

    # ------------------------------------------------------------------
    # Phase 4B — Evidence Foundation API
    # ------------------------------------------------------------------

    def build_evidence_foundation(
        self,
        project_id: str,
        scaffold_root=None,
    ):
        """Register local artifacts as evidence. Returns (collection, quality_gate, redaction_report)."""
        from core.evidence_manager import EvidenceManager
        root = None
        if scaffold_root is not None:
            root = Path(scaffold_root)
            if not root.exists():
                root = self._outputs_root / scaffold_root / "03_framework" / "playwright"
        return EvidenceManager(outputs_root=self._outputs_root).build_evidence_foundation(project_id, root)

    def render_evidence_artifacts(
        self,
        collection,
        quality_gate,
        redaction_report,
        project_id: str,
    ) -> dict:
        """Write evidence artifacts to outputs/<project_id>/05_evidence/."""
        from core.evidence_manager import EvidenceManager
        return EvidenceManager(outputs_root=self._outputs_root).render_evidence_artifacts(
            collection, quality_gate, redaction_report, project_id
        )

    # ------------------------------------------------------------------
    # Phase 4C — Report Draft API
    # ------------------------------------------------------------------

    def build_report_drafts(
        self,
        project_id: str,
        scaffold_root=None,
    ):
        """Build draft reports from local artifacts. Returns (internal, client, delivery_note, checklist)."""
        from core.report_draft_builder import ReportDraftBuilder
        root = None
        if scaffold_root is not None:
            root = Path(scaffold_root)
            if not root.exists():
                root = self._outputs_root / scaffold_root / "03_framework" / "playwright"
        return ReportDraftBuilder(outputs_root=self._outputs_root).build_report_drafts(project_id, root)

    def render_report_drafts(
        self,
        internal_summary,
        client_report,
        delivery_note,
        quality_checklist,
        project_id: str,
    ) -> dict:
        """Write report draft artifacts to outputs/<project_id>/06_client_draft/."""
        from core.report_draft_builder import ReportDraftBuilder
        return ReportDraftBuilder(outputs_root=self._outputs_root).render_report_drafts(
            internal_summary, client_report, delivery_note, quality_checklist, project_id
        )

    # ------------------------------------------------------------------
    # Phase 4C — Delivery Preview API
    # ------------------------------------------------------------------

    def build_delivery_preview(
        self,
        project_id: str,
        scaffold_root=None,
    ):
        """Inspect local artifacts and return (preview, safety_checklist). No packaging."""
        from core.delivery_preview_builder import DeliveryPreviewBuilder
        root = None
        if scaffold_root is not None:
            root = Path(scaffold_root)
            if not root.exists():
                root = self._outputs_root / scaffold_root / "03_framework" / "playwright"
        return DeliveryPreviewBuilder(outputs_root=self._outputs_root).build_delivery_preview(project_id, root)

    def render_delivery_preview_artifacts(
        self,
        preview,
        checklist,
        project_id: str,
    ) -> dict:
        """Write delivery preview artifacts to outputs/<project_id>/06_client_draft/."""
        from core.delivery_preview_builder import DeliveryPreviewBuilder
        return DeliveryPreviewBuilder(outputs_root=self._outputs_root).render_delivery_preview_artifacts(
            preview, checklist, project_id
        )

    # ------------------------------------------------------------------
    # Phase 4ABC — Scenario Evaluation API
    # ------------------------------------------------------------------

    def evaluate_scenarios(
        self,
        project_id: str,
        fixtures_root=None,
    ):
        """Evaluate local scenario fixtures. No external calls. Returns batch report."""
        from core.scenario_batch_evaluator import ScenarioBatchEvaluator
        fr = Path(fixtures_root) if fixtures_root else None
        return ScenarioBatchEvaluator(fixtures_root=fr, outputs_root=self._outputs_root).evaluate_scenarios(project_id)

    def render_scenario_evaluation_artifacts(
        self,
        report,
        project_id: str,
    ) -> dict:
        """Write evaluation artifacts to outputs/<project_id>/99_internal/scenario_evaluation/."""
        from core.scenario_batch_evaluator import ScenarioBatchEvaluator
        return ScenarioBatchEvaluator(outputs_root=self._outputs_root).render_scenario_evaluation_artifacts(
            report, project_id
        )

    # ------------------------------------------------------------------
    # Phase 4D — Controlled Browser Execution API
    # ------------------------------------------------------------------

    def run_controlled_browser_execution(
        self,
        project_id: str,
        scaffold_root=None,
        approve_demo: bool = False,
        approve_public_readonly: bool = False,
        target_category=None,
        base_url=None,
        demo_profile=None,
        readonly_profile=None,
        command_mode: str = "list",
        timeout: int = 120,
    ):
        """Run approval-gated controlled browser execution and return BrowserExecutionReport."""
        from core.browser_execution_runner import BrowserExecutionRunner
        runner = BrowserExecutionRunner(outputs_root=self._outputs_root)
        return runner.run_browser_execution(
            project_id=project_id,
            scaffold_root=scaffold_root,
            approve_demo=approve_demo,
            approve_public_readonly=approve_public_readonly,
            target_category=target_category,
            base_url=base_url,
            demo_profile=demo_profile,
            readonly_profile=readonly_profile,
            command_mode=command_mode,
            timeout=timeout,
        )

    def render_browser_execution_artifacts(
        self,
        approval,
        report,
        project_id: str,
    ) -> dict:
        """Write browser execution artifacts to outputs/<project_id>/07_execution/."""
        from core.browser_execution_runner import BrowserExecutionRunner
        runner = BrowserExecutionRunner(outputs_root=self._outputs_root)
        return runner.render_execution_artifacts(approval, report, project_id)

    # ------------------------------------------------------------------
    # Phase 4E — Credential Safety API
    # ------------------------------------------------------------------

    def inspect_credential_safety(
        self,
        project_id: str,
        include_fixtures: bool = False,
        include_scaffold: bool = False,
        strict: bool = False,
    ):
        """Inspect credential safety for a project. Returns (policy, report, storage_policy, auth_approval).

        No real credentials used. No login. No .env reading. Static inspection only.
        """
        from core.credential_safety_inspector import CredentialSafetyInspector
        inspector = CredentialSafetyInspector(outputs_root=self._outputs_root)
        report = inspector.inspect_credentials(
            project_id=project_id,
            include_fixtures=include_fixtures,
            include_scaffold=include_scaffold,
            strict=strict,
        )
        policy = inspector.build_credential_policy(project_id)
        storage_policy = inspector.build_storage_state_policy(project_id)
        auth_approval = inspector.build_auth_execution_approval(project_id)
        return policy, report, storage_policy, auth_approval

    def render_credential_safety_artifacts(
        self,
        policy,
        report,
        storage_policy,
        auth_approval,
        project_id: str,
    ) -> dict:
        """Write credential safety artifacts to outputs/<project_id>/08_credentials/."""
        from core.credential_safety_inspector import CredentialSafetyInspector
        inspector = CredentialSafetyInspector(outputs_root=self._outputs_root)
        return inspector.render_credential_safety_artifacts(
            policy, report, storage_policy, auth_approval, project_id
        )

    # ------------------------------------------------------------------
    # Phase 4F — Demo Auth Execution API
    # ------------------------------------------------------------------

    def run_demo_auth_execution(
        self,
        project_id: str,
        scaffold_root=None,
        approve_demo_auth: bool = False,
        auth_profile=None,
        command_mode: str = "auth_smoke",
        timeout: int = 120,
    ):
        """Run approval-gated demo auth execution. Returns AuthExecutionReport.

        No real credentials. No personal/production accounts.
        No Alza/Amazon/Google/Linear auth.
        Requires approve_demo_auth=True and auth_profile='saucedemo_demo_auth'.
        """
        from core.demo_auth_runner import DemoAuthRunner
        from pathlib import Path
        runner = DemoAuthRunner(outputs_root=self._outputs_root)
        return runner.run_demo_auth_execution(
            project_id=project_id,
            scaffold_root=Path(scaffold_root) if scaffold_root else None,
            approve_demo_auth=approve_demo_auth,
            auth_profile=auth_profile,
            command_mode=command_mode,
            timeout=timeout,
        )

    def render_demo_auth_artifacts(self, report, project_id: str) -> dict:
        """Write demo auth artifacts to outputs/<project_id>/09_auth/."""
        from core.demo_auth_runner import DemoAuthRunner
        runner = DemoAuthRunner(outputs_root=self._outputs_root)
        return runner.render_auth_artifacts(report, project_id)

    # Phase 4G — Scenario Execution Matrix API

    def build_scenario_execution_matrix(
        self,
        project_id: str,
        include_test_account_plan: bool = True,
        decision_url: Optional[str] = None,
        scenario_type: Optional[str] = None,
        target_category: Optional[str] = None,
        profile: Optional[str] = None,
    ):
        """Build the canonical scenario execution matrix. No execution, no credentials."""
        from core.scenario_execution_matrix import ScenarioExecutionMatrixBuilder
        builder = ScenarioExecutionMatrixBuilder(outputs_root=self._outputs_root)
        return builder.build_matrix(
            project_id=project_id,
            include_test_account_plan=include_test_account_plan,
            decision_url=decision_url,
            scenario_type=scenario_type,
            target_category=target_category,
            profile=profile,
        )

    def decide_scenario_execution(
        self,
        project_id: str,
        target_url: Optional[str],
        scenario_type: str,
        target_category: Optional[str] = None,
        profile: Optional[str] = None,
    ):
        """Classify a URL/scenario into an execution lane. No execution, no credentials."""
        from core.scenario_execution_matrix import ScenarioExecutionMatrixBuilder
        builder = ScenarioExecutionMatrixBuilder(outputs_root=self._outputs_root)
        return builder.decide_execution(
            project_id=project_id,
            target_url=target_url,
            scenario_type=scenario_type,
            target_category=target_category,
            profile=profile,
        )

    def build_dedicated_test_account_plan(self, project_id: str):
        """Build dedicated test-account planning document. No execution, no credentials."""
        from core.scenario_execution_matrix import ScenarioExecutionMatrixBuilder
        builder = ScenarioExecutionMatrixBuilder(outputs_root=self._outputs_root)
        return builder.build_dedicated_test_account_plan(project_id)

    def render_scenario_execution_matrix_artifacts(self, report, project_id: str) -> dict:
        """Write matrix artifacts to outputs/<project_id>/10_execution_matrix/."""
        from core.scenario_execution_matrix import ScenarioExecutionMatrixBuilder
        builder = ScenarioExecutionMatrixBuilder(outputs_root=self._outputs_root)
        return builder.render_matrix_artifacts(report, project_id)

    # ------------------------------------------------------------------
    # Phase 5AB — Runtime Secret Routing + Dedicated Auth API
    # ------------------------------------------------------------------

    def validate_test_account_intake(
        self,
        project_id: str,
        target_url: Optional[str] = None,
        target_category: str = "",
        scenario_lane: str = "",
        account_provider: str = "",
        account_type: str = "",
        username_env_var: Optional[str] = None,
        password_env_var: Optional[str] = None,
        token_env_var: Optional[str] = None,
        dedicated_test_account_confirmed: bool = False,
        personal_account_confirmed: bool = False,
        production_account_confirmed: bool = False,
        staging_environment_confirmed: bool = False,
        client_scope_confirmed: bool = False,
    ):
        """Validate a dedicated test-account intake request. No execution, no env value reading."""
        from core.dedicated_auth_runner import DedicatedAuthRunner
        runner = DedicatedAuthRunner(outputs_root=self._outputs_root)
        return runner.validate_intake(
            project_id=project_id,
            target_url=target_url,
            target_category=target_category,
            scenario_lane=scenario_lane,
            account_provider=account_provider,
            account_type=account_type,
            username_env_var=username_env_var,
            password_env_var=password_env_var,
            token_env_var=token_env_var,
            dedicated_test_account_confirmed=dedicated_test_account_confirmed,
            personal_account_confirmed=personal_account_confirmed,
            production_account_confirmed=production_account_confirmed,
            staging_environment_confirmed=staging_environment_confirmed,
            client_scope_confirmed=client_scope_confirmed,
        )

    def run_dedicated_auth_execution(
        self,
        project_id: str,
        approve_dedicated_auth_execution: bool = False,
        scenario_lane: str = "",
        target_category: str = "",
        target_url: Optional[str] = None,
        username_env_var: Optional[str] = None,
        password_env_var: Optional[str] = None,
        token_env_var: Optional[str] = None,
        dedicated_test_account_confirmed: bool = False,
        staging_environment_confirmed: bool = False,
        client_scope_confirmed: bool = False,
        personal_account_confirmed: bool = False,
        production_account_confirmed: bool = False,
        command_mode: str = "auth_smoke",
        scaffold_root=None,
        timeout: int = 120,
    ):
        """Run approval-gated dedicated test-account auth execution. Returns DedicatedAuthExecutionReport.

        No personal/production accounts. No Google OAuth. No raw secrets in arguments.
        Requires approve_dedicated_auth_execution=True and all safety gates to pass.
        """
        from core.dedicated_auth_runner import DedicatedAuthRunner
        runner = DedicatedAuthRunner(outputs_root=self._outputs_root)
        return runner.run_dedicated_auth(
            project_id=project_id,
            approve_dedicated_auth_execution=approve_dedicated_auth_execution,
            scenario_lane=scenario_lane,
            target_category=target_category,
            target_url=target_url,
            username_env_var=username_env_var,
            password_env_var=password_env_var,
            token_env_var=token_env_var,
            dedicated_test_account_confirmed=dedicated_test_account_confirmed,
            staging_environment_confirmed=staging_environment_confirmed,
            client_scope_confirmed=client_scope_confirmed,
            personal_account_confirmed=personal_account_confirmed,
            production_account_confirmed=production_account_confirmed,
            command_mode=command_mode,
            scaffold_root=scaffold_root,
            timeout=timeout,
        )

    def render_dedicated_auth_artifacts(self, report, project_id: str) -> dict:
        """Write dedicated auth artifacts to outputs/<project_id>/12_dedicated_auth/."""
        from core.dedicated_auth_runner import DedicatedAuthRunner
        runner = DedicatedAuthRunner(outputs_root=self._outputs_root)
        return runner.render_dedicated_auth_artifacts(report, project_id)

    # ------------------------------------------------------------------
    # Phase 5D — API Auth Smoke
    # ------------------------------------------------------------------

    def run_api_auth_smoke(
        self,
        project_id: str,
        approve_api_auth_execution: bool = False,
        target_profile: str = "",
        base_url: str = None,
        username_env_var: str = None,
        password_env_var: str = None,
        personal_account_confirmed: bool = False,
        production_account_confirmed: bool = False,
        run_safe_read_check: bool = True,
        timeout: int = 30,
    ):
        from core.api_auth_runner import APIAuthRunner
        runner = APIAuthRunner(outputs_root=self._outputs_root)
        return runner.run_api_auth(
            project_id=project_id,
            approve_api_auth_execution=approve_api_auth_execution,
            target_profile=target_profile,
            base_url=base_url,
            username_env_var=username_env_var,
            password_env_var=password_env_var,
            personal_account_confirmed=personal_account_confirmed,
            production_account_confirmed=production_account_confirmed,
            run_safe_read_check=run_safe_read_check,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_initial_status(
        self, project_id: str, classification: TaskClassification
    ) -> ProjectStatus:
        return ProjectStatus(
            project_id=project_id,
            phase="intake",
            overall_status="in_progress",
            next_action=f"Review classification ({classification.task_type}) and approve next step",
            notes=f"Phase 2A intake complete. confidence={classification.confidence}",
        )

    def _determine_next_safe_step(
        self,
        input_map: InputMap,
        classification: TaskClassification,
    ) -> str:
        blocked = [s for s in input_map.sources if s.input_type in _BLOCKED_TYPES]
        has_credentials = any(
            s.input_type == "credentials_reference" for s in input_map.sources
        )

        if has_credentials:
            return (
                "BLOCKED: Credential reference detected. "
                "No credential use permitted in Phase 2A. "
                "Review credential references and obtain explicit approval before proceeding."
            )

        if blocked:
            blocked_types = sorted({s.input_type for s in blocked})
            return (
                f"REVIEW REQUIRED: Inputs of type(s) {blocked_types} require approval "
                "before any fetch, execution, or access. "
                "Approve target URLs / external resources manually, then proceed to Phase 2B."
            )

        task_type = classification.task_type
        if task_type == "qa_automation":
            return (
                "Safe to proceed to Phase 2B: "
                "Generate project blueprint and QA strategy from classified inputs. "
                "No external execution until approved."
            )
        if task_type == "api_testing":
            return (
                "Safe to proceed to Phase 2B: "
                "Generate API test strategy. "
                "No API calls until target URL and credentials are approved."
            )
        if task_type == "proposal":
            return (
                "Safe to proceed: Generate proposal draft from brief. "
                "No external access required."
            )
        if task_type == "test_strategy":
            return (
                "Safe to proceed to Phase 2B: "
                "Generate test strategy document from classified inputs."
            )
        return (
            "Review classified inputs and task type, then decide next phase. "
            "No automatic execution without explicit approval."
        )

    # ------------------------------------------------------------------
    # Artifact writing
    # ------------------------------------------------------------------

    def _write_artifacts(self, result: dict) -> dict:
        project_id: str = result["project_id"]
        out_dir = self._outputs_root / project_id / "00_project"
        out_dir.mkdir(parents=True, exist_ok=True)

        input_map: InputMap = result["input_map"]
        work_request: WorkRequest = result["work_request"]
        classification: TaskClassification = result["task_classification"]
        status: ProjectStatus = result["project_status"]
        next_step: str = result["next_safe_step"]

        paths = {}

        # INPUT_MAP
        paths["input_map_json"] = self._write_json(
            out_dir / "INPUT_MAP.json", input_map.to_dict()
        )
        paths["input_map_md"] = self._write_text(
            out_dir / "INPUT_MAP.md",
            self._render_input_map(input_map),
        )

        # WORK_REQUEST
        paths["work_request_json"] = self._write_json(
            out_dir / "WORK_REQUEST.json", work_request.to_dict()
        )
        paths["work_request_md"] = self._write_text(
            out_dir / "WORK_REQUEST.md",
            self._render_work_request(work_request),
        )

        # TASK_CLASSIFICATION
        paths["task_classification_json"] = self._write_json(
            out_dir / "TASK_CLASSIFICATION.json", classification.to_dict()
        )
        paths["task_classification_md"] = self._write_text(
            out_dir / "TASK_CLASSIFICATION.md",
            self._render_classification(classification),
        )

        # PROJECT_STATUS
        paths["project_status_json"] = self._write_json(
            out_dir / "PROJECT_STATUS.json", status.to_dict()
        )
        paths["project_status_md"] = self._write_text(
            out_dir / "PROJECT_STATUS.md",
            self._render_project_status(status),
        )

        # NEXT_SAFE_STEP
        paths["next_safe_step_md"] = self._write_text(
            out_dir / "NEXT_SAFE_STEP.md",
            self._render_next_step(next_step, classification),
        )

        return paths

    # ------------------------------------------------------------------
    # Markdown renderers
    # ------------------------------------------------------------------

    def _render_input_map(self, im: InputMap) -> str:
        lines = [
            f"# Input Map — {im.project_id}",
            "",
            f"**Created:** {im.created_at}",
            f"**Sources:** {len(im.sources)}",
            "",
            "---",
            "",
        ]
        for i, src in enumerate(im.sources, 1):
            lines += [
                f"## Source {i}: `{src.input_type}`",
                "",
                f"- **Label:** {src.label}",
                f"- **Approved:** {src.approved}",
            ]
            if src.raw_value:
                truncated = src.raw_value[:200] + ("..." if len(src.raw_value) > 200 else "")
                lines += [f"- **Value (truncated):** {truncated}"]
            if src.classification_notes:
                lines += [f"- **Notes:** {src.classification_notes}"]
            lines.append("")
        return "\n".join(lines)

    def _render_work_request(self, wr: WorkRequest) -> str:
        lines = [
            f"# Work Request — {wr.project_id}",
            "",
            f"**Title:** {wr.request_title}",
            f"**Platform:** {wr.source_platform}",
            f"**Created:** {wr.created_at}",
            "",
            "## Summary",
            "",
            wr.request_summary or "_No summary extracted._",
            "",
        ]
        if wr.inputs:
            lines += ["## Input types", ""]
            for inp in wr.inputs:
                lines.append(f"- {inp}")
            lines.append("")
        if wr.target_urls:
            lines += ["## Target URLs (not yet approved)", ""]
            for url in wr.target_urls:
                lines.append(f"- `{url}` — blocked; requires approval")
            lines.append("")
        if wr.tags:
            lines += ["## Tags", ""]
            lines.append(", ".join(f"`{t}`" for t in wr.tags))
            lines.append("")
        return "\n".join(lines)

    def _render_classification(self, tc: TaskClassification) -> str:
        lines = [
            f"# Task Classification — {tc.project_id}",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| Task type | `{tc.task_type}` |",
            f"| Project type | `{tc.project_type}` |",
            f"| Platform | `{tc.source_platform}` |",
            f"| Confidence | {tc.confidence} |",
            f"| Classified at | {tc.classified_at} |",
            "",
            "## Notes",
            "",
            tc.notes or "_none_",
            "",
            "## Signals",
            "",
        ]
        for sig in tc.signals:
            lines.append(f"- `{sig}`")
        lines.append("")
        return "\n".join(lines)

    def _render_project_status(self, ps: ProjectStatus) -> str:
        lines = [
            f"# Project Status — {ps.project_id}",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| Phase | `{ps.phase}` |",
            f"| Status | `{ps.overall_status}` |",
            f"| Updated | {ps.updated_at} |",
            "",
            "## Next action",
            "",
            ps.next_action or "_none_",
            "",
        ]
        if ps.notes:
            lines += ["## Notes", "", ps.notes, ""]
        return "\n".join(lines)

    def _render_next_step(self, next_step: str, tc: TaskClassification) -> str:
        lines = [
            "# Next Safe Step",
            "",
            f"**Task type:** `{tc.task_type}`  ",
            f"**Project type:** `{tc.project_type}`  ",
            f"**Confidence:** {tc.confidence}",
            "",
            "---",
            "",
            next_step,
            "",
            "---",
            "",
            "_Generated by WorkbenchController (Phase 2A — classify only). "
            "No execution has occurred. All URLs, credentials, and external resources "
            "require explicit approval before any access._",
            "",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # File helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _write_json(path: Path, data: dict) -> str:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return str(path)

    @staticmethod
    def _write_text(path: Path, content: str) -> str:
        path.write_text(content, encoding="utf-8")
        return str(path)
