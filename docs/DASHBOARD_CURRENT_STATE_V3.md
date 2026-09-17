# Dashboard — current-state truth (V3 handoff pack)

**Stage:** SUPER MACRO A / A2 (Issue #74)
**Purpose:** extract what the Dashboard *actually is today*, before any redesign, so the A3 UX contract
and the frontend writer build against real behaviour rather than an imagined one.
**Identity:** static evidence from `feat/macro-a-v3-foundation` @ `2d38293`; live capture from the
running Dashboard at `running_sha ff97547096ec`.

> This is a **description, not a proposal.** Nothing here is a redesign. Where a surface is confusing,
> that is recorded as an observation for A3 to resolve — not fixed here.

---

## 1. How it runs

| Fact | Evidence |
|---|---|
| CLI | `main.py:592-596` — `dashboard` subcommand, `--port` default **8765** |
| Startup | `main.py:421-448` → `start_dashboard(service, port, operator_home=True)` |
| Server | `core/scout/dashboard.py:6143-6197` — `ThreadingHTTPServer`, **loopback only**; a non-loopback bind raises |
| Renderer | Every page is a Python f-string. `_page(title, active, body, script)` at `:5729` is the only layout. **No template engine, no static asset route, no JS bundle.** |
| Interactivity | Vanilla `fetch` + a polling helper that compares a computed signature before re-rendering |
| Theme/density | `localStorage` only, never sent to the server |

**Second entry point, different home page:** `python main.py scout dashboard` → `operator_home=False`
→ `/` renders the *legacy* overview instead of the v3.1 Overview, on the **same default port**.

### Security seams that must survive any redesign

1. Loopback-only bind, or the server refuses to start.
2. **Reads are guarded too** — a non-loopback `Host` header gets 403 *before* any route matches
   (anti-DNS-rebinding), so evidence and contacts are protected, not just mutations.
3. Every mutation passes one shared guard: loopback bind + loopback `Host` + `Origin` +
   `secrets.compare_digest` CSRF, with a per-server token published to
   `outputs/scout/_dashboard/csrf-<port>.token`.
4. No endpoint accepts a command or argv. Body sizes are capped.
5. Lifecycle mutations are serialised per project by a lock.
6. All untrusted text goes through `_esc()`; the client report is **re-rendered through app escaping**
   rather than served as third-party HTML.
7. Restart is deliberately **not** exposed over HTTP.

---

## 2. Route inventory

**Exhaustiveness method (re-proven, not sampled):** `grep -n 'def do_'` returns exactly `do_GET`,
`do_POST`, and `do_HEAD = do_GET`. A grep for `elif path|match path|self.path ==` returns **0**, so
there is no secondary dispatcher. Counting the branch forms gives **73 route branch statements**:
`if path == "` ×53, `if path.startswith("` ×2, `if parsed.path == "` ×16, `if parsed.path in (` ×1,
`if parsed.path.startswith(` ×1. Both handlers end in an explicit 404. Verbs other than
GET/HEAD/POST fall through to stdlib 501.

### GET (≈57 path patterns)

**Pages:** `/` (Overview, or legacy home when `operator_home=False`) · `/work` · `/work/<project_id>` ·
`/scout` (Manual URL Scan) · `/scout/new` (Start Scout) · `/scout/campaigns` · `/scout/progress` ·
`/scout/history` · `/scout/target` · `/scout/run` · `/scout/attention` · `/results` · `/company` ·
`/activity` · `/data` · `/settings` · `/tools` · `/collab` · `/docs` · `/projects` (303 → `/work`)

**JSON APIs:** `/health` · `/api/status` · `/api/csrf` · `/api/prospects` · `/api/prospect` ·
`/api/events` · `/api/campaign` · `/api/candidates` · `/api/providers` · `/api/presend` · `/api/comms` ·
`/api/tools` · `/api/services` · `/api/toolgap` · `/api/projects` · `/api/overview` · `/api/work` ·
`/api/work/<project_id>` · `/api/activity` · `/api/access` · `/api/build` · `/api/collab` ·
`/api/discovery` · `/api/scout/catalog` · `/api/scout/progress` · `/api/scout/history` ·
`/api/scout/target` · `/api/scout/attention` · `/api/scout/validation` · `/api/results`

**File/bundle serving:** `/artifact` · `/scout/artifact` · `/scout/client-evidence` (builds the client
ZIP) · `/scout/client-report` (client-facing preview) · `/work-evidence`

### POST (≈21 exact paths + 1 prefix) — every one behind `_guard_mutation`

`/api/control` (`pause|resume|cancel|kill`, in-process run) · `/api/campaign/start` ·
`/api/scout/preflight` · `/api/scout/launch` · `/api/scout/import` · `/api/scout/intake/preview` ·
`/api/scout/data/{preview,trash,restore,delete,classify}` · `/api/scout/control`
(`pause|resume|stop`, persisted campaign) · `/api/scout/export` · `/api/scout/rescan` ·
`/api/scout/replay` · `/api/scout/challenge/{start,action}` · `/api/scout/operator` ·
`/api/scout/engagement` · `/api/scout/polish-draft` · `/api/scout/start-client-work` ·
`/api/work/<action>`

`/api/work/<action>` accepts: `analyze`, `worker-start`, `worker-resume`, `worker-cancel`,
`worker-status`, `approve`, `review`, `review-reject`, `prepare-delivery`, `reopen-delivery`
(reason required), `mark-delivered`. Anything else → 404 `unknown work action`.

---

## 3. Live capture evidence

25 read-only routes fetched from the running Dashboard; **all 25 returned 200**. Routes with side
effects were deliberately excluded (`/scout/client-evidence` builds a ZIP, `/api/access?refresh=1`
recomputes, artifact routes need params).

| Route | Bytes | Page title / JSON shape |
|---|---:|---|
| `/` | 27,344 | Overview — sections: Overview, Scout, Needs your attention, Client work |
| `/work` | 31,692 | Work |
| `/scout` | 32,151 | Scout — "Manual URL Scan", "Start a bounded read-only campaign" |
| `/scout/new` | 33,034 | Start Scout |
| `/scout/campaigns` | 27,355 | Scout campaigns |
| `/scout/history` | 39,007 | Scout history |
| `/scout/attention` | 30,318 | Needs attention — "Sites blocked before a full analysis" |
| `/results` | 25,117 | Companies & outreach |
| `/activity` | 27,493 | Activity |
| `/data` | 72,322 | Data management |
| `/settings` | 38,958 | Settings — Runtime, Appearance, Scout defaults, Data & retention, Integrations |
| `/tools` | 34,784 | Advanced readiness — Service capabilities |
| `/collab` | 36,283 | Collaboration — Reviewer, Delivery worker, Background supervisor, Current tasks |
| `/docs` | 27,713 | Help — "Start a run: which screen?" |
| `/health` | 132 | `status, product, version, run_id, running` |
| `/api/build` | 345 | `product_version, running_sha, head_sha, running_build, …` |
| `/api/overview` | 2,085 | `schema, generated_at, attention, scout_attention, active_work` |
| `/api/work` | 178 | `schema, generated_at, view, total, offset, limit, projects` |
| `/api/collab` | 50,897 | `schema, generated_at, current_head, driver, delivery, supervisor` |
| `/api/projects` | 4,723 | `project_count, by_type, projects` |
| `/api/discovery` | 14,906 | `schema, kill_switch, provider, last_campaign, next_run, …` |
| `/api/scout/history` | 13,110 | `rows` |
| `/api/access` | 11,084 | `schema, count, any_secret_shown, integrations` |
| `/api/tools` | 8,195 | `generated_at, tool_count, domains, any_live_accepted, tools` |
| `/api/services` | 19,386 | `schema, service_count, services` |

Note `/docs` shipping a card titled **"Start a run: which screen?"** — the product needs a help page to
explain its own navigation. That is a UX finding, recorded in §7.

---

## 4. Read models — where truth comes from

**Client work has a real read-model layer and does not bypass it:**

- `core/dashboard/read_model.py` — `DashboardReadModel`, schema `dashboard-read-model/v1`. Composes
  `ProjectIndex` + `WorkExecutionService` + `ToolBroker`; derives stage labels, health buckets,
  attention reasons and the view predicate. **Reads persisted state only.**
- `core/dashboard/actions.py` — `allowed_actions(status)` derives the button set **from the real
  lifecycle state, never in JS**; `ProjectDetailBuilder.detail()` reads the persisted per-project JSON
  and stamps evidence `integrity` as verified/stale/unverified.
- `core/orchestration/project_index.py` — the single `_CLIENT_NEXT_ACTION` map that Work list, Work
  detail and Overview all read.

**Scout has two truth surfaces — this is the seam that matters for A3:**

| Surface | Reads | Consequence |
|---|---|---|
| `/api/status`, `/api/prospects`, `/api/prospect`, `/api/events`, `/api/campaign`, `/api/candidates`, `/health`, all of `/scout` | the **in-process** `ScoutService` object | structurally empty unless a run was started or attached *in this same process* |
| `/results`, `/company` | a run-scoped SQLite `memory.db` | returns `{"companies": [], "note": "no memory database for this run"}` when no run is bound |
| `/scout/history`, `/scout/target`, `/api/scout/*` | `CampaignService` + `AnalyzedSiteRegistry` (**persisted disk**) | shows the real data |

So on a plain `python main.py dashboard`, `/results` is empty while `/scout/history` shows campaigns
for the same disk — and **Overview links to the empty one**.

---

## 5. Operator actions exposed by the UI

Scout: pause/resume/stop-and-save/cancel a run · start a manual-seed campaign · import curated
CSV/XLSX seeds · preview/normalise seeds · launch adaptive discovery (with explicit
`approve_live_discovery`) · pause/resume/stop a campaign · export a campaign bundle · archive /
restore / forget targets · skip queued · delete evidence · archive/restore/delete a run · re-scan a
blocked target · headed replay · set engagement stage (`won`/`delivered` require confirm) · start
client work from a prospect · AI-polish an outreach draft (**the only paid-model path in the UI**) ·
open a visible browser for a challenge, then continue/defer/skip.

Client work: analyze a brief · approve plan · approve/reject review · prepare delivery · reopen
delivery (reason required) · mark delivered · start/resume/cancel the bounded worker.

Data: preview / classify / trash / restore / permanently delete (confirm required).

**Deliberately not actions — these are hand-offs:** executing the work and running validation are
"Open in VS Code", "Copy Claude Code Work Order", "Copy Workspace Path". The Dashboard sends no email
and performs no outbound delivery.

---

## 6. Status vocabularies surfaced today

- **Client work (17 states):** `RECEIVED, INTAKE_COMPLETE, PLANNED, WAITING_FOR_INFORMATION,
  WAITING_FOR_APPROVAL, READY_TO_EXECUTE, EXECUTING, EXECUTION_PARTIAL, VERIFYING, REPAIR_REQUIRED,
  READY_FOR_REVIEW, READY_FOR_DELIVERY, DELIVERY_PREPARED, BLOCKED, FAILED, CANCELLED, COMPLETED`
  → health buckets `On track / Needs attention / Blocked / Done`.
- **Work views:** `all, active, needs_attention, ready_to_execute, in_progress, blocked,
  ready_for_review, ready_for_delivery, delivery_prepared, completed`.
- **Scout campaign:** `QUEUED, DISCOVERING, TRIAGING, ANALYZING, PAUSING, PAUSED, RECOVERABLE,
  STOPPED_WITH_CHECKPOINT, COMPLETED, BLOCKED, FAILED, RUNNING, DONE`.
- **Prospect/target outcome:** `DONE, MANUAL_ACTION_REQUIRED, RESOLVED_BY_MANUAL_CHECK, FAILED,
  PENDING, SKIPPED` — plus a **second, overlapping** map adding `RUNNING, COMPLETED, CANCELLED, KILLED`.
- **Manual-challenge session:** `opening, waiting, continuing, defer_requested, skip_requested,
  completed, deferred, skipped, failed, timed_out`.
- **Engagement:** `prospect, contacted, replied, won, delivered, lost`.
- **Collaboration thread:** `WORKING, REVIEWING, NEEDS_OWNER, WAITING_FOR_CI, FIXING, DONE`.
- **Tool readiness:** `Runtime Available, Fixture Verified, Live Verified, Blocked, Unavailable`.

---

## 7. Duplicated / confusing UX (observations for A3, evidence-backed)

1. **Two entry points, two home pages, one default port** (`operator_home` True/False).
2. **The legacy home is a shape-shifter** — it renders one of four entirely different pages depending
   on which report file happens to exist on disk.
3. **Two ways to start Scout** — `/scout` (in-process launcher) vs `/scout/new` (CampaignService).
   `/docs` carries a card that exists solely to answer "which screen?".
4. **Two prospect/company truth stores** (§4) — and Overview links to the one that is usually empty.
5. **Two run-control vocabularies** — `pause|resume|cancel|kill` vs `pause|resume|stop`: same words,
   different verbs, different state stores.
6. **Two prospect-status label maps that disagree.**
7. **Dead HTML builders still in the file** — four are defined and never called; one ships its own
   standalone `<style>` block, i.e. a second unreachable design system.
8. **An endpoint with no UI caller** — `POST /api/scout/preflight` is only referenced by tests.
9. **Overloaded `/api/work/` prefix** — the same URL means a project id on GET and a verb on POST.
10. **`/projects` is a ghost route** (303 → `/work`) still linked from two pages.
11. **Three readiness surfaces** collapsed into one page hidden behind Settings.
12. **`/collab` hard-reloads every 15s** while every other page uses the shared signature-poll script.

---

## 8. Client-facing vs operator-only

**Client-facing content** (still served on the operator's loopback origin):
`/scout/client-report` — explicitly labelled a preview of what the client would receive, with a banner
stating that talking points, the email draft and contact provenance are *not* included;
`/scout/client-evidence` — the bounded client-ready ZIP; and the package-status block on the target
page.

**Everything else is operator-only by construction** — drafts, contact provenance, engagement stage,
budgets, diagnostics, scorecards, prospect ids.

The exclusion is centralised, not ad-hoc: `_public_finding()` is a field **allowlist**, and the
internal `finding_id` is never forwarded — a derived `cf-<sha12>` handle is emitted at the single
boundary all four client surfaces pass through.

---

## 9. What must be preserved in any redesign

1. Loopback-only bind **and** the `Host`-header read guard.
2. The one shared mutation guard (loopback + `Origin` + constant-time CSRF).
3. Allowed actions derived **server-side from lifecycle state**, never in JS.
4. The client/operator field allowlist and the `cf-<sha12>` handle boundary.
5. Counting done once through the canonical actionable/informational split, so README, CSV, JSON and
   manifest cannot disagree.
6. Build identity in the footer of every page, with `stale` / `restart_required` honesty.
7. Health (liveness) kept distinct from readiness; restart kept off the HTTP surface.
8. Hand-offs that are deliberately not buttons — execution and validation stay operator-initiated.

---

## 10. Non-claims

No redesign is proposed here. No pixel screenshots were captured — the deterministic capture in §3 is
structural (status, title, sections, size) and was chosen because `outputs/` is never committed, so
binary screenshots would not travel with the repo; pixel captures can be produced on demand from the
running Dashboard. Routes with side effects were not exercised. The POST surface was **not** invoked
at all — it is documented from source, not from live calls.

---

## Related

- `docs/AI_QA_FACTORY_V3_GAP_ANALYSIS.md` — the V3 classification this feeds
- `docs/DASHBOARD_OPERATOR_GUIDE.md` — operator-facing usage
- `docs/architecture/DASHBOARD_V31_REUSE_MAP.md` — prior reuse map
