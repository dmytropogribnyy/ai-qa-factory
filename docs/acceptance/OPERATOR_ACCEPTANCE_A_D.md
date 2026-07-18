# Operator Acceptance A–D — GENUINE executions, persisted by the Factory (v3.0.2)

Date: 2026-07-19 · Branch: `fix/v3.0.2-final-integrity`

Each scenario is real work wrapped in the full persisted `WorkExecutionService` lifecycle (analyze →
approve → execute → evidence → validate → **explicit review** → **prepare-delivery** →
**mark-delivered**), with artifact + evidence hashing, post-validation change detection, a
delivery-content secret scan, and the non-bypassable `DELIVERY_PREPARED` boundary. Nothing external
happens: local fixtures only, loopback HTTP only, no third party, no email, no manufactured evidence
or counts.

The genuine executions are proven by executable tests (they fail if the real work does not happen):

| Scenario | Genuine execution (what actually runs) | Test |
|---|---|---|
| **C** bug fix | **Real `pytest`**: authors a buggy module + test, runs `pytest` → **fails** (exit≠0, "1 failed"), applies the fix, runs `pytest` again → **passes** (exit 0, "1 passed"). Both outputs captured as evidence. | [test_v3_genuine_execution_cd.py](../../tests/test_v3_genuine_execution_cd.py) |
| **D** API tests | **Real OpenAPI parsed by the production `APIContractImporter` + real localhost HTTP**: the written spec is parsed, the positive/negative cases are **derived from the parsed contract** (each traced back to a contract path), then a `127.0.0.1` server implementing the spec answers real requests — `/health`→200, `/item/1`→200, `/item/abc`→**400**, `/nope`→**404**. | [test_v3_genuine_execution_cd.py](../../tests/test_v3_genuine_execution_cd.py) |
| **A** Playwright framework | **Real `playwright test` on the GENERATED framework**: authors `package.json` + `playwright.config.ts` + `tests/home.spec.ts`, then runs the real `playwright` binary against a loopback fixture. The generated config + spec are discovered, Chromium loads the fixture, and the **real exit code + reporter JSON + a genuine artifact (screenshot/trace)** are captured; the test count is read from the report. A negative acceptance authors a deliberately broken assertion and proves it genuinely **fails**. | [test_v3_genuine_execution_ab.py](../../tests/test_v3_genuine_execution_ab.py) |
| **B** QA audit | **Real browser audit**: Chromium + axe-core over a local fixture carrying a planted `image-alt` defect; axe genuinely detects it; findings + a real screenshot are captured as evidence. | [test_v3_genuine_execution_ab.py](../../tests/test_v3_genuine_execution_ab.py) |

C and D are deterministic and run in CI's **core-deterministic** job. A and B require Chromium + axe;
scenario A additionally requires the npm `@playwright/test` runtime (both provisioned by CI). They run
in CI's **browser-acceptance** job, which asserts **zero skips** (a misprovisioned runtime cannot pass
as green-but-skipped). All four assert the persisted final state is `DELIVERY_PREPARED`.

## Driving a whole client job from the CLI (no custom Python)

The operator completes the persisted lifecycle for arbitrary client work with the public CLI — proven
end to end as an external process in [test_v3_cli_e2e.py](../../tests/test_v3_cli_e2e.py):

```
python main.py analyze-job       --text "<job brief>" --project-id job1
python main.py client-work approve           --project-id job1 --reviewer you
#   ... do the work in outputs/job1/40_ark_work/ ...
python main.py client-work record-execution  --project-id job1 --artifacts src/calc.py --evidence before.txt:"failing first"
python main.py client-work validate          --project-id job1 --validation-argv-json '["python","-m","pytest","-q"]'
python main.py client-work review            --project-id job1 --reviewer you        # or --reject
python main.py client-work prepare-delivery  --project-id job1                        # -> DELIVERY_PREPARED
python main.py client-work mark-delivered    --project-id job1                        # you send it yourself; this records that
```

`validate` runs the operator's own structured command (`shell=False`, workspace-confined, bounded
timeout) and captures each attempt as registered evidence under `evidence/validation/<id>/`.

## Integrity guarantees enforced by the Factory

- Project ids and artifact paths are confined (no traversal); a malicious/buggy executor cannot
  escape the workspace.
- Every produced artifact + evidence file (including per-attempt validation evidence) is
  content-hashed; the exact validated set is snapshotted; **delivery is refused if anything changed
  after validation**.
- Delivery contents are secret-scanned; a delivery carrying secret-like content is refused.
- `READY_FOR_DELIVERY` requires an **explicit operator review** — validation alone does not advance to
  delivery. Rejecting the review sends the work back to `REPAIR_REQUIRED`.
- **Completion is reachable only through `DELIVERY_PREPARED`.** `prepare-delivery` writes an exact
  manifest (included files + per-file SHA-256 + a deterministic package digest); `mark-delivered`
  re-verifies the manifest and every included file and **records the operator's assertion of a manual
  send — it sends nothing itself**. Direct `READY_FOR_DELIVERY → COMPLETED` is impossible, and a
  changed or secret-containing file can never be delivered by calling `mark-delivered` directly.

## Honesty notes

- Execution is Claude-Code-driven and human-approved; it is not an autonomous agent. The genuine
  executors above are the real-work path (`is_acceptance_fixture = False`), distinct from the labeled
  deterministic **fixtures** in `tests/test_v3_execution_lifecycle.py` used for lifecycle coverage.
- Scenario A executes the generated TypeScript framework with the real `playwright test` runner — the
  authored framework is genuinely run, not merely shaped on disk.
- None of these send email, submit forms, solve CAPTCHAs, or contact a third party.
