# Dashboard Operator Guide (v3.1)

The Dashboard is the local **Administrator/Operator** front door over the existing safety-gated core.
It is one application (`core/scout/dashboard.py`), extended in v3.1 — not a new dashboard.

```powershell
python main.py dashboard            # http://127.0.0.1:8765  (Ctrl+C to stop)
```

> **Access & Integrations** shows the two distinct email identities — **Gmail Scout Send**
> (`dipptrue@gmail.com`, `gmail.send`) and **Gmail QA Test Inbox** (`drdiplextech@gmail.com`,
> `gmail.readonly`) — each with independent readiness. The canonical policy is
> `docs/EMAIL_IDENTITY_AND_MAILBOX_POLICY.md`. The Dashboard never exposes a generic mailbox browser.

## Dashboard vs Claude Code vs Core

- **Dashboard** — operator control: status, approvals, filtering, evidence review, delivery control,
  and the mandatory Scout UI. It **reads** persisted state through read-only DTOs (lightweight polling
  + a manual **Refresh**) and performs mutations by calling the **same core services the CLI uses**.
- **Claude Code (in VS Code)** — repository reasoning, implementation, editing, terminal, and **real
  test execution**. The Dashboard hands work off to it (Open in VS Code / Copy Work Order); it does
  **not** embed a code editor or a Claude chat, and does **not** run arbitrary commands.
- **Core / CLI** — the only source of truth: lifecycle enforcement, persistence, evidence, security,
  validation, delivery integrity.

The Dashboard synchronizes only **structured QA project state** (state, artifacts, evidence,
validation, blockers, approvals, delivery) — never chat, terminal, or editor contents.

## Navigation

`Overview · Scout · Work · More (Activity · Collaboration · Settings · Help)`.

| Route | Purpose |
|---|---|
| `/` | Stable Overview inbox: Open work, Needs attention, Active Scout campaigns |
| `/scout`, `/scout/campaigns` | Scout launch, current/archived campaigns and state-aware controls |
| `/scout/history`, `/scout/target`, `/scout/run` | QA history, target evidence and exact-run retention |
| `/results`, `/company` | Companies & outreach (commercial follow-up, separate from QA History) |
| `/work`, `/work/<id>` | Active/Needs attention/Completed/All views, stage filter, brief analysis; project Summary/Plan/Results/Delivery |
| `/activity` | Recent lifecycle transitions (from state history) |
| `/collab` | Active collaboration by default; completed cycles in a separate view |
| `/settings` | Appearance, Scout defaults, integrations, Data & retention; advanced diagnostics |
| `/tools` | Advanced technical readiness, linked from Settings rather than primary navigation |
| `/docs` | Operator Help Center; developer reference files stay under Advanced |

In operator-home mode, `/` always stays Overview even when a Scout run is active; explicit Scout
pages own progress and controls. The legacy `/projects` route redirects to canonical `/work`.
**Companies & outreach** keeps text/contact-state/severity filters in the URL.

Ordinary views show human titles and keep campaign/run/project IDs, model names, token counts,
build SHAs, CI references, and raw readiness data inside **Advanced** diagnostics. Production views
hide smoke/acceptance/replay/demo data unless the operator explicitly enables diagnostics.

### Counting rules the operator can rely on

Every headline count equals the number of rows behind the link it points at — the count and its
destination are derived from the same projection, never from two separate rules:

| Overview tile | Destination | Means |
|---|---|---|
| Open work | `/work?view=active` | every client project that is not COMPLETED/CANCELLED |
| Needs attention (client work) | `/work?view=needs_attention` | blocked, approval-ready, or review-ready **client work** |
| Active Scout campaigns | `/scout/campaigns` | campaigns currently running |

Work attention and Scout attention are counted separately because they resolve to different
surfaces. A **failed Scout campaign is never folded into the client-work tile** — it would promise
more rows than `/work?view=needs_attention` can contain. Failed campaigns instead appear in their
own labelled block under *Scout* on Overview, with their own count and a link to
`/scout/campaigns`, so they stay visible without distorting the work queue.

The Overview *Active work* table is deliberately narrower than the Open work tile: it lists only
work that is approved and ready to run, running, or being validated.

**Blockers vs. information needed.** A project shows *Blockers* only for what is stopping it right
now. Intake questions block only until the operator approves the plan; afterwards they remain
visible on the project as "Information needed from the client (recorded at intake; no longer
blocking)". An approved project is therefore never described as both *Ready to execute* and
*blocked on missing information*. The Work list and the project detail read one shared next-action
rule, so a project states the same next step on every screen.

### A run's summary accounts for every target in it

The run-results tiles are not a selection of interesting numbers — they partition the run. `Targets`
is the total, and the remaining tiles are one per outcome actually present, so their counts always
sum to the total: a failed, an interrupted or an operator-skipped target can never sit in no category
and disappear from the summary while the operator reads "3 completed, 1 needs attention" and
concludes nothing else needs them.

The tiles and the rows they count read the same status vocabulary (`_run_status_label`), so a state
is called the same thing in both places: *Completed*, *Needs your help*, *Could not complete*,
*Queued*, *Skipped*. A status this build has never seen is titled and counted rather than dropped.

### A queued skip is visible, and "requested" is not "applied"

Skipping queued targets writes a request that the engine reads before it starts each new target — so
at the moment of the click nothing has happened yet to the target itself. The page therefore shows
the request where it was made: a banner stating how many targets are queued to be skipped and that
they will not start, plus a *Skip requested* marker on each affected row.

The marker means the request is pending, not that the target was skipped. It appears only while the
target is still `Queued`; once the engine acts, the target's own status becomes *Skipped* and the
marker is gone. A request left behind in the file for a target that has since finished can never
apply and is never advertised.

A target that cannot be skipped is refused with its real status, and that refusal keeps the operator
on the page instead of being erased by a reload, because a refusal is not persisted anywhere else. A
target cannot be skipped once it has completed, failed or been blocked — **and also once the engine
has started it**: the request is read immediately before each target begins and never interrupts one
mid-analysis, so such a target is refused as *already started*.

That last case needs one fact the status cannot carry. A target the engine is analyzing stays
`PENDING` in the compact state until it finishes, so the engine records `started_at` the moment it
begins one. Every surface reads that: a started target reads *In progress* rather than *Queued*, it
carries no skip marker, and the banner never promises that it will not start.

### Incomplete Scout targets never show confirmed findings

A target's confirmed findings come from a completed analysis only. Any prospect whose persisted
status is non-empty and not `DONE` — a challenge (`MANUAL_ACTION_REQUIRED`), a failure (`FAILED`), a
run interrupted before its result was recorded (`PENDING`), an operator skip (`SKIPPED`), or a status
a future engine adds — reads as 0 confirmed findings on **every** surface: the Target page, the run
results, `/api/scout/target`, and the raw-JSON `/api/prospect` diagnostic.

The rule lives in one place, `analysis_incomplete()` in `core/scout/campaign_service.py`, and every
read path calls it, so a new surface inherits the rule instead of re-deriving it. A historical record
with no status at all keeps its previous artifact-loading behaviour; that is the single deliberate
exemption.

**Which screen you get does not depend on how you arrived.** The Target page picks the truthful
renderer from that same predicate, never from whether a `run` was pinned in the link. This matters
because History links to a target without a run, and a domain is registered as analyzed once it is
promoted — regardless of how its individual QA run ended. A target whose latest run was interrupted
therefore reads as *Not analyzed* whether it was opened from a run page or from History.

**Result-bearing artifacts follow the result.** The finding records, the priority scorecard derived
from them, the reproduction record and its video clip are reachable only for a completed analysis —
withheld from the page and refused by `/scout/artifact` with `409` otherwise, because that URL is
user-facing and guessable. Nothing is deleted from disk. Page-level capture stays available for an
incomplete target — screenshots, the page observation, the browser trace and the stop-reason record —
because that is what explains why the run stopped.

`/api/prospect` stays useful for diagnosing an interrupted run: it still returns the page-level
`observation` and `evidence`, and it always states `prospect_status` and `analysis_complete`. What it
withholds it says plainly — `{"withheld": "analysis_incomplete", "artifact_present": true|false}` —
so "we are not showing this because the analysis never finished" is never confused with "there is
nothing on disk".

**Each incomplete state is described by what actually happened to it.** The Target screen derives its
badge, its page title and its available action from the real status: a challenge says *Needs your
help* and offers the manual check; a skipped target says *Skipped*; an interrupted one says *Not
analyzed*; anything else says *Could not complete*. Only a real challenge links to
`/scout/attention`, because only a challenge appears there.

**Counts on a completed target.** For a `DONE` target the numbers satisfy
`Actionable = findings with severity != "info"`, `Informational = findings with severity == "info"`,
and `Total = Actionable + Informational`, which equals the number of findings the read API returns
for that target. The run row reads the compact prospect counters and the Target card reads the
findings artifact, so this is a direct number-to-number agreement between two independent sources.

### The six site results, and why there are six

A site's result is one of six values. The first five were the original vocabulary; **Not analyzed**
is a deliberate sixth, because a target that was discovered and never scanned did not *fail* —
nothing was attempted — and reporting a failure that never happened is worse than reporting nothing.

| Result | Means | Never used for |
|---|---|---|
| **Ready to contact** | Analysis completed with at least one actionable finding and a public contact | A site with no confirmed actionable finding |
| **Needs review** | Analysis ran, but its evidence could not be resolved or a human must look | A run that failed |
| **No actionable findings** | Analysis completed and confirmed nothing worth acting on | "The site is defect-free" — it is a bounded pass, not a clean bill of health |
| **Blocked** | A challenge, login wall or access control stopped the scan | A crash or an internal error |
| **Failed** | A run that genuinely failed, proven by its own recorded state | A target that was never attempted |
| **Not analyzed** | Discovered, queued, interrupted or skipped — never scanned | Anything that produced a result |

Three rules keep them apart:

- **Never scanned → Not analyzed.** Not *Failed*, whatever the surrounding run did.
- **Analyzed but evidence unresolved → Needs review.** Not *Failed*: the analysis happened.
- **A proven failed run → Failed**, and only then.

The same value appears in Overview, History, Details and the read API, from one computation
(`core.scout.site_result`), so the four cannot disagree. Registry statuses are persisted lowercase
(`analyzed`) and prospect statuses uppercase (`DONE`); both are normalised before comparison —
comparing the two vocabularies directly is what once made an analysed site read as *Failed*.

## Data & retention

### What a run was for

Every run records a **purpose** when it starts, and nothing infers one afterwards from a name:

- **Production** — ordinary operator work. The default: the daily form does not ask, and what it
  does not ask for is real work.
- **Acceptance / Diagnostic / Manual test** — deliberately disposable. Created only through a
  harness, the CLI, or a server started with `AIQA_SCOUT_TEST_PURPOSE=1`; a request cannot label its
  own data disposable by adding a field.
- **Unclassified** — written before the field existed. Treated conservatively as real work and never
  swept automatically.

History and the campaign counts show production by default; the purpose filter reveals the rest
without changing anything. Only a disposable purpose can be permanently deleted, and deleting one
never touches a production run of the same site.

Settings explains the three cleanup classes before the operator acts:

- **Archive** — reversible; hides a target or run from current views.
- **Forget target** — removes History/dedup memory while preserving exact-run evidence.
- **Delete** — permanent; limited to selected heavy evidence or an inactive exact run.

Completed Work and Collaboration are removed from the default active queue but remain available in
their dedicated completed views. Raw Activity remains append-only.

On **Work**, the four primary views stay visible while individual lifecycle stages live in the
**Status** selector. Diagnostic projects are available only under **Advanced view options**. The
empty Active/All states link directly to **Analyze a client brief**; that form creates a persisted,
reviewable feasibility assessment and work plan, but never begins execution. The source platform is
an optional bounded choice (`Upwork`, `Direct client`, or `Other`), not an integration or import.
Validation and server errors appear beside the form and move focus to the field that needs attention.

**Interactions.** Overview, Work list, and project detail do bounded same-origin polling: a *Live /
Last updated* indicator plus an "Updates available — Refresh" banner when persisted state changes.
Polling never auto-reloads, so it never interrupts the intake form or a reviewer prompt; manual
**Refresh** is always available. Project detail uses accessible **tabs** (Summary/Plan/Results/
Delivery) with keyboard navigation and a `?tab=` deep link. Lifecycle-action buttons are disabled
while a mutation is in flight (double-submit safe). **Open in VS Code** uses a correctly-encoded
cross-platform `vscode://file/` URI; **Copy Work Order** / **Copy Workspace Path** remain as
fallbacks with visible copy feedback.

## What the Dashboard does and does NOT execute

- **Guarded mutations** (POST, behind loopback Host + Origin + CSRF): `analyze`, `approve`, `review`,
  `review-reject`, `prepare-delivery`, `reopen-delivery`, `mark-delivered`, plus Scout `campaign/start`
  and `control`. They accept only ids/reviewer/note/reason — **never a command or argv**.
- **Not over HTTP:** `record-execution` and `validate` (which runs a real command) are **Claude Code
  handoffs**, done in VS Code via the CLI. There is no arbitrary-command or argv endpoint.
- **Nothing is sent.** `mark-delivered` records your assertion that you sent the prepared package
  manually; the Dashboard never sends email, submits a form, scans a third party, or bypasses a login.
- **Upwork intake is manual**: select Upwork as the source and paste the brief. There is no Upwork
  API, source-reference field, or background import.

The shared footer identifies ordinary pages as **AI QA Factory · Operator Dashboard**. Scout routes
retain the Scout product/version identity so operators can distinguish the module without making
Work or Overview look like Scout-only screens.

## Lifecycle & delivery

`PLANNED → READY_TO_EXECUTE → EXECUTING → VERIFYING → READY_FOR_REVIEW → READY_FOR_DELIVERY →
DELIVERY_PREPARED → COMPLETED` (with `REPAIR_REQUIRED`/`BLOCKED`). The project detail's **primary
action** is derived from the real state machine.

- **Prepare Delivery** seals the exact package (registered artifacts + evidence + `DELIVERY_REPORT.md`
  + `CLIENT_MESSAGE.md`, each hashed) → `DELIVERY_PREPARED`.
- **Reopen Delivery** (from `DELIVERY_PREPARED`) archives the prepared manifest as audit history and
  returns to `READY_FOR_DELIVERY` (drafts/metadata only) or `REPAIR_REQUIRED` (validated content
  changed — the review is invalidated and the full loop is required).
- **Mark Delivered** re-verifies the manifest + every file, then records the manual send.

## Evidence

Evidence appears in Project → Results with an integrity badge — **Verified** (hash matches the
validated snapshot), **Stale** (changed since validation), or **Unverified**. **Preview** opens the
`/work-evidence` endpoint, which is path-confined and size-bounded: images preview inline; text
previews as text; **active content (HTML/SVG/JS) is never executed** — it is returned as a text/plain
attachment under a `sandbox` CSP.

## Tool readiness levels

Declared · Binding Available · Runtime Available · Fixture Verified · Live Verified · Blocked ·
Unavailable. A test file is never a runtime binding; a binding present is *Binding Available*; nothing
is *Live Verified* without a real live acceptance.

## Security

Local-only: loopback bind; a shared guard on every state-changing endpoint (loopback `Host` anti
DNS-rebinding + `Origin` + per-server CSRF); a local-only Content-Security-Policy with no external
scripts/styles/fonts; project-id validation and artifact-path confinement; safe download headers; no
arbitrary filesystem browser, no arbitrary command endpoint, no secrets in HTML/JSON/URLs/logs.
