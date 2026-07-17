# AI QA Factory / ARK Prospect QA Scout v1.0.1 — hardened local release

**Release:** `scout-v1.0.1` · **Date:** 2026-07-17 · **Phase:** 8.3.1

A focused independent-acceptance and hardening pass over v1.0.0. Still an honest **local**
release — **not** cloud, SaaS, unrestricted discovery, automated outreach, production
deployment, full accessibility certification, or Lighthouse-level performance.

## What changed (post-release review findings)

1. **Dashboard/run control now genuinely works.** `scout dashboard --seeds "..."` starts a run
   OWNED by a single `ScoutService` (worker + `RunControl` together), so pause/resume/cancel/
   global-kill really drive it, and the report is built when the worker finishes successfully.
   `scout dashboard --run-id <id>` attaches READ-ONLY. `/api/control` returns **HTTP 409** for a
   read-only/attached (or idle) run instead of a fake `{"ok": true}`, and **400** for an unknown
   action. Added a same-origin CSRF guard (no HTTP start/scan endpoint is introduced — start is
   CLI-owned), an artifact-size cap, full HTML-escaping of prospect fields, and an ACTIVE vs
   READ-ONLY mode indicator that hides ineffective controls. A top-level worker failure is now
   recorded as `FAILED` instead of leaving the run wedged at `RUNNING`.

2. **Playwright SSRF hardening.** The real-browser backend intercepts every request and
   re-validates it against the URL policy, so redirects, navigations, and subresources to
   loopback / private / link-local / reserved addresses or unsupported schemes are aborted and
   recorded — never followed. The final URL after navigation is re-validated and its content is
   never read if unsafe. Rendered HTML is byte-bounded by `max_response_bytes`; console-error,
   failed-resource and blocked-request arrays are capped; the screenshot reference is a basename
   only (no absolute-path leak); the browser context/browser always close on error; and safety
   errors are recorded honestly rather than becoming a "successful" observation.

3. **Run-id / stale-artifact isolation.** Fresh scans get a unique run id (UTC timestamp +
   cryptographic entropy) via `fresh_run_id`; the engine fails closed when a fresh run id already
   exists and when a `--resume` config (campaign/seeds/budgets) does not match the original run.
   `--resume` requires an explicit `--run-id`. The bundled demo keeps its deterministic id but
   resets its own path-confined run directory first.

4. **Honest concurrency.** The runtime is sequential; `concurrency` now fails closed unless `1`
   (default `1`). Parallel execution is explicitly **deferred**, not a decorative option.

5. **Real browser acceptance.** A marked `playwright_acceptance` test launches real headless
   Chromium against an allow-listed LOCAL fixture and proves the live path (launch, render,
   viewport, console error, failed resource, blocked internal subresource, confined screenshot,
   CAPTCHA → manual with no interaction, no form submission, full engine → verification → report).
   It is skipped automatically unless playwright + Chromium are installed, so the ordinary suite
   stays deterministic.

6. **Documentation truthfulness.** Removed brittle inline test-count claims from the README
   quick-start/run sections (exact totals live in the versioned release notes and the current
   handoff). Clarified that static accessibility checks are bounded heuristics (not a full axe
   audit) and static performance observations are not Lighthouse/real rendered metrics. A
   regression test guards against stale canonical test-count claims reappearing.

## Deferred (unchanged from v1.0)

Broad/undirected discovery; contact discovery/enrichment; outreach sending; authenticated flows;
`REVERSIBLE_SESSION_WRITE` execution; parallel execution; cloud/deployment. CAPTCHA and
access-prohibited pages remain `MANUAL_ACTION_REQUIRED` (never interacted with or bypassed).

## Safety confirmation

No outreach, form submission, account creation, login, booking, order, payment, CAPTCHA solving,
private-resource access, access-control/proxy/stealth evasion, or any other external side effect
occurs. Scoring never authorizes outreach (`outreach_eligible` always False).
