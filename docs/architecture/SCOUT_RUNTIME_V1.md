# Prospect QA Scout v1.0 — Runtime Architecture

**Status:** Implemented (Phase 8.3). Local, bounded, read-only runtime.
**Scope:** the first runnable slice of the [Prospect QA Radar spec](PROSPECT_QA_RADAR_SPEC.md).
It is **not** cloud/SaaS, not unrestricted discovery, not automated outreach, not a deployment.

## Pipeline

```
campaign + 1..10 explicit public seeds
  → fail-closed URL eligibility (core/scout/url_safety.py)
  → bounded profiling + read-only checks (backends.py, checks.py)
  → independent second-pass verification (verification.py)
  → sanitized evidence (sanitize.py, reuses content_safety)
  → non-authorizing scoring (scoring.py, reuses LeadScorecard)
  → durable atomic persistence + resume (store.py)
  → localhost dashboard + global kill (service.py, dashboard.py)
  → report export (report.py, reuses ArtifactSafeWriter)
```

Orchestrated by `core/scout/engine.py` with cooperative pause/resume/cancel/kill
(`control.py`). CLI: `core/scout/cli.py` (`python main.py scout ...`).

## Runtime boundary

**Permitted (default):** fetching public http(s) seeds; following public links; reading
menus/tabs/modals; public search/filter/pagination; viewport checks; console/failed-resource
observation (browser backend); pre-submit form-validation checks; accessibility/SEO inspection;
bounded performance observation; screenshots + sanitized evidence; one public business flow
explored up to (never through) a side-effect boundary.

**Blocked (fail-closed):** form submission; login/credentials; OTP/email/SMS; account creation;
bookings/orders/payments/uploads; CAPTCHA interaction/solving; access-control bypass;
stealth/fingerprint/proxy evasion; automatic outreach; automatic contact discovery; destructive
actions; cloud deployment. CAPTCHA / access-prohibition pages become `MANUAL_ACTION_REQUIRED`
with no interaction while other safe prospects continue.

## Backends

A pluggable `BrowserBackend` keeps automated tests deterministic:

- **`StaticHttpBackend`** — stdlib `urllib` + `html.parser`; no JavaScript, no browser; follows
  redirects manually and re-validates every hop; drops unsafe response headers. Drives the
  deterministic fixture E2E (no external network, no browser).
- **`PlaywrightBackend`** — optional, lazily imported (`pip install playwright`); adds console
  errors, failed resources, timing, and a screenshot. **Never required by tests.**

## Runtime reuse map

**Reused as-is:** `core/orchestration/content_safety.py` (`ContentSecretScanner`,
`redact_intake_text`, `ArtifactSafeWriter`) for sanitization + atomic secret-scanned publishing;
`core/schemas/prospect_scoring.py` (`LeadScorecard`, `ScoreDimension`) for scoring;
`core/schemas/prospect_campaign.py` (`ProspectCampaign`) as optional campaign provenance; Python
stdlib `http.server` for the dashboard (no new web dependency).

**New, thin, domain-specific (`core/scout/`):** URL-safety, run config, backends + page
observation, checks, findings + verification lifecycle, sanitizer wrapper, run store, control,
engine, service, dashboard, report, CLI, bundled demo site.

**Deliberately not built:** a second QA engine, a second evidence engine, a second verifier, a
second report generator, a separate secret scanner, a universal crawler, automatic outreach, or
any anti-bot/CAPTCHA/proxy-evasion capability.

## Safety invariants (tested)

- URL eligibility is fail-closed (localhost/private-IP/creds/unsafe-port/DNS-rebinding rejected).
- Only independently reproduced **and** sanitized findings are client-safe; scoring never sets
  `outreach_eligible`.
- Evidence is a sanitized public fact sheet — no response body, cookies, tokens, or credentials.
- Persistence is atomic and path-confined; corruption fails closed; completed stages are
  immutable on resume.
- The dashboard binds to `127.0.0.1` only, serves artifacts path-confined to the run directory,
  and exposes a global kill that stops future work and interrupts the active loop.
