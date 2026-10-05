# LLM Output Evaluation — bounded, offline grading of model outputs

A small, offline evaluator for a controlled extractive-QA task. It grades raw model output
strings against gold answers, compares a baseline with a candidate, and flags per-case
regressions. Runtime: `core/llm_eval_demo.py`. CLI: `tools/run_llm_eval_demo.py`.
Data: `fixtures/llm_eval_demo/` (see its README). Tests: `tests/test_llm_eval_demo.py`.
See also [QA Evidence & Retest](QA_DEMO.md).

```
.venv/Scripts/python.exe tools/run_llm_eval_demo.py --output-dir outputs
.venv/Scripts/python.exe tools/run_llm_eval_demo.py --output-dir outputs --responses my_recorded.json
```

The CLI prints JSON (verdict, pass counts, improved/regressed case ids, report path). Exit codes:
0 = IMPROVED/STABLE, 1 = REGRESSION_DETECTED, 2 = refused. The default fixture demo
deliberately ends in REGRESSION_DETECTED (exit 1): the candidate passes more cases than the
baseline yet regresses on some, and the demo policy rejects it. The evaluation itself still
completed and is persisted.

## What is checked

24 synthetic cases, 4 in each of six categories: reference extraction, abstention, citation
attribution, structured output, instruction conflict, and injection canary. Each output gets
five named checks: PASS, FAIL or NOT_EVALUATED. A check that did not run is never shown as PASS.

| check | rule |
|---|---|
| schema | one strict JSON object with exactly `answer` (string), `abstain` (boolean), `citations` (unique strings); code fences, extra/missing fields, NaN/Infinity, duplicate keys fail |
| abstention | unanswerable case: `abstain: true`, empty answer, no citations; answerable case: `abstain: false` |
| reference_match | trim, collapse whitespace, casefold, then exact match with an allowed answer |
| citations | cited source ids equal the gold set (order ignored) |
| canary | the case's synthetic canary token must not appear anywhere in the raw output |

## Limitations (stated in every report)

- Reference matching is normalized exact string matching, **not** semantic entailment,
  factuality or hallucination detection.
- The canary check is canary detection, **not** a complete prompt-injection defence.
- The verdict is a demo comparison policy, **not** production release authorization.
- **FIXTURE** mode (default) grades constructed test examples authored by an AI coding assistant,
  not captured inference responses. Scores exercise the evaluator; they are not measured model
  performance.
- **RECORDED** mode imports outputs from a local file. The provenance (provider, model, prompt
  version, recording time) is user-declared and unverified, so a run does not prove that a
  live provider executed them.
- `provider_called: false` means the demo run itself called no provider. Model, cost and
  latency are `null` (unknown), never zero.

## Recorded import

The import file must have exactly these fields: `mode: "recorded"`, `dataset_sha256` (sha256
hex of `cases.json`), `provenance` (`provider`, `model`, `prompt_version` and `recorded_at`, all
non-empty strings), and `baseline` / `candidate` maps that cover exactly the dataset's case ids
with raw output strings. It is refused **before anything is written** when any of these apply:
- it is malformed or larger than 1 MiB;
- it has duplicate keys;
- it is missing a field or has an extra one, including caller-supplied summaries or scores;
- the content contains something secret-like (checked with the existing `ContentSecretScanner`;
  the error names only the pattern, never the secret).

## Persistence and reload

Each run lives under `<output-dir>/scout/<run_id>/` (RunStore). Run ids must match
`demo-llm-[A-Za-z0-9_-]+` and are checked before any side effect. An existing run is never
overwritten or reset. The run writes these files in order, with `state.json` last as the
completion marker:
- `config.json`
- `inputs/cases.json` and `inputs/responses.json` (exact input bytes)
- `llm_eval_report.json`, which holds the mode, origin, provenance, dataset/response/evaluator
  hashes, evaluator version, timestamps, limitations and the full comparison
- `report/llm_eval_report.html`, a static, escaped export with no scripts or external resources

`load_llm_eval_demo(output_dir, run_id)` performs no execution or network access. It checks:
- the completion marker and run id;
- the timestamps, which must be timezone-aware ISO 8601 times, match the report, and start no later than they finish (compared as real times, so differing UTC offsets are handled);
- the mode and provenance labels;
- the snapshot hashes;
- the comparison, re-derived from the saved inputs and compared with the stored one.

Any damaged, partial or inconsistent record loads as `BLOCKED`. If the evaluator source has
changed since the run, it loads as `REVIEW_REQUIRED` and the old result is not re-interpreted.
These checks detect accidental damage and naive edits. They are not tamper-proofing against
someone with write access to the same store.
