# Direct Collaboration Driver v1

Status: implemented (GitHub Issue #14). Combines delivery phases B + C + D of the
[Collaborative AI Engineering Model](COLLABORATIVE_AI_ENGINEERING_MODEL.md).

## Purpose

Remove the manual Claude↔GPT copy/paste from the review loop while keeping owner visibility and every
existing safety boundary. It is enabling infrastructure that accelerates Scout/Dashboard/AI QA Factory
completion — not a general multi-agent platform (invariant 10).

The direct reviewer is a **bounded GPT reviewer invoked through the OpenAI API** — not this interactive
ChatGPT conversation. The interactive chat remains the owner console; the local reviewer agent performs
the automated review loop using the canonical independent-reviewer contract.

## Components (`core/collaboration/`)

| Module | Role |
|---|---|
| `envelopes.py` | SHA-bound message vocabulary: `QUESTION/RESPONSE`, `PROPOSAL/CRITIQUE/RECOMMENDATION`, `CHECKPOINT/DECISION` (GO/NO-GO/COMMENT), `ACKNOWLEDGEMENT`, `NEEDS_OWNER`. Code-bound kinds require an exact full 40-char head SHA + branch; bodies are redacted at construction; idempotency key is stable across retries, unique per SHA. |
| `store.py` | Append-only, write-once thread log under the **same** `_review_relay` base (one canonical store). Idempotent replay, open-request queue, envelope-level SHA binding. |
| `budget.py` | Per-thread + daily call/spend caps with a **fail-closed** `check()`, bounded exponential-backoff retries, an idempotent response cache, input clamp+redaction, restart-persistent usage. |
| `reviewer_client.py` | Strict output schema per request kind; `FixtureReviewerClient` (CI) and `OpenAIReviewerClient` (live). The model receives **text only** — no tools, so it cannot merge, write source, run shell, or send externally. |
| `evidence.py` | Bounded, redacted evidence for one exact SHA (capped changed-files + truncated diff + subject + request refs); read-only injectable git runner; no repo dump. |
| `reviewer_driver.py` | Watches open requests → gathers evidence → reviews within budget+retries → validates output → posts the reply immutably. Fails closed to `NEEDS_OWNER` on a stale head, a reached cap, a schema violation, or exhausted retries. Persists health/stage/spend + heartbeat. |
| `session_delivery.py` | Binds a thread to one Claude session UUID (gitignored file); resumes only that session with a **fixed** prompt template, passing the decision as a **data file** (never interpolated into the argv command, never a shell string). Idempotent via a persisted marker; fails safe with no/invalid binding or no native `claude.exe`. |
| `monitor.py` | Owner-visible read model: per-thread state, actor, current/next action, branch/PR/SHA, decision + live head match, driver heartbeat/staleness, timeline, CI refs, spend vs cap. |
| `service.py` | Assembly + worker-side helpers (git head, submit, ack, build driver). |

Launchers: `tools/run_collab_driver.py` (bounded reviewer loop), `tools/collab_ack.py` (worker ACK).
Dashboard: `/collab` page + `/api/collab` JSON (reuses the existing Dashboard/read model — no second
dashboard). OpenAI key is owner-gated: `OPENAI_API_KEY` env or `~/.aiqa/openai.key` (never committed).
The independent reviewer defaults to **`gpt-5.6-sol` in high-thinking mode** (`reasoning_effort=high`) —
GO/NO-GO on code is a high-value decision (invariant 7). Override per deployment with
`AIQA_REVIEWER_MODEL` and `AIQA_REVIEWER_REASONING_EFFORT` (set the latter to `""` for non-reasoning
models). `temperature` is omitted by default since GPT-5 reasoning models accept only the default.

## Safety boundaries

- The remote model is handed text only; it has **no** merge/source-write/shell/external-send capability.
- One writer: Claude on the active branch. The reviewer is independent and read-only with respect to source.
- Secrets are redacted before persistence and before any API submission.
- Fail closed: a reached cap, stale head, malformed output, or exhausted retries escalates to
  `NEEDS_OWNER`/`BLOCKED` and stops — never a hidden unlimited loop.
- Merge is executed only by the trusted local workflow after a validated exact-SHA GO (see the model doc,
  section 13); the driver itself cannot merge.

## Live E2E acceptance (all must pass before "ready" — Issue #14)

1. `QUESTION → GPT RESPONSE → correct Claude session → ACK`, no owner copy/paste.
2. `PROPOSAL → GPT CRITIQUE/RECOMMENDATION → Claude RESPONSE/ACK`, no owner copy/paste.
3. `CHECKPOINT(exact SHA) → GPT GO or NO-GO → Claude receives/ACKs`, no owner copy/paste.
4. Move the branch head after a checkpoint: the old decision is rejected as stale.
5. Restart the driver between processing and delivery: no duplicate API call/decision/delivery.
6. Bind a wrong/nonexistent session: fail safely; do not wake another session.
7. Reach a tiny test budget cap: state becomes `NEEDS_OWNER`/`BLOCKED`, no further calls.
8. Dashboard shows truthful heartbeat, timeline, task, actor, PR/SHA/CI, spend, and owner-action state.
9. Neither reviewer nor relay can merge, write source, send externally, or run arbitrary shell.
10. Local restart does not require re-entering ordinary settings; secrets/session bindings stay local and gitignored.

Deterministic coverage of the wiring lives in `tests/test_collaboration_*.py`; the live cycles (1–3, 7)
require the owner-gated OpenAI key and a bound local Claude session.
