# Dashboard v3.1 — Reuse Map (mandatory, precedes implementation)

v3.1 is an **incremental extension and UX consolidation** of the existing v3.0.x dashboard
(`core/scout/dashboard.py`), not a new dashboard. There is exactly **one** dashboard application,
one HTTP handler (`_make_handler`), one escaping helper (`_esc`), one guard, one artifact server,
one CSRF/ownership model. This map is the authority for KEEP / EXTEND / MINIMAL-REFACTOR / CREATE.

## Existing architecture (inspected)

- **Server:** `core/scout/dashboard.py` — a single stdlib `ThreadingHTTPServer` bound to `127.0.0.1`,
  one `_make_handler(service, launcher, csrf_token)` class. Started by `start_dashboard(...)`, which
  also publishes the CSRF token file and the ownership record (v3.0.2 M7).
- **GET routes:** `/health`, `/api/status`, `/api/csrf`, `/api/prospects`, `/api/prospect`,
  `/api/events`, `/api/campaign`, `/api/candidates`, `/api/providers`, `/api/presend`, `/api/comms`,
  `/api/tools`, `/tools`, `/api/projects`, `/projects`, `/api/results`, `/results`, `/company`,
  `/artifact`, `/` (adaptive overview).
- **POST routes (guarded):** `/api/control`, `/api/campaign/start` — each behind loopback bind +
  loopback `Host` + `Origin` + per-server CSRF; body drained before rejection.
- **Renderers (server-side HTML, inline `<style>`, `_esc`-escaped):** `_overview_html`,
  `_campaign_html`, `_presend_html`, `_comms_html`, `_results_html`, `_company_html`,
  `_projects_html`, `_tools_html`.
- **Reused domain services:** `ProjectIndex` (`_projects_snapshot`), `ToolBroker` (`_tools_snapshot`),
  `ScoutService` (status/control), `CampaignLauncher` (guarded start), `MemoryDB` (results/company).
- **Guard helpers on the handler:** `_host_is_loopback`, `_csrf_ok`, `_origin_ok`, `_read_json_body`.

## Regression locks (must stay green — from existing tests)

- `test_phase83_dashboard.py`: `/health`, `/api/status`, `/api/prospects`, `/artifact` traversal-safe,
  and **`/` renders the Scout run view** containing `"Prospect QA Scout"`, `"Cancel (kill)"`,
  `"Stop Safely"` for an active/controllable run.
- `test_phase831_dashboard_control.py`: `/api/control` pause/resume/cancel/kill; a READ_ONLY_ATTACHED
  run shows **`"Controls unavailable"`** at `/` and control POSTs return 409; non-CSRF POST → 403.
- `test_v3_campaign_start.py`: guarded `/api/campaign/start` (loopback Host/Origin/CSRF, DNS-rebinding),
  CSRF token file for the CLI.
- `test_v3_windows_stop_ownership.py`: the ownership record written by `start_dashboard`.

**Consequence:** `/` stays adaptive. When the dashboard is bound to an active/attached Scout run it
keeps rendering today's Scout run view (regression preserved, zero migration). The **idle/home**
branch of `/` — today an empty prospect table — becomes the new **Overview operator inbox**. A new
`/scout` route is an explicit entry to the Scout run/home view for the consolidated nav.

## Decision table

| Capability | Verdict | Notes |
|---|---|---|
| Single dashboard server + `_make_handler` | **KEEP** | one app; all new routes added to the same handler |
| `_esc`, `_html`, `_json`, `_artifact` confinement | **KEEP** | reuse for all new pages; no second escaper |
| Guard helpers (`_host_is_loopback`/`_origin_ok`/`_csrf_ok`/`_read_json_body`) | **MINIMAL REFACTOR** | extract into one shared `RequestGuard` (M10) and reuse for the new Work POSTs; behavior identical so existing tests stay green |
| `/api/campaign/start`, `/api/control` | **KEEP** | unchanged; now call the shared guard |
| `/` overview | **EXTEND** | active/attached run branch unchanged; idle branch → Overview inbox |
| `/results`, `/company`, `/projects`, `/tools`, `/api/*` | **KEEP** | continue working; Scout module + Work list reuse them |
| `ProjectIndex`, `WorkExecutionService`, `ClientWorkService`, `ScoutService`, `ToolBroker`, evidence model, state machine | **KEEP / REUSE** | no second store/index/pipeline/state machine |
| Tool readiness | **EXTEND** | add conceptual levels (M0.3) on top of the existing `ToolBroker` ladder — same broker, no new catalogue |
| Read model for the UI (OverviewSnapshot, ProjectListItem, ProjectDetail, AttentionItem, AllowedAction, …) | **CREATE (thin)** | `core/dashboard/read_model.py` + `actions.py` — helper DTOs that COMPOSE the existing services; not a second dashboard, database, or API layer, and no business logic duplicated in JS |
| Design tokens CSS (`M9`) | **CREATE (thin)** | one local, inlined token stylesheet reused by all pages; replaces the ad-hoc per-page `<style>` blocks incrementally, no external assets |
| Nav consolidation Overview / Scout / Work / More | **EXTEND** | reorganizes and links existing pages; does NOT recreate Scout/Results/Company/Tools/Projects behind new routes |
| `/work`, `/work/<id>`, `/activity`, `/settings`, `/docs` | **CREATE** | genuinely missing; Work reuses `ProjectIndex`+`WorkExecutionService`, Activity reuses state history, Settings shows existing config |
| Client-work Work actions over HTTP (approve/review/prepare/reopen/mark-delivered) | **CREATE (guarded)** | new POSTs behind the shared guard; explicit confirmation; **never** an argv/command over HTTP |

## Genuinely missing (CREATE, justified)

1. Operator **Overview inbox** (idle `/`) — no equivalent exists (today it is an empty prospect table).
2. **Work list** `/work` and **project detail** `/work/<id>` with lifecycle tabs — the current
   `/projects` is a flat read-only table with no per-project view or actions.
3. **Claude Code handoff** (work order text, Open in VS Code, copy commands) — none exists.
4. **Guarded Work-action POSTs** (approve/review/prepare-delivery/reopen-delivery/mark-delivered) —
   the lifecycle is CLI-only today; the Dashboard needs guarded, confirmation-gated buttons.
5. **Activity** and **Settings** pages — none exist.
6. **Read-model DTOs / AllowedAction** — the UI must not parse raw JSON or embed state logic in JS.
7. **Design tokens** — pages use ad-hoc inline styles; a shared token set is needed for consistency.

## Superseded / consolidated (reported separately)

- **None deleted.** `/` idle content is *extended* (empty table → Overview), not removed; the active/
  attached Scout view at `/` is unchanged. `/projects` remains but the primary Work experience moves
  to `/work` (a `/projects` → `/work` compatibility link is added; `/projects` is not removed).

## Prohibitions honored

No second dashboard app, no second frontend framework, no parallel UI tree, no duplicate
Scout/Results/Company/Tools/campaign-control/client-work views, no second database/state/evidence/
project-index/API layer/design-system, no rewrite of backend safety logic for presentation, no
external CDN/font/analytics, no arbitrary shell/argv over HTTP.
