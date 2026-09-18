# Dashboard UX Contract V1 — frontend ↔ backend

**Stage:** SUPER MACRO A / A3 (Issue #74)
**Status:** contract. Binding on both writers.
**Writers:** backend contracts, read models and integration — Claude. Frontend components, layout and
UX — the admitted frontend writer (Lovable). One writer per seam; neither rewrites the other's.

**Grounded in:** `docs/DASHBOARD_CURRENT_STATE_V3.md` (what exists today, with a live capture) and
`docs/AI_QA_FACTORY_V3_GAP_ANALYSIS.md` (what is real vs proposed). Read those first — this contract
only defines the target and the rules; it does not restate current behaviour.

---

## 0. The four rules that outrank everything else in this document

1. **ONE canonical read model.** The frontend reads product truth from exactly one backend read-model
   surface. It never reads a second store, and it never reconstructs truth the backend already derives.
2. **ONE persisted truth.** No product state lives in the frontend, in browser storage, or in any
   frontend-side database. Browser storage is for per-viewer conveniences only (theme, density,
   collapsed sections, unsent drafts).
3. **No business logic in the frontend.** Status, eligibility, allowed actions, counts and severity
   roll-ups are computed server-side and consumed as given.
4. **Missing is not zero. NOT_VERIFIED is not PASS. Health is not readiness.** A field the backend
   could not determine renders as *unknown*, never as `0`, `""`, "OK" or an empty state that implies
   absence of a problem.

A design that is prettier but violates any of these is rejected.

---

## 1. Information architecture

### 1.1 Top-level navigation (exactly eight)

| Section | Purpose | Answers |
|---|---|---|
| **Overview** | One inbox. What needs me now. | "What should I do next?" |
| **Work** | Client engagements through their lifecycle | "What are we delivering?" |
| **Scout** | Prospect acquisition and target discovery | "Who should we approach?" |
| **Assurance** | Run and review assurance profiles against a target | "What was tested, and what passed?" |
| **Evidence** | Evidence as a first-class, searchable surface | "What is proven, and how?" |
| **Reviews** | Human + independent review decisions and the engineering bridge | "What is waiting on a decision?" |
| **History** | Activity and audit trail | "What happened, and when?" |
| **Settings** | Runtime, integrations, data & retention, diagnostics | "How is this configured?" |

**A new top-level section must justify why an existing workflow cannot contain it.** Advanced
diagnostics, tool/capability matrices and MCP internals live **inside Settings**, hidden by default.
Agents and MCP are implementation mechanisms, not the user's mental model.

### 1.2 Project / Target view (exactly seven tabs)

Every engagement, campaign target and assurance subject uses the **same** seven-tab view. There is not
one tab set for client work and another for Scout targets.

| Tab | Contains |
|---|---|
| **Summary** | Identity, profile, lifecycle state, next action, headline counts |
| **Coverage** | What was tested and what was *not*, with the reason — never silence |
| **Findings** | Actionable findings, grouped and deduplicated server-side |
| **Evidence** | Evidence items with type, capture status, integrity and client-safety |
| **Retest / Delta** | `NEW` / `RESOLVED` / `REGRESSED` / `UNCHANGED` / `NOT_REVERIFIED` against a baseline |
| **Baseline** | Candidate / accepted / superseded / invalidated |
| **Release Gate** | `PASS` / `WARN` / `BLOCK` against the customer-owned policy |

Tabs whose backend capability does not yet exist render an explicit **"not yet available"** state —
never a fabricated empty table that reads as "nothing to report".

### 1.3 Assurance is one workflow, many profiles

`Accessibility`, `AI`, `Agent` and `Custom Policy / Compliance` are **profiles selected inside the
Assurance workflow**. They are not separate products, separate dashboards or separate navigation
entries. Adding a framework mapping (WCAG, AI Act, DORA, NIS2, BYO policy) adds a *profile*, never a
page.

---

## 2. Resolutions of the twelve current duplications

These are decided here so neither writer re-litigates them. Each maps to a numbered observation in
`DASHBOARD_CURRENT_STATE_V3.md` §7.

| # | Current | Contract |
|---|---|---|
| 1 | Two entry points, two home pages, one port | **One** home. The legacy `operator_home=False` overview is retired; both entry points render the same Overview. |
| 2 | Legacy home shape-shifts across four layouts by file presence | Retired with #1. Layout never depends on which report file happens to exist. |
| 3 | Two ways to start Scout | **One** Start Scout entry. The in-process manual-URL path becomes a *mode* inside it, not a rival screen. The "which screen?" help card is deleted, not rewritten. |
| 4 | Two prospect/company truth stores; Overview links to the empty one | **One** — the persisted registry/campaign surface. The in-process and run-scoped `memory.db` reads are removed from outward surfaces. This is the single most important fix in this contract. |
| 5 | Two run-control vocabularies (`cancel\|kill` vs `stop`) | **One** control vocabulary, defined in §4.3. |
| 6 | Two disagreeing prospect-status label maps | **One** map, server-side, §4.2. |
| 7 | Four dead HTML builders, one with a second design system | Deleted. |
| 8 | `POST /api/scout/preflight` has no UI caller | Either surfaced in Start Scout as a readiness step, or removed. Not left orphaned. |
| 9 | `/api/work/` means a project id on GET and a verb on POST | Split: resources under `/api/v2/work/<id>`, commands under `/api/v2/work/<id>/actions/<action>`. |
| 10 | `/projects` ghost route still linked | Links updated; redirect kept one release, then removed. |
| 11 | Three readiness surfaces behind one hidden page | Consolidated into Settings → Diagnostics. |
| 12 | `/collab` hard-reloads every 15s | Uses the shared signature-poll mechanism like every other view. |

---

## 3. The canonical read model

### 3.1 Single surface

`core/dashboard/read_model.py` (`dashboard-read-model/v1`) is the seed and **must be extended, not
duplicated**. The V2 surface adds Scout, Assurance, Evidence and Reviews to the same model that already
serves client work.

Backend rule: every outward read endpoint is a projection of persisted truth through this model.
Introducing a second read path for the same concept is a contract violation, regardless of convenience.

### 3.1.1 Canonical evidence and finding types (A4)

The read model projects exactly **one** evidence type and **one** finding type:

| Concept | Canonical type | Everything else |
|---|---|---|
| Evidence item | `core/schemas/evidence.py:EvidenceRecord` — extended in A4 with `content_hash` and `verification_status`, fail-closed defaults (`client_visible=False`, `requires_redaction=True`, `verification_status="UNVERIFIED"`) | the live producer shapes (`core/schemas/work_execution.py:EvidenceItem`, `core/scout/pipeline/evidence.py:EvidenceItem`, `core/schemas/browser_execution.py:BrowserExecutionEvidence`) reach the read model **only** through `core/schemas/evidence_adapters.py`; `core/schemas/execution_summary.py:EvidenceItem` is deprecated and has no product consumer |
| Finding | `core/schemas/finding.py:Finding` | `core/scout/findings.py:ScoutFinding` reaches it **only** through `finding_from_scout` in `core/risk/finding_adapters.py`; anything short of `VERIFIED` arrives as `needs_review`, and evidence references are withheld unless the Scout finding is client-safe |

`GET /api/v2/evidence` returns `EvidenceRecord` projections; `GET /api/v2/targets/<ref>` findings are
`Finding` projections. A backend that introduces a third evidence or finding shape for a V2 endpoint
violates this contract. The full classification of every evidence-shaped class in `core/` is
`EVIDENCE_SHAPE_REGISTRY` in `core/schemas/evidence_adapters.py`, and a guard test fails when a new
one appears unclassified.

### 3.2 Envelope

Every read endpoint returns the same envelope, so the frontend has one parsing strategy:

```json
{
  "schema": "dashboard-read-model/v2",
  "generated_at": "<iso8601>",
  "data": { },
  "truncated": false,
  "unknown_fields": []
}
```

- `unknown_fields` names fields the backend **could not determine**. The frontend must render those as
  *unknown*, distinctly from zero or empty. This is rule 4 made mechanical.
- `truncated` is set whenever a bounded list was capped; the frontend must show that it was capped.

### 3.3 Endpoints (read)

| Endpoint | Returns |
|---|---|
| `GET /api/v2/overview` | attention items, active work, Scout attention, system readiness verdict |
| `GET /api/v2/work?view=` | engagement list for a named view |
| `GET /api/v2/work/<id>` | the seven-tab payload for one engagement |
| `GET /api/v2/scout/campaigns` | campaign list |
| `GET /api/v2/scout/targets?campaign=` | target list |
| `GET /api/v2/targets/<ref>` | the seven-tab payload for one target |
| `GET /api/v2/assurance/profiles` | available profiles and their applicability |
| `GET /api/v2/assurance/runs?target=` | assurance runs for a subject |
| `GET /api/v2/evidence?subject=` | `EvidenceRecord` projections: integrity (`content_hash`, `verification_status`) + client-safety flags |
| `GET /api/v2/reviews` | pending decisions, bridge state, review history |
| `GET /api/v2/history?subject=` | activity/audit entries |
| `GET /api/v2/settings/runtime` | build identity, readiness, integrations |

Existing `/api/*` endpoints remain until their V2 replacement is live. **No endpoint is removed before
its replacement ships.**

### 3.4 Actions (write)

```
POST /api/v2/<resource>/<id>/actions/<action>
```

- The **allowed action set is served by the backend** with the resource. The frontend renders exactly
  what it is given and never infers availability from status strings.
- Every action returns the updated resource in the same envelope, so the frontend never re-derives
  state after a mutation.
- Irreversible or consequential actions carry `"confirm_required": true` and a human-readable
  `confirm_prompt`; the frontend must honour it.

---

## 4. Single vocabularies

The backend owns these. The frontend renders labels it is given and must not invent, translate or
re-map them.

### 4.1 Lifecycle
Client work keeps its existing 17 states and four health buckets (*On track / Needs attention /
Blocked / Done*). Scout campaigns keep their existing states. **Both are exposed with a
backend-supplied `label` and `health` so the frontend never maps state → colour itself.**

### 4.2 Target / prospect outcome
One map replaces the two that currently disagree. Superset, decided server-side:
`PENDING, RUNNING, DONE, MANUAL_ACTION_REQUIRED, RESOLVED_BY_MANUAL_CHECK, SKIPPED, FAILED, CANCELLED`.

### 4.3 Run control
One vocabulary for every run type: **`pause` · `resume` · `stop` · `cancel`**, where `stop` checkpoints
and `cancel` abandons. `kill` is not an outward verb.

### 4.4 Assurance status
`PASS · FAIL · PARTIAL · NOT_APPLICABLE · NOT_VERIFIED · BLOCKED · UNKNOWN`, carrying the existing
`run_validation` discipline. `NOT_VERIFIED` and `UNKNOWN` are rendered **visually distinct from
`PASS`** — not a neutral grey that reads as "fine".

### 4.5 Evidence availability
The existing four-valued taxonomy is preserved and surfaced verbatim, with its reason string:
`AVAILABLE · NOT_APPLICABLE · NOT_CAPTURED(reason) · CAPTURE_FAILED(reason)`.

---

## 5. Client-safe rendering

The Evidence and Findings surfaces are the boundary where operator data could leak into a client view.

- Client-facing projections pass through the existing **field allowlist**; the internal `finding_id` is
  never sent to a client surface — the derived `cf-<sha12>` handle is.
- Any view marked client-facing must be reachable in a "client preview" mode that renders **only**
  allowlisted fields, so the operator can see exactly what the client sees.
- Counts are computed **once** server-side through the canonical actionable/informational split, so
  report, table, export and manifest cannot disagree.
- Never present sandboxed or simulated execution as a real transaction; where a result came from a
  fixture or sandbox, the backend labels it and the frontend shows that label.

---

## 6. Security invariants the frontend must not break

These are non-negotiable and already implemented:

1. Loopback-only bind; non-loopback `Host` rejected before routing — **reads are guarded too**.
2. Every mutation carries the per-server CSRF token, same-origin, constant-time compared.
3. No endpoint accepts a command, argv or path from the client.
4. Body sizes are capped; bounded lists report `truncated`.
5. Restart is not an HTTP action.
6. All untrusted text is escaped; third-party HTML is re-rendered, never served as-is.
7. Target/page content and tool output are **untrusted data** and can never grant authority.

If the frontend becomes a separate app, it inherits all seven. A remote-origin frontend is **out of
scope for V1** — that would be a new trust boundary and needs its own owner decision.

---

## 7. Frontend writer handoff

### 7.1 Build order
1. Overview, Work list, Work detail (seven tabs) — the backend read model already exists here.
2. Scout list + target detail on the *persisted* surface (resolves duplication #4).
3. Reviews, History, Settings.
4. Assurance and Evidence — backend lands during A5–A7; build against the mock contract first.

### 7.2 Mock contract
Every endpoint in §3.3 must have a fixture response with the exact §3.2 envelope, so the frontend can
be built and reviewed before the backend ships. Fixtures must include the **awkward** cases, not only
happy paths:

- an `unknown_fields` entry that must render as *unknown*, not zero;
- a `truncated: true` list;
- a target with `NOT_CAPTURED` evidence carrying a reason;
- an engagement in `BLOCKED` with a next action;
- an assurance run with mixed `PASS` / `NOT_VERIFIED` / `BLOCKED`;
- a release gate returning `WARN`.

A component that only renders the happy path is not done.

### 7.3 Explicitly out of scope for the frontend
Business rules; status derivation; eligibility; counts; severity scoring; any persistence of product
state; any direct store/database access; any second source of truth.

---

## 8. Non-claims

This contract does not implement anything. Assurance, Evidence, Retest/Delta, Baseline and Release Gate
are **contract-only** here — the gap analysis classifies their backends as `NEW` or `EXTEND`, and §1.2
requires them to render "not yet available" until real. Endpoint paths are proposed and become binding
when implemented; none exist yet. No frontend technology choice is mandated by this document beyond the
rules above.

---

## Related

- `docs/DASHBOARD_CURRENT_STATE_V3.md` — current truth (A2)
- `docs/AI_QA_FACTORY_V3_GAP_ANALYSIS.md` — what is real vs proposed (A1)
- `docs/ENGINEERING_EXECUTION_POLICY.md` — how work is executed (A0)
