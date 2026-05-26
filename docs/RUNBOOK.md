# Operational Runbook — Guided QA Automation Workbench

**Version:** 5.6.0  
**Updated:** 2026-05-25

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
