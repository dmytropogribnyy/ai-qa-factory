# Phase Contracts — Guided QA Automation Workbench

**Version:** 6.4.0
**Updated:** 2026-05-27
**Phase:** 6-R

This document defines the contract for each implementation phase: inputs, outputs,
allowed actions, blocked actions, and acceptance criteria. Agents must respect these
boundaries before, during, and after each phase.

Status markers:
- `[implemented]` — built and tested in this repository
- `[planned]` — designed but not yet built

---

## Phase 1A — Identity and Documentation `[implemented]`

**Purpose:** Establish product identity, vision, and operational runbook.

**Input artifacts:** none (initial phase)

**Output artifacts:**
- `README.md`
- `docs/VISION.md`
- `docs/RUNBOOK.md`
- `docs/COMMANDS.md`
- `docs/APPROVAL_MODEL.md`
- `docs/SAFETY_RULES.md`
- `docs/TOOLING_DECISIONS.md`

**Allowed actions:**
- Create and edit documentation
- Define product direction, principles, and workflow

**Blocked actions:**
- No code execution
- No external calls
- No credentials

**Acceptance criteria:**
- README describes entry points
- VISION, RUNBOOK, COMMANDS, APPROVAL_MODEL, SAFETY_RULES, TOOLING_DECISIONS present

---

## Phase 1B — Schema Foundation `[implemented]`

**Purpose:** Define the full domain model for the workbench as pure Python dataclasses.
No runtime execution. No side effects.

**Input artifacts:** Phase 1A docs

**Output artifacts:**
- `core/schemas/` — all domain schema modules
- `tests/test_schema_foundations.py`

**Allowed actions:**
- Create Python dataclasses in `core/schemas/`
- Define `to_dict()` / `from_dict()` via `SchemaMixin`
- Write schema round-trip tests
- Update `docs/SCHEMA_FOUNDATION.md`

**Blocked actions:**
- No runtime execution
- No external calls
- No database
- No credentials
- No side effects

**Acceptance criteria:**
- All schemas have `to_dict()` / `from_dict()` round-trips
- All schema tests pass
- `docs/SCHEMA_FOUNDATION.md` accurately describes the schema layer

---

## Phase 1B-DOCS — Documentation Governance `[implemented]`

**Purpose:** Add documentation governance so docs never drift from code.

**Input artifacts:** Phase 1B schemas, Phase 1A docs

**Output artifacts:**
- `docs/DOCS_MANIFEST.md`
- `docs/DOCUMENTATION_GOVERNANCE.md`
- `tools/docs_audit.py`
- `outputs/docs_audit/DOCS_FRESHNESS_REPORT.md` (runtime, gitignored)

**Allowed actions:**
- Create docs manifest and governance rules
- Create `tools/docs_audit.py` — dependency-free, no external calls
- Run audit and write report to `outputs/`

**Blocked actions:**
- No external calls in audit tool
- No automatic doc rewriting
- No LLM calls

**Acceptance criteria:**
- `docs_audit.py` reports PASS
- All required docs exist
- DOCS_MANIFEST.md is populated

---

## Phase 2A — Input Context Resolver + Work Request Classifier `[implemented]`

**Purpose:** Classify raw inputs (URLs, files, text) into typed schema objects and write
initial project artifacts. Classify-only — no execution, no fetching.

**Input artifacts:** raw text / URLs / files from user

**Output artifacts (per project run, under `outputs/<project_id>/00_project/`):**
- `INPUT_MAP.json` / `INPUT_MAP.md`
- `WORK_REQUEST.json` / `WORK_REQUEST.md`
- `TASK_CLASSIFICATION.json` / `TASK_CLASSIFICATION.md`
- `PROJECT_STATUS.json` / `PROJECT_STATUS.md`
- `NEXT_SAFE_STEP.md`

**Runtime modules:**
- `core/input_context_resolver.py` — `InputContextResolver`
- `core/work_request_classifier.py` — `WorkRequestClassifier`
- `core/workbench_controller.py` — `WorkbenchController` (Phase 2A methods)
- `tools/classify_inputs.py` — CLI entry point

**Allowed actions:**
- Classify input strings by type (task_url, target_url, repo_url, api_docs_url, etc.)
- Redact detected secrets before storing
- Write artifacts to `outputs/<project_id>/00_project/`
- Run keyword signal detection (no LLM required)

**Blocked actions:**
- No URL fetching
- No browser execution
- No repository cloning
- No credential use
- No external API calls
- No n8n/webhook calls [planned — Phase 2+]

**Secret redaction rules (enforced):**
- Raw passwords, tokens, cookies, JWTs, API keys are replaced with `[REDACTED_*]`
- `credentials_reference` sources are blocked and approval-required
- No raw secret value is stored in any artifact

**Acceptance criteria:**
- `python tools/classify_inputs.py --input "..."` classifies correctly
- All 5 artifact types are written
- No raw secrets in any artifact
- 69+ Phase 2A tests passing

---

## Phase 2B — Project Blueprint Builder `[implemented]`

**Purpose:** Build the project planning source-of-truth from Phase 2A context.
Planning-only — no execution, no scaffolding.

**Input artifacts:**
- `INPUT_MAP.json` (Phase 2A)
- `WORK_REQUEST.json` (Phase 2A)
- `TASK_CLASSIFICATION.json` (Phase 2A)

**Output artifacts (under `outputs/<project_id>/00_project/`):**
- `PROJECT_BLUEPRINT.json` / `PROJECT_BLUEPRINT.md`
- `ASSUMPTIONS.md`
- `MISSING_INFO.md`
- `SAFE_NEXT_STEPS.md`
- `BLOCKED_ACTIONS.md`
- `INITIAL_QA_STRATEGY_OUTLINE.md`

**Runtime modules:**
- `core/project_blueprint_builder.py` — `ProjectBlueprintBuilder`
- `core/workbench_controller.py` — Phase 2B methods
- `tools/classify_inputs.py --with-blueprint` — CLI entry point

**Allowed actions:**
- Infer project type from text signals (8 types)
- Infer environment from text signals (5 types)
- Build assumptions, missing info, safe next steps, blocked actions lists
- Write all 7 artifact files to `outputs/<project_id>/00_project/`
- Redact secrets in all artifacts

**Blocked actions:**
- No URL fetching
- No browser execution
- No Playwright scaffold generation
- No credential use
- No external calls
- No executable test generation
- No n8n/webhook calls [planned — Phase 2+]

**Acceptance criteria:**
- `python tools/classify_inputs.py --input "..." --with-blueprint` writes 16 artifacts
- No raw secrets in any artifact
- `credentials_reference` sources blocked and noted in blueprint
- 82+ Phase 2B tests passing

---

## Phase 2B-AGENT — Agent Operating Contract `[implemented]`

**Purpose:** Define the agent operating contract, phase contracts, artifact contracts,
and handoff template. Create an agent readiness audit tool.
Documentation and tooling only — no runtime changes.

**Input artifacts:** all Phase 2B docs and code

**Output artifacts:**
- `docs/AGENT_CONTRACT.md`
- `docs/PHASE_CONTRACTS.md` ← this file
- `docs/ARTIFACT_CONTRACTS.md`
- `docs/AGENT_HANDOFF_TEMPLATE.md`
- `tools/agent_readiness_audit.py`
- `tests/test_agent_readiness.py`

**Allowed actions:**
- Create agent contract and phase contract docs
- Create artifact contract doc
- Create handoff report template
- Create `tools/agent_readiness_audit.py` — dependency-free, no external calls
- Write tests that verify docs and audit tool exist and pass
- Update DOCS_MANIFEST, DOCUMENTATION_GOVERNANCE, COMMANDS, RUNBOOK, TOOLING_DECISIONS

**Blocked actions:**
- No new runtime modules
- No schema changes
- No autonomous agent runtime
- No external calls
- No credentials

**Acceptance criteria:**
- All four agent contract docs created
- `agent_readiness_audit.py` reports PASS
- All tests pass
- docs_audit passes

---

## Phase 2C — Strategy Planner + Tactical Planning Foundation `[implemented]`

**Purpose:** Build QA strategy and tactical planning foundation from `ProjectBlueprint`.
Planning-only — no execution, no scaffolding, no credential use, no external calls.

**Input artifacts:**
- `PROJECT_BLUEPRINT.json` (Phase 2B)
- Optional: `InputMap`, `WorkRequest`, `TaskClassification` (from 2A, for signal enrichment)

**Output artifacts (under `outputs/<project_id>/02_strategy/`):**
- `QA_STRATEGY.json` / `QA_STRATEGY.md`
- `TEST_SCOPE.md`
- `RISK_MATRIX.md`
- `TEST_LAYERS.md`
- `TACTICAL_PLAN_OUTLINE.md`
- `QUALITY_RUBRIC.md`
- `STRATEGY_DECISIONS.md`
- `PROJECT_STATUS.json` / `PROJECT_STATUS.md` (updated)

**Runtime modules:**
- `core/qa_strategy_planner.py` — `QAStrategyPlanner`
- `core/schemas/qa_strategy.py` — `QAStrategy` and 5 component schemas
- `core/workbench_controller.py` — Phase 2C methods
- `tools/build_strategy.py` — CLI entry point (standalone)
- `tools/classify_inputs.py --with-strategy` — combined 2A+2B+2C CLI

**Allowed actions:**
- Build QA strategy from blueprint using local signal detection (no LLM required)
- Generate risk matrix from project type, environment, and risk signals
- Define test scope, test layers, and tactical plan from surfaces and blocked actions
- Write all 8 artifact files to `outputs/<project_id>/02_strategy/`
- Carry forward blocked actions and required approvals from blueprint unchanged

**Blocked actions (permanent):**
- No URL fetching
- No browser execution
- No credential use
- No external calls
- No n8n/webhook calls [planned — Phase 2+]
- No Playwright scaffold generation (Phase 3A)
- No executable test generation
- No cleanup/deletion actions
- `client_ready` must remain `False` — explicit approval required before delivery

**Acceptance criteria:**
- `python tools/build_strategy.py --input "..."` writes 8 artifacts to `02_strategy/`
- `python tools/classify_inputs.py --input "..." --with-strategy` writes 22+ total artifacts
- No raw secrets in any artifact
- `client_ready = False` in all strategy outputs
- Blocked actions from blueprint are preserved in strategy output
- 106+ Phase 2C tests passing

---

## Phase 3A — Framework Scaffold Generation `[implemented]`

**Purpose:** Generate a Playwright TypeScript framework scaffold from ProjectBlueprint + QAStrategy.
Scaffold generation only — no execution, no browser, no npm/npx, no credential use.

**Input artifacts:**
- `PROJECT_BLUEPRINT.json` (Phase 2B)
- `QA_STRATEGY.json` (Phase 2C) — optional; scaffold generation works without strategy

**Output artifacts (under `outputs/<project_id>/03_framework/playwright/`):**
- `package.json`, `tsconfig.json`, `playwright.config.ts`, `.gitignore`, `.env.example`, `README.md`
- `tests/smoke/smoke.spec.ts`, `tests/regression/regression-placeholder.spec.ts`
- `tests/auth/auth-placeholder.spec.ts` (if auth layer or web_saas/auth_heavy)
- `tests/api/api-placeholder.spec.ts` (if api layer or api_backend/mixed_ui_api)
- `tests/ecommerce/checkout-placeholder.spec.ts` (ecommerce — blocked until sandbox approval)
- `tests/admin/admin-placeholder.spec.ts` (admin_panel — blocked until admin account approval)
- `pages/BasePage.ts`, `pages/LoginPage.ts` (conditional), `pages/DashboardPage.ts` (conditional)
- `fixtures/test-fixtures.ts`, `utils/env.ts`, `utils/test-data.ts`
- `utils/api-client.ts` (if api layer)
- `test-data/README.md`, `test-data/sample-users.example.json`
- `docs/TEST_STRATEGY.md`, `docs/HOW_TO_RUN.md`, `docs/SCAFFOLD_REVIEW_CHECKLIST.md`
- `FRAMEWORK_SCAFFOLD.json`, `FRAMEWORK_SCAFFOLD.md` (metadata, written to root)

**Runtime modules:**
- `core/framework_scaffold_generator.py` — `FrameworkScaffoldGenerator`
- `core/schemas/framework_scaffold.py` — `FrameworkFile`, `FrameworkScaffold`, `FrameworkScaffoldPlan`
- `core/workbench_controller.py` — Phase 3A methods
- `tools/generate_scaffold.py` — CLI entry point (standalone)

**Allowed actions:**
- Generate scaffold files as plain text to local disk (no execution)
- Build `FrameworkScaffoldPlan` and `FrameworkScaffold` schema objects
- Write all scaffold files to `outputs/<project_id>/03_framework/playwright/`
- Write metadata (`FRAMEWORK_SCAFFOLD.json`, `FRAMEWORK_SCAFFOLD.md`)

**Blocked actions (permanent):**
- No browser execution
- No Playwright execution
- No npm/npx execution
- No TypeScript compilation
- No test execution
- No URL fetching
- No credential use
- No external calls
- No cleanup/deletion actions
- `execution_allowed` must remain `False` in all generated scaffold metadata
- `client_visible` must remain `False` — scaffold requires review before any delivery

**Acceptance criteria:**
- `python tools/generate_scaffold.py --input "..." --project-id <id>` writes all scaffold files
- `FRAMEWORK_SCAFFOLD.json` has `execution_allowed: false`, `client_visible: false`, `requires_review: true`
- Auth spec contains `test.skip` guard requiring `TEST_USERNAME`/`TEST_PASSWORD`
- API spec contains `test.skip` guard requiring `API_BASE_URL`
- Checkout spec (ecommerce) and admin spec (admin_panel) are `test.skip` blocked
- All env references use `process.env.*` — no hardcoded secrets or URLs
- `sample-users.example.json` contains only `PLACEHOLDER` values
- 577+ existing tests passing + Phase 3A test suite passing
- No subprocess, no playwright import in generator module

---

## Phase 3B — Safe Local Scaffold Validation `[implemented]`

**Purpose:** Statically validate a generated Playwright scaffold without executing any code.
Inspection-only — no npm/npx, no TypeScript compilation, no Playwright execution, no browser launch.

**Input artifacts:**
- `outputs/<project_id>/03_framework/playwright/` (Phase 3A scaffold)
- `FRAMEWORK_SCAFFOLD.json` (Phase 3A metadata)

**Output artifacts (under `outputs/<project_id>/03_framework/playwright/`):**
- `STATIC_VALIDATION_REPORT.json` — full `ScaffoldValidationReport` schema
- `STATIC_VALIDATION_REPORT.md` — human-readable report with safety invariants
- `VALIDATION_PLAN.md` — what Phase 3B checked and what Phase 3C (toolchain) would do
- `LOCAL_VALIDATION_CHECKLIST.md` — human checklist before running any local command
- `TOOLCHAIN_VALIDATION_PLAN.md` — proposed toolchain commands (not executed)

**Runtime modules:**
- `core/scaffold_validator.py` — `ScaffoldValidator`
- `core/schemas/scaffold_validation.py` — `ScaffoldValidationCheck`, `ScaffoldValidationReport`, `ToolchainValidationPlan`
- `core/workbench_controller.py` — Phase 3B methods
- `tools/validate_scaffold.py` — CLI entry point

**Check categories:**
- `structure` — required files present
- `metadata` — `execution_allowed=False`, `client_visible=False`, `requires_review=True`
- `package_json` — parseable, no lifecycle hooks, Playwright declared
- `config` — `playwright.config.ts` uses `process.env`
- `env` — `.env.example` present, no real secrets, no `.env` file
- `tests` — skip guards on auth/api/checkout specs
- `docs` — README present and documents env vars
- `secrets` — no API keys, JWTs, hardcoded passwords in scaffold files
- `urls` — no hardcoded external URLs in executable files
- `repository_boundary` — scaffold inside `outputs/`, no `.git` inside scaffold

**Blocked actions (permanent):**
- No npm install / npm ci / npx
- No TypeScript compilation
- No Playwright execution
- No browser launch
- No URL fetching
- No credential use
- No external calls
- `execution_performed`, `npm_performed`, `npx_performed`, `browser_performed`,
  `external_calls_performed` remain `False` always
- `safe_to_execute_tests` remains `False` always

**Safety invariants (guaranteed):**
- `ScaffoldValidationReport.execution_performed = False`
- `ScaffoldValidationReport.npm_performed = False`
- `ScaffoldValidationReport.npx_performed = False`
- `ScaffoldValidationReport.browser_performed = False`
- `ScaffoldValidationReport.external_calls_performed = False`
- `ScaffoldValidationReport.safe_to_execute_tests = False`

**Acceptance criteria:**
- `python tools/validate_scaffold.py --scaffold-root <path>` runs without error
- `STATIC_VALIDATION_REPORT.json` has all six safety flags `false`
- `execution_allowed=True` in scaffold metadata → blocker
- `client_visible=True` in scaffold metadata → blocker
- `requires_review=False` in scaffold metadata → blocker
- Lifecycle hooks in `package.json` → blocker
- Hardcoded external URL in scaffold `.ts`/`.js` → blocker
- Secret patterns in scaffold files → blocker
- Scaffold outside `outputs/` → blocker
- `FakeSecret123` in scaffold → does not appear in validation artifacts
- 49+ Phase 3B tests passing
- No subprocess, no playwright import in `scaffold_validator.py`

---

## Phase 3B-SCENARIOS — Practical Client Scenario Fixtures `[implemented]`

**Purpose:** Create a controlled, committed fixture layer of realistic client QA scenarios.
Fixtures are source inputs used to evaluate Workbench behavior across all phases.
Docs/fixtures/tests only — no runtime behavior changes.

**Input artifacts:** Phase 3B docs and tools

**Output artifacts:**
- `docs/CLIENT_SCENARIO_FIXTURES.md` — category definitions, safe usage, blocked actions
- `fixtures/client_scenarios/README.md` — directory intro and category rules
- `fixtures/client_scenarios/synthetic/` — 4 synthetic scenarios
- `fixtures/client_scenarios/public_demo_targets/` — 6 public demo scenarios
- `fixtures/client_scenarios/real_public_readonly/` — 2 real production read-only scenarios
- `fixtures/client_scenarios/high_risk_marketplace_readonly/` — 1 high-risk marketplace scenario
- `tests/test_client_scenario_fixtures.py` — fixture evaluation tests

**Scenario categories:**
- `synthetic` — fake URLs and fake credentials; safety and redaction verification
- `public_demo_targets` — real demo/practice apps; execution requires approval
- `real_public_readonly` — real production sites; read-only planning only; execution blocked
- `high_risk_marketplace_readonly` — real marketplaces (Amazon etc.); all execution blocked

**Allowed actions:**
- Create Markdown fixture files in `fixtures/client_scenarios/`
- Create evaluation tests in `tests/test_client_scenario_fixtures.py`
- Update existing docs to reference fixtures correctly

**Blocked actions (permanent):**
- No URL fetching
- No browser execution
- No external API calls
- No credential use
- No real secrets in fixture files
- No runtime outputs generated in `outputs/`
- No orchestrator changes
- No heavy new dependencies

**Fixture contract guarantees:**
- Fixtures are committed source material — not runtime outputs
- Real URLs in fixtures do not authorize execution against those URLs
- Every public demo target explicitly requires per-run approval
- Every real production fixture explicitly blocks execution without written approval
- High-risk marketplace fixtures mark all execution as unconditionally blocked
- No real secrets, OAuth tokens, webhook tokens, or API keys in any fixture
- `task_url` inputs (Linear, Jira, etc.) are requirement sources — not `target_application`

**Acceptance criteria:**
- 13 scenario files exist across 4 categories
- Every scenario has all 11 required sections
- `tests/test_client_scenario_fixtures.py` passes with all scenario-count and safety checks
- No real credentials found in any fixture file
- All 7 updated docs reflect Phase 3B-SCENARIOS correctly

---

## Phase 3C — Approved Local Toolchain Validation `[implemented]`

**Purpose:** Approval-gated local toolchain validation for generated Playwright scaffolds.
Runs only allowlisted local commands (`npm install`, `npm run typecheck`,
`npx playwright test --list`) inside the scaffold directory. Requires explicit `--approve-toolchain`
flag; without it, all commands are skipped and `validation_status="blocked"`. No browser
execution, no external URLs, no credentials — ever.

**Input artifacts:** Phase 3B static validation report (`STATIC_VALIDATION_REPORT.json`)

**Output artifacts** (written to scaffold root):
- `TOOLCHAIN_VALIDATION_REPORT.json` — `ToolchainValidationReport` schema object
- `TOOLCHAIN_VALIDATION_REPORT.md` — human-readable report with safety invariants
- `TOOLCHAIN_COMMAND_LOG.md` — per-command stdout/stderr excerpts (no secrets)
- `TOOLCHAIN_APPROVAL_RECORD.md` — approval state, allowed/denied commands, constraints

**New schemas:** `ToolchainCommandResult`, `ToolchainApprovalRecord`, `ToolchainValidationReport`

**New modules:** `core/toolchain_validator.py`, `core/schemas/toolchain_validation.py`

**New CLI:** `tools/validate_toolchain.py --project-id <id> [--approve-toolchain]`

**Allowed actions (with `--approve-toolchain`):**
- `npm install` inside scaffold root
- `npm run typecheck` inside scaffold root
- `npx playwright test --list` inside scaffold root (discovery mode only)

**Blocked actions (permanent — no flag overrides these):**
- No `npx playwright install` or `npx playwright test`
- No `npm test` or `npm run test`
- No headed/headless browser launch
- No external URL access
- No `.env` reading or credential injection
- No external API calls
- No n8n / webhook calls

**Safety invariants (hardcoded `False` — never overridden):**
- `safe_to_execute_tests = False`
- `browser_execution_performed = False`
- `external_url_used = False`
- `credentials_used = False`

**Acceptance criteria:**
- 63 Phase 3C tests pass (all classes)
- Without `--approve-toolchain`: no subprocess runs, `validation_status="blocked"`
- With `--approve-toolchain`: allowlisted commands run, safety invariants remain `False`
- `core/workbench_controller.py` has `validate_toolchain()` and `render_toolchain_validation_artifacts()`
- All 7 Phase 3C docs updated
- `python tools/validate_toolchain.py --project-id <id>` runs without error (no-write mode)

---

## Phase 4ABC — Readiness, Evidence Foundation, Report Drafts, Delivery Preview, Scenario Evaluation `[implemented]`

**Purpose:** Prepare for future approved execution by generating readiness artifacts,
evidence foundation, draft reports, delivery preview, and scenario evaluation.
No browser execution. No Playwright test execution. No target URL access. No credentials.

**Inputs:**
- `outputs/<id>/00_project/PROJECT_BLUEPRINT.json` (Phase 2B)
- `outputs/<id>/02_strategy/QA_STRATEGY.json` (Phase 2C)
- `outputs/<id>/03_framework/playwright/FRAMEWORK_SCAFFOLD.json` (Phase 3A)
- `outputs/<id>/03_framework/playwright/STATIC_VALIDATION_REPORT.json` (Phase 3B)
- `outputs/<id>/03_framework/playwright/TOOLCHAIN_VALIDATION_REPORT.json` (Phase 3C)
- `fixtures/client_scenarios/**/*.md` (Phase 3B-SCENARIOS)

**Output artifacts:**
- `04_execution_plan/` — approval checklist, readiness report, boundaries, evidence plan
- `05_evidence/` — evidence manifest, quality gate, redaction report, internal summary
- `06_client_draft/` — internal QA summary, client report draft, delivery note, quality checklist, delivery preview, safety checklist
- `99_internal/scenario_evaluation/` — scenario batch evaluation

**CLI tools:**
- `python tools/plan_execution.py --project-id <id>`
- `python tools/build_evidence_foundation.py --project-id <id>`
- `python tools/build_report_drafts.py --project-id <id>`
- `python tools/build_delivery_preview.py --project-id <id>`
- `python tools/evaluate_scenarios.py --project-id <id>`

**Blocked actions (permanent in this phase):**
- No browser execution
- No Playwright test execution
- No target URL fetching
- No credential use
- No external API calls
- No zip/package creation
- No marking `approved_for_execution=True`
- No marking `approved_for_client_delivery=True`
- No marking `safe_to_deliver=True`

**Safety invariants (always False):**
- `approved_for_execution=False`
- `approved_for_browser_execution=False`
- `approved_for_client_delivery=False`
- `client_visible=False` (evidence records)
- `approved_for_client_view=False`
- `safe_to_deliver=False`
- `safe_to_package=False`
- `package_created=False`
- `zip_created=False`
- `external_calls_performed=False` (scenario evaluation)
- `evaluation_performed_without_execution=True` (scenario evaluation)

**New schemas:**
- `ExecutionApprovalRequirement`, `ExecutionApprovalChecklist`, `ExecutionReadinessReport` (Phase 4A)
- `EvidenceRecord`, `EvidenceCollection`, `EvidenceQualityGate`, `EvidenceRedactionReport` (Phase 4B)
- `ReportSection`, `ReportDraft`, `ReportQualityChecklist`, `DeliveryNoteDraft` (Phase 4C)
- `DeliveryPreviewItem`, `DeliveryPackagePreview`, `DeliverySafetyChecklist` (Phase 4C)
- `ScenarioEvaluationResult`, `ScenarioBatchEvaluationReport` (Phase 4ABC)

**Acceptance criteria:**
- All Phase 4ABC tests pass
- docs_audit passes, agent_readiness_audit passes
- No URL fetching, no browser execution, no Playwright test execution
- No credential use, no external calls
- All approved_for_* flags False by default
- Evidence internal-only by default
- Client reports draft-only, not approved for delivery
- Delivery preview is preview-only, no packaging

---

## Phase 4D — Approved Controlled Demo and Public Read-Only Browser Execution `[implemented]`

**Purpose:** Run approval-gated Playwright commands against safe demo/local targets and one explicit public read-only profile. Collect internal evidence. No general production execution.

**Approval flags:**
- `--approve-demo-execution` — allows local/localhost/public_demo_target execution only
- `--approve-public-readonly-execution` + `--readonly-profile playwright_docs_readonly` — allows playwright.dev read-only smoke only

**Allowed targets:**
- `local` / `localhost`
- `public_demo_target` (saucedemo_public_demo, the_internet_public_demo)
- `real_public_readonly` only via `playwright_docs_readonly` profile

**Allowed commands (allowlist):**
- `npx playwright test --list`
- `npx playwright test tests/smoke --reporter=list`
- `npx playwright test tests/smoke --reporter=html,list`

**Output artifacts (under `outputs/<project_id>/07_execution/`):**
- `BROWSER_EXECUTION_APPROVAL.json/.md`
- `BROWSER_EXECUTION_REPORT.json/.md`
- `BROWSER_COMMAND_LOG.md`
- `BROWSER_EVIDENCE_MANIFEST.json/.md`

**Blocked actions (permanent):**
- `alza.sk`, `amazon.com`, `linear.app` always blocked
- `playwright.dev` blocked without readonly profile + approval
- `production`, `high_risk_marketplace_readonly`, `task_source` always blocked
- No real credentials, no auth flows, no payment/checkout, no destructive writes
- No scraping/crawling/load/security testing
- No npm install / playwright install
- No client delivery (`safe_to_deliver=False`, `approved_for_client_delivery=False`)

**Acceptance criteria:**
- No subprocess without explicit approval flag
- No execution against blocked targets regardless of approval
- All delivery flags hardcoded False via `__post_init__`
- Evidence internal-only by default
- All existing tests pass; new Phase 4D tests pass

**What Phase 4D is NOT:**
- Not general production/client execution (→ Phase 5A+)
- Not auth/credential execution (→ future explicit phase)
- Not payment/checkout execution (→ future explicit phase)
- Not final client delivery

---

## Phase 4E — Credential and Test-Account Safety Layer `[implemented]`

**Purpose:** Define credential safety policy, schema, and tooling for safe credential handling in future auth execution phases. Policy, schema, CLI inspection only — no real credentials, no login, no auth execution.

**Inputs:**
- Project ID (from any prior phase)
- Optional: fixture scan, scaffold scan, sandbox label

**Outputs:** `outputs/<project_id>/08_credentials/` (11 artifacts — all internal-only)

**Allowed actions:**
- Static text scanning of safe local files (.md, .json, .ts, .js, .example)
- Sandbox profile classification from labels
- Writing credential safety artifacts to `outputs/`
- Producing `CredentialPolicy`, `CredentialSafetyReport`, `StorageStatePolicy`, `AuthExecutionApproval`

**Blocked actions:**
- Reading `.env`, `.env.local`, `.auth/*.json`, `storageState` files
- Using, storing, or logging real credentials
- Login or auth execution
- Reading node_modules, test-results, playwright-report
- External API calls
- subprocess execution
- Staging `outputs/`

**Safety invariants (always True in Phase 4E):**
- `safe_for_auth_execution=False`
- `safe_for_client_visibility=False`
- `approved_for_commit=False` (StorageStatePolicy)
- `AuthExecutionApproval.approved=False`
- `SandboxProfileClassification.blocked_in_current_phase=True`
- `allow_real_credentials=False` (CredentialPolicy, enforced by `__post_init__`)
- `allow_personal_accounts=False`
- `allow_production_accounts=False`

**Acceptance criteria:**
- All existing tests pass; new Phase 4E tests pass
- `python tools/inspect_credentials.py --project-id demo --no-write` exits cleanly
- `--classify-sandbox "Amazon Pay Sandbox"` → `future_sandbox_integration`, blocked
- `--classify-sandbox "Alza production account"` → `blocked_production_ecommerce`, blocked
- docs_audit passes; agent_readiness_audit passes

**What Phase 4E is NOT:**
- Not auth execution (→ future explicit auth execution phase)
- Not credential provisioning (→ client provides test credentials at execution time)
- Not payment/sandbox testing (→ future explicit sandbox phase)
- Not final client delivery

---

## Phase 5AB — Runtime Secret Routing + Dedicated Test-Account Auth Execution `[implemented]`

**Goal:** Add approval-gated auth execution for dedicated test accounts using env var references.
No raw secrets in CLI args, no .env reading, no personal/production accounts, no Google OAuth.

**Inputs:**
- `--approve-dedicated-auth-execution` flag (required for execution)
- `--username-env-var` / `--password-env-var` (env var **names** only — not values)
- `--scenario-lane` + `--target-category` + `--target-url`
- `--dedicated-test-account-confirmed` + scope confirmation flag

**Outputs:**
- `outputs/<project_id>/11_runtime_secrets/` — intake validation, routing plan
- `outputs/<project_id>/12_dedicated_auth/` — execution report, command log, session artifacts, safety boundary

**CLI tools:**
- `python tools/plan_runtime_secrets.py --project-id <id>` — validate intake, no execution
- `python tools/run_dedicated_auth.py --project-id <id> --approve-dedicated-auth-execution ...` — run

**Allowed lanes:** `dedicated_test_account_auth_future`, `staging_client_app_future`

**Allowed target categories:** `staging`, `client_test_environment`, `dedicated_test_environment`,
`orangehrm_demo_auth`, `restful_booker_demo_auth`, `dedicated_test_account_custom_target`

**9 security gates (all must pass before any subprocess):**
1. `--approve-dedicated-auth-execution` flag required
2. Personal/production account flags blocked
3. `--scenario-lane` in allowed set
4. `--target-category` in allowed set
5. `--target-url` not matching blocked URL patterns
6. `--dedicated-test-account-confirmed` + scope confirmation
7. Env var name format validation (`^[A-Z][A-Z0-9_]{0,79}$`)
8. Env var values exist in `os.environ`
9. Scaffold / node_modules / tests/auth exist

**Always-blocked targets (regardless of approval):**
`accounts.google.com`, `google.com/o/oauth2`, `amazon.com`, `pay.amazon.com`,
`alza.sk/cz/hu/at/de`, `linkedin.com`, `upwork.com`

**Safety invariants (always False — hardcoded in `__post_init__` and `from_dict`):**
- `raw_credentials_logged=False`
- `raw_credentials_serialized=False`
- `personal_account_used=False`
- `production_account_used=False`
- `safe_to_deliver=False`
- `approved_for_client_delivery=False`
- `DedicatedAuthSessionArtifact.approved_for_commit=False`
- `DedicatedAuthSessionArtifact.client_visible=False`
- `TestAccountValidationResult.approved_for_execution_now=False`

**What Phase 5AB is NOT:**
- Not approval for Amazon Pay Sandbox (→ Phase 5C)
- Not approval for task source integration (Linear/Jira) (→ Phase 5D)
- Not approval for production read-only auth (→ separate explicit phase)
- Not approval for Google OAuth (always blocked)
- Not approval for Alza/Amazon/LinkedIn/Upwork auth (always blocked)
- Not final client delivery (`safe_to_deliver=False` always)

---

## Cross-Phase Rules (all phases)

These rules apply in every phase, without exception:

1. `outputs/` is always gitignored — never staged, never committed
2. Secrets are redacted before storage in any field or artifact
3. `core/orchestrator.py` is never replaced without explicit architecture approval
4. Docs are updated alongside code changes (same commit)
5. Every phase ends with: `pytest -q` + `docs_audit` + `agent_readiness_audit` all passing
6. Execution phases require the `RUNBOOK.md` section 4 checklist completed per run

---

## Phase 4F — Approved Demo Auth Execution `[implemented]`

**Goal:** Add approval-gated demo auth execution layer using safe public demo credentials only.

**Inputs:** Scaffold at `outputs/<project_id>/03_framework/playwright/`, `--approve-demo-auth-execution`, `--auth-profile saucedemo_demo_auth`

**Outputs:** `outputs/<project_id>/09_auth/` (8 artifacts — all internal-only)

**Allowed:**
- `saucedemo_demo_auth` profile only (SauceDemo public demo credentials)
- `auth_smoke` and `auth_setup` command modes
- `tests/auth` test path only
- storageState under `outputs/<project_id>/09_auth/.auth/` only

**Blocked:**
- No personal credentials, production credentials, or client credentials
- No Alza/Amazon/Google/LinkedIn/Upwork/Linear auth — always blocked
- No payment/checkout/order creation
- No destructive/admin writes
- No npm install / npx playwright install
- No client delivery — `safe_to_deliver=False` always

**Safety invariants (always enforced):**
- `real_credentials_used=False` — hardcoded in schema
- `personal_account_used=False` — hardcoded in schema
- `production_account_used=False` — hardcoded in schema
- `safe_to_deliver=False` — hardcoded in schema
- `approved_for_client_delivery=False` — hardcoded in schema
- `AuthSessionArtifact.approved_for_commit=False` — hardcoded
- `AuthSessionArtifact.client_visible=False` — hardcoded

**What Phase 4F is NOT:**
- Not approval for Alza/Amazon/Google/LinkedIn/Upwork/Linear auth
- Not approval for real client credentials or personal accounts
- Not approval for production auth execution
- Not approval for payment/checkout/destructive flows
- Not approval for client delivery

---

## Phase 4G — Scenario Execution Matrix and Dedicated Test Account Planning `[implemented]`

**Goal:** Canonical execution lane routing, permission table, target profiles, dedicated
test-account planning. Policy/schema/routing only — no execution, no credentials.

**Allowed-now lanes (3):** `no_auth_demo_smoke`, `no_auth_public_readonly_smoke`, `demo_auth_smoke`  
**Future lanes (5):** `dedicated_test_account_auth_future`, `staging_client_app_future`,
`production_readonly_future`, `sandbox_payment_future`, `task_source_integration_future`  
**Blocked lane (1):** `strictly_blocked`

**Safety invariants:** `safe_for_execution_now=False`, `personal_account_allowed=False`,
`production_account_allowed=False`, `repo_storage_allowed=False`, `logging_allowed=False`,
`client_visible_allowed=False` — all hardcoded.

**What Phase 4G is NOT:**
- Not approval for dedicated test-account execution (Phase 5A)
- Not approval for staging client app execution (Phase 5A)
- Not approval for Amazon Pay Sandbox (Phase 5C)
- Not approval for task source integration (Phase 5D)
- Not approval for API auth smoke (Phase 5E)
- Not approval for client delivery

---

## Phase 5E — API Auth Smoke [implemented]

**Scope:** Approval-gated HTTP API auth smoke for token-based public/demo/staging API targets.

**Runner:** `APIAuthRunner` (`core/api_auth_runner.py`)  
**CLI:** `tools/run_api_auth_smoke.py`  
**Artifacts:** `outputs/<project_id>/13_api_auth/`

**Allowed target profiles:**

| Profile | Base URL | Auth endpoint | Safe read |
|---|---|---|---|
| `restful_booker_public_api` | `https://restful-booker.herokuapp.com` | `POST /auth` | `GET /booking` |

**Security gates (7 sequential):**

1. `--approve-api-auth-execution` required
2. No `personal_account_confirmed=True`
3. No `production_account_confirmed=True`
4. Target profile must be in allowlist
5. URL not in strictly-blocked list
6. Env var name format: `^[A-Z][A-Z0-9_]*$`, max 64 chars
7. Env var must exist in process environment (truthy)

**Safety invariants (hardcoded in `__post_init__` + `from_dict`):**
- `raw_credentials_logged=False` always
- `raw_credentials_serialized=False` always
- `token_logged=False` always
- `token_serialized=False` always
- `safe_to_deliver=False` always
- `approved_for_client_delivery=False` always
- `personal_account_used=False` always
- `production_account_used=False` always

**What Phase 5E is NOT:**
- Not approval for browser UI auth (→ Phase 5AB `run_dedicated_auth.py`)
- Not approval for Amazon Pay Sandbox (→ Phase 5C)
- Not approval for task source integration (→ Phase 5D)
- Not approval for DELETE / PUT / destructive API calls
- Not approval for client delivery

---

## Phase 5G — Google/OAuth Test Account Capability [implemented]

**Scope:** Permissioned capability path for dedicated Google test-account authentication.
Replaces the blanket Google block (which remains in generic runners) with a Google-specific
runner that supports manual storageState capture and storageState reuse smoke.

**Planner:** `GoogleAuthCapabilityPlanner` (`core/google_auth_capability.py`)
**Runner:** `GoogleAuthRunner` (`core/google_auth_runner.py`)
**CLIs:** `tools/plan_google_auth.py`, `tools/capture_google_storage_state.py`, `tools/run_google_auth_smoke.py`
**Artifacts:** `outputs/<project_id>/15_google_auth/`

**Supported modes:**

| Mode | Status in 5G | Notes |
|---|---|---|
| `manual_storage_state_capture` | **executable** | Browser opens, user logs in manually |
| `storage_state_reuse` | **executable** | Read-only smoke using captured state |
| `cdp_attach` | planning-only | Execution deferred |
| `dedicated_profile_context` | planning-only | Execution deferred |
| `google_api_oauth_token_future` | planning-only | Execution deferred |
| `google_service_account_future` | planning-only | Execution deferred |
| `totp_test_account_future` | planning-only | Execution deferred |
| `mock_oauth_provider_future` | planning-only | Execution deferred |

**Allowed Google target URL prefixes (https only):**
- `https://accounts.google.com`
- `https://mail.google.com`
- `https://drive.google.com`
- `https://docs.google.com`
- `https://myaccount.google.com`
- `https://workspace.google.com`

**Required approval flags (every executable mode):**
- `--approve-google-test-account`
- `--google-test-account-confirmed`
- `--dedicated-test-account-confirmed`

**Always blocked (hardcoded, cannot be overridden):**
- `personal_account_confirmed=True` → BLOCK
- `production_account_confirmed=True` → BLOCK
- `captcha_bypass_allowed` → always `False`
- `anti_bot_bypass_allowed` → always `False`
- `client_delivery_allowed` → always `False`
- Stealth/undetected-browser as core path → never
- Raw secrets in CLI args / JSON / MD / logs / reports → never
- Reading storageState content / Chrome profile content → never

**Generic runners still block Google:**
- `core/dedicated_auth_runner.py` — `accounts.google.com` remains in `_STRICTLY_BLOCKED_URL_PATTERNS`
- `core/api_auth_runner.py` — same
- Google is only allowed via Phase 5G dedicated runner.

**Safety invariants (hardcoded in `__post_init__` + `from_dict`):**
- `GoogleAuthCapability.raw_secrets_allowed=False`
- `GoogleAuthCapability.captcha_bypass_allowed=False`
- `GoogleAuthCapability.anti_bot_bypass_allowed=False`
- `GoogleAuthCapability.client_delivery_allowed=False`
- `GoogleAuthCapability.personal_account_always_blocked=True`
- `GoogleAuthCapability.production_account_always_blocked=True`
- `GoogleAuthEvidenceReport.cookies_logged=False`
- `GoogleAuthEvidenceReport.tokens_logged=False`
- `GoogleAuthEvidenceReport.storage_state_content_read=False`
- `GoogleAuthEvidenceReport.captcha_bypass_attempted=False`
- `GoogleAuthEvidenceReport.anti_bot_bypass_attempted=False`
- `GoogleAuthEvidenceReport.safe_to_deliver=False`
- `GoogleAuthEvidenceReport.human_review_required=True`

**What Phase 5G is NOT:**
- Not unblocking Google globally — only the Phase 5G dedicated runner accepts Google.
- Not approval for personal Google accounts.
- Not approval for production Google accounts.
- Not approval for CAPTCHA or anti-bot bypass.
- Not approval for reading Gmail/Drive content.
- Not approval for writing/deleting Google account data.
- Not approval to copy main Chrome profile.
- Not approval for client delivery.

---

## Phase 5F — QA Evidence Report Generator [implemented]

**Scope:** Read-only aggregation of Phase 5AB and Phase 5E execution artifacts into a
consolidated QA Evidence Report with multi-source aggregation and secret scan.

**Generator:** `QAReportGenerator` (`core/qa_report_generator.py`)  
**CLI:** `tools/generate_qa_report.py`  
**Artifacts:** `outputs/<project_id>/14_qa_report/`

**Multi-source aggregation:**
- Accepts 1..N `source_project_ids` (via `--source-project-id`, repeatable)
- Reads from each source: `12_dedicated_auth/DEDICATED_AUTH_EXECUTION_REPORT.json`
  and `13_api_auth/API_AUTH_EXECUTION_REPORT.json`
- Missing artifacts produce `artifacts_missing` entries, not errors
- Coverage summary computed across all source projects

**Secret scan:**
- Checks generated report content against known env var values
- Env var names checked: `ORANGEHRM_USERNAME/PASSWORD`, `RESTFUL_BOOKER_USERNAME/PASSWORD`,
  `QA_TEST_USERNAME/PASSWORD`, `STAGING_USERNAME/PASSWORD`
- Values read internally, never logged or printed — only finding descriptions logged
- Token pattern scan: flags unmasked alphanumeric strings ≥ 20 chars
- Verdict: `clean | warn | fail`

**Safety invariants (hardcoded in `__post_init__` + `from_dict`, all unconditional):**
- `execution_performed=False` — no tests or scripts run
- `network_calls_performed=False` — no HTTP requests
- `raw_credentials_in_report=False`
- `raw_tokens_in_report=False`
- `storage_state_content_read=False` — `.auth/storageState.json` never read
- `safe_to_deliver=False`
- `approved_for_client_delivery=False`
- `client_ready=False`
- `human_review_required=True`

**Coverage model:**

| Lane | Provided by |
|---|---|
| `browser_auth` | Phase 5AB `DEDICATED_AUTH_EXECUTION_REPORT.json` |
| `api_auth` | Phase 5E `API_AUTH_EXECUTION_REPORT.json` |
| `functional_tests` | Not yet covered — future phase |
| `e2e_scenarios` | Not yet covered — future phase |
| `performance_tests` | Not yet covered — future phase |
| `security_tests` | Not yet covered — future phase |

**What Phase 5F is NOT:**
- Not execution — no subprocess, no browser, no network calls
- Not approval for client delivery — `approved_for_client_delivery=False` always
- Not a replacement for Phase 5AB or Phase 5E runners
- Not able to read storageState content

---

## Phase 5H — Multi-Target Expansion + Task Source Integration [implemented]

**Scope:**
1. Amazon/Alza unblocked as public read-only navigation targets (path-gated; auth/cart/checkout remain blocked)
2. Linear task source integration — read issues as requirements input, derive test scenarios
3. SauceDemo + practice site demo auth target categories
4. New API profiles: JSONPlaceholder (no-auth), PetStore Swagger (no-auth), Reqres.in, DummyJSON
5. CDP Attach + Dedicated Profile Context promoted from planning-only to executable

**What Phase 5H IS:**
- Reading Linear issues via official GraphQL API with a read-only token (never writeback)
- Deriving test scenarios from issue titles/descriptions/acceptance criteria
- Public product/search/category pages on Amazon and Alza (path-gated readonly)
- CDP Attach: attaching to an already-running Chrome session the user launched and authenticated manually
- Dedicated Profile Context: launching Chromium with a persistent `user-data-dir` the user pre-populated

**What Phase 5H is NOT:**
- Not testing Linear UI (Linear is requirements input only — never navigated)
- Not testing Amazon/Alza auth, cart, checkout, account, or order pages
- Not automating login on any Google/Amazon/Alza site
- Not storing raw Linear API tokens (env var name only)
- Not posting comments, changing statuses, or creating webhooks in Linear

**Safety invariants (all hardcoded, cannot be bypassed):**
- `writeback_allowed=False` in `TaskSourceFetchPolicy`
- `raw_token_logged=False` in `TaskSourceFetchPolicy`
- `client_delivery_allowed=False` in `TaskSourceFetchReport`
- Amazon/Alza blocked paths: `/signin`, `/cart`, `/checkout`, `/account`, `/order`, `/gp/buy`, `/ap/`, `/orders`
- CDP Attach port must be 1024–65535; no password automation
- `captcha_bypass_allowed=False` — hardcoded, unchanged

---

---

## Phase 5I — Mobile Viewport + Visual Regression + GitHub OAuth [implemented]

**Scope:**
1. Mobile viewport emulation — Playwright device emulation (iPhone, Pixel, iPad) for mobile web testing
2. Visual regression runner — `toHaveScreenshot()` baseline capture + pixel diff comparison
3. GitHub OAuth runner — dedicated test account auth capability planner and smoke runner

**What Phase 5I IS:**
- Testing mobile web layouts with Playwright's built-in device emulation (not Appium — that is planned for Phase 5K)
- Capturing visual baseline screenshots and comparing against them to detect regressions
- GitHub test-account storageState capture + reuse smoke (dedicated test accounts only)
- Amazon/Alza mobile readonly profiles (same path-gate + selector-scan as Phase 5H)
- GitHub OAuth: `manual_storage_state_capture` + `storage_state_reuse` executable in Phase 5I

**What Phase 5I is NOT:**
- Not native mobile app testing (Appium/Maestro are planned for Phase 5K — not implemented here)
- Not Amazon/Alza mobile auth or checkout flows (always blocked)
- Not personal or production GitHub account auth (always blocked)
- Not GitHub API token flows or GitHub Apps (planning-only in Phase 5I)
- Not Microsoft OAuth (planning-only in Phase 5I — deferred to next phase)
- Not CAPTCHA or anti-bot bypass (always blocked)
- Not generating client delivery packages

**Allowed Actions:**
- Run `tools/run_mobile_viewport_smoke.py` with `--approve-mobile-execution`
- Run `tools/run_visual_regression.py` with `--approve-visual-regression`
- Run `tools/run_github_auth_smoke.py` with `--approve-github-test-account --dedicated-test-account-confirmed`
- Read baseline screenshots to verify visual comparison is working
- Plan Microsoft OAuth runner (deferred — not yet implemented)

**Blocked Actions:**
- Mobile auth, checkout, cart, account flows on any ecommerce site
- Personal GitHub accounts (hardcoded block, cannot be overridden)
- Production GitHub org accounts (hardcoded block)
- CAPTCHA or anti-bot bypass (hardcoded block)
- Raw secrets via CLI flags or in any artifact
- Committing storageState, baselines, or runtime-generated scripts
- Client delivery without human review

**Acceptance Criteria:**
- `tools/run_mobile_viewport_smoke.py` generates artifacts in `17_mobile_viewport/`
- `tools/run_visual_regression.py` generates artifacts in `18_visual_regression/`
- `tools/run_github_auth_smoke.py` generates artifacts in `19_github_auth/`
- All new schemas: `safe_to_deliver=False`, `human_review_required=True` hardcoded in `__post_init__` AND `from_dict`
- Amazon/Alza mobile readonly: same blocked paths as desktop profiles
- GitHub: `personal_account_always_blocked=True`, `production_account_always_blocked=True` hardcoded
- ruff: clean; pytest: 1665 passed

**Safety invariants (all hardcoded, cannot be bypassed):**
- `MobileViewportExecutionReport`: `credentials_used=False`, `auth_performed=False`, `safe_to_deliver=False`, `approved_for_client_delivery=False`, `human_review_required=True`
- `VisualRegressionReport`: `credentials_used=False`, `auth_performed=False`, `safe_to_deliver=False`, `approved_for_client_delivery=False`, `human_review_required=True`, `baselines_committed=False`
- `GitHubAuthCapability`: `personal_account_always_blocked=True`, `production_account_always_blocked=True`, `captcha_bypass_allowed=False`, `raw_secrets_allowed=False`, `storage_state_content_read=False`, `client_delivery_allowed=False`
- `GitHubAuthEvidenceReport`: `cookies_logged=False`, `tokens_logged=False`, `storage_state_content_read=False`, `safe_to_deliver=False`, `human_review_required=True`

---

---

## Phase 5J-R — E2E Pipeline Hardening + Demo Workflows [implemented]

**Scope:**
1. `stop_on_first_failure` — pipeline stops after the first failed or blocked module (new flag)
2. `stopped_early` field on `PipelineRunReport` — records whether the pipeline was cut short
3. qa_report-only note — `plan()` warns when qa_report is the only enabled module (no source artifacts)
4. Demo pipeline runner (`tools/run_demo_pipeline.py`) — pre-configured for Restful Booker + SauceDemo

**What Phase 5J-R IS:**
- Hardening of `E2EPipelineRunner.run()` with an optional `stop_on_first_failure` parameter
- A pre-configured demo CLI that requires no module config — safe public targets are built in
- 54 new integration tests targeting the hardened runner and demo workflows

**What Phase 5J-R is NOT:**
- Not changing the fixed execution order (still hardcoded)
- Not adding new modules or new safety-gate types
- Not real network-connected integration tests (demo tests run in plan mode or via `_run_module` mocking)

**Acceptance Criteria:**
- `--stop-on-failure` flag in `run_e2e_pipeline.py` and `run_demo_pipeline.py`
- `PipelineRunReport.stopped_early` set correctly when stop_on_first_failure triggers
- `plan()` adds note when qa_report is the only enabled module
- `tools/run_demo_pipeline.py` exits 0 in plan mode; blocked flags exit 2
- ruff: clean; pytest: 1832 passed

---

## Phase 5J — E2E Pipeline Runner + DB Smoke [implemented]

**Scope:**
1. E2E Pipeline Runner — subprocess orchestration layer that runs all enabled Phase 5x CLI tools in a fixed, safe sequence
2. DB Smoke Runner — read-only database connectivity smoke for PostgreSQL, MySQL, and MongoDB

**What Phase 5J IS:**
- A subprocess orchestration layer (`E2EPipelineRunner`) that calls existing Phase CLI tools in a hardcoded order: `task_source → browser → api_smoke → google_auth → github_auth → mobile_viewport → visual_regression → db_smoke → qa_report`
- Read-only database smoke: `SELECT`/`SHOW`/`DESCRIBE`/`EXPLAIN` for SQL; `find`/`aggregate`/`count`/etc. for MongoDB
- Connection string accepted via env var NAME only — raw URLs blocked at CLI and runner level
- Row limit enforced: default 10, max 100 (hard cap)
- DB drivers (psycopg2, mysql-connector-python, pymongo) are optional — missing driver produces a `blocked` result with install instructions
- Planning-only mode: `E2EPipelineRunner.plan()` builds an execution plan without calling any subprocess

**What Phase 5J is NOT:**
- Not replacing `QAFactoryOrchestrator` (AI/LLM workflow engine)
- Not replacing `WorkbenchController` (Phase 2A intake + artifact writing)
- Not replacing `EvidenceManager` (Phase 4B evidence registration)
- Not a write-capable database runner — INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/EXEC and all destructive operations are permanently blocked
- Not a general pipeline scheduler or CI/CD system
- Not producing client delivery packages (`client_delivery_allowed=False` hardcoded)

**Allowed Actions:**
- Run `tools/run_e2e_pipeline.py` with `--approve-pipeline-execution`
- Run `tools/run_db_smoke.py` with `--approve-db-smoke`
- Build and inspect execution plan without `--approve-pipeline-execution` (plan-only mode)
- Pass DB connection string via env var name (e.g. `--db-url-env-var STAGING_DATABASE_URL`)

**Blocked Actions:**
- Raw connection strings, passwords, or tokens via any CLI flag
- Any SQL other than SELECT/SHOW/DESCRIBE/EXPLAIN
- Any MongoDB operation not in the allowed list
- Destructive DB operations (INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE etc.)
- Reordering the pipeline execution sequence
- Client delivery without human review
- Committing `outputs/` artifacts

**Acceptance Criteria:**
- `tools/run_e2e_pipeline.py` generates artifacts in `20_e2e_pipeline/`
- `tools/run_db_smoke.py` generates artifacts in `21_db_smoke/`
- All new schemas: `safe_to_deliver=False`, `human_review_required=True` hardcoded in `__post_init__` AND `from_dict`
- `PipelineRunReport`: `raw_secrets_allowed=False`, `production_write_allowed=False`, `client_delivery_allowed=False` hardcoded
- `DBSmokeReport`: `destructive_db_actions_allowed=False`, `connection_string_logged=False` hardcoded
- Blocked flags (`--password`, `--token`, `--secret`, `--api-key`, `--cookie`, `--db-url`, etc.) reject immediately with exit code 2
- ruff: clean; pytest: 1778 passed

**Safety invariants (all hardcoded, cannot be bypassed):**
- `PipelineRunReport`: `raw_secrets_allowed=False`, `production_write_allowed=False`, `client_delivery_allowed=False`, `safe_to_deliver=False`, `human_review_required=True`
- `DBSmokeReport`: `raw_secrets_allowed=False`, `production_write_allowed=False`, `destructive_db_actions_allowed=False`, `client_delivery_allowed=False`, `human_review_required=True`, `connection_string_logged=False`
- SQL safety: word-boundary regex blocks all destructive keywords even inside subqueries
- MongoDB safety: operation allowlist enforced before any driver connection attempt

---

## Phase 5K — AI Intelligence Core [implemented]

**What Phase 5K IS:**
- `IntakeAgent` — heuristic classifier: classifies work requests into test type, risk level,
  and recommended pipeline modules. Raw input text is **never** stored in any artifact.
- `TestOracle` — scenario generator: produces prioritized test scenarios from an `IntakeReport`
  or a classification string. Defers performance/security to Phase 5N.
- `EvidenceIntelligence` — static gap analyzer: reads existing artifact directories and
  computes a coverage score with severity-ranked gaps and recommendations. No subprocess,
  no network calls.
- Three CLI tools: `run_intake_agent.py`, `run_test_oracle.py`, `run_evidence_intelligence.py`
- Three artifact directories: `22_intake/`, `23_test_oracle/`, `24_evidence_intelligence/`

**What Phase 5K is NOT:**
- Not an LLM integration (heuristic-only in Phase 5K; LLM mode planned for a later phase)
- Not a test executor — all outputs are planning artifacts (`executable_without_approval=False`)
- Not a replacement for `QAFactoryOrchestrator`, `WorkbenchController`, or `EvidenceManager`
- Not a credentials store — no tokens, passwords, or secrets accepted via CLI or stored in artifacts

**Allowed Actions:**
- Heuristic keyword scoring against a fixed vocabulary
- Reading existing `outputs/<project_id>/` artifact directories (filesystem only)
- Writing JSON + Markdown planning artifacts to `22_intake/`, `23_test_oracle/`, `24_evidence_intelligence/`

**Blocked Actions:**
- Storing raw input text in any artifact
- LLM/API calls (deferred)
- subprocess, network, or DB calls from any Phase 5K runner
- Accepting credentials via CLI flags

**Acceptance Criteria:**
- `tools/run_intake_agent.py` generates artifacts in `22_intake/`
- `tools/run_test_oracle.py` generates artifacts in `23_test_oracle/`
- `tools/run_evidence_intelligence.py` generates artifacts in `24_evidence_intelligence/`
- `IntakeReport.raw_input_stored=False` hardcoded in `__post_init__` AND `from_dict`
- `IntakeReport.credentials_in_output=False` hardcoded in `__post_init__` AND `from_dict`
- All three report schemas: `safe_to_deliver=False`, `human_review_required=True` hardcoded
- `TestOracleReport.executable_without_approval=False` hardcoded in `__post_init__` AND `from_dict`
- `EvidenceIntelligenceReport.network_calls_made=False`, `execution_performed=False` hardcoded
- Blocked flags (`--password`, `--token`, etc.) reject immediately with exit code 2
- ruff: clean; pytest: 1931 passed

**Safety invariants (all hardcoded, cannot be bypassed):**
- `IntakeReport`: `raw_input_stored=False`, `credentials_in_output=False`, `safe_to_deliver=False`, `human_review_required=True`
- `TestOracleReport`: `raw_input_stored=False`, `executable_without_approval=False`, `safe_to_deliver=False`, `human_review_required=True`
- `EvidenceIntelligenceReport`: `network_calls_made=False`, `execution_performed=False`, `safe_to_deliver=False`, `human_review_required=True`

---

## Phase 5L — Desktop Browser Execution CLI [implemented]

**What Phase 5L IS:**
- `tools/run_browser_execution.py` — approval-gated CLI for desktop Playwright smoke execution
- Wraps `core/browser_execution_runner.py` with a hardened, flag-checked entry point
- Supports `list`, `smoke`, and `readonly_smoke` command modes
- Dual-approval model for `ecommerce_public_readonly` targets (Amazon, Alza): requires
  both `--approve-demo-execution` AND `--approve-public-readonly-execution` simultaneously
- Generates `playwright-report/index.html` + screenshots/videos/traces on failure
- Smoke test scaffold: `outputs/<project_id>/03_framework/playwright/tests/smoke/`
  with desktop + mobile spec files that skip gracefully on wrong viewport

**What Phase 5L is NOT:**
- Not a test generator — spec files are hand-authored or scaffold-generated artifacts
- Not a CI/CD runner — designed for local controlled execution under human oversight
- Not an auth flow runner — no credentials, no login, no storageState
- Not a CAPTCHA/anti-bot bypass tool — `captcha_bypass_allowed=False` hardcoded

**Allowed Actions:**
- Running `npx playwright test` with headless Chromium against public read-only URLs
- Writing `playwright-report/`, `test-results/` under the scaffold root
- Writing execution plan artifacts under `outputs/<project_id>/`

**Blocked Actions:**
- Accepting credentials via CLI flags (`--password`, `--token`, `--secret`, etc.)
- CAPTCHA bypass or anti-bot bypass (hardcoded False)
- Checkout, payment, form submission, or any write action against the target site
- Running with personal or production accounts
- Running ecommerce targets without both approval flags

**Acceptance Criteria:**
- `tools/run_browser_execution.py` exists and is importable
- Blocked flags exit with code 2 before any other action
- `ecommerce_public_readonly` targets blocked unless both `approve_demo=True` AND
  `approve_public_readonly=True` are set
- `playwright.config.cjs` generates screenshots/videos/traces on failure
- Desktop spec files skip mobile-specific assertions (and vice versa) via `test.skip()`
- `tsconfig.json` uses `noEmit: true`, `rootDir: "."`, `lib: ["ES2020", "DOM"]`
- pytest: 35 Phase 5L tests pass; Playwright: 23 passed, 7 skipped (dual-viewport suite)

**Safety invariants (all hardcoded, cannot be bypassed):**
- `captcha_bypass_allowed=False`
- `anti_bot_bypass_allowed=False`
- `personal_accounts_blocked=True`
- `production_accounts_blocked=True`
- No credentials accepted or stored in any artifact

---

## Phase 5M — API Contract Importer + CI/CD Builder [implemented]

**What Phase 5M IS:**
- `APIContractImporter` — parses OpenAPI JSON/YAML and Postman collections into a
  classified `APIContractReport` with per-endpoint safety levels (safe_readonly /
  requires_approval / blocked_by_default)
- `APITestGenerator` — generates Playwright API test skeleton files from a contract
  report. Only safe_readonly endpoints get active stubs. All output is planning-only.
- `CICDBuilder` — generates GitHub Actions and GitLab CI workflow files for running
  Playwright smoke tests. All configs are planning artifacts — not auto-committed.
- Three CLI tools: `import_api_contract.py`, `generate_api_tests.py`, `build_cicd_config.py`
- Three artifact dirs: `25_api_contract/`, `26_generated_tests/`, `27_cicd/`

**What Phase 5M is NOT:**
- Not a live API tester — no network calls during import or generation
- Not a code committer — generated CI configs must be copied manually
- Not a test executor — all generated specs have `executable_without_approval=False`
- Not a credential store — no tokens, API keys, or secrets accepted via CLI flags

**Allowed Actions:**
- Reading local spec files (JSON/YAML/Postman) from the local filesystem
- Writing planning artifacts to `25_api_contract/`, `26_generated_tests/`, `27_cicd/`
- Generating TypeScript test file skeletons and YAML CI configs

**Blocked Actions:**
- Network calls to fetch specs from URLs
- Accepting credential flags (`--password`, `--token`, `--secret`, etc.)
- Auto-executing generated tests
- Auto-committing or pushing generated CI configs to any repository
- Embedding secrets in generated workflow files

**Acceptance Criteria:**
- `APIContractReport.raw_secrets_allowed=False`, `destructive_api_calls_allowed=False`,
  `production_write_allowed=False`, `human_review_required=True` hardcoded in `__post_init__` AND `from_dict`
- `GeneratedTestsReport.executable_without_approval=False` hardcoded in `__post_init__` AND `from_dict`
- `CICDConfig.auto_pr_creation_allowed=False`, `client_repo_writeback_allowed=False`,
  `production_deploy_allowed=False` hardcoded in `__post_init__` AND `from_dict`
- Blocked flags exit with code 2 before any parsing
- ruff: clean; pytest: 2067 passed (101 new Phase 5M tests)

**Safety invariants (all hardcoded, cannot be bypassed):**
- `APIContractReport`: `raw_secrets_allowed=False`, `destructive_api_calls_allowed=False`, `production_write_allowed=False`, `human_review_required=True`, `client_delivery_allowed=False`
- `GeneratedTestsReport`: `executable_without_approval=False`, `raw_secrets_allowed=False`, `human_review_required=True`, `client_delivery_allowed=False`
- `CICDConfig/CICDManifest`: `auto_pr_creation_allowed=False`, `client_repo_writeback_allowed=False`, `production_deploy_allowed=False`, `human_review_required=True`

---

## Phase 5P — Client Delivery Pack `[implemented]`

**Purpose:** Aggregate outputs from all previous phases into a clean, client-ready
delivery package. Generate structured reports, run a secret scan, create a ZIP archive.

**Input artifacts:** `outputs/<project_id>/14_qa_report/`, `25_api_contract/`,
`26_generated_tests/`, `27_cicd/` (all optional — graceful degradation if missing)

**Output artifacts** (`outputs/<project_id>/28_client_delivery/`):
- `QA_Report.md` / `QA_Report.html` — 11-section client QA report
- `Bug_Report.md` — defect report template
- `Test_Cases.csv` — structured test case list
- `Risk_Matrix.md` — risk matrix with severity and mitigation
- `Recommendations.md` — automation and CI/CD recommendations
- `Evidence_Index.md` — evidence artifact index
- `Delivery_Checklist.md` — pre-delivery checklist (all items unchecked by default)
- `client_delivery_manifest.json` — manifest with safety flags and secret scan result
- `client_delivery.zip` — ZIP of all artifacts (blocked files excluded)

**Allowed Actions:**
- Reading outputs from `outputs/<project_id>/` subdirectories
- Generating report content from available data (placeholder when data missing)
- Running secret filename scan on delivery directory
- Creating ZIP archive (excluding blocked filenames)

**Blocked Actions:**
- Auto-approving delivery (`approved_for_client_delivery` always `False`)
- Sending to client automatically (`auto_send_to_client` always `False`)
- Skipping secret scan (`secret_scan_before_delivery` always `True`)
- Including storageState, .env, credentials, cookies, tokens in ZIP

**Acceptance Criteria:**
- All 9 artifact files generated + manifest + ZIP = 10 total artifacts
- `client_delivery_manifest.json` contains `approved_for_client_delivery=False`,
  `human_review_required=True`, `secret_scan_before_delivery=True`
- Secret scan result in manifest with `scan_passed=True` for clean output
- ZIP contains all main artifacts, excludes ZIP itself and blocked filenames
- Blocked CLI flags (`--approve`, `--auto-send`, `--skip-secret-scan`) exit with code 1
- ruff: clean; pytest: 2226 passed (108 new Phase 5P tests)

**Safety invariants (all hardcoded in `__post_init__`):**
- `ClientDeliveryManifest`: `approved_for_client_delivery=False`, `human_review_required=True`,
  `auto_send_to_client=False`, `secret_scan_before_delivery=True`, `raw_secrets_included=False`
- `SecretScanResult`: `scan_passed` recomputed from `blocked_files` — cannot be injected

---

## Phase 5M-R — Real Demo Workflow + Hardening `[implemented]`

**Purpose:** Validate the full Phase 5M pipeline against real fixture specs covering all
safety classification levels. Harden edge cases (DELETE always blocked, PyYAML error messages,
smoke exclusion of blocked endpoints, CI/CD content invariants).

**Input artifacts:**
- `fixtures/demo_specs/petstore_openapi.json` — OpenAPI 3.0 JSON with GET/POST/PUT/HEAD/OPTIONS
- `fixtures/demo_specs/sample_openapi.yaml` — OpenAPI 3.0 YAML with GET/POST/PATCH
- `fixtures/demo_specs/risky_api_openapi.json` — OpenAPI with DELETE/payment/admin/refund endpoints
- `fixtures/demo_specs/postman_sample.json` — Postman v2.1 collection

**Output artifacts:**
- `tests/test_phase5mr_demo_workflow.py` — 51 end-to-end demo workflow tests

**Pipeline validated:** `fixtures/demo_specs/` → `APIContractImporter` → `APITestGenerator` → `CICDBuilder`

**Allowed Actions:**
- Parse local fixture files (no network calls)
- Classify all endpoints before test generation
- Generate smoke/schema/negative content from fixture reports
- Write artifacts to `tmp_path` in pytest fixtures

**Blocked Actions:**
- Network calls to fetch specs from external URLs
- Auto-executing generated tests
- Modifying production CI/CD configuration

**Acceptance Criteria:**
- DELETE method always classified `blocked_by_default` regardless of path
- `POST /payments/charge` classified `blocked_by_default`; `GET /health` classified `safe_readonly`
- Smoke content never includes active `test()` blocks for DELETE or `charge` paths
- CI/CD workflow content contains no passwords, API keys, deploy steps, git push, or PR creation
- ruff: clean; pytest: 2118 passed (51 new Phase 5M-R tests)

**Key fixes applied:**
- `classify_endpoint`: DELETE checked first — always `blocked_by_default`
- PyYAML ImportError message: "YAML parsing requires pyyaml. Install with: pip install pyyaml"

---

## Phase 5N — Accessibility + Performance + Passive Security `[implemented]`

**Modules:**
- `core/accessibility_runner.py` — axe-core Playwright skeleton generator + approved execution
- `core/performance_smoke_runner.py` — CDP timing skeleton generator + approved execution
- `core/passive_security_runner.py` — OWASP header skeleton + real HEAD request (approved)
- `core/schemas/accessibility.py` — `AccessibilityReport`, `AccessibilityViolation`
- `core/schemas/performance_smoke.py` — `PerformanceSmokeReport`, `PerformanceThreshold`
- `core/schemas/passive_security.py` — `PassiveSecurityReport`, `SecurityHeaderCheck`
- `tools/run_accessibility_smoke.py` — CLI
- `tools/run_performance_smoke.py` — CLI
- `tools/run_passive_security_smoke.py` — CLI
- `tests/test_phase5n_accessibility.py` — 58 tests
- `tests/test_phase5n_performance_smoke.py` — 58 tests
- `tests/test_phase5n_passive_security.py` — 58 tests

**Execution model (hybrid):**
- Default mode: skeleton generator — Playwright TypeScript spec + planning report, no network
- Approved execution: `--execute` + approval flags — approved execution path per module
- Passive security only: real urllib HEAD request (truly passive, no browser needed)
- Accessibility/performance: spec generated, execution via `npx playwright test` (manual)

**Status field distinguishes:**
- `planning_only` — skeleton generated, no execution (default, delivery shows "Generated checks only")
- `executed` — checks were actually performed
- `partial` — some checks ran, some skipped

**Safety invariants (all hardcoded in `__post_init__`):**
- `read_only=True`
- `active_scan_allowed=False`
- `exploit_attempts_allowed=False`
- `auth_bypass_allowed=False` (passive security)
- `destructive_actions_allowed=False` (passive security)
- `load_testing_allowed=False` (performance)
- `production_write_allowed=False` (performance)
- `human_review_required=True`

**Artifact directories:**
- `outputs/<id>/29_accessibility/` — accessibility spec + report + summary + violations CSV
- `outputs/<id>/30_performance/` — performance spec + report + summary + slow_resources.json
- `outputs/<id>/31_passive_security/` — security spec + report + summary + security_headers.json

**Client Delivery Pack integration:**
- `_collect_source_data` reads 29/30/31 dirs and status fields
- QA report table shows "Generated checks only; execution requires approval" for `planning_only`
- Evidence Index notes execution status for each 5N module

**Quality gates:**
- ruff: clean; pytest: 2472 passed (174 new Phase 5N tests)

---

## Phase 5N-R — Quality Audit Demo + Delivery Pack Integration `[implemented]`

**Purpose:** Validates Phase 5N end-to-end with a realistic demo project and proves that
Accessibility, Performance, and Passive Security results are correctly represented in the
Client Delivery Pack.

**Demo project ID:** `demo_quality_audit`

**Fixture layout (`fixtures/demo_quality_audit/`):**
- `29_accessibility/` — 4 files, status `planning_only` (axe-core spec + report + summary + CSV)
- `30_performance/` — 4 files, status `planning_only` (CDP timing spec + report + summary + slow_resources)
- `31_passive_security/` — 4 files, status `executed` (3/5 OWASP headers present, CSP+Referrer-Policy missing)

**Tests (`tests/test_phase5nr_quality_audit_delivery.py`, 96 tests):**
- `TestDemoFixtureIntegrity` — all 12 fixture files exist, JSON valid, safety flags intact
- `TestPlanningOnlyMode` — runners produce `planning_only` with no-network artifacts
- `TestApprovedExecutionMode` — passive security with mocked HEAD returns `executed`; accessibility/performance blocked without dual-flag
- `TestDeliveryPackIntegration5N` — QA report includes Accessibility/Performance/Passive Security rows; evidence index refs 29/30/31; `executed` shows "Executed", `planning_only` shows "Generated checks only; execution requires approval"
- `TestZIPSafety5N` — ZIP excludes storageState/.env/token/authSession/credentials; includes QA_Report/Evidence_Index
- `TestGoldenContent5N` — report human-readable, no credentials, draft notice, approved=false stated

**Quality gates:** ruff clean; pytest 2568 passed (96 new Phase 5N-R tests)

---

## Phase 5O — Self-Healing + Flaky Test Analyzer `[implemented]`

**Purpose:** Static analysis of Playwright spec files to detect flakiness patterns, classify selector stability, and generate self-healing proposals. No browser, no network, no auto-apply.

**Allowed actions:**
- Read Playwright spec files (`*.spec.ts`) from configured paths or auto-discovered in `outputs_root`
- Regex-based pattern matching for flakiness risks (hard waits, fragile selectors, race-prone patterns)
- Generate selector stability scores (0–100)
- Write JSON + Markdown reports to `outputs/<id>/32_flaky_test_analyzer/`
- Insert TODO comment proposals when `--apply-proposals --approve-code-modification` both provided

**Blocked actions:**
- `--auto-fix` — always blocked
- `--skip-human-review` — always blocked
- `--approve-delivery` — always blocked
- `--force-apply` — always blocked
- Applying proposals without `--approve-code-modification` flag

**Safety invariants (hardcoded in `__post_init__` + `from_dict`):**
- `read_only=True`
- `auto_apply_changes=False`
- `code_modification_allowed=False`
- `production_write_allowed=False`
- `human_review_required=True`

**Artifacts produced:** `outputs/<id>/32_flaky_test_analyzer/`
- `flaky_test_analysis.json` + `Flaky_Test_Analysis_Report.md`
- `selector_stability.json` + `Selector_Stability_Report.md`
- `self_healing_proposals.json` + `Self_Healing_Proposals.md`

**Acceptance criteria:**
- `analyze()` detects hard waits, fragile selectors, non-web-first assertions in flaky spec fixture
- `analyze_selectors()` returns `stability_score >= 70` for stable spec, `< 70` for flaky spec
- `generate_healing_proposals()` produces proposals with `applied=False`, status=`proposal_generated`
- `apply_proposals()` raises `ValueError` without `approve_code_modification=True`
- All safety invariant injection blocked via `from_dict()`
- CLI blocked flags exit 1 with `[BLOCKED]` in stderr
- `--no-write` produces no files on disk

**Quality gates:** ruff clean; pytest 2643 passed (75 new Phase 5O tests)

---

## Phase 6 — QA Factory as MCP Server `[implemented]`

**Purpose:** Expose QA Factory capabilities as a Model Context Protocol (MCP) server. Thin adapter layer over existing core modules — no business logic in the MCP layer.

**Architecture:**
- `integrations/mcp/tool_handlers.py` — Pure Python handler functions, testable without mcp package
- `integrations/mcp/server.py` — MCP server wrapper (requires: `pip install mcp`)
- `tools/run_mcp_server.py` — CLI entry point

**7 MCP tools registered:**
| Tool | Description |
|---|---|
| `qa_factory_health` | Health, version, safety mode — no network |
| `analyze_project` | Classify project directory, return recommendations |
| `run_quality_audit` | Accessibility + Performance + Passive security (planning_only default) |
| `run_flaky_test_analysis` | Static flaky analysis on Playwright spec files |
| `generate_delivery_pack` | Build client delivery pack with secret scan + ZIP |
| `propose_self_healing_fixes` | Generate proposals — no code changes |
| `apply_self_healing_fixes` | Apply TODO comments; requires `approve_code_modification=true` + `dry_run=false` |

**Allowed actions:**
- Call any tool handler with no credentials in params
- Start MCP server over stdio with `python tools/run_mcp_server.py`
- `--list-tools`, `--version`, `--demo-health` CLI flags

**Blocked actions:**
- `--approve-delivery` — always blocked
- `--skip-review` — always blocked
- `--auto-start-browser` — always blocked
- `--credentials` — always blocked
- Passing credential/password/token/api_key/secret as any tool parameter

**Safety invariants (enforced in tool_handlers.py):**
- All tools default to `planning_only` / `analysis_only` (no network, no browser)
- `network_by_default=False`, `browser_by_default=False`, `auto_apply_changes=False`
- `human_review_required=True` in every response
- `approved_for_client_delivery=False` always in delivery tool
- `code_modification_allowed=False` in analysis/proposal tools
- Blocked params (`credential`, `password`, `token`, `api_key`, `secret`, `private_key`) raise `ValueError`

**Acceptance criteria:**
- All 7 tools callable without mcp package (via tool_handlers directly)
- Default mode returns `planning_only` / `analysis_only` status
- Network requires `approve_public_readonly_execution=True`
- Apply fixes requires `approve_code_modification=True`
- Dry run is default for `apply_self_healing_fixes`
- All responses have `status` and `human_review_required` fields
- No credentials in any response JSON
- CLI blocked flags exit 1 with `[BLOCKED]` in stderr

**Quality gates:** ruff clean; pytest 2738 passed (95 new Phase 6 tests)

---

## Phase 6-R — MCP Demo Workflow Validation `[implemented]`

**Purpose:** Validate all 7 MCP tool handlers end-to-end via a real demo workflow on demo_quality_audit fixtures. Proves the full QA Factory flow: health → analyze → audit → flaky → proposals → delivery pack → blocked apply.

**New artifacts:**
- `tools/run_mcp_demo_workflow.py` — 7-step demo runner CLI
- `tests/test_phase6r_mcp_demo_workflow.py` — 49 end-to-end tests

**Allowed actions:**
- Run demo workflow in dry-run or write mode
- Inspect all 7 tool results in JSON via `--json-output`
- Write artifacts to `outputs/<project-id>/` when `--no-write` is not set

**Blocked actions:**
- `--approve-delivery` — always blocked (exit 1)
- `--skip-review` — always blocked (exit 1)
- `--force-apply` — always blocked (exit 1)
- No credentials or live network calls in demo mode

**Safety invariants validated by demo:**
- All 7 tools return `human_review_required=True`
- `apply_self_healing_fixes` returns `blocked` without `approve_code_modification`
- `generate_delivery_pack` returns `approved_for_client_delivery=False`
- Spec files are not modified during blocked apply
- No credentials appear in any tool response JSON

**Acceptance criteria:**
- All 7 tools appear in results dict
- All statuses honest: `healthy`, `analysis_only`, `planning_only`, `proposal_generated`, `draft`, `blocked`
- ZIP excludes storagestate, .env, credential, token
- QA_Report.md has no credentials
- All CLI tests pass on Windows (ASCII-only output, no Unicode encoding errors)

**Quality gates:** ruff clean; pytest 2787 passed (49 new Phase 6-R tests)

---

## Related Documents

- [`AGENT_CONTRACT.md`](AGENT_CONTRACT.md) — agent operating rules
- [`ARTIFACT_CONTRACTS.md`](ARTIFACT_CONTRACTS.md) — artifact paths and ownership
- [`AGENT_HANDOFF_TEMPLATE.md`](AGENT_HANDOFF_TEMPLATE.md) — final report template
- [`SAFETY_RULES.md`](SAFETY_RULES.md) — non-negotiable safety rules
- [`COMMANDS.md`](COMMANDS.md) — CLI reference
