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

Open **Start Scout** (`/scout/new`). The only thing you choose is **where the websites come from**:

| Source | What you give it |
|---|---|
| **Find websites** | countries, business types, optional signals/keywords |
| **Paste URLs** | one address per line |
| **Upload file** | a CSV/XLSX whose column holds the addresses |

Then set an optional **Maximum sites** and press **Start Scout**. There is no scan mode, coverage
profile, campaign preset, page cap or capture switch to choose: those describe the engine rather
than the work, and answering them wrongly changed what evidence came back. Scout resolves depth
against a real Chromium probe and says which it used ("deep evidence capture", or "static scan (no
browser available…)") — a downgrade is never silent.

Whichever source you pick, the queue is the same after intake: addresses are canonicalised,
de-duplicated **by canonical domain** (so `www.nolt.io`, `nolt.io/` and a tracking-tagged pricing URL
are one site), checked for safety, and anything that is not a public website is refused by name. For
pasted and uploaded addresses the preview shows those counts **before** you press Start, computed by
the same code that will build the queue.

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

- **Scout → History** (`/scout/history`): one row per site, columns
  `Site | Result | Priority | Evidence | Contact | Analyzed | Open`. **Result** is the outcome —
  *Ready to contact*, *Needs review*, *No actionable findings*, *Blocked*, *Failed*, *Not analyzed* —
  not the kind of run that touched the site, with the reason underneath it. Empty facts are written
  out (*Not found*, *None captured*) rather than left blank, because a blank cell reads as "still
  working". Filter by text, by result, and by one collapsible date range. Archived results are on
  the **Archived** tab.
- **Scout → Needs attention** (`/scout/attention`): **one current row per canonical domain** whose
  automated browser was stopped by CAPTCHA, Cloudflare, an access check or a similar gate. Repeated
  blockages of the same site are that row's attempt history, not extra rows. The headline counts
  sites and attempts separately ("5 sites need review. 13 blocked attempts were recorded."), and a
  recorded value that is not a public website (`0.1`, a private IP) is listed as rejected input
  rather than beside real companies. The action is **Open manual check** — it opens the target; it
  does not clear the block.
- **Scout → Campaigns** (`/scout/campaigns`): campaign progress + counters. Archived runs move out
  of the Current view and remain recoverable from the **Archived** tab.
- **Target card** (click a domain): four sections in the order the work happens — **Findings**,
  **Evidence**, **Contact & outreach**, **Client package** — for the exact selected run. Internal
  IDs, raw JSON, hashes, policy ceilings and low-level diagnostics stay collapsed under **Advanced
  diagnostics**.
- Every evidence kind carries one of four states, never a blank: **Available**, **Not applicable**
  (a static scan opens no browser, so a screenshot was never in scope), **Not captured: reason** (it
  was in scope and the policy decided against it — nothing safe reproduced, so no video was kept), or
  **Capture failed: reason** (the browser ran and axe-core still could not be injected). Only the
  last of the four is a fault on our side, and it is the only one that warrants a re-run.
- **Contact & outreach** shows the public address with the exact page it was found on, the
  deterministic **talking points** the draft is built from, a suggested subject, and the draft itself
  marked **Draft — not sent**. No draft is written when nothing actionable was confirmed. Nothing is
  ever sent, and none of this goes into the client package.
- Findings include **severity**, **confidence**, a **one-line repro hint**, and category; findings
  are ordered by expected commercial value. **Screenshots/evidence** are attached and viewable from
  the card. Absent confidence/repro show a neutral placeholder (never invented).
- The browser trace shown in the Dashboard is a redacted structured event record. It is not a native
  Playwright `trace.zip`; Playwright Inspector is a live developer tool and is intentionally not part
  of the operator evidence UI.
- After a target reaches **Analysis complete**, select **Download client evidence (.zip)**.
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

Scout never solves or bypasses a challenge. Only a challenge that actually **blocks** the page
counts: the site answered with a refusal, an interstitial, or a bare challenge element with no page
around it. A CAPTCHA/Turnstile widget sitting on the site's own signup or contact form does **not**
block anything — the site served its content, so the target is analysed normally. When a real
challenge is detected, the target is marked **Needs your help** and the Dashboard provides:

1. **Open manual check** — starts a visible Chromium session for that exact target.
2. Complete the challenge yourself in the opened browser. The browser stays open for up to 15 minutes.
3. Select **Continue** to re-check the same page in the same in-memory browser context.
4. Select **Defer** to leave it in Needs attention, or **Skip** to end that attempt.

Cookies/session state stay in process memory and are not written into Scout evidence. A successful
manual handoff creates a new exact attempt and preserves the original blocked evidence rather than
rewriting history. If the challenge remains after Continue, the attempt stays incomplete.

**Nothing expires while you are away.** A blocked target waits in Needs attention indefinitely; the
15-minute clock starts only once the visible browser has reached the block, i.e. when the window is
already in front of you. Opening the check re-walks that ONE target, never the campaign. A timed-out
or deferred attempt leaves the target listed so you can simply start another; retries never pile up
duplicate rows.

When a check does carry a target to a result, that target **leaves** Needs attention: the original
run marks it `RESOLVED_BY_MANUAL_CHECK` ("Resolved by a manual check") and links to the attempt run
where the findings live. The original run keeps its blocked evidence and still reports no findings
of its own — the result belongs to the run that produced it.

If the banner says a verification page **may have** prevented analysis, the detector could not
prove a block and failed closed; it names the signal it saw so you can judge it yourself. Opening
the manual check on such a target and finding an ordinary page is a legitimate outcome — report it,
because it means the signal was wrong.

## 4a. Restart the Dashboard after a code change

The Dashboard is run from source, so a process keeps serving whatever it loaded at start. **Overview
→ Runtime** answers whether that still matches the disk:

- **Process started** — when this process began serving.
- **Running HEAD** — the commit it started from. A process started from a working tree is reported
  as `<sha> + local changes`, never as a clean commit it is not serving.
- **Local changes at process start** — whether uncommitted executable code was on disk then.
- **Restart required** — `Yes` when executable code (`main.py`, `core/`) changed after the process
  started. Docs, outputs, evidence, test data and the test suite are outside that check on purpose:
  editing them changes nothing the running process does.

To clear it, run `tools/restart_dashboard.ps1` (or the "AI QA Factory Dashboard" desktop shortcut,
which passes `-OpenBrowser` and is the single button for both starting and restarting — starting a
Dashboard that is already running is only the special case of restarting one).
It stops only THIS checkout's Dashboard, lets the `AIQA-Collab-Supervisor` task bring it back on the
repo venv, waits for `/health`, and prints the new PID, start time, running build and executable. If
the supervisor is unavailable it says so and exits non-zero rather than leaving you with a stopped
Dashboard and a success message; `-StartIfNoSupervisor` launches it directly instead.

There is deliberately **no restart button in the Dashboard**: it never spawns processes and never
accepts a command over HTTP. Process control stays outside that surface.

## 4b. What the client evidence package contains

Downloaded from the target's **Client package** section as
`<domain>-qa-evidence-<YYYYMMDD>.zip`. It extracts into one dated folder — never a scatter of loose
files — and everything in it opens offline by double-clicking:

```
<domain>-qa-evidence-YYYYMMDD/
  00-README.html          what to open first
  QA-Report.html          the findings with the screenshots that show them
  Findings.csv            the same list for a tracker (UTF-8 BOM + CRLF, so Excel reads it)
  Evidence/Screenshots/   named for the page each one shows
  Evidence/Videos/
  Evidence/Technical/     accessibility / performance / console / network summaries
  manifest.json           MIME, size and SHA-256 per file, plus run and build provenance
```

The package is **one site only**: no other company's evidence, findings or contacts. Your talking
points, the email draft and where the contact came from stay out of it — those are operator notes,
and one accidental forward is all it takes to matter. `approved_for_client_delivery` is `false`
inside the artifact itself, so a forwarded ZIP cannot imply an approval nobody gave: generating a
package is not deciding it may be sent.

- **Up to three UNIQUE screenshots** of pages the analysis actually visited — a ceiling, never a
  quota. A site with one meaningful page yields one frame. A capture that is byte-identical to one
  already packaged (the verification pass re-photographing an unchanged landing page) is dropped by
  SHA-256 and recorded in `manifest.json` under `omitted` with that reason.
- Each frame is **named for the page it shows** (`landing.png`, `pricing.png`, `booking-flow.png`)
  and bound to that page's URL in the manifest, so "2 screenshots" always means two different
  pictures of two different pages.
- **A reproduction video only for a reproducible interaction defect** — a dead control, a broken
  flow, an error or lost state after an action. Accessibility, structure, console and performance
  findings are evidenced by the page capture and the technical records, so the package states in
  writing *why* no video is attached instead of leaving a bare zero that reads as missing evidence.

  Scout makes that call itself — there is no capture switch to remember. Every finding is judged by
  `core/scout/evidence_policy.py::video_qualified`: the defect must be an interaction a still frame
  cannot show, severe enough, evidenced strongly enough, genuinely replayed (never merely attempted),
  reached by a safe read-only path with verified cleanup, and within the per-campaign cap. The
  verdict — kept or refused, with its reason — is persisted in `reproduction.json` as
  `video_decision` and is what the client package quotes. A page-load clip is never kept.

  `video_mode` remains in the run config as an explicit opt-out (`off`, or the legacy `manual`); a
  run recorded before this became automatic reads back as `manual`, because it never recorded.
- Deferred (see `docs/POST_V2_BACKLOG.md`): cropped, highlighted shots of the individual element
  behind a visual finding.

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

### More → Data management (`/data`)

Everything Scout has stored, what each run was for, and a staged way to let test data go.

- **Purpose is declared, never guessed.** A run records `run_purpose` at launch. Anything that did
  not — including every run made before the field existed — is **Unclassified** and is *never* swept,
  because inferring "this looks like a test" from a name is how production history disappears. Use
  **Record what these were** to make that decision explicitly; only Acceptance, Diagnostic and Manual
  test can be chosen, so the screen cannot hand out production's protection.
- **Deletion is staged**: *Preview* (names the runs, sites, screenshots, findings and megabytes, and
  lists everything it refuses and why) → *Move to Trash* (reversible, nothing leaves the disk) →
  *Restore*, or a **separate confirmation inside Trash** for permanent removal. There is deliberately
  no "Clear all".
- A site that production also scanned keeps its history, evidence and registry entry; only the test
  run's claim on it is released. An interrupted cleanup converges when retried. A tombstone records
  scope, counts and the moment — never the deleted content.

Acceptance and diagnostic runs are also kept out of production counters by default; the switch to
show them lives in **Settings**, beside the Runtime block.

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
