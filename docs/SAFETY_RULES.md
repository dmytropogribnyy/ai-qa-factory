# Safety Rules — Guided QA Automation Workbench

**Version:** 5.1.0  
**Updated:** 2026-05-24

These rules are non-negotiable. No flag, no argument, and no configuration overrides them without an explicit human decision documented outside the system.

---

## Hard rules

### Rule 1 — Do not confuse task URL with target application URL

A brief may contain multiple URLs:
- A **task URL** points to where the work was described (Jira ticket, Linear issue, Notion page, Upwork job post).
- A **target URL** points to the application under test (staging SaaS, e-commerce site, API endpoint).

These must be classified separately before any action. A task URL is never a test target. A target URL is never treated as task context.

**Violation:** Using a Jira ticket URL as the base URL for Playwright tests, or treating a staging URL as a source of project requirements.

### Rule 2 — Do not run against an unknown external URL

If the system or a generated script references an external URL that has not been explicitly classified and approved, that URL must not be contacted.

"It looks like a staging URL" is not sufficient. The URL must be:
1. Named explicitly in the agreed project scope
2. Confirmed by the client as a test target
3. Approved via the checklist in [`RUNBOOK.md`](RUNBOOK.md) section 4

**Violation:** Running `npx playwright test` with a BASE_URL that was not explicitly approved for testing.

### Rule 3 — Do not run against a target URL without approval

Even when the target URL is correctly classified and confirmed, automated execution against it requires explicit approval per run.

Approval means:
- `--approve` flag passed with awareness of what it unlocks
- Section 4 checklist in RUNBOOK.md completed
- Staging confirmed as separate from production

**Violation:** Running `npx playwright test` against any staging URL without completing the checklist and passing `--approve`.

### Rule 4 — Do not run against production without explicit read-only approval

Production environments require a higher level of approval than staging:
- Written confirmation from the client that production testing is in scope
- Explicit read-only scope defined (no write, no mutation, no state change)
- Stop conditions agreed in writing

**Violation:** Any automated run against a production URL, even for smoke tests, without written client authorization.

### Rule 5 — Do not test payment flows unless sandbox is confirmed

Payment flow testing requires:
- Written confirmation that the payment provider is in sandbox/test mode
- Test card numbers confirmed (Stripe test cards, etc.)
- No real money involved — ever

This must be confirmed **in writing by the client** before any payment-adjacent test runs.

**Violation:** Running checkout tests that call a payment API without written sandbox confirmation.

### Rule 6 — Do not use credentials unless explicitly approved

Credentials (usernames, passwords, API tokens, session cookies) used in tests must:
- Be synthetic test accounts created specifically for testing
- Never be real user accounts or real production credentials
- Live in `.env` files only — never in briefs, test specs, reports, or commits
- Be confirmed by the client as safe-to-use test accounts

**Violation:** Pasting a real user password into a test file. Using a production API token in automation. Including credentials in a client report.

### Rule 7 — Do not claim tests were executed unless there is evidence

The workbench generates test plans, strategies, and scaffolds. It does not execute tests unless explicitly run.

Never write or approve a client-facing report that implies tests were run when they were not. Evidence means:
- Playwright test results (HTML report, JSONL results)
- Screenshots or traces from an actual run
- A log entry showing execution

**Violation:** Delivering a `TEST_RESULTS.md` that says "All 45 tests passed" when only the scaffold was generated.

### Rule 8 — Do not include internal notes or prompts in client-facing reports

Internal artifacts include:
- System prompts and LLM instructions
- Agent reasoning notes
- Mock-mode placeholder text
- Routing decisions and internal scoring
- `HUMAN_REVIEW_REQUIRED.md` checklists
- `QUALITY_GATE_REPORT.md` errors and warnings

These must never appear in a document delivered to a client. Client reports are a clean, professional subset.

**Violation:** Delivering a report that contains `[MOCK OUTPUT]` placeholders, internal quality gate warnings, or agent prompt fragments.

### Rule 9 — Do not auto-deliver client-facing reports

No client-facing report is sent automatically. Every delivery is a manual action:
1. Open the generated report
2. Complete the `HUMAN_REVIEW_REQUIRED.md` checklist
3. Manually edit the report (remove internals, verify claims, soften overclaims)
4. Send it yourself

**Violation:** Any configuration, script, or workflow that automatically emails, posts, or submits a report to a client or platform.

### Rule 10 — Do not perform destructive actions automatically

Destructive actions include:
- Deleting records or data in any environment
- Modifying production configuration
- Triggering irreversible state changes (order cancellation, user deletion, billing changes)
- Security testing actions (injection, auth bypass attempts)

These require explicit written scope from the client and a separate approval decision per action type.

**Violation:** A generated test script that deletes test users or orders without an explicit "destructive scope" confirmation.

---

## Consequences of rule violations

| If a rule is violated during a run | Required action |
|---|---|
| Staging URL accessed without approval | Stop the run, document what happened, re-run with proper approval |
| Client report contains internal notes | Regenerate the report, do not send the contaminated version |
| Credentials appear in test files | Rotate credentials immediately, remove from files, add to `.gitignore` |
| Evidence claimed without execution | Do not deliver. Re-run the actual tests. |
| Payment test without sandbox confirmation | Stop immediately. Confirm sandbox mode before any further run. |

---

## Related documents

- [`APPROVAL_MODEL.md`](APPROVAL_MODEL.md) — risk levels and approval gates
- [`RUNBOOK.md`](RUNBOOK.md) — approval checklist (section 4), safe local vs. external execution (section 5)
- [`REAL_TESTING_PREPARATION.md`](REAL_TESTING_PREPARATION.md) — full staging pre-execution checklist
