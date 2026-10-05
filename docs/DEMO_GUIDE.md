# Product Demos in the Dashboard

The Dashboard has a **Demos** page (`/demos`, in the main navigation and linked from Overview) for
the two implemented demonstrations:

- **QA Evidence & Retest** — real local Chromium + axe-core on an owned synthetic page, a
  **predefined** repair at the same URL, and a scoped retest of two axe rules (`image-alt`,
  `label`). Engine and details: [QA_DEMO.md](QA_DEMO.md).
- **LLM Output Evaluation** — **FIXTURE** mode only from the web page: constructed baseline and
  candidate outputs graded against gold cases. No model, provider or API is called, so the scores
  exercise the evaluator, not measured model performance. Engine and details:
  [LLM_EVALUATION.md](LLM_EVALUATION.md).

Start the Dashboard as usual (`python main.py dashboard`), open `/demos`, and press **Run QA demo**
or **Run evaluation**. Both buttons are disabled while a run is in progress; when the run finishes
the result page opens. Opening or reloading a result never runs anything again; pressing a button
again always creates a new run and leaves earlier runs untouched.

Runtime: `core/dashboard/demos.py` (read projection, start path, HTML fragments) with routes in
`core/scout/dashboard.py`. Tests: `tests/test_demo_dashboard.py`.

## What the result pages show

- **QA**: the scoped verdict (`FIX_VERIFIED`, `RETEST_FAILED`, `BASELINE_NOT_REPRODUCED` or
  `BLOCKED`) with its reason, the genuine before/after screenshots, a two-rule before/after table,
  run id and timestamps. Out-of-scope axe rules, evidence hashes, tool/fixture provenance,
  limitations and the stored JSON are under a details section. The verdict covers the two target
  rules on the synthetic page only; it is not an accessibility certification.
- **LLM**: mode, verdict, baseline and candidate passed/total with rate, regressed and improved
  cases, and the comparison policy. `REGRESSION_DETECTED` means the evaluation completed and the
  candidate fails the demo regression policy (a case passed on the baseline and fails on the
  candidate); it is not a server error and not release authorization. Each case expands to its
  prompt, context and expected answer — read from the run's own hash-checked `inputs/cases.json`
  snapshot, not the current fixture — plus both raw outputs and every check's reason.

All numbers come from the engines' persisted, re-verified results; the page does not re-grade.
Recent runs (newest 20, with an explicit "Showing the 20 most recent of N demo runs." note when
there are more) are read from
the existing `<output-dir>/scout/demo-qa-*` and `demo-llm-*` run folders. Older `demo-interview-*`
QA records still open read-only; new runs never use that prefix.

## HTTP routes

| Route | Purpose |
| --- | --- |
| `GET /demos` | The page. Never starts a run. |
| `GET /demos/run?id=<run-id>` | Result page for one persisted run. |
| `GET /api/demos/run?id=<run-id>` | The same read as JSON: `record` is `verified`, `review_required` or `unverifiable`. |
| `GET /demos/evidence?id=<qa-run-id>&side=before\|after` | The canonical PNG screenshot of a verified QA run. |
| `GET /demos/export?id=<run-id>` | A self-contained, escaped HTML report (download) generated from the verified record. |
| `POST /api/demos/start` | Body `{"scenario": "qa" \| "llm", "csrf_token": ...}`. Runs one demo and returns `run_id`, `url` and the outcome. |

Status codes: `400` invalid id, side or request body; `403` refused by the Dashboard guard; `404`
unknown run or no screenshot for that side; `409` another demo is running, or the record is not
verified (evidence/export); `422` the record exists but could not be verified; `500` the run
failed (error type only).

## Safety boundaries

- Every route inherits the Dashboard's loopback `Host` check. The start route also passes the
  shared Origin + CSRF guard before anything happens.
- The request selects a scenario and nothing else. Output folder, URL, path, model, import file and
  run id are refused as unsupported fields; the server chooses a fresh run id.
- One demo runs at a time per Dashboard (a second start gets `409`). Runs are synchronous; there is
  no queue or background worker.
- Only demo run ids (`demo-qa-*`, `demo-llm-*`, legacy `demo-interview-*`) are readable. Evidence is
  limited to `evidence/before.png` / `evidence/after.png` of a verified QA record, re-hashed against
  its evidence record, size-bounded and served with `nosniff` and `no-store`.
- Stored HTML is never served. The export is rebuilt from the loaded result with all text escaped,
  served as an attachment under a sandboxing Content-Security-Policy.
- Errors carry no tracebacks or filesystem paths. A damaged or unfinished run is shown as not
  verified, never as a success.
