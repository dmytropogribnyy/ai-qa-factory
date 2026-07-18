# Operator Acceptance A–D — GENUINE executions, persisted by the Factory (v3.0.1)

Date: 2026-07-18 · Branch: `fix/v3.0.1-acceptance-integrity`

Independent verification found the earlier A–D "acceptance" used structural stand-ins (existence and
shape checks) rather than genuine executions. This replaces them with real work, each wrapped in the
full persisted `WorkExecutionService` lifecycle (analyze → approve → execute → evidence → validate →
**explicit review** → delivery, with artifact hashing + post-validation change detection + a
delivery-content secret scan). Nothing external happens: local fixtures only, loopback HTTP only, no
third party, no email, no manufactured evidence or counts.

The genuine executions are proven by executable tests (they fail if the real work does not happen):

| Scenario | Genuine execution (what actually runs) | Test |
|---|---|---|
| **C** bug fix | **Real `pytest`**: authors a buggy module + test, runs `pytest` → **fails** (exit≠0, "1 failed"), applies the fix, runs `pytest` again → **passes** (exit 0, "1 passed"). Both outputs captured as evidence. | [test_v3_genuine_execution_cd.py](../../tests/test_v3_genuine_execution_cd.py) |
| **D** API tests | **Real OpenAPI fixture + real localhost HTTP**: starts a `127.0.0.1` server implementing the spec, issues real requests — `/health`→200, `/item/1`→200, `/item/abc`→**400**, `/nope`→**404** (positive + negative). | [test_v3_genuine_execution_cd.py](../../tests/test_v3_genuine_execution_cd.py) |
| **A** Playwright | **Real headless Chromium run**: authors a Playwright+TS framework, launches Chromium against a local fixture, checks the spec assertion (`toHaveTitle`), captures a real screenshot as evidence. | [test_v3_genuine_execution_ab.py](../../tests/test_v3_genuine_execution_ab.py) |
| **B** QA audit | **Real browser audit**: Chromium + axe-core over a local fixture carrying a planted `image-alt` defect; axe genuinely detects it; findings + a real screenshot are captured as evidence. | [test_v3_genuine_execution_ab.py](../../tests/test_v3_genuine_execution_ab.py) |

C and D are deterministic and run in CI's **core-deterministic** job. A and B require Chromium + axe
and run in CI's **browser-acceptance** job (skipped locally when those are absent). All four assert the
persisted final state is `READY_FOR_DELIVERY`.

## Driving a whole client job from the CLI (no custom Python)

The operator completes the persisted lifecycle for arbitrary client work with these commands
([CLIENT_WORK_OPERATOR_GUIDE.md](../CLIENT_WORK_OPERATOR_GUIDE.md)); `validate` runs the operator's
own command in the workspace and records its output as evidence:

```
python main.py analyze-job       --text "<job brief>" --project-id job1
python main.py client-work approve           --project-id job1 --reviewer you
#   ... do the work in outputs/job1/40_ark_work/ ...
python main.py client-work record-execution  --project-id job1 --artifacts src/calc.py --evidence before.txt:"failing first"
python main.py client-work validate          --project-id job1 --command "pytest -q"
python main.py client-work review            --project-id job1 --reviewer you        # or --reject
python main.py client-work prepare-delivery  --project-id job1
python main.py client-work mark-delivered    --project-id job1
```

## Integrity guarantees enforced by the Factory

- Project ids and artifact paths are confined (no traversal); a malicious/buggy executor cannot
  escape the workspace.
- Every produced artifact + evidence file is content-hashed at execution; the exact validated set is
  snapshotted; **delivery is refused if anything changed after validation**.
- Delivery contents are secret-scanned; a delivery carrying secret-like content is refused.
- `READY_FOR_DELIVERY` requires an **explicit operator review** — validation alone does not advance to
  delivery. Rejecting the review sends the work back to `REPAIR_REQUIRED`.

## Honesty notes

- Execution is Claude-Code-driven and human-approved; it is not an autonomous agent. The genuine
  executors above are the real-work path (`is_acceptance_fixture = False`), distinct from the labeled
  deterministic **fixtures** in `tests/test_v3_execution_lifecycle.py` used for lifecycle coverage.
- None of these send email, submit forms, solve CAPTCHAs, or contact a third party.
