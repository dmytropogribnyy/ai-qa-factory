# Phase Contracts — Guided QA Automation Workbench

**Version:** 5.9.0
**Updated:** 2026-05-26
**Phase:** 5J

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

## Related Documents

- [`AGENT_CONTRACT.md`](AGENT_CONTRACT.md) — agent operating rules
- [`ARTIFACT_CONTRACTS.md`](ARTIFACT_CONTRACTS.md) — artifact paths and ownership
- [`AGENT_HANDOFF_TEMPLATE.md`](AGENT_HANDOFF_TEMPLATE.md) — final report template
- [`SAFETY_RULES.md`](SAFETY_RULES.md) — non-negotiable safety rules
- [`COMMANDS.md`](COMMANDS.md) — CLI reference
