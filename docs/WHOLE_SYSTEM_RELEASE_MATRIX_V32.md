# Whole-System Release Matrix — AI QA Factory v3.2

**Final SHA:** `9b047a1` · **Hosted CI:** run
[`29725542723`](https://github.com/dmytropogribnyy/ai-qa-factory/actions/runs/29725542723) on `643ff03`
(the Resource-Readiness commit `9b047a1` is in the follow-up CI referenced from PR #1). Parsed hosted
JUnit: **core 4768 / browser 25 (0 skip) / provider 118 / windows 4768 — 0 failures, 0 errors**;
**28 dashboard screenshots** (desktop dark/light + mobile). Capability-honesty classes:
**Live Verified / Fixture Verified / Needs Client / Needs Operator / Declared** — an externally
dependent capability is never called Live Verified because its code exists.

## 1. Operator Dashboard

| Capability | Implementation | Automated test | CI job | Screenshot | External dep | Class |
|---|---|---|---|---|---|---|
| All primary pages load | `core/scout/dashboard.py`, `core/dashboard/read_model.py` | `test_v3_dashboard_*`, `test_v3_results_view.py` | core + browser | overview/work/tools/activity/settings/docs/results/company/projects/scout | none | **Live Verified** |
| Dark + Light themes | dashboard CSS (theme-aware) | axe checks | browser | `desktop-dark-*`, `desktop-light-*` | none | **Live Verified** |
| Work cards + mobile layout | responsive components | screenshot regression | browser | `mobile-dark-*` (7) | none | **Live Verified** |
| Project/run detail | read-model DTOs | `test_v3_results_view.py` | core | `*-project-summary/plan/results/delivery` | none | **Live Verified** |
| Tools/capability matrix | `service_capability.py`, `tool_broker.py`, `access_bootstrap.py` | `test_v3_tool_broker.py`, `test_v32_access_bootstrap.py` | core | `desktop-dark-tools` | none | **Live Verified** |
| Activity/logs, settings/docs | dashboard routes | dashboard tests | core+browser | `*-activity/settings/docs` | none | **Live Verified** |
| Scout/results/company/projects | shared layout | scout+results tests | core | `*-scout-home/campaigns/results/company/projects` | none | **Live Verified** |
| Actionable background failures, no secret/traceback exposure | redaction + bounded errors | `test_v3_*` redaction, dashboard security tests | core | — | none | **Live Verified** |

## 2. Work engine

| Capability | Implementation | Test | CI | External dep | Class |
|---|---|---|---|---|---|
| intake → planning → approval → trusted execution | `work_execution.py`, `client_work.py`, `execution_trust.py` | `test_v32_execution_trust.py` (15), `test_v3_genuine_execution_*` | core | none | **Live Verified** |
| client-code trust boundary (control-store authority) | `execution_trust.py` (control store outside work dir) | `test_v32_execution_trust.py` | core | none | **Live Verified** |
| private work dir preflight | `preflight_work_isolation` (git-ignored, fail-closed) | `test_v32_execution_trust.py` | core | none | **Live Verified** |
| execute + validate, repair/resume, review, prepared delivery, integrity re-hash, fresh-process resume | `work_execution.py` lifecycle + manifest hashing | `test_v3_genuine_execution_{ab,cd}.py`, `test_v32_integrated_playwright_lifecycle.py` | core+browser | none | **Live Verified** |
| concurrency/idempotency, blocked/error recovery | state manager + capability gate | `test_v32_execution_trust.py`, worker tests | core | none | **Live Verified** |

## 3. Real-runtime acceptance

| Capability | Test | CI | Evidence | Class |
|---|---|---|---|---|
| integrated multi-file TS/Playwright lifecycle, real `playwright test`, fail→repair→pass | `test_v32_integrated_playwright_lifecycle.py` | browser | JUnit browser 25 tests, **0 skip**; lifecycle test present | **Live Verified** |
| browser acceptance zero-skip | pytest `playwright_acceptance` | browser | `skipped="0"` in junit-browser.xml | **Live Verified** |
| hosted Windows smoke | full suite on windows-latest | windows | 4768/0/0 | **Live Verified** |
| provider contract | provider-contract suite | provider | 118/0/0 | **Live Verified** |

## 4. Scout

| Capability | Implementation | Test | Class |
|---|---|---|---|
| discovery/ingestion, dedup/rescan, filters/prioritization | `core/scout/discovery/*`, `pipeline/*` | `test_phase84_discovery_*`, `test_final1_*` | **Fixture Verified** (live discovery = **Needs Operator**: a configured trusted provider) |
| authorization/policy boundary | `discovery/suppression.py`, disclosure | discovery-safety tests | **Live Verified** |
| evidence + status in Dashboard | read-model + Scout UI | results/scout tests | **Live Verified** |
| Scout sender identity `dipptrue@gmail.com` (gmail.send) | `comms/gmail.py`, `gmail_oauth.py` | `test_final2_*`, live authorize | **Live Verified** (send authorized; live self-test send accepted) |
| QA test-inbox identity `drdiplextech@gmail.com` (gmail.readonly) | `comms/test_inbox.py` | `test_v32_test_inbox.py` (26) | **Live Verified** (read authorized; correlated read succeeded) |
| external outreach disabled by default | kill switch + `outreach-control` | `test_final1_outreach.py` | **Live Verified** |
| exactly one authorized self-test; no prospect contacted | `selftest_guard.py` | `test_v32_selftest_guard.py` | **Live Verified** (one send, idempotency guard) |

## 5. Observability & security

| Capability | Implementation | Test | Class |
|---|---|---|---|
| bounded/redacted logs, background exceptions visible, no silent failures | `content_safety.py`, dashboard error surfacing | redaction + dashboard tests | **Live Verified** |
| CSRF/Origin/CSP/loopback/path confinement | dashboard shared guard | dashboard security tests | **Live Verified** |
| secret scanning; no credentials in repo/artifacts/HTTP/screenshots/delivery | GitHub secret-scanning (0 alerts), gitignore, redaction | history scan + delivery-scan tests | **Live Verified** |

## 6. External dependencies (per-engagement / owner — not Factory defects)

| Item | Class | Action owner |
|---|---|---|
| Gmail OAuth durability (Testing → Production) | **Needs Operator** (owner-only) | operator — see `OAUTH_DURABILITY_AND_CREDENTIALS.md` |
| Client repo / staging URL / test account / read-only DB | **Needs Client** | client — surfaced by the Resource Readiness Checklist |
| Non-GitHub CI (Azure/GitLab/Jenkins), Postman/BrowserStack/Sentry/Stripe/Supabase | **Needs Client / Needs Operator** | per engagement |
| Live prospect discovery provider | **Needs Operator** | operator (trusted provider config) |

## 7. Conclusion

Every base-platform subsystem is **implemented + automated-tested + green in hosted CI**, with dashboard
**screenshot** evidence and honest capability classes. Externally dependent capabilities are classed
**Needs Client / Needs Operator**, never falsely Live Verified. The only owner-only blockers to a fully
durable production posture are **Gmail OAuth publication** and **PAT rotation verification** (both
documented). No base-platform regression remains for v3.2.
