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

> Phase 2A/2B implementation available as a direct script: `python tools/classify_inputs.py`

### `blueprint` `[planned]`

Build or update the Project Blueprint from classified inputs via `main.py`.

```bash
python main.py blueprint --project-id <id>
```

Produces: `PROJECT_BLUEPRINT.md` — structured source of truth for the project

> Phase 2B implementation available as `python tools/classify_inputs.py --with-blueprint`

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

### `auth-plan` `[planned]`

Generate an authentication flow test plan from a project blueprint.

```bash
python main.py auth-plan --project-id <id>
```

Produces: `AUTH_FLOW_PLAN.md`, `AuthFlowPlan` schema object. Requires prior approval gate for credential use.

### `auth-check` `[planned]`

Run a single auth check step (read-only, smoke mode) after approval.

```bash
python main.py auth-check --project-id <id> --step <step-id>
```

Requires: `AuthFlowPlan.approved = True`, `CredentialUseApproval.approved = True`. Result stored as `AuthCheckResult`.

### `run-auth-smoke` `[planned]`

Run the full approved auth smoke suite for a project.

```bash
python main.py run-auth-smoke --project-id <id>
```

Requires: all approval gates in `AuthFlowPlan` and `CredentialPolicy` satisfied. Never runs against production without explicit production read-only approval.

### `credentials-status` `[planned]`

Show credential reference status for a project — what is referenced, what is approved, what is missing.

```bash
python main.py credentials-status --project-id <id>
```

Shows: credential types, storage modes, approval status. Never shows actual secret values.

### `redaction-check` `[planned]`

Scan generated artifacts for possible secret leaks before client delivery.

```bash
python main.py redaction-check --project-id <id>
```

Produces: `RedactionReport`. Blocks client delivery if `possible_secret_leaks_found = True`. No actual secret values are printed in output.

### `integration-status` `[planned]`

Show integration policy and endpoint status for a project.

```bash
python main.py integration-status --project-id <id>
```

Shows: enabled integrations, approval status, provider list. Never shows actual URLs, tokens, or secrets.

### `integration-policy` `[planned]`

View or set the integration policy for a project.

```bash
python main.py integration-policy --project-id <id>
```

Produces: `IntegrationPolicy` status report.

### `integration-event-preview` `[planned]`

Preview what event payload would be sent for a given workbench event type. Dry-run only — no external calls.

```bash
python main.py integration-event-preview --project-id <id> --event-type approval_required
```

### `n8n-export-event` `[planned]`

Export a workbench event to n8n after approval. Requires `IntegrationPolicy.allow_outbound_events = True` and explicit `--approve`.

```bash
python main.py n8n-export-event --project-id <id> --event-type report_generated
```

### `n8n-webhook-validate` `[planned]`

Validate that a configured n8n webhook reference is structurally correct. Does not send a real HTTP request.

```bash
python main.py n8n-webhook-validate --project-id <id>
```

### `integration-test-dry-run` `[planned]`

Run a full dry-run integration test — simulate event generation and delivery without real external calls.

```bash
python main.py integration-test-dry-run --project-id <id>
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

## Direct scripts `[implemented]`

These are run directly with Python, not via `main.py`.

### `python tools/docs_audit.py` `[implemented]`

Run the documentation freshness audit. Checks that required docs exist, that planned
commands are marked `[planned]`, that foundation-only features are not described as
runtime-implemented, and that DOCS_MANIFEST.md and DOCUMENTATION_GOVERNANCE.md are present.

```bash
python tools/docs_audit.py                # run audit + write reports to outputs/docs_audit/
python tools/docs_audit.py --no-write     # print only, do not write output files
```

Outputs (when `--no-write` is not passed):
- `outputs/docs_audit/DOCS_FRESHNESS_REPORT.md`
- `outputs/docs_audit/docs_freshness_report.json`

Exit codes: `0` = all required docs present, no hard errors. `1` = missing required doc or hard contradiction.

### `python tools/classify_inputs.py` `[implemented]`

Phase 2A input classification script. Classifies raw inputs (URLs, text, file paths) into
typed schema objects and writes structured artifacts. Classify-only: no URL fetching,
no browser execution, no credential use, no external calls. Secrets are redacted.

```bash
python tools/classify_inputs.py --input "Need Playwright tests for SaaS dashboard"
python tools/classify_inputs.py --input "https://app.example.com" --input "brief text"
python tools/classify_inputs.py --input-file brief.txt
python tools/classify_inputs.py --input "..." --no-write          # print only
python tools/classify_inputs.py --input "..." --json              # JSON output to stdout
python tools/classify_inputs.py --input "..." --project-id myproject
python tools/classify_inputs.py --input "..." --source-platform upwork
python tools/classify_inputs.py --input "..." --with-blueprint    # Phase 2A + 2B: classify + blueprint
python tools/classify_inputs.py --input "..." --json --with-blueprint  # JSON with blueprint included
```

**Phase 2A outputs** (written to `outputs/<project_id>/00_project/` unless `--no-write`):
- `INPUT_MAP.json` / `INPUT_MAP.md`
- `WORK_REQUEST.json` / `WORK_REQUEST.md`
- `TASK_CLASSIFICATION.json` / `TASK_CLASSIFICATION.md`
- `PROJECT_STATUS.json` / `PROJECT_STATUS.md`
- `NEXT_SAFE_STEP.md`

**Phase 2B outputs** (additional, when `--with-blueprint` is passed):
- `PROJECT_BLUEPRINT.json` / `PROJECT_BLUEPRINT.md`
- `ASSUMPTIONS.md`
- `MISSING_INFO.md`
- `SAFE_NEXT_STEPS.md`
- `BLOCKED_ACTIONS.md`
- `INITIAL_QA_STRATEGY_OUTLINE.md`

Secret handling: passwords, tokens, cookies, API keys detected in input are replaced
with `[REDACTED_PASSWORD]`, `[REDACTED_TOKEN]`, `[REDACTED_COOKIE]`, `[REDACTED_SECRET]`.
If secrets are detected, the artifact includes an explicit notice that no credential use was performed.

### `python tools/agent_readiness_audit.py` `[implemented]`

Check whether the repository has the required agent operating contract docs, artifact
contracts, and tooling for agent-safe work. Dependency-free: no external calls, no LLM
calls, no automatic rewrites.

```bash
python tools/agent_readiness_audit.py              # run audit + write reports
python tools/agent_readiness_audit.py --no-write   # print only
python tools/agent_readiness_audit.py --json       # JSON output to stdout
```

Checks (34 total):
- Required agent contract docs exist (AGENT_CONTRACT, PHASE_CONTRACTS, ARTIFACT_CONTRACTS, AGENT_HANDOFF_TEMPLATE)
- Required governance and safety docs exist
- `outputs/` is gitignored
- AGENT_CONTRACT contains forbidden actions, report format, safety phrases
- PHASE_CONTRACTS contains allowed/blocked actions, acceptance criteria, implemented/planned markers
- ARTIFACT_CONTRACTS documents 00_project path, tests/ reservation, machine-readable distinction
- AGENT_HANDOFF_TEMPLATE contains all required sections

Outputs (when `--no-write` is not passed):
- `outputs/agent_audit/AGENT_READINESS_REPORT.md`
- `outputs/agent_audit/agent_readiness_report.json`

Exit codes: `0` = all required checks passed. `1` = one or more required checks failed.

---

## Planned commands — documentation governance `[planned]`

These commands are designed but not yet implemented in `main.py`.

### `docs-audit` `[planned]`

Run docs audit via `main.py`.

```bash
python main.py docs-audit
```

Currently available as a direct script: `python tools/docs_audit.py`

### `docs-check` `[planned]`

Quick check that required docs exist and are not stale.

```bash
python main.py docs-check
```

### `docs-freshness-report` `[planned]`

Generate a full documentation freshness report for a project.

```bash
python main.py docs-freshness-report --project-id <id>
```

Produces: `DocumentationFreshnessReport` schema object + Markdown report.

### `docs-sync-preview` `[planned]`

Preview which docs would need updating if a schema or command changed. Dry-run only.

```bash
python main.py docs-sync-preview --trigger schema_changed
```

### `docs-sync-apply` `[planned]`

After human review of `docs-sync-preview` output, apply recommended doc updates.

```bash
python main.py docs-sync-apply --trigger schema_changed --approve
```

Requires `--approve`. Never auto-rewrites documentation without human review.

---

## Planned commands — agent readiness `[planned]`

These commands are designed but not yet implemented in `main.py`.

### `agent-audit` `[planned]`

Run agent readiness audit via `main.py`.

```bash
python main.py agent-audit
```

Currently available as a direct script: `python tools/agent_readiness_audit.py`

### `agent-readiness` `[planned]`

Quick check that all agent contract docs are present and consistent.

```bash
python main.py agent-readiness
```

### `agent-handoff-report` `[planned]`

Generate a pre-populated handoff report for the current project state.

```bash
python main.py agent-handoff-report --project-id <id>
```

Produces: handoff report pre-filled from current project artifacts, using
the `AGENT_HANDOFF_TEMPLATE.md` structure.

---

## Commands that do NOT exist

| Wrong | Correct |
|---|---|
| `python -m ai_qa_factory` | `python main.py <mode>` |
| `--brief` | `--input` |
| `python main.py opportunity` | `python main.py prescreen` |
| Auto-execute against staging URL | Use `run-approved` (planned) after `approve-action` |
| Auto-send to client | Manual — workbench never auto-sends |

---

## Related documents

- [`APPROVAL_MODEL.md`](APPROVAL_MODEL.md) — risk levels and approval gates
- [`SCHEMA_FOUNDATION.md`](SCHEMA_FOUNDATION.md) — domain schema layer (`core/schemas/`)
- [`TOOLING_DECISIONS.md`](TOOLING_DECISIONS.md) — why each tool was or was not added
- [`RUNBOOK.md`](RUNBOOK.md) — step-by-step operational playbooks
