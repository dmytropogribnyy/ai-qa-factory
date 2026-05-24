# Command Reference — Guided QA Automation Workbench

**Version:** 5.1.0-workbench-alpha  
**Updated:** 2026-05-24

All commands run as: `python main.py <command> [options]`  
Use `.venv\Scripts\python.exe` on Windows to ensure the venv Python is used.

---

## System commands

### `system-health`

Check local readiness before any real-mode work.

```bash
python main.py system-health
```

Checks: Python packages, `.env` config, API key presence, output/memory directories, Node/npm/npx.  
Expected: all 26 checks pass.

### `capabilities`

Print the capability matrix — what project types the workbench handles and at what support level.

```bash
python main.py capabilities
```

### `agents`

List agents registered in the system.

```bash
python main.py agents                        # all agents
python main.py agents --workflow prescreen   # agents for a specific workflow
```

---

## Opportunity evaluation workflows

These workflows are for evaluating job posts, freelancing opportunities, and inbound briefs.

### `prescreen`

Fast suitability check. Run this first before spending time on a full analysis.

```bash
python main.py prescreen --input real_jobs/job_001.txt
python main.py prescreen --input real_jobs/job_001.txt --source-platform upwork
python main.py prescreen --input real_jobs/job_001.txt --require-real-llm
```

Open after: `READ_ME_FIRST.md` → `DECISION.md` → `PRESCREENING_REPORT.md`

### `filter`

Opportunity filtering and routing — similar to prescreen with slightly different agent sequence.

```bash
python main.py filter --input real_jobs/job_001.txt
```

### `batch-filter`

Filter a whole directory of opportunity files and produce a shortlist report.

```bash
python main.py batch-filter --input real_jobs/
```

Output: `outputs/batch_opportunity_report.md`

### `upwork`

Full Upwork proposal pack: routing + proposal + test design.

```bash
python main.py upwork --input real_jobs/job_001.txt --source-platform upwork --require-real-llm
```

Open after: `proposal.md`, `screening_answers.md`, `evidence_needed.md`, `commercial_strategy.md`,  
`QUALITY_GATE_REPORT.md`, `HUMAN_REVIEW_REQUIRED.md`

---

## QA delivery workflows

These workflows are for real client project delivery — building test strategies, scaffolding, and documentation.

### `test-design`

Generate test strategy, test plan, and test cases from a client brief.

```bash
python main.py test-design --input client_briefs/project_001.txt --require-real-llm
```

Outputs: `TEST_STRATEGY.md`, `TEST_PLAN.md`, `TEST_CASES.md`

### `scaffold`

Generate a complete Playwright TypeScript test framework from a brief.

```bash
python main.py scaffold --input client_briefs/project_001.txt --require-real-llm
```

Output: `outputs/<project_id>/framework/` — full npm project (tsconfig, playwright.config.ts, CI workflow, specs)

After scaffold, follow setup steps:
```bash
cd outputs/<project_id>/framework
npm install
npx playwright install
# set BASE_URL in framework/.env before running tests
```

### `plan`

Lightweight test planning — strategy + plan without full routing or proposals.

```bash
python main.py plan --input client_briefs/project_001.txt --require-real-llm
```

### `audit`

SaaS/compliance audit workflow.

```bash
python main.py audit --input client_briefs/saas_audit_brief.txt --require-real-llm
```

### `review`

Review a test file or code file for quality, brittleness, and improvement suggestions.

```bash
python main.py review --input tests/smoke.spec.ts
```

Outputs: flakiness report, selector quality assessment, improvement suggestions.

### `delivery`

Generate delivery documentation for completed work.

```bash
python main.py delivery --input client_briefs/project_001.txt --require-real-llm
```

### `full`

Complete end-to-end workflow: routing + proposal + test design + scaffold + delivery notes.

```bash
python main.py full --input client_briefs/project_001.txt --require-real-llm
```

---

## Utility

### `run-tests`

Safely run tests for a generated Playwright or pytest project.

```bash
python main.py run-tests --project-path outputs/<project_id>/framework --kind playwright
python main.py run-tests --project-path outputs/<project_id> --kind pytest
```

### `ask`

Ask a question about a saved project (uses persisted state).

```bash
python main.py ask --project-id <project_id> --question "Why did you recommend apply_selectively?"
python main.py ask --project-id <project_id>   # interactive REPL
```

### `mcp-guide`

Generate MCP integration guide for the current context.

```bash
python main.py mcp-guide --input client_briefs/project_001.txt
```

---

## Execution mode flags

These flags work with any workflow command.

| Flag | Effect |
|---|---|
| `--auto` | Run all agents without pauses (default) |
| `--step` | Pause between agents for inline feedback |
| `--dry-run` | Run without writing final output files |
| `--only <agent>` | Run only one specific agent |
| `--from-step <agent>` | Resume workflow from a specific agent |
| `--project-id <id>` | Resume a previously saved project |
| `--approve` | Mark output as pre-approved (skips HUMAN_REVIEW_REQUIRED) |
| `--require-real-llm` | Fail if LLM_MODE=mock (enforce real output) |
| `--allow-mock` | Allow mock despite --require-real-llm (dry/training runs) |
| `--client-id <id>` | Link a client memory context |
| `--source-platform <p>` | Force source platform hint |

Examples:

```bash
python main.py full --input brief.txt --step
python main.py full --input brief.txt --dry-run
python main.py full --input brief.txt --only proposal_writer
python main.py full --input brief.txt --from-step proposal_writer
python main.py full --input brief.txt --project-id abc123 --only proposal_writer
```

---

## `--source-platform` values

Use when the pasted text does not make the source obvious.

| Value | Use for |
|---|---|
| `upwork` | Upwork job post |
| `fiverr` | Fiverr buyer request |
| `peopleperhour` | PeoplePerHour brief |
| `contra` | Contra project post |
| `linkedin_direct` | LinkedIn DM or direct lead |
| `writing_platform` | nDash, Draft.dev, TestMu, DO Ripple, etc. |
| `direct_b2b` | Client email / direct B2B brief |
| `ai_evaluator` | Evaluator platform opportunity |
| `unknown` | Default when source is unclear |

---

## Mock vs real mode

**Mock mode** (default, safe, no cost — always used in tests):

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

Windows — set encoding before real runs to avoid UnicodeEncodeError from LiteLLM:

```powershell
$env:PYTHONIOENCODING="utf-8"
.venv\Scripts\python.exe main.py <command> --require-real-llm
```

---

## Commands that do NOT exist

| Wrong | Correct |
|---|---|
| `python -m ai_qa_factory` | `python main.py <mode>` |
| `--brief` | `--input` |
| `python main.py opportunity` | `python main.py prescreen` |
| `python main.py gig` | `python main.py prescreen` |
| URL-only autonomous analysis | Write a brief `.txt` first (Phase 2 adds URL classification) |
| Screenshot-only intake | Not yet implemented (Phase 2 scope) |
| Auto-execute against staging | Requires explicit `--approve` + staging checklist |

---

## Run tests

```bash
.venv\Scripts\python.exe -m pytest -q
```

Expected: 69 passed. Always runs in mock mode — no API keys consumed.
