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
| Needs attention | `/work?view=needs_attention` | blocked, approval-ready, or review-ready work |
| Active Scout campaigns | `/scout/campaigns` | campaigns currently running |

The Overview *Active work* table is deliberately narrower than the Open work tile: it lists only
work that is approved and ready to run, running, or being validated.

**Blockers vs. information needed.** A project shows *Blockers* only for what is stopping it right
now. Intake questions block only until the operator approves the plan; afterwards they remain
visible on the project as "Information needed from the client (recorded at intake; no longer
blocking)". An approved project is therefore never described as both *Ready to execute* and
*blocked on missing information*. The Work list and the project detail read one shared next-action
rule, so a project states the same next step on every screen.

## Data & retention

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
