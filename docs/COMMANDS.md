# Command Reference — Guided QA Automation Workbench

**Version:** 5.1.0  
**Updated:** 2026-05-24

Status labels:
- `[implemented]` — works now
- `[planned]` — designed, not yet built
- `[placeholder]` — exists in code but not fully wired

All current commands: `python main.py <command> [options]`  
Use `.venv\Scripts\python.exe` on Windows.

---

## System commands

### `system-health` `[implemented]`

Check local readiness before any real-mode work.

```bash
python main.py system-health
```

Checks: Python packages, `.env` config, API key presence, output/memory directories, Node/npm/npx.  
Expected: all 26 checks pass.

### `capabilities` `[implemented]`

Print the capability matrix — supported project/opportunity types and support levels.

```bash
python main.py capabilities
```

### `agents` `[implemented]`

List registered agents.

```bash
python main.py agents                       # all agents
python main.py agents --workflow prescreen  # agents for one workflow
```

---

## Implemented workflow commands

### `prescreen` `[implemented]`

Fast suitability check. Run before spending time on full analysis.

```bash
python main.py prescreen --input brief.txt
python main.py prescreen --input brief.txt --source-platform upwork
python main.py prescreen --input brief.txt --require-real-llm
```

Outputs: `READ_ME_FIRST.md`, `DECISION.md`, `PRESCREENING_REPORT.md`

### `filter` `[implemented]`

Opportunity filtering and routing.

```bash
python main.py filter --input brief.txt
```

### `batch-filter` `[implemented]`

Filter a whole folder of opportunity files.

```bash
python main.py batch-filter --input real_jobs/
```

Output: `outputs/batch_opportunity_report.md`

### `upwork` `[implemented]`

Full Upwork proposal pack: routing + proposal + test design.

```bash
python main.py upwork --input brief.txt --source-platform upwork --require-real-llm
```

Outputs: `proposal.md`, `screening_answers.md`, `evidence_needed.md`, `commercial_strategy.md`

### `plan` `[implemented]`

Lightweight test planning — strategy + plan without full routing or proposals.

```bash
python main.py plan --input brief.txt --require-real-llm
```

### `test-design` `[implemented]`

Generate test strategy, test plan, and test cases.

```bash
python main.py test-design --input brief.txt --require-real-llm
```

Outputs: `TEST_STRATEGY.md`, `TEST_PLAN.md`, `TEST_CASES.md`

### `scaffold` `[implemented]`

Generate a complete Playwright TypeScript test framework from a brief.

```bash
python main.py scaffold --input brief.txt --require-real-llm
```

Output: `outputs/<id>/framework/` — full npm project (tsconfig, playwright.config.ts, specs, CI workflow)

### `audit` `[implemented]`

SaaS / compliance audit workflow.

```bash
python main.py audit --input brief.txt --require-real-llm
```

### `review` `[implemented]`

Review a test file or code file for quality, brittleness, and improvement suggestions.

```bash
python main.py review --input tests/smoke.spec.ts
```

### `delivery` `[implemented]`

Generate delivery documentation for completed work.

```bash
python main.py delivery --input brief.txt --require-real-llm
```

### `full` `[implemented]`

Complete end-to-end workflow: routing + proposal + test design + scaffold + delivery notes.

```bash
python main.py full --input brief.txt --require-real-llm
```

### `run-tests` `[implemented]`

Safely run tests for a generated Playwright or pytest project.

```bash
python main.py run-tests --project-path outputs/<id>/framework --kind playwright
python main.py run-tests --project-path outputs/<id> --kind pytest
```

### `ask` `[implemented]`

Ask a question about a saved project (uses persisted state).

```bash
python main.py ask --project-id <id> --question "Why apply_selectively?"
python main.py ask --project-id <id>   # interactive REPL
```

### `mcp-guide` `[implemented]`

Generate MCP integration guide.

```bash
python main.py mcp-guide --input brief.txt
```

---

## Execution mode flags `[implemented]`

These flags work with any workflow command.

| Flag | Effect |
|---|---|
| `--auto` | Run all agents without pauses (default) |
| `--step` | Pause between agents for inline feedback |
| `--dry-run` | Run without writing final output files |
| `--only <agent>` | Run only one specific agent |
| `--from-step <agent>` | Resume workflow from a specific agent |
| `--project-id <id>` | Resume a previously saved project |
| `--approve` | Mark as pre-approved (skips HUMAN_REVIEW_REQUIRED gate) |
| `--require-real-llm` | Fail if LLM_MODE=mock |
| `--allow-mock` | Allow mock despite --require-real-llm |
| `--client-id <id>` | Link a client memory context |
| `--source-platform <p>` | Force source platform hint |

---

## Planned commands — client project workflow

These commands are designed for the new client project workflow (Phase 4+). They do not exist yet.

### `init-project` `[planned]`

Initialize a new client project with structured intake.

```bash
python main.py init-project --name "Client ABC - SaaS Audit"
```

Creates: `projects/<id>/` directory, project config, PROJECT_BLUEPRINT.md skeleton.

### `intake` `[planned]`

Interactive intake wizard. Asks structured questions when info is missing.

```bash
python main.py intake --input brief.txt
# or interactively:
python main.py intake
```

Produces: `PROJECT_INTAKE_CHECKLIST.md`, pre-populated `PROJECT_BLUEPRINT.md`

### `classify-inputs` `[planned]`

Classify all inputs provided: text briefs, URLs, screenshots, archives.

```bash
python main.py classify-inputs --input brief.txt --url https://app.example.com
```

Produces: `INPUT_MAP.md` — what each input is (task source vs. target vs. API docs vs. unknown)

### `blueprint` `[planned]`

Build or update the Project Blueprint from classified inputs.

```bash
python main.py blueprint --project-id <id>
```

Produces: `PROJECT_BLUEPRINT.md` — structured source of truth for the project

### `strategy` `[planned]`

Generate the strategic QA plan from the Project Blueprint.

```bash
python main.py strategy --project-id <id>
```

Produces: `QA_STRATEGY.md`, `RISK_MATRIX.md`

### `tactical-plan` `[planned]`

Generate test cases and automation plan from the strategy.

```bash
python main.py tactical-plan --project-id <id>
```

Produces: `TEST_PLAN.md`, `TEST_CASES.md`, `AUTOMATION_PLAN.md`

### `status` `[planned]`

Show current project status — what phase it's in, what's been approved, what's pending.

```bash
python main.py status --project-id <id>
```

### `explain` `[planned]`

Explain a decision, recommendation, or generated artifact in plain language.

```bash
python main.py explain --project-id <id> --artifact TEST_STRATEGY.md
python main.py explain --project-id <id> --decision "Why playwright over cypress?"
```

### `approval-board` `[planned]`

Show all pending approval decisions for a project.

```bash
python main.py approval-board --project-id <id>
```

### `next-action` `[planned]`

Show the next recommended action for the project based on current state.

```bash
python main.py next-action --project-id <id>
```

### `approve-action` `[planned]`

Approve a specific pending action, enabling it to proceed.

```bash
python main.py approve-action --project-id <id> --action run-against-staging
```

### `reject-action` `[planned]`

Reject a pending action and record the reason.

```bash
python main.py reject-action --project-id <id> --action run-against-staging --reason "Scope not confirmed"
```

### `run-local` `[planned]`

Run safe local validation on a generated scaffold.

```bash
python main.py run-local --project-id <id>
# Runs: TypeScript compile, lint, playwright --dry-run
# Never touches external URLs
```

### `run-approved` `[planned]`

Run approved external tests after an `approve-action` has been recorded.

```bash
python main.py run-approved --project-id <id> --action run-against-staging
```

### `collect-evidence` `[planned]`

Gather evidence from a test run and structure it for the report.

```bash
python main.py collect-evidence --project-id <id> --run-dir outputs/<id>/test-results/
```

Produces: `EVIDENCE.md`, evidence log with screenshots, traces, and pass/fail counts

### `report` `[planned]`

Generate a report from the current project state and evidence.

```bash
python main.py report --project-id <id> --kind internal
python main.py report --project-id <id> --kind client   # requires prior approval
```

### `delivery-check` `[planned]`

Run pre-delivery checks on a client-facing report.

```bash
python main.py delivery-check --project-id <id>
```

Checks: no mock content, no internal notes, no invented claims, all quality gate checks pass.

### `validate-project` `[planned]`

Validate that a project's artifacts are consistent and complete.

```bash
python main.py validate-project --project-id <id>
```

### `validate-schemas` `[planned]`

Validate all structured schema files against their expected shape.

```bash
python main.py validate-schemas
```

### `doctor` `[planned]`

Deep diagnostic — check system, project, schema, and artifact consistency.

```bash
python main.py doctor
python main.py doctor --project-id <id>
```

---

## `--source-platform` values `[implemented]`

| Value | Use for |
|---|---|
| `upwork` | Upwork job post |
| `fiverr` | Fiverr buyer request |
| `peopleperhour` | PeoplePerHour |
| `contra` | Contra project |
| `linkedin_direct` | LinkedIn DM or direct lead |
| `writing_platform` | nDash, Draft.dev, TestMu, etc. |
| `direct_b2b` | Client email / direct B2B brief |
| `ai_evaluator` | Evaluator platform |
| `unknown` | Default |

---

## Commands that do NOT exist

| Wrong | Correct |
|---|---|
| `python -m ai_qa_factory` | `python main.py <mode>` |
| `--brief` | `--input` |
| `python main.py opportunity` | `python main.py prescreen` |
| Auto-execute against staging URL | Use `run-approved` (planned) after `approve-action` |
| Auto-send to client | Manual — workbench never auto-sends |
