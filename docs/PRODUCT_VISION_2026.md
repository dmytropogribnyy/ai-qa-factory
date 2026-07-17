# Product Vision 2026 — ARK / Capability-Driven AI Work & Delivery Factory

**Version:** 8.4.0 (discovery + commercial triage runtime)
**Status:** Target architecture with a growing implemented local runtime — Phases 8.0–8.4 are
implemented (8.2 contracts; 8.3/8.3.1/8.4 runtime). Phases 8.5–8.9 remain planned. See the
three-part phase map below (target / implemented / remaining).
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
   commercial triage). Contact intelligence, disclosure, and outreach remain future-facing.
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

### Remaining local roadmap (finite)

| Phase | Scope | State |
|---|---|---|
| 8.5 | Adaptive/deep QA: axe accessibility, Lighthouse (or an honest existing performance equivalent), traces/video where justified, synthetic personas, bounded reversible-session actions with verified cleanup | planned |
| 8.6 | Company/site memory: a transactional local database, rechecks/change detection, retention/storage manager, scheduler/queues, and the full operational dashboard | planned |
| 8.7 | Public contact intelligence: suppression/contact provenance, disclosure manifests, audit-offer mapping, outreach **draft** generation, human review queues — **no automatic send** | planned |
| 8.8 | Explicitly human-approved sending: reply/bounce/opt-out history, follow-up controls, CRM/commercial metrics — no inferred-contact sending, no bulk spam behavior | planned |
| 8.9 | Full local E2E, CI, startup/installer, backups/crash recovery, an evaluation benchmark, and the final Prospect Radar v2.0 release | planned |

**Status:** Phases 8.0–8.4 are implemented (8.2 as contracts; 8.3/8.3.1/8.4 as runtime).
Contact discovery, disclosure manifests, and any outreach remain unimplemented and are gated to
Phases 8.7–8.8 with human approval. No sending, contact enrichment, or external side effects
exist in the current runtime.

See `docs/UNIVERSAL_WORK_FACTORY.md` for the component architecture and
`docs/REUSE_MAP_PHASE8.md` for the exact reuse decisions.
