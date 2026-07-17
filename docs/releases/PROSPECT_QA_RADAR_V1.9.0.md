# AI QA Factory / ARK Prospect QA Radar v1.9.0 — complete local pre-send prospect pipeline

**Release:** `scout-v1.9.0` · **Date:** 2026-07-17 · **Phase:** Final Phase I

Completes the first of the two frozen remaining functional phases. An honest **local** release
that runs the **complete pre-send workflow up to a human review queue** and **sends nothing**.

## What it adds (Final Phase I)

Extends the Scout QA + discovery runtime into the full pre-send pipeline:

- **Adaptive deep QA.** A planner selects the relevant capabilities per profile (saas /
  ecommerce / booking / agency / personal_brand / local_service / content_media / startup_mvp),
  producing the Phase 8.2 SITE_PROFILE / BUSINESS_CONTEXT / INTERACTION_BOUNDARY / COVERAGE_MAP
  plus a CAPABILITY_PLAN. Static capabilities reuse the Scout checks (no second engine) and add
  deep technical-SEO signals.
- **Real accessibility + performance.** `run_axe` runs **real axe-core** against the rendered
  page (clearly distinct from the static heuristics); `run_performance` captures a real rendered
  performance observation (honestly named `chrome_perf_observation` with configurable versioned
  thresholds — **not** Lighthouse). Both are exercised by a real local Chromium acceptance.
- **Safe bounded business-flow QA.** One bounded reversible cart action with synthetic data and
  **verified post-cleanup**; a cleanup failure marks the session unclean so its findings can
  never become CLIENT_SAFE. The browser never submits a form.
- **Evidence center + finding normalization + lifecycle.** Sanitized, hashed, retention-stamped
  evidence; normalization merges only on a shared root user impact and preserves provenance;
  findings carry a full lifecycle (UNVERIFIED→…→VERIFIED and ACTIVE→RESOLVED→REGRESSED); only
  independently reproduced, sanitized, current findings are CLIENT_SAFE.
- **Transactional company/site memory.** A narrow SQLite store with schema versioning +
  transactional migrations (interrupted-migration rollback), foreign keys, uniqueness/integrity
  constraints, backup/restore, fail-closed corruption detection, and an idempotent importer.
- **Scheduler + durable queues.** Leased claiming (no duplicate execution after restart), retry
  ceilings with dead-letter, crash-recovery lease reclamation, heartbeats, pause/resume/kill.
- **Rechecks / fingerprints / retention.** Bounded change fingerprints (never capturing
  cookies/session/secrets) + recheck classification; a retention/storage manager with
  explicit-confirmed, path-confined, always-audited purge.
- **Public contact intelligence + governance.** Reuses the Phase 8.2 contact contracts — public
  sources only, inferred candidates never send-eligible, named-person contacts always reviewed,
  NO_OUTREACH permanently blocks draft readiness (never overridden by scores).
- **Audit offers + controlled disclosure + drafts + review queues.** Focused offer mapping
  (bands, never fabricated prices); Phase 8.2 disclosure manifests with fail-closed ceilings and
  computed readiness; drafts generated from structured facts only (no invented facts, no urgency,
  no guessed names); a human review queue. **Drafts are PENDING_REVIEW and can never be sent** (a
  DB CHECK backs the no-send invariant).
- **Dashboard + CLI.** A read-only pre-send review view on the existing localhost dashboard with
  **no send button**; `scout presend-demo` runs the complete deterministic demo, and
  `scout db-status / db-backup / db-restore / review-list / doctor` operate the memory + review.

## Reuse (no rebuild)

Reuses the Phase 8.2 contracts (identity, business, coverage, scoring, contact, disclosure,
governance), the Scout URL safety / profiler / checks / evidence / dashboard, `RunStore`, and
`ArtifactSafeWriter`. New: the SQLite memory + scheduler (no prior local DB/queue existed).

## Honest scope

Real axe/performance/reversible are acceptance-proven; the default deterministic pipeline runs
static-mode capabilities and is browser-free. Deeper polish (larger axe rule catalogue, full
Lighthouse, richer dashboard drill-downs, wider crawl) is deferred to `docs/POST_V2_BACKLOG.md`.
It must **not** be read as claiming any message was sent, automatic outreach, cloud/SaaS,
production deployment, unrestricted global crawling, accessibility certification, or Lighthouse
equivalence when Lighthouse did not run.

## Deferred to Final Phase II (exact)

Human-approved sending; reply/bounce/opt-out history; follow-up controls; CRM/commercial metrics;
startup/installer; evaluation benchmark; the final Prospect QA Radar v2.0 release. **No sending,
provider send-call, or external-communication worker exists before Final Phase II.**

## Safety confirmation

No message, form submission, account creation, login, booking, order, payment, CAPTCHA
interaction, private-resource access, contact enrichment, or any external side effect occurs.
`scout-v1.0.0`, `scout-v1.0.1`, and `scout-v1.1.0` are unchanged.
