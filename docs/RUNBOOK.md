# Operational Runbook — Guided QA Automation Workbench

**Version:** 6.5.0  
**Updated:** 2026-05-27

> **AI drafts. Senior QA decides.**

This is the daily operating guide. What to run, what to open, what to check, and what to never skip.

Docs: [`VISION.md`](VISION.md) · [`COMMANDS.md`](COMMANDS.md) · [`APPROVAL_MODEL.md`](APPROVAL_MODEL.md) · [`SAFETY_RULES.md`](SAFETY_RULES.md)

---

## 1. Before any real work

```bash
python main.py system-health          # all 26 checks must pass
.venv\Scripts\python.exe -m pytest -q # 577 passed — always mock mode
```

If `system-health` fails: fix the listed issue before continuing.  
If tests fail: do not proceed with real-mode runs until green.

---

## 2. Standard client project workflow

```
1. Receive input (brief / task link / any form)
2. Run prescreen to classify and estimate
3. Read DECISION.md + PRESCREENING_REPORT.md
4. Choose workflow: scaffold / test-design / full
5. Review all outputs — NEVER send without manual pass
6. Complete HUMAN_REVIEW_REQUIRED.md checklist
7. Run local validation (compile, lint, dry-run)
8. Approval checkpoint before any external execution
9. Collect evidence after execution
10. Produce internal summary → then client-facing report
```

---

## 3. What to do based on input type

### A — You have only a text brief

```bash
python main.py prescreen --input brief.txt --require-real-llm
# Read: DECISION.md → PRESCREENING_REPORT.md
# If promising:
python main.py scaffold   --input brief.txt --require-real-llm
# or
python main.py test-design --input brief.txt --require-real-llm
```

Open after run:
```
READ_ME_FIRST.md → DECISION.md → EXECUTION_FLOW.md
APPROVAL_CHECKPOINTS.md → QUALITY_GATE_REPORT.md → HUMAN_REVIEW_REQUIRED.md
```

### B — You have a target application URL

The URL must be classified before any action. Do NOT paste raw URLs as if they were briefs.

Steps:
1. Write a brief `.txt` that describes the project and includes the URL as context
2. Run `prescreen` to classify project type and risk level
3. The system will note the URL in context but will NOT fetch or test it automatically
4. After prescreen, choose scaffold or test-design
5. External execution against that URL requires `--approve` and a completed checklist

```bash
# Write: real_sites/project_001_brief.txt
# Include the target URL in the brief description
python main.py prescreen --input real_sites/project_001_brief.txt --require-real-llm
```

**Do not run Playwright against a target URL without completing section 7 (approval checkpoint).**

### C — You have screenshots

Screenshots are classified via the vision model role. Current state: planned (Phase 2).

Interim approach:
1. Describe what the screenshots show in a text brief
2. Save screenshots to `real_sites/<project>/screenshots/`
3. Run prescreen on the text brief
4. Reference screenshots manually when reviewing outputs

Phase 2 will add: `--screenshot path/to/file.png` input mode.

### D — You have an archive, repo, or API docs

Archives and repos are planned (Phase 3).

Current approach:
1. Extract the relevant context (endpoints, tech stack, file structure) into a text brief
2. Run prescreen on the brief
3. For API docs: paste the key endpoints and schemas into the brief
4. Phase 3 will add structured OpenAPI/Postman ingestion

---

## 4. Approval checkpoints

These must be completed before external execution — every time, no exceptions:

```
Written scope
  [ ] Client confirmed target URL and in-scope flows in writing
  [ ] Out-of-scope areas defined
  [ ] Stop conditions agreed

Environment
  [ ] Staging URL confirmed (different domain from production)
  [ ] Synthetic test accounts provisioned (no real user data)
  [ ] API tokens are staging-only
  [ ] Payment flows: sandbox mode confirmed in writing (test cards only)

Safety
  [ ] No destructive actions in scope
  [ ] No production database access
  [ ] Credentials stored in .env only — not in briefs, specs, or reports

System readiness
  [ ] python main.py system-health — all pass
  [ ] pytest -q — 69/69 green
  [ ] --require-real-llm confirmed non-mock output
  [ ] APPROVAL_CHECKPOINTS.md generated and reviewed
  [ ] PRESCREENING_REPORT.md reviewed
```

Full checklist: [`REAL_TESTING_PREPARATION.md`](REAL_TESTING_PREPARATION.md)

---

## 5. Safe local validation vs. external execution

### Safe local validation — runs automatically

| Action | Command |
|---|---|
| TypeScript compile check | `npm run build` or `npx tsc --noEmit` inside framework |
| Playwright dry-run | `npx playwright test --dry-run` — no browser, no network |
| Lint | `npx eslint` inside framework |
| pytest (mock mode) | `.venv\Scripts\python.exe -m pytest -q` |

These are always safe. No approval needed. Run them freely.

### External execution — requires approval

| Action | Gate |
|---|---|
| Playwright tests against staging URL | `--approve` flag + section 4 checklist |
| API calls against real staging | `--approve` flag + scope confirmation |
| Any run against production | Explicit read-only approval + written scope |
| Payment / auth flow testing | Sandbox confirmation in writing |

To set BASE_URL and run against staging after approval:
```bash
cd outputs/<project_id>/framework
# Edit .env: BASE_URL=https://your-staging.example.com
npx playwright test           # only after completing section 4
```

---

## 6. How reports should be generated

Two report types — always separate:

**Internal summary** (always generated):
- `SUMMARY.md` — system-generated overview
- `QUALITY_GATE_REPORT.md` — 16 automated checks
- `SELF_HEALTH_REPORT.md` — system readiness
- `state.json` — full project state

**Client-facing report** (gated):
- `proposal.md`, `delivery_note.md`, `TEST_STRATEGY.md`, `TEST_PLAN.md`
- All require human review before delivery
- Never auto-sent
- Must pass through `HUMAN_REVIEW_REQUIRED.md` checklist first

Steps before any client delivery:
1. Open `HUMAN_REVIEW_REQUIRED.md` — read every item
2. Open `QUALITY_GATE_REPORT.md` — check for errors (not just warnings)
3. Manually edit the client-facing document
4. Remove any mock-mode placeholder text
5. Remove any internal notes or system prompts
6. Send manually

---

## 7. What must never run automatically

These require an explicit human decision — not a flag, a real decision:

- Running Playwright against any external URL (staging, demo, production)
- Testing payment flows of any kind
- Testing auth flows involving real credentials
- Security-sensitive actions (injection tests, auth bypass attempts)
- Sending anything to a client
- Pushing to any repository
- Creating or modifying issues/tickets in external systems
- Any action described as "destructive" in scope

If the system or a generated script proposes any of these: stop, read the scope, confirm with the client, then decide.

---

## 8. Upwork / opportunity evaluation workflow

```bash
# Step 1 — save job text
# Create: real_jobs/job_001.txt

# Step 2 — prescreen first
python main.py prescreen --input real_jobs/job_001.txt --source-platform upwork --auto

# Step 3 — read the verdict
# READ_ME_FIRST.md → DECISION.md → PRESCREENING_REPORT.md

# Step 4 — if promising, run full proposal
python main.py upwork --input real_jobs/job_001.txt --source-platform upwork --require-real-llm

# Step 5 — review before sending
# proposal.md, screening_answers.md, evidence_needed.md,
# commercial_strategy.md, QUALITY_GATE_REPORT.md, HUMAN_REVIEW_REQUIRED.md
```

**Never invent:** bug reports, Loom recordings, Linear tickets, device availability, Tosca/Maestro experience, client names.

---

## 9. Playwright scaffold setup

After `scaffold` generates a framework:

```bash
cd outputs/<project_id>/framework
npm install
npx playwright install

# Read the generated README.md first
# Set BASE_URL in .env — no fallback default
# Review smoke.spec.ts assertions before running

npx playwright test   # only against staging, only after approval
```

Safe pre-run checks (no approval needed):
```bash
npx tsc --noEmit          # TypeScript compile
npx playwright test --dry-run  # lists tests, no execution
```

---

## 10. Mock vs. real mode

**Mock mode** (default, always used in tests):
```env
LLM_MODE=mock
MODEL_PROFILE=mock
```

**Real mode** (requires API keys):
```env
LLM_MODE=real
MODEL_PROFILE=premium_hybrid
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

Windows — set encoding before real runs:
```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe main.py <command> --require-real-llm
```

Mock fallback warning: if you see `WARNING: N LLM call(s) fell back to mock output` — the output is not client-ready. Fix API keys and re-run.

---

## 11. Troubleshooting

| Symptom | Fix |
|---|---|
| `--require-real-llm` fails | Set `LLM_MODE=real` in `.env`, run `system-health` |
| Mock fallback warning | Check API key validity (`system-health`) |
| `BASE_URL missing` in Playwright | Set `BASE_URL` in framework `.env` |
| Pytest hitting real LLM | It doesn't — `conftest.py` forces mock mode |
| `botocore` warning | Harmless — AWS Bedrock not used here |
| Output too generic / short | You're in mock mode. Set `LLM_MODE=real`, use `--require-real-llm` |

---

## 12. Keeping documentation current

Documentation becomes stale when schemas, commands, workflows, safety rules, or integrations change. Use this process to keep docs accurate.

### When to run the docs audit

Run `python tools/docs_audit.py` after:
- Adding or changing schema modules in `core/schemas/`
- Adding, removing, or renaming CLI commands
- Changing workflow steps or agent behavior
- Changing safety rules or approval model
- Adding or changing tool/integration decisions
- Completing a phase

### How to run

```bash
python tools/docs_audit.py
```

Review the output. Fix any **errors** before proceeding. Assess **warnings** — not all require immediate action.

Reports are written to `outputs/docs_audit/DOCS_FRESHNESS_REPORT.md` unless `--no-write` is passed.

### Before moving to the next phase

1. Run `python tools/docs_audit.py` — no errors allowed.
2. Open `docs/DOCS_MANIFEST.md` — update the Status column for any changed docs.
3. Verify no doc claims runtime behavior for features that are still schema-only or planned.
4. Verify all new commands are in `docs/COMMANDS.md` with correct `[planned]` or `[implemented]` markers.
5. Verify all new schema modules are listed in `docs/SCHEMA_FOUNDATION.md`.

### Foundation-only reminder

Several Phase 1B schemas are foundation-only — no runtime execution yet. Docs referencing these must use a qualifier (`schema-only`, `foundation-only`, `planned`, or `[planned]`): credentials/auth execution, mobile/native execution, n8n/external integration calls, cleanup apply/deletion, live redaction.

See [`DOCUMENTATION_GOVERNANCE.md`](DOCUMENTATION_GOVERNANCE.md) for full rules.

---

## 13. Phase 2C: Build QA strategy before tactical execution

Run Phase 2C after Phase 2B has produced a `PROJECT_BLUEPRINT.json`. This step produces
a QA strategy, risk matrix, test layer recommendations, and tactical planning foundation.
All output is planning-only — no execution, no credentials, no external calls.

### Option A — Build from new input (full 2A + 2B + 2C):

```bash
python tools/build_strategy.py --input "Need Playwright tests for SaaS dashboard with login"
python tools/build_strategy.py --input "..." --project-id myproject
python tools/build_strategy.py --input "..." --no-write   # dry run, print only
python tools/build_strategy.py --input "..." --json       # JSON output to stdout
```

### Option B — Build from existing Phase 2B blueprint:

```bash
python tools/build_strategy.py --from-output outputs/<project_id>/00_project
python tools/build_strategy.py --from-output outputs/<project_id>/00_project --json
```

### Option C — Combined classify + blueprint + strategy:

```bash
python tools/classify_inputs.py --input "..." --with-strategy
python tools/classify_inputs.py --input "..." --with-strategy --no-write  # dry run
```

### What to review after Phase 2C:

1. Open `outputs/<project_id>/02_strategy/QA_STRATEGY.md` — review confidence level and strategy summary.
2. Open `RISK_MATRIX.md` — confirm risk items are realistic and mitigations are appropriate.
3. Open `BLOCKED_ACTIONS.md` (from Phase 2B) — all blocked items must still be blocked in strategy.
4. Open `STRATEGY_DECISIONS.md` — review key decisions before tactical work begins.
5. Confirm `client_ready = False` in `QA_STRATEGY.json` — do not deliver strategy to client without human review.

### What Phase 2C never does:

- Does not fetch any URL or access any external resource.
- Does not use credentials or read `.env` files.
- Does not execute Playwright or run any tests.
- Does not set `client_ready = True`.
- Does not remove or weaken blocked actions from Phase 2B.

---

## 14. Phase 3A: Generate Playwright TypeScript scaffold

Run Phase 3A after Phase 2C has produced a `QA_STRATEGY.json`. This step generates a
Playwright TypeScript scaffold in `outputs/<project_id>/03_framework/playwright/`.
Scaffold generation only — no URL fetching, no browser execution, no npm/npx, no credentials.

### Option A — Full pipeline from text input (Phase 2A + 2B + 2C + 3A):

```bash
python tools/generate_scaffold.py --input "Need Playwright tests for SaaS dashboard with login"
python tools/generate_scaffold.py --input "..." --project-id myproject
python tools/generate_scaffold.py --input "..." --no-write   # dry run, print only
python tools/generate_scaffold.py --input "..." --json       # JSON scaffold summary to stdout
```

### Option B — Scaffold only from existing Phase 2B/2C output:

```bash
python tools/generate_scaffold.py --from-output outputs/<project_id> --project-id <id>
python tools/generate_scaffold.py --from-output outputs/<project_id> --json
```

### Option C — Via WorkbenchController (programmatic):

```python
from core.workbench_controller import WorkbenchController
ctrl = WorkbenchController()
result = ctrl.build_context_with_scaffold(raw_inputs=["SaaS dashboard with login"], project_id="myproject")
scaffold = result["scaffold"]
# scaffold.execution_allowed is always False
```

### What to review after Phase 3A:

1. Open `outputs/<project_id>/03_framework/playwright/FRAMEWORK_SCAFFOLD.md` — review file list and safety flags.
2. Confirm `execution_allowed: false`, `client_visible: false`, `requires_review: true` in `FRAMEWORK_SCAFFOLD.json`.
3. Open `docs/SCAFFOLD_REVIEW_CHECKLIST.md` inside the scaffold — **complete before running any command**.
4. Review `pages/*.ts` — all selectors are placeholders; replace with real ones after inspecting the application.
5. Check `.env.example` — copy to `.env` and set approved values only; never commit `.env`.
6. Verify auth spec has `test.skip` guard; verify API spec has `test.skip` guard.

### What Phase 3A never does:

- Does not run npm install, npx, TypeScript compilation, or any test.
- Does not open a browser or fetch any URL.
- Does not use credentials or read `.env` files.
- Does not set `execution_allowed = True` or `client_visible = True`.
- Does not deliver scaffold to client — human review required first.

---

## 15. Phase 3B: Statically validate the scaffold

Run Phase 3B after Phase 3A to validate the generated scaffold without executing any code.

```bash
# By project ID (looks up outputs/<id>/03_framework/playwright/):
python tools/validate_scaffold.py --project-id <project_id>

# By direct path:
python tools/validate_scaffold.py --scaffold-root outputs/<project_id>/03_framework/playwright

# Dry run (no artifacts written):
python tools/validate_scaffold.py --project-id <project_id> --no-write

# JSON output:
python tools/validate_scaffold.py --project-id <project_id> --json
```

Phase 3B runs 27+ static checks across categories: structure, metadata, package_json, config,
env, tests, docs, secrets, urls, repository_boundary.

**Artifacts written to scaffold root:**
- `STATIC_VALIDATION_REPORT.json` / `.md` — full report with safety invariants
- `VALIDATION_PLAN.md` — what was checked and what needs approval
- `LOCAL_VALIDATION_CHECKLIST.md` — manual steps before any local command
- `TOOLCHAIN_VALIDATION_PLAN.md` — proposed toolchain commands (not yet executed)

### What to review after Phase 3B:

1. Open `STATIC_VALIDATION_REPORT.md` in the scaffold root.
2. Resolve all BLOCKERS before proceeding.
3. Review WARNINGS — most require human judgement, not automatic fix.
4. If validation passes: use `TOOLCHAIN_VALIDATION_PLAN.md` as the approval checklist for Phase 3C.

### What Phase 3B never does:

- Does not run npm install, npx, TypeScript compilation, or any test.
- Does not open a browser or fetch any URL.
- Does not use credentials or read `.env` files.
- Does not set `safe_to_execute_tests = True` — that requires Phase 4A approval.
- Does not deliver anything to the client.

### Before running toolchain commands locally (Phase 3C — requires approval):

After completing `SCAFFOLD_REVIEW_CHECKLIST.md` and Phase 3B static validation:
```bash
cd outputs/<project_id>/03_framework/playwright
npm install               # requires approval
npx playwright install    # requires approval, downloads browser binary
npm run typecheck         # TypeScript compile — no network, no browser
```

Only run tests after completing the checklist and obtaining explicit approval for the target URL.

---

## 16. Phase 3B-SCENARIOS: Practical client scenario fixtures

The `fixtures/client_scenarios/` directory contains controlled input files that simulate realistic
client QA tasks. They are source material for evaluation — **not runtime outputs**.

Reading fixture files does not fetch URLs, open browsers, run tests, or call external services.

### Categories

| Category | Purpose | Real URLs allowed |
|---|---|---|
| `synthetic/` | Fake URLs/creds; safety and redaction testing | No |
| `public_demo_targets/` | QA practice apps (SauceDemo, Restful Booker, etc.) | Yes — demo apps only |
| `real_public_readonly/` | Real production sites; read-only planning only | Yes — planning only |
| `high_risk_marketplace_readonly/` | High-risk marketplaces (Amazon etc.); strict blocking | Yes — planning only |

### Safe usage examples

```bash
# Classify a fixture file as input (reads as plain text brief):
python tools/classify_inputs.py \
  --input-file fixtures/client_scenarios/public_demo_targets/01_saucedemo_ecommerce_login.md \
  --no-write

# Build strategy from fixture brief text (--input, not --input-file):
python tools/build_strategy.py \
  --project-id scenario-saucedemo \
  --input "Need Playwright tests for SauceDemo. Surfaces: login, product listing, cart." \
  --no-write

# Validate a generated scaffold from a fixture-driven project:
python tools/validate_scaffold.py --project-id scenario-saucedemo --no-write
```

### What presence of a real URL in a fixture does NOT mean

A real URL appearing in a fixture file is a planning reference only. It does **not**:
- Authorize execution against that URL
- Enable URL fetching during classification, planning, scaffold, or validation
- Remove the per-run approval requirement

Real demo targets still require explicit per-run approval. Real production sites require written approval.

### Linear and other task-management tool URLs

Task management URLs (Linear, Jira, ClickUp, Asana) that appear as `task_url` inputs are
**requirement sources, not target applications**. The Workbench must classify them as
`task_source` in the blueprint — not as `target_application`. See:
`fixtures/client_scenarios/synthetic/04_linear_issue_task_source.md`

See: [`docs/CLIENT_SCENARIO_FIXTURES.md`](CLIENT_SCENARIO_FIXTURES.md)

---

## 17. Phase 3C: Approved local toolchain validation

Phase 3C adds approval-gated command execution for generated scaffolds.
**Without `--approve-toolchain`: nothing runs.** With it: only `npm install`,
`npm run typecheck`, and `npx playwright test --list` are executed.

### Prerequisite

Static validation (Phase 3B) must pass first:

```bash
python tools/validate_scaffold.py --project-id <id>
```

Resolve any blockers in `STATIC_VALIDATION_REPORT.json` before proceeding.

### Inspection mode (safe, no commands run)

```bash
python tools/validate_toolchain.py --project-id <id> --no-write
```

Output: `validation_status="blocked"`, all commands shown as `skipped`.

### Approved run (runs npm install + typecheck + --list)

```bash
python tools/validate_toolchain.py --project-id <id> --approve-toolchain
```

Writes 4 artifacts to scaffold root:
- `TOOLCHAIN_VALIDATION_REPORT.json` / `.md`
- `TOOLCHAIN_COMMAND_LOG.md`
- `TOOLCHAIN_APPROVAL_RECORD.md`

### Safety invariants — always False

Regardless of `--approve-toolchain` or command results:
- `safe_to_execute_tests` — False always
- `browser_execution_performed` — False always
- `external_url_used` — False always
- `credentials_used` — False always

Passing toolchain validation does **not** authorize browser tests or target URL access.
That requires Phase 4A approval (planned).

### What is always blocked

- `npx playwright install` — install browsers (not allowed)
- `npx playwright test` — run tests (not allowed)
- `npm test` / `npm run test` — run test suite (not allowed)
- Any command with an external URL
- Any command with credential-like arguments

See: [`docs/COMMANDS.md`](COMMANDS.md) — `validate_toolchain.py` section for all flags.

---

## 18. Agent-safe workflow

When Claude Code or any other AI assistant is driving changes in this workbench, the following rules apply before any agent session begins and before any commit is made.

### Before an agent-driven session

1. Read [`docs/AGENT_CONTRACT.md`](AGENT_CONTRACT.md) — the operating contract that governs what agents are and are not allowed to do.
2. Confirm which phase you are in. Read the relevant phase entry in [`docs/PHASE_CONTRACTS.md`](PHASE_CONTRACTS.md) for allowed and blocked actions.
3. Run `python -m pytest -q` — all tests must be green before new agent work starts.
4. Run `python tools/docs_audit.py --no-write` — no errors allowed.
5. Run `python tools/agent_readiness_audit.py --no-write` — all 34 required checks must pass.

### What agents must never do

- Do not fetch any URL, clone any repo, or call any external API.
- Do not open a browser or execute Playwright automation.
- Do not read `.env` files or use any credentials.
- Do not stage or commit anything in `outputs/`.
- Do not mark `[planned]` commands or features as implemented in docs.
- Do not implement autonomous agent runtimes, LangGraph, n8n, or browser execution — these are future phases.

See [`docs/AGENT_CONTRACT.md`](AGENT_CONTRACT.md) for the full forbidden actions list and required safety phrase declarations.

### Before a phase handoff or commit

1. Run the three checks above (pytest, docs_audit, agent_readiness_audit) — all must pass.
2. Run `git status` — confirm no `.env`, no `outputs/`, and no unintended files are staged.
3. Fill out [`docs/AGENT_HANDOFF_TEMPLATE.md`](AGENT_HANDOFF_TEMPLATE.md) and include it in the final response.
4. Do not commit automatically — always present the diff for human review first.

### Credential and external call policy

Credentials and external API calls are **not permitted in the current phase**. If a credential-like input is detected during classification, the workbench redacts it and outputs a notice. Any real credential use requires explicit written approval from the human operator and is gated to a future phase (Phase 2+).

---

## 20. Phase 4ABC: Readiness, Evidence, Reporting, Delivery Preview, Scenario Evaluation

> **No execution in Phase 4ABC.** No browser, no Playwright tests, no credentials,
> no external calls. All commands read local artifacts and produce local draft/preview/evaluation artifacts.

### Phase 4A: Execution Readiness Planning

```bash
python tools/plan_execution.py --project-id <id>
```

Inspects existing local artifacts (blueprint, strategy, scaffold, validation reports) and generates:
- `04_execution_plan/EXECUTION_APPROVAL_CHECKLIST.json/.md` — what must be approved before execution
- `04_execution_plan/EXECUTION_READINESS_REPORT.json/.md` — readiness status with blockers
- `04_execution_plan/EVIDENCE_COLLECTION_PLAN.md` — plan for future evidence collection
- `04_execution_plan/EXECUTION_BOUNDARIES.md` — what has/has not been done

All `approved_for_execution`, `approved_for_browser_execution`, and `approved_for_client_delivery`
flags remain `False`. Human review and explicit approval required for each.

### Phase 4B: Evidence Foundation

```bash
python tools/build_evidence_foundation.py --project-id <id>
```

Registers existing local validation artifacts as internal evidence records:
- `05_evidence/EVIDENCE_MANIFEST.json/.md` — registry of all evidence records
- `05_evidence/EVIDENCE_QUALITY_GATE.json/.md` — quality gate (not approved for client view)
- `05_evidence/EVIDENCE_REDACTION_REPORT.json/.md` — redaction status
- `05_evidence/INTERNAL_EVIDENCE_SUMMARY.md` — internal overview

Evidence is **internal-only by default** (`client_visible=False`). `approved_for_client_view=False`.
No real browser/execution evidence exists until Phase 4A+ approved execution.

### Phase 4C: Report Drafts

```bash
python tools/build_report_drafts.py --project-id <id>
python tools/build_delivery_preview.py --project-id <id>
```

Builds draft reports and a delivery preview manifest:
- `06_client_draft/INTERNAL_QA_SUMMARY_DRAFT.md` — internal summary
- `06_client_draft/CLIENT_REPORT_DRAFT.md` — **DRAFT** client report (not approved)
- `06_client_draft/DELIVERY_NOTE_DRAFT.md` — draft delivery note
- `06_client_draft/REPORT_QUALITY_CHECKLIST.md` — quality gate for delivery
- `06_client_draft/DELIVERY_PACKAGE_PREVIEW.md` — what would be included in a future package
- `06_client_draft/DELIVERY_SAFETY_CHECKLIST.md` — safety gate before packaging

All reports are marked **DRAFT — NOT APPROVED FOR DELIVERY**.
`client_ready=False`. `safe_to_deliver=False`. `safe_to_package=False`.
No zip or package is created.

### Phase 4ABC: Scenario Batch Evaluation

```bash
python tools/evaluate_scenarios.py --project-id <id>
```

Reads local `fixtures/client_scenarios/**/*.md` and evaluates safety expectations:
- `99_internal/scenario_evaluation/SCENARIO_BATCH_EVALUATION.json/.md`

`evaluation_performed_without_execution=True`. `external_calls_performed=False`.
No URL fetching. No execution. Internal only.

### Safety Rules for Phase 4ABC

- No browser execution is performed.
- No Playwright tests are run.
- No target URL is contacted.
- No credentials are used.
- No external APIs are called.
- No zip/package is created.
- No content is approved for client delivery.
- Evidence is internal-only by default.
- Client reports are draft-only.

---

## 19. Archive hygiene

**Exclude from any zip or share:**
```
.env  .env.local  .venv/  __pycache__/  outputs/  test-results/
playwright-report/  node_modules/  real_jobs/  real_sites/
```

**Safe to include:** source, `sample_inputs/`, `validation_inputs/`, `docs/`, `tests/`, `requirements.txt`, `README.md`, `.env.example`

If `.env` was accidentally shared: **rotate all API keys immediately.**

---

## 21. Phase 4D: Approved Controlled Demo and Public Read-Only Browser Execution

> **Approval-gated.** No general production execution. No real credentials. No payment/destructive actions. No scraping/crawling/load/security testing. No client delivery.

### Pre-flight approval checklist

Before running any Phase 4D command, confirm:

- [ ] Static scaffold validation passed (`validate_scaffold.py`)
- [ ] Toolchain validation run (`validate_toolchain.py`)
- [ ] Target is only: local/localhost, approved demo profile, or `playwright_docs_readonly`
- [ ] No real credentials used
- [ ] No general production target
- [ ] No payment/checkout/order creation
- [ ] No destructive/admin writes
- [ ] No scraping/crawling/load/security testing
- [ ] Evidence will remain internal-only
- [ ] Client delivery remains blocked

### No-execution (blocked) preview

```bash
python tools/run_demo_execution.py --project-id <id>
```

Result: `approved=False`, `execution_status=blocked`, no subprocess called.

### Approved local demo list execution

```bash
python tools/run_demo_execution.py --project-id <id> \
  --approve-demo-execution --target-category local --command-mode list
```

### Approved SauceDemo demo profile execution

```bash
# List mode (discovery, no browser opened)
python tools/run_demo_execution.py --project-id <id> \
  --approve-demo-execution --demo-profile saucedemo_public_demo --command-mode list

# Smoke mode (tests/smoke only, requires dependencies installed)
python tools/run_demo_execution.py --project-id <id> \
  --approve-demo-execution --demo-profile saucedemo_public_demo --command-mode smoke
```

### Approved Playwright.dev public read-only execution

```bash
# List mode
python tools/run_demo_execution.py --project-id <id> \
  --approve-public-readonly-execution --readonly-profile playwright_docs_readonly --command-mode list

# Read-only smoke (tests/smoke only, requires dependencies)
python tools/run_demo_execution.py --project-id <id> \
  --approve-public-readonly-execution --readonly-profile playwright_docs_readonly --command-mode readonly_smoke
```

### Blocked target examples (always rejected)

```bash
# Alza.sk — always blocked
python tools/run_demo_execution.py --project-id <id> \
  --approve-public-readonly-execution --target-category real_public_readonly --base-url https://www.alza.sk
# → BLOCKED: Alza.sk is always blocked

# Amazon.com — always blocked
python tools/run_demo_execution.py --project-id <id> \
  --approve-public-readonly-execution --target-category high_risk_marketplace_readonly --base-url https://www.amazon.com
# → BLOCKED: high_risk_marketplace_readonly targets are always blocked

# Linear.app — always blocked as task source
python tools/run_demo_execution.py --project-id <id> \
  --approve-demo-execution --target-category task_source --base-url https://linear.app/acme/issue/QA-123
# → BLOCKED: task_source targets are always blocked

# playwright.dev without readonly profile — blocked
python tools/run_demo_execution.py --project-id <id> \
  --approve-demo-execution --target-category real_public_readonly
# → BLOCKED: requires --approve-public-readonly-execution and playwright_docs_readonly profile
```

### If dependencies/browsers are missing

```
Approved smoke execution support is implemented, but real smoke was skipped
because dependencies/browsers are not present.
```

- Do not run `npm install` or `npx playwright install` automatically.
- Toolchain setup is Phase 3C responsibility.
- List-mode smoke and blocked-target smokes still work without dependencies.

### Artifacts generated

```
outputs/<id>/07_execution/
  BROWSER_EXECUTION_APPROVAL.json/md
  BROWSER_EXECUTION_REPORT.json/md
  BROWSER_COMMAND_LOG.md
  BROWSER_EVIDENCE_MANIFEST.json/md
```

All evidence: `internal_only=True`, `client_visible=False`, `requires_redaction=True`. Client delivery remains blocked.

---

## 22. Phase 4E: Credential and Test-Account Safety Layer

**Purpose:** Create a credential and test-account safety infrastructure. Policy, schema, validation, and CLI inspection only — no real credentials, no login, no auth execution.

### Pre-flight checklist

Before running any Phase 4E command, confirm:
- [ ] No real credentials in repo or fixtures
- [ ] No personal accounts will be used
- [ ] No production accounts will be used
- [ ] No .env files will be read
- [ ] No login or auth execution will occur

### Workflow

```bash
# Generate scaffold (if not already done)
python tools/generate_scaffold.py --project-id demo-4e --input "SaaS login and API"

# Inspect credential safety (no-write preview)
python tools/inspect_credentials.py --project-id demo-4e --no-write

# Full inspection with artifacts
python tools/inspect_credentials.py --project-id demo-4e

# Include fixture scanning
python tools/inspect_credentials.py --project-id demo-4e --include-fixtures

# Classify a sandbox profile
python tools/inspect_credentials.py --project-id demo-4e --classify-sandbox "Amazon Pay Sandbox"
```

### Key rules

- **Personal accounts are forbidden** — always use dedicated test accounts
- **Production accounts are forbidden** — use sandbox/staging only
- **storageState must be internal-only** — never commit to repo; must be in .gitignore
- **Auth execution requires explicit future phase approval** — blocked in Phase 4E
- **No real credentials in any artifact** — placeholders and env refs only

### Sandbox account distinctions

| Profile | Status | Notes |
|---|---|---|
| Amazon.com retail account | Always blocked | Production marketplace — do not use |
| Amazon Pay Sandbox | Blocked in Phase 4E | Future sandbox integration — requires merchant setup |
| Alza.sk production account | Blocked in Phase 4E | Requires client-provided staging/test access |
| Alza staging/test account | Blocked in Phase 4E | Future candidate with explicit client scope |
| Google/OAuth personal account | Always blocked | Personal accounts forbidden |
| Linear/Jira/ClickUp token | Always blocked | Task source integration — not an execution target |
| SauceDemo public demo | Allowed (Phase 4D) | Public credentials — not a secret |
| Dedicated staging/test account | Blocked in Phase 4E | Required for future auth execution phases |

### Artifacts written to `outputs/<project_id>/08_credentials/`

```
CREDENTIAL_POLICY.json/md
CREDENTIAL_SAFETY_REPORT.json/md
STORAGE_STATE_POLICY.json/md
AUTH_EXECUTION_APPROVAL_DRAFT.json/md
SANDBOX_PROFILE_CLASSIFICATION.json/md
CREDENTIAL_REDACTION_CHECKLIST.md
```

All credential artifacts are `internal_only=True`, `client_visible=False`. Client delivery requires human redaction review.

---

## 23. Phase 4F — Approved Demo Auth Execution

**Purpose:** Run approval-gated auth smoke against SauceDemo public demo target only.  
**Requires:** Phase 4E credential safety PASS. Explicit `--approve-demo-auth-execution` flag.

### Pre-flight checklist

- [ ] Phase 4E credential safety inspection passed (status=pass)
- [ ] Only `saucedemo_demo_auth` profile selected
- [ ] `--approve-demo-auth-execution` flag present and intentional
- [ ] No personal credentials present in environment
- [ ] No production credentials present in environment
- [ ] No payment/checkout/order creation in test scope
- [ ] Scaffold exists at `outputs/<project_id>/03_framework/playwright/`
- [ ] `node_modules` present (Phase 3C) — if absent, report cleanly, do not install

### Safe examples

```bash
# Approved auth smoke:
python tools/run_demo_auth.py --project-id demo --approve-demo-auth-execution --auth-profile saucedemo_demo_auth --command-mode auth_smoke

# Approved auth setup (storageState):
python tools/run_demo_auth.py --project-id demo --approve-demo-auth-execution --auth-profile saucedemo_demo_auth --command-mode auth_setup
```

### Blocked examples (always rejected)

```bash
# Alza auth — always blocked:
python tools/run_demo_auth.py --auth-profile alza_auth  → BLOCKED

# Amazon auth — always blocked:
python tools/run_demo_auth.py --auth-profile amazon_auth  → BLOCKED

# Google OAuth personal login — always blocked:
python tools/run_demo_auth.py --auth-profile google_oauth  → BLOCKED

# Linear token/account — always blocked:
python tools/run_demo_auth.py --auth-profile linear_auth  → BLOCKED

# No approval flag — always blocked:
python tools/run_demo_auth.py --project-id demo  → BLOCKED (no --approve-demo-auth-execution)
```

### Key rules

- Public demo credentials (standard_user/secret_sauce) injected into subprocess env only
- Credentials never appear in command args, logs, JSON/MD artifacts
- storageState generated only under `outputs/<project_id>/09_auth/.auth/` (gitignored)
- storageState content never read or included in reports
- `real_credentials_used=False`, `personal_account_used=False`, `production_account_used=False` always
- `safe_to_deliver=False`, `approved_for_client_delivery=False` always
- Evidence internal-only

### Artifacts written to `outputs/<project_id>/09_auth/`

```
AUTH_EXECUTION_APPROVAL.json/md
AUTH_EXECUTION_REPORT.json/md
AUTH_COMMAND_LOG.md
AUTH_SESSION_ARTIFACTS.json/md
AUTH_REDACTION_CHECKLIST.md
09_auth/.auth/storageState.json  ← optional, gitignored, internal-only
```

---

## 24. Phase 4G — Scenario Execution Matrix and Dedicated Test Account Planning

**Purpose:** Build a routing/planning matrix that classifies every scenario URL into an execution lane,
defines permission rules, and produces a dedicated test account plan. Policy and planning only —
no browser, no credentials, no execution.  
**Requires:** Phase 4E credential safety schemas in place.

### Pre-flight checklist

- [ ] `core/schemas/scenario_execution_matrix.py` imports without error
- [ ] `core/scenario_execution_matrix.py` imports without error
- [ ] `tools/build_execution_matrix.py` present and executable
- [ ] No `.env`, no `.auth`, no `storageState` files in scope

### Safe examples

```bash
# Build full matrix (all 9 lanes + artifacts):
python tools/build_execution_matrix.py --project-id demo-4g

# JSON output only (no file write):
python tools/build_execution_matrix.py --project-id demo-4g --json --no-write

# Include dedicated test account plan:
python tools/build_execution_matrix.py --project-id demo-4g --include-test-account-plan

# Routing decision for a URL:
python tools/build_execution_matrix.py --project-id demo-4g \
  --decide-url https://www.saucedemo.com --scenario-type no_auth_smoke

# Routing decision — strictly blocked URL:
python tools/build_execution_matrix.py --project-id demo-4g \
  --decide-url https://www.amazon.com --scenario-type no_auth_smoke
```

### Blocked examples (always rejected by routing)

```bash
# Personal Amazon account — always blocked:
--decide-url https://www.amazon.com → lane=strictly_blocked, allowed_now=False

# Google OAuth — always blocked:
--decide-url https://accounts.google.com → lane=strictly_blocked, allowed_now=False

# Linear — always blocked:
--decide-url https://linear.app → lane=strictly_blocked, allowed_now=False

# Alza — always blocked (real e-commerce auth required):
--decide-url https://www.alza.sk → lane=strictly_blocked, allowed_now=False
```

### Canonical execution lanes

| Lane ID | Status | Allowed Now | Approval Flag |
|---|---|---|---|
| `no_auth_demo_smoke` | implemented | Yes | `--approve-demo-execution` |
| `no_auth_public_readonly_smoke` | implemented | Yes | `--approve-public-readonly-execution` |
| `demo_auth_smoke` | implemented | Yes | `--approve-demo-auth-execution` |
| `dedicated_test_account_auth_future` | planned | No | Phase 5A |
| `staging_client_app_future` | planned | No | Phase 5A |
| `production_readonly_future` | planned | No | Phase 5B |
| `sandbox_payment_future` | planned | No | Phase 5C |
| `task_source_integration_future` | planned | No | Phase 5D |
| `strictly_blocked` | blocked | No | Never |

### Key safety invariants

- `DedicatedTestAccountRequirement.personal_account_allowed=False` — forced in `__post_init__` + `from_dict`
- `DedicatedTestAccountRequirement.production_account_allowed=False` — forced in `__post_init__` + `from_dict`
- `CredentialProvisioningRoute.repo_storage_allowed=False` — forced always
- `CredentialProvisioningRoute.logging_allowed=False` — forced always
- `CredentialProvisioningRoute.client_visible_allowed=False` — forced always
- `DedicatedTestAccountPlan.safe_for_execution_now=False` — forced always (planning doc only)
- No subprocess calls in builder — pure routing logic
- No credentials read or used in builder
- No external API calls in builder

### Artifacts written to `outputs/<project_id>/10_execution_matrix/`

```
SCENARIO_EXECUTION_MATRIX.json/md
EXECUTION_LANES.md
PERMISSION_ROUTING_TABLE.md
TARGET_PROFILE_RULES.md
BLOCKED_SCENARIOS.md
FUTURE_SCENARIOS.md
CREDENTIAL_PROVISIONING_ROUTES.md
DEDICATED_TEST_ACCOUNT_PLAN.json/md
```

All Phase 4G artifacts: `internal_only=True`, `client_visible=False`. Planning documents only.

---

## 25. Phase 5AB — Runtime Secret Routing + Dedicated Test-Account Auth Execution

**Purpose:** Validate and execute approval-gated auth against dedicated test accounts using env var references.
No raw secrets in CLI args. No `.env` reading. No personal/production accounts. No Google OAuth.  
**Requires:** Phase 4G execution matrix in place. Env vars set in shell before execution.

### Pre-flight checklist

- [ ] `core/schemas/runtime_secret_routing.py` imports without error
- [ ] `core/dedicated_auth_runner.py` imports without error
- [ ] `tools/plan_runtime_secrets.py` present and executable
- [ ] `tools/run_dedicated_auth.py` present and executable
- [ ] Target URL verified: not `accounts.google.com`, not `amazon.com`, not Alza/LinkedIn/Upwork
- [ ] Env vars set in shell using target-specific names (e.g. `export ORANGEHRM_USERNAME=...` / `export ORANGEHRM_PASSWORD=...`)
- [ ] `--dedicated-test-account-confirmed` confirmed (separate dedicated test account, not personal)
- [ ] Scaffold present at project path with `node_modules/` and `tests/auth/`
- [ ] No `.env`, no `.auth` files read — env vars set only in terminal
- [ ] Ready to pass `--approve-dedicated-auth-execution` with full awareness of what it unlocks

### Planning workflow (no execution)

```bash
# Validate intake request — no env var reading, no subprocess:
python tools/plan_runtime_secrets.py --project-id demo-5ab \
    --scenario-lane dedicated_test_account_auth_future \
    --target-category orangehrm_demo_auth \
    --target-url https://opensource-demo.orangehrmlive.com \
    --username-env-var ORANGEHRM_USERNAME \
    --password-env-var ORANGEHRM_PASSWORD \
    --dedicated-test-account-confirmed \
    --staging-environment-confirmed

# Preview only (no write):
python tools/plan_runtime_secrets.py --project-id demo-5ab --json --no-write
```

### Execution workflow (approval required)

```bash
# Step 1 — set env vars using target-specific names (never in .env or chat):
export ORANGEHRM_USERNAME=your_test_username
export ORANGEHRM_PASSWORD=your_test_password

# Step 2 — preview (no execution, no env var reading):
python tools/run_dedicated_auth.py --project-id demo-5ab

# Step 3 — approved OrangeHRM auth smoke (browser):
python tools/run_dedicated_auth.py --project-id demo-5ab \
    --approve-dedicated-auth-execution \
    --scenario-lane dedicated_test_account_auth_future \
    --target-category orangehrm_demo_auth \
    --target-url https://opensource-demo.orangehrmlive.com \
    --username-env-var ORANGEHRM_USERNAME \
    --password-env-var ORANGEHRM_PASSWORD \
    --dedicated-test-account-confirmed \
    --staging-environment-confirmed \
    --command-mode auth_smoke

# Restful Booker uses API token auth (not browser form) — use Phase 5D runner:
# python tools/run_api_auth_smoke.py --project-id demo-5d \
#     --approve-api-auth-execution \
#     --target-profile restful_booker_public_api \
#     --username-env-var RESTFUL_BOOKER_USERNAME \
#     --password-env-var RESTFUL_BOOKER_PASSWORD
# (See Section 26 — Phase 5D)
```

### Blocked examples (always rejected by 9 security gates)

```bash
# No approval flag — blocked at gate 1:
python tools/run_dedicated_auth.py --project-id demo-5ab
# → execution_status=blocked

# Personal account flag — blocked at gate 2:
python tools/run_dedicated_auth.py ... --personal-account-confirmed
# → BLOCKED: personal_account_confirmed is not allowed

# Google OAuth target — blocked at gate 5:
python tools/run_dedicated_auth.py ... --target-url https://accounts.google.com
# → BLOCKED: target URL matches blocked pattern

# Raw secret flag (would be rejected by argparse):
python tools/run_dedicated_auth.py ... --password secret123
# → ERROR: Unknown argument / BLOCKED: raw secret flag

# Missing env var — blocked at gate 8:
python tools/run_dedicated_auth.py ... --username-env-var QA_MISSING_VAR
# → BLOCKED: env var QA_MISSING_VAR not set in environment
```

### Key safety invariants

- `DedicatedAuthExecutionReport.raw_credentials_logged=False` — forced in `__post_init__` + `from_dict`
- `DedicatedAuthExecutionReport.raw_credentials_serialized=False` — forced always
- `DedicatedAuthExecutionReport.personal_account_used=False` — forced always
- `DedicatedAuthExecutionReport.production_account_used=False` — forced always
- `DedicatedAuthExecutionReport.safe_to_deliver=False` — forced always
- `DedicatedAuthExecutionReport.approved_for_client_delivery=False` — forced always
- `DedicatedAuthSessionArtifact.approved_for_commit=False` — forced always
- `DedicatedAuthSessionArtifact.client_visible=False` — forced always
- `TestAccountValidationResult.approved_for_execution_now=False` — forced always (planning never grants execution)
- Secret masking: `_mask()` applied to all subprocess stdout/stderr before storage

### Artifacts written

**`outputs/<project_id>/11_runtime_secrets/`** (planning):
```
TEST_ACCOUNT_INTAKE_VALIDATION.json
RUNTIME_SECRET_ROUTING_PLAN.md
```

**`outputs/<project_id>/12_dedicated_auth/`** (execution):
```
DEDICATED_AUTH_EXECUTION_REPORT.json/md
DEDICATED_AUTH_COMMAND_LOG.md
DEDICATED_AUTH_SESSION_ARTIFACTS.json/md
DEDICATED_AUTH_SAFETY_BOUNDARY.md
.auth/storageState.json  ← optional, gitignored, never committed
```

All Phase 5AB artifacts: `internal_only=True`, `client_visible=False`, `approved_for_commit=False`, `safe_to_deliver=False` always.

---

## Section 26 — Phase 5E — API Auth Smoke

### What it does

Approval-gated HTTP API auth smoke for token-based API targets (Restful Booker, staging, dedicated test).
No Playwright/browser. Pure HTTP via `urllib`. Env var names only — raw values never in CLI args.

### Pre-flight checklist

- [ ] `core/api_auth_runner.py` imports without error
- [ ] `tools/run_api_auth_smoke.py` present and executable
- [ ] Target URL not in blocked list (`accounts.google.com`, `amazon.com`, Alza, etc.)
- [ ] Env vars set in shell: `export RESTFUL_BOOKER_USERNAME=...` / `export RESTFUL_BOOKER_PASSWORD=...`
- [ ] Ready to pass `--approve-api-auth-execution` with full awareness of what it unlocks

### Execution workflow

```bash
# Step 1 — set env vars (session-only, never in .env):
export RESTFUL_BOOKER_USERNAME=admin
export RESTFUL_BOOKER_PASSWORD=password123

# Step 2 — preview (no execution, no env var reading):
python tools/run_api_auth_smoke.py --project-id demo-5e

# Step 3 — approved Restful Booker API auth smoke:
python tools/run_api_auth_smoke.py \
    --project-id restful-booker-api-smoke \
    --approve-api-auth-execution \
    --target-profile restful_booker_public_api \
    --username-env-var RESTFUL_BOOKER_USERNAME \
    --password-env-var RESTFUL_BOOKER_PASSWORD
```

### Key safety invariants

- `raw_credentials_logged=False` always
- `token_logged=False` always (token presence verified, value masked)
- `safe_to_deliver=False` always
- No DELETE / destructive API calls in Phase 5E
- No browser, no subprocess, no Playwright

### Artifacts

**`outputs/<project_id>/13_api_auth/`** (execution):
```
API_AUTH_EXECUTION_REPORT.json/md
```

All Phase 5E artifacts: `internal_only=True`, `client_visible=False`, `token_logged=False`, `safe_to_deliver=False` always.

---

## Section 27 — Phase 5F — QA Evidence Report Generator

### What it does

Read-only aggregation of Phase 5AB and Phase 5E execution artifacts into a consolidated
QA Evidence Report. Supports multi-source aggregation (browser auth + API auth from
separate project IDs). Includes secret scan. No execution, no network calls.

### Pre-flight checklist

- [ ] At least one source project has `outputs/<id>/12_dedicated_auth/DEDICATED_AUTH_EXECUTION_REPORT.json`
  or `outputs/<id>/13_api_auth/API_AUTH_EXECUTION_REPORT.json`
- [ ] `core/qa_report_generator.py` and `tools/generate_qa_report.py` present
- [ ] No storageState content will be read (enforced in generator)

### Execution workflow

```bash
# Single browser-auth source:
python tools/generate_qa_report.py \
    --project-id first-real-auth-smoke

# Single API-auth source:
python tools/generate_qa_report.py \
    --project-id restful-booker-api-smoke

# Combined multi-source report:
python tools/generate_qa_report.py \
    --project-id qa-demo-evidence-report \
    --source-project-id first-real-auth-smoke \
    --source-project-id restful-booker-api-smoke

# Preview (no artifacts written):
python tools/generate_qa_report.py \
    --project-id qa-demo-evidence-report \
    --source-project-id first-real-auth-smoke \
    --no-write
```

### Key safety invariants

- `execution_performed=False` always (hardcoded in `__post_init__`)
- `network_calls_performed=False` always
- `storage_state_content_read=False` always — `.auth/` directories never entered
- `safe_to_deliver=False` always
- `approved_for_client_delivery=False` always
- `human_review_required=True` always

### Artifacts

**`outputs/<project_id>/14_qa_report/`**:
```
QA_EVIDENCE_REPORT.json
QA_EVIDENCE_REPORT.md
QA_REPORT_REVIEW_CHECKLIST.md
QA_REPORT_SECRET_SCAN.json
QA_REPORT_SECRET_SCAN.md
```

All Phase 5F artifacts: `execution_performed=False`, `safe_to_deliver=False`, `human_review_required=True` always.

---

## Section 28 — Phase 5G — Google/OAuth Test Account Capability

### What it does

Permissioned Google auth path for dedicated test accounts. Replaces the blanket Google
block with a capability model: personal/production accounts stay blocked, dedicated
test accounts are allowed under explicit approval flags with safe modes only.

### Pre-flight checklist

- [ ] Dedicated Google test account exists (NOT your personal account)
- [ ] You are NOT signed into a production/admin Google account in the browser session
- [ ] Phase 3A scaffold exists at `outputs/<project_id>/03_framework/playwright/`
- [ ] Node.js is installed and on PATH
- [ ] `.gitignore` covers `15_google_auth/.auth/` and `*.cjs` runtime scripts
- [ ] You understand: this runner does NOT bypass CAPTCHA or 2FA — you solve them yourself

### Three-step workflow

```bash
# Step 1 — plan capability (no browser, no network):
python tools/plan_google_auth.py \
    --project-id my-google-smoke \
    --account-email-label danrobinson_artist_gmail \
    --dedicated-test-account-confirmed \
    --google-test-account-confirmed

# Step 2 — capture storageState (you log in manually in the visible browser):
python tools/capture_google_storage_state.py \
    --project-id my-google-smoke \
    --approve-google-test-account \
    --google-test-account-confirmed \
    --dedicated-test-account-confirmed \
    --account-email-label danrobinson_artist_gmail \
    --target-url https://accounts.google.com

# Step 3 — read-only smoke using captured state:
python tools/run_google_auth_smoke.py \
    --project-id my-google-smoke \
    --approve-google-test-account \
    --google-test-account-confirmed \
    --dedicated-test-account-confirmed \
    --storage-state-path outputs/my-google-smoke/15_google_auth/.auth/google-storageState.json \
    --target-url https://myaccount.google.com
```

### Always-blocked sub-paths (hardcoded)

- Personal/production Google accounts
- CAPTCHA bypass / anti-bot bypass
- Stealth or undetected-browser as core path
- Raw secrets in CLI args (`--password`, `--token`, `--cookie`, etc.)
- Reading storageState content / Chrome profile content
- Reading Gmail/Drive content
- Writing/deleting Google account data
- Copying main Chrome profile

### What about "I'm not a robot" / CAPTCHA?

Phase 5G NEVER bypasses CAPTCHA. Workflow:
1. In manual capture, browser is visible; you solve any challenge.
2. The captured storageState contains the post-login session.
3. Subsequent smokes reuse that session — Google does not show CAPTCHA again until the session expires (~2-4 weeks).

### Artifacts

**`outputs/<project_id>/15_google_auth/`**:
```
GOOGLE_AUTH_CAPABILITY_PLAN.json/md
GOOGLE_STORAGE_STATE_POLICY.json/md
GOOGLE_AUTH_EXECUTION_DECISION.json/md
GOOGLE_AUTH_EVIDENCE_REPORT.json/md
GOOGLE_AUTH_REDACTION_CHECKLIST.md
.auth/google-storageState.json    ← gitignored, internal-only
manual_capture.cjs                 ← runtime script, gitignored
storage_state_smoke.cjs            ← runtime script, gitignored
smoke_redacted.png                 ← optional screenshot, gitignored
```

All Phase 5G artifacts: `safe_to_deliver=False`, `human_review_required=True` always.

---

## Section 29 — Phase 5H — Multi-Target Expansion + Task Source Integration

### 29a. Linear Task Source Fetch

**Purpose:** Read Linear issues as requirements input and derive test scenarios. Linear is never
an app-under-test — it is a task source (requirements input) only.

**Prerequisites:**
- [ ] Linear API token in env var (e.g. `LINEAR_API_TOKEN`) — must be a read-only token
- [ ] Project scaffold exists at `outputs/<project_id>/` (or will be created on first run)
- [ ] Confirm `--approve-task-source-integration` is appropriate for client engagement

**Command:**
```bash
python tools/fetch_task_source.py \
    --project-id my-project \
    --provider linear \
    --token-env-var LINEAR_API_TOKEN \
    --team-key ENG \
    --approve-task-source-integration
```

**Safety checklist:**
- [ ] `--token-env-var` contains an env var NAME (not a raw token value)
- [ ] Env var NAME matches `^[A-Z][A-Z0-9_]{0,79}$`
- [ ] Linear API token has read-only scope (no create/update/comment permissions)
- [ ] `writeback_allowed=False` confirmed (hardcoded — cannot be bypassed)
- [ ] `raw_token_in_output=False` confirmed (hardcoded — cannot be bypassed)

**Output artifacts (`outputs/<project_id>/16_task_source/`):**
```
task_source_report.json     ← TaskSourceFetchReport schema
derived_scenarios.json      ← List of derived test scenarios
task_source_summary.md      ← Human-readable fetch summary
```

All Phase 5H task source artifacts: `writeback_performed=False`, `raw_token_in_output=False`,
`client_delivery_allowed=False` always.

### 29b. Amazon/Alza Public Readonly Navigation

**Purpose:** Test public product, search, and category pages on Amazon and Alza.
Auth/cart/checkout paths remain hard-blocked at all levels.

**Command (scenario matrix decision):**
```bash
python tools/decide_scenario.py \
    --project-id my-ecommerce-test \
    --decide-url https://www.amazon.com/dp/B08N5WRWNW \
    --scenario-type public_search_browse \
    --approve-public-readonly-execution \
    --readonly-profile amazon_public_readonly
```

**Always-blocked paths (cannot be unlocked):**
`/signin`, `/ap/`, `/gp/buy`, `/cart`, `/checkout`, `/account`, `/order`, `/orders`, `/your-account`, `/wishlist/`

### 29c. CDP Attach Mode (Google Auth)

**Purpose:** Attach to an already-running Chrome session the user launched and authenticated
manually. No password automation. No CAPTCHA bypass.

**User flow:**
1. Launch Chrome with debugging port:
   ```bash
   google-chrome --remote-debugging-port=9222 --user-data-dir=/tmp/chrome-test
   ```
2. Navigate and log in manually (solve CAPTCHA/2FA yourself)
3. Run the auth runner with `--auth-mode cdp_attach --cdp-port 9222`

**Safety:** CDP port must be 1024–65535. The system attaches only — never automates login.

---

### 30. Mobile Viewport Smoke (Phase 5I)

**Purpose:** Run Playwright tests with mobile device viewport emulation. No credentials.

**Checklist:**
- [ ] Test files in scaffold use only no-auth public page selectors
- [ ] No `addToCart`, `checkout`, `buy`, `password` selectors in test files (if ecommerce readonly)
- [ ] `--approve-mobile-execution` flag included

**Command (basic smoke):**
```bash
python tools/run_mobile_viewport_smoke.py \
    --project-id my-project \
    --device "iPhone 14" \
    --approve-mobile-execution
```

**Command (Amazon mobile readonly):**
```bash
python tools/run_mobile_viewport_smoke.py \
    --project-id amazon-mobile-test \
    --device "Pixel 7" \
    --readonly-profile amazon_mobile_readonly \
    --target-url https://www.amazon.com/dp/B08N5WRWNW \
    --approve-mobile-execution
```

**Output artifacts (`outputs/<project_id>/17_mobile_viewport/`):**
```
MOBILE_VIEWPORT_EXECUTION_REPORT.json
MOBILE_VIEWPORT_EXECUTION_REPORT.md
MOBILE_VIEWPORT_SAFETY_CHECKLIST.md
```

All artifacts: `credentials_used=False`, `auth_performed=False`, `safe_to_deliver=False`,
`human_review_required=True` always.

---

### 31. Visual Regression (Phase 5I)

**Purpose:** Playwright `toHaveScreenshot()` visual regression — capture baselines and compare.

**Checklist:**
- [ ] Target URL is in the allowed URL prefix list (localhost, saucedemo, amazon, alza, etc.)
- [ ] No credentials passed
- [ ] `--approve-visual-regression` flag included
- [ ] Baselines captured before comparison (`--mode capture` first)

**Command (capture baselines):**
```bash
python tools/run_visual_regression.py \
    --project-id my-project \
    --target-url https://www.saucedemo.com \
    --mode capture \
    --approve-visual-regression
```

**Command (compare):**
```bash
python tools/run_visual_regression.py \
    --project-id my-project \
    --target-url https://www.saucedemo.com \
    --mode compare \
    --approve-visual-regression
```

**Output artifacts (`outputs/<project_id>/18_visual_regression/`):**
```
VISUAL_REGRESSION_REPORT.json
VISUAL_REGRESSION_REPORT.md
VISUAL_REGRESSION_REVIEW_CHECKLIST.md
baselines/   ← gitignored
```

All artifacts: `credentials_used=False`, `auth_performed=False`, `safe_to_deliver=False`,
`baselines_committed=False`, `human_review_required=True` always.

---

### 32. GitHub OAuth Smoke (Phase 5I)

**Purpose:** Plan GitHub test-account OAuth capability or run storage-state-reuse smoke.
Mirrors Phase 5G Google auth runner. Personal and production accounts always blocked.

**Checklist:**
- [ ] Account is a dedicated test account (not personal `dpogribnyy@...` or production org)
- [ ] `--dedicated-test-account-confirmed` flag included
- [ ] `--personal-account-confirmed` NOT included (blocks execution)
- [ ] `--production-account-confirmed` NOT included (blocks execution)
- [ ] storageState file is gitignored (not committed)

**Command (capability plan):**
```bash
python tools/run_github_auth_smoke.py \
    --project-id my-project \
    --account-email-label qa_bot_github \
    --approve-github-test-account \
    --dedicated-test-account-confirmed
```

**Command (storage-state-reuse smoke):**
```bash
python tools/run_github_auth_smoke.py \
    --project-id my-project \
    --decide \
    --run-smoke \
    --auth-mode storage_state_reuse \
    --target-url https://github.com \
    --storage-state-path outputs/my-project/19_github_auth/.auth/github-storageState.json \
    --approve-github-test-account \
    --dedicated-test-account-confirmed
```

**Output artifacts (`outputs/<project_id>/19_github_auth/`):**
```
GITHUB_AUTH_CAPABILITY_PLAN.json/md
GITHUB_AUTH_EXECUTION_DECISION.json/md
GITHUB_AUTH_EVIDENCE_REPORT.json/md
GITHUB_AUTH_REDACTION_CHECKLIST.md
.auth/github-storageState.json   ← NEVER COMMITTED
github_smoke.cjs                 ← runtime only, NEVER COMMITTED
```

All artifacts: `personal_account_used=False`, `production_account_used=False`,
`captcha_bypass_attempted=False`, `safe_to_deliver=False`, `human_review_required=True` always.

---

### 33. E2E Pipeline Runner (Phase 5J)

**Purpose:** Orchestrate all enabled Phase 5x runners in a fixed, safe sequence.
Requires `--approve-pipeline-execution`. Each module's own safety gates remain in effect.

**Checklist:**
- [ ] All enabled modules have their own approval flags included
- [ ] DB connection string is an env var NAME (e.g. `STAGING_DATABASE_URL`), not a raw URL
- [ ] No `--password`, `--token`, `--secret`, `--api-key`, `--cookie`, or `--db-url` flags used
- [ ] Plan reviewed before execution (`--approve-pipeline-execution` omitted for plan-only)
- [ ] `outputs/<project_id>/20_e2e_pipeline/` artifacts reviewed by a human before any delivery

**Command (plan only — no execution):**
```bash
python tools/run_e2e_pipeline.py \
    --project-id my-project \
    --enable-browser \
    --enable-api \
    --enable-qa-report
```

**Command (run pipeline):**
```bash
python tools/run_e2e_pipeline.py \
    --project-id my-project \
    --enable-browser \
    --enable-api \
    --enable-db \
    --api-target-url https://restful-booker.herokuapp.com \
    --browser-target-url https://www.saucedemo.com \
    --browser-category saucedemo \
    --db-provider postgresql \
    --db-url-env-var STAGING_DATABASE_URL \
    --approve-pipeline-execution \
    --approve-browser-execution \
    --approve-api-smoke \
    --approve-db-smoke
```

**Output artifacts (`outputs/<project_id>/20_e2e_pipeline/`):**
```
PIPELINE_RUN_REPORT.json
PIPELINE_RUN_REPORT.md
PIPELINE_SAFETY_CHECKLIST.md
```

All artifacts: `raw_secrets_allowed=False`, `production_write_allowed=False`,
`client_delivery_allowed=False`, `safe_to_deliver=False`, `human_review_required=True` always.

---

### 34. DB Smoke Runner (Phase 5J)

**Purpose:** Read-only database connectivity smoke. Verifies the connection string env var
is set, the driver is available, and the target table/collection is queryable.
Only SELECT/SHOW/DESCRIBE/EXPLAIN and approved MongoDB operations are allowed.

**Checklist:**
- [ ] Env var (e.g. `STAGING_DATABASE_URL`) is set in the shell environment before running
- [ ] `--db-url-env-var` flag contains an env var NAME, not a raw URL
- [ ] No `--password`, `--token`, `--secret`, `--db-url`, `--connection-string` flags used
- [ ] Custom `--query` (if used) starts with SELECT/SHOW/DESCRIBE/EXPLAIN
- [ ] MongoDB `--mongo-operation` (if used) is in the allowed list
- [ ] `--approve-db-smoke` flag included
- [ ] `outputs/<project_id>/21_db_smoke/` artifacts reviewed by a human

**Command (PostgreSQL — default SELECT):**
```bash
python tools/run_db_smoke.py \
    --project-id my-project \
    --provider postgresql \
    --db-url-env-var STAGING_DATABASE_URL \
    --table users \
    --approve-db-smoke
```

**Command (MongoDB — find):**
```bash
python tools/run_db_smoke.py \
    --project-id my-project \
    --provider mongodb \
    --db-url-env-var STAGING_MONGO_URL \
    --mongo-operation find \
    --table products \
    --row-limit 10 \
    --approve-db-smoke
```

**Output artifacts (`outputs/<project_id>/21_db_smoke/`):**
```
DB_SMOKE_REPORT.json
DB_SMOKE_REPORT.md
DB_SMOKE_SAFETY_CHECKLIST.md
```

All artifacts: `raw_secrets_allowed=False`, `destructive_db_actions_allowed=False`,
`connection_string_logged=False`, `safe_to_deliver=False`, `human_review_required=True` always.

### 35. Intake Agent (Phase 5K)

**Purpose:** Heuristic classification of work requests into test type, risk level,
and recommended pipeline modules. Raw input text is never stored.

**Checklist:**
- [ ] No credentials, tokens, or secrets in input text
- [ ] `--input-file` or `--input-text` provided (not both)
- [ ] Review `INTAKE_REPORT.md` — classification, risk level, recommended modules
- [ ] If classification is `unknown`, provide more specific requirements
- [ ] Human review completed before acting on recommendations

**Command:**
```bash
python tools/run_intake_agent.py \
    --project-id my-project \
    --input-text "We need to test the login API and session management"
```

**Output artifacts (`outputs/<project_id>/22_intake/`):**
```
INTAKE_REPORT.json
INTAKE_REPORT.md
```

All artifacts: `raw_input_stored=False`, `credentials_in_output=False`, `safe_to_deliver=False`, `human_review_required=True` always.

---

### 36. Test Oracle (Phase 5K)

**Purpose:** Generates prioritized test scenarios from a classification or intake report.
All scenarios are planning artifacts — not executable without human approval.

**Checklist:**
- [ ] `--intake-report-path` or `--classification` provided (not both)
- [ ] Review `TEST_ORACLE_REPORT.md` — priority order, risk scores, deferred items
- [ ] Performance/security scenarios are deferred to Phase 5N
- [ ] Human review and explicit approval before any scenario is executed

**Command (from classification):**
```bash
python tools/run_test_oracle.py \
    --project-id my-project \
    --classification api_testing
```

**Command (from intake report):**
```bash
python tools/run_test_oracle.py \
    --project-id my-project \
    --intake-report-path outputs/my-project/22_intake/INTAKE_REPORT.json
```

**Output artifacts (`outputs/<project_id>/23_test_oracle/`):**
```
TEST_ORACLE_REPORT.json
TEST_ORACLE_REPORT.md
```

All artifacts: `raw_input_stored=False`, `executable_without_approval=False`, `safe_to_deliver=False`, `human_review_required=True` always.

---

### 37. Evidence Intelligence (Phase 5K)

**Purpose:** Read-only static analysis of existing artifact directories — computes
coverage score, identifies gaps, and generates recommendations. No approval needed.

**Checklist:**
- [ ] Run after other pipeline modules have produced artifacts
- [ ] Review `EVIDENCE_INTELLIGENCE_REPORT.md` — coverage score, high-severity gaps
- [ ] Act on recommendations before proceeding to client delivery

**Command:**
```bash
python tools/run_evidence_intelligence.py --project-id my-project

# Check specific areas only
python tools/run_evidence_intelligence.py \
    --project-id my-project \
    --areas auth api database
```

**Output artifacts (`outputs/<project_id>/24_evidence_intelligence/`):**
```
EVIDENCE_INTELLIGENCE_REPORT.json
EVIDENCE_INTELLIGENCE_REPORT.md
```

All artifacts: `network_calls_made=False`, `execution_performed=False`, `safe_to_deliver=False`, `human_review_required=True` always.

### 38. Desktop Browser Execution CLI (Phase 5L)

**Purpose:** Approval-gated desktop Playwright smoke execution against public read-only
targets. Requires explicit dual-approval for ecommerce sites (Amazon, Alza).

**Checklist:**
- [ ] Scaffold has `node_modules` (`npm install` run inside `03_framework/playwright/`)
- [ ] Both approval flags present for Amazon/Alza: `--approve-demo-execution` AND `--approve-public-readonly-execution`
- [ ] No credential flags passed (`--password`, `--token`, etc.)
- [ ] Review `playwright-report/index.html` after run
- [ ] Check `test-results/` for screenshots/videos/traces on failures

**Commands:**
```bash
# List available profiles (no approval required)
python tools/run_browser_execution.py --project-id my-project --command-mode list

# Amazon/Alza readonly smoke (both approval flags required)
python tools/run_browser_execution.py \
    --project-id my-project \
    --readonly-profile \
    --command-mode readonly_smoke \
    --approve-demo-execution \
    --approve-public-readonly-execution \
    --scaffold-root outputs/amazon-alza-viewport/03_framework/playwright

# Run Playwright directly in the scaffold
cd outputs/amazon-alza-viewport/03_framework/playwright
npx playwright test tests/smoke --config playwright.config.cjs --reporter=list
```

**Reporting artifacts (under scaffold root):**
```
playwright-report/index.html        # HTML report (always generated)
test-results/*/test-failed-*.png    # Screenshots (on failure only)
test-results/*/video.webm           # Video (retained on failure)
test-results/*/trace.zip            # Trace (retained on failure)
```

**Safety invariants:**
- `captcha_bypass_allowed=False` — hardcoded, cannot be changed
- `personal_accounts_blocked=True`, `production_accounts_blocked=True` — hardcoded
- Ecommerce dual-approval: both `--approve-demo-execution` AND `--approve-public-readonly-execution`
- No credentials, no auth, no checkout, no form submission

### 39. API Contract Importer (Phase 5M)

**Purpose:** Parse OpenAPI/Postman spec files into a classified endpoint inventory.
No approval flag needed — reads local files only, no network calls.

**Checklist:**
- [ ] Spec file is local (JSON/YAML/Postman collection)
- [ ] Review `api_contract_summary.md` — check safety classifications
- [ ] Review `risky_endpoints.json` — verify requires_approval and blocked lists

**Command:**
```bash
python tools/import_api_contract.py \
    --project-id my-project \
    --spec-file path/to/openapi.json
```

### 40. API Test Generator (Phase 5M)

**Purpose:** Generate Playwright API test skeleton files from an APIContractReport.
All output is planning-only — `executable_without_approval=False`.

**Checklist:**
- [ ] `25_api_contract/api_contract_inventory.json` exists
- [ ] Review generated `.spec.ts` files before running
- [ ] Do NOT auto-execute without human review

**Command:**
```bash
python tools/generate_api_tests.py \
    --project-id my-project \
    --contract-report-path outputs/my-project/25_api_contract/api_contract_inventory.json
```

### 41. CI/CD Builder (Phase 5M)

**Purpose:** Generate GitHub Actions or GitLab CI workflow for running Playwright
smoke tests. Generated configs are planning artifacts — must be copied manually.

**Checklist:**
- [ ] Review generated workflow YAML before committing
- [ ] Replace placeholder comments with real secrets via CI/CD platform secret stores
- [ ] Do NOT auto-commit or auto-push — copy manually to your repository

**Commands:**
```bash
# GitHub Actions
python tools/build_cicd_config.py \
    --project-id my-project \
    --platform github_actions \
    --scaffold-root outputs/my-project/03_framework/playwright

# GitLab CI
python tools/build_cicd_config.py \
    --project-id my-project \
    --platform gitlab_ci
```

**Output artifacts:**
```
outputs/<project_id>/27_cicd/github-actions-qa-smoke.yml
outputs/<project_id>/27_cicd/cicd_summary.md
outputs/<project_id>/27_cicd/cicd_manifest.json
```

**Safety invariants:**
- `auto_pr_creation_allowed=False` — no auto-commit, copy manually
- `client_repo_writeback_allowed=False` — no repo write-back
- `production_deploy_allowed=False` — no deployment steps generated

---

## Section 43 — Phase 5P: Client Delivery Pack

**Purpose:** Generate a client-ready delivery package from previous phase outputs.

**Generate a delivery pack:**
```bash
python tools/create_client_delivery_pack.py \
    --project-id my-project \
    --include-generated-tests \
    --include-cicd
```

**Dry run (no files written):**
```bash
python tools/create_client_delivery_pack.py --project-id my-project --no-write
```

**Output directory:** `outputs/<project_id>/28_client_delivery/`

**Delivery artifacts generated:**

| File | Description |
|------|-------------|
| `QA_Report.md` | Full 11-section QA report |
| `QA_Report.html` | HTML version for browser viewing |
| `Bug_Report.md` | Defect report template |
| `Test_Cases.csv` | Structured test cases with status |
| `Risk_Matrix.md` | Risk matrix with severity/mitigation |
| `Recommendations.md` | Automation and CI/CD recommendations |
| `Evidence_Index.md` | Evidence artifact index with checklist |
| `Delivery_Checklist.md` | Pre-delivery checklist (all unchecked) |
| `client_delivery_manifest.json` | Manifest with safety flags and scan result |
| `client_delivery.zip` | ZIP of all artifacts |

**Before sending to client:**
1. Complete all items in `Delivery_Checklist.md`
2. Verify `client_delivery_manifest.json`: `secret_scan.scan_passed=true`
3. Customize all placeholder sections in `QA_Report.md`
4. Obtain QA Lead sign-off
5. Verify no sensitive data in evidence files

**Safety invariants:**
- `approved_for_client_delivery=False` — requires manual sign-off
- `auto_send_to_client=False` — never sends automatically
- Secret scan excludes storageState, .env, credentials, cookies, tokens from ZIP

---

## Section 42 — Phase 5M-R: Demo Workflow Validation

**Purpose:** Validate the full Phase 5M pipeline against realistic fixture specs.

**Fixture specs** (`fixtures/demo_specs/`):

| File | Format | Coverage |
|------|--------|----------|
| `petstore_openapi.json` | OpenAPI 3.0 JSON | GET/POST/PUT/HEAD/OPTIONS |
| `sample_openapi.yaml` | OpenAPI 3.0 YAML | GET/POST/PATCH |
| `risky_api_openapi.json` | OpenAPI 3.0 JSON | DELETE/payment/admin/refund |
| `postman_sample.json` | Postman v2.1 | GET/POST/DELETE, /health, /payment/charge |

**Run demo tests:**
```bash
python -m pytest tests/test_phase5mr_demo_workflow.py -v
```

**Key classification rules validated:**
- DELETE method → always `blocked_by_default` (regardless of path)
- POST /payments/charge → `blocked_by_default` (payment term in path)
- POST /payments/refund → `blocked_by_default` (refund term in path)
- POST /account/deactivate → `blocked_by_default` (deactivate term in path)
- DELETE /admin/users → `blocked_by_default` (DELETE + admin term)
- GET /health → `safe_readonly`
- GET /users, GET /products → `safe_readonly`
- POST /users → `requires_approval`

**CI/CD hardening verified programmatically:**
- No `password:` in workflow YAML
- No `api_key:` in workflow YAML
- No `deploy` step
- No `git push` command
- No `gh pr create` or `create-pull-request` action
- `upload-artifact` step present
- `smoke` keyword present

**Safety invariants:**
- All classification is done before any test generation
- No network calls in any Phase 5M component (local fixture files only)
- `blocked_by_default` endpoints never appear as executable `test()` blocks

---

## Section 44 — Phase 5N: Accessibility + Performance + Passive Security

### Purpose

Generate and optionally execute accessibility, performance, and passive security smoke checks.
Default mode is always skeleton-only (no network). Approved execution requires explicit flags.

### Accessibility Smoke

**Step 1 — Generate skeleton spec (no network):**
```bash
python tools/run_accessibility_smoke.py \
  --project-id <id> \
  --target-url https://staging.example.com \
  --wcag-level AA
```

**Step 2 — Review generated spec:**
- Check `outputs/<id>/29_accessibility/accessibility_smoke.generated.spec.ts`
- Verify WCAG level, target URL, and check list
- Confirm no unexpected URLs or checks

**Step 3 (optional) — Approved execution:**
```bash
python tools/run_accessibility_smoke.py \
  --project-id <id> \
  --target-url https://staging.example.com \
  --execute \
  --approve-public-readonly-execution \
  --approve-browser-execution
```

Then run: `npx playwright test accessibility_smoke.generated.spec.ts --grep @accessibility`

**Outputs:** `accessibility_report.json` | `accessibility_summary.md` | `accessibility_violations.csv`

---

### Performance Smoke

**Step 1 — Generate skeleton spec:**
```bash
python tools/run_performance_smoke.py \
  --project-id <id> \
  --target-url https://staging.example.com \
  --endpoints / /about /products
```

**Step 2 — Review thresholds** in `performance_summary.md` (LCP<2500ms, FCP<1800ms, TTFB<800ms).

**Step 3 (optional) — Approved execution:**
```bash
python tools/run_performance_smoke.py \
  --project-id <id> --target-url https://staging.example.com \
  --execute --approve-public-readonly-execution --approve-browser-execution
```

Then run: `npx playwright test performance_smoke.generated.spec.ts --grep @performance`

**Outputs:** `performance_report.json` | `performance_summary.md` | `slow_resources.json`

---

### Passive Security Smoke (can execute without browser)

**Step 1 — Generate skeleton spec:**
```bash
python tools/run_passive_security_smoke.py \
  --project-id <id> \
  --target-url https://staging.example.com
```

**Step 2 — Approved execution (real HEAD request):**
```bash
python tools/run_passive_security_smoke.py \
  --project-id <id> \
  --target-url https://staging.example.com \
  --execute \
  --approve-public-readonly-execution
```

**Outputs:** `passive_security_report.json` | `passive_security_summary.md` | `security_headers.json`

**OWASP headers checked:** HSTS, CSP, X-Content-Type-Options, X-Frame-Options, Referrer-Policy

---

### Safety checklist

- [ ] No `--active-scan`, `--exploit`, `--bypass-auth`, `--load-test`, `--fuzzing` flags used
- [ ] `human_review_required=True` in all output JSON files
- [ ] Status field shows `planning_only` for skeleton-only runs
- [ ] Delivery report shows "Generated checks only; execution requires approval" for planning_only
- [ ] No credentials in any generated spec or report file

---

## Section 45 — Phase 5O: Flaky Test Analyzer + Self-Healing Proposals

**Purpose:** Static analysis of Playwright spec files to detect flakiness, classify selector stability, and generate self-healing proposals. No browser, no network, no auto-apply.

### Analyze flakiness risks

```bash
python tools/run_flaky_test_analyzer.py \
  --project-id my-project \
  --spec-files tests/smoke/login.spec.ts tests/smoke/checkout.spec.ts
```

**Outputs:** `flaky_test_analysis.json` | `Flaky_Test_Analysis_Report.md` | `selector_stability.json` | `Selector_Stability_Report.md` | `self_healing_proposals.json` | `Self_Healing_Proposals.md`

### Auto-discover specs (outputs_root scan)

```bash
python tools/run_flaky_test_analyzer.py \
  --project-id my-project \
  --outputs-root outputs/
```

### Dry run (no file output)

```bash
python tools/run_flaky_test_analyzer.py \
  --project-id my-project \
  --spec-files tests/smoke/login.spec.ts \
  --no-write
```

### Apply healing proposals (TODO comments, review first)

```bash
# Step 1: review Self_Healing_Proposals.md
# Step 2: apply with explicit approval
python tools/run_flaky_test_analyzer.py \
  --project-id my-project \
  --spec-files tests/smoke/login.spec.ts \
  --apply-proposals \
  --approve-code-modification
```

**Apply mode inserts TODO comments at affected lines only — does not auto-replace code.**

### Safety checklist

- [ ] No `--auto-fix`, `--skip-human-review`, `--approve-delivery`, `--force-apply` flags used
- [ ] `human_review_required=True` in all output JSON files
- [ ] `code_modification_allowed=False` in all reports before applying
- [ ] Reviewed `Self_Healing_Proposals.md` before running `--apply-proposals`
- [ ] No production spec files modified without code review

---

## Section 46 — Phase 6: QA Factory MCP Server

**Purpose:** Expose QA Factory as an MCP server for Claude Desktop / VS Code / Claude Code.
All tools default to safe mode. Execution requires explicit approval flags per tool call.

### Setup

```bash
pip install mcp
```

### Verify tools available (no mcp needed)

```bash
python tools/run_mcp_server.py --list-tools
python tools/run_mcp_server.py --demo-health
```

### Start MCP server

```bash
python tools/run_mcp_server.py
```

### Claude Desktop config (`~/Library/Application Support/Claude/claude_desktop_config.json`)

```json
{
  "mcpServers": {
    "qa-factory": {
      "command": "python",
      "args": ["D:/path/to/ai-qa-factory/tools/run_mcp_server.py"]
    }
  }
}
```

### Tool call examples (via Claude interface)

**Health check:**
```json
{ "tool": "qa_factory_health", "arguments": {} }
```

**Flaky test analysis:**
```json
{
  "tool": "run_flaky_test_analysis",
  "arguments": {
    "project_id": "demo_quality_audit",
    "spec_files": ["fixtures/demo_quality_audit/playwright_specs/flaky_test.spec.ts"],
    "write_files": false
  }
}
```

**Delivery pack (write to outputs):**
```json
{
  "tool": "generate_delivery_pack",
  "arguments": { "project_id": "demo_quality_audit", "write_files": true }
}
```

### Safety checklist

- [ ] No `--approve-delivery`, `--skip-review`, `--auto-start-browser`, `--credentials` flags used
- [ ] No credentials passed as tool arguments
- [ ] `human_review_required=True` in all tool responses
- [ ] `approved_for_client_delivery=False` in delivery pack response
- [ ] `apply_self_healing_fixes` reviewed in dry_run mode before setting `dry_run=false`

---

## Section 47 — Phase 6.1: One-Command Client Audit

**Purpose:** Run a full client QA audit with a single command using existing modules.

### Run safe audit (planning mode)

```bash
python tools/run_client_audit.py --project-id my-demo --mode safe_audit --no-write
```

### Run with spec file (adds API contract import)

```bash
python tools/run_client_audit.py \
  --project-id client-x --spec-file openapi.json --mode safe_audit
```

### Run API-only mode

```bash
python tools/run_client_audit.py \
  --project-id api-audit --spec-file openapi.json --mode api_only
```

### Delivery-only mode (existing outputs)

```bash
python tools/run_client_audit.py --project-id existing --mode delivery_only
```

### Validate 106 tests

```bash
python -m pytest tests/test_phase6_1_client_audit_workflow.py -q
```

### Safety checklist

- [ ] Blocked flags (`--auto-approve-all`, `--skip-human-review`, `--force-deliver`) reject and exit 1
- [ ] Preflight plan printed before any module runs
- [ ] `human_review_required=True` in run report JSON
- [ ] `approved_for_client_delivery=False` in run report JSON
- [ ] No credentials in any JSON or Markdown output
- [ ] `33_client_audit/` dir created with plan + preflight + run report + summary

---

## Section 48 — Phase 6-R: MCP Demo Workflow

**Purpose:** End-to-end validation of all 7 MCP tool handlers against demo fixtures.

### Run demo (dry run)

```bash
python tools/run_mcp_demo_workflow.py --no-write
```

### Run demo (write artifacts)

```bash
python tools/run_mcp_demo_workflow.py --project-id mcp-demo --outputs-root outputs
```

### Inspect full JSON output

```bash
python tools/run_mcp_demo_workflow.py --no-write --json-output
```

### Validate all 49 demo tests

```bash
python -m pytest tests/test_phase6r_mcp_demo_workflow.py -q
```

### Safety checklist

- [ ] Blocked flags (`--approve-delivery`, `--skip-review`, `--force-apply`) reject and exit 1
- [ ] All 7 steps complete; step 7 (`apply_self_healing_fixes`) returns `blocked`
- [ ] `human_review_required=True` in all 7 tool results
- [ ] No credentials in any JSON output
- [ ] Spec fixtures not modified after blocked apply

---

## Section 49 — Phase 6.2: Structured Finding Schema + Risk Matrix

**Purpose:** Verify that `Finding` schema, `RiskMatrix`, and adapters work correctly.
No new CLI commands — Phase 6.2 enriches `run_client_audit.py` output.

### Validate 98 Phase 6.2 tests

```bash
python -m pytest tests/test_phase6_2_finding_schema.py -q
```

### Inspect structured findings in audit output

```bash
python tools/run_client_audit.py \
  --project-id demo \
  --spec-file fixtures/demo_specs/petstore_openapi.json \
  --no-write \
  --json-output
```

Look for `structured_findings`, `total_findings`, `risk_summary` in JSON output.

### Inspect Risk Matrix section in summary.md

After a write run, check `outputs/<project-id>/33_client_audit/client_audit_summary.md`
for `## Risk Matrix` section.

### Safety checklist

- [ ] Empty input to adapters returns `[]` (no fake findings)
- [ ] `RiskMatrix.sorted_by_risk()` is deterministic (same input = same order)
- [ ] `by_severity()` always returns all 5 severity keys
- [ ] `structured_findings` in JSON is list of dicts (serialized via `to_dict()`)
- [ ] `findings: int` backward-compat field still present alongside new fields
- [ ] No credentials in any Finding field

---

## Section 50 — Phase 6.3: Client Delivery Report v1

**Purpose:** Verify that `client_report.md` is generated correctly and is client-ready.

### Validate 83 Phase 6.3 tests

```bash
python -m pytest tests/test_phase6_3_client_delivery_report.py -q
```

### Generate report in dry-run mode (no files written)

```bash
python tools/run_client_audit.py \
  --project-id demo \
  --spec-file fixtures/demo_specs/petstore_openapi.json \
  --no-write
```

### Generate and inspect client_report.md

```bash
python tools/run_client_audit.py \
  --project-id report-demo \
  --spec-file fixtures/demo_specs/petstore_openapi.json

# Report path is printed at the end of the run:
# Client report: outputs/report-demo/33_client_audit/client_report.md
```

### Safety checklist

- [ ] `client_report.md` contains DRAFT notice
- [ ] `client_report.md` contains `approved_for_client_delivery = False`
- [ ] All 12 sections present in the report
- [ ] `--no-write` run produces no `client_report.md`
- [ ] No fake findings in report when modules ran in planning_only mode
- [ ] `approved_for_client_delivery` remains False after report generation

---

## Phase 7A — Auth Capability Planner Runbook

### Run auth capability planning (no execution)

```bash
# Basic plan (all methods classified, no inputs)
python tools/plan_auth_capability.py --project-id demo --no-write

# With dedicated test account + password env var
python tools/plan_auth_capability.py \
  --project-id myproject \
  --has-dedicated-test-account \
  --password-env-var QA_PASSWORD

# With Google test account + existing storageState
python tools/plan_auth_capability.py \
  --project-id myproject \
  --has-google-account \
  --has-storage-state

# With API token env var + full JSON output
python tools/plan_auth_capability.py \
  --project-id myproject \
  --api-token-env-var QA_API_TOKEN \
  --no-write \
  --json-output
```

### Reading the output

Readiness markers in the summary:
- `[ok]` — allowed now, all required inputs present
- `[plan]` — planning only, no executable path
- `[blocked]` — blocked by safety rules
- `[manual]` — requires a manual step before automation
- `[need-account]` — dedicated test account required
- `[need-env]` — env var secret must be configured
- `[need-confirm]` — client must confirm before proceeding

### Safety checklist

- [ ] No raw secrets in any CLI flag (only `--*-env-var NAME` accepted)
- [ ] Blocked flags (`--password`, `--secret`, `--token`, etc.) exit 1 before argparse
- [ ] `personal_account_allowed` is always `False` in output JSON
- [ ] `production_account_allowed` is always `False` in output JSON
- [ ] `captcha_bypass_allowed` is always `False` in output JSON
- [ ] `auth_bypass_allowed` is always `False` in output JSON
- [ ] `human_review_required` is always `True` in output JSON

---

## Phase 7B — Auth Strategy Selector Runbook

### Select strategy from existing 7A plan

```bash
python tools/select_auth_strategy.py \
  --project-id myproject \
  --plan-file outputs/myproject/34_auth_capability/auth_capability_plan.json \
  --no-write
```

### Select strategy inline (runs planner internally)

```bash
# With API token -- should produce ready_for_execution + api_token_runner
python tools/select_auth_strategy.py \
  --project-id myproject \
  --api-token-env-var QA_API_TOKEN \
  --no-write

# With Google test account + storageState -- should produce ready_for_execution + google_oauth_runner
python tools/select_auth_strategy.py \
  --project-id myproject \
  --has-google-account \
  --has-storage-state \
  --no-write --json-output
```

### Reading the decision output

- `decision_status: ready_for_execution` + `safe_to_execute: true` → run `next_runner`
- `decision_status: missing_required_input` → check `missing_inputs` list, provide them, re-run
- `decision_status: planning_only` → no runner available for these methods yet
- `decision_status: blocked` → safety invariants block all methods

### Safety checklist

- [ ] `raw_secrets_allowed` is always `False` in output JSON
- [ ] `browser_execution_allowed` is always `False` in output JSON
- [ ] `credential_usage_allowed` is always `False` in output JSON
- [ ] `personal_account_allowed` is always `False` in output JSON
- [ ] `captcha_bypass_allowed` is always `False` in output JSON
- [ ] `human_review_required` is always `True` in output JSON
- [ ] `safe_to_execute` is `True` only when `decision_status == ready_for_execution`

---

## 7C. Running Google OAuth StorageState Smoke

### Prerequisites

1. Capture storageState manually (one time, or when session expires):
   ```bash
   cd outputs/amazon-alza-viewport/03_framework/playwright
   node capture_google.cjs
   ```
   - Edge opens with automation detection disabled
   - Log in with the dedicated test account (email → password → any 2FA/verification)
   - **CRITICAL: Wait until you see the Google Account page (name + avatar fully loaded)**
   - **Only then** come back to the terminal and press Enter
   - File saved to `storage_state_google.json` in project root

   > If you press Enter while still on the Sign In form, the storageState will be unauthenticated. The smoke will show the Sign In page and report `status: failed`. Re-capture if this happens.

2. `storage_state_google.json` is gitignored via `storage_state_*.json` pattern — never commit it.

### Planning-only run (no storageState required)

```bash
python tools/run_google_oauth_smoke.py --project-id my_project
```

### Execution run — headless (CI/default)

```bash
python tools/run_google_oauth_smoke.py \
  --project-id my_project \
  --storage-state-path storage_state_google.json \
  --target-url https://accounts.google.com \
  --dedicated-test-account-confirmed \
  --google-test-account-confirmed \
  --approve-execution
```

### Execution run — headed (visual verification)

```bash
python tools/run_google_oauth_smoke.py \
  --project-id my_project \
  --storage-state-path storage_state_google.json \
  --target-url https://accounts.google.com \
  --dedicated-test-account-confirmed \
  --google-test-account-confirmed \
  --approve-execution \
  --headed
```
Browser opens visibly, stays open for 5 seconds so you can confirm the logged-in account page (not the Sign In form), saves screenshot, closes.

### Reading the result

- `status: passed` → OAuth session valid, HTTP 200, screenshot saved — session is live
- `status: planning_only` → storageState not present; run capture first
- `status: blocked` → `--approve-execution` missing, or URL not allowlisted
- `status: failed` → smoke failed — check `smoke_results` stderr in report JSON; likely session expired, re-capture

### Safety checklist (7C)

- [ ] `raw_secrets_allowed` is `False` in all output JSON
- [ ] `storage_state_content_read` is `False` in all output JSON
- [ ] `captcha_bypass_allowed` is `False` in all output JSON
- [ ] `personal_account_allowed` is `False` in all output JSON
- [ ] `production_account_allowed` is `False` in all output JSON
- [ ] `human_review_required` is `True` in all output JSON
- [ ] storageState file is not committed to git
- [ ] Only dedicated test account credentials used (never personal/production)

---

## 7D. Running Email/Password Auth Smoke (OrangeHRM demo)

**Purpose:** Verify email/password login flow using dedicated test credentials stored in env vars.

### Prerequisites

1. Set credentials at OS level (never via CLI):
   ```powershell
   $env:ORANGEHRM_USERNAME = "your_test_username"
   $env:ORANGEHRM_PASSWORD = "your_test_password"
   ```
2. Confirm you are using a **dedicated test account** (never personal, never production).
3. Playwright scaffold with `node_modules/` must exist (run Phase 3A setup if not).

### Step-by-step

**Step 1 — check readiness (plan only):**
```bash
python tools/run_email_password_smoke.py --project-id my_project
```
Look for `mode_readiness: executable` and no blockers.

**Step 2 — run the smoke:**
```bash
python tools/run_email_password_smoke.py \
  --project-id my_project \
  --dedicated-test-account-confirmed \
  --approve-execution
```

**Step 3 — check artifacts:**
- `outputs/my_project/37_email_password_auth/email_password_plan.json`
- `outputs/my_project/37_email_password_auth/email_password_report.json`
- `outputs/my_project/37_email_password_auth/email_password_summary.md`

### Interpreting results

- `status: passed` → Login succeeded, URL reached dashboard suffix
- `status: planning_only` → Env vars not set or prerequisites missing
- `status: blocked` → `--approve-execution` not set
- `status: failed` → Login failed — check `smoke_results` in report JSON; verify credentials in env and that OrangeHRM demo is accessible

### Safety checklist (7D)

- [ ] `raw_secrets_allowed` is `False` in all output JSON
- [ ] `credential_logging_allowed` is `False` in all output JSON
- [ ] `captcha_bypass_allowed` is `False` in all output JSON
- [ ] `personal_account_allowed` is `False` in all output JSON
- [ ] `production_account_allowed` is `False` in all output JSON
- [ ] `human_review_required` is `True` in all output JSON
- [ ] `approved_for_client_delivery` is `False` in report JSON
- [ ] No credential values appear in artifacts, logs, or stdout
- [ ] Only dedicated test account used (never personal/production)

---

## 7R. Running the Auth Demo Workflow

**Purpose:** Validate the full auth workbench (7A→7B→7C→7D) end-to-end and generate an Authentication Coverage section for the client report. No real credentials or storageState required.

### Step-by-step

**Step 1 — run the demo:**
```bash
python tools/run_auth_demo_workflow.py
```
Or with a custom project id:
```bash
python tools/run_auth_demo_workflow.py --project-id my-project
```

**Step 2 — check artifacts:**
```
outputs/demo-auth-workflow/
  33_client_audit/client_report.md        ← Authentication Coverage section
  34_auth_capability/auth_capability_plan.json
  35_auth_strategy/auth_strategy_decision.json
  16_google_oauth/google_oauth_report.json
  37_email_password_auth/email_password_report.json
```

**Step 3 — review client_report.md:**
Open `33_client_audit/client_report.md`. Verify:
- Executed section says "none — demo mode"
- Planned section lists 7A and 7B results
- Skipped section lists Google OAuth and Email/Password (missing prerequisites)
- Blocked section lists 4 safety invariant cases
- Safety boundary table shows all flags as `False` / `True`
- `approved_for_client_delivery=False` and `human_review_required=True`

### Interpreting results

| Category | Meaning |
|---|---|
| `planned` | Auth method identified by 7A/7B; planning artifacts produced |
| `skipped` | Method known but prerequisites missing (no storageState, no env vars) |
| `blocked` | Safety invariant prevents execution (personal account, raw password, etc.) |
| `executed` | Actual auth smoke ran successfully (requires real credentials — not in demo mode) |

### Safety checklist (7R)

- [ ] `approved_for_client_delivery` is `False` in demo result JSON
- [ ] `human_review_required` is `True` in demo result JSON
- [ ] No credential values in any artifact
- [ ] All 4 safety blocked cases present in client_report.md
- [ ] client_report.md labelled as "Draft"

---

## ARK universal work planning (Phase 8.1, planning-only)

Use `python main.py work` to turn a brief into a reviewable plan. It never executes.

1. Provide the brief via exactly one of `--input <file>` / `--text "..."` / `--stdin`.
2. Give a safe `--project-id` (no separators, not absolute).
3. Read the outputs under `outputs/<project_id>/40_ark_work/`:
   - `WORK_SUMMARY.md` — human overview (profile, state, counts).
   - `NEXT_ACTION.md` — what to provide/approve next.
   - `APPROVALS_REQUIRED.md` — unresolved approvals (nothing is granted).
   - `CAPABILITY_PLAN.json` / `TOOLCHAIN_PLAN.json` — planned capabilities/steps (MCP steps
     stay unresolved until Phase 8.3 discovery; no tool names are fabricated).
4. Review the plan. Execution is a later, separately-gated phase.

**Checklist:**
- [ ] Run state is `PLANNED`, `WAITING_FOR_INFORMATION`, or `WAITING_FOR_APPROVAL` (never executing)
- [ ] MCP steps show empty `tool_name` and `availability_verified=false`
- [ ] `MCP_CONFIGURED_SERVERS_SNAPSHOT.json` has `live_discovery_performed=false`
- [ ] No secrets in any artifact (content scan runs before publish)
- [ ] Artifacts confined to `outputs/<project_id>/40_ark_work/`

---

## Prospect QA Scout v1.0.1 (Phase 8.3 / 8.3.1 — bounded read-only local runtime)

`python main.py scout` runs a bounded, read-only QA vertical over explicit public seeds. It
never submits forms, logs in, sends outreach, or performs any external side effect.

**Try it (no external network, no browser):**
```bash
python main.py scout demo
```
This runs the bundled demo site end to end and writes `outputs/scout/scout-demo/report/`.

**Scan your own public sites** (each fresh run gets a unique run id):
```bash
python main.py scout run --seeds "https://a.example/,https://b.example/" --campaign my-scan
```

**Run WITH a live dashboard you can control** (the dashboard owns the run):
```bash
python main.py scout dashboard --seeds "https://a.example/" --campaign my-scan --port 8765
# then, in another terminal, drive the active run:
python main.py scout control --signal pause  --port 8765
python main.py scout control --signal resume --port 8765
python main.py scout control --signal kill   --port 8765   # global kill stops all work
```

**Watch a finished run read-only:** `python main.py scout dashboard --run-id <run_id>` — the
controls are disabled and `/api/control` returns HTTP 409 (it never fakes success).

**Live browser (optional):** `pip install playwright && python -m playwright install chromium`,
then add `--browser playwright`. Run the real-browser acceptance with
`python -m pytest -m playwright_acceptance -q`.

**Checklist:**
- [ ] Only explicit public http(s) seeds are used (localhost/private IPs rejected)
- [ ] CAPTCHA / access-prohibition prospects are `MANUAL_ACTION_REQUIRED` (no interaction)
- [ ] Every reported finding is `VERIFIED` (independently reproduced) and sanitized
- [ ] No cookie/secret/credential appears in any artifact
- [ ] Report + artifacts confined to `outputs/scout/<run_id>/`
- [ ] The dashboard is reachable only on `127.0.0.1`; the global kill stops the run
