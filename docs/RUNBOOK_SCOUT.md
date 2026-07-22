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

- **Scout → History** (`/scout/history`): processed sites, filterable by status/period.
- **Scout → Campaigns** (`/scout/campaigns`): campaign progress + counters.
- **Target card** (click a domain): findings with **severity**, **confidence**, a **one-line repro hint**,
  and category; findings are ordered by expected commercial value. **Screenshots/evidence** are attached and
  viewable from the card. Absent confidence/repro show a neutral placeholder (never invented).
- **Progress/budget** are shown truthfully (discovered / eligible / analyzed / rejected / failed, provider
  calls, cost). Errors and skipped items are reported honestly, not hidden.

## 4. Control a run

- **Pause / Resume / Stop** from the campaign view (or `main.py scout control --signal pause|resume|cancel`).
  State is honest and cooperative (finishes the current op, starts no new one).
- Data and history are **file-based** under `outputs/` and **persist across a Dashboard restart**.

## 5. Safety

Read-only public analysis only. No outreach, no form submission, no login, no CAPTCHA solving, no
irreversible action. Outreach drafts are copy-only and are never sent by the system.

## 6. Known limitations (deferred, non-blocking)

- **History freshness:** a re-analysis of an already-registered domain surfaces fresh findings on the
  target card, but the History row's `last_analysis_at` may lag until the site is promoted; use the target
  card for the current findings. (Tracked for a follow-up.)
- **Seed CLI vs. Dashboard:** `scout run --seeds` writes report files under `outputs/scout/<run>/`; per-target
  Dashboard cards are populated by the **discovery** flow (§2). Use discovery for Dashboard-visible results.
- **Session-independent autonomous writer** (Issue #17) is **parked, disabled by default** — not part of this
  release. The proven Direct-Driver GPT review + durable Dashboard/supervisor are on `main`.
