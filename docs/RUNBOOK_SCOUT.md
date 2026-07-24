# AI QA Factory / Scout — Operator Runbook (daily local use)

Bounded, **read-only** prospect QA over public sites. It never submits forms, logs in, sends outreach,
solves CAPTCHAs, or performs any external side effect.

## 1. Start (one command)

```
.venv/Scripts/python.exe main.py dashboard
```

Then open **http://127.0.0.1:8765** (loopback only); stop with Ctrl+C. Missing *optional* keys (e.g. a
discovery provider) are reported by `main.py system-health`, not fatal — the Dashboard still starts. What
is Production / Optional / Experimental / Parked in this build is in `docs/CAPABILITY_STATUS.md` (the
experimental autonomous writer is **off** — it is not on `main`). The durable supervisor (Windows Scheduled Task
`AIQA-Collab-Supervisor`) also keeps one Dashboard alive across restarts — if it is installed you can just
open the URL. Readiness check any time:

```
.venv/Scripts/python.exe main.py system-health
```

## 2. Run your first analysis

**Recommended — discovery campaign (Dashboard):** open **Scout → Discover Prospects** (`/scout/new`):
1. Pick a **size**: Quick (≈2 actionable), Standard (≈5), Extended (≈10).
2. Set **filters**: country, industry, business type, keywords.
3. Confirm and start. The run is bounded and finite; large/obviously-unsuitable companies are excluded,
   candidates are **pre-listed**, and already-seen sites are **de-duplicated** across runs.

Discovery uses the Tavily provider (already configured; to (re)configure: `python tools/tavily_setup.py`).

**Alternative — analyze specific public URLs (CLI)** — one line (PowerShell/cmd have no `\`
continuation):
```
.venv/Scripts/python.exe main.py scout run --seeds "https://example-a.com,https://example-b.com" --browser playwright --max-sites 2 --max-pages 2 --campaign my-scan
```
(Seed CLI runs write a full report under `outputs/scout/<run-id>/report/`. Discovery campaigns are the
path that surfaces per-target findings in the Dashboard — see §3.)

**Deterministic offline demo** (no network, proves the pipeline): `main.py scout demo`.

## 3. Where to see results

- **Scout → History** (`/scout/history`): processed sites, filterable by status/period. The default
  view hides archived results; use the **Archived** tab to restore them.
- **Scout → Needs attention** (`/scout/attention`): targets whose automated browser was stopped by
  CAPTCHA, Cloudflare, an access check, or a similar manual gate.
- **Scout → Campaigns** (`/scout/campaigns`): campaign progress + counters. Archived runs move out
  of the Current view and remain recoverable from the **Archived** tab.
- **Target card** (click a domain): an outcome-first summary, findings, evidence, and coverage for
  the exact selected run. Internal IDs, raw JSON, hashes, policy ceilings, and low-level diagnostics
  stay collapsed under **Advanced diagnostics**.
- Findings include **severity**, **confidence**, a **one-line repro hint**, and category; findings
  are ordered by expected commercial value. **Screenshots/evidence** are attached and viewable from
  the card. Absent confidence/repro show a neutral placeholder (never invented).
- The browser trace shown in the Dashboard is a redacted structured event record. It is not a native
  Playwright `trace.zip`; Playwright Inspector is a live developer tool and is intentionally not part
  of the operator evidence UI.
- After a target reaches **Analysis complete**, select **Download client-ready evidence (.zip)**.
  The exact-target attachment is capped at 20 MiB and contains an offline HTML summary, Markdown,
  client-facing findings, coverage, screenshots, an optional qualifying reproduction video,
  sanitized console/network/accessibility data, a structured event trace when recorded, and a
  SHA-256 manifest. Structured text is secret-scanned. It excludes raw observations/headers,
  cookies, browser storage, absolute paths, run/prospect IDs, and commercial scorecards.
  Screenshots/video still require human review before attaching the ZIP to email; an incomplete
  target cannot be exported as a completed client package.
- With at least one confirmed actionable finding, **Next actions** also shows up to five public
  contact emails found in the captured page metadata/links, with the public source page, and a
  copy-only outreach draft. Same-domain generic mailboxes are preferred. The draft lists only
  confirmed issues and describes implementation conservatively: fixes are offered only for items
  within proven scope, after scope agreement and repo/staging access. With zero findings or an
  incomplete analysis, no outreach draft is offered.
- **Progress/budget** are shown truthfully (discovered / eligible / analyzed / rejected / failed, provider
  calls, cost). Errors and skipped items are reported honestly, not hidden.

## 4. Finish a target blocked by CAPTCHA or Cloudflare

Scout never solves or bypasses a challenge. When a challenge is detected, the target is marked
**Needs your help** and the Dashboard provides:

1. **Open manual check** — starts a visible Chromium session for that exact target.
2. Complete the challenge yourself in the opened browser. The browser stays open for up to 15 minutes.
3. Select **Continue** to re-check the same page in the same in-memory browser context.
4. Select **Defer** to leave it in Needs attention, or **Skip** to end that attempt.

Cookies/session state stay in process memory and are not written into Scout evidence. A successful
manual handoff creates a new exact attempt and preserves the original blocked evidence rather than
rewriting history. If the challenge remains after Continue, the attempt stays incomplete.

## 5. Control or clean up runs

- **Pause / Resume / Stop** from the campaign view (or `main.py scout control --signal pause|resume|cancel`).
  State is honest and cooperative (finishes the current op, starts no new one).
- In **Run results**, select queued targets and use **Skip queued**. The current operation finishes;
  selected targets that have not started are marked skipped before the next operation.
- In **History** or **Run results**, select rows and use **Archive**. Archive hides records from the
  default view without deleting them; use the Archived tab to restore them.
- **Delete heavy evidence** removes screenshots, video, HAR, ZIP, structured browser traces, and
  any derived client-ready ZIP for that run only after confirmation. The short result, findings,
  and cleanup audit record remain.
- **Delete run** is an advanced, confirmed action for a completed run. Active/non-terminal runs are
  refused; stop them safely first. Deleting a run is not the same as **Forget target**: forgetting
  removes the cross-run dedup/history entry so the domain can be discovered again.
- Data and history are **file-based** under `outputs/` and **persist across a Dashboard restart**.

## 6. Safety

Read-only public analysis only. No outreach, no form submission, no login, no CAPTCHA solving, no
automated challenge bypass. Outreach drafts are copy-only and are never sent by the system. Destructive
cleanup is confined to an exact run/evidence path and requires explicit confirmation.

## 7. Known limitations (deferred, non-blocking)

- **Seed CLI vs. Dashboard:** `scout run --seeds` writes report files under `outputs/scout/<run>/`; per-target
  Dashboard cards are populated by the **discovery** flow (§2). Use discovery for Dashboard-visible results.
- **Trace format:** Scout exposes a bounded redacted event trace, not a native Playwright
  `trace.zip`/Trace Viewer recording.
- **Session-independent autonomous writer** (Issue #17) is **parked, disabled by default** — not part of this
  release. The proven Direct-Driver GPT review + durable Dashboard/supervisor are on `main`.
