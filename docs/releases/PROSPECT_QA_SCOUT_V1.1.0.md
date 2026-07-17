# AI QA Factory / ARK Prospect QA Scout v1.1.0 — local discovery + commercial-triage release

**Release:** `scout-v1.1.0` · **Date:** 2026-07-17 · **Phase:** 8.4

Extends the hardened Scout v1.0.1 QA runtime with a controlled discovery + commercial-triage
front end. Still an honest **local** release — **not** cloud, SaaS, unrestricted global
discovery, automated contact enrichment, automated outreach, or a production deployment.

## What it adds

`core/scout/discovery/` turns "explicit seeds → QA → report" into
"campaign → controlled discovery → normalization → dedup → suppression → cheap commercial triage
→ bounded promotion into the existing Scout v1.0.1 QA engine → report". Entrypoints:
`python main.py scout campaign-demo | campaign-plan | campaign-run | providers`.

- **Providers.** Typed `ProviderMetadata` (auth by env-var reference only). Built-in: a
  deterministic fixture provider (no network; drives the E2E) and a bounded, path-confined,
  secret-scanned file-import provider (CSV/JSON/NDJSON/newline, with a malformed-row report).
  Terms-blocked / disabled / unapproved-live providers never execute. The real provider path is an
  adapter interface that reports a factual readiness state — no scraping fallback. Live discovery
  is opt-in (`--approve-live-discovery`) and never required by automated tests.
- **Campaign + matrix + budgets.** The campaign is validated through the Phase 8.2
  `ProspectCampaign` contracts. The matrix (country × language × industry × business_type × flow ×
  provider) is sized before execution and fails closed above the configured ceiling unless an
  explicit sample is given. Per-provider result budgets, candidate/eligible/promoted caps, a time
  budget, and an optional monetary ceiling all fail closed.
- **Normalization / dedup / suppression.** Candidates are normalized with the Scout URL safety and
  the Phase 8.2 `normalize_hostname`, deduplicated by URL then domain, and likely same-company
  aliases are flagged as *uncertain identity* for review (never silently merged). The Phase 8.2
  `SuppressionPolicy` is applied before any fetch: `NO_SCAN` blocks all profiling; `NO_OUTREACH`
  permits read-only profiling only when the campaign allows it and never becomes outreach-ready.
- **Cheap, explainable triage.** Technical eligibility uses the existing static profiler (never
  Playwright) to reject unreachable / parked / unparseable / unsupported-market candidates.
  Commercial triage builds a Phase 8.2 `LeadScorecard` from cheap page signals across independent
  dimensions. **The commercial score never collects contacts or authorizes outreach**
  (`outreach_eligible` stays False).
- **Bounded promotion.** Only the explainable top-N eligible, non-suppressed candidates are
  promoted, as explicit seeds, into the unchanged hardened Scout v1.0.1 engine, which
  independently re-validates URL safety and performs the full read-only QA + evidence +
  verification + report. A discovery candidate never bypasses Scout safety.
- **Artifacts + dashboard.** 15 canonical artifacts are published atomically and
  content-secret-scanned (`PROSPECT_CAMPAIGN.json` … `DISCOVERY_SUMMARY.md`). The existing
  localhost dashboard gains read-only campaign/candidate/provider views (`/api/campaign`,
  `/api/candidates`, `/api/providers`).

## Reuse (no rebuild)

Reuses the Phase 8.2 contracts (campaign, identity, governance/suppression, business, scoring),
the Scout URL safety + static profiler, `RunStore`, `ArtifactSafeWriter`/`ContentSecretScanner`,
the `ScoutEngine`, and the dashboard/service. **No** second URL-safety engine, company-identity
model, Scout engine, persistence layer, crawler, or dashboard app was built.

## Deferred (future-facing)

Live third-party discovery at scale; a transactional site-memory database, rechecks, retention,
scheduler, and the full operational dashboard (Phase 8.6); public contact intelligence,
disclosure manifests, and outreach **drafting** (Phase 8.7); human-approved sending (Phase 8.8).

## Validation

- Full suite green (mock mode); the exact total for this release is recorded in the current
  handoff (`docs/handoffs/CURRENT.md`). ruff clean; docs audit `[PASS]`; agent readiness `[PASS]`;
  `git diff --check` clean.
- Deterministic discovery-to-Scout E2E green (`pytest tests/test_phase84_discovery_e2e.py`;
  `python main.py scout campaign-demo`): duplicates are never scanned twice; `NO_SCAN`/private/
  malformed URLs are never fetched; terms-blocked and unconfigured providers never execute;
  suppressed state is preserved; commercial scoring never authorizes outreach; budgets and top-N
  fail closed; every promoted target retains provenance and runs the real Scout engine; and no
  secret or contact leaks into any artifact.
- The Scout v1.0.1 QA demo and the real Playwright acceptance still pass unchanged.

## Safety confirmation

No contact discovery/enrichment, outreach drafting or sending, form submission, account creation,
booking, order, payment, CAPTCHA solving, proxy/stealth evasion, or any other external side effect
occurs. `scout-v1.0.0` and `scout-v1.0.1` are unchanged.
