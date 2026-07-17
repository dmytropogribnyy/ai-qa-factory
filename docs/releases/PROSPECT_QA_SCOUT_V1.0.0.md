# AI QA Factory / ARK Prospect QA Scout v1.0 — local release

**Release:** `scout-v1.0.0` · **Date:** 2026-07-17 · **Phase:** 8.3

An honest **local** release. This is **not** cloud, SaaS, unrestricted discovery, automated
outreach, or a production deployment.

## What it is

A genuinely runnable, bounded, **read-only** local QA vertical over 1–10 explicit public seed
URLs. Package: `core/scout/`. Entrypoint: `python main.py scout ...`.

```
python main.py scout demo     # deterministic bundled demo (no external network, no browser)
python main.py scout run --seeds "https://a.example/,https://b.example/"
python main.py scout dashboard --run-id <run_id>   # http://127.0.0.1:8765
python main.py scout control --signal kill --port 8765
```

## Implemented capabilities

- Campaign + 1–10 seed runtime with fail-closed URL eligibility (rejects credentials-in-URL,
  localhost, loopback/private/link-local/reserved/multicast/unspecified IPs, unsafe schemes/
  ports, malformed hosts, and DNS-rebinding to internal addresses).
- Bounded public profiling and read-only checks: broken links, accessibility, technical SEO,
  structured data, mobile viewport, bounded performance, pre-submit form validation, one public
  business flow explored up to (never through) a side effect, and console/failed-resource
  observation (browser backend).
- Independent second-pass verification (`UNVERIFIED → REPRODUCED → EVIDENCE_CAPTURED → SANITIZED
  → VERIFIED`); transient findings rejected; only reproduced + sanitized findings are client-safe.
- Sanitized evidence (no response body, cookies, tokens, or credentials); non-authorizing
  scoring (a Phase 8.2 `LeadScorecard`; `outreach_eligible` always False).
- Durable atomic, path-confined persistence with resume; corruption fails closed.
- Localhost dashboard (`127.0.0.1` only) with health, overview/prospect/findings views, live
  events, path-confined artifact serving, and start/pause/resume/cancel/**global-kill** controls.
- Report export (campaign summary, shortlist, verified findings, coverage & limitations,
  scorecard summary, evidence index, machine-readable JSON) published atomically after a content
  secret scan.
- Pluggable backend: stdlib `StaticHttpBackend` (offline-safe; drives the deterministic E2E) and
  an optional lazy `PlaywrightBackend` (live browser; `pip install playwright`; never required by
  tests).

## Deferred (not in v1.0)

Broad/undirected discovery; contact discovery/enrichment; outreach sending; authenticated flows;
`REVERSIBLE_SESSION_WRITE` execution; cloud/dashboard background workers; deployment. CAPTCHA and
access-prohibited pages are surfaced as `MANUAL_ACTION_REQUIRED` (never interacted with or bypassed).

## Validation

- Full suite: 4090 passed, 4 pre-existing warnings, 0 failed. Phase 8.3: 74 tests.
- ruff clean; docs audit `[PASS]`; agent readiness `[PASS]`; `git diff --check` clean.
- Deterministic fixture E2E green (`python main.py scout demo`): clean control yields no defects;
  CAPTCHA/access → manual-action; the report is sanitized (no cookie/secret leak) and references
  only approved artifacts.

## Safety confirmation

No outreach, form submission, account creation, booking, order, payment, CAPTCHA solving,
access-control/proxy/stealth evasion, or any other external side effect occurs.
