# Operational Runbook — Guided QA Automation Workbench

**Version:** 5.1.0  
**Updated:** 2026-05-24

> **AI drafts. Senior QA decides.**

This is the daily operating guide. What to run, what to open, what to check, and what to never skip.

Docs: [`VISION.md`](VISION.md) · [`COMMANDS.md`](COMMANDS.md) · [`APPROVAL_MODEL.md`](APPROVAL_MODEL.md) · [`SAFETY_RULES.md`](SAFETY_RULES.md)

---

## 1. Before any real work

```bash
python main.py system-health          # all 26 checks must pass
.venv\Scripts\python.exe -m pytest -q # 471 passed — always mock mode
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

## 13. Agent-safe workflow

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

## 14. Archive hygiene

**Exclude from any zip or share:**
```
.env  .env.local  .venv/  __pycache__/  outputs/  test-results/
playwright-report/  node_modules/  real_jobs/  real_sites/
```

**Safe to include:** source, `sample_inputs/`, `validation_inputs/`, `docs/`, `tests/`, `requirements.txt`, `README.md`, `.env.example`

If `.env` was accidentally shared: **rotate all API keys immediately.**
