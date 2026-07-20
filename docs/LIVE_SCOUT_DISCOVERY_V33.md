# Live Scout Discovery (v3.3) — Tavily seedless discovery

**Status: LIVE VERIFIED** (justified by a real bounded observe-only acceptance, below). The smallest
complete increment that makes Scout discover company domains from campaign filters **without any
manually supplied seed URL**, using ONE real provider (Tavily) through the existing
`DiscoveryProvider` protocol, campaign matrix, suppression/dedup/scoring/budgets, and Scout CLI +
Dashboard. It reuses — never replaces — the existing Scout architecture.

## Components

| Piece | File |
|---|---|
| Real provider (Tavily Search API) | `core/scout/discovery/tavily_provider.py` |
| Domain intelligence (canonical domain + company/aggregator classification) | `core/scout/discovery/domain_intel.py` |
| Global cross-campaign analyzed-site registry | `core/scout/discovery/analyzed_registry.py` |
| Secret handling (outside-repo, env-var-name referenced) | `core/scout/discovery/tavily_secret.py` |
| Hidden interactive key setup | `tools/tavily_setup.py` |
| Wiring (registry build + reconciliation) | `core/scout/discovery/live_registry.py`, `core/scout/discovery/cli.py` |

## Safety model (observe-only)

Public pages only; GET-style search via the Tavily API; **no login, account creation, form
submission, CAPTCHA bypass, vulnerability scanning, fuzzing, or state-changing request**; no contact
with any company; **no email**; the external-send/outreach kill switch stays disabled. Pre-authorization
observations are **"Passive public-surface QA signals"**, never confirmed vulnerabilities. Discovery is
fully separate from outbound email (`core/scout/discovery` vs `core/scout/comms`).

## Secret handling

`TAVILY_API_KEY` is read from the environment variable or the outside-repo secret file
(`%USERPROFILE%\.aiqa\secrets\tavily.key`), referenced by **name** only. It is never printed, logged,
committed, serialized, returned by any readiness/status surface, or placed on a command line. Setup:

```
python tools/tavily_setup.py            # hidden prompt, stores outside repo, validates, no echo
python tools/tavily_setup.py --status   # presence + git-safety only
```

## Fail-closed behavior

Discovery fails closed (never a fixture fallback) when: the key is absent; authentication fails (401);
live approval is missing (`--approve-live-discovery`); request/result/credit budgets are exhausted; or
a response is malformed. Transient failures and HTTP 429 use a bounded timeout + retry/backoff.

## Cross-campaign analyzed-site registry

One persistent canonical registry (`outputs/scout/_registry/analyzed_sites.json`) keyed by the
canonical domain (public-suffix + shared-hosting aware, so US/DE/keyword/campaign/restart duplicates
collapse to one company and unrelated shared-hosting tenants are never merged). Completed targets are
**skipped by default ("Already analyzed")** and their existing result is shown; failed/interrupted
targets may retry; concurrent campaigns cannot analyze the same target at once (atomic O_EXCL lease
lock); rescan is explicit (manual / interval / fingerprint) — never merely because the same URL
reappeared in another query.

## Live acceptance evidence (redacted)

One authorized bounded observe-only campaign was run against the real Tavily API. Company domains are
public information; **no API key, credential, or private datum appears here**.

| Field | Value |
|---|---|
| Campaign ID | `v33-live-acceptance` |
| Provider | `tavily` (topic=general, search_depth=basic, include_answer=false) |
| Filter matrix | countries = **United States, Germany**; industry = **B2B SaaS**; 2 cells |
| Provider calls (queries) | **2** |
| Results returned | 9 |
| Unique / duplicates / uncertain | 7 unique / 1 duplicate / 1 uncertain (in-campaign) |
| Global registry unique domains | **8** (≤10 cap enforced) |
| Rejected (directory/social/job-board) | recorded with reasons in the provider rejection log |
| Promoted to Scout QA / held | 5 / 1 |
| Final unique domains | `sellerscommerce.com, encharge.io, appdirect.com, sumatosoft.com, builtin.com, spxcommerce.com, growably.de, cloudblue.com` |
| Budget consumed | provider_calls=2, results=9, cost=$0 |
| Kill switch | external send **disabled** (`PROSPECT_RADAR_EXTERNAL_SEND_DISABLED=1`) |
| Contact | **nobody contacted; no email/form/login/order/payment** |

**Cross-campaign skip proof:** the 8 domains were marked analyzed; a second campaign (`v33-skip-proof`)
with identical filters reconciled to `newly_discovered=0, already_analyzed_skipped=8` — every
previously-analyzed domain was **skipped without re-analysis**.

## Scheduling

Uses the canonical Scout CLI. A thin, **opt-in, disabled-by-default** Windows Task Scheduler wrapper
(`tools/scout_schedule.py`) invokes `main.py scout campaign-run … --campaign-id <id>` by id, with an
overlap guard (no concurrent run of the same campaign), preserved fresh-process resume, and safe
create/status/disable/remove commands. **The API key is never embedded in the scheduled task
command.** "Run discovery now" is the plain CLI.

## Classification

Seedless Scout discovery is now **Live Verified** for the Tavily provider (real API, real bounded
acceptance, real cross-campaign skip). All other providers remain fixture/file/Needs-Operator as
before. Live send/outreach remains disabled and separate.
