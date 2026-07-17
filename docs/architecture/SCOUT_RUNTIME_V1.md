# Prospect QA Radar v2.0.0 — Runtime Architecture

**Status:** Implemented (Phase 8.3 QA runtime; hardened in 8.3.1; discovery + commercial triage in
8.4; complete pre-send pipeline in Final Phase I; approved communication + product completion in
Final Phase II). Local. Sending is **disabled by default** and only via individually human-approved,
revalidated, at-most-once provider calls; the deterministic tests use a confined local sink only.
**Scope:** the first runnable slice of the [Prospect QA Radar spec](PROSPECT_QA_RADAR_SPEC.md).
It is **not** cloud/SaaS, not unrestricted discovery, not automated outreach, not a deployment,
not full accessibility certification, and not Lighthouse-level performance.

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
  deterministic fixture E2E (no external network, no browser). Its accessibility checks are
  bounded heuristics (not a full axe audit) and it records no real navigation timing (not
  Lighthouse) — both are surfaced as explicit coverage limitations.
- **`PlaywrightBackend`** — optional, lazily imported (`pip install playwright`); adds console
  errors, failed resources, timing, and a screenshot. **Never required by the ordinary suite.**
  It intercepts every request (`page.route`) and re-validates it against the URL policy, so
  redirects/navigations/subresources to loopback/private/link-local/reserved addresses or
  unsupported schemes are aborted; the final URL is re-validated before content is read; rendered
  HTML is byte-bounded; and the browser always closes on error. A marked `playwright_acceptance`
  test exercises the real Chromium path against an allow-listed local fixture.

## Discovery + commercial triage (Phase 8.4)

`core/scout/discovery/` adds a controlled front end to the QA runtime, entrypoints
`python main.py scout campaign-demo|campaign-plan|campaign-run|providers`:

```
campaign (Phase 8.2 ProspectCampaign) + budgets
  → deterministic matrix (country x language x industry x business_type x flow x provider)
  → providers (fixture / file-import / adapter-ready real; budget + terms + trust gated)
  → normalize + dedup (Scout URL safety + Phase 8.2 normalize_hostname)
  → suppression (Phase 8.2 SuppressionPolicy: NO_SCAN blocks all fetch)
  → cheap technical eligibility (static profiler; never Playwright)
  → explainable commercial triage (Phase 8.2 LeadScorecard; never authorizes outreach)
  → bounded top-N promotion INTO the existing Scout QA engine (unchanged, re-validates URLs)
  → atomic, secret-scanned artifacts + read-only dashboard views
```

- Providers declare typed metadata (auth by env-var reference only); terms-blocked / disabled /
  unapproved-live providers never execute. The only built-in live path is an adapter interface
  that reports a factual readiness state — no scraping fallback. Live discovery is opt-in
  (`--approve-live-discovery`) and never required by tests.
- Duplicates, `NO_SCAN`-suppressed, and invalid/private URLs are never fetched. The commercial
  score ranks candidates for QA only; it never collects contacts or authorizes outreach.
- No new persistence layer, URL-safety engine, company-identity model, Scout engine, crawler, or
  dashboard app — everything reuses the existing components. Site-memory / transactional DB,
  contact intelligence, and outreach remain future-facing (Phases 8.5–8.8).

## Complete pre-send pipeline (Final Phase I)

`core/scout/pipeline/`, `core/scout/memory/`, `core/scout/scheduler/`, and
`core/scout/outreach/` extend discovery/QA into the full pre-send workflow, entrypoint
`python main.py scout presend-demo`:

```
promoted candidate
  → adaptive deep-QA planner (relevant capabilities per profile; Phase 8.2 profile artifacts)
  → capabilities: static heuristics (reuse Scout checks) + deep SEO; real axe + real
    chrome_perf_observation + bounded reversible cart (verified cleanup) — acceptance-proven
  → normalized findings (merge on shared root impact; provenance preserved) + full lifecycle
  → evidence center (sanitized, hashed, retention-stamped; secret-bearing payloads rejected)
  → independent verification (client-safe only when verified+sanitized+clean-session+active)
  → transactional SQLite company/site memory (migrations, backup/restore, corruption fail-closed)
  → site fingerprint + recheck classification
  → public contact intelligence (Phase 8.2 contacts) + suppression governance
  → audit-offer mapping → controlled disclosure (Phase 8.2 manifest, computed readiness)
  → outreach DRAFT (structured facts only) → human review queue
  → durable scheduler/queues for internal work
```

**Invariants:** nothing is sent (no send command/button/worker; a DB CHECK makes a "sent" draft
unrepresentable); inferred/named-person contacts are never send-eligible without review;
`NO_OUTREACH` permanently blocks draft readiness; reversible-cleanup failure blocks client-safe
evidence; real axe/performance are distinguishable from static heuristics (never "Lighthouse"
unless Lighthouse runs); the memory DB fails closed on corruption and never silently empties.

## Approved communication (Final Phase II)

`core/scout/comms/` and `core/scout/integrations/` complete the product, entrypoints
`python main.py scout radar-demo|send|outreach-control|comms-status|mcp-audit`:

```
verified prospect (Final Phase I memory)
  → immutable draft revision (snapshot hashes of recipient/body/finding/evidence/disclosure/suppression)
  → explicit single-use, expiring human approval bound to the exact revision + snapshots
  → immediate pre-send revalidation (recompute every gate from authoritative truth; reject placeholders)
  → transactional reservation: consume approval + reserve message (one idempotency key) in one tx
  → provider called EXACTLY ONCE (local sink / sandbox / adapter-ready real; disabled by default)
  → normalized delivery/reply/bounce/opt-out events → durable suppression + follow-up gating
  → human-approved follow-ups (separate revisions) → commercial funnel metrics → artifacts
```

**Invariants:** sending disabled by default + dry-run by default; editing/recipient-change/resolved-
finding/opt-out invalidates the approval; approval replay / duplicate command / restart never send
twice; `OUTCOME_UNKNOWN` never auto-retries; opt-out/bounce/complaint immediately block; a security
finding never enters outreach; MCP servers are disabled by default and never live-accepted (agent-
only ≠ Factory). Schema v2 migrates a real v1.9.0 DB preserving history + suppression. **Exactly-
once external delivery is not claimed**; the tests use a confined local sink (nothing sent).

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
  immutable on resume. A fresh scan gets a unique run id (timestamp + entropy); the engine fails
  closed on run-id reuse and on a `--resume` whose config does not match the original run, so no
  stale artifacts mix into a new run.
- The dashboard binds to `127.0.0.1` only, serves artifacts path-confined to the run directory,
  and exposes a global kill that stops future work and interrupts the active loop. Controls act
  on a run OWNED by the `ScoutService` (`scout dashboard --seeds`); a READ-ONLY attached run
  (`--run-id`) hides controls and its `/api/control` fail-closes with HTTP 409 (no fake success),
  guarded by a same-origin check. No HTTP start/scan endpoint is exposed — starting is CLI-owned.
- Concurrency is fail-closed to `1` (sequential runtime; parallel execution is deferred).
