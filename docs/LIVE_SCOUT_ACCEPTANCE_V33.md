# Live Scout Acceptance — v3.3 Adaptive Operator Workflow

Operator runbook for the one **Dashboard-driven** live acceptance run. Everything below the
"live" line is deterministically verified in tests/CI; the live run is the only step that touches
real external sites, and **you** run it from your Windows desktop.

## A. Implemented production capabilities (deterministic + CI verified)

- **Adaptive Scout Brain** (not a static crawler): target understanding (archetype / business
  model / critical journeys + confidence + evidence), adaptive replanning on new evidence, separate
  Commercial / QA / Evidence-confidence / Safety-confidence + combined score.
  `core/scout/scout_brain.py`. Contract: `docs/architecture/SCOUT_BRAIN_CONCEPT.md`.
- **Adaptive allocation**: hard ceilings ≠ outcome targets ≠ per-target depth (SKIP/BASELINE/
  SELECTIVE/DEEP); diversity caps; early-stop on outcome targets. `core/scout/adaptive.py`,
  `core/scout/target_planner.py`.
- **Finite runs + 7 counters + stop reasons**: `core/scout/presets.py`, `run_counters.py`,
  `discovery/engine.py` (actionable-target stop, QA cap, consecutive-failure breaker).
- **Production presets** (Balanced default, Conservative, Opportunity, Scheduled Daily) + the
  named US-DE and Safe Live Acceptance presets; strategy + outcome + diversity.
- **A/B/C prioritization + country confidence** (Verified/Probable/Unverified).
- **Per-vertical planning + fail-closed public-action policy**. The current automatic Scout path
  performs read-only navigation/observation. Reversible-interaction policy and deterministic
  fixtures exist, but are not wired into automatic live execution. It never crosses submit/reserve/
  order/pay/signup. `core/scout/verticals.py`, `public_action_policy.py`.
- **Persisted 11-state run-control** (pause/resume/Stop&Save/restart-recovery/no-overlap).
- **Bounded evidence + qualified reproduction video**: separate landing/verification screenshots,
  redacted observation and browser trace, integrity manifest, and short WebM only when the same safe
  interaction is genuinely reproduced and cleanup succeeds. Failed/precondition-only attempts keep
  no video. `core/scout/engine.py`, `core/scout/backends.py`, `core/scout/evidence_policy.py`.
  Load/stress remains refused (single-user only unless separately authorized).
- **Mode-3 test-account approval gate** + **structured bug-reproduction context**.
- **Dashboard**: campaign form + preflight + progress + history + per-target decision trail +
  Pause/Resume/Stop/Export. **Scheduling** modes on the existing Task Scheduler wrapper.
- **Operational memory**: cross-campaign analyzed-site registry (skip processed, explicit rescan,
  resume without repeat).

## F. Start the Dashboard (Windows)

```powershell
cd "D:\1QA AI\ai-qa-factory"
.\.venv\Scripts\python.exe main.py dashboard        # loopback only; open the printed http://127.0.0.1:<port>/
```
(or the desktop launcher, per `local_env_secrets_launcher`). The server binds to loopback and
enforces CSRF + Origin + Host guards.

## G. Where the live preset lives

Dashboard → **Scout → Campaigns → New adaptive campaign** (`/scout/new`) → in **Preset** choose
**"Safe Live Acceptance — US/DE"**. It is Quick-sized, US+DE, conservative strategy, actionable
target 2, no purchases/reservations/submissions/account creation.

## H. Readiness preflight — what it actually probes (installed ≠ ready)

Click **Run readiness preflight**. It really: checks the Tavily key presence (never shows the
value), **launches + closes Chromium headless**, opens a bounded outbound TCP connection, writes+
deletes a probe file in the evidence dir, imports the runtime, validates the campaign is bounded/
no-outreach, and checks for unsupported auth + scheduling. The report is `ok` only when every
required check is `ready`/`configured`.

## I. What a healthy run looks like

After you tick the live-approval box and click **Run**, you land on `/scout/progress?id=…` and see:
run state transitioning (discovering → triaging → analyzing → completed), the 7 counters filling
(Discovered / Eligible / QA analyzed / Actionable / Already / Rejected / Failed), the adaptive
decision table (domain → priority → depth → business model), and an explicit **stop reason**.

## J. What safely blocks or stops the run

Actionable target reached · runtime ceiling · provider budget · max browser targets · excessive
consecutive blocks/failures · operator Stop&Save · a safety boundary (CAPTCHA / auth ambiguity /
cleanup failure / unexpected state → that target is blocked/marked non-client-safe, others
continue). The Dashboard always shows the exact stop reason; an honest partial/blocked result is
shown instead of false success.

## K. Export the internal campaign record

Under **Advanced run diagnostics** on the progress page click
**Export internal campaign record** → it writes
`outputs/scout/_bundles/<campaign_id>/EVIDENCE_BUNDLE.json` (run state, stop reason, discovery
state, brain decision trail) and shows the path. This is an operator/reviewer diagnostic, not a
client attachment. For a client, open a completed exact target and select
**Download client-ready evidence (.zip)**.

## L. CLI fallback (diagnostics only — not the primary path)

```powershell
.\.venv\Scripts\python.exe main.py scout campaign-run --live-provider tavily --approve-live-discovery `
  --countries us,de --industries "B2B SaaS" --tavily-max-results 10
```

## M. Release-readiness checklist

- **Deterministically verified (local + CI):** presets/budgets/actionable-stop, A/B/C + scores +
  country confidence, vertical flows + fail-closed policy, run-control + recovery, adaptive
  allocation + planner, Scout Brain (understanding/replan/scoring), evidence/load policy, preflight,
  campaign service lifecycle, Dashboard routes (render + CSRF), scheduling argv, Mode-3 gate + repro
  context. **4956 passed / 5 skipped.**
- **Browser-fixture verified (not the live Scout path):** the reversible-cart primitive + vertical
  flow invariants on fake pages. The automatic Scout runtime stays read-only; real Playwright launch
  is probed by preflight.
- **CI verified:** current pull requests run the repository CI matrix, including deterministic
  Windows tests and a real Chromium/axe/Playwright acceptance job.
- **Still requires your one live desktop acceptance:** the Dashboard-driven live run above against
  real US/DE sites (real Tavily + real browser + real network), with pause/resume demonstrated and
  the evidence bundle exported. Not run in this environment; not fabricated.

## Honest deferrals (not implemented as live runtime)

- Live **Mode-3 account creation** execution (the approval gate + constraints are implemented).
- Deep per-flow adaptive replanning is wired as decisions/policy; the engine executes bounded
  static+promoted QA today — replanning escalation is surfaced, not yet a live multi-pass loop.
