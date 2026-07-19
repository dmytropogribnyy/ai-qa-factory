# Live Claude worker acceptance (v3.2, items 15-17)

This records the **genuine live-provider evidence** for the bounded autonomous worker and the exact
operator command to reproduce the full production-adapter acceptance. It is honest about what ran
live here versus what requires a clean (non-nested) operator shell.

## What was proven live in this environment

A real failing fixture was repaired by the **live, non-fixture** Claude Code CLI (the same command
`build_worker_command` produces), fail-before / pass-after:

- **Before:** `test_calc.py` genuinely fails — `assert add(2, 3) == 5` → `assert -1 == 5`.
- **Live run:** `claude -p "…fix calc.py so add returns a+b…" --output-format json --permission-mode
  acceptEdits --allowedTools Edit Read --model claude-haiku-4-5-20251001 --max-budget-usd 0.60`
  returned a **real result object**: `subtype=success`, `is_error=false`, a real `session_id`, and
  `total_cost_usd ≈ $0.065`.
- **After:** `calc.py` becomes `return a + b`; `pytest -q test_calc.py` → **1 passed**.

The real `--max-budget-usd` flag is genuinely enforced: a first attempt with `--max-budget-usd 0.30`
on Opus stopped with `subtype=error_max_budget_usd`, `errors=["Reached maximum budget ($0.3)"]` and
applied no edit (first-turn cache creation alone exceeds $0.30 on Opus — hence the cheap haiku default).

## The nested-session constraint (why the full adapter run is operator-gated)

When the **production `ClaudeCodeWorker`** spawns the CLI from *inside a parent Claude Code session*
(`CLAUDE_CODE_CHILD_SESSION` set) with the operator's global hooks active, the child does **not**
auto-apply edits under `--permission-mode acceptEdits` — it returns prose asking to
"approve the pending write permission for `calc.py`" instead of a JSON result. This is an environment
constraint (the identical command run from a **top-level shell** applies the edit), not a worker bug.

Two genuine honesty fixes came out of this and are covered by deterministic tests
(`tests/test_v32_claude_worker.py`):

1. The worker **never reports success** when `--output-format json` yields no result object (an
   un-granted permission prompt / interruption) — `ok=false` with an explicit blocker.
2. Agent scaffold dirs (`.remember/`, `.claude/`, `__pycache__`) are **excluded** from
   `files_changed`, so hook noise is never counted as a produced artifact.

## One clean-shell command (run OUTSIDE any Claude Code session)

Run the full production-adapter live acceptance (real fixture → real Claude repair via
`ClaudeCodeWorker` → fail-before/pass-after → persisted session + evidence → resume through a fresh
worker) in a **plain terminal**, authenticated to Claude:

PowerShell (Windows):

```powershell
$env:AIQA_CLAUDE_LIVE=1; $env:AIQA_CLAUDE_MODEL="claude-haiku-4-5-20251001"; $env:AIQA_CLAUDE_BUDGET="0.60"; `
  .venv\Scripts\python.exe -m pytest tests/test_v32_claude_worker.py::test_live_claude_worker_repairs_a_fixture -q
```

bash:

```bash
AIQA_CLAUDE_LIVE=1 AIQA_CLAUDE_MODEL=claude-haiku-4-5-20251001 AIQA_CLAUDE_BUDGET=0.60 \
  .venv/Scripts/python.exe -m pytest tests/test_v32_claude_worker.py::test_live_claude_worker_repairs_a_fixture -q
```

Cost is ~$0.06 for the one-line fix. The test is skipped by default (operator-gated) so CI never
depends on a paid live call.
