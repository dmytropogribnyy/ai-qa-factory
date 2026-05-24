# Approval Model — Guided QA Automation Workbench

**Version:** 5.1.0-workbench-alpha  
**Updated:** 2026-05-24

> **AI drafts. Senior QA decides.**

This document defines what requires human approval, what is automatically safe, and how the approval gates work in practice.

---

## Core rule

**The workbench generates artifacts. Dmytro approves before use.**

No artifact is sent to a client, submitted to a platform, or executed against a real environment without an explicit human decision. The workbench enforces this structurally — not just by convention.

---

## Approval boundaries

### Always automatic (no approval needed)

These operations run without any gate:

| Operation | Why safe |
|---|---|
| Reading input files | Local read-only |
| LLM inference (mock or real) | No external side effects |
| Writing output files to `outputs/` | Local, reversible |
| TypeScript scaffold generation | Local file writes |
| State snapshots and logs | Local, internal |
| `--dry-run` mode | No final writes |
| `pytest` runs | Always mock mode, no network |

### Requires human review (always)

These trigger `HUMAN_REVIEW_REQUIRED.md`:

| Artifact | What to check |
|---|---|
| `proposal.md` | Claims, tone, mandatory keywords, invented evidence |
| `screening_answers.md` | Accuracy, AI trap responses |
| `evidence_needed.md` | Nothing invented or unavailable |
| `commercial_strategy.md` | Price, rates, milestone structure |
| `TEST_STRATEGY.md` | Scope, tool choices, coverage claims |
| `TEST_PLAN.md` | Environment assumptions, test data |
| `TEST_CASES.md` | Assertions, selectors, hardcoded values |
| Any client-facing document | Every claim, every commitment |

### Requires explicit `--approve` flag

The `--approve` flag signals that Dmytro has already reviewed the input and context. Without it:
- `HUMAN_REVIEW_REQUIRED.md` is generated with a manual checklist.
- The quality gate runs and any errors block the "approved" status.

With `--approve`:
- `HUMAN_REVIEW_REQUIRED.md` is still generated (for audit trail) but marked as pre-approved.
- Use only when you have already read and verified the input.

```bash
# Without --approve: HUMAN_REVIEW_REQUIRED.md generated with checklist
python main.py upwork --input brief.txt --require-real-llm

# With --approve: pre-approved run
python main.py upwork --input brief.txt --require-real-llm --approve
```

### Requires written approval before execution

These actions are blocked by default and require an explicit decision:

| Action | Gate |
|---|---|
| Running Playwright tests against staging URL | Review BASE_URL in framework `.env`, check APPROVAL_CHECKPOINTS.md |
| Running Playwright tests against client production | Not supported — requires explicit scope and written confirmation |
| Submitting a proposal on Upwork | Manual — workbench never auto-submits |
| Sending a client report | Manual — workbench never auto-sends |
| Making database changes during validation | Requires explicit written scope |
| Any destructive test action | Requires explicit written scope |

---

## How the gates work in code

### Pre-run safety prompts

Certain keywords in the input brief trigger interactive prompts before the workflow starts:

| Trigger keyword | Prompt |
|---|---|
| `payment`, `sandbox`, `stripe` | Confirm payment-flow testing is sandbox-only |
| `production`, `live site` | Confirm staging/prod boundary and stop conditions |
| `urgency`, `ASAP`, `tonight` | Confirm scope is realistic for the timeline |

In interactive (TTY) mode: the prompt blocks until answered.  
In CI/non-interactive mode: the answers default to "acknowledged" and are recorded in state.

### `HUMAN_REVIEW_REQUIRED.md`

Generated after every normal run (without `--approve`). Contains:

- List of artifacts that require review
- Specific checklist items per artifact type
- Warning if any quality gate checks failed

**Never send any output before opening and clearing this checklist.**

### `QUALITY_GATE_REPORT.md`

Generated after every run. Contains results of 16 automated checks:

| Check type | Examples |
|---|---|
| Error (blocks client use) | Invented evidence phrases, hardcoded credentials, mock output in client text, risky security wording |
| Warning (review carefully) | Low budget red flags, generic proposal phrases, missing client questions, brittle selectors |

The quality gate does not auto-reject — it informs. Dmytro decides whether a warning is acceptable.

### `--require-real-llm`

Fails the run immediately if `LLM_MODE=mock`. Use before any client-facing output to ensure the content is real LLM output, not mock placeholder text.

```bash
# Will fail if LLM_MODE=mock is set
python main.py upwork --input brief.txt --require-real-llm
```

### Mock fallback warning

If real LLM calls fail and the system falls back to mock output, the terminal shows:

```
WARNING: N LLM call(s) fell back to mock output. Check outputs/<id>/logs/factory.jsonl.
```

Exit code 2 under `--require-real-llm`. **Do not use that output for clients.** Fix keys, re-run.

---

## Approval checklist for Playwright scaffold runs

Before running `npx playwright test` against any real URL:

```
Written scope
  [ ] Client provided written scope: target URL, in-scope flows, out-of-scope, timebox
  [ ] Staging URL confirmed separate from production
  [ ] Stop conditions agreed

Environment
  [ ] Test accounts provisioned (no PII, synthetic data)
  [ ] BASE_URL in framework .env points to staging
  [ ] Credentials in .env only — not in briefs, specs, or reports

Safety
  [ ] Sandbox payment confirmed in writing (test cards only, no real transactions)
  [ ] No destructive actions in scope
  [ ] No production database access

System readiness
  [ ] python main.py system-health — all pass
  [ ] pytest -q — 69/69 green
  [ ] LLM_MODE=real, --require-real-llm confirmed non-mock output

Human sign-off
  [ ] APPROVAL_CHECKPOINTS.md reviewed and signed off
  [ ] PRESCREENING_REPORT.md reviewed
  [ ] No artifact sent without manual edit
```

Full checklist: [`docs/REAL_TESTING_PREPARATION.md`](REAL_TESTING_PREPARATION.md)

---

## What the approval model is NOT based on

- **Not robots.txt.** robots.txt is a crawling convention, not a security boundary. The workbench does not use it to decide what it may or may not test.
- **Not URL pattern matching.** The workbench does not infer safety from URL structure (e.g., `/staging/` vs `/prod/`).
- **Not domain allowlists.** Any external execution requires an explicit decision, regardless of domain.

The boundary is always: **execution mode + explicit approval**. Local = automatic. External = requires approval.

---

## Related documents

- [`docs/SAFETY_RULES.md`](SAFETY_RULES.md) — the full rule set
- [`docs/REAL_TESTING_PREPARATION.md`](REAL_TESTING_PREPARATION.md) — staging/production checklist
- [`docs/RUNBOOK.md`](RUNBOOK.md) — daily operating guide
