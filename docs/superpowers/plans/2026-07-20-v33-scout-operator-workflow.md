# v3.3 Scout Operator Workflow — Implementation Plan

> **For agentic workers:** implemented test-first in bounded, committed increments on
> branch `feature/v3.3-live-scout-discovery` (draft PR #2). Reuse the existing architecture;
> never create a parallel Scout/Dashboard/store.

**Goal:** Complete the missing operator workflow around the existing v3.3 discovery engine:
Dashboard campaign form → bounded Scout run → discovery → commercial triage → safe public QA
of the best candidates → evidence → A/B/C prioritization → persistent history →
pause/stop/resume — culminating in ONE operator-run live acceptance from the Dashboard.

**Architecture:** Thin orchestration + policy + UI layered on the existing
`DiscoveryEngine` (discovery→dedup→suppression→triage→promotion→`ScoutEngine` QA),
`AnalyzedSiteRegistry` (cross-campaign history + lease locks + rescan), `pipeline/browser_qa`
(reversible cart / axe / rendered-perf, fail-closed), the stdlib-HTTP Dashboard (loopback +
CSRF guarded), and the existing Windows Task Scheduler wrapper. No new provider, DB,
scheduler service, or daemon.

**Tech Stack:** Python 3.11 stdlib (dataclasses, http.server), Playwright (existing),
axe-core (vendored/optional), Tavily (existing provider), pytest.

## Global Constraints (verbatim from the spec)

- STRICT SCOPE: no second search provider; no always-on daemon; no new DB; no new scheduler
  service; no Upwork/Fiverr/LinkedIn connectors; no outreach automation; no vulnerability
  scanning; no CAPTCHA bypass; no Lovable; no theme changes; no unrelated refactoring; no new
  audit/readiness cycle.
- DO NOT TOUCH: v3.2 SHA `6cb8578`, PR #1, `main`, the cooler-theme stash.
- Never print `TAVILY_API_KEY`; owner deferred key rotation (accepted risk) — do not reopen.
- Interactive QA is strictly bounded + fail-closed. Never send a message/lead/booking/
  reservation/order/payment/production-signup. Any uncertain boundary, cleanup failure, auth
  ambiguity, CAPTCHA, anti-bot challenge, or unexpected state STOPS the flow and marks it
  non-client-safe. Never bypass logins/CAPTCHA/site protections.
- Honesty: never fabricate live results, external-site totals, SHAs, CI URLs, screenshots, or
  evidence. Distinguish deterministic fixture verification from real external live verification.
  Never mark "installed" as "ready" without the runtime probe.
- Every run is finite. Stop on ANY of: actionable target, discovery limit, QA-analysis limit,
  page limit, duration limit, API-call/credit ceiling. If actionable target not reached,
  finish honestly — never continue indefinitely.

## Session Presets (budgets)

| Preset   | actionable | discovered | qa_analyzed | pages/site | duration |
|----------|-----------:|-----------:|------------:|-----------:|---------:|
| Quick    | 2          | 15         | 5           | 3          | 20 min   |
| Standard | 5          | 40         | 12          | 5          | 45 min   |
| Extended | 10         | 80         | 25          | 5          | 90 min   |

## Named Campaign Presets

- **US-DE Commercial QA Prospects** — US+DE, en+de, commercial/B2B SaaS/e-commerce/booking;
  signals pricing/free trial/book demo/sign up/shop/cart/availability/booking; min score 70;
  Quick; rescan 30d; Weekdays 09:00 Europe/Bratislava, disabled until enabled.
- **Safe Live Acceptance — US/DE** — the acceptance preset: Quick, US+DE, a small representative
  vertical mix, actionable-target stop, no purchases/reservations/submissions/account creation.

## File Map (created / modified)

- Create `core/scout/presets.py` — `SessionPreset`, `SESSION_PRESETS`, `CampaignPreset`,
  `CAMPAIGN_PRESETS`, `build_config(preset, session)` → `DiscoveryCampaignConfig`.
- Modify `core/scout/discovery/config.py` — add `actionable_target`, `site_types`,
  `session_preset`, `max_qa_analyzed` (back-compat defaults).
- Modify `core/scout/discovery/engine.py` — actionable-target stop + 7-counter surface.
- Create `core/scout/priority.py` — A/B/C classification combining commercial + QA evidence.
- Create `core/scout/country_confidence.py` — Verified/Probable/Unverified from bounded evidence.
- Create `core/scout/verticals.py` — vertical profile selection + bounded per-vertical flows
  (extends `pipeline/browser_qa` primitives; booking date-select-stop, saas signup-entry,
  marketplace/e-comm reversible cart, prof-services form-validate-no-submit).
- Create `core/scout/run_control.py` — 11-state machine + pause/resume/stop/checkpoint/recovery.
- Create `core/scout/test_account.py` — Mode-3 isolated-test-account approval gate.
- Create `core/scout/preflight.py` — readiness preflight (Tavily/browser/network/evidence/
  runtime/policy/auth), honest installed!=ready.
- Modify `core/scout/dashboard.py` — campaign form, preset select, preflight panel, progress
  view, history view, run controls (all behind the existing guard).
- Modify `tools/scout_schedule.py` — Manual/Daily/Weekdays/Weekly modes, key never in command.
- Tests: `tests/test_v33_presets.py`, `_priority.py`, `_country_confidence.py`, `_verticals.py`,
  `_run_control.py`, `_test_account.py`, `_preflight.py`, `_dashboard_scout_workflow.py`,
  `_schedule_modes.py`.

## Increments (each ends green + committed)

1. **Presets + budgets + actionable-target stop + counters** — `presets.py`, config fields,
   engine stop/counters. (this increment)
2. **A/B/C prioritization + commercial-vs-QA score split + country confidence.**
3. **Vertical QA profiles + public-action policy (modes 1/2) — deterministic fixture pages.**
4. **Run-control state machine + pause/resume/stop + restart recovery.**
5. **Mode-3 isolated test-account approval gate.**
6. **Dashboard: campaign form + preset select + preflight + progress + history + run controls.**
7. **Scheduling modes via existing Task Scheduler wrapper.**
8. **Finalization: full deterministic tests, push, PR #2 update, one 4-job CI, evidence comment,
   operator runbook (A–H).**

## Acceptance

- Deterministic: all new tests green locally + in CI (4 jobs).
- Live (operator-run, NOT fabricated here): Dashboard → "Safe Live Acceptance — US/DE" →
  preflight pass → Run → bounded run vs real US/DE sites → pause/resume once → A/B/C preserved →
  evidence/history visible → export bundle. Reported by the operator with real evidence.
