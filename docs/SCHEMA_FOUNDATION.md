# Schema Foundation — Guided QA Automation Workbench

**Version:** 5.10.0  
**Updated:** 2026-05-26  
**Phase:** 5K — Schema foundations + all phases through Phase 5K

---

## Purpose

`core/schemas/` defines the domain model for every structured concept the workbench works with: inputs, blueprints, approvals, artifacts, test evidence, monitoring, and ops.

These are pure Python dataclasses. They have no side effects, no database, no external calls. They exist to:

1. Give every concept in the system a named, typed, serialisable shape
2. Make `to_dict()` / `from_dict()` round-trips explicit and tested
3. Provide a shared vocabulary for agents, state, reports, and future persistence layers
4. Prevent string-dict soup in agent code

---

## Base pattern

All schema classes inherit `SchemaMixin` from `core/schemas/base.py`:

```python
class SchemaMixin:
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)   # dataclasses.asdict — recursive

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> T:
        known = {f.name for f in fields(cls)}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)
```

Container schemas (those with `List[SomeRecord]` fields) override `from_dict` explicitly to reconstruct typed objects from raw dicts. This is intentional — no reflection magic, just clear per-class handling.

---

## Constants (`core/schemas/constants.py`)

Frozen sets for valid values used as field values across schemas:

| Constant | Purpose |
|---|---|
| `INPUT_TYPES` | Valid `input_type` values for `InputSource` |
| `RISK_LEVELS` | Risk level taxonomy (safe_analysis → client_delivery) |
| `PROJECT_TYPES` | Project type taxonomy (web_saas, ecommerce, …) |
| `ENVIRONMENT_TYPES` | local, staging, production, sandbox, unknown |
| `ACTION_STATUSES` | pending, approved, rejected, running, completed, failed, skipped |
| `ACCESS_LEVELS` | none, read_only, read_write, admin |
| `ARTIFACT_TYPES` | test_strategy, scaffold, report, evidence, … |
| `ASSISTANT_TYPES` | workflow entry points: prescreen, scaffold, full, … |
| `WORK_DOMAINS` | web_ui, api, mobile, performance, security, … |
| `TASK_TYPES` | prescreen, proposal, test_design, scaffold, … |
| `DELIVERABLE_TYPES` | proposal, test_plan, test_cases, report, … |

These constants are informational — schemas do not validate field values against them at construction time. Validation can be added in Phase 2 if needed.

---

## Schema modules

### Input / context

| Module | Classes | Description |
|---|---|---|
| `source_reference` | `SourceReference` | Origin of a work request (URL, platform, raw text) |
| `work_request` | `WorkRequest` | Normalised intake record with UUID, brief, platform, target URLs |
| `task_classification` | `TaskClassification` | Classification result: task type, project type, confidence, signals |
| `input_map` | `InputSource`, `InputMap` | Classified inputs for a project; explicit nested from_dict |

### Project / blueprint

| Module | Classes | Description |
|---|---|---|
| `project_blueprint` | `ProjectBlueprint` | Structured source-of-truth: type, stack, scope, risks |
| `delivery_plan` | `DeliveryItem`, `DeliveryPlan` | Planned deliverables with status; explicit nested from_dict |
| `quality_rubric` | `QualityCriterion`, `QualityRubric` | Scoring criteria with weights; explicit nested from_dict |

### Execution

| Module | Classes | Description |
|---|---|---|
| `automation_plan` | `AutomationAction`, `AutomationPlan` | Planned test actions with risk level and framework; explicit nested from_dict |
| `approval` | `ApprovalDecision`, `ApprovalHistory` | Per-action approval/rejection record; explicit nested from_dict |
| `tool_selection` | `ToolRecommendation`, `ToolSelection` | Tool recommendations with rationale; explicit nested from_dict |
| `artifact_manifest` | `ArtifactRecord`, `ArtifactManifest` | Registry of all generated artifacts; explicit nested from_dict |
| `run_context` | `RunContext` | Execution context: workflow, mode, flags, agents run |
| `safety` | `SafetyCheck`, `SafetyReport` | Per-rule safety evaluation with violation details; explicit nested from_dict |
| `execution_summary` | `EvidenceItem`, `ExecutionSummary` | Test run results with evidence items; explicit nested from_dict |
| `assistance` | `AssistanceRecord`, `AssistanceHistory` | AI assistance session log; explicit nested from_dict |

### Monitoring

| Module | Classes | Description |
|---|---|---|
| `activity_log` | `ActivityEvent`, `ActivityLog` | Ordered event timeline; explicit nested from_dict |
| `blocker` | `Blocker`, `BlockerRegister` | Open blockers with severity/status; explicit nested from_dict |
| `progress` | `ProgressItem`, `ProgressTracker` | Progress items with completion %; explicit nested from_dict |
| `self_assessment` | `SelfAssessmentFinding`, `SelfAssessment` | Automated quality findings; explicit nested from_dict |
| `project_status` | `ProjectStatus` | Phase, overall status, pending approvals, next action |

### Ops

| Module | Classes | Description |
|---|---|---|
| `cleanup` | `CleanupPolicy`, `CleanupCandidate`, `CleanupReport` | Retention/cleanup policy (all-preserve defaults); dry-run cleanup candidates (approved_for_deletion=False by default); explicit nested from_dict on CleanupReport |
| `ai_resilience` | `AIProviderStatus`, `AIFallbackEvent`, `AIResilienceReport` | Provider health + fallback history; explicit nested from_dict |
| `admin_feedback` | `AdminNotification`, `AdminFeedbackCenter` | Admin notifications requiring attention; explicit nested from_dict |
| `media_evidence` | `MediaEvidenceItem`, `MediaEvidenceCollection` | Screenshots, traces, videos from test runs; explicit nested from_dict |
| `analytics` | `AnalyticsMetric`, `AnalyticsReport` | Aggregated project metrics; explicit nested from_dict |

### Documentation governance

| Module | Classes | Description |
|---|---|---|
| `documentation` | `DocumentationRecord`, `DocumentationManifest`, `DocumentationFreshnessCheck`, `DocumentationFreshnessReport` | Documentation metadata registry and freshness audit results. `DocumentationManifest.docs` reconstructed as typed `DocumentationRecord` objects; `DocumentationFreshnessReport.checks` reconstructed as `DocumentationFreshnessCheck` objects. `docs_current = False` by default — audit must explicitly confirm docs are current. |

### QA Strategy (Phase 2C)

| Module | Classes | Description |
|---|---|---|
| `qa_strategy` | `QAStrategyArea` | One area of QA focus (e.g., auth, e2e flows, payment). `blocked=False` by default; set to `True` with `blocked_reason` when the area requires approval before any work can begin. |
| `qa_strategy` | `RiskMatrixItem` | One risk entry with likelihood, impact, severity, and mitigation. `blocked=False`, `approval_required=False` by default. Payment and auth risks have `approval_required=True` by default. |
| `qa_strategy` | `TestLayerRecommendation` | Recommendation for one test layer (unit, integration, e2e, api, visual, etc.). `recommended=True`, `blocked=False` by default. Mobile-native layer is always `blocked=True` in Phase 2C. Nested `examples` and `notes` are plain `List[str]`. |
| `qa_strategy` | `TacticalPlanningItem` | One tactical planning step (e.g., "Define test data strategy"). `requires_approval=False`, `blocked=False` by default. |
| `qa_strategy` | `StrategyDecision` | A recorded strategy decision with rationale and alternatives considered. |
| `qa_strategy` | `QAStrategy` | Root strategy object. All 5 list types have explicit nested reconstruction in `from_dict`. `client_ready=False` always — never changed by the planner. `confidence_level` is one of: `low`, `medium`, `high`. |

### Framework Scaffold (Phase 3A)

| Module | Classes | Description |
|---|---|---|
| `framework_scaffold` | `FrameworkFile` | One file in a generated scaffold. Fields: `id`, `path`, `purpose`, `file_type`, `client_visible=False`, `generated=True`, `requires_review=True`, `notes`. |
| `framework_scaffold` | `FrameworkScaffold` | Root scaffold object. Contains `List[FrameworkFile]` with explicit nested reconstruction in `from_dict`. Hard safety defaults: `execution_allowed=False`, `client_visible=False`, `requires_review=True`. `scaffold_status` is one of: `planned`, `generated`, `needs_review`, `approved_for_local_validation`, `rejected`. |
| `framework_scaffold` | `FrameworkScaffoldPlan` | Planning-only object that describes what the scaffold will contain: `included_layers`, `deferred_layers`, `blocked_layers`, `required_approvals`, `recommended_structure`. Created by `FrameworkScaffoldGenerator.build_scaffold_plan()` before generation. |

Module constants:
- `FILE_TYPES` — valid `file_type` values: `package_json`, `tsconfig`, `playwright_config`, `test_spec`, `page_object`, `fixture`, `utility`, `test_data`, `documentation`, `gitignore`, `ci_config`, `example_env`, `unknown`
- `FRAMEWORK_TYPES` — `playwright_ts`, `api_only`, `mixed_ui_api`, `unknown`
- `SCAFFOLD_STATUSES` — `planned`, `generated`, `needs_review`, `approved_for_local_validation`, `rejected`

Runtime: `core/framework_scaffold_generator.py` — `FrameworkScaffoldGenerator`. Generates all scaffold files as plain text strings and writes them to disk. No subprocess, no browser, no npm, no external calls.

---

## Phase 3B — Scaffold Validation schemas

These schemas represent the output of static scaffold inspection (Phase 3B).
No runtime execution is performed — all fields are populated by reading local files.

| Module | Classes | Description |
|---|---|---|
| `scaffold_validation` | `ScaffoldValidationCheck` | One static check result. Fields: `id` (e.g. `CHK-001`), `name`, `category`, `status` (pass/fail/warning/skipped), `severity` (info/low/medium/high/critical), `file_path`, `message`, `recommendation`, `blocks_next_phase`, `notes`. |
| `scaffold_validation` | `ScaffoldValidationReport` | Root validation report. Contains `List[ScaffoldValidationCheck]` with explicit nested reconstruction in `from_dict`. Hard safety defaults: all execution/npm/npx/browser/external flags `False`, `safe_to_execute_tests=False`. `validation_status` is one of: `pass`, `fail`, `warning`, `unknown`. |
| `scaffold_validation` | `ToolchainValidationPlan` | Describes what toolchain commands WOULD be run with approval. Safety defaults: `approval_required=True`, `network_access_required=True`, `browser_execution_required=False`, `safe_without_approval=False`. Never executes anything. |

Module constants:
- `VALIDATION_STATUSES` — `pass`, `fail`, `warning`, `unknown`, `skipped`
- `CHECK_STATUSES` — `pass`, `fail`, `warning`, `skipped`
- `SEVERITIES` — `info`, `low`, `medium`, `high`, `critical`
- `CATEGORIES` — `structure`, `metadata`, `safety`, `secrets`, `urls`, `package_json`, `config`, `env`, `tests`, `docs`, `repository_boundary`, `toolchain_plan`

Runtime: `core/scaffold_validator.py` — `ScaffoldValidator`. Inspects scaffold files statically. No subprocess, no browser, no npm, no Playwright, no external calls. All six execution flags remain `False` always.

---

## Phase 3C — Toolchain Validation schemas

These schemas represent the output of approval-gated local toolchain validation (Phase 3C).
All four safety invariant fields (`safe_to_execute_tests`, `browser_execution_performed`,
`external_url_used`, `credentials_used`) are hardcoded `False` and never overridden.

| Module | Classes | Description |
|---|---|---|
| `toolchain_validation` | `ToolchainCommandResult` | One command execution result. Fields: `id`, `command`, `cwd`, `exit_code`, `stdout_excerpt`, `stderr_excerpt`, `status` (pass/fail/skipped/blocked), `duration_seconds`, `executed`, `skipped_reason`, `safety_notes`. |
| `toolchain_validation` | `ToolchainApprovalRecord` | Records the approval state at validation time. Fields: `project_id`, `scaffold_root`, `approved` (bool), `approval_source` (`cli_flag` or `not_provided`), `approval_reason`, `approved_commands`, `denied_commands`, `safety_constraints`. |
| `toolchain_validation` | `ToolchainValidationReport` | Root validation report. Contains `List[ToolchainCommandResult]` with explicit nested reconstruction in `from_dict`. Hard safety defaults: `browser_execution_performed=False`, `external_url_used=False`, `credentials_used=False`, `safe_to_execute_tests=False`. `validation_status` is one of: `pass`, `fail`, `blocked`, `skipped`, `warning`, `unknown`. |

Module constants:
- `TOOLCHAIN_STATUSES` — `pass`, `fail`, `blocked`, `skipped`, `warning`, `unknown`
- `COMMAND_STATUSES` — `pass`, `fail`, `skipped`, `blocked`
- `ALLOWED_COMMAND_CATEGORIES` — `dependency_install`, `typecheck`, `discovery`
- `BLOCKED_COMMAND_CATEGORIES` — `test_execution`, `browser_launch`, `external_call`, `install_browsers`

Runtime: `core/toolchain_validator.py` — `ToolchainValidator`. Runs only allowlisted commands
(`npm install`, `npm run typecheck`, `npx playwright test --list`) inside scaffold root.
Requires `approved=True`; without it, all commands are skipped. Strips sensitive env vars
before any subprocess call. Four safety invariants are hardcoded `False` always.

---

## Safety defaults

| Default | Why |
|---|---|
| `CleanupReport.dry_run = True` | Cleanup never executes automatically |
| `CleanupCandidate.approved_for_deletion = False` | Explicit approval required per candidate |
| `SafetyReport.all_passed = True` | Fail-safe: only set to False on violation |
| `RunContext.approved = False` | Approval is opt-in, not assumed |
| `RunContext.mode = "unknown"` | Workflow mode must be set explicitly |
| `RunContext.llm_mode = "mock"` | Real LLM mode must be explicitly requested |
| `FrameworkScaffold.execution_allowed = False` | No test may run without explicit approval |
| `FrameworkScaffold.client_visible = False` | Scaffold is internal until delivery is approved |
| `FrameworkScaffold.requires_review = True` | Senior QA review required before any use |
| `FrameworkFile.client_visible = False` | Individual files inherit scaffold visibility default |
| `ScaffoldValidationReport.execution_performed = False` | Static validator never executes code |
| `ScaffoldValidationReport.npm_performed = False` | No npm commands run during validation |
| `ScaffoldValidationReport.npx_performed = False` | No npx commands run during validation |
| `ScaffoldValidationReport.browser_performed = False` | No browser launched during validation |
| `ScaffoldValidationReport.external_calls_performed = False` | No network calls during validation |
| `ScaffoldValidationReport.safe_to_execute_tests = False` | Tests must not run based on static validation alone |
| `ToolchainValidationPlan.approval_required = True` | All toolchain commands require explicit approval |
| `ToolchainValidationPlan.safe_without_approval = False` | No toolchain command is safe to run without approval |
| `ToolchainValidationReport.safe_to_execute_tests = False` | Toolchain validation alone never grants test execution permission |
| `ToolchainValidationReport.browser_execution_performed = False` | No browser launched during toolchain validation |
| `ToolchainValidationReport.external_url_used = False` | No external URLs contacted during toolchain validation |
| `ToolchainValidationReport.credentials_used = False` | No credentials read or injected during toolchain validation |
| `ToolchainApprovalRecord.approved = False` | Default: no approval; must be set via `--approve-toolchain` |

---

## Credential and auth safety schemas (Phase 1B-auth)

**Schema-only foundation. No runtime auth execution in this phase.**

Three modules added in Phase 1B-auth addendum:

### `credentials.py`

| Class | Description |
|---|---|
| `CredentialReference` | Metadata reference for a test credential. Stores only env var names — never actual secret values. `raw_value_stored = False`, `requires_approval_before_use = True`, `approved_for_use = False` by default. |
| `CredentialPolicy` | Project-level policy governing credential use. All protective defaults enabled. `allow_credential_use = False`, `allow_production_credentials = False`, `prohibit_destructive_account_actions = True`. |
| `CredentialUseApproval` | Recorded approval for using a credential in a specific action. `approved = False` by default. Forbidden actions list pre-populated with destructive account actions. |

### `auth_flow.py`

| Class | Description |
|---|---|
| `AuthFlowStep` | One step in an auth flow plan. `risk_level = "payment_or_auth"`, `requires_approval = True`, `destructive = False`, `allowed_in_production = False` by default. |
| `AuthFlowPlan` | Full auth flow plan. `blocked = True`, `safe_to_execute = False`, `approved = False` by default. Nested `steps` reconstructed as `AuthFlowStep` objects via explicit `from_dict`. |
| `AuthCheckResult` | Result of an auth check — metadata only. `executed = False`, `auth_success = None`, `secrets_redacted = True`, `client_safe = False` by default. Must never store usernames, passwords, tokens, or session values. |

### `redaction.py`

| Class | Description |
|---|---|
| `SecretRedactionRule` | One redaction rule: target + pattern type + replacement string. `replacement = "[REDACTED]"`, `enabled = True` by default. |
| `RedactionReport` | Summary of redaction applied for a run. `redaction_performed = False`, `blocked_client_delivery = False` by default. Nested `rules_applied` reconstructed as `SecretRedactionRule` objects. |

### New constants (credentials/auth)

`CREDENTIAL_TYPES`, `CREDENTIAL_STORAGE_MODES`, `AUTH_FLOW_TYPES`, `AUTH_ACTION_RISK_LEVELS`, `SECRET_REDACTION_TARGETS` — all added to `core/schemas/constants.py`.

### Runtime auth execution — deferred

The schemas above define the data model for future credential-aware and auth-aware testing. Runtime behaviour (reading `.env`, executing login flows, applying redaction to actual output) is **not implemented in this phase**. See `APPROVAL_MODEL.md` for the approval gates that will govern runtime use.

---

## Phase 2A runtime modules (classify-only)

These modules add the first runtime layer: input classification and artifact writing.
They do not replace `core/orchestrator.py` and do not execute any external calls.

| Module | Class(es) | Description |
|---|---|---|
| `core/input_context_resolver.py` | `InputContextResolver` | Classifies raw inputs (URLs, files, text) into `InputSource` objects. Redacts secrets. No URL fetching, no browser, no external calls. |
| `core/work_request_classifier.py` | `WorkRequestClassifier` | Classifies `InputMap` + text into `WorkRequest` + `TaskClassification`. Keyword-based signal detection. No external calls. |
| `core/workbench_controller.py` | `WorkbenchController` | Coordinates classification and writes structured artifacts to `outputs/<project_id>/00_project/`. Does NOT replace `core/orchestrator.py`. |

**Artifacts written by `WorkbenchController.build_initial_context()`:**
- `INPUT_MAP.json` / `.md` — all classified input sources
- `WORK_REQUEST.json` / `.md` — normalised work request
- `TASK_CLASSIFICATION.json` / `.md` — task type, project type, confidence, signals
- `PROJECT_STATUS.json` / `.md` — current phase and next action
- `NEXT_SAFE_STEP.md` — human-readable guidance

**Secret redaction (Phase 2A):** passwords, tokens, cookies, API keys, and session values
detected in raw input are replaced with `[REDACTED_PASSWORD]`, `[REDACTED_TOKEN]`,
`[REDACTED_COOKIE]`, or `[REDACTED_SECRET]` before any value is stored. If secrets are
detected, a notice is added to artifacts stating that no credential use was performed.

---

## Phase 2B runtime modules (planning/blueprint)

These modules add the Project Blueprint builder. They consume Phase 2A output and produce
planning artifacts. No URL fetching, no browser, no credential use, no external calls.

| Module | Class(es) | Description |
|---|---|---|
| `core/project_blueprint_builder.py` | `ProjectBlueprintBuilder` | Builds `ProjectBlueprint` from `InputMap` + `WorkRequest` + `TaskClassification`. Infers project type, environment, surfaces, risks, assumptions, missing info, blocked actions, and QA strategy. |

**`ProjectBlueprintBuilder.build()`** produces a `ProjectBlueprint` with:
- Project type inference (web_saas, ecommerce, api_backend, ai_generated_app, admin_panel, auth_heavy, mixed_ui_api)
- Environment inference (staging, production, local, none, unknown)
- task_source vs target_application separation — task URL ≠ target application
- Assumptions, missing information, safe next steps, blocked actions
- Required approvals list
- Recommended strategy and tactical test focus
- Confidence level (low / medium / high)

**Artifacts written by `WorkbenchController.build_context_with_blueprint()`** (7 additional files):
- `PROJECT_BLUEPRINT.json` / `PROJECT_BLUEPRINT.md` — structured planning source-of-truth
- `ASSUMPTIONS.md` — working assumptions for client confirmation
- `MISSING_INFO.md` — information needed before strategy or execution
- `SAFE_NEXT_STEPS.md` — planning-only actions that can proceed immediately
- `BLOCKED_ACTIONS.md` — actions blocked until listed approvals are obtained
- `INITIAL_QA_STRATEGY_OUTLINE.md` — preliminary test layer and focus guidance

**New controller methods (Phase 2B):**
- `build_project_blueprint(input_map, work_request, task_classification) → ProjectBlueprint`
- `render_blueprint_artifacts(blueprint, task_type, project_id) → dict`
- `update_project_status_for_blueprint(project_id, blueprint) → ProjectStatus`
- `build_context_with_blueprint(raw_inputs, ...) → dict` — runs Phase 2A + 2B, writes all 14 artifacts

**CLI access:** `python tools/classify_inputs.py --with-blueprint`

---

## Phase 2C runtime modules (strategy planner)

These modules add the QA Strategy Planner. They consume Phase 2B output and produce
strategy artifacts. No URL fetching, no browser, no credential use, no external calls.
`client_ready = False` is a hard invariant — never modified by the planner.

| Module | Class(es) | Description |
|---|---|---|
| `core/qa_strategy_planner.py` | `QAStrategyPlanner` | Builds `QAStrategy` from `ProjectBlueprint` using local signal detection. Covers 8 project types. Writes 8 artifact files to `outputs/<project_id>/02_strategy/`. No LLM calls. |

**`QAStrategyPlanner.build_strategy()`** produces a `QAStrategy` with:
- Strategy areas tailored to the project type (e.g., auth testing, e2e flows, API contract)
- Risk matrix covering universal risks + type-specific + signal-detected (payment, mobile, integration)
- Test layer recommendations (unit, integration, e2e, api, visual, a11y, performance, security, mobile_native)
- Tactical planning outline with phase-ordered steps
- Strategy decisions with rationale
- Blocked actions and required approvals carried forward from blueprint
- Confidence level (low / medium / high)
- `client_ready = False` — always

**Artifacts written by `WorkbenchController.render_strategy_artifacts()`** (8 files):
- `QA_STRATEGY.json` / `QA_STRATEGY.md` — full strategy schema + human summary
- `TEST_SCOPE.md` — in-scope and out-of-scope areas
- `RISK_MATRIX.md` — risk items with likelihood, impact, mitigation
- `TEST_LAYERS.md` — recommended test layers
- `TACTICAL_PLAN_OUTLINE.md` — tactical planning sequence
- `QUALITY_RUBRIC.md` — quality criteria
- `STRATEGY_DECISIONS.md` — key decisions and rationale
- `PROJECT_STATUS.json` / `PROJECT_STATUS.md` — updated project status

**New controller methods (Phase 2C):**
- `build_qa_strategy(blueprint, input_map, work_request, task_classification) -> QAStrategy`
- `render_strategy_artifacts(strategy, project_id, updated_status) -> dict`
- `update_project_status_for_strategy(project_id, strategy) -> ProjectStatus`
- `build_context_with_strategy(raw_inputs, ...) -> dict` — runs Phase 2A + 2B + 2C, writes all 22+ artifacts

**CLI access:** `python tools/build_strategy.py` or `python tools/classify_inputs.py --with-strategy`

---

## State integration — deferred to Phase 2

`QAFactoryState` (`core/state.py`) currently holds free-form dict fields for agent outputs. Schema objects can be stored as `to_dict()` snapshots and rehydrated via `from_dict()`. The wiring is not done yet.

See the `TODO (Phase 2)` comment in `core/state.py` for the list of fields planned for integration. The deferral keeps all 69 existing mock-mode tests passing without change.

---

## Testing

All schemas have round-trip tests in `tests/test_schema_foundations.py`. Coverage:
- Constants: 6 checks
- Every schema class: at minimum `from_dict` reconstruction + round-trip
- Container schemas: explicit test that nested dicts are reconstructed as typed objects
- Defaults: `dry_run`, `approved`, `mode`, `all_passed`, counter fields

Run: `python -m pytest tests/test_schema_foundations.py -v`

---

## Phase 4ABC — Readiness, Evidence, Reporting, Delivery Preview, Scenario Evaluation schemas

Module files: `core/schemas/execution_approval.py`, `core/schemas/evidence.py`,
`core/schemas/reporting.py`, `core/schemas/delivery_preview.py`, `core/schemas/scenario_evaluation.py`

### Execution approval schemas (Phase 4A)

| Class | Description |
|---|---|
| `ExecutionApprovalRequirement` | A single approval requirement with risk level and `blocks_execution`. `approved=False` by default. |
| `ExecutionApprovalChecklist` | Aggregated checklist. `approved_for_execution=False`, `approved_for_browser_execution=False`, `approved_for_client_delivery=False` always. `from_dict` forces all three back to `False`. |
| `ExecutionReadinessReport` | Readiness summary. All `approved_for_*` flags are `False` by default. `from_dict` forces all back to `False`. |

### Evidence schemas (Phase 4B)

| Class | Description |
|---|---|
| `EvidenceRecord` | A single evidence record. `client_visible=False`, `internal_only=True`, `requires_redaction=True` by default. |
| `EvidenceCollection` | Full evidence collection. `ready_for_client_review=False` always. `from_dict` forces this back to `False`. |
| `EvidenceQualityGate` | Quality gate. `approved_for_client_view=False` always. `from_dict` forces this back to `False`. |
| `EvidenceRedactionReport` | Redaction status. `client_visible_blocked=True` by default. |

### Reporting schemas (Phase 4C)

| Class | Description |
|---|---|
| `ReportSection` | A section in a report. `client_visible=False`, `internal_only=True`, `requires_review=True` by default. |
| `ReportDraft` | A draft report. `status="draft"`, `approved_for_delivery=False` always. `from_dict` forces `approved_for_delivery=False`. |
| `ReportQualityChecklist` | Quality gate. `client_ready=False`, `approval_checked=False`, `safe_to_deliver=False` always. `from_dict` forces all three. |
| `DeliveryNoteDraft` | Delivery note draft. `approved_for_delivery=False` always. `from_dict` forces this. |

### Delivery preview schemas (Phase 4C)

| Class | Description |
|---|---|
| `DeliveryPreviewItem` | A single delivery candidate or exclusion. `approved_for_delivery=False` by default. |
| `DeliveryPackagePreview` | Preview manifest. `package_created=False`, `zip_created=False`, `approved_for_delivery=False` always. `from_dict` forces all three. |
| `DeliverySafetyChecklist` | Safety gate. `approved_for_delivery=False`, `safe_to_package=False` always. `from_dict` forces both. |

### Scenario evaluation schemas (Phase 4ABC)

| Class | Description |
|---|---|
| `ScenarioEvaluationResult` | Result for a single fixture file. `no_execution_confirmed=False` until confirmed by content scan. |
| `ScenarioBatchEvaluationReport` | Batch evaluation report. `evaluation_performed_without_execution=True`, `external_calls_performed=False` always. `from_dict` enforces both. |

### Safety defaults — Phase 4ABC

| Schema | Field | Default | from_dict enforced? |
|---|---|---|---|
| `ExecutionApprovalChecklist` | `approved_for_execution` | `False` | Yes |
| `ExecutionApprovalChecklist` | `approved_for_browser_execution` | `False` | Yes |
| `ExecutionApprovalChecklist` | `approved_for_client_delivery` | `False` | Yes |
| `ExecutionReadinessReport` | all `approved_for_*` flags | `False` | Yes (all 6) |
| `EvidenceRecord` | `client_visible` | `False` | — |
| `EvidenceCollection` | `ready_for_client_review` | `False` | Yes |
| `EvidenceQualityGate` | `approved_for_client_view` | `False` | Yes |
| `EvidenceRedactionReport` | `client_visible_blocked` | `True` | — |
| `ReportDraft` | `approved_for_delivery` | `False` | Yes |
| `ReportQualityChecklist` | `client_ready` | `False` | Yes |
| `ReportQualityChecklist` | `safe_to_deliver` | `False` | Yes |
| `ReportQualityChecklist` | `approval_checked` | `False` | Yes |
| `DeliveryNoteDraft` | `approved_for_delivery` | `False` | Yes |
| `DeliveryPackagePreview` | `package_created` | `False` | Yes |
| `DeliveryPackagePreview` | `zip_created` | `False` | Yes |
| `DeliveryPackagePreview` | `approved_for_delivery` | `False` | Yes |
| `DeliverySafetyChecklist` | `approved_for_delivery` | `False` | Yes |
| `DeliverySafetyChecklist` | `safe_to_package` | `False` | Yes |
| `ScenarioBatchEvaluationReport` | `evaluation_performed_without_execution` | `True` | Yes |
| `ScenarioBatchEvaluationReport` | `external_calls_performed` | `False` | Yes |
| `BrowserExecutionReport` | `safe_to_deliver` | `False` | Yes (`__post_init__`) |
| `BrowserExecutionReport` | `approved_for_client_delivery` | `False` | Yes (`__post_init__`) |
| `BrowserExecutionReport` | `client_delivery_created` | `False` | Yes (`__post_init__`) |
| `BrowserExecutionReport` | `credentials_used` | `False` | Yes (`__post_init__`) |
| `BrowserExecutionReport` | `destructive_actions_performed` | `False` | Yes (`__post_init__`) |
| `BrowserExecutionEvidence` | `client_visible` | `False` | — |
| `BrowserExecutionEvidence` | `internal_only` | `True` | — |

---

## Phase 4D — Browser Execution schemas

**Module:** `core/schemas/browser_execution.py`

| Class | Description |
|---|---|
| `BrowserExecutionApproval` | Records what was approved for a browser execution session. `approved=False` by default. Only set True by CLI approval flags after target validation. |
| `BrowserExecutionCommand` | A single Playwright command attempt. `executed=False`, `status=skipped` by default. |
| `BrowserExecutionEvidence` | Reference to evidence collected during execution. `internal_only=True`, `client_visible=False`, `requires_redaction=True` by default. |
| `BrowserExecutionReport` | Full report of a controlled execution session. Delivery flags forced False by `__post_init__`. `browser_execution_performed` and `playwright_test_execution_performed` may become True only when approved execution actually ran. |

Constants: `EXECUTION_STATUSES`, `COMMAND_STATUSES`, `EVIDENCE_TYPES`, `TARGET_CATEGORIES`, `COMMAND_MODES`

---

## Related documents

## Integration schemas (Phase 1B-n8n)

**Schema-only foundation. No runtime external calls in this phase.**

Module: `core/schemas/integration.py`

| Class | Description |
|---|---|
| `IntegrationEndpoint` | Reference descriptor for an optional external endpoint. `enabled = False`, `requires_approval = True` by default. `url_ref` holds an env var name — never a live URL with secrets. |
| `IntegrationEvent` | Metadata record for one workbench event queued for external delivery. `delivered = False`, `contains_sensitive_data = False`, `client_visible = False` by default. `payload_summary` is safe short metadata only. |
| `IntegrationPolicy` | Project-level policy. `allow_outbound_events = False`, `allow_inbound_webhooks = False`, `require_approval_for_external_calls = True`, `redact_sensitive_payloads = True` by default. `allowed_providers` defaults to empty — no provider is allowed without explicit configuration. |

**n8n model:** n8n is an optional external automation bridge, not the core orchestration engine. The Workbench handles all QA logic, state, approvals, and reporting. n8n may later receive event notifications and drive delivery workflows after human sign-off.

New constants: `INTEGRATION_PROVIDERS`, `INTEGRATION_DIRECTIONS`, `INTEGRATION_EVENT_TYPES` — all added to `core/schemas/constants.py`.

---

## Phase 4E — Credential Safety schemas

**Module:** `core/schemas/credential_safety.py`

**Exported from `core/schemas/__init__.py` with Safety prefix to avoid conflict with Phase 2A schemas.**

| Class (in module) | Exported as | Purpose |
|---|---|---|
| `CredentialReference` | `CredentialSafetyReference` | Metadata ref to a credential found in scan |
| `CredentialPolicy` | `CredentialSafetyPolicy` | Project-level credential safety policy |
| `CredentialSafetyReport` | `CredentialSafetyReport` | Full inspection report |
| `TestAccountProfile` | `TestAccountProfile` | Test account safety classification |
| `StorageStatePolicy` | `StorageStatePolicy` | storageState handling policy |
| `AuthExecutionApproval` | `AuthExecutionApproval` | Blocked draft approval for future auth execution |
| `SandboxProfileClassification` | `SandboxProfileClassification` | Sandbox/test-account profile classification |

### Safety defaults (hardcoded, cannot be bypassed)

| Field | Always | Guard |
|---|---|---|
| `CredentialPolicy.allow_real_credentials` | `False` | `__post_init__` + `from_dict` |
| `CredentialPolicy.allow_personal_accounts` | `False` | `__post_init__` + `from_dict` |
| `CredentialPolicy.allow_production_accounts` | `False` | `__post_init__` + `from_dict` |
| `CredentialPolicy.allow_repo_storage` | `False` | `__post_init__` + `from_dict` |
| `CredentialPolicy.allow_logging` | `False` | `__post_init__` + `from_dict` |
| `CredentialPolicy.allow_client_visible_credentials` | `False` | `__post_init__` + `from_dict` |
| `CredentialSafetyReport.safe_for_auth_execution` | `False` | `__post_init__` + `from_dict` |
| `CredentialSafetyReport.safe_for_client_visibility` | `False` | `__post_init__` + `from_dict` |
| `StorageStatePolicy.approved_for_commit` | `False` | `__post_init__` + `from_dict` |
| `AuthExecutionApproval.approved` | `False` | `__post_init__` |
| `AuthExecutionApproval.real_credentials_allowed` | `False` | `__post_init__` |
| `AuthExecutionApproval.personal_account_allowed` | `False` | `__post_init__` |
| `SandboxProfileClassification.blocked_in_current_phase` | `True` | `__post_init__` |

---

## Phase 4F — Auth Execution schemas

**Module:** `core/schemas/auth_execution.py`

| Class | Exported as | Purpose |
|---|---|---|
| `AuthCredentialProfile` | `AuthCredentialProfile` | Credential profile metadata (no raw values) |
| `AuthExecutionCommand` | `AuthExecutionCommand` | Single auth command record |
| `AuthExecutionReport` | `AuthExecutionReport` | Full demo auth execution report |
| `AuthSessionArtifact` | `AuthSessionArtifact` | Reference to a session artifact (storageState, etc.) |

### Safety defaults (hardcoded — cannot be bypassed via constructor or from_dict)

| Field | Value | Enforced by |
|---|---|---|
| `AuthExecutionReport.real_credentials_used` | `False` | `__post_init__` + `from_dict` |
| `AuthExecutionReport.personal_account_used` | `False` | `__post_init__` + `from_dict` |
| `AuthExecutionReport.production_account_used` | `False` | `__post_init__` + `from_dict` |
| `AuthExecutionReport.safe_to_deliver` | `False` | `__post_init__` + `from_dict` |
| `AuthExecutionReport.approved_for_client_delivery` | `False` | `__post_init__` + `from_dict` |
| `AuthCredentialProfile.personal_account` | `False` | `__post_init__` + `from_dict` |
| `AuthCredentialProfile.production_account` | `False` | `__post_init__` + `from_dict` |
| `AuthCredentialProfile.safe_to_store_in_repo` | `False` | `__post_init__` + `from_dict` |
| `AuthSessionArtifact.approved_for_commit` | `False` | `__post_init__` |
| `AuthSessionArtifact.approved_for_client_view` | `False` | `__post_init__` |
| `AuthSessionArtifact.client_visible` | `False` | `__post_init__` |

NOT forced (reflect real execution state when approved demo auth runs):
`auth_execution_performed`, `browser_execution_performed`, `storage_state_created`, `credentials_used`

---

## Phase 4G — Scenario Execution Matrix schemas

**Module:** `core/schemas/scenario_execution_matrix.py`

| Class | Exported as | Purpose |
|---|---|---|
| `ScenarioExecutionLane` | `ScenarioExecutionLane` | Single execution lane definition (name, status, allowed_now) |
| `ScenarioPermissionRule` | `ScenarioPermissionRule` | Permission rule for an execution lane |
| `ScenarioTargetProfile` | `ScenarioTargetProfile` | Target URL/scenario profile with routing metadata |
| `ScenarioExecutionDecision` | `ScenarioExecutionDecision` | Routing decision for a given URL + scenario type |
| `ScenarioExecutionMatrixReport` | `ScenarioExecutionMatrixReport` | Full matrix report (lanes, rules, profiles, decisions, counts) |

### Dedicated test account planning schemas

| Class | Exported as | Purpose |
|---|---|---|
| `DedicatedTestAccountRequirement` | `DedicatedTestAccountRequirement` | Requirement item for a dedicated test account |
| `CredentialProvisioningRoute` | `CredentialProvisioningRoute` | Provisioning route option for test credentials |
| `DedicatedTestAccountPlan` | `DedicatedTestAccountPlan` | Full planning-only test account plan |

### Safety defaults (hardcoded — cannot be bypassed via constructor or from_dict)

| Field | Value | Enforced by |
|---|---|---|
| `DedicatedTestAccountRequirement.production_account_allowed` | `False` | `__post_init__` + `from_dict` |
| `DedicatedTestAccountRequirement.personal_account_allowed` | `False` | `__post_init__` + `from_dict` |
| `CredentialProvisioningRoute.repo_storage_allowed` | `False` | `__post_init__` |
| `CredentialProvisioningRoute.logging_allowed` | `False` | `__post_init__` |
| `CredentialProvisioningRoute.client_visible_allowed` | `False` | `__post_init__` |
| `DedicatedTestAccountPlan.safe_for_execution_now` | `False` | `__post_init__` + `from_dict` |

NOT forced (reflect real routing state):
`ScenarioExecutionLane.allowed_now`, `ScenarioExecutionDecision.allowed_now` — set by routing logic, not hardcoded

---

## Phase 5AB — Runtime Secret Routing + Dedicated Test-Account Auth schemas

**Module:** `core/schemas/runtime_secret_routing.py`

| Class | Exported as | Purpose |
|---|---|---|
| `RuntimeSecretReference` | `RuntimeSecretReference` | Env var name reference for a runtime secret — never stores the value |
| `TestAccountIntakeRequest` | `TestAccountIntakeRequest` | Dedicated test-account intake request with env var names only |
| `TestAccountValidationResult` | `TestAccountValidationResult` | Result of validating an intake request |
| `DedicatedAuthExecutionCommand` | `DedicatedAuthExecutionCommand` | Record of a single Playwright command run during auth execution |
| `DedicatedAuthSessionArtifact` | `DedicatedAuthSessionArtifact` | Reference to a session artifact (storageState etc.) — always internal-only |
| `DedicatedAuthExecutionReport` | `DedicatedAuthExecutionReport` | Full report for a dedicated test-account auth execution run |

### Safety defaults (hardcoded — cannot be bypassed via constructor or from_dict)

| Field | Value | Enforced by |
|---|---|---|
| `RuntimeSecretReference.raw_value_present` | `False` | `__post_init__` + `from_dict` |
| `RuntimeSecretReference.value_materialized` | `False` | `__post_init__` + `from_dict` |
| `RuntimeSecretReference.safe_to_persist` | `False` | `__post_init__` + `from_dict` |
| `RuntimeSecretReference.safe_to_log` | `False` | `__post_init__` + `from_dict` |
| `RuntimeSecretReference.safe_for_client_visibility` | `False` | `__post_init__` + `from_dict` |
| `RuntimeSecretReference.requires_redaction` | `True` | `__post_init__` + `from_dict` |
| `TestAccountValidationResult.approved_for_execution_now` | `False` | `__post_init__` + `from_dict` |
| `DedicatedAuthSessionArtifact.internal_only` | `True` | `__post_init__` + `from_dict` |
| `DedicatedAuthSessionArtifact.client_visible` | `False` | `__post_init__` + `from_dict` |
| `DedicatedAuthSessionArtifact.requires_redaction` | `True` | `__post_init__` + `from_dict` |
| `DedicatedAuthSessionArtifact.approved_for_commit` | `False` | `__post_init__` + `from_dict` |
| `DedicatedAuthSessionArtifact.approved_for_client_view` | `False` | `__post_init__` + `from_dict` |
| `DedicatedAuthExecutionReport.raw_credentials_logged` | `False` | `__post_init__` + `from_dict` |
| `DedicatedAuthExecutionReport.raw_credentials_serialized` | `False` | `__post_init__` + `from_dict` |
| `DedicatedAuthExecutionReport.personal_account_used` | `False` | `__post_init__` + `from_dict` |
| `DedicatedAuthExecutionReport.production_account_used` | `False` | `__post_init__` + `from_dict` |
| `DedicatedAuthExecutionReport.safe_to_deliver` | `False` | `__post_init__` + `from_dict` |
| `DedicatedAuthExecutionReport.approved_for_client_delivery` | `False` | `__post_init__` + `from_dict` |

### Phase 5E — API Auth Smoke (`core/schemas/api_auth.py`)

| Class | Exported as | Purpose |
|---|---|---|
| `APIAuthTarget` | `APIAuthTarget` | Profile for a safe API auth target (URL, endpoints, category) |
| `APIAuthCommand` | `APIAuthCommand` | Record of a single API call — URL + method only, no credential body |
| `APIAuthSessionArtifact` | `APIAuthSessionArtifact` | Reference to a session artifact — always internal-only |
| `APIAuthExecutionReport` | `APIAuthExecutionReport` | Full report for a Phase 5E API auth execution run |

**Safety defaults (hardcoded):**

| Field | Value | Enforced by |
|---|---|---|
| `APIAuthSessionArtifact.internal_only` | `True` | `__post_init__` + `from_dict` |
| `APIAuthSessionArtifact.approved_for_commit` | `False` | `__post_init__` + `from_dict` |
| `APIAuthExecutionReport.raw_credentials_logged` | `False` | `__post_init__` + `from_dict` |
| `APIAuthExecutionReport.raw_credentials_serialized` | `False` | `__post_init__` + `from_dict` |
| `APIAuthExecutionReport.token_logged` | `False` | `__post_init__` + `from_dict` |
| `APIAuthExecutionReport.token_serialized` | `False` | `__post_init__` + `from_dict` |
| `APIAuthExecutionReport.safe_to_deliver` | `False` | `__post_init__` + `from_dict` |
| `APIAuthExecutionReport.approved_for_client_delivery` | `False` | `__post_init__` + `from_dict` |
| `APIAuthExecutionReport.personal_account_used` | `False` | `__post_init__` + `from_dict` |
| `APIAuthExecutionReport.production_account_used` | `False` | `__post_init__` + `from_dict` |

---

### Phase 5G — Google/OAuth Test Account Capability (`core/schemas/google_auth.py`)

| Class | Export | Description |
|---|---|---|
| `GoogleTestAccountProfile` | `GoogleTestAccountProfile` | Identification of a dedicated test account (labels only, never raw email values as credentials) |
| `GoogleAuthModePolicy` | `GoogleAuthModePolicy` | Policy decision for a single auth mode (allowed/blocked + reasons) |
| `GoogleStorageStatePolicy` | `GoogleStorageStatePolicy` | Policy for handling Google storageState files (path/metadata only) |
| `GoogleAuthCapability` | `GoogleAuthCapability` | Top-level capability plan covering all 8 supported modes |
| `GoogleAuthExecutionDecision` | `GoogleAuthExecutionDecision` | Per-request decision: can this specific request run now? |
| `GoogleAuthEvidenceReport` | `GoogleAuthEvidenceReport` | Evidence report for executed (or planned-only) Google auth flow |

**Constants:**
- `GOOGLE_AUTH_MODES` — all 8 supported mode names
- `GOOGLE_AUTH_MODES_EXECUTABLE_5G` — modes with real execution support in Phase 5G+: `manual_storage_state_capture`, `storage_state_reuse`, `cdp_attach` (Phase 5H), `dedicated_profile_context` (Phase 5H)
- `GOOGLE_AUTH_MODES_PLANNING_ONLY_5G` — modes deferred to later phases: `google_api_oauth_token_future`, `google_service_account_future`, `totp_test_account_future`, `mock_oauth_provider_future`
- `GOOGLE_TARGET_KINDS` — target categorization: `google_account_ui`, `sign_in_with_google_oauth`, `google_api_endpoint`, `mock_oauth_endpoint`

**Hardcoded safety defaults (set in `__post_init__` AND `from_dict`):**

| Field | Hardcoded value | Enforced in |
|---|---|---|
| `GoogleAuthCapability.raw_secrets_allowed` | `False` | `__post_init__` + `from_dict` |
| `GoogleAuthCapability.storage_state_content_read` | `False` | `__post_init__` + `from_dict` |
| `GoogleAuthCapability.browser_profile_content_read` | `False` | `__post_init__` + `from_dict` |
| `GoogleAuthCapability.captcha_bypass_allowed` | `False` | `__post_init__` + `from_dict` |
| `GoogleAuthCapability.anti_bot_bypass_allowed` | `False` | `__post_init__` + `from_dict` |
| `GoogleAuthCapability.client_delivery_allowed` | `False` | `__post_init__` + `from_dict` |
| `GoogleAuthCapability.personal_account_always_blocked` | `True` | `__post_init__` + `from_dict` |
| `GoogleAuthCapability.production_account_always_blocked` | `True` | `__post_init__` + `from_dict` |
| `GoogleAuthCapability.stealth_live_login_as_core_path` | `False` | `__post_init__` + `from_dict` |
| `GoogleAuthExecutionDecision.*` | same set as Capability | `__post_init__` + `from_dict` |
| `GoogleStorageStatePolicy.internal_only` | `True` | `__post_init__` + `from_dict` |
| `GoogleStorageStatePolicy.approved_for_commit` | `False` | `__post_init__` + `from_dict` |
| `GoogleStorageStatePolicy.client_visible` | `False` | `__post_init__` + `from_dict` |
| `GoogleStorageStatePolicy.storage_state_content_read` | `False` | `__post_init__` + `from_dict` |
| `GoogleAuthEvidenceReport.raw_credentials_logged` | `False` | `__post_init__` + `from_dict` |
| `GoogleAuthEvidenceReport.cookies_logged` | `False` | `__post_init__` + `from_dict` |
| `GoogleAuthEvidenceReport.tokens_logged` | `False` | `__post_init__` + `from_dict` |
| `GoogleAuthEvidenceReport.storage_state_content_read` | `False` | `__post_init__` + `from_dict` |
| `GoogleAuthEvidenceReport.browser_profile_content_read` | `False` | `__post_init__` + `from_dict` |
| `GoogleAuthEvidenceReport.captcha_bypass_attempted` | `False` | `__post_init__` + `from_dict` |
| `GoogleAuthEvidenceReport.anti_bot_bypass_attempted` | `False` | `__post_init__` + `from_dict` |
| `GoogleAuthEvidenceReport.personal_account_used` | `False` | `__post_init__` + `from_dict` |
| `GoogleAuthEvidenceReport.production_account_used` | `False` | `__post_init__` + `from_dict` |
| `GoogleAuthEvidenceReport.safe_to_deliver` | `False` | `__post_init__` + `from_dict` |
| `GoogleAuthEvidenceReport.approved_for_client_delivery` | `False` | `__post_init__` + `from_dict` |
| `GoogleAuthEvidenceReport.client_visible` | `False` | `__post_init__` + `from_dict` |
| `GoogleAuthEvidenceReport.internal_only` | `True` | `__post_init__` + `from_dict` |
| `GoogleAuthEvidenceReport.human_review_required` | `True` | `__post_init__` + `from_dict` |

---

### Phase 5F — QA Evidence Report (`core/schemas/qa_report.py`)

| Class | Export | Description |
|---|---|---|
| `QAEvidenceItem` | `QAEvidenceItem` | Single evidence item from one execution lane of one source project |
| `QAEvidenceSource` | `QAEvidenceSource` | Evidence collected from a single source project |
| `QACoverageSummary` | `QACoverageSummary` | Coverage across all aggregated source projects |
| `QASecretScanResult` | `QASecretScanResult` | Result of scanning generated report for raw secrets/tokens |
| `QAEvidenceReport` | `QAEvidenceReport` | Consolidated QA Evidence Report — internal-only, human review required |

**Hardcoded safety defaults in `QAEvidenceReport` (set in `__post_init__` AND `from_dict`):**

| Field | Hardcoded value | Enforced in |
|---|---|---|
| `QAEvidenceReport.execution_performed` | `False` | `__post_init__` + `from_dict` |
| `QAEvidenceReport.network_calls_performed` | `False` | `__post_init__` + `from_dict` |
| `QAEvidenceReport.raw_credentials_in_report` | `False` | `__post_init__` + `from_dict` |
| `QAEvidenceReport.raw_tokens_in_report` | `False` | `__post_init__` + `from_dict` |
| `QAEvidenceReport.storage_state_content_read` | `False` | `__post_init__` + `from_dict` |
| `QAEvidenceReport.safe_to_deliver` | `False` | `__post_init__` + `from_dict` |
| `QAEvidenceReport.approved_for_client_delivery` | `False` | `__post_init__` + `from_dict` |
| `QAEvidenceReport.client_ready` | `False` | `__post_init__` + `from_dict` |
| `QAEvidenceReport.human_review_required` | `True` | `__post_init__` + `from_dict` |

---

### Phase 5H — Task Source Integration (`core/schemas/task_source.py`)

| Class | Export | Description |
|---|---|---|
| `TaskSourceToken` | `TaskSourceToken` | Reference to an API token (env var name only — never a raw value) |
| `TaskSourceIssue` | `TaskSourceIssue` | Parsed issue from the task source (id, title, description, status, labels, acceptance criteria) |
| `TaskSourceFetchPolicy` | `TaskSourceFetchPolicy` | Hardcoded read-only policy — no writeback, no comments, no webhooks |
| `TaskSourceScenario` | `TaskSourceScenario` | A derived test scenario from a task source issue |
| `TaskSourceFetchReport` | `TaskSourceFetchReport` | Fetch result report — issues fetched, scenarios derived, blockers, artifacts written |

**Constants:**
- `TASK_SOURCE_PROVIDERS` — all recognized providers: `linear`, `jira`, `clickup`, `github_issues`
- `TASK_SOURCE_PROVIDERS_EXECUTABLE_5H` — currently executable: `linear`
- `TASK_SOURCE_PROVIDERS_PLANNING_ONLY_5H` — planning-only: `jira`, `clickup`, `github_issues`

**Hardcoded safety defaults in `TaskSourceFetchPolicy` (set in `__post_init__` AND `from_dict`):**

| Field | Hardcoded value | Description |
|---|---|---|
| `writeback_allowed` | `False` | No issue status changes |
| `status_change_allowed` | `False` | No status updates |
| `comment_allowed` | `False` | No comments posted |
| `webhook_allowed` | `False` | No webhooks triggered |
| `raw_token_logged` | `False` | Token value never logged |
| `client_delivery_allowed` | `False` | Internal use only |

**Hardcoded safety defaults in `TaskSourceFetchReport`:**

| Field | Hardcoded value | Description |
|---|---|---|
| `writeback_performed` | `False` | Confirmed no writeback occurred |
| `raw_token_in_output` | `False` | Confirmed no token in artifacts |
| `client_delivery_allowed` | `False` | Requires human review before delivery |

---

---

### Phase 5I — Mobile Viewport (`core/schemas/mobile_viewport.py`)

| Class | Export | Description |
|---|---|---|
| `MobileViewportProfile` | `MobileViewportProfile` | Device profile with viewport dimensions and User-Agent |
| `MobileViewportExecutionCommand` | `MobileViewportExecutionCommand` | Command issued to the mobile viewport runner |
| `MobileViewportExecutionReport` | `MobileViewportExecutionReport` | Execution result — device, status, blockers, notes |

**Constants:**
- `MOBILE_VIEWPORT_DEVICES` — `iPhone 14`, `iPhone 14 Pro`, `iPhone 13`, `Pixel 7`, `Pixel 5`, `Galaxy S22`, `Galaxy S9+`, `iPad Pro`, `iPad Mini`, `Nexus 10`
- `MOBILE_VIEWPORT_MODES` — `list`, `viewport_smoke`
- `MOBILE_ECOMMERCE_READONLY_PROFILES` — `amazon_mobile_readonly`, `alza_mobile_readonly`

**Hardcoded safety defaults in `MobileViewportExecutionReport` (set in `__post_init__` AND `from_dict`):**

| Field | Hardcoded value | Enforced in |
|---|---|---|
| `credentials_used` | `False` | `__post_init__` + `from_dict` |
| `auth_performed` | `False` | `__post_init__` + `from_dict` |
| `safe_to_deliver` | `False` | `__post_init__` + `from_dict` |
| `approved_for_client_delivery` | `False` | `__post_init__` + `from_dict` |
| `human_review_required` | `True` | `__post_init__` + `from_dict` |

---

### Phase 5I — Visual Regression (`core/schemas/visual_regression.py`)

| Class | Export | Description |
|---|---|---|
| `VisualBaselineRecord` | `VisualBaselineRecord` | Metadata for a captured baseline screenshot |
| `VisualDiffResult` | `VisualDiffResult` | Result of comparing a screenshot against its baseline |
| `VisualRegressionReport` | `VisualRegressionReport` | Full visual regression run report — mode, stats, diffs, blockers |

**Constants:**
- `VISUAL_REGRESSION_MODES` — `capture`, `compare`, `update`
- `VISUAL_DIFF_VERDICTS` — `pass`, `fail`, `new`, `error`

**Hardcoded safety defaults in `VisualRegressionReport` (set in `__post_init__` AND `from_dict`):**

| Field | Hardcoded value | Enforced in |
|---|---|---|
| `credentials_used` | `False` | `__post_init__` + `from_dict` |
| `auth_performed` | `False` | `__post_init__` + `from_dict` |
| `safe_to_deliver` | `False` | `__post_init__` + `from_dict` |
| `approved_for_client_delivery` | `False` | `__post_init__` + `from_dict` |
| `human_review_required` | `True` | `__post_init__` + `from_dict` |
| `baselines_committed` | `False` | `__post_init__` + `from_dict` |

---

### Phase 5I — GitHub OAuth (`core/schemas/github_auth.py`)

| Class | Export | Description |
|---|---|---|
| `GitHubTestAccountProfile` | `GitHubTestAccountProfile` | Dedicated test account profile — label, target kind, not personal/production |
| `GitHubAuthModePolicy` | `GitHubAuthModePolicy` | Per-mode allow/block decision with blockers and notes |
| `GitHubStorageStatePolicy` | `GitHubStorageStatePolicy` | StorageState path + metadata policy (content never read) |
| `GitHubAuthCapability` | `GitHubAuthCapability` | Full capability plan — modes, account profile, blockers |
| `GitHubAuthExecutionDecision` | `GitHubAuthExecutionDecision` | Per-request allow/block decision |
| `GitHubAuthEvidenceReport` | `GitHubAuthEvidenceReport` | Execution evidence report — status, screenshot, blockers |

**Constants:**
- `GITHUB_AUTH_MODES` — all recognized modes
- `GITHUB_AUTH_MODES_EXECUTABLE_5I` — `manual_storage_state_capture`, `storage_state_reuse`
- `GITHUB_AUTH_MODES_PLANNING_ONLY_5I` — `cdp_attach`, `dedicated_profile_context`, `github_api_token_future`, `github_app_future`
- `GITHUB_TARGET_KINDS` — `github_login_ui`, `github_protected_resource`, `github_api_endpoint`

**Hardcoded safety defaults in `GitHubAuthCapability` (set in `__post_init__` AND `from_dict`):**

| Field | Hardcoded value | Description |
|---|---|---|
| `personal_account_always_blocked` | `True` | Personal GitHub accounts: always blocked |
| `production_account_always_blocked` | `True` | Production org accounts: always blocked |
| `captcha_bypass_allowed` | `False` | CAPTCHA bypass: always blocked |
| `raw_secrets_allowed` | `False` | Raw secrets in CLI/artifacts: always blocked |
| `storage_state_content_read` | `False` | storageState content: never read by Python |
| `client_delivery_allowed` | `False` | Requires human review before delivery |

**Hardcoded safety defaults in `GitHubAuthEvidenceReport`:**

| Field | Hardcoded value | Description |
|---|---|---|
| `cookies_logged` | `False` | Cookies never logged |
| `tokens_logged` | `False` | Tokens never logged |
| `storage_state_content_read` | `False` | storageState content never read |
| `captcha_bypass_attempted` | `False` | CAPTCHA bypass never attempted |
| `personal_account_used` | `False` | Personal accounts never used |
| `production_account_used` | `False` | Production accounts never used |
| `safe_to_deliver` | `False` | Always requires human review |
| `human_review_required` | `True` | Always requires human review |

---

---

### Phase 5J — E2E Pipeline (`core/schemas/pipeline.py`)

| Class | Export | Description |
|---|---|---|
| `PipelineModuleConfig` | `PipelineModuleConfig` | Per-module configuration for all pipeline modules |
| `PipelineModuleResult` | `PipelineModuleResult` | Result of running one module — status, exit code, stdout excerpt, blockers |
| `PipelineRunPlan` | `PipelineRunPlan` | Execution plan — enabled modules, execution order, planned commands, blockers |
| `PipelineRunReport` | `PipelineRunReport` | Full pipeline run report — module results, counters, overall status |

**Constants:**
- `PIPELINE_MODULES` — fixed ordered tuple of 9 module names
- `PIPELINE_MODULE_STATUSES` — `pending`, `complete`, `failed`, `blocked`, `skipped`
- `PIPELINE_OVERALL_STATUSES` — `planned`, `running`, `complete`, `partial`, `failed`, `blocked`
- `PIPELINE_MODULE_CLI_TOOLS` — maps module name → CLI tool path
- `PIPELINE_MODULE_ARTIFACT_DIRS` — maps module name → artifact directory path

**Hardcoded safety defaults in `PipelineRunPlan` and `PipelineRunReport` (set in `__post_init__` AND `from_dict`):**

| Field | Hardcoded value | Enforced in |
|---|---|---|
| `raw_secrets_allowed` | `False` | `__post_init__` + `from_dict` |
| `production_write_allowed` | `False` | `__post_init__` + `from_dict` |
| `client_delivery_allowed` | `False` | `__post_init__` + `from_dict` |
| `safe_to_deliver` | `False` | `__post_init__` + `from_dict` |
| `human_review_required` | `True` | `__post_init__` + `from_dict` |

---

### Phase 5J — DB Smoke (`core/schemas/db_smoke.py`)

| Class | Export | Description |
|---|---|---|
| `DBSmokeTarget` | `DBSmokeTarget` | Target DB — provider, env var name, table, operation, row limit |
| `DBSmokeQueryResult` | `DBSmokeQueryResult` | Result of one query — rows, columns, duration, error |
| `DBSmokeReport` | `DBSmokeReport` | Full DB smoke report — target, query results, status, blockers |

**Constants:**
- `DB_PROVIDERS` — `postgresql`, `mysql`, `mongodb`
- `DB_ALLOWED_SQL_PREFIXES` — `SELECT`, `SHOW`, `DESCRIBE`, `EXPLAIN`
- `DB_BLOCKED_SQL_KEYWORDS` — 16 destructive keywords
- `MONGODB_ALLOWED_OPERATIONS` — 9 read-only operations
- `MONGODB_BLOCKED_OPERATIONS` — 14 destructive operations
- `DB_SMOKE_STATUSES` — `pending`, `complete`, `failed`, `blocked`, `skipped`
- `DEFAULT_ROW_LIMIT` — `10`
- `DEFAULT_TIMEOUT_SECONDS` — `30`
- `MAX_ROW_LIMIT` — `100`

**Hardcoded safety defaults in `DBSmokeReport` (set in `__post_init__` AND `from_dict`):**

| Field | Hardcoded value | Enforced in |
|---|---|---|
| `raw_secrets_allowed` | `False` | `__post_init__` + `from_dict` |
| `production_write_allowed` | `False` | `__post_init__` + `from_dict` |
| `destructive_db_actions_allowed` | `False` | `__post_init__` + `from_dict` |
| `client_delivery_allowed` | `False` | `__post_init__` + `from_dict` |
| `human_review_required` | `True` | `__post_init__` + `from_dict` |
| `connection_string_logged` | `False` | `__post_init__` + `from_dict` |

---

### Phase 5K — AI Intelligence Core

#### `core/schemas/intake.py`

| Class | Schema class | Purpose |
|---|---|---|
| `IntakeClassification` | `IntakeClassification` | Single classification result — type, confidence, risk, modules |
| `IntakeReport` | `IntakeReport` | Full intake analysis — classification + safety flags |

**Constants:**
- `INTAKE_CLASSIFICATIONS` — 9 values: `auth_testing`, `api_testing`, `mobile_testing`, `database_testing`, `visual_testing`, `performance_testing`, `security_testing`, `functional_testing`, `unknown`
- `INTAKE_RISK_LEVELS` — `low`, `medium`, `high`, `critical`
- `INTAKE_MODES` — `heuristic`, `llm_enhanced`

**Hardcoded safety defaults in `IntakeReport` (set in `__post_init__` AND `from_dict`):**

| Field | Hardcoded value | Enforced in |
|---|---|---|
| `raw_input_stored` | `False` | `__post_init__` + `from_dict` |
| `credentials_in_output` | `False` | `__post_init__` + `from_dict` |
| `safe_to_deliver` | `False` | `__post_init__` + `from_dict` |
| `human_review_required` | `True` | `__post_init__` + `from_dict` |

#### `core/schemas/test_oracle.py`

| Class | Schema class | Purpose |
|---|---|---|
| `TestScenario` | `TestScenario` | One test scenario — name, area, priority, risk score, tags |
| `TestOracleReport` | `TestOracleReport` | Full oracle report — scenarios, deferred, source classification |

**Constants:**
- `TEST_COVERAGE_AREAS` — coverage area identifiers
- `TEST_SCENARIO_PRIORITIES` — `1` (critical) through `4` (low)
- `TEST_ORACLE_MODES` — `heuristic`, `llm_enhanced`

**Hardcoded safety defaults in `TestOracleReport`:**

| Field | Hardcoded value | Enforced in |
|---|---|---|
| `raw_input_stored` | `False` | `__post_init__` + `from_dict` |
| `executable_without_approval` | `False` | `__post_init__` + `from_dict` |
| `safe_to_deliver` | `False` | `__post_init__` + `from_dict` |
| `human_review_required` | `True` | `__post_init__` + `from_dict` |

#### `core/schemas/evidence_intelligence.py`

| Class | Schema class | Purpose |
|---|---|---|
| `EvidenceGap` | `EvidenceGap` | One coverage gap — area, severity, description, recommendation |
| `EvidenceCoverageItem` | `EvidenceCoverageItem` | Coverage status per area — present, artifact count |
| `EvidenceIntelligenceReport` | `EvidenceIntelligenceReport` | Full gap analysis — score, items, gaps, recommendations |

**Constants:**
- `EVIDENCE_GAP_SEVERITIES` — `low`, `medium`, `high`, `critical`
- `EVIDENCE_COVERAGE_AREAS` — 12 areas matching artifact directories
- `EVIDENCE_ARTIFACT_DIR_MAP` — area → artifact directory name mapping

**Hardcoded safety defaults in `EvidenceIntelligenceReport`:**

| Field | Hardcoded value | Enforced in |
|---|---|---|
| `network_calls_made` | `False` | `__post_init__` + `from_dict` |
| `execution_performed` | `False` | `__post_init__` + `from_dict` |
| `safe_to_deliver` | `False` | `__post_init__` + `from_dict` |
| `human_review_required` | `True` | `__post_init__` + `from_dict` |

---

### Phase 5M — API Contract + CI/CD

#### `core/schemas/api_contract.py`

| Class | Schema class | Purpose |
|---|---|---|
| `APIParameter` | `APIParameter` | Single endpoint parameter — name, location, type |
| `APIEndpoint` | `APIEndpoint` | Endpoint with method, path, and safety classification |
| `AuthRequirement` | `AuthRequirement` | Auth scheme detected from the spec |
| `APIContractReport` | `APIContractReport` | Full contract analysis — endpoints, auth, counts |
| `GeneratedTestFile` | `GeneratedTestFile` | Metadata for a single generated test file |
| `GeneratedTestsReport` | `GeneratedTestsReport` | Report of all generated test artifacts |
| `CICDConfig` | `CICDConfig` | CI/CD workflow content + platform metadata |
| `CICDManifest` | `CICDManifest` | Artifact list for the generated CI/CD config |

**Constants:**
- `ENDPOINT_SAFETY_LEVELS` — `safe_readonly`, `requires_approval`, `blocked_by_default`
- `SAFE_METHODS` — `GET`, `HEAD`, `OPTIONS`
- `RISKY_PATH_TERMS` — path terms that escalate classification
- `CICD_PLATFORMS` — `github_actions`, `gitlab_ci`, `azure_devops`
- `SOURCE_FORMATS` — `openapi_json`, `openapi_yaml`, `postman_collection`, `unknown`

**Hardcoded safety defaults in `APIContractReport`:**

| Field | Hardcoded value | Enforced in |
|---|---|---|
| `raw_secrets_allowed` | `False` | `__post_init__` + `from_dict` |
| `destructive_api_calls_allowed` | `False` | `__post_init__` + `from_dict` |
| `production_write_allowed` | `False` | `__post_init__` + `from_dict` |
| `human_review_required` | `True` | `__post_init__` + `from_dict` |
| `client_delivery_allowed` | `False` | `__post_init__` + `from_dict` |

**Hardcoded safety defaults in `GeneratedTestsReport`:**

| Field | Hardcoded value | Enforced in |
|---|---|---|
| `executable_without_approval` | `False` | `__post_init__` + `from_dict` |
| `raw_secrets_allowed` | `False` | `__post_init__` + `from_dict` |
| `human_review_required` | `True` | `__post_init__` + `from_dict` |
| `client_delivery_allowed` | `False` | `__post_init__` + `from_dict` |

**Hardcoded safety defaults in `CICDConfig` / `CICDManifest`:**

| Field | Hardcoded value | Enforced in |
|---|---|---|
| `auto_pr_creation_allowed` | `False` | `__post_init__` + `from_dict` |
| `client_repo_writeback_allowed` | `False` | `__post_init__` + `from_dict` |
| `production_deploy_allowed` | `False` | `__post_init__` + `from_dict` |
| `human_review_required` | `True` | `__post_init__` + `from_dict` |

---

---

## Phase 5N — Accessibility + Performance + Passive Security schemas

### `core/schemas/accessibility.py`

| Class | Purpose |
|---|---|
| `AccessibilityViolation` | Single WCAG violation result (template, populated after execution) |
| `AccessibilityReport` | Accessibility smoke plan/result — planning or executed |

**Safety flags (hardcoded):** `read_only=True`, `active_scan_allowed=False`, `exploit_attempts_allowed=False`, `human_review_required=True`

**Status tracking:** `status` (`planning_only`|`executed`|`partial`), `checks_planned`, `checks_executed`, `checks_skipped`, `checks_blocked`

---

### `core/schemas/performance_smoke.py`

| Class | Purpose |
|---|---|
| `PerformanceThreshold` | Single Core Web Vitals threshold (metric, threshold_ms, guidance) |
| `PerformanceSmokeReport` | Performance smoke plan/result — planning or executed |

**Safety flags:** `read_only=True`, `load_testing_allowed=False`, `active_scan_allowed=False`, `production_write_allowed=False`, `human_review_required=True`

**Default thresholds:** LCP < 2500ms | FCP < 1800ms | TTFB < 800ms | TBT < 300ms | CLS < 100ms

---

### `core/schemas/passive_security.py`

| Class | Purpose |
|---|---|
| `SecurityHeaderCheck` | Single OWASP header check result (present/missing/not_checked) |
| `PassiveSecurityReport` | Passive security smoke plan/result — passive HEAD only |

**Safety flags:** `read_only=True`, `active_scan_allowed=False`, `exploit_attempts_allowed=False`, `auth_bypass_allowed=False`, `destructive_actions_allowed=False`, `human_review_required=True`

**OWASP headers:** HSTS, CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy

---

## Phase 5O — Flaky Test Analyzer + Self-Healing schemas

### `core/schemas/flaky_test_analysis.py`

| Class | Purpose |
|---|---|
| `FlakinessRisk` | Single detected flakiness risk (category, severity, file, line, recommendation) |
| `FlakyTestAnalysisReport` | Static flakiness analysis report — read-only, no code changes |
| `SelectorFinding` | Stability classification for a single selector (strong/medium/weak) |
| `SelectorStabilityReport` | Selector stability analysis report — stability score 0–100 |
| `SelfHealingProposal` | Single proposed selector replacement — not yet applied |
| `SelfHealingReport` | Self-healing proposal report — proposals only by default |

**Safety flags (all hardcoded in `__post_init__` + injection-proof via `from_dict`):**
- `FlakyTestAnalysisReport`: `read_only=True`, `auto_apply_changes=False`, `code_modification_allowed=False`, `human_review_required=True`
- `SelectorStabilityReport`: `read_only=True`, `auto_fix_selectors=False`, `human_review_required=True`
- `SelfHealingReport`: `read_only=True`, `auto_apply_changes=False`, `code_modification_allowed=False`, `production_write_allowed=False`, `human_review_required=True`

**Risk categories:** `hard_wait` | `fragile_selector` | `race_prone` | `non_web_first_assertion` | `network_dependent` | `dynamic_selector` | `missing_evidence_hook`

**Selector stability levels:** `strong` | `medium` | `weak` | `unknown`

**Healing status values:** `analysis_only` | `proposal_generated` | `patch_applied` | `partial`

---

## Phase 6 — MCP Server

No new schemas. Phase 6 is a thin adapter layer that reuses existing core schemas.
Tool responses are plain Python `dict` objects — no separate dataclasses needed.

Safety invariants enforced in `integrations/mcp/tool_handlers.py`:
- `human_review_required=True` hardcoded in every response
- `network_by_default=False`, `browser_by_default=False`, `auto_apply_changes=False`
- `approved_for_client_delivery=False` in delivery tool
- Blocked params raise `ValueError` before any handler logic runs

---

## Phase 6.1 — One-Command Client Audit

New schemas in `core/schemas/client_audit.py`:

| Class | Description |
|---|---|
| `ClientAuditMode` | Enum: `safe_audit`, `api_only`, `frontend_readonly`, `delivery_only` |
| `ClientAuditInputs` | All inputs; safety invariants enforced in `__post_init__` |
| `SkippedModule` | Name + reason for a skipped module |
| `ClientAuditPlan` | Preflight plan: enabled/skipped/blocked/approval-required modules |
| `ModuleResult` | Single module run outcome: name, status, artifacts, note |
| `ClientAuditResult` | Full run result; safety invariants enforced in `__post_init__` |

**Safety fields enforced in `__post_init__` (both `ClientAuditInputs` and `ClientAuditResult`):**
- `raw_secrets_allowed=False`
- `destructive_actions_allowed=False`
- `production_write_allowed=False`
- `auto_send_allowed=False`
- `client_delivery_auto_approved=False`
- `human_review_required=True` (`ClientAuditInputs`)
- `approval_required_for_execution=True` (`ClientAuditInputs`)
- `approved_for_client_delivery=False` (`ClientAuditResult`)

---

## Phase 6-R — MCP Demo Workflow

No new schemas. Demo workflow calls existing `dispatch()` and returns `dict[str, dict]`.

**Fixed status values validated in demo tests:**
- `healthy` — qa_factory_health
- `analysis_only` — analyze_project, run_flaky_test_analysis
- `planning_only` — run_quality_audit (default)
- `proposal_generated` — propose_self_healing_fixes
- `draft` — generate_delivery_pack
- `blocked` — apply_self_healing_fixes (no approval)

---

- [`APPROVAL_MODEL.md`](APPROVAL_MODEL.md) — risk levels used in `AutomationAction.risk_level` and `ApprovalDecision.risk_level`
- [`SAFETY_RULES.md`](SAFETY_RULES.md) — rules enforced by `SafetyCheck` / `SafetyReport`
- [`TOOLING_DECISIONS.md`](TOOLING_DECISIONS.md) — why pure dataclasses over Pydantic
- [`COMMANDS.md`](COMMANDS.md) — planned commands that will produce schema objects
