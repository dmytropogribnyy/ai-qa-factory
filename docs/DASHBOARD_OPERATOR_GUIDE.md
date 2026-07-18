# Dashboard Operator Guide (v3.1)

The Dashboard is the local **Administrator/Operator** front door over the existing safety-gated core.
It is one application (`core/scout/dashboard.py`), extended in v3.1 — not a new dashboard.

```powershell
python main.py dashboard            # http://127.0.0.1:8765  (Ctrl+C to stop)
```

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

`Overview · Scout · Work · More (Tools · Activity · Settings · Documentation)`.

| Route | Purpose |
|---|---|
| `/` | Overview inbox: Needs your attention, Active work, Active Scout campaigns |
| `/scout`, `/scout/campaigns`, `/results`, `/company` | Scout: home (+ start & Pause/Resume/Stop Safely/Cancel), campaigns, results, company detail |
| `/work`, `/work/<id>` | Work list (saved-view filters) and project detail (Summary/Plan/Results/Delivery) |
| `/tools` | Honest tool readiness levels |
| `/activity` | Recent lifecycle transitions (from state history) |
| `/settings`, `/docs` | Workspace/density/Scout defaults/Gmail status; local documentation |

`/` shows the Scout run view when the dashboard is bound to an active Scout run (preserved v3.0.x
behavior); it is the Overview inbox in operator-home mode.

## What the Dashboard does and does NOT execute

- **Guarded mutations** (POST, behind loopback Host + Origin + CSRF): `analyze`, `approve`, `review`,
  `review-reject`, `prepare-delivery`, `reopen-delivery`, `mark-delivered`, plus Scout `campaign/start`
  and `control`. They accept only ids/reviewer/note/reason — **never a command or argv**.
- **Not over HTTP:** `record-execution` and `validate` (which runs a real command) are **Claude Code
  handoffs**, done in VS Code via the CLI. There is no arbitrary-command or argv endpoint.
- **Nothing is sent.** `mark-delivered` records your assertion that you sent the prepared package
  manually; the Dashboard never sends email, submits a form, scans a third party, or bypasses a login.
- **Upwork intake is manual**: paste the brief (+ optional source reference). There is no Upwork API.

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
