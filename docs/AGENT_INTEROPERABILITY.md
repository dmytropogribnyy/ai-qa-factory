# Agent Interoperability

**Version:** 8.0.0 (foundation)
**Status:** Planned. Phase 8.0 documents the contract; no runtime interop is implemented.

---

## Goal

One Factory, usable from multiple agents at once:
- Claude Code
- ChatGPT / Codex
- other MCP-compatible agents
- the local CLI

## Source of truth is artifacts, not chat history

Shared state must never live only in one agent's conversation history. The canonical
state is:

- structured JSON artifacts (`WORK_PACKET.json`, `CAPABILITY_PLAN.json`,
  `TOOLCHAIN_PLAN.json`, `MCP_CONFIGURED_SERVERS_SNAPSHOT.json`, …)
- Markdown human reports (`WORK_SUMMARY.md`, `APPROVALS_REQUIRED.md`, `NEXT_ACTION.md`)
- the project state store (`persistence` / `state`)
- the evidence index
- the execution journal
- git repository / worktree state

Any agent reads and writes through these artifacts under `outputs/<project_id>/`, so work
can hand off between Claude, Codex, and the CLI without shared in-memory state.

## ARK MCP high-level tool contract (planned)

ARK remains an MCP server and adds high-level **orchestration** tools (not a mirror of
downstream tools):

- `factory_health`
- `ingest_work`
- `build_work_packet`
- `plan_capabilities`
- `discover_available_capabilities`
- `analyze_capability_gaps`      # see all MCP/plugins/connectors + what is missing
- `propose_mcp_additions`        # recommend candidates to add (approval-gated manifest edit)
- `compose_toolchain`
- `prepare_workspace`
- `generate_worker_tasks`
- `request_execution_approval`
- `execute_approved_step`
- `collect_evidence`
- `verify_result`
- `assemble_delivery`
- `explain_decision`

The existing seven QA tools in `integrations/mcp/server.py` are preserved for
compatibility. Downstream MCP calls are internal implementation details captured in the
execution journal.

## Independent verification across agents

When implementation is delegated to an external worker (e.g. Codex), the EvidenceVerifier
evaluates **only the artifacts and evidence**, never the worker's self-report. A coding
agent cannot approve its own work; verifier state is independent of implementer state.
