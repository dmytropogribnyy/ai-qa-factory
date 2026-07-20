# Client Work Operator Guide

Client work runs in **Claude Code**. The Factory analyzes first and never starts implementation
before you approve.

> **Email identities:** for any client signup / email-verification / magic-link / password-reset
> testing, use the operator-owned **Gmail QA Test Inbox** (`drdiplextech@gmail.com`, read-only) per
> the canonical `docs/EMAIL_IDENTITY_AND_MAILBOX_POLICY.md`. Client communication and Scout outreach
> use `dipptrue@gmail.com`. Automated inbox assertions require an explicitly authorized flow.

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
VALIDATION -> **REVIEW** -> **DELIVERY_PREPARED** -> COMPLETED. Small read-only analysis is allowed
before approval; **significant execution (writes, repo changes, external tools) waits for your
approval** of scope/plan/repo/tools.

After approval, Claude executes through the repo runners, the selected tools (see
`python main.py tool-status`), and MCPs connected in your session, records progress and evidence,
runs validation, and prepares the delivery package. Execution is **Claude-Code-driven and
human-approved** — the Factory records and persists what was produced; it is not an autonomous agent.

Drive the whole persisted lifecycle from the CLI — no custom script needed. Each command
reads/writes durable state on disk, so it survives a restart or a new Claude session:

```powershell
python main.py client-work status           --project-id <id>                    # where it stands + next action
python main.py client-work approve           --project-id <id> --reviewer <you>   # PLANNED -> READY_TO_EXECUTE
#   ... do the work in outputs/<id>/40_ark_work/ ...
python main.py client-work record-execution  --project-id <id> --artifacts src/app.py,tests/test_app.py --evidence before.txt:"failing first"
python main.py client-work validate          --project-id <id> --validation-argv-json '["python","-m","pytest","-q"]'
python main.py client-work review            --project-id <id> --reviewer <you>   # explicit gate (or --reject -> REPAIR_REQUIRED)
python main.py client-work prepare-delivery  --project-id <id>                    # -> DELIVERY_PREPARED (verifies hashes + scans, builds the exact manifest)
python main.py client-work reopen-delivery   --project-id <id> --reviewer <you> --reason "<why>"   # recover a prepared delivery
python main.py client-work mark-delivered    --project-id <id>                    # you send it yourself first; this records that + re-verifies the package
python main.py client-work resume            --project-id <id>                    # reload persisted state after a restart
```

Prefer **`--validation-argv-json`** (a JSON array of argument strings) — it is unambiguous on Windows
and for paths with spaces, and it is the same structured contract the future Dashboard will use. It
runs your command with `shell=False`, confined to the workspace, with a bounded timeout. `--command
"pytest -q"` remains a POSIX-tokenized convenience. Each validation attempt is captured as its own
registered evidence under `evidence/validation/<id>/` (metadata + stdout + stderr, hashed, never
overwritten).

The Factory content-hashes every produced artifact + evidence at execution and **refuses delivery**
if anything changed after validation or if the delivery contents look secret-like. Delivery also
requires the explicit review above — validation alone never advances to delivery.

## 4. Delivery

`prepare-delivery` moves the project to **`DELIVERY_PREPARED`**: it rehashes every registered artifact
and evidence file against the validated snapshot, rejects any added/removed/changed file, scans the
exact delivery set for secret-like content, requires your approved review, and writes an exact
`WORK_DELIVERY_MANIFEST.json` (included files + per-file SHA-256 + a deterministic package digest).

`mark-delivered` requires `DELIVERY_PREPARED`, re-verifies the manifest and every included file, and
**records your assertion that you sent the package manually — it sends nothing itself**. Completion is
reachable only through `DELIVERY_PREPARED`; there is no way to jump straight from `READY_FOR_DELIVERY`
to `COMPLETED`, and a changed or secret-containing file can never be delivered by calling
`mark-delivered` directly. Resume a project later from its persisted `WORK_RUN_STATE.json`.

A delivery package includes the scope completed, changed files, setup/run commands, test results,
evidence, known limitations, handover notes, and a client-facing draft message (for you to edit and
send). The lifecycle is proven three ways: deterministic acceptance **fixtures**
(`tests/test_v3_execution_lifecycle.py`), a **full real-CLI end-to-end** run
(`tests/test_v3_cli_e2e.py`), and documented **genuine** operator executions for scenarios A–D (see
[acceptance/OPERATOR_ACCEPTANCE_A_D.md](acceptance/OPERATOR_ACCEPTANCE_A_D.md)).

## Supported vs rejected

Supported: Playwright/TS frameworks, adding/repairing tests, Selenium->Playwright migration, QA
audits, bug reproduction + bounded fixes, API testing from OpenAPI/Postman, CI test integration,
accessibility/perf-smoke, docs/handover, existing-repo stabilization, small/medium dev tasks with
proven fit. Rejected honestly: Java-only deep builds with no execution capability, inaccessible
systems, undefined scope, impossible deadlines, unvalidatable or unsafe work, and anything needing
credentials you have not provided.
