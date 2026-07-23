# Current Cross-Agent Handoff

**Author of this handoff:** GitHub Copilot (coding agent session)
**Date:** 2026-07-23
**Purpose:** Independent verification of the Phase 8.2 documentation branch and
preparation of handoff + reuse analysis for the next Claude Code session.
**This file records the *verified* state, not merely the expected state.**

---

## Scout Dashboard — PR-A1 + PR-A2 merged — READ FIRST (latest)

**Author:** GitHub Copilot (coding agent). Both PRs based on exact `main` heads, squash-merged
after an owner-relayed independent GPT exact-head GO review (never self-approved/self-merged
without that verdict).

- **PR-A1 "Run Results Golden Path + Manual-Action Truthfulness"** — merged as `main@637490b`
  (squash of PR #34). Exact-run pinning for `CampaignService.target_detail()`, truthful
  MANUAL_ACTION_REQUIRED rendering (no invented stage/boundary/browser/landing values),
  cross-domain/cross-run isolation. `tests/test_scout_run_results_golden_path.py` (16 tests).
- **PR-A2 "Evidence Usability + Operator UI Truthfulness"** — merged as `main@6cd61b6` (squash
  of PR #35, from branch `feat/scout-evidence-usability`, base exactly `main@637490b`). Adds
  `source_kind` (discovery/curated/manual/`""`), `video_mode`, and a bounded `evidence_files`
  list to `target_detail()`; surfaces axe-core (`axe_status`/`axe_violations`) and raw `perf`
  evidence; Dashboard Target page gains truthful curated/manual source labels, a
  video-policy-vs-failure card, an axe-core accessibility card, a raw-evidence-files card, and
  a Problems-table Informational/Defect column; Activity page no longer falsely claims "No
  activity yet" for an attached run with only engine-level history.
  `tests/test_scout_evidence_usability.py` (16 tests).
  - **NO-GO → fix → GO cycle:** first review round (exact head `ba8d98a`) was NO-GO —
    `source_kind` defaulted to `"manual"` for ANY unrecognised/legacy `campaign_name`
    (mislabelling unknown sources). Fixed in `27b5415`: `source_kind` is now `"manual"` only
    for a known manual `campaign_name` (`adhoc`, `scout-demo`, `headed-replay`); anything else
    stays `""` (genuinely unknown). A second minor thread (a code comment implying video no
    longer renders next to screenshots — untrue, only the wording was ambiguous) was reworded.
    Both Copilot review threads replied-to and resolved. Re-reviewed exact head `27b5415` → GO
    → squash-merged.
  - Both PRs' full quality gates were green at merge time: `ruff check .` clean, `docs_audit.py`
    PASS, `agent_readiness_audit.py` PASS, full `pytest tests/ -q` (5332 passed, 5 skipped, 0
    failed on the PR-A2 head), and PR CI (`fast`, `scout-smoke`, `browser-acceptance`, `meta`
    green; `provider-contract`/`relay-smoke`/`windows-full`/`windows-targeted` skipped by the
    expected tiered path-filter).
- **Not started (explicit non-goals for both PRs):** PR-B (coverage/adaptive work), PR-C
  (multi-step flows), outreach, CAPTCHA solving, a new evidence store, a broad Dashboard
  redesign, or any LLM calls added to a read path.

---

## Operator-Path Hotfix — Prospect QA Radar v2.0.2 — earlier


**Author:** Claude Code. **Branch:** `fix/scout-v2.0.2-gmail-operator-path` (from `main@11a7b8a`, the
v2.0.1 release). Earlier tags (incl. `scout-v2.0.1`) are **not** moved. **Not** a new functional phase.

Two independently discovered operator-path defects reproduced and fixed:

- **Blocker 1** — Gmail was not wired into the public `scout send`: `cli._registry` used the demo
  registry (no `gmail_personal`); `GmailProvider` lived only in tests; and the provider was resolved
  only AFTER approval consumption + reservation (stranding state on an unknown provider). Fix: new
  `runtime.build_runtime_provider_registry` (registers `gmail_personal`), the CLI uses it, and a
  **provider preflight** runs BEFORE approval consumption / reservation / attempt — bad providers →
  clean BLOCKED, nothing reserved, zero provider calls.
- **Blocker 2** — OAuth account verification was fail-open (`account or expected_account` invented the
  identity). Fix: scopes validated first; account proven fail-closed via a verified id-token claim;
  unprovable/wrong account or invalid scopes raise and write no token (atomic write, partial temp
  removed); `gmail_status` verifies only via the id-token claim, never the bare `account` field.

**Verified:** targeted operator-path suite green; ruff clean. OAuth remains unconfigured (no creds
supplied); **no provider live-accepted; no real external message sent.** See
`docs/releases/PROSPECT_QA_RADAR_V2.0.2.md`.

---

## Final Independent Acceptance — Prospect QA Radar v2.0.1 — earlier

**Author:** Claude Code. **Branch:** `fix/final-independent-acceptance-v2.0.1` (from `main@286cb16`,
the v2.0.0 release). Earlier tags (`scout-v1.0.0/1.0.1/1.1.0/1.9.0/2.0.0`) are **not** moved.

Independent verification of `scout-v2.0.0` + the real CI fix + the Gmail provider path.
**Not** a new functional phase; no further product phase follows.

**Done (all committed + tested):**

- **CI root cause fixed** — the v2.0.0 `core-deterministic` failure (GitHub run `29614052117`) was a
  test launching a subprocess with a hardcoded Windows `cwd` (`d:\1QA AI\ai-qa-factory`) → Linux
  `FileNotFoundError` on 10 `TestCLIBlockedFlags` cases. Now derives the repo root from the test's
  location + a regression guard against machine-specific hardcoded cwd.
- **Complete contact provenance (schema v3, additive)** + **real persisted gate records**
  (`suppression_checks` / `pre_send_revalidations` / `policy_decisions`) replacing synthetic
  `reval-live`; expanded placeholder rejection.
- **Mandatory reviewed-content proof** (canonical REVIEW_PREVIEW hash); **enforced state machines +
  finalized send-attempts**; **closed pre-provider control race** (zero provider calls on a late
  block); **provider-event trust model** (forged relationships quarantined).
- **Exact-payload provider boundary** + **genuine Gmail API provider** (primary; sender
  `dipptrue@gmail.com`) + **local send-only OAuth desktop flow**; **optional Resend secondary**
  (`darrowcode.com`, excluded from critical path); **daily outreach limits** (5/day, ceiling 10);
  **complete review + Gmail CLI**.
- **CI hardened** with `PROSPECT_RADAR_EXTERNAL_SEND_DISABLED=1` on every job.

**Verified state:** full deterministic suite **4336 passed, 4 pre-existing warnings**; ruff clean;
`docs_audit` **[PASS]**; `agent_readiness` **[PASS]**. **No provider is live-accepted and no real
external message has been sent.** Provider readiness: Gmail **adapter-ready** (no credential in this
environment). See `docs/GMAIL_PROVIDER_SETUP.md` and `docs/releases/PROSPECT_QA_RADAR_V2.0.1.md`.

---

## Final Phase II — Approved communication & product completion (Prospect QA Radar v2.0.0) — earlier

**Author:** Claude Code. **Branch:** `final/phase-2-product-completion` (from `main@86b2339`, the
v1.9.0 release). **`scout-v1.0.0`/`1.0.1`/`1.1.0`/`1.9.0` were not moved.**

The second and final functional phase. The functional roadmap is now **complete**; only the
verification-only Final Independent Acceptance pass remains.

**Implemented (all committed + tested):**
- Independent FP I review → the canonical snapshot/hashing layer + placeholder-reference rejector.
- Additive **schema v2** migration (draft_revisions, approval_records, outbound_messages,
  send_attempts, provider_events, contact_events, followup_plans, commercial_events,
  outreach_controls, recipient_allowlist). A real v1.9.0 DB migrates preserving data + suppression +
  no-send drafts history; transactional interrupted-rollback; idempotent; backup/restore across
  versions.
- **Immutable revisions + single-use expiring approvals** (bound to exact snapshot hashes; edited/
  recipient-changed/resolved-finding/opt-out invalidates them; reviewer required; no bulk approval).
- **Immediate pre-send revalidation** from authoritative truth (rejects placeholder refs).
- **Providers** (mandatory DeterministicLocalSinkProvider + sandbox + adapter-ready real email) +
  outreach controls (**disabled by default**, global kill) checked at every gate.
- **Transactional send** (dry-run default; consume approval + reserve message atomically; provider
  called **exactly once**; `OUTCOME_UNKNOWN` never auto-retried; crash reconcile).
- **Events** (delivery/reply/bounce/opt-out/complaint; idempotent; durable suppression), **follow-up**
  (individually approved), **responsible disclosure** (security findings never enter outreach),
  **commercial metrics** (factual; zero-incident counters).
- **MCP + VS Code integration audit** (14 servers, all disabled by default, never live-accepted,
  agent-only ≠ Factory; adversarial guards; `.vscode` recommendation files; `mcp-audit` CLI).
- **CLI** (`send`/`radar-demo`/`outreach-control`/`comms-status`/`mcp-audit`/`doctor`), a read-only
  dashboard communication view with **no send button**, a Windows launcher, and **CI**.

**Nothing is sent to a real recipient.** Sending is disabled by default; the deterministic tests +
full E2E + benchmark use a confined local sink. Exactly-once external delivery is not claimed.

**Validation (this session, on the branch and merged main):** full suite **4251 passed, 4
pre-existing warnings, 0 failed** (was 4208 at v1.9.0; +43 FP II). ruff clean; docs audit `[PASS]`;
agent readiness `[PASS]`; `git diff --check` clean. Complete deterministic local-sink v2 E2E green;
benchmark meets all zero-incident targets; schema v1→v2 migration + backup/restore green; Scout QA
demo, discovery, pre-send, radar demos, and prior Playwright/axe acceptance still pass. SCOUT_VERSION
→ 2.0.0. Merged `--no-ff` and tagged `scout-v2.0.0` (new tag; older tags untouched); exact
merged-main HEAD/tag in the final report. **CI:** the workflow is added; a real GitHub Actions run
is triggered by the push to main and must be verified on GitHub (not claimed green here). **No real
external message was sent during acceptance.**

---

## Final Phase I — Complete pre-send prospect pipeline (Prospect QA Radar v1.9.0) — READ FIRST (previous)

**Author:** Claude Code. **Branch:** `final/phase-1-pre-send-pipeline` (from `main@7cecb26`, the
Scout v1.1.0 release). **`scout-v1.0.0`/`1.0.1`/`1.1.0` were not moved.**

Completes the first of the two frozen remaining functional phases. The remaining pre-v2 roadmap is
now frozen at exactly **Final Phase I** (done) + **Final Phase II** (planned) + a verification-only
pass; the historical 8.5–8.9 map is preserved as superseded. Non-blocking depth is recorded only in
`docs/POST_V2_BACKLOG.md`.

**Implemented (all committed + tested):**
- Phase 8.4 independent review → 4 fail-closed fixes (provider-result type confusion,
  campaign-dir reuse guard, absolute-path leak, malformed CandidateRecord coercion).
- Adaptive deep-QA planner (per-profile capability selection + Phase 8.2 SITE_PROFILE/
  BUSINESS_CONTEXT/INTERACTION_BOUNDARY/COVERAGE_MAP/CAPABILITY_PLAN) + static capabilities (reuse
  Scout checks + deep SEO).
- Real capabilities: **real axe-core** (`run_axe`), a real rendered `chrome_perf_observation`
  (not Lighthouse), and a bounded reversible cart action with verified cleanup — all
  real-Chromium acceptance-proven (`-m final1_browser_acceptance`).
- Evidence center + finding normalization + full lifecycle (UNVERIFIED→…→VERIFIED and
  ACTIVE→RESOLVED→REGRESSED); client-safe gated on verified+sanitized+clean-session+active.
- Transactional SQLite company/site memory (migrations + interrupted-rollback, FKs/constraints,
  backup/restore, corruption fail-closed, idempotent importer); durable scheduler/queues (leases,
  retries, dead-letter, crash-recovery reclaim, pause/kill).
- Rechecks + site fingerprints + retention/storage (confirmed, path-confined, audited purge).
- Public contact intelligence + governance (inferred/named-person never send-eligible without
  review; `NO_OUTREACH` permanently blocks); audit offers; controlled disclosure (Phase 8.2
  manifest, computed readiness, fail-closed ceilings); drafts from structured facts only; human
  review queues.
- Pre-send orchestrator + full campaign artifact set; read-only dashboard pre-send view with **no
  send button**; `scout presend-demo` + `db-status/backup/restore/review-list/doctor`.

**Nothing is sent** — no send command, button, or worker; a DB CHECK makes a "sent" draft
unrepresentable. **Deferred to Final Phase II:** human-approved sending, reply/opt-out history,
follow-ups, CRM metrics, installer, benchmark, v2.0 release.

**Validation (this session, on the branch and merged main):** full suite **4208 passed, 4
pre-existing warnings, 0 failed** (was 4152 at Scout v1.1.0; +56 Final Phase I). ruff clean; docs
audit `[PASS]`; agent readiness `[PASS]`; `git diff --check` clean. Deterministic integrated
pre-send E2E green; real axe/performance/reversible Chromium acceptance **3 passed**; the Scout QA
demo, discovery campaign-demo, and prior Playwright acceptance still pass. SCOUT_VERSION → 1.9.0.
Merged `--no-ff` and tagged `scout-v1.9.0` (new tag; older tags untouched); exact merged-main
HEAD/tag are in the final report. **Honest scope:** real axe/perf/reversible are acceptance-proven;
the default deterministic pipeline is static-mode and browser-free; deeper polish is in
POST_V2_BACKLOG. No cloud/SaaS/deployment; no accessibility certification; not Lighthouse.

---

## Phase 8.4 — Discovery + commercial triage (Scout v1.1.0) — READ FIRST (previous)

**Author:** Claude Code. **Branch:** `phase/8.4-discovery-commercial-triage` (from `main@dbe1579`,
the v1.0.1 release). **`scout-v1.0.0` and `scout-v1.0.1` were not moved.**

Adds the first controlled discovery + commercial-triage runtime (`core/scout/discovery/`,
`python main.py scout campaign-demo|campaign-plan|campaign-run|providers`) and rebases the roadmap
on reality.

- **Roadmap rebase.** `PRODUCT_VISION_2026` phase map split into target / implemented (8.0–8.4) /
  remaining (8.5–8.9, finite); `PROSPECT_QA_RADAR_SPEC` status corrected from "not implemented" to
  "partially implemented"; explicit Phase 8.4 contract added to `PHASE_CONTRACTS.md`.
- **Runtime.** campaign (Phase 8.2 `ProspectCampaign`) → bounded matrix + budgets → providers
  (deterministic fixture + file-import + adapter-ready real, all gated by trust/terms/approval;
  terms-blocked and unconfigured never execute) → normalize + dedup (Scout URL safety +
  `normalize_hostname`; uncertain identity held, never merged) → suppression (`SuppressionPolicy`;
  `NO_SCAN` blocks all fetch) → cheap static technical eligibility → explainable commercial triage
  (`LeadScorecard`; never authorizes outreach) → bounded top-N promotion into the **unchanged**
  Scout v1.0.1 engine (re-validates URL safety) → 15 atomic secret-scanned artifacts + read-only
  dashboard campaign views.
- **Reuse-first.** No second URL-safety engine, company-identity model, Scout engine, persistence
  layer, crawler, or dashboard app. Contact intelligence, disclosure, outreach, and a
  transactional site-memory DB remain deferred (Phases 8.6–8.8).

**Validation (this session, on the branch and merged main):** full suite **4152 passed, 4
pre-existing `PytestCollectionWarning`s, 0 failed** (was 4124 at v1.0.1; +28 Phase 8.4). ruff
clean; docs audit `[PASS]`; agent readiness `[PASS]`; `git diff --check` clean. Deterministic
discovery-to-Scout E2E green (`pytest tests/test_phase84_discovery_e2e.py`; `python main.py scout
campaign-demo` → COMPLETED, 3 promoted, 1 held). The Scout v1.0.1 QA demo (`scout demo` → v1.1.0
COMPLETED) and the real Playwright acceptance (2 passed) still pass. Playwright stays optional.
**Local release only** — no contact enrichment/discovery, outreach, cloud/SaaS, or deployment.
Merged to `main` with `--no-ff` and tagged `scout-v1.1.0` (new tag; `scout-v1.0.0`/`scout-v1.0.1`
untouched); exact merged-main HEAD/tag are in the final report.

---

## Phase 8.3.1 — Scout v1.0.1 acceptance hardening — READ FIRST (previous)

**Author:** Claude Code. **Branch:** `fix/scout-v1.0.1-acceptance-hardening` (from `main@3035cf4`,
the v1.0.0 release). **`scout-v1.0.0` was not moved.**

An independent post-release acceptance pass that reproduced and fixed six review findings without
changing the runtime boundary:

1. **Dashboard/control** — `scout dashboard --seeds` now starts a run OWNED by one `ScoutService`
   (worker + `RunControl`), so pause/resume/cancel/global-kill genuinely drive it and the report
   is built on success; `--run-id` attaches READ-ONLY. `/api/control` fail-closes with **HTTP 409**
   for a read-only/attached run (no fake success), **400** for unknown actions; same-origin CSRF
   guard; no HTTP start/scan endpoint (start is CLI-owned). Worker failure → `FAILED`, not stuck
   `RUNNING`.
2. **Playwright SSRF** — every navigation/redirect/subresource is intercepted and re-validated;
   the final URL is re-validated before content is read; HTML is byte-bounded; arrays capped;
   screenshot ref is a basename; browser always closes. Redirect/rebinding now blocked on **both**
   backends.
3. **Run isolation** — fresh scans get a unique run id (timestamp + entropy); the engine fails
   closed on run-id reuse and on a `--resume` config mismatch (no stale-artifact mixing).
4. **Concurrency** — fail-closed to `1` (sequential runtime; parallel deferred).
5. **Real browser acceptance** — a marked `playwright_acceptance` test launches real headless
   Chromium against an allow-listed local fixture (proves launch/render/console/failed-resource/
   blocked-subresource/screenshot/CAPTCHA-manual/no-submit + engine→report). Actually executed.
6. **Docs truthfulness** — removed brittle inline test totals from the README generic sections;
   clarified static a11y/perf as bounded heuristics (not axe/Lighthouse); added a regression guard.

**Validation (this session, on the branch):** full suite **4124 passed, 4 pre-existing
`PytestCollectionWarning`s, 0 failed** (was 4090 at v1.0.0; +34, incl. 2 real-browser acceptance
tests that run because Chromium is installed and otherwise skip). ruff clean; docs audit `[PASS]`;
agent readiness `[PASS]`; `git diff --check` clean; `python main.py scout demo` COMPLETED;
dashboard-control HTTP acceptance green; real Playwright acceptance green
(`python -m pytest -m playwright_acceptance -q`). Playwright stays an **optional** dependency (not
in `requirements.txt`). **Local release only** — no cloud/SaaS/unrestricted discovery/automated
outreach/deployment/full-a11y-cert/Lighthouse. Merged to `main` with `--no-ff` and tagged
`scout-v1.0.1` (new tag; `scout-v1.0.0` untouched); exact merged-main HEAD/tag recorded in the
final report.

---

## Phase 8.3 — Prospect QA Scout v1.0 (local runtime) — READ FIRST (previous)

**Author:** Claude Code. **Branch:** `phase/8.3-scout-vertical-mvp` (created from `main@7a10485`).

This session built the **first ARK runtime**: a genuinely runnable, bounded, read-only local
`Prospect QA Scout v1.0` (`core/scout/`, `python main.py scout ...`). Contracts-only Phase 8.2
stays intact and is reused, not rewritten.

**Pipeline:** campaign + 1–10 explicit public seeds → fail-closed URL eligibility → bounded
profiling + read-only checks → independent second-pass verification → sanitized evidence →
non-authorizing scoring → durable atomic persistence/resume → localhost dashboard (global kill)
→ report export.

**Reuse:** `content_safety` (`ContentSecretScanner`, `redact_intake_text`, `ArtifactSafeWriter`)
for sanitized + atomic report publishing; `LeadScorecard`/`ScoreDimension` for scoring;
`ProspectCampaign` for provenance; stdlib `http.server` for the dashboard (no new dependency).
A pluggable backend keeps tests deterministic (stdlib `StaticHttpBackend`; optional lazy
`PlaywrightBackend`, never required by tests).

**Safety:** no form submission/login/outreach/CAPTCHA/evasion/side effects; CAPTCHA + access
prohibition → `MANUAL_ACTION_REQUIRED` (no interaction); only reproduced + sanitized findings are
client-safe; scoring never authorizes outreach; dashboard is `127.0.0.1`-only with path-confined
artifact serving and a global kill switch.

**Validation:** full suite **4090 passed** (+74 Phase 8.3), 4 pre-existing warnings; ruff clean;
docs audit + agent readiness PASS; `git diff --check` clean; deterministic fixture E2E green
(`python main.py scout demo`). **Local release only** — no cloud/SaaS/unrestricted discovery/
automated outreach/deployment. Merged to `main` with `--no-ff`; tagged per convention.

---

## Claude Code Finalization Session (2026-07-17) — READ FIRST (previous)

**Author:** Claude Code. **Branch:** `phase/8.2-prospect-contact-disclosure-contracts`.
**origin/main before this session:** `d467eba` (unchanged until the merge below).

**What this session did:**

1. **Recovered + independently reviewed** the interrupted local diff (Copilot then Codex):
   `prospect_contact.py`, `prospect_disclosure.py`, and their tests. Verified every claimed
   invariant against code and adversarial tests — the contact/disclosure hardening is
   complete and correct. Committed as **`bc2ae99`** (`fix: harden Phase 8.2 contact and
   disclosure readiness`).
2. **Phase 8.2-wide review** found a real fail-open: the earlier-slice `from_dict` methods
   silently dropped malformed nested list entries and silently coerced a present-but-malformed
   nested object to a permissive default (a corrupted `suppression`/`retention` policy became
   a disabled default — a suppression bypass). Fixed fail-closed across `prospect_interaction`
   (shared helpers) + `prospect_campaign/identity/business/coverage/lifecycle/scoring/
   governance`. Added the full synthetic contract journey test
   (`tests/test_phase82_contract_journey.py`, 27 tests). Committed as **`e235fcd`**
   (`fix: fail-closed nested parsing across Phase 8.2 contracts + journey test`).

**Validation (this session):** ruff clean; Phase 8.2 targeted **372 passed** (60+64+94+30+53+44
+ 27 journey); full suite **4016 passed, 4 warnings, 0 failed**; docs audit [PASS]; agent
readiness [PASS]; `git diff --check` clean. The 4 warnings are the pre-existing
`PytestCollectionWarning`s (unrelated).

**Merge:** after these commits and gates, this session merges the child branch into `main`
with `--no-ff` (no squash/rebase/amend), re-runs the full gate on merged main, and pushes
main. No release tag. All Phase 8.2 remains contracts/planning only — **no runtime**
(no discovery, crawl, browser, MCP, network, contact lookup, outreach, dashboard worker,
CAPTCHA, proxy evasion, or external side effect occurred).

---

## Implementation Session Update (2026-07-17, slice-3/4 hardening + contact/disclosure) — READ FIRST

Two branches are now in play (neither merged):

- **Core contracts branch** `phase/8.2-prospect-core-contracts` @ `ad58f45`
  (`fix: harden Phase 8.2 identity lifecycle and scoring contracts`) — pushed.
- **Child contact/disclosure branch** `phase/8.2-prospect-contact-disclosure-contracts`
  (created from `ad58f45`) — tip is the docs commit for this slice (run `git log --oneline -6`).
- **origin/main:** `d467eba74f478a968415abfa5da39dd43812f973` (unchanged).

**New commits this session (newest last):**

| Branch | Commit | Subject |
|---|---|---|
| core | `ad58f45` | fix: harden Phase 8.2 identity lifecycle and scoring contracts (Part A) |
| child | `f24de8a` | feat: add Phase 8.2 public business contact contracts |
| child | `2fa8c9f` | feat: add Phase 8.2 controlled disclosure contracts |
| child | `<tip>` | docs: document Phase 8.2 contact and disclosure slice |

**Part A — slice-3/4 hardening (`ad58f45`, core branch):**
- `normalize_hostname`: rejects IPv4/IPv6 (`ipaddress`), invalid labels (leading/trailing
  hyphen, underscore, empty), enforces length; IDNA-encodes international domains; single
  documented `is_primary`⇔`relation="primary"` rule. `CompanyIdentity` requires a name or a
  domain and de-dups brands/aliases case-insensitively.
- `ProspectLifecycle`: full **history integrity** (contiguity, `state_version` = transition
  count, status/previous consistency) + **approved lineage** for `CONTACTED`; `APPROVED`
  transitions require `actor` + `approval_ref`; late outreach snapshots cannot be forged.
- Governance: enabled suppression forces `manual_override_required`, normalizes domains,
  validates ISO + COOLDOWN ordering; retention forces the composed `CleanupPolicy` inert
  (`enabled=False`); recheck forces pre-send revalidation, restricts full re-audit to `L4`,
  forbids L0 change detection; `MONITOR_CHANGES_ONLY` permits only L0/L1.
- Scoring: rejects bool/str/NaN/±Inf weights (`math.isfinite`); `REJECTED` forbids outreach;
  `outreach_eligible=True` requires `outreach_eligibility_ref`.

**Child slice — contact / storage / disclosure:**
- `prospect_contact.py` (`f24de8a`) — `ContactProvenance`, `ContactStatus`, `ContactRecord`,
  `ContactCollection`. Public sources only; deterministic email/phone/form normalization
  (no invented country code, no deliverability claim); inferred contacts never `VERIFIED`;
  named-person → manual review; only `VERIFIED` is an outreach candidate (computed); dedup
  keeps the stricter status and unions provenance.
- `prospect_disclosure.py` (`2fa8c9f`) — `StorageClass`, `DisclosureLevel`, `DisclosureStage`,
  `DisclosureItem`, `FindingDisclosurePolicy`, `DisclosureManifest`. Storage (handling) kept
  separate from disclosure level (permission); references only; `CLIENT_SAFE` requires
  sanitized + no PII/secrets; `OUTREACH_ELIGIBLE` requires independent verification +
  `CLIENT_SAFE` + minimal teaser; responsible-disclosure stays `INTERNAL_ONLY`; manifest
  readiness is **computed** (contact + suppression-check + revalidation + approval); sends nothing.
- `docs/ARTIFACT_CONTRACTS.md` maps these to planned `CONTACTS.json` / `DISCLOSURE_MANIFEST.json`
  etc. (none generated at runtime); provenance is nested, not a separate artifact.

**Reuse decisions taken:** `SchemaMixin`; `SourceReference` + `Confidence`;
`normalize_hostname` (shared). `ContactProvenance` nested in `ContactRecord` (no separate
schema). `DisclosureManifest` implemented as a **fresh computed-readiness** schema, **not** an
extension of `ClientDeliveryManifest` (recorded in the reuse analysis). `StorageClass`
implemented (was deferred), kept separate from `DisclosureLevel`.

### Validation (this session)

| Gate | Result |
|---|---|
| Targeted prospect tests (6 modules) | **303 passed** (60 + 64 + 94 + 30 + 29 + 26) |
| Full suite `pytest tests/ -q` | **3947 passed, 4 warnings** |
| `ruff check .` | All checks passed |
| `tools/docs_audit.py` | [PASS] (see final gate) |
| `tools/agent_readiness_audit.py` | [PASS] (see final gate) |
| `git diff --check` | clean |

Test progression this session: 3850 → 3947 (+97: +42 hardening, +29 contacts, +26 disclosure).
The 4 warnings are the same pre-existing `PytestCollectionWarning`s (unrelated).

### Deferred (still planned Phase 8.2)

Synthetic data contracts; dashboard information architecture; and all discovery, contact
lookup, evidence capture, revalidation, outreach, delivery, and execution runtime.

### Unresolved questions for Claude Code

- Confirm `DisclosureManifest` as a fresh computed-readiness schema (vs. extending
  `ClientDeliveryManifest`) is the desired direction.
- Confirm the two-branch layout (core hardening + child contact/disclosure) is acceptable, or
  whether the child branch should be rebased/re-parented before review (note: no rebase was
  performed).
- Confirm hostname policy (IDNA + reject single-label/IP) and the phone normalization that
  never invents a country code match the intended contact model.

### Next Claude Code review step

1. Verify Git state: core branch `phase/8.2-prospect-core-contracts` @ `ad58f45`; child
   branch `phase/8.2-prospect-contact-disclosure-contracts` (tip = contact/disclosure docs
   commit); base `6a25288`; `origin/main` `d467eba`; neither merged.
2. Review the child-branch diff `ad58f45..HEAD` (contacts + disclosure) and the core-branch
   hardening diff `d66f8f6..ad58f45` — schema/contracts only, no runtime.
3. Challenge: `DisclosureManifest` not reusing `ClientDeliveryManifest`; contact VERIFIED
   gating; storage-vs-disclosure separation; computed readiness (not forgeable via `from_dict`).
4. Inspect fail-closed defaults: inferred≠verified, named-person manual review, suppression
   never outreach-eligible, `OUTREACH_ELIGIBLE` requires verified+CLIENT_SAFE, responsible
   disclosure INTERNAL_ONLY, lifecycle approved lineage.
5. Rerun the six `test_phase82_*` modules plus the full gate.
6. Withhold merge until explicit human authorization. The next contracts-only slice (if
   approved) is synthetic data / dashboard IA — still no runtime.

---

## Implementation Session Update (2026-07-17, slices 2H/3/4) — READ FIRST

This session hardened slice 2 and added two more contracts-only slices (identity/lifecycle/
governance and scoring). All schema/planning only; no runtime. Merge was not performed.

### Latest state

- **Active branch:** `phase/8.2-prospect-core-contracts`
- **Active branch HEAD:** tip of that branch (run `git log --oneline -10`) — the
  `docs: document Phase 8.2 identity and lifecycle slice` commit.
- **Base documentation branch:** `phase/8.2-prospect-radar-contracts` @ `6a25288`, pushed.
- **origin/main:** `d467eba74f478a968415abfa5da39dd43812f973` (unchanged).
- **Merge state:** neither branch merged.

**New commits this session (newest last):**

| Commit | Subject |
|---|---|
| `b957a38` | fix: harden Phase 8.2 business profile contracts (Part A) |
| `8fa7f3d` | feat: add Phase 8.2 prospect identity and lifecycle contracts (Part B) |
| `5f20740` | feat: add Phase 8.2 prospect scoring contracts (Part C) |
| `<tip>` | docs: document Phase 8.2 identity and lifecycle slice |

**Part A — slice-2 hardening (`b957a38`):**
1. `BusinessContext.business_type` uses new `BUSINESS_TYPES`; `SiteProfile.resource_type`
   uses `RESOURCE_TYPES` — distinct vocabularies (old values kept for backward compat).
2. `SiteProfile` de-dups surfaces; a route cannot be both public and authenticated;
   `public_open` cannot have authenticated surfaces.
3. `SiteFingerprint` adds `fingerprint_algorithm` (`sha256`) and validates digest shape
   (64 lowercase hex; rejects URLs/secrets/prose; empty allowed; lowercase-normalized).
4. `BusinessFlowProfile.planned_interaction_action_class` rejects `DESTRUCTIVE`.
5. `CoverageArea` requires non-empty `area`, rejects blank evidence refs, dedups refs.

**Part B — slice 3 identity/lifecycle/governance (`8fa7f3d`):**
- `prospect_identity.py` — `DomainIdentity` (bare-hostname normalization; rejects
  URL/credentials/port/whitespace/single-label; lowercase + trailing-dot strip),
  `CompanyIdentity` (hostname-unique domains, ≤1 primary, deduped brands/aliases).
- `prospect_lifecycle.py` — `ProspectTransition`, `ProspectLifecycle` + `PROSPECT_STATES`
  + deterministic `ALLOWED_TRANSITIONS` + `TERMINAL_STATES`. `CONTACTED` requires an
  APPROVED/COOLDOWN lineage; `APPROVED`≠sent; `PAID_AUDIT`≠payment; SUPPRESSED≠ARCHIVED.
- `prospect_governance.py` — `SuppressionPolicy` (modes NO_OUTREACH/NO_SCAN/COOLDOWN/
  MONITOR_CHANGES_ONLY; enabled requires reason; COOLDOWN requires expiry),
  `ProspectRetentionPolicy` (**composes `CleanupPolicy`**; forces dry-run/preserve-git/
  preserve-client; preserves suppression+identity; negative durations rejected; deletion
  never executed), `RecheckPolicy` (L0–L4; pre-send revalidation default on; full re-audit
  default off), `ProspectGovernancePlan` (NO_SCAN conflicts with an active recheck).

**Part C — slice 4 scoring foundation (`5f20740`):**
- `prospect_scoring.py` — `ScoreDimension` (12 independent 0..100 axes), `LeadScorecard`
  (dimensions stay visible; optional `weighted_total` only from explicit/validated/
  normalized weights; no hidden single score; `outreach_eligible` default False;
  access-complexity/public-coverage/remediation-fit independent), `ProspectPriority`
  (A/B/C/D/REJECTED). `OpportunityFilterAgent` inspected as precursor only, not reused.

**Reuse decisions taken (verified):** `SchemaMixin`; `SourceReference`; `Confidence`
values; `WorkRunState`/`StateTransition` *shape* for the lifecycle (parallel vocabulary);
`CleanupPolicy` **composed** by retention (no competing cleanup engine). `DomainIdentity`
kept standalone (not folded into `CompanyIdentity`). `StorageClass` remains deferred.

### Validation (this session)

| Gate | Result |
|---|---|
| Targeted prospect tests (4 modules) | **206 passed** (60 + 64 + 60 + 22) |
| Full suite `pytest tests/ -q` | **3850 passed, 4 warnings** |
| `ruff check .` | All checks passed |
| `tools/docs_audit.py` | [PASS] |
| `tools/agent_readiness_audit.py` | [PASS] |
| `git diff --check` | clean |

Test progression: 3747 → 3768 (Part A +21) → 3828 (Part B +60) → 3850 (Part C +22). The 4
warnings are the same pre-existing `PytestCollectionWarning`s (unrelated).

### Deferred (still planned Phase 8.2)

Contact records/provenance/status, findings/disclosure, synthetic data, `StorageClass`,
dashboard information architecture. **Phase 8.2 as a whole remains planned.**

### Unresolved questions for Claude Code

- Confirm the prospect lifecycle transition map (esp. control-state edges and the
  `CONTACTED` approved-lineage guard) matches the intended Scout workflow.
- Confirm `ProspectRetentionPolicy` composing `CleanupPolicy` (vs. a per-`StorageClass`
  map) is the desired retention shape; `StorageClass` was deferred.
- Confirm `DomainIdentity` staying standalone (not folded into `CompanyIdentity`) is desired.
- Confirm hostname normalization rejecting single-label/internal hosts is acceptable.

---

## Implementation Session Update (2026-07-17, continued) — historical

The human extended this Copilot session and authorized: committing the handoff files,
pushing the documentation branch, creating an implementation branch, implementing the
**first Phase 8.2 contracts slice**, then (a further extension) **hardening slice 1** and
implementing a **second contracts-only slice**. All of that is done (schema/planning
only). Merge remained prohibited and was not performed.

### Latest state (Part A hardening + Part B slice 2)

- **Active branch:** `phase/8.2-prospect-core-contracts`
- **Active branch HEAD:** the tip of that branch (run `git log --oneline -8`).
- **Base documentation branch:** `phase/8.2-prospect-radar-contracts` @ `6a25288`, pushed.
- **origin/main:** `d467eba74f478a968415abfa5da39dd43812f973` (unchanged).
- **Merge state:** neither branch merged.

**Full commit chain (newest last):**
`d467eba → f13b4f7 → b047ea8 → 6a25288 → bcc1b85 → 4144233 → 9280dfc → 74ecc98 → db772fb → <docs slice-2 tip>`

| Commit | Subject |
|---|---|
| `bcc1b85` | feat: add Phase 8.2 prospect planning contracts (slice 1) |
| `4144233` | docs: document Phase 8.2 prospect contract slice |
| `9280dfc` | docs: note line-ending normalization in Phase 8.2 handoff |
| `74ecc98` | fix: harden Phase 8.2 prospect contract invariants (Part A) |
| `db772fb` | feat: add Phase 8.2 business and site profile contracts (slice 2) |
| `<tip>` | docs: document Phase 8.2 business-profile contract slice |

**Part A — five hardening fixes (all in `74ecc98`, `InteractionBoundary` +
`DiscoverySourcePolicy` + `MarketPolicy`):**
1. Mandatory approval classes (POTENTIAL_BUSINESS_SIDE_EFFECT / EXTERNAL_COMMUNICATION /
   FINANCIAL) can never vanish from both approval-required and blocked — deterministically
   restored to approval-required unless blocked.
2. Permitting `REVERSIBLE_SESSION_WRITE` forces `cleanup_required=True`.
3. `public_access_only` wins → `authenticated_access_allowed` forced False.
4. `DiscoverySourcePolicy.provider_resolution_status` rejects unknown values with
   `ValueError` (no silent rewrite; never an available/verified runtime state).
5. Side-effect flags (authenticated access, real submission, account/order/booking/hold,
   payment, file upload) require a non-empty `written_authorization_ref` (else `ValueError`)
   and keep the matching action class approval-required; evasion switches stay off
   regardless of authorization. Also: dedup of action-class lists; `"none"` cannot coexist
   with a real outreach channel in `MarketPolicy`.

**Part B — slice 2 (all in `db772fb`, planning/contracts only):**
- `core/schemas/prospect_business.py` — `BusinessContext`, `SiteProfile`,
  `BusinessFlowProfile`.
- `core/schemas/prospect_coverage.py` — `CoverageArea`, `CoverageMap`, `SiteFingerprint`.
- `tests/test_phase82_business_profiles.py` (43 tests).

**Slice-2 reuse (verified):** `SchemaMixin`; `Confidence` values from `finding.py`
(string-typed, not a new enum); `SourceReference` provenance; `InteractionActionClass` for
planned flow risk; `ATOMIC_CAPABILITIES` for capability refs; opaque-string fingerprints
(no in-schema hashing/crawling). `CoverageMap` was implemented as a thin new projection
(not an extension of `scenario_execution_matrix`) to keep QA coverage and commercial
opportunity decoupled — recorded in `REUSE_MAP_PHASE8.md`.

**Slice-2 fail-closed invariants:** explicit `unknown` defaults; bounded confidence;
`COVERED`/`PARTIAL` require an evidence/verification reference; blocked/partial never
treated as complete; public vs authenticated surfaces kept separate; fingerprint inputs
reject secret/session/volatile terms and are deterministic (sorted, de-duplicated);
unknown enums/statuses fail closed; existing schemas unchanged.

**Deferred (still planned Phase 8.2):** contact/identity, findings/disclosure,
scoring/lifecycle, synthetic data, retention/suppression/storage-class, dashboard.

### Validation (Part A + Part B)

| Gate | Result |
|---|---|
| Targeted prospect contract tests (`test_phase82_prospect_contracts.py` + `test_phase82_business_profiles.py`) | **103 passed** (60 + 43) |
| Full suite `pytest tests/ -q` | **3747 passed, 4 warnings** |
| `ruff check .` | All checks passed |
| `tools/docs_audit.py` | [PASS] |
| `tools/agent_readiness_audit.py` | [PASS] |
| `git diff --check` | clean |

Test total progression: 3679 (slice 1) → 3704 (+25 hardening) → 3747 (+43 slice 2). The 4
warnings are the same pre-existing `PytestCollectionWarning`s (unrelated).

### Unresolved questions for Claude Code

- Confirm `CoverageMap` as a thin new schema (not extending `scenario_execution_matrix`)
  is the desired decoupling.
- Confirm the `str`-typed `Confidence`/vocabulary approach (frozenset of enum values) is
  acceptable vs. storing the `Confidence` enum directly.
- Confirm the fail-closed *normalization* choice for `InteractionBoundary` (auto-restore /
  auto-correct) vs. strict rejection is the preferred contract style.

---

### Original active state (slice 1, retained)

- **Repository:** `dmytropogribnyy/ai-qa-factory`
- **Active branch:** `phase/8.2-prospect-core-contracts` (implementation)
- **Active branch HEAD:** the tip of `phase/8.2-prospect-core-contracts` — the
  `docs: document Phase 8.2 prospect contract slice` commit (run `git log --oneline -4`).
- **Base documentation branch:** `phase/8.2-prospect-radar-contracts` @
  `6a25288` (`docs: add cross-agent handoff and Phase 8.2 reuse analysis`), pushed.
- **origin/main:** `d467eba74f478a968415abfa5da39dd43812f973` (unchanged).
- **Merge state:** neither branch merged.

### Commits created this session (newest last)

| Branch | Commit | Subject |
|---|---|---|
| `phase/8.2-prospect-radar-contracts` | `6a25288` | docs: add cross-agent handoff and Phase 8.2 reuse analysis |
| `phase/8.2-prospect-core-contracts` | `bcc1b85` | feat: add Phase 8.2 prospect planning contracts |
| `phase/8.2-prospect-core-contracts` | tip | docs: document Phase 8.2 prospect contract slice |

The implementation branch is built on the reviewed documentation branch so Claude Code
can review the commit chain in order
(`d467eba → f13b4f7 → b047ea8 → 6a25288 → bcc1b85 → docs-slice tip`).

### Contracts implemented (slice 1 — planning/contracts only)

- `core/schemas/prospect_interaction.py` — `InteractionActionClass` (`str, Enum`:
  READ_ONLY, REVERSIBLE_SESSION_WRITE, POTENTIAL_BUSINESS_SIDE_EFFECT,
  EXTERNAL_COMMUNICATION, FINANCIAL, DESTRUCTIVE) and fail-closed `InteractionBoundary`.
- `core/schemas/prospect_campaign.py` — `ProspectCampaign`, `CampaignTargetCriteria`,
  `MarketPolicy`, `DiscoverySourcePolicy`.
- `capabilities/profiles/prospect_qa_radar.yaml` — planning-only capability profile
  (9th profile); `CAPABILITY_PROFILES` gains `prospect_qa_radar`.
- `tests/test_phase82_prospect_contracts.py` (35 tests) + updated
  `tests/test_phase8_manifests.py` / `tests/test_phase8_schemas.py` for the new profile.

### Reuse decisions actually taken

- **Reused as-is:** `SchemaMixin` (additive-safe serialization); `SourceReference`
  (campaign origin/owner — no new provenance model).
- **Reused as pattern:** `WorkRunState` (uuid id / UTC ISO timestamps / explicit
  `schema_version`, without reusing client-work states); `ToolExecutionPolicy` /
  `IntegrationPolicy` (conservative `read_only`/approval policy shape);
  `config/mcp_servers.yaml` reference-only manifest (a discovery source is a planning
  candidate, never verified runtime); documented `APPROVAL_MODEL.md` action classes,
  typed as `InteractionActionClass`.
- **New thin domain models:** the five schemas above (justified — no precursor covers a
  campaign header, target criteria, market/discovery policy, or interaction boundary).
- New schemas are imported directly from their modules (Phase 8 convention; **not**
  re-exported in `core/schemas/__init__.py`).

### Contracts deliberately deferred (still planned)

Contact/identity, findings/disclosure, scoring/lifecycle, synthetic data, site memory
(recheck/fingerprint/retention/suppression/storage class), coverage map, and dashboard —
see `docs/handoffs/PHASE_8_2_REUSE_ANALYSIS.md`.

### Fail-closed invariants enforced + tested

- destructive always blocked; financial + external communication approval-gated; approval
  classes cannot be listed as permitted; only READ_ONLY permitted by default;
- CAPTCHA-bypass, access-control evasion, proxy/stealth evasion cannot be enabled through
  `InteractionBoundary` (setters forced off in `__post_init__` and on rehydration);
- real submission / account / order / booking / payment / file-upload blocked by default;
- market policy never auto-approves outreach; `respect_robots` cannot be disabled;
- discovery sources are read-only planning candidates (never "available" runtime);
- exploration budget bounded 0–100 %; campaign limits non-negative; unknown enum values
  fail validation rather than silently becoming permissive;
- serialization round-trips stable (including after fail-closed correction); unknown keys
  ignored (backwards compatible).

### Validation (this implementation session)

| Gate | Command | Result |
|---|---|---|
| Targeted contract tests | `pytest tests/test_phase82_prospect_contracts.py -q` | **35 passed** |
| Profile/schema tests | `pytest tests/test_phase8_manifests.py tests/test_phase8_schemas.py -q` | pass |
| Full suite | `pytest tests/ -q` | **3679 passed, 4 warnings** |
| Lint | `ruff check .` | All checks passed |
| Docs audit | `tools/docs_audit.py` | [PASS] |
| Agent readiness | `tools/agent_readiness_audit.py` | [PASS] |
| Whitespace | `git diff --check` | clean |

Warnings: the same 4 pre-existing `PytestCollectionWarning`s (dataclasses named `Test*`);
unrelated to this work. Full total moved 3643 → 3679 (+36: 35 contract tests + 1 profile
test).

### Known risks / review questions for Claude Code

- `DiscoverySourcePolicy` vs. later contact/provider policies — confirm no overlap when the
  contact slice lands.
- `InteractionActionClass` (str-enum) vs. the frozenset `CAPABILITY_CLASSES` — intentionally
  a distinct, documented vocabulary aligned to `APPROVAL_MODEL.md`; confirm this is the
  desired shape before more prospect schemas depend on it.
- Adding `prospect_qa_radar` touched the pinned profile-set assertions in two Phase 8
  tests; verify those edits are acceptable and not masking drift.
- **Large diff on three handoff/instruction files is expected:** `docs/handoffs/CURRENT.md`,
  `docs/handoffs/PHASE_8_2_REUSE_ANALYSIS.md`, and `.github/copilot-instructions.md` were
  created CRLF in the first session and normalized to LF here (repo convention is LF).
  Relative to `6a25288` they appear fully rewritten, but the only substantive content
  change is in `CURRENT.md`; the other two changed line endings only.

---

## Repository State (original reviewer-session record, retained)

- **Repository:** `dmytropogribnyy/ai-qa-factory`
- **Branch:** `phase/8.2-prospect-radar-contracts`
- **HEAD:** `b047ea8cd53fe9ef6ac71ef2305390fe96790ab7`
  (`fix: audit nested architecture documentation`)
- **origin/main:** `d467eba74f478a968415abfa5da39dd43812f973`
  (`merge: complete Phase 8.1 planning workflow`)
- **Ahead / behind:** 2 commits ahead of `origin/main`, 0 behind.
- **Push state:** branch is pushed (`origin/phase/8.2-prospect-radar-contracts` at HEAD).
- **Merge state:** not merged into main.
- **Working tree (before this session's additions):** clean.
- **Working tree (after this session):** clean except the 3 new uncommitted handoff/
  instruction files listed below. No reviewed commit was modified.

**Branch commits (newest first):**

| Commit | Subject |
|---|---|
| `b047ea8` | fix: audit nested architecture documentation |
| `f13b4f7` | docs: integrate Prospect QA Radar into Phase 8 roadmap |

Base `d467eba` (Phase 8.1 merge) is the branch point. Everything above matches the
expected state described in the takeover prompt — verified via Git, not assumed.

---

## Completed (verified on this branch)

- **Phase 8.1 merge** (`d467eba`, on main): deterministic planning-only `main.py work`
  workflow. `CapabilityRegistry` and `CapabilityPlanner` already exist as of Phase 8.1
  (confirmed: `core/orchestration/capability_registry.py`,
  `core/orchestration/capability_planner.py`).
- **Phase 8.2 documentation integration** (`f13b4f7`): Prospect QA Radar integrated into
  the Phase 8 roadmap across `AGENTS.md`, `CLAUDE.md`, `README.md`,
  `docs/PRODUCT_VISION_2026.md`, `docs/PHASE_CONTRACTS.md`, `docs/UNIVERSAL_WORK_FACTORY.md`,
  `docs/REUSE_MAP_PHASE8.md`, `docs/APPROVAL_MODEL.md`, `docs/SAFETY_RULES.md`,
  `docs/ARTIFACT_CONTRACTS.md`, `docs/DOCUMENTATION_GOVERNANCE.md`, `docs/DOCS_MANIFEST.md`;
  full spec added at `docs/architecture/PROSPECT_QA_RADAR_SPEC.md` (2145 lines) with a
  status block marking it approved, future-facing, not implemented.
- **Recursive docs-audit work** (`b047ea8`): `tools/docs_audit.py` now scans `docs/`
  recursively (`rglob`) so nested architecture specs are covered; `docs/archive/` keeps
  its intentional exemption from the runtime-overclaim scan; `docs/architecture/README.md`
  index added; both new nested docs registered as required docs; 8 new tests in
  `tests/test_docs_audit_recursive.py`.
- **Prospect Radar specification location:**
  `docs/architecture/PROSPECT_QA_RADAR_SPEC.md` (single canonical copy).
- **Explicit absence of runtime/schema implementation:** the diff contains only
  documentation, the docs-audit tool, and docs-audit tests. **No runtime module and no
  domain schema were added.** Verified via `git diff --stat origin/main...HEAD`.

---

## Independent Review

**Reviewed:** the full diff `origin/main...HEAD` — 16 files, +2515 / −24. Files:
`AGENTS.md`, `CLAUDE.md`, `README.md`, `docs/APPROVAL_MODEL.md`,
`docs/ARTIFACT_CONTRACTS.md`, `docs/DOCS_MANIFEST.md`, `docs/DOCUMENTATION_GOVERNANCE.md`,
`docs/PHASE_CONTRACTS.md`, `docs/PRODUCT_VISION_2026.md`, `docs/REUSE_MAP_PHASE8.md`,
`docs/SAFETY_RULES.md`, `docs/UNIVERSAL_WORK_FACTORY.md`,
`docs/architecture/PROSPECT_QA_RADAR_SPEC.md`, `docs/architecture/README.md`,
`tests/test_docs_audit_recursive.py`, `tools/docs_audit.py`.

**Findings:**

- Only documentation, the docs-audit tool, and docs-audit tests changed. **Confirmed —
  no runtime or schema implementation introduced.**
- Phase 8.0 and 8.1 consistently marked **complete**; Phase 8.2 consistently marked
  **planned / contracts-only** across all touched docs.
- `CapabilityRegistry` / `CapabilityPlanner` are consistently described as **already
  existing** (Phase 8.1), not new to Phase 8.2. Confirmed against actual modules.
- Prospect Radar is described as **approved future-facing architecture, not implemented**
  everywhere it appears; the spec's own status block states runtime is not implemented.
- No competing/second roadmap introduced — the single phase map lives in
  `docs/PRODUCT_VISION_2026.md`; the spec defers implementation status to
  `docs/PHASE_CONTRACTS.md`.
- Reuse-first is preserved: planned Prospect artifacts are explicitly marked as needing a
  reuse review before any schema is finalized; no duplicate schema commitment contradicts
  the reuse map.
- `docs/archive/` remains intentionally excluded from the runtime-overclaim scan;
  verified no duplicate Prospect spec exists under `docs/archive/`.
- Nested docs are correctly included by the audit (both new files are required docs and
  registered in `DOCS_MANIFEST.md`).
- Tests are meaningful (nested-scan positive/negative, archive exemption, qualified-claim
  exemption, required-doc-missing detection, real-spec presence) and avoid brittle
  line-count coupling (they assert size `> 1000` bytes, not exact length).
- Test-count references verified: 3635 baseline (Phase 8.1) + 8 new docs-audit tests =
  3643 full suite (see Validation).
- No secrets or generated `outputs/` committed; `git diff --check` clean.

**Defects / inconsistencies:** none found.

**Branch readiness:** the branch **appears ready for human / Claude Code review and
merge**. This is an independent review recommendation only — **it is not merged and must
not be merged by an agent without explicit human authorization.**

**Unresolved questions:**

- The exact `40_ark_work/` → Prospect artifact namespace ownership is deferred to Phase
  8.2 contract work (documented as planned names only). No action needed now.

---

## Validation (exact results, this session)

| Gate | Command | Result |
|---|---|---|
| Targeted docs-audit tests | `pytest tests/test_docs_audit_recursive.py -q` | **8 passed** in 0.27s |
| Full test suite | `pytest tests/ -q` | **3643 passed, 4 warnings** in 73.70s |
| Lint | `ruff check .` | **All checks passed!** |
| Docs audit | `tools/docs_audit.py` | **[PASS]** |
| Agent readiness | `tools/agent_readiness_audit.py` | **[PASS]** |
| Whitespace | `git diff --check` | clean |

**Warnings:** the 4 pytest warnings are pre-existing `PytestCollectionWarning`s
(dataclasses named `Test*` in `core/schemas/credential_safety.py` and
`core/schemas/runtime_secret_routing.py` that pytest cannot collect). They are unrelated
to this branch and are not errors.

Environment: Windows, `.venv/Scripts/python.exe`.

---

## Current Scope Boundary

**Phase 8.2 is contracts / schema / planning / governance only.**

Explicitly blocked (per `docs/PHASE_CONTRACTS.md` and `docs/SAFETY_RULES.md`):

- live discovery or crawling;
- browser / Playwright execution;
- MCP discovery / invocation / server spawning;
- network / provider runtime;
- contact lookup runtime;
- email / outreach sending;
- dashboard background workers;
- CAPTCHA solving / bypass;
- stealth or proxy / fingerprint / rate-limit evasion;
- real form submission;
- account / order / booking / slot-hold / payment / file upload;
- authenticated / private access;
- autonomous remediation or deployment.

---

## Files Created During This Copilot Session

Reviewer + handoff (committed as `6a25288` on the documentation branch):

- `.github/copilot-instructions.md`
- `docs/handoffs/CURRENT.md` (this file)
- `docs/handoffs/PHASE_8_2_REUSE_ANALYSIS.md`

Implementation slice 1 (on `phase/8.2-prospect-core-contracts`):

- `core/schemas/prospect_interaction.py` (new)
- `core/schemas/prospect_campaign.py` (new)
- `capabilities/profiles/prospect_qa_radar.yaml` (new)
- `tests/test_phase82_prospect_contracts.py` (new)
- edited: `core/schemas/capability.py`, `tests/test_phase8_manifests.py`,
  `tests/test_phase8_schemas.py`, `README.md`, `docs/SCHEMA_FOUNDATION.md`,
  `docs/PHASE_CONTRACTS.md`, `docs/REUSE_MAP_PHASE8.md`, `docs/DOCS_MANIFEST.md`.

No reviewed commit was amended, squashed, or rebased. No branch was merged.

---

## Continued Copilot Session — Authorization Update (2026-07-17)

The human explicitly extended this Copilot session and authorized productive work for
~2–3 hours, then a clean checkpoint for Claude Code. This supersedes the original
"leave everything uncommitted" stop instruction for **this** session only.

**Now allowed by the user (this session):**

- commit the three handoff/instruction files (this file, the Copilot instructions, and
  the reuse analysis);
- push the documentation branch `phase/8.2-prospect-radar-contracts`;
- create and push a new Phase 8.2 implementation branch
  `phase/8.2-prospect-core-contracts`;
- implement the approved **first contracts-only slice** (campaign definition, target
  criteria, market/discovery policy, interaction boundary + action classes),
  schema/planning only.

**Still prohibited (this session):**

- merge any branch;
- force-push;
- amend, squash, or rebase reviewed commits;
- runtime implementation outside the Phase 8.2 contracts boundary (no discovery,
  crawling, browser/Playwright, MCP invocation, provider install, outreach, dashboard
  workers, persistent DB runtime, new CLI command);
- external communication;
- CAPTCHA solving/bypass;
- proxy / stealth / rate-limit / access-control evasion;
- destructive actions;
- updating project memory.

---

## Exact Next Safe Step

The Copilot implementation session is complete (docs branch pushed; implementation branch
`phase/8.2-prospect-core-contracts` pushed; nothing merged). **Claude Code is next.**

Claude Code must:

1. **Verify Git state** — branch, HEAD, base doc-branch commit `6a25288`, `origin/main`
   `d467eba`; confirm the commit chain and that neither branch is merged.
2. **Independently review the implementation diff** (`6a25288..HEAD` on
   `phase/8.2-prospect-core-contracts`) — schema/contracts only, no runtime/network/
   browser/MCP.
3. **Challenge duplicate-schema decisions** — confirm the five new schemas genuinely lack
   precursors and that `SourceReference` / `WorkRunState` / `ToolExecutionPolicy` reuse is
   correct (not a missed reuse).
4. **Inspect fail-closed defaults** — re-check `InteractionBoundary` invariants (CAPTCHA/
   evasion off; destructive blocked; approval classes not permitted; outreach not
   auto-approved; discovery read-only).
5. **Rerun focused tests** — `pytest tests/test_phase82_prospect_contracts.py
   tests/test_phase8_manifests.py tests/test_phase8_schemas.py -q` plus the full gate.
6. **Withhold merge if any concern remains.** Only merge after explicit human authorization.

Do not create every candidate schema at once. Do not start runtime. Slices 1 (campaign
definition), 1-hardening, 2 (business/site profiles), 2-hardening, 3 (identity/lifecycle/
governance), and 4 (scoring foundation) are complete. The next contracts-only slice (if
approved) is the **contact group** (`ContactRecord`, `ContactProvenance`, `ContactStatus`)
plus `StorageClass` and disclosure (`FindingDisclosurePolicy`, `DisclosureManifest`) — the
most PII-sensitive area, still contract-only — per `docs/handoffs/PHASE_8_2_REUSE_ANALYSIS.md`.
No contact lookup, outreach, dashboard, or execution runtime.

---

## Prohibited Actions (still in force this session)

- no merge;
- no force-push;
- no amend / squash / rebase of reviewed commits;
- no runtime implementation outside the Phase 8.2 contracts boundary;
- no external communication;
- no browser / network / MCP execution;
- no CAPTCHA solving / bypass;
- no proxy / stealth / access-control evasion;
- no destructive actions;
- no project-memory updates;
- no hidden cleanup of failures.
