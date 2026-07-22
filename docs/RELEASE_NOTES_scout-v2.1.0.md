# Release notes — scout-v2.1.0 (2026-07-22)

**AI QA Factory / Scout — daily-usable local release.** Bounded, read-only prospect QA over public sites,
driven from a local operator Dashboard. See `docs/RUNBOOK_SCOUT.md` to run it.

## What's in this release (verified)

- **Discovery → analysis → Dashboard, end-to-end** (live-verified on real public sites via
  `safe-live-acceptance`/Quick, Playwright): Tavily discovery (bounded, de-duplicated, obviously-unsuitable
  large companies excluded) → per-site QA analysis → results surfaced in the Dashboard.
- **`/target` detail card (new):** each finding shows its **confidence** label and a **one-line reproduction
  hint**, ordered by expected commercial value (reuses `core/scout/priority.py` scoring). Dynamic text is
  HTML-escaped and newline-collapsed; absent confidence/repro use a neutral placeholder (never invented).
- **Evidence:** screenshots and captured evidence are attached to target cards and viewable from the Dashboard.
- **Honest operation:** truthful progress/error/skip/budget reporting; bounded finite runs; pause/resume/stop
  with cooperative, honest state; file-based data that persists across a Dashboard restart.
- **Safety:** read-only public analysis only — no outreach, form submission, login, CAPTCHA solving, or
  irreversible action.

## Verification

**Corroborated by this release SHA's record:** GitHub CI green; ruff clean; docs + agent audits PASS.
This PR itself is docs + a version constant only (no source/behaviour change).

**Observed by the operator during the release smoke on this workstation** (live, not part of the committed
diff — reproduce with `docs/RUNBOOK_SCOUT.md`): a bounded `safe-live-acceptance`/Quick discovery run
completed with `discovered=15, eligible=5, analyzed=5, rejected=5, failed=0`, and a target card
(appdirect.com) rendered 10 findings with severity/confidence/repro + a screenshot; the deterministic
`scout demo` completed with 15 findings. The `/target` feature (PR #21) was merged to `main` after an
independent GPT **GO** on its exact head (CI green).

## Deferred (non-blocking; see RUNBOOK §6)
- History-row `last_analysis_at` may lag a re-analysis until promotion (use the target card for current
  findings).
- `scout run --seeds` (CLI) writes report files; Dashboard target cards are populated by the discovery flow.
- Session-independent autonomous writer (Issue #17) parked, disabled by default (PR #19 deferred). The proven
  Direct-Driver GPT review + durable Dashboard/supervisor remain on `main`.

## Requires (operator)
- Tavily key for live discovery (already configured; `python tools/tavily_setup.py` to (re)configure).
