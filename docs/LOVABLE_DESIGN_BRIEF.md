# Lovable Design Brief — AI QA Factory Operator Dashboard (v3.1)

**This is a brief for a later, optional, presentation-only pass. Do NOT start it yet.** The functional
v3.1 candidate is implemented in this repository (server-rendered pages in `core/scout/dashboard.py`
over the read model in `core/dashboard/`). A Lovable pass may refine visual hierarchy, spacing,
typography, colour, component appearance, responsive behaviour, and usability polish **only**.

Lovable must **not**: redesign application architecture; create another backend, database, or state
store; change safety guards; add authentication; replace persisted state; invent features; or become
the source repository. All application DTOs, routes, and workflows below are fixed contracts.

## Product & operator

- **Product:** a local-first operator dashboard over a safety-gated AI QA automation core. One local
  user is both **Administrator** and **Operator**. No multi-user, roles, cloud, SaaS, billing, or team
  collaboration.
- **The dashboard answers three questions fast:** What needs my attention? What is running now? What
  should I do next? Use progressive disclosure (status → summary → one primary action → details →
  technical logs only when expanded). No vanity metrics or decorative charts.
- **Boundaries (must remain visible):** the Dashboard reads state and performs guarded lifecycle
  mutations; Claude Code (in VS Code) does the implementation and real test execution; the Dashboard
  never embeds a chat/editor/terminal, never runs arbitrary commands, and never sends anything.

## Visual constraints (real content only)

Light workspace; neutral gray/slate surfaces; blue primary action; green only for verified success;
amber for attention; red only for errors/destructive actions. No decorative gradients; restrained
shadows; clear typography; consistent spacing; status conveyed by **text + icon, never colour alone**.
Desktop-first, responsive, no horizontal page overflow (wide tables scroll within their own box).
Comfortable/Compact density. Visible focus ring; keyboard accessible; zero serious/critical axe
violations must be preserved.

## Route inventory (fixed)

| Route | Page | Notes |
|---|---|---|
| `/` | Overview inbox (operator-home) / Scout run view (run-bound) | attention, active work, campaigns |
| `/work` · `/work/<id>` | Work list (saved-view filters) · Project detail | tabs: Summary/Plan/Results/Delivery |
| `/scout` · `/scout/campaigns` · `/results` · `/company` | Scout module | start + Pause/Resume/Stop Safely/Cancel preserved |
| `/tools` · `/activity` · `/settings` · `/docs` | More | honest readiness · state history · config · local docs |
| `/work-evidence` | safe evidence preview/download | confined; active content never inline |

### JSON read-model endpoints (UI consumes these; do not parse raw files)
`/api/overview`, `/api/work`, `/api/work/<id>`, `/api/activity`, `/api/tools`, `/api/csrf`.

### Guarded mutation endpoints (POST; shared guard; never a command/argv)
`/api/work/{analyze,approve,review,review-reject,prepare-delivery,reopen-delivery,mark-delivered}`,
`/api/campaign/start`, `/api/control`.

## Component inventory (reusable)

Shared layout `_page(title, active, body, script)` + `_nav_html` (Overview/Scout/Work/More). Building
blocks: `.card`, `table` + `<caption>`/`<th>` (scrolls within its box), `.badge`(`.ok/.attention/
.blocked/.done`), `.btn`(`.primary/.danger`), `.chip` (filters/saved views), `.empty` (empty states),
`<details>` (progressive disclosure), `.row` (wrapping flex), `.skeleton` (loading). DTOs:
OverviewSnapshot, ProjectListItem, ScoutCampaignListItem, AttentionItem, ToolReadinessItem,
ActivityItem, AllowedAction, ProjectDetail (`core/dashboard/read_model.py` + `actions.py`).

## Design tokens (CSS custom properties, `:root`)

`--bg --surface --surface-2 --border --text --muted --primary --primary-ink --ok --attention --danger
--focus` (colour); `--radius --pad --gap --maxw --row` (layout, with a `[data-density="compact"]`
override); `--font`. Tokens are local and inlined (CSP: no external assets). A Lovable pass may retune
token **values** and component **appearance**; it must not rename tokens the server relies on or change
the DTO/route contracts.

## Permitted presentation-only improvements

Visual hierarchy, spacing rhythm, typography scale, colour refinement (keeping contrast + semantics),
component polish (cards, badges, buttons, tables, empty/loading states), responsive behaviour, and
micro-usability. Everything must keep working against the same endpoints, DTOs, guards, and lifecycle.
