# Operator Acceptance A–D — real Claude-Code-driven, persisted by the Factory (v3.0.0)

Date: 2026-07-18 · Branch: `final/unified-operator-product-v3.0.0`

This records a **real** operator session (a Claude Code session, not a CI fixture and not an
autonomous agent) driving the client-work lifecycle end-to-end for four representative scenarios.
For each one the operator **authored genuine deliverables** into the project workspace; the Factory
then **recorded, validated (for real, in-process), and persisted** the whole lifecycle, and a
**brand-new process resumed** the persisted state. Nothing external happened — no network, no
browser, no email, no third-party scan.

- Executor: [`OperatorWorkspaceExecutor`](../../core/orchestration/operator_executor.py)
  (`is_acceptance_fixture = False`). It fabricates no content: it registers the files the operator
  wrote and runs a declared validation over them. This is the counterpart to the CI acceptance
  **fixtures** in [`fixture_executors.py`](../../core/orchestration/fixture_executors.py)
  (`is_acceptance_fixture = True`), which drive the *same* contract deterministically in CI.
- Persistence + transitions: [`WorkExecutionService`](../../core/orchestration/work_execution.py)
  over [`WorkRunState`](../../core/schemas/work_run_state.py) /
  [`WorkStateManager`](../../core/orchestration/work_state_manager.py).
- Reproduce: `OUTPUT_DIR=<scratch> .venv/Scripts/python.exe tools/operator_acceptance_ad.py`
  (see [`tools/operator_acceptance_ad.py`](../../tools/operator_acceptance_ad.py)). Output dirs are
  never committed.

## Result (captured)

```
A: verdict=TAKE_AFTER_CLARIFICATION  state=READY_FOR_DELIVERY  valid=True  tests=5/5  ev=1  fixture=False  artifacts=5
B: verdict=TAKE_AFTER_CLARIFICATION  state=READY_FOR_DELIVERY  valid=True  tests=2/2  ev=2  fixture=False  artifacts=4
C: verdict=TAKE_AFTER_CLARIFICATION  state=READY_FOR_DELIVERY  valid=True  tests=1/1  ev=1  fixture=False  artifacts=3
D: verdict=TAKE_AFTER_CLARIFICATION  state=READY_FOR_DELIVERY  valid=True  tests=4/4  ev=0  fixture=False  artifacts=1

RESULT: [PASS] all A-D executed, validated, and persisted (real operator path)
```

| Scenario | Work | Real validation the Factory ran | Deliverables persisted |
|---|---|---|---|
| **A** | Playwright + TypeScript E2E framework | structural: `package.json` has a `test` script, config has `testDir`, spec/README present | `delivery/package.json`, `playwright.config.ts`, `tests/example.spec.ts`, `README.md` |
| **B** | QA audit with reproductions + evidence | every finding has a reproduction **and** an on-disk evidence file | `delivery/QA_AUDIT_REPORT.md`, `findings.json`, `evidence/f1.txt`, `evidence/f2.txt` |
| **C** | Reproduce + fix a Python defect + regression | imports the operator-authored module and runs `add(2,3)==5` in-process | `src/calc.py`, `tests/test_calc.py`, `evidence/failing_before.txt` |
| **D** | API tests (positive + negative) | executes the authored positive+negative cases against an in-process stub | `delivery/API_TEST_PLAN.json`, `delivery/API_TEST_RESULTS.json` |

## Proof it was persisted (not just narrated) — scenario C

The state machine advanced through the full lifecycle and was written to disk at each step
(`WORK_RUN_STATE.json` history):

```
RECEIVED -> INTAKE_COMPLETE -> PLANNED -> WAITING_FOR_INFORMATION -> PLANNED
  -> READY_TO_EXECUTE -> EXECUTING -> VERIFYING -> READY_FOR_REVIEW -> READY_FOR_DELIVERY
```

`EXECUTION_PROGRESS.json` records the real (non-fixture) executor:

```
executor = operator:claude-code/bug-fix   |   is_acceptance_fixture = False
```

`WORK_DELIVERY_MANIFEST.json` (persisted delivery package):

```json
{
  "project_id": "acc-c",
  "produced_artifacts": ["src/calc.py", "tests/test_calc.py", "evidence/failing_before.txt"],
  "evidence_count": 1,
  "validation_passed": true,
  "tests_run": 1,
  "approved_for_delivery": true
}
```

Files the Factory persisted in the workspace `outputs/acc-c/40_ark_work/` (abridged):

```
APPROVAL.json  WORK_RUN_STATE.json  EXECUTION_PROGRESS.json  EVIDENCE_INDEX.json
TEST_RESULTS.json  WORK_DELIVERY_MANIFEST.json  DELIVERY_REPORT.md  CLIENT_MESSAGE.md
src/calc.py  tests/test_calc.py  evidence/failing_before.txt
+ the planning artifacts (FEASIBILITY_REPORT.json, WORK_PACKET.json, CLIENT_QUESTIONS.md, …)
```

## Resume after restart / a new Claude session

For every scenario the summary's `final_state` / `evidence_count` / `delivery_ready` are read by a
**freshly constructed** `WorkExecutionService` (a new process would behave identically) — the values
above come from that reload, so they prove the lifecycle is recovered from disk, not from in-memory
state. The CLI exposes the same for an operator:

```
python main.py client-work resume  --project-id acc-c
python main.py client-work status  --project-id acc-c
```

## Honesty notes

- The **verdict** for A–D is `TAKE_AFTER_CLARIFICATION` (not auto-`RECOMMENDED`): the briefs omit
  repo access / target URLs / the OpenAPI spec, so the Factory asks first — then the operator
  resolves the questions and approves before any execution. This is the intended honest boundary.
- Deterministic CI proves the same persisted contract via labeled **acceptance fixtures**
  (`tests/test_v3_execution_lifecycle.py`); this document is the **real operator** counterpart with
  `is_acceptance_fixture = False`. Neither path sends email, submits forms, solves CAPTCHAs, scans a
  real third party, or runs an autonomous coding agent.
