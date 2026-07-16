# Product Vision 2026 — ARK / Capability-Driven AI Work & Delivery Factory

**Version:** 8.0.0 (foundation)
**Status:** Planned architecture — Phase 8.0 lays documentation and schema foundation only.
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

## Phase map (planned)

| Phase | Scope | State |
|---|---|---|
| 8.0 | Docs, schemas, manifests, tests (this) | foundation only |
| 8.1 | `main.py work` — planning-only artifacts | planned |
| 8.2 | Typed CapabilityRegistry + CapabilityPlanner | planned |
| 8.3 | MCPRegistry + live discovery + ToolPolicyEngine (discovery only) | planned |
| 8.4 | Read-only pilots: context7, Playwright, Chrome DevTools | planned |
| 8.5 | Universal EvidenceVerifier + DeliveryAssembler adapters | planned |
| 8.6+ | Controlled write integrations (approval-gated) | planned |

See `docs/UNIVERSAL_WORK_FACTORY.md` for the component architecture and
`docs/REUSE_MAP_PHASE8.md` for the exact reuse decisions.
