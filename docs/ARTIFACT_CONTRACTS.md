# Artifact Contracts — Guided QA Automation Workbench

**Version:** 5.9.0
**Updated:** 2026-05-26
**Phase:** 5J

This document defines the stable artifact paths, formats, and ownership rules for all
workbench-generated files. Agents and scripts should use these paths and respect the
ownership boundaries described here.

---

## Core Principle

```
outputs/                  ← runtime artifacts — always gitignored, never committed
core/                     ← source code — committed
tests/                    ← Workbench self-tests — committed
docs/                     ← governance docs — committed
```

**`repository tests/` is reserved exclusively for Workbench self-tests.**
It must never contain generated client test specs, Playwright specs, or project-specific
test files. Those belong under `outputs/<project_id>/03_framework/` (Phase 3A+).

---

## Artifact Ownership

| Artifact type | Location | Committed? | Agent may create? |
|---|---|---|---|
| Generated project artifacts | `outputs/<project_id>/` | No — gitignored | Yes |
| Playwright/pytest framework | `outputs/<project_id>/03_framework/` | No — gitignored | Phase 3A+ |
| Workbench self-tests | `tests/` | Yes | Yes (in phase scope) |
| Schema modules | `core/schemas/` | Yes | Yes (in phase scope) |
| Runtime modules | `core/*.py` | Yes | Yes (in phase scope) |
| Governance docs | `docs/` | Yes | Yes (in phase scope) |
| Audit reports | `outputs/docs_audit/`, `outputs/agent_audit/` | No — gitignored | Yes |

---

## Phase 2A/2B Artifact Layout

All Phase 2A and 2B artifacts are written to:

```
outputs/<project_id>/00_project/
```

### Machine-readable (JSON) — source for agents

| File | Phase | Description |
|---|---|---|
| `INPUT_MAP.json` | 2A | All classified input sources with types, labels, approval status |
| `WORK_REQUEST.json` | 2A | Normalised intake record: title, summary, raw brief, platform, inputs |
| `TASK_CLASSIFICATION.json` | 2A | Task type, project type, confidence, signals, notes |
| `PROJECT_STATUS.json` | 2A | Current phase, overall status, next action, notes |
| `PROJECT_BLUEPRINT.json` | 2B | Full planning source-of-truth: type, environment, surfaces, risks, etc. |

When reading project state, prefer `.json` over `.md` for structured processing.

### Human-readable (Markdown) — companion files for review

| File | Phase | Description |
|---|---|---|
| `INPUT_MAP.md` | 2A | Formatted list of input sources |
| `WORK_REQUEST.md` | 2A | Formatted work request |
| `TASK_CLASSIFICATION.md` | 2A | Classification table and signals |
| `PROJECT_STATUS.md` | 2A | Status table and next action |
| `NEXT_SAFE_STEP.md` | 2A | Human-readable next action guidance |
| `PROJECT_BLUEPRINT.md` | 2B | Full planning overview |
| `ASSUMPTIONS.md` | 2B | Working assumptions for client confirmation |
| `MISSING_INFO.md` | 2B | Information needed before execution |
| `SAFE_NEXT_STEPS.md` | 2B | Planning-only actions safe to proceed |
| `BLOCKED_ACTIONS.md` | 2B | Actions blocked until approvals obtained |
| `INITIAL_QA_STRATEGY_OUTLINE.md` | 2B | Preliminary test layer guidance |

### Artifact contract guarantees (Phase 2A/2B)

- **No raw secrets** — all passwords, tokens, cookies, JWTs are replaced with
  `[REDACTED_*]` before writing
- **No execution claims** — artifacts explicitly state no execution has occurred
- **No invented data** — all values are derived from actual input text
- `PROJECT_BLUEPRINT.json` is the primary source for Phase 2C (Strategy Planner)
- `BLOCKED_ACTIONS.md` lists what requires approval before any execution

---

## Phase 2C Artifact Layout

Phase 2C artifacts are written to:

```
outputs/<project_id>/02_strategy/
```

### Machine-readable (JSON) — source for agents

| File | Description |
|---|---|
| `QA_STRATEGY.json` | Full `QAStrategy` schema: areas, risk matrix, test layers, tactical plan, decisions |
| `PROJECT_STATUS.json` | Updated project status reflecting strategy phase completion |

### Human-readable (Markdown) — for review

| File | Description |
|---|---|
| `QA_STRATEGY.md` | Strategy summary, project type, confidence, blocked actions |
| `TEST_SCOPE.md` | In-scope and out-of-scope areas, blocked areas, surfaces |
| `RISK_MATRIX.md` | Risk items with likelihood, impact, severity, mitigation |
| `TEST_LAYERS.md` | Recommended test layers with purpose, priority, examples |
| `TACTICAL_PLAN_OUTLINE.md` | Phase-ordered tactical planning sequence |
| `QUALITY_RUBRIC.md` | Quality criteria for this project type |
| `STRATEGY_DECISIONS.md` | Key strategy decisions with rationale and alternatives |
| `PROJECT_STATUS.md` | Updated project status |

### Artifact contract guarantees (Phase 2C)

- **No raw secrets** — inherited from Phase 2B; planner never introduces new secrets
- **No execution claims** — strategy artifacts describe what to test, not what was tested
- **`client_ready = False`** — all Phase 2C artifacts require human review before delivery
- **Blocked actions preserved** — anything blocked in Phase 2B remains blocked in strategy output
- **Required approvals preserved** — approval requirements from blueprint are carried forward

---

## Phase 3A Artifact Layout

Phase 3A artifacts are written to:

```
outputs/<project_id>/03_framework/playwright/
```

### Always-present files (17 minimum)

| File | Description |
|---|---|
| `package.json` | Node.js project definition with Playwright scripts |
| `tsconfig.json` | TypeScript compiler configuration |
| `playwright.config.ts` | Playwright test runner — reads `BASE_URL` from env |
| `.gitignore` | Ignores `node_modules/`, `test-results/`, `.env` |
| `.env.example` | Placeholder env vars — copy to `.env`, never commit `.env` |
| `README.md` | Scaffold overview, setup, approval requirements |
| `tests/smoke/smoke.spec.ts` | Smoke test placeholder |
| `tests/regression/regression-placeholder.spec.ts` | Regression placeholder (skipped) |
| `pages/BasePage.ts` | Base page object with shared helpers |
| `fixtures/test-fixtures.ts` | Playwright test fixtures |
| `utils/env.ts` | Safe env var reader with validation |
| `utils/test-data.ts` | Test data factory — no real credentials |
| `test-data/README.md` | Test data governance |
| `test-data/sample-users.example.json` | Sample user structure — placeholders only |
| `docs/TEST_STRATEGY.md` | Strategy summary from QAStrategy |
| `docs/HOW_TO_RUN.md` | Setup and run guide with approval checklist |
| `docs/SCAFFOLD_REVIEW_CHECKLIST.md` | Pre-execution safety checklist |

### Conditional files (per project type / strategy layers)

| File | Condition |
|---|---|
| `tests/auth/auth-placeholder.spec.ts` | auth layer, web_saas, auth_heavy |
| `pages/LoginPage.ts` | auth layer, web_saas, auth_heavy |
| `tests/api/api-placeholder.spec.ts` | api layer, api_backend, mixed_ui_api |
| `utils/api-client.ts` | api layer, api_backend, mixed_ui_api |
| `pages/DashboardPage.ts` | web_saas, admin_panel, ecommerce |
| `tests/ecommerce/checkout-placeholder.spec.ts` | ecommerce — blocked until sandbox approval |
| `tests/admin/admin-placeholder.spec.ts` | admin_panel — blocked until admin account approval |

### Metadata files (always written to scaffold root)

| File | Description |
|---|---|
| `FRAMEWORK_SCAFFOLD.json` | Full `FrameworkScaffold` schema — files, status, safety flags |
| `FRAMEWORK_SCAFFOLD.md` | Human-readable scaffold summary |

### Artifact contract guarantees (Phase 3A)

- **`execution_allowed = False`** — no test may be run without completing `SCAFFOLD_REVIEW_CHECKLIST.md`
- **`client_visible = False`** — scaffold is internal until explicitly approved for delivery
- **`requires_review = True`** — must be reviewed by a senior QA reviewer before any use
- **No raw secrets** — all credential references use `process.env.*` placeholders only
- **No hardcoded URLs** — all URLs are `process.env.BASE_URL` or `http://localhost:3000` placeholder
- **Auth spec skipped by default** — `test.skip` guard requires `TEST_USERNAME`/`TEST_PASSWORD`
- **API spec skipped by default** — `test.skip` guard requires `API_BASE_URL`
- **Checkout/admin specs blocked** — `test.skip(true, ...)` until sandbox/admin approval

---

## Phase 3B Artifact Layout

Phase 3B artifacts are written to the same scaffold root as Phase 3A:

```
outputs/<project_id>/03_framework/playwright/
```

### Validation artifacts (written by `python tools/validate_scaffold.py`)

| File | Description |
|---|---|
| `STATIC_VALIDATION_REPORT.json` | Full `ScaffoldValidationReport` schema — checks, blockers, warnings, safety flags |
| `STATIC_VALIDATION_REPORT.md` | Human-readable report with Safety Invariants section |
| `VALIDATION_PLAN.md` | Summary of static checks run and toolchain steps that would require approval |
| `LOCAL_VALIDATION_CHECKLIST.md` | Manual checklist of steps to complete before running any local command |
| `TOOLCHAIN_VALIDATION_PLAN.md` | Proposed toolchain commands requiring explicit human approval |

### Artifact contract guarantees (Phase 3B)

- **`execution_performed = False`** — validator never executes any code
- **`npm_performed = False`** — no npm commands run
- **`npx_performed = False`** — no npx commands run
- **`browser_performed = False`** — no browser launched
- **`external_calls_performed = False`** — no network access
- **`safe_to_execute_tests = False`** — static validation alone does not grant test execution permission
- **`approval_required = True`** — `ToolchainValidationPlan` always requires explicit approval
- **No secret echo** — artifact files describe secret detection results but never reproduce secret values

---

## Phase 3C Artifact Layout

Phase 3C artifacts are written to the same scaffold root as Phase 3A/3B:

```
outputs/<project_id>/03_framework/playwright/
```

### Toolchain validation artifacts (written by `python tools/validate_toolchain.py`)

| File | Description |
|---|---|
| `TOOLCHAIN_VALIDATION_REPORT.json` | Full `ToolchainValidationReport` schema — commands, safety invariants, blockers |
| `TOOLCHAIN_VALIDATION_REPORT.md` | Human-readable report with Safety Boundary section and next steps |
| `TOOLCHAIN_COMMAND_LOG.md` | Per-command stdout/stderr excerpts; no secret values reproduced |
| `TOOLCHAIN_APPROVAL_RECORD.md` | Approval state, approved/denied command lists, safety constraints |

### Artifact contract guarantees (Phase 3C)

- **`safe_to_execute_tests = False`** — toolchain validation alone never grants test execution permission
- **`browser_execution_performed = False`** — no browser launched under any circumstances
- **`external_url_used = False`** — no external URL contacted under any circumstances
- **`credentials_used = False`** — no credentials read or injected under any circumstances
- **`approval_required = True`** — `--approve-toolchain` flag must be provided to run any command
- **Without approval** — `validation_status="blocked"`, all commands `status="skipped"`, no subprocess runs
- **No secret echo** — `TOOLCHAIN_COMMAND_LOG.md` reproduces stdout/stderr excerpts but strips env-level secrets

---

## Phase 4ABC Artifact Layout

Phase 4ABC artifacts are written to new subdirectories:

```
outputs/<project_id>/
    04_execution_plan/   ← Execution approval checklist, readiness report, boundaries (Phase 4A)
    05_evidence/         ← Evidence manifest, quality gate, redaction report, summary (Phase 4B)
    06_client_draft/     ← Draft reports, delivery note, delivery preview, quality checklist (Phase 4C)
    99_internal/
        scenario_evaluation/  ← Scenario batch evaluation (Phase 4ABC)
```

### Phase 4A — Execution Plan artifacts

| File | Description |
|---|---|
| `EXECUTION_APPROVAL_CHECKLIST.json` | `ExecutionApprovalChecklist` schema — all `approved_for_*` flags False |
| `EXECUTION_APPROVAL_CHECKLIST.md` | Human-readable checklist with approval requirements |
| `EXECUTION_READINESS_REPORT.json` | `ExecutionReadinessReport` schema — blockers, required approvals |
| `EXECUTION_READINESS_REPORT.md` | Human-readable readiness report |
| `EVIDENCE_COLLECTION_PLAN.md` | Plan for future evidence collection after approved execution |
| `EXECUTION_BOUNDARIES.md` | What has/has not been done, what requires approval |

### Phase 4B — Evidence Foundation artifacts

| File | Description |
|---|---|
| `EVIDENCE_MANIFEST.json` | `EvidenceCollection` schema — all evidence records (`client_visible=False`) |
| `EVIDENCE_MANIFEST.md` | Human-readable evidence registry |
| `EVIDENCE_QUALITY_GATE.json` | `EvidenceQualityGate` schema (`approved_for_client_view=False`) |
| `EVIDENCE_QUALITY_GATE.md` | Human-readable quality gate |
| `EVIDENCE_REDACTION_REPORT.json` | `EvidenceRedactionReport` schema (`client_visible_blocked=True`) |
| `EVIDENCE_REDACTION_REPORT.md` | Human-readable redaction status |
| `INTERNAL_EVIDENCE_SUMMARY.md` | Internal evidence overview — not for client delivery |

### Phase 4C — Client Draft artifacts

| File | Description |
|---|---|
| `INTERNAL_QA_SUMMARY_DRAFT.json/.md` | Internal QA summary — not for client delivery |
| `CLIENT_REPORT_DRAFT.json/.md` | Client report — **DRAFT, not approved for delivery** |
| `DELIVERY_NOTE_DRAFT.json/.md` | Delivery note — **DRAFT, not approved for delivery** |
| `REPORT_QUALITY_CHECKLIST.json/.md` | Quality gate (`safe_to_deliver=False`) |
| `DELIVERY_PACKAGE_PREVIEW.json/.md` | Preview manifest (`package_created=False`, `zip_created=False`) |
| `DELIVERY_SAFETY_CHECKLIST.json/.md` | Safety gate (`safe_to_package=False`) |

### Phase 4ABC — Scenario Evaluation artifacts (99_internal)

| File | Description |
|---|---|
| `99_internal/scenario_evaluation/SCENARIO_BATCH_EVALUATION.json` | `ScenarioBatchEvaluationReport` schema (`external_calls_performed=False`) |
| `99_internal/scenario_evaluation/SCENARIO_BATCH_EVALUATION.md` | Human-readable evaluation — internal only |

### Artifact contract guarantees (Phase 4ABC)

- **`approved_for_execution=False`** — never set to True in Phase 4ABC
- **`approved_for_browser_execution=False`** — never set to True in Phase 4ABC
- **`approved_for_client_delivery=False`** — never set to True in Phase 4ABC
- **`client_visible=False`** — all evidence records are internal-only by default
- **`approved_for_client_view=False`** — quality gate not passed until human review
- **`safe_to_deliver=False`** — reports are draft-only
- **`safe_to_package=False`** — no delivery package created
- **`package_created=False`** — no zip/archive created
- **`zip_created=False`** — no zip/archive created
- **`external_calls_performed=False`** — scenario evaluation reads local fixtures only
- **`evaluation_performed_without_execution=True`** — scenario evaluation is static only
- **No raw secrets** — no credential values reproduced in any artifact
- **Client reports clearly marked DRAFT** — must state no browser execution occurred

---

## Full Artifact Layout (current state)

```
outputs/<project_id>/
    00_project/          ← Phase 2A/2B (implemented)
    01_approval/         ← Approval decisions and status (planned)
    02_strategy/         ← QA strategy, risk matrix, test scope (Phase 2C — implemented)
    03_framework/        ← Generated Playwright TypeScript framework (Phase 3A — implemented)
    04_execution_plan/   ← Execution readiness artifacts (Phase 4A — implemented)
    05_evidence/         ← Evidence foundation (Phase 4B — implemented)
    06_client_draft/     ← Draft reports, delivery preview (Phase 4C — implemented)
        packages/        ← Zipped delivery packages (require delivery approval — planned Phase 5A+)
    07_execution/        ← Controlled browser execution artifacts (Phase 4D — implemented)
    08_credentials/      ← Credential safety artifacts (Phase 4E — implemented)
    09_auth/             ← Demo auth execution artifacts (Phase 4F — implemented)
        .auth/           ← storageState (gitignored, internal-only, never committed)
    10_execution_matrix/ ← Scenario execution matrix and test account plan (Phase 4G — implemented)
    11_runtime_secrets/  ← Runtime secret routing plan and intake validation (Phase 5AB — implemented)
    12_dedicated_auth/   ← Dedicated test-account auth execution artifacts (Phase 5AB — implemented)
        .auth/           ← storageState (gitignored, internal-only, never committed)
    13_api_auth/         ← API auth execution artifacts (Phase 5E — implemented)
    14_qa_report/        ← QA Evidence Report (Phase 5F — implemented)
    15_google_auth/      ← Google/OAuth test-account capability (Phase 5G — implemented)
        .auth/           ← Google storageState (gitignored, internal-only, never committed)
        user-data-dir/   ← Optional dedicated Chrome profile dir (gitignored)
    16_task_source/      ← Linear task source fetch report + derived scenarios (Phase 5H — implemented)
    99_internal/         ← Internal notes, quality gate reports, debug logs
        scenario_evaluation/  ← Scenario batch evaluation (Phase 4ABC — implemented)
```

### Folder ownership rules

| Folder | Committed? | Client-visible? | Notes |
|---|---|---|---|
| `00_project/` | No | No (internal) | Planning artifacts |
| `01_approval/` | No | No | Approval records (planned) |
| `02_strategy/` | No | Prepared by agent, reviewed by human | Strategy docs |
| `03_framework/` | No | Delivered after review | Generated scaffold |
| `04_execution_plan/` | No | No | Readiness artifacts — internal |
| `05_evidence/` | No | Internal only by default | Evidence records (client_visible=False) |
| `06_client_draft/` | No | After human review only | DRAFT — not approved for delivery |
| `07_execution/` | No | Never — internal only | Browser execution approval, report, command log, evidence manifest |
| `08_credentials/` | No | Never — internal only | Credential policy, safety report, storageState policy, auth approval draft, sandbox classification, redaction checklist |
| `09_auth/` | No | Never — internal only | Auth execution approval, report, command log, session artifacts, redaction checklist |
| `09_auth/.auth/` | **Never committed** | Never | storageState (gitignored always) |
| `10_execution_matrix/` | No | Never — internal only | Scenario execution matrix, permission rules, target profiles, routing decisions, test account plan |
| `11_runtime_secrets/` | No | Never — internal only | Runtime secret routing plan, intake validation |
| `12_dedicated_auth/` | No | Never — internal only | Dedicated auth execution report, command log, session artifacts, safety boundary |
| `12_dedicated_auth/.auth/` | **Never committed** | Never | storageState (gitignored always) |
| `13_api_auth/` | No | Never — internal only | API auth execution report, command log, token check result, safety boundary |
| `14_qa_report/` | No | Never — internal only | QA Evidence Report, secret scan result, review checklist |
| `15_google_auth/` | No | Never — internal only | Google capability plan, storage-state policy, execution decision, evidence report, redaction checklist |
| `15_google_auth/.auth/` | **Never committed** | Never | Google storageState (gitignored always) |
| `15_google_auth/user-data-dir/` | **Never committed** | Never | Optional dedicated Chrome profile dir (gitignored) |
| `16_task_source/` | No | Never — internal only | Task source fetch report, derived scenarios, summary |
| `99_internal/` | No | Never | Internal quality gates, debug, scenario evaluation |

**`06_client_draft/` is never sent without completing `DELIVERY_SAFETY_CHECKLIST.md`.**
**`07_execution/` is always internal-only. Evidence remains `client_visible=False` until explicit future approval.**
**`08_credentials/` is always internal-only. All credential safety artifacts remain `client_visible=False`. Human redaction review required before any client-facing use.**
**`09_auth/` is always internal-only. Auth execution artifacts remain `client_visible=False`. storageState `approved_for_commit=False` always — must not be committed.**
**`10_execution_matrix/` is always internal-only. All planning artifacts remain `client_visible=False`. `safe_for_execution_now=False` always — this is planning only.**
**`11_runtime_secrets/` is always internal-only. Intake validation and routing plan only — no env var values, no execution.**
**`12_dedicated_auth/` is always internal-only. `raw_credentials_logged=False`, `raw_credentials_serialized=False`, `safe_to_deliver=False`, `approved_for_client_delivery=False` always. storageState `approved_for_commit=False` always.**
**`13_api_auth/` is always internal-only. Phase 5E. `raw_credentials_logged=False`, `raw_credentials_serialized=False`, `token_logged=False`, `safe_to_deliver=False`, `approved_for_client_delivery=False` always.**
**`14_qa_report/` is always internal-only. Phase 5F. `execution_performed=False`, `safe_to_deliver=False`, `approved_for_client_delivery=False`, `human_review_required=True` always. storageState content never read.**
**`15_google_auth/` is always internal-only. Phase 5G. `cookies_logged=False`, `tokens_logged=False`, `storage_state_content_read=False`, `browser_profile_content_read=False`, `captcha_bypass_attempted=False`, `anti_bot_bypass_attempted=False`, `personal_account_used=False`, `production_account_used=False`, `safe_to_deliver=False`, `approved_for_client_delivery=False` always. Google `accounts.google.com` is still blocked in generic runners — Google is allowed ONLY through Phase 5G dedicated runner.**
**`16_task_source/` is always internal-only. Phase 5H. `writeback_performed=False`, `raw_token_in_output=False`, `client_delivery_allowed=False` always. Linear API token value never appears in any artifact. No status changes, no comments, no webhooks.**
**`99_internal/` must never be included in client delivery packages.**

---

## Audit Report Layout

```
outputs/docs_audit/
    DOCS_FRESHNESS_REPORT.md    ← generated by python tools/docs_audit.py
    docs_freshness_report.json  ← machine-readable summary

outputs/agent_audit/
    AGENT_READINESS_REPORT.md   ← generated by python tools/agent_readiness_audit.py
    agent_readiness_report.json ← machine-readable summary
```

Both report folders are under `outputs/` and are gitignored.

---

## Client Scenario Fixtures (Phase 3B-SCENARIOS)

Scenario fixtures are **source inputs**, not runtime outputs.

```
fixtures/client_scenarios/
    README.md
    synthetic/
        01_google_oauth_auth_heavy.md
        02_payment_checkout_sandbox_required.md
        03_n8n_webhook_integration_blocked.md
        04_linear_issue_task_source.md
    public_demo_targets/
        01_saucedemo_ecommerce_login.md
        02_orangehrm_admin_dashboard.md
        03_the_internet_dynamic_ui.md
        04_restful_booker_api_auth_crud.md
        05_jsonplaceholder_fake_rest_api.md
        06_realworld_conduit_ui_api.md
    real_public_readonly/
        01_alza_sk_public_ecommerce_readonly.md
        02_playwright_docs_readonly.md
    high_risk_marketplace_readonly/
        01_amazon_public_marketplace_readonly.md
```

### Fixture ownership rules

| Property | Value |
|---|---|
| Committed to repository? | **Yes** |
| Runtime execution triggered? | **No** |
| Agent may read as planning input? | Yes |
| Agent may add real credentials? | **Never** |
| Agent may fetch URLs in fixtures? | **Never** |
| Client-visible? | Not without human review |

### Fixture contract guarantees

- **Source inputs only** — reading a fixture file does not fetch URLs, open browsers, run tests, or call external services
- **No real secrets** — synthetic fixtures contain only fake values; demo targets list published demo credentials only as reference text
- **Real URLs ≠ execution permission** — a URL appearing in a fixture does not authorize contacting that URL
- **Execution approval still required** — every external URL, including public demo targets, requires explicit per-run approval before any test execution
- **Not `outputs/`** — fixtures are committed source material; they never appear in `outputs/` and are not generated artifacts

---

## Artifact Safety Rules

1. **Never commit `outputs/`** — it is gitignored for a reason. Artifacts contain runtime
   data, potentially partial secrets, client info, and internal state.
2. **JSON artifacts are machine-readable truth** — prefer them over `.md` when reading
   project state programmatically.
3. **Markdown artifacts are for human review** — they may be opened in a browser, IDE, or
   shared in Slack. Ensure they contain no raw secrets.
4. **Framework code in `03_framework/`** is generated scaffold — always review before
   execution. It does not run automatically.
5. **`99_internal/` content never goes to clients** — quality gate reports, agent
   reasoning notes, and debug logs stay internal.

---

## Machine-Readable Format Notes

All JSON artifacts use:
- UTF-8 encoding
- 2-space indentation
- ISO 8601 timestamps
- `project_id` present in every root object
- Empty lists `[]` rather than `null` for list fields

Agents reading JSON artifacts should:
1. Check `project_id` matches expected project
2. Check `phase` field to understand what was generated
3. Check `BLOCKED_ACTIONS.md` before planning any execution
4. Check `SAFE_NEXT_STEPS.md` for approved planning actions

---

### `outputs/<project_id>/17_mobile_viewport/` (Phase 5I)

| File | Schema | Owner | Notes |
|---|---|---|---|
| `MOBILE_VIEWPORT_EXECUTION_REPORT.json` | `MobileViewportExecutionReport` | system | Execution result — device, status, blockers |
| `MOBILE_VIEWPORT_EXECUTION_REPORT.md` | — | system | Human-readable report |
| `MOBILE_VIEWPORT_SAFETY_CHECKLIST.md` | — | system | Pre-delivery review checklist |
| `mobile.config.cjs` | — | system | **Runtime-generated, gitignored — never committed** |

Safety guarantees: `credentials_used=False`, `auth_performed=False`, `safe_to_deliver=False`, `human_review_required=True` always.

### `outputs/<project_id>/18_visual_regression/` (Phase 5I)

| File | Schema | Owner | Notes |
|---|---|---|---|
| `VISUAL_REGRESSION_REPORT.json` | `VisualRegressionReport` | system | Mode, diffs, stats, blockers |
| `VISUAL_REGRESSION_REPORT.md` | — | system | Human-readable report |
| `VISUAL_REGRESSION_REVIEW_CHECKLIST.md` | — | system | Pre-delivery review checklist |
| `baselines/` | — | system | **Baseline screenshots — gitignored, never committed** |
| `visual_regression.spec.ts` | — | system | **Runtime-generated spec — gitignored, never committed** |

Safety guarantees: `credentials_used=False`, `auth_performed=False`, `safe_to_deliver=False`, `baselines_committed=False`, `human_review_required=True` always.

### `outputs/<project_id>/19_github_auth/` (Phase 5I)

| File | Schema | Owner | Notes |
|---|---|---|---|
| `GITHUB_AUTH_CAPABILITY_PLAN.json` | `GitHubAuthCapability` | system | Mode policies, account profile |
| `GITHUB_AUTH_CAPABILITY_PLAN.md` | — | system | Human-readable capability plan |
| `GITHUB_AUTH_EXECUTION_DECISION.json` | `GitHubAuthExecutionDecision` | system | Per-request allow/block decision |
| `GITHUB_AUTH_EXECUTION_DECISION.md` | — | system | Human-readable decision |
| `GITHUB_AUTH_EVIDENCE_REPORT.json` | `GitHubAuthEvidenceReport` | system | Execution evidence |
| `GITHUB_AUTH_EVIDENCE_REPORT.md` | — | system | Human-readable evidence |
| `GITHUB_AUTH_REDACTION_CHECKLIST.md` | — | system | Pre-delivery redaction checklist |
| `.auth/github-storageState.json` | — | system | **Captured session — NEVER COMMITTED, gitignored** |
| `github_smoke.cjs` | — | system | **Runtime-generated script — NEVER COMMITTED, gitignored** |

Safety guarantees: `safe_to_deliver=False`, `human_review_required=True`, `cookies_logged=False`,
`tokens_logged=False`, `storage_state_content_read=False`, `personal_account_used=False`,
`production_account_used=False`, `captcha_bypass_attempted=False` always.

### `outputs/<project_id>/20_e2e_pipeline/` (Phase 5J)

| File | Schema | Owner | Notes |
|---|---|---|---|
| `PIPELINE_RUN_REPORT.json` | `PipelineRunReport` | system | Module results, counters, overall status |
| `PIPELINE_RUN_REPORT.md` | — | system | Human-readable pipeline run summary |
| `PIPELINE_SAFETY_CHECKLIST.md` | — | system | Pre-delivery safety checklist |

Safety guarantees: `raw_secrets_allowed=False`, `production_write_allowed=False`, `client_delivery_allowed=False`, `safe_to_deliver=False`, `human_review_required=True` always.

### `outputs/<project_id>/21_db_smoke/` (Phase 5J)

| File | Schema | Owner | Notes |
|---|---|---|---|
| `DB_SMOKE_REPORT.json` | `DBSmokeReport` | system | Query results, provider, status, blockers |
| `DB_SMOKE_REPORT.md` | — | system | Human-readable DB smoke report |
| `DB_SMOKE_SAFETY_CHECKLIST.md` | — | system | Pre-delivery safety checklist |

Safety guarantees: `raw_secrets_allowed=False`, `destructive_db_actions_allowed=False`, `connection_string_logged=False`, `safe_to_deliver=False`, `human_review_required=True` always.

### `outputs/<project_id>/22_intake/` (Phase 5K)

| File | Schema | Owner | Notes |
|---|---|---|---|
| `INTAKE_REPORT.json` | `IntakeReport` | system | Classification, risk level, recommended modules |
| `INTAKE_REPORT.md` | — | system | Human-readable intake summary |

Safety guarantees: `raw_input_stored=False`, `credentials_in_output=False`, `safe_to_deliver=False`, `human_review_required=True` always. Raw input text is never stored in any artifact.

### `outputs/<project_id>/23_test_oracle/` (Phase 5K)

| File | Schema | Owner | Notes |
|---|---|---|---|
| `TEST_ORACLE_REPORT.json` | `TestOracleReport` | system | Prioritized test scenarios, deferred items |
| `TEST_ORACLE_REPORT.md` | — | system | Human-readable scenario list |

Safety guarantees: `raw_input_stored=False`, `executable_without_approval=False`, `safe_to_deliver=False`, `human_review_required=True` always. All scenarios are planning artifacts only.

### `outputs/<project_id>/24_evidence_intelligence/` (Phase 5K)

| File | Schema | Owner | Notes |
|---|---|---|---|
| `EVIDENCE_INTELLIGENCE_REPORT.json` | `EvidenceIntelligenceReport` | system | Coverage score, gaps, recommendations |
| `EVIDENCE_INTELLIGENCE_REPORT.md` | — | system | Human-readable gap analysis |

Safety guarantees: `network_calls_made=False`, `execution_performed=False`, `safe_to_deliver=False`, `human_review_required=True` always. Read-only file analysis — no subprocess or network calls.

---

### `outputs/<project_id>/25_api_contract/` (Phase 5M)

| File | Schema | Owner | Notes |
|---|---|---|---|
| `api_contract_inventory.json` | `APIContractReport` | system | All endpoints with safety classifications |
| `api_contract_summary.md` | — | system | Human-readable endpoint table |
| `auth_requirements_map.json` | `AuthRequirement[]` | system | Detected auth schemes |
| `risky_endpoints.json` | `APIEndpoint[]` | system | requires_approval + blocked endpoints |

Safety guarantees: `raw_secrets_allowed=False`, `destructive_api_calls_allowed=False`, `production_write_allowed=False`, `human_review_required=True` always. No network calls — local file analysis only.

---

### `outputs/<project_id>/26_generated_tests/` (Phase 5M)

| File | Schema | Owner | Notes |
|---|---|---|---|
| `api_smoke.generated.spec.ts` | — | system | Playwright API smoke stubs (safe_readonly only) |
| `api_schema.generated.spec.ts` | — | system | Schema validation stubs |
| `api_negative_candidates.md` | — | system | Negative test planning (approval required before use) |
| `generated_tests_manifest.json` | `GeneratedTestsReport` | system | Manifest with safety flags |

Safety guarantees: `executable_without_approval=False`, `human_review_required=True` always. Planning artifacts only — must not be auto-executed.

---

### `outputs/<project_id>/27_cicd/` (Phase 5M)

| File | Schema | Owner | Notes |
|---|---|---|---|
| `github-actions-qa-smoke.yml` | — | system | GitHub Actions workflow (or platform equivalent) |
| `cicd_summary.md` | — | system | Usage instructions and safety notes |
| `cicd_manifest.json` | `CICDManifest` | system | Artifact list with safety flags |

Safety guarantees: `auto_pr_creation_allowed=False`, `client_repo_writeback_allowed=False`, `production_deploy_allowed=False`, `human_review_required=True` always. No secrets embedded. Must be manually copied to target repo.

---

### `outputs/<project_id>/28_client_delivery/` (Phase 5P)

| File | Schema | Owner | Notes |
|---|---|---|---|
| `QA_Report.md` | — | system | Full client QA report (11 sections) |
| `QA_Report.html` | — | system | HTML version of QA report |
| `Bug_Report.md` | — | system | Bug/defect report template (populate after test execution) |
| `Test_Cases.csv` | — | system | Structured test case list (ID, Title, Type, Status, Priority) |
| `Risk_Matrix.md` | — | system | Risk matrix with severity and mitigation |
| `Recommendations.md` | — | system | Automation and CI/CD recommendations |
| `Evidence_Index.md` | — | system | Index of all evidence artifacts |
| `Delivery_Checklist.md` | — | system | Pre-delivery checklist (all items unchecked by default) |
| `client_delivery_manifest.json` | `ClientDeliveryManifest` | system | Manifest with safety flags and secret scan result |
| `client_delivery.zip` | — | system | ZIP of all delivery artifacts (blocked files excluded) |

Safety guarantees: `approved_for_client_delivery=False`, `human_review_required=True`,
`auto_send_to_client=False`, `secret_scan_before_delivery=True`, `raw_secrets_included=False` always.
Secret scan runs before ZIP creation. storageState, .env, credentials, cookies, tokens excluded from ZIP.

---

## Related Documents

- [`AGENT_CONTRACT.md`](AGENT_CONTRACT.md) — agent operating rules
- [`PHASE_CONTRACTS.md`](PHASE_CONTRACTS.md) — phase boundaries
- [`AGENT_HANDOFF_TEMPLATE.md`](AGENT_HANDOFF_TEMPLATE.md) — final report template
- [`DOCS_MANIFEST.md`](DOCS_MANIFEST.md) — all docs registry
