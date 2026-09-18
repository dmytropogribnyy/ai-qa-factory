# AI QA Factory V3 — Unified Gap Analysis

**Stage:** SUPER MACRO A / A1 (Issue #74)
**Base identity:** analysed against `feat/macro-a-v3-foundation` @ `dac7119`, whose tree descends from
`main` @ `ff97547` (TASK 0.1 merged).
**Method:** five bounded read-only reconnaissance agents over disjoint areas, followed by
**integrator re-proof** of every material claim. Subagent output was treated as evidence, not verdict.
One agent claim was **rejected on re-proof** (§6.4) and one was **corrected** (§5.1).

## Scope limitation — read this before trusting any classification

The five V3 design-package documents named in the Issue #74 execution order
(`..._ASSURANCE_AGENTIC_PROFIT_ROADMAP_V3_...`, `..._IMPLEMENTATION_PROFIT_BLUEPRINT_V2_...`,
`..._POLY_SCALPEL_..._REUSE_BLUEPRINT_V1_...`, `..._DUAL_BLUEPRINT_HARDENING_..._V1_...`,
`..._AGENT_MCP_EXECUTION_FABRIC_ADDENDUM_V1_...`) **are not present in this repository** and were not
available to this analysis. `find` for `*2026-09-17*` returns nothing.

Therefore this document classifies the V3 proposals **as enumerated in Issue #74 itself** against live
code. Where a design document contains a proposal not restated in Issue #74, that proposal is
**NOT_ANALYSED** here. This is a gap in the analysis, not a gap in the product.

## Classification legend

| Verdict | Meaning |
|---|---|
| `ALREADY_EXISTS` | Implemented and wired into a production path. Reuse; do not rebuild. |
| `EXTEND` | Real substrate exists. Add to it. Building parallel machinery would violate reuse-over-rebuild. |
| `NEW` | Genuinely absent. Must be built. |
| `DEFER` | Absent, and not required for the nearest sellable outcome. |
| `REJECT` | Proposed but disproved by live code, or would violate a product invariant. |

A recurring and important sub-case: **implemented but unwired** — the code exists, is tested, and has
*no production caller*. That is classified `EXTEND`, never `ALREADY_EXISTS`, because a component with
no call site does not do anything. Four significant instances are recorded below.

---

## 1. Area classifications

### 1.1 Assurance Core (the eight V3 objects)

| Object | Verdict | Evidence |
|---|---|---|
| `AssuranceProfile` | `EXTEND` | Absent by name (zero hits for "assurance" in `core/**/*.py`). `core/schemas/capability.py:69 CapabilityProfile` already carries `evidence_expectations` + `delivery_shape`, with 9 YAML profiles in `capabilities/profiles/`. That is the seed. |
| `Requirement` | `ALREADY_EXISTS` | `core/schemas/requirement.py:33`, 7-value `VERIFICATION_STATUSES`, fail-closed rehydration, real producer `requirement_extractor.py:56`. |
| `Control` | `NEW` | No control/compliance-control object. Check vocabularies exist (`core/quality_gate.py:18`, `core/scout/checks.py`) but a Control is not a Check. |
| `VerificationSpec` | `NEW` | No declarative "how to verify X". `core/schemas/test_oracle.py:45 TestScenario` has no expected-result/assertion field. |
| `ApplicabilityReceipt` | `EXTEND` | Absent by name; semantics exist in three places, notably `core/schemas/prospect_coverage.py:145-151`, which **refuses `COVERED`/`PARTIAL` without evidence refs**, and `core/scout/evidence_state.py:27-30`. |
| `VerificationResult` | `EXTEND` | `core/scout/run_validation.py:47 Check` (`expected`/`observed`/`explanation`/`evidence_refs`) is the richest existing shape; `core/schemas/work_execution.py:55 ValidationOutcome` is the other. |
| `RequirementAssessment` | `NEW` | **Re-proven:** `Requirement.verification_status` is written as `"unverified"` at exactly two sites (`requirement_extractor.py:79,94`) and `from_dict` actively *downgrades* `"satisfied"` back to `"unverified"` (`requirement.py:53-55`). Nothing maps evidence → satisfaction. The `EvidenceVerifier` named in two docstrings **does not exist**. |
| `ReviewDecision` | `EXTEND` | Two concrete decision records exist: `REVIEW.json` (`work_execution.py:472`) and the SHA-bound collaboration `DECISION` (`envelopes.py:31`). `core/schemas/approval.py:12 ApprovalDecision` exists but has **no runtime consumer**. |

**Hard invariants are already honoured somewhere and must be preserved:** `core/scout/run_validation.py`
implements `PASS/FAIL/PARTIAL/NOT_APPLICABLE/UNKNOWN` with `validated` true only when every applicable
check passes, and its docstring states *"An unproven fact is reported as UNKNOWN, never as 0, "" or
Success."* That is the chassis for assurance status roll-up — `EXTEND` it, do not write a new one.

### 1.2 EvidenceCenter / RunStore — `EXTEND`, with a duplication problem

`RunStore` (`core/scout/store.py:40`) is `ALREADY_EXISTS`-grade: atomic writes, path confinement,
append-only events with **idempotent** `append_event_once`, fail-closed `StoreCorruptionError`.
`prepare_delivery` (`core/orchestration/work_execution.py:490`) is a genuine content-hash seal with
re-open history.

**But the "ONE evidence model" invariant is already violated.** Re-proven directly:

- **Three** competing `EvidenceItem` dataclasses: `core/schemas/execution_summary.py:12`,
  `core/schemas/work_execution.py:27`, `core/scout/pipeline/evidence.py:35`.
  *(Recon reported two; re-proof found three.)*
- **Two** unbridged finding types: `core/schemas/finding.py:49 Finding` and
  `core/scout/findings.py:35 ScoutFinding`, with no adapter between them.
- **Four** evidence writers over different roots.

Converging these is Macro A work, not a later cleanup: every V3 assurance object that references
"evidence" must reference exactly one of them.

`known_at` semantics: `NEW` (zero hits). Per-run attempt identity: `NEW`.

### 1.3 Accessibility — `EXTEND`

- axe-core injection/parse/store on the Scout path: `ALREADY_EXISTS`. Version pinned via
  `axe-playwright-python==0.1.8` (axe-core 4.12.1), discovered at runtime by `preflight.py:119-120`,
  and `campaign_start.py:209-216` **refuses a Deep Capture run with 503 rather than silently
  downgrading** when axe is unusable. `_parse_axe_report` raises rather than recording "0 violations"
  for a failed run.
- **axe rule → WCAG success-criterion mapping: `NEW` on the live path.** The only `_WCAG_TAG_MAP` lives
  in `core/accessibility_runner.py`, which **never runs a browser** (re-proven: every `npx playwright`
  reference there is a comment or an instruction string; `execute()` only appends notes). A WCAG
  technical profile product line needs this mapping to exist somewhere real.
- `PUBLIC_TEASER` / `AUTHORIZED_AUDIT`: **zero occurrences in Python** (re-proven). They exist only in
  `docs/architecture/PROSPECT_QA_RADAR_SPEC.md` and `docs/SAFETY_RULES.md`. The implemented analogue is
  `core/schemas/prospect_disclosure.py` `DisclosureStage`/`DisclosureLevel` with hard teaser ceilings —
  `EXTEND` that. A **client-authorisation / permission-to-test artifact is `NEW`**; today "scope" means
  only "this URL passed `url_safety`".
- Coverage policy and the four-valued missing-evidence taxonomy (`AVAILABLE / NOT_APPLICABLE /
  NOT_CAPTURED / CAPTURE_FAILED`): `ALREADY_EXISTS` and unusually good.
- Client evidence bundle with operator-only exclusion: `ALREADY_EXISTS`
  (`core/scout/client_evidence.py:339 _public_finding` is an allowlist; internal `finding_id` is never
  forwarded).

### 1.4 Scout / Deep Capture — `ALREADY_EXISTS` (browser seam `EXTEND`)

Deep Capture, SSRF hardening (per-subresource route check plus post-navigation final-URL
re-validation), coverage ceilings, video qualification, two-pass independent verification — all
implemented and bounded. Live discovery and all outbound sending remain **gated/disabled by default**.

`EXTEND`: there is **no single `launch_browser()`**. Four duplicated `chromium.launch()` sites
(`backends.py:439,606,696`, `preflight.py:73`) plus an entirely separate `npx playwright test`
subprocess lineage across ~14 modules. An MVP should centralise the first four.

`DEFER`: Playwright tracing and HAR capture are absent; not required for the nearest sellable audit.

### 1.5 Retest / delta / baseline — `EXTEND` (implemented, **unwired**)

Re-proven: `reconcile_lifecycle` (`core/scout/pipeline/normalize.py:112`) appears **only** in its own
definition and `tests/test_final1_findings.py`. **Zero production callers.** The SQLite schema is ready
(`lifecycle_state`, `first_seen_at`, `root_impact_key`).

It computes only `RESOLVED` and `REGRESSED` — **`NEW` and `UNCHANGED` buckets do not exist**, and there
is no cross-run baseline selector. So A8 is "wire + add two states + add baseline selection", which is
materially cheaper than the roadmap implies.

### 1.6 Agent / MCP control fabric — mostly `NEW`, on good primitives

| Component | Verdict | Note |
|---|---|---|
| Canonical tool registry | `EXTEND` | Four disjoint registries (`config/mcp_servers.yaml` v1 — the only one loaded — plus `v2.yaml`, `capabilities/atomic_capabilities.yaml`, `tool_broker._CATALOGUE`). `core/schemas/mcp_descriptor.py:86 MCPToolDescriptor` is nearly the V3 row but **nothing constructs it at runtime**. |
| R0–R5 risk tiers | `NEW` | Four competing risk vocabularies; the ordinal `RISK_LEVELS` has **zero non-test consumers**. |
| Task capability envelope | `EXTEND` | `ToolchainPlan`/`ExecutionBudget` exist but are planning artifacts no executor reads back. |
| Deterministic policy gateway | `NEW` | `ToolPolicyEngine` is referenced in four docstrings and **does not exist**. `core/scout/integrations/mcp.py` implements exactly the right primitives (`validate_tool`, `check_recursion`, `detect_prompt_injection`, `classify_result`) — with **test-only callers**. The natural single choke is `_call_handler` in `integrations/mcp/server.py`. |
| Action receipts | `NEW` | `operator_executor.py:222-237` validation `metadata.json` is the template to generalise. |
| Per-tool-call idempotency | `NEW` | Explicitly deferred in-code (`work_run_state.py:16-22`). Run-level and message-level idempotency are `ALREADY_EXISTS`. |
| Budgets | `EXTEND` | `BudgetLedger` is a real fail-closed persistent ledger; `ExecutionBudget` is the right schema with no runtime. |
| Explicit refusal states | `EXTEND` | `NEEDS_OWNER` exists only as a collaboration message kind, not a work-run state nor an MCP response state. ≥5 exception types and ≥3 JSON refusal shapes. |
| Taint / trust propagation | `NEW` | `untrusted_output=True` is declared and rehydration-protected but never enforced at runtime; the injection detector is unwired. |

**"Destructive is blocked by default" is weaker than it reads.** `capability_planner.py:49-51` blocks
`class == "destructive"`, but **no capability in `capabilities/atomic_capabilities.yaml` declares that
class**. Destructive is blocked by vocabulary absence, not by an exercised runtime gate.

Secret redaction is the strongest part of the fabric and is `ALREADY_EXISTS`: one redactor, applied at
every persistence boundary, with the correct redact-**then**-truncate ordering and an in-memory scan
before any write.

### 1.7 Direct Collaboration — `ALREADY_EXISTS`, with one blocking defect (§6.1)

Nine modules, 9-kind envelope vocabulary, SHA-bound, write-once store with O_EXCL sequencing, budget
ledger, response cache, session delivery with an argv-list command and a narrow tool grant, monitor and
supervisor. Hard limits are real and documented: it can never merge, write source, run arbitrary shell,
or send externally. TASK 0.1 hardened the delivery lease, bounds and ACK suppression.

Review Relay (`core/review_relay.py`) is **live** (own CI job, own tests, documented worker protocol)
but **superseded in function** by the envelope model. Classification: `EXTEND` as an MCP transport
surface; its *protocol* is legacy.

### 1.8 Dashboard / frontend seams — `EXTEND`

One HTTP surface: a hand-rolled `BaseHTTPRequestHandler` in `core/scout/dashboard.py` (~6.2k lines, all
HTML as Python f-strings). ~57 GET paths and ~21 POST paths. Loopback-only bind, non-loopback `Host`
rejected before routing, every mutation behind one shared guard (loopback + `Origin` + constant-time
CSRF). A real read-model layer exists for client work (`core/dashboard/read_model.py`,
`actions.py`) and derives the allowed action set from persisted lifecycle state, never in JS.

Duplication to resolve in A2/A3 (evidence-backed):

1. **Two entry paths, two different home pages, one shared default port** (`operator_home` True/False).
2. **Two ways to start Scout** — `/scout` (in-process launcher) vs `/scout/new` (CampaignService); the
   Help page exists mainly to explain which to use.
3. **Two prospect/company truth stores** — `/results` + `/company` read a run-scoped `memory.db` and are
   structurally empty unless a run is bound *in this process*, while `/scout/history` reads the same
   disk via the registry and shows data. Overview links to the empty one.
4. **Two run-control vocabularies** — `pause|resume|cancel|kill` vs `pause|resume|stop`.
5. Dead HTML builders still in the file, including one with its own second design system.
6. `GET /api/work/<project_id>` and `POST /api/work/<action>` share a prefix with different meanings.

This is the single strongest argument for the A3 unified UX contract: the backend already has one
truth for client work; the Scout surfaces have two.

### 1.9 Approvals / safety — `ALREADY_EXISTS` (work lifecycle), `NEW` (uniform per-action)

The work-execution approval is genuinely strong and should be the model: authority lives in an
operator-only control store **outside** client-writable content, is project- and workspace-bound, and
its `approval_at` must match both `APPROVAL.json` and the latest `READY_TO_EXECUTE` transition. The
in-workspace file is labelled evidence-only. A client checkout cannot self-assert trust. Rehydration
forces every approval flag to `False`.

Against that, ~15 runners each invent their own approval boolean, and the one generic
`ApprovalDecision` schema has no consumer. A uniform per-action approval object is `NEW`.

### 1.10 Replay / controlled learning — `NEW` (entirely)

Replay corpus, champion/challenger, prospective shadow, frozen generations, drift, canary: **all
absent**. Every keyword hit is a false positive (idempotent replay, headed browser "replay",
`@dataclass(frozen=True)`, documentation-drift checks). Usable substrate exists (immutable envelope
store, per-SHA evidence packs, fixture client seams, scenario fixtures) — so this is greenfield on good
foundations, and correctly sequenced last (B9/B10).

### 1.11 GitHub protection / merge gates — `NEW`

`.github/` contains exactly two files. No CODEOWNERS, no rulesets, no required-check configuration.
Merge policy exists only as prose, and the prose **conflicts** (§6.2). `core/collaboration/manifest.py`
is the natural hook for a CI-fed gate but has no producer (§6.1).

### 1.12 Subscription / API execution paths — `EXTEND`

Two parallel, unreconciled model-selection paths: the `LLMRouter` profile system (`core/config.py`,
`core/llm_router.py`, 6 role aliases, `mock` default, degradation ladder ending in mock) and the
Direct Collaboration reviewer (`gpt-5.6-sol`, `reasoning_effort=high`, key from
`~/.aiqa/openai.key`), which is **not routed through `LLMRouter` at all**.

Cost metering is fragmented across four disjoint mechanisms with no unified ledger, and **USD is
structurally always zero by default** (§6.3).

---

## 2. Duplication inventory (the ONE-X invariants)

| Invariant | Status |
|---|---|
| ONE Dashboard | Holds — one HTTP surface. But two home pages and two Scout truth surfaces inside it. |
| ONE persisted product truth | **At risk** — client work has one read model; Scout has two (`memory.db` vs registry). |
| ONE evidence model | **Violated** — three `EvidenceItem` classes, two finding classes, four evidence writers. |
| ONE engineering bridge | Holds — the Direct Collaboration Driver; Review Relay shares the same store base by design. |

---

## 3. What Macro A should actually build (ordered by dependency)

1. **Converge the evidence/finding models** (A4/A5 precondition). Pick one `EvidenceItem` and one
   finding type; write adapters rather than a third variant.
2. **`AssuranceProfile` as an extension of `CapabilityProfile`**, not a new object.
3. **`Control` + `VerificationSpec`** — the two genuinely new Assurance Core objects.
4. **`RequirementAssessment` + the missing `EvidenceVerifier`** — the only thing that makes
   `Requirement.verification_status` mean anything.
5. **Status roll-up on `run_validation.py`'s chassis**, preserving `UNKNOWN ≠ 0 ≠ PASS`.
6. **axe rule → WCAG criterion mapping** on the live Scout path.
7. **Authorisation artifact + PUBLIC/AUTHORIZED split** over `DisclosureStage`.
8. **Wire `reconcile_lifecycle`**, add `NEW`/`UNCHANGED`, add baseline selection.
9. **Centralise `launch_browser()`** across the four in-process sites.

---

## 4. REJECT / DEFER

| Proposal | Verdict | Reason |
|---|---|---|
| Build a new evidence store for Assurance | `REJECT` | Four already exist; a fifth violates the invariant. `RunStore` + the seal are sufficient. |
| Build a second run-state machine | `REJECT` | `WorkRunState` + `WorkStateManager` already enforce transitions with immutable history. |
| Build a second browser engine | `REJECT` | Explicitly forbidden by A7 and unnecessary. |
| Playwright tracing / HAR capture | `DEFER` | Not required for the nearest sellable accessibility audit. |
| Full multi-tenant SaaS | `DEFER` | Hard ceiling in the ABC directive. |
| Live `tools/list` MCP discovery | `DEFER` | Deliberately deferred in-code; a static registry is enough for B0. |

---

## 5. Corrections made during integrator re-proof

1. **Evidence duplication undercounted.** Recon reported two `EvidenceItem` classes; there are three.
2. **A claimed truthfulness defect was rejected.** Recon characterised `core/client_delivery_pack.py`
   as advertising an accessibility section backed by a stub. Re-proof shows the pack is **honest**: the
   status label reads *"Generated checks only; execution requires approval"* with an "N checks planned"
   count, and the code comment records that this distinction was added deliberately. It is a
   **capability gap, not a truthfulness violation**, and must not be reported as the latter.

---

## 6. Material findings requiring owner attention

### 6.1 The collaboration bridge cannot issue GO on a CHECKPOINT (blocking for ABC)

`reviewer_driver.py:180-192` refuses a `CHECKPOINT → GO` unless a trusted CI/test manifest exists for
that exact SHA **and** reports success. **Re-proven:** `record_gate_manifest` has no caller anywhere
outside `tests/test_collaboration_manifest.py`. Nothing writes the manifest.

Consequence: a CHECKPOINT can only ever escalate to `NEEDS_OWNER` with *"no trusted CI/test manifest
for this exact SHA"*. QUESTION and PROPOSAL flows work. This directly affects the ABC plan to use the
bridge for material internal gates. Fix is small — a producer that records CI conclusion + test/audit
results per SHA — and belongs in B0/B1.

### 6.2 Merge governance is prose, and the prose conflicts

`CLAUDE.md` records a standing merge authorization (autonomous merge after exact-head GO + green CI);
`.github/copilot-instructions.md:68` says *"Never merge or push without explicit user authorization."*
Both are live instructions to agents. There is no machine-readable required-check configuration to
arbitrate. **Owner decision needed** on which is authoritative; then encode it.

### 6.3 Reviewer spend caps never bind

`_cost_from_usage` prices tokens with `AIQA_REVIEWER_PRICE_PER_MTOK_IN/_OUT`, both defaulting to `"0"`,
and **re-proven** to appear in no `.env.example` and no doc. So `per_thread_usd=2.0` and
`daily_usd=10.0` are inert; only the call caps (12/thread, 100/day) actually bound spend. Corroborated
by live observation during TASK 0: the ledger recorded `usd: 0.0` against 1503 real tokens. The code is
honest about this ("never a fabricated flat charge") — the gap is that the USD caps read as protection
they do not provide.

### 6.4 SECURITY — the "read-only Observer" transport is not read-only

**Re-proven end to end:**

- `integrations/mcp/server.py:194` — `ALL_TOOL_SCHEMAS = _TOOL_SCHEMAS + OBSERVER_TOOL_SCHEMAS`.
- `build_server()` publishes that full catalog; **both** stdio and `build_http_app` use it. The HTTP
  docstring's assurance that "the Observer tools remain read-only" is true but incomplete — the 7
  planning tools ride the same transport.
- `apply_self_healing_fixes` reads `approve_code_modification` and `outputs_root` **from caller-supplied
  params** (`tool_handlers.py:434-438`), and with `dry_run=false` calls
  `apply_proposals(..., write_files=True)` → `spec_path.write_text(...)` (`core/flaky_test_analyzer.py`).
- `_check_blocked_params` only rejects credential-*named* parameters; it does not gate write intent.

So the approval for a **file-writing** tool is a boolean supplied by the remote caller, on the same
surface documented as read-only. The live tunnel process runs `tools/run_mcp_server.py` in **stdio**
mode, bridged outward — the same catalog.

**Honest severity.** This is *not* unauthenticated RCE: the HTTP transport requires a bearer token, the
tunnel is outbound-only with no public inbound port, the writes are `HEAL-<id>` comments inserted into
spec files under a project directory, and the remote party is the owner's own controller. It is a
**least-privilege / trust-boundary defect**: the realistic threat is prompt injection reaching the
remote Observer (which reads QA data derived from untrusted websites) and inducing a write call.

**Recommended (B0, small):** adopt the pattern the relay server already uses — a role/transport-scoped
tool catalog (`review_relay_server.py:126-129` proves the pattern in-repo), and read approval state
from operator-side storage instead of caller-supplied booleans. Until then the exposure is bounded by
the bearer token and the tunnel's outbound-only shape.

Two smaller contradictions in the same area: `observer_export_ai_review_bundle` **writes files** (path-
confined and bounded, but three separate places claim no write tools exist), and
`observer_get_system_readiness(deep=true)` **launches Chromium and network probes** with no approval
flag — its own schema string says so.

---

## 7. Residuals / not analysed

- The five V3 design documents (absent from the repo) — **NOT_ANALYSED**.
- `core/quality_gate.py` beyond line 90, and `run_validation.py` function bodies beyond the outline,
  were not read line by line.
- Several recon greps were output-capped; every conclusion carried into this document was re-proven
  with a targeted uncapped command or a full file read.
- No runtime behaviour was executed for this analysis. Every claim is static-evidence based, except
  those explicitly corroborated by TASK 0/0.1 live observation (§6.3).

---

## A4 addendum — evidence-model convergence, as actually found (2026-09-18)

The A4 slice re-proved §1.2 before touching anything, and the picture is different from the one
recorded above in two ways that changed the work:

1. **One of the three `EvidenceItem` classes is dead.** `core/schemas/execution_summary.py:EvidenceItem`
   (and its container `ExecutionSummary`) has **zero** product consumers — it is re-exported from
   `core/schemas/__init__.py` and constructed by one schema test, nothing else. It was deprecated, not
   adapted, and a guard test fails if product code starts using it again.
2. **The count above was of the exact class name, not the concept.** Beside the three `EvidenceItem`
   classes, `core/` also holds `BrowserExecutionEvidence` (a live per-item evidence record, adapted
   below), and `QAEvidenceItem` (report aggregate), `MediaEvidenceItem` (media metadata) and
   `EvidenceCoverageItem` (coverage aggregate), which are not per-item records and needed no adapter.
   A convergence claim that did not name them would have been incomplete.

What A4 did, and did not do:

- **Canonical record = `core/schemas/evidence.py:EvidenceRecord`.** It was already the shape on the
  delivery path (`core/evidence_manager.py`, `core/schemas/work_delivery.py`) with fail-closed
  client-safety defaults. It was **extended** with `content_hash` and `verification_status` (both
  default to "not proven"); persisted records from before the extension load unchanged. Its declared
  `EVIDENCE_TYPES` vocabulary — which was never enforced — was widened to cover every type an adapter
  can emit, and a test pins that.
- **Three adapters, no fourth model:** `core/schemas/evidence_adapters.py` adapts the client-work
  and Scout pipeline shapes onto the record — and a third, `BrowserExecutionEvidence`
  (`core/schemas/browser_execution.py`), which the A1 count could not see because its name carries
  neither `Item` nor `Record`. A structural scan (an `evidence_type` field plus a path field) found
  it after the first two adapters were written; the guard test now runs both scans. Client visibility is granted only when the source proves
  both sanitisation and client clearance; nothing (hash, timestamp, status) is invented; origin is
  preserved in `notes`.
- **`ScoutFinding` -> `Finding`** lives in the existing adapter home `core/risk/finding_adapters.py`.
  Only `VERIFIED` becomes `open`; `REJECTED` becomes `false_positive`; everything else is
  `needs_review`. Evidence references cross only when the Scout finding is client-safe, and the
  withholding is tagged. Scout categories with no canonical equivalent (`seo`, `structured_data`,
  `coverage`) map to `unknown` with the original preserved as a tag — extending `FindingCategory`
  touches risk scoring and client rendering and is recorded here as an `EXTEND` candidate, not done.
- **Not done:** the four evidence writers over different roots (§1.2) are untouched; the producers
  still write their own shapes and the adapters are available at the read/delivery boundary. Moving
  the writers onto `EvidenceRecord` directly is the next convergence step and belongs with the
  Assurance Core persistence work it was a precondition for.

---

## Related

- `docs/ENGINEERING_EXECUTION_POLICY.md` — how work is executed
- `docs/PHASE_CONTRACTS.md` — authoritative surface boundaries
- `docs/DIRECT_COLLABORATION_DRIVER.md` — the engineering bridge
- `docs/architecture/SCOUT_RUNTIME_V1.md` — implemented Scout boundaries
