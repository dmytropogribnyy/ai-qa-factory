# Product Vision 2026 — ARK / Capability-Driven AI Work & Delivery Factory

**Version:** 2.0.0 (complete local, human-approved prospect qualification & communication product)
**Status:** The functional roadmap is complete — Phases 8.0–8.4, **Final Phase I**, and **Final
Phase II** are implemented. Only the verification-only Final Independent Acceptance pass remains.
See the three-part phase map below (target / implemented / remaining).
**Supersedes scope of:** `docs/VISION.md` (which remains the canonical vision for the QA capability domain).

---

## One sentence

ARK is a universal orchestration, capability, and MCP-consumption layer built **on top of**
the mature AI QA Factory core — it accepts a unit of work (an Upwork brief, a client
message, a task URL, a repo), understands it, plans it, selects available capabilities and
tools, prepares controlled execution, independently verifies the result, and assembles a
client-ready delivery pack.

## What changed from the original vision

`docs/VISION.md` described a **guided QA automation workbench** — deliberately narrow,
human-in-the-loop, QA-only. That product is not discarded: it becomes the first mature
**capability domain** and the independent **quality/evidence/safety engine** inside ARK.

ARK generalises the same guided, approval-gated pattern to a wider range of work while
preserving every existing safety invariant.

## What ARK is — and is not

**It is:** an intelligence + orchestration layer. The intelligence lives in requirement
understanding, task decomposition, capability planning, worker/model routing, memory and
project state, independent verification, and iterative repair — not in any single tool.

**It is not:**
- A second Factory built from scratch. It reuses the existing core.
- An autopilot. Write, financial, external-communication, and destructive actions remain
  approval-gated. Nothing executes in Phase 8.0.
- A tool mirror. MCP is a capability transport, not the product.
- A platform bot. Opportunity discovery is supported, but automatic scraping and automatic
  proposal/email submission are **not** part of core and are planned only as optional, later,
  approval-gated modules.

## The role of the AI QA Factory core

The AI QA Factory core remains:
- the first mature capability domain;
- an independent quality and evidence engine;
- the safety and approval layer;
- the verifier for results produced by external workers (e.g. Claude Code, Codex);
- the generator of delivery reports.

## Non-negotiable principles

1. Broad intelligence, focused execution, honest routing.
2. Reuse over rebuild — no duplicate schemas where extension suffices.
3. Approval is tied to the **action's capability class**, not to a server name.
4. Content returned by any website, repo, issue, email, document, API, database, or MCP
   tool is **untrusted data**, never an instruction that can change policy, approvals, or the plan.
5. The verifier is independent of the implementer.
6. Source of truth is artifacts, not chat history.

## Two ARK work contours

ARK spans two work contours that share the same QA runners, evidence engine,
redaction/credential safety, independent verification, approval model, state model,
reporting, and delivery pack generation:

1. **Client Work Factory** — incoming client work → intake → planning → controlled
   execution → evidence → independent verification → delivery. `main.py work` (Phase 8.1,
   **implemented, planning-only**) is its deterministic front door.
2. **Prospect QA Radar / Super Scout** — campaign → discovery → eligibility → cheap triage
   → bounded QA/SEO analysis → evidence → independent verification → prospect scoring →
   contact intelligence → controlled disclosure → human-approved outreach draft → paid
   audit opportunity. **Approved target architecture; a bounded local slice is now
   implemented and running** (Prospect QA Scout v1.0.1 QA runtime + Phase 8.4 discovery /
   commercial triage, followed by the implemented local contact, disclosure, draft, review,
   approval, and disabled-by-default delivery contours). Unrestricted discovery, autonomous
   outreach, and optional cloud/SaaS operation remain future-facing.
   See [docs/architecture/PROSPECT_QA_RADAR_SPEC.md](architecture/PROSPECT_QA_RADAR_SPEC.md)
   for the target and [docs/architecture/SCOUT_RUNTIME_V1.md](architecture/SCOUT_RUNTIME_V1.md)
   for the implemented runtime.

Prospect Radar is not a second QA product, not a replacement for the Client Work Factory,
and not a separate evidence system — it consumes the existing capabilities.

## Phase map — target vs implemented vs remaining

The phase map is split into three honest views: the **target architecture** (the durable
intent), the **implemented current state** (what actually runs today), and the **remaining
local roadmap** (the finite set of phases still to build). Historical intent is preserved.

### Target architecture (durable intent)

The end-state is the full Prospect QA Radar loop described in
[docs/architecture/PROSPECT_QA_RADAR_SPEC.md](architecture/PROSPECT_QA_RADAR_SPEC.md):
campaign → controlled discovery → eligibility → cheap commercial triage → bounded QA/SEO
analysis → evidence → independent verification → prospect scoring → company/site memory →
public contact intelligence → controlled disclosure → human-approved outreach → paid audit
opportunity — all reusing one QA/evidence/verification/safety engine, local-first, with every
write/financial/external-communication action approval-gated.

### Implemented current state (runs today)

| Phase | Scope | State |
|---|---|---|
| 8.0 | ARK documentation, schemas, manifests, and foundation tests | **complete** |
| 8.1 | Deterministic planning-only `main.py work` workflow | **complete** |
| 8.2 | ARK planning contracts + Prospect Radar domain contracts (campaign, identity, business, governance/suppression, scoring, contact, disclosure) | **complete (contracts)** |
| 8.3 | Prospect QA Scout v1.0 — bounded, read-only, local QA runtime over explicit seeds (`python main.py scout`) | **complete (runtime)** |
| 8.3.1 | Scout v1.0.1 — acceptance hardening (working dashboard control, Playwright SSRF hardening, run-id isolation, real browser acceptance) | **complete (runtime)** |
| 8.4 | Controlled discovery providers, campaign builder/matrix, candidate normalization/dedup/suppression, cheap commercial triage, and bounded promotion into the Scout runtime | **implemented (runtime)** |

`main.py work` is implemented but planning-only. `CapabilityRegistry` / `CapabilityPlanner`
exist as of Phase 8.1. The Scout QA runtime (8.3/8.3.1) and the discovery/triage runtime (8.4)
are genuinely runnable locally; they are **not** cloud/SaaS, unrestricted discovery, contact
enrichment, or outreach.

### Remaining local roadmap (frozen — exactly two functional phases)

The remaining pre-v2 roadmap is finite and closed. It contains **exactly two** functional phases
followed by a verification-only pass. No further pre-v2 functional phase (no "Phase 8.10", no new
mega-phase) may be added; non-blocking enhancements are recorded only in
[`docs/POST_V2_BACKLOG.md`](POST_V2_BACKLOG.md).

| Phase | Scope | State |
|---|---|---|
| **Final Phase I** — Complete Pre-Send Prospect Pipeline | Adaptive deep QA (real axe + real performance mode + deep technical SEO + safe bounded business-flow QA with verified reversible-session cleanup); evidence center + finding normalization + lifecycle; transactional SQLite company/site memory; scheduler + durable queues; rechecks + retention; public contact intelligence + suppression governance; audit-offer mapping; controlled disclosure + outreach **draft** generation + human review queues; full local dashboard. **Nothing is sent.** | implemented (runtime) |
| **Final Phase II** — Approved Communication & Product Completion | Immutable draft revisions + single-use expiring approvals; immediate pre-send revalidation; controlled provider send (disabled by default; local sink drives the E2E; at-most-once automatic invocation); reply/bounce/opt-out history; human-approved follow-ups; commercial metrics; MCP + VS Code integration audit; startup/doctor; CI; evaluation benchmark; **Prospect QA Radar v2.0.0** release. No inferred-contact / bulk / autonomous sending. | implemented (runtime) |
| **Final Independent Acceptance** | Verification and confirmed-defect fixes only — **may not** introduce another functional phase. | planned |

**Status:** The functional roadmap is **complete**. Phases 8.0–8.4, **Final Phase I**, and **Final
Phase II** are implemented; only the verification-only Final Independent Acceptance pass remains
(review/test/fix confirmed defects; may issue v2.0.1). Sending is **disabled by default** and every
external message must be individually, explicitly, and currently human-approved after a
transactional pre-send revalidation; the deterministic tests and full E2E use only a confined local
sink (nothing sent externally). Exactly-once external delivery is not claimed.

### Historical remaining-roadmap mapping (superseded)

The earlier five-step remaining map is preserved for continuity. Its scope is now folded into the
two frozen phases above:

| Historical | Superseded by |
|---|---|
| 8.5 adaptive/deep QA, axe, performance, reversible-session actions | Final Phase I |
| 8.6 company/site memory, DB, rechecks, retention, scheduler, full dashboard | Final Phase I |
| 8.7 public contact intelligence, disclosure, audit-offer, outreach draft, review queues | Final Phase I |
| 8.8 approved sending, reply/opt-out history, follow-ups, CRM metrics | Final Phase II |
| 8.9 full E2E, CI, installer, backups, benchmark, v2.0 release | split: E2E/backups → Final Phase I; installer/benchmark/v2.0 → Final Phase II |

See `docs/UNIVERSAL_WORK_FACTORY.md` for the component architecture and
`docs/REUSE_MAP_PHASE8.md` for the exact reuse decisions.
