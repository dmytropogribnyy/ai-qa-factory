# AI QA Factory / ARK — Product Contract (v3.2, candidate)

v3.2 extends the accepted v3.0.2 core and the v3.1 dashboard into an operator-friendly Autonomous AI
QA Operator. It states plainly what is **deterministic core**, **fixture-verified**, **runtime/live
verified**, **client-authorized-external**, or **needs operator/client** — nothing unverified is shown
as live. Complements [PRODUCT_CONTRACT_V3.md](PRODUCT_CONTRACT_V3.md) and the combined reuse map
([architecture/V32_COMBINED_REUSE_MAP.md](architecture/V32_COMBINED_REUSE_MAP.md)). This is a review
candidate: **not merged, not tagged; main + previous tags unchanged.**

## What v3.2 adds (all over the existing single core)

| Area | Real today | Evidence |
|---|---|---|
| Universal safe project-id (Windows reserved names, OS-independent) at every boundary | real | `tests/test_v32_project_id.py` |
| Analyze idempotency + per-project concurrency | real | `tests/test_v31_operator_dashboard.py` |
| Richer polling change-detection + mobile Work cards | real | `tests/test_v31_dashboard_browser_acceptance.py` |
| Broader secret redaction (argv/stdout/stderr/spawn) with per-field honesty | real | `tests/test_v3_validation_evidence.py` |
| Pro Dark design system (dark default + accessible persisted Light toggle, no flash) | real | `tests/test_v31_dashboard_browser_acceptance.py` (axe both themes) |
| Service Capability Matrix (12 advertised services, honest readiness) | real | `core/orchestration/service_capability.py`, `tests/test_v32_service_capability.py` |
| Access & Identity Bootstrap (no secrets) | real | `core/orchestration/access_bootstrap.py`, `tests/test_v32_access_bootstrap.py` |
| Bounded Claude Code worker adapter (never skip-permissions) | real (adapter) | `core/orchestration/claude_worker.py`, `tests/test_v32_claude_worker.py` |
| Tool/MCP Broker gap report | real | `core/orchestration/tool_gap.py`, `tests/test_v32_tool_gap.py` |
| Genuine service acceptance (flaky, read-only DB, migration, writing, autonomous-operator, AI-MVP) | real | `tests/test_v32_service_acceptance.py` |
| Challenge policy (public Scout never solves; solvers prohibited) | real | `core/orchestration/challenge_policy.py`, `tests/test_v32_challenge_policy.py` |

## Honesty ladder

deterministic-core · fixture-verified · runtime-verified · **live-verified** (only GitHub Actions here)
· client-authorized-external · needs-operator · needs-client · unavailable. A catalog entry, installed
package, mock, deterministic fixture, structural test, or generated-but-unrun config is **never** shown
as a live capability.

## Execution modes & boundaries

- Modes: **PLAN_ONLY**, **AUTONOMOUS_LOCAL** (safe, reversible, project-confined), and
  **APPROVAL_GATED_EXTERNAL** (external/irreversible/paid/production/credential/messaging).
- The Dashboard reads persisted state and performs only guarded, predefined lifecycle mutations
  (loopback Host + Origin + CSRF; no command/argv over HTTP; DNS-rebinding refused on reads too). It
  embeds no chat/editor/terminal and never executes arbitrary code.
- The Claude worker is never exposed as arbitrary HTTP execution; it runs a validated Work Order,
  bounded (turns + timeout + confined workspace), never with `--dangerously-skip-permissions`.
- **Database mutation** requires explicit authorization and is never the default; read-only validation
  refuses any mutation keyword.
- **Public Scout** never solves/bypasses a CAPTCHA and never retries after denial; public-target
  solver services are never integrated. Upwork intake stays manual (no API). Nothing is sent,
  submitted, deployed, purchased, or mutated in production.

## Live provider execution (honest)

The Claude Code CLI is detected (v2.1.198) and the bounded worker adapter is implemented and
fixture/injected verified. The **direct Claude CLI provider command is Live Verified** (a real
failing fixture was repaired: fail-before/pass-after, real session id + cost). The **full production
`ClaudeWorkerExecutor` clean-shell acceptance is Needs Operator** until its gated test passes: inside
a parent Claude Code session the operator's hooks force an interactive permission prompt, so
`acceptEdits` does not apply non-interactively. Verify in a clean, NON-NESTED shell with flags that
the installed CLI supports (verified via `claude --help`, consistent with `build_worker_command`):
`claude -p "<work order>" --output-format json --permission-mode acceptEdits --allowedTools Edit Read
--max-budget-usd 0.60` (or run `pytest -k live_claude_worker` with `AIQA_CLAUDE_LIVE=1`; see
`docs/LIVE_CLAUDE_ACCEPTANCE_V32.md`).

## Autonomous execution scope & honesty (v3.2)

- **Representative workload (multi-file), IMPLEMENTED.** The full persisted lifecycle handles a
  multi-file project with a cross-file defect end to end — worker implementation, a structured
  pre-approved validation command (operator policy, never HTTP), failing-before validation with
  redacted evidence, operator-triggered resume/repair, passing-after validation, review, prepared
  delivery with per-file hash + package-digest verification, and fresh-process resume. Proven
  deterministically by `tests/test_v32_golden_multifile_lifecycle.py`.
- **Repair is operator-triggered, NOT an autonomous loop.** A failed validation moves the project to
  `REPAIR_REQUIRED`; the operator (CLI `client-work worker-resume` / a guarded Dashboard action)
  starts the next bounded execution. There is no self-looping "run until green" agent, and the
  product does not claim one.
- **Language scope.** The lifecycle is language-agnostic; deterministic acceptance uses a Python
  project, and real **TypeScript/Playwright execution** is separately proven by the browser-acceptance
  CI job (`test_v3_genuine_execution_ab.py` runs real `playwright test` on a generated framework).
- **Live provider.** A live `ClaudeWorkerExecutor` run is operator-gated (`AIQA_CLAUDE_LIVE`, clean
  non-nested shell); CI never makes a paid live call.
