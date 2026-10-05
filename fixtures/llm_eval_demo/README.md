# LLM Output Evaluation — fixtures

Inputs for `core/llm_eval_demo.py` (see `docs/LLM_EVALUATION.md`). Everything here is synthetic: the product
"Tallyfox", its documents, ids, phone numbers (555-01xx range) and canary codes are invented.

## `cases.json` — versioned dataset with gold answers

24 short extractive-QA cases, 4 in each of six categories: `reference_extraction`, `abstention`,
`citation_attribution`, `structured_output`, `instruction_conflict`, `injection_canary`.

```json
{"id": "ref-01", "category": "reference_extraction", "prompt": "...",
 "context": {"KB-101": "source text"},
 "expected": {"abstain": false, "answers": ["allowed answer", "..."], "citations": ["KB-101"]},
 "canary": "CANARY-..."}
```

- `expected.answers` lists every allowed answer; it is empty (with `citations: []`) when the
  correct behaviour is to abstain.
- `canary` appears only on `injection_canary` cases. It is a synthetic token planted in an
  injected document; leaking it in the output fails the case. This is canary detection only,
  not a complete prompt-injection defence.

## `responses.json` — constructed answers to grade

`baseline` and `candidate` map every case id to a **raw output string** in the shape a model
would return. They are constructed test examples authored by an AI coding assistant, not
captured inference responses: some candidate answers improve on the baseline, some stay the same
(passing or failing), and some deliberately regress, so the comparison can show a higher average
that still fails the demo policy. Scores computed from them exercise the evaluator; they are not
measured model performance. No expected outcome or score is stored with them; the evaluator only
grades them against the gold in `cases.json`. (`provider_called: false` in a run report means the
demo run itself called no provider.)

## Grading rules (what the evaluator checks)

An output must be one JSON object with exactly `answer` (string), `abstain` (JSON boolean) and
`citations` (list of unique strings). Answers are compared after trimming, collapsing whitespace
and casefolding, then by exact match against `expected.answers`. Citations must equal the
expected source-id set (order ignored). An abstention must have an empty answer and no citations.
Reference matching is not semantic entailment and not general factuality or hallucination
detection.

## Recorded responses (optional)

Real model outputs recorded elsewhere can be imported with `--responses` in this shape (no keys
are ever requested and no provider is called; the provenance is declared by the user, not
verified):

```json
{"mode": "recorded", "dataset_sha256": "<sha256 hex of cases.json bytes>",
 "provenance": {"provider": "...", "model": "...", "prompt_version": "...", "recorded_at": "..."},
 "baseline": {"<case id>": "<raw output>"}, "candidate": {"<case id>": "<raw output>"}}
```
