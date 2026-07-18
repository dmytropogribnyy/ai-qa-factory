# Client Work Operator Guide

Client work runs in **Claude Code**. The Factory analyzes first and never starts implementation
before you approve.

## 1. Intake + feasibility (read-only)

Paste the job (text, URL, budget, deadline, attachments) and say *"only analyze"*, or run:

```powershell
python main.py analyze-job --text "<job brief>" --source-platform upwork
python main.py analyze-job --input path\to\brief.txt
```

You get a **feasibility verdict** and, in `outputs\<project-id>\40_ark_work\`:

- `FEASIBILITY_REPORT.json` / `FEASIBILITY_SUMMARY.md` - verdict, intent, requirements, deliverables,
  effort/risk, selected capabilities/tools, unavailable blockers, honest reasons to reject.
- `CLIENT_QUESTIONS.md` - the questions to ask the client.
- `PROPOSAL_DRAFT.md` - an editable proposal draft.
- plus the planning artifacts (`WORK_PACKET.json`, `CAPABILITY_PLAN.json`, `TOOLCHAIN_PLAN.json`,
  `WORK_RUN_STATE.json`, ...).

The URL is never the only durable source - the redacted job text is snapshotted.

## 2. Verdicts

- **RECOMMENDED_TO_TAKE** - good fit; propose and proceed after approval.
- **TAKE_AFTER_CLARIFICATION** - ask the client questions first.
- **TAKE_AFTER_ACCESS_OR_TOOL_SETUP** - needs repo access / a tool authorization first.
- **NOT_RECOMMENDED** - outside proven capability, inaccessible, unbounded, impossible deadline, or
  unvalidatable. The proposal draft offers a smaller in-scope slice instead of a fake plan.

## 3. Approval boundary + execution

Lifecycle: INTAKE -> FEASIBILITY -> QUESTIONS -> PLAN_PROPOSED -> **HUMAN_APPROVED** -> EXECUTION ->
VALIDATION -> DELIVERY_READY. Small read-only analysis is allowed before approval; **significant
execution (writes, repo changes, external tools) waits for your approval** of scope/plan/repo/tools.

After approval, Claude executes through the repo runners, the selected tools (see
`python main.py tool-status`), and MCPs connected in your session, records progress and evidence,
runs validation, and prepares the delivery package.

## 4. Delivery

A delivery package includes the scope completed, changed files, setup/run commands, test results,
evidence, known limitations, handover notes, and a client-facing message. Delivery is never claimed
before validation passes. Resume a project later from its persisted `WORK_RUN_STATE.json`.

## Supported vs rejected

Supported: Playwright/TS frameworks, adding/repairing tests, Selenium->Playwright migration, QA
audits, bug reproduction + bounded fixes, API testing from OpenAPI/Postman, CI test integration,
accessibility/perf-smoke, docs/handover, existing-repo stabilization, small/medium dev tasks with
proven fit. Rejected honestly: Java-only deep builds with no execution capability, inaccessible
systems, undefined scope, impossible deadlines, unvalidatable or unsafe work, and anything needing
credentials you have not provided.
