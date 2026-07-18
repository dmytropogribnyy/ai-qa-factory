# Scout Operator Guide

Scout finds public websites/apps, runs safe read-only QA, verifies findings, collects evidence,
locates publicly published business contacts with provenance, and shows results in the local
dashboard. No terminal, JSON, or database commands are needed for daily use.

## Start

```powershell
scripts\start-local.ps1        # http://127.0.0.1:8765 (idle home; nothing scanned yet)
```

## Create + run a campaign

**From the dashboard (guarded Start panel).** On the idle home page, the **Start a bounded read-only
campaign** panel takes 1–10 **public https** seed URLs, a campaign name, and max pages/site, plus an
explicit confirmation checkbox. It starts only the existing bounded, read-only Scout engine — it
never sends email, submits forms, solves CAPTCHAs, or runs commands. The endpoint is fenced by four
independent guards: it binds to loopback only, the `Host` header must be loopback (blocks
DNS-rebinding), a cross-origin `Origin` is refused, and a per-page CSRF token is required. Non-public
/ private / loopback targets are rejected before anything runs, one campaign runs at a time, and the
campaign intent is persisted before execution (so a restart leaves an honest record).

Then watch: status, sites discovered/triaged/checked, verified findings, contacts found, the current
safe operation, and errors. Controls: **Pause / Resume / Stop Safely** (graceful) **/ Cancel** (global
kill). State survives a restart.

**From the CLI.** Richer discovery-based campaigns (countries/languages/industries, providers,
budgets, a11y rules, retention, dedup) run through `python main.py scout campaign-run ...`; attach the
dashboard to a run with `python main.py scout dashboard --run-id <id>`.

## Review results

Company cards show name, domain, country, industry, discovery source, commercial score, verified
findings, top impact, contact availability, evidence freshness, and review state. Filter (verified
only / high impact / public email / not contacted / evidence current / no suppression / ...) and
sort (recommended first / impact / freshness / contact / date). Open a company for the summary,
findings (with reproduction + evidence), evidence (screenshot/trace/logs/a11y/perf), and the contact
with **provenance** (source URL, publication evidence, freshness, organization/named-person, terms,
suppression).

## Contacting a prospect (manual-first)

The preferred flow keeps you in control:

1. Review the evidence and the prepared **draft** (editable).
2. **Open in Gmail** (or Copy Email / Copy Subject / Copy Draft).
3. In Gmail, personally click **Send**.
4. **Mark as Contacted.**

Manual sending needs **no Gmail OAuth setup**. The Gmail API path is an optional, one-at-a-time
advanced action (see [GMAIL_PROVIDER_SETUP.md](GMAIL_PROVIDER_SETUP.md)). There is no bulk send,
send-all, automatic campaign sending, automatic follow-up, or inbox sync.

## Safety

Public pages only, bounded rate, normal browser behavior. No payment, no impactful form submission,
no account creation, no CAPTCHA/login/paywall/access-control bypass, no stealth/proxy/rate-limit
evasion, no private-API exploitation, no re-checking after an explicit prohibition, and no security
finding placed into ordinary sales outreach.
