# Schema Foundation — Guided QA Automation Workbench

**Version:** 5.7.0  
**Updated:** 2026-05-25  
**Phase:** 4ABC — Schema foundations + Phase 3A/3B/3C schemas + Phase 4ABC Readiness/Evidence/Reporting/Delivery/Scenario schemas

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

- [`APPROVAL_MODEL.md`](APPROVAL_MODEL.md) — risk levels used in `AutomationAction.risk_level` and `ApprovalDecision.risk_level`
- [`SAFETY_RULES.md`](SAFETY_RULES.md) — rules enforced by `SafetyCheck` / `SafetyReport`
- [`TOOLING_DECISIONS.md`](TOOLING_DECISIONS.md) — why pure dataclasses over Pydantic
- [`COMMANDS.md`](COMMANDS.md) — planned commands that will produce schema objects
