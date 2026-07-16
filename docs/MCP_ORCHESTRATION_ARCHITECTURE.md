# MCP Orchestration Architecture

**Version:** 8.0.0 (foundation)
**Status:** Planned. Phase 8.0 defines schemas + manifest only. Live discovery and any
MCP tool invocation are planned for Phase 8.3+ and are **not implemented** yet.

---

## Purpose

ARK becomes both:
- an **MCP server** for Claude, Codex, and other clients (the existing
  `integrations/mcp/server.py` is preserved), and
- an **MCP client / orchestrator** that consumes downstream MCP servers as a
  capability transport.

MCP is a transport, not the intelligence. The intelligence is requirement
understanding, capability planning, routing, verification, and repair.

## Design goal: prefer ready tools, never reinvent the wheel

The Factory must make **maximum, effective use of existing MCP servers and tools**, and
must make **adding or building new capabilities flexible**. This is enforced structurally:

### Tool-selection preference order

For each required atomic capability, the ToolchainComposer selects a backend/tool in
this order:

1. **Ready MCP server** listed in the capability's `candidate_mcp_servers`
   (e.g. `web_navigation → playwright`, `dom_inspection → chrome-devtools`,
   `api_contract_analysis → context7`, `database_read → supabase`).
2. **Existing in-repo backend** (`existing_runner`, `playwright_cli`) when it is more
   deterministic or cheaper (e.g. repeatable CI regression).
3. **Build new** — only when no ready tool exists (capability has empty
   `candidate_mcp_servers` and no suitable runner). This becomes a deliberate,
   surfaced decision per capability, not a default.

Because `candidate_mcp_servers` and `candidate_backends` live in
`capabilities/atomic_capabilities.yaml`, "is there already a good tool for this?" is
answered by data, per capability — not re-decided in code.

### Adding a new MCP = a manifest entry, not code

A new downstream MCP server is added by appending one block to
`config/mcp_servers.yaml` (alias, transport, capability classes, version, default
policy) and, if it realises a new ability, mapping it under a capability in
`atomic_capabilities.yaml`. No orchestration code changes are required to register a
server. `MCPDiscovery` + `MCPRegistry` normalise any registered server into
`MCPServerDescriptor` / `MCPToolDescriptor`.

## Capability gap detection & MCP provisioning (planned, approval-gated)

The Factory and its agents must be able to **see and analyse all MCP servers, plugins,
and connectors** — configured, reachable, needing auth, unreachable, or known candidates
not yet configured — and to identify **which needed ones are missing**.

This is modelled by `core/schemas/capability_gap.py`:

- `CapabilityGapReport` — for a work packet, lists available servers + capabilities vs.
  required capabilities, and the resulting gaps.
- `CapabilityGap` — one required capability that is not currently satisfiable, classified
  as `no_tool_available`, `server_not_configured`, `server_unreachable`,
  `requires_auth_setup`, `requires_approval`, or `build_required`.
- `MCPRecommendation` — how to close the gap: `use_existing`, `configure_candidate`,
  `authenticate`, `repair`, or `build`.

Flow (planned): inventory (from the manifest + `known_candidate_not_configured` catalog and,
in Phase 8.3+, live discovery) → gap analysis against the plan's required capabilities →
recommendation. **Adding or connecting a server is never automatic.** It is surfaced as an
approval item and applied as a manifest edit (a write/external action), preserving the
"prefer ready tools, build only when nothing suitable exists" preference order above.

## Availability scope model (Phase 8.0 correction #1)

A server is classified by **five independent scopes** (see
`core/schemas/mcp_descriptor.py`):

| Scope | Meaning |
|---|---|
| `available_to_claude_agent` | invoked by the current Claude Code workspace |
| `available_to_factory_process` | the standalone ARK Python process can itself spawn (stdio) or connect (remote) |
| `requires_factory_auth_setup` | reachable by Claude but ARK cannot reuse Claude's OAuth/session |
| `configured_but_unreachable` | configured but failing health |
| `known_candidate_not_configured` | a candidate, not configured |

**Rule:** stdio (npx) servers are potentially usable by the standalone Factory after a
launch check. Cloud / HTTP-OAuth servers must not be assumed available to the Factory
process — Claude credentials and OAuth sessions are not exported or reused.

## Health inventory is not full tool discovery (correction #2)

- Phase 8.0/8.1: only server-level status is recorded
  (`MCP_CONFIGURED_SERVERS_SNAPSHOT.json`), derived from configuration + health checks.
- Phase 8.3: `MCPDiscovery` performs actual protocol discovery and writes an immutable
  `MCP_DISCOVERY_SNAPSHOT.json`. Expected tools are never copied from a server's README
  as if they had been discovered live.

## Discovery behaviour (planned, Phase 8.3)

- `tools/list` with pagination; `resources/list` / `prompts/list` only when advertised.
- Namespaced tool identifiers `<server>.<tool>`; duplicate names disambiguated.
- Track `notifications/tools/list_changed`.
- Schema validation; timeouts; graceful degrade when a server is unavailable.
- Immutable discovery snapshots for audit.

## ARK MCP high-level tool contract (correction #4)

ARK's own MCP interface exposes **orchestration** tools, not a one-to-one mirror of
hundreds of downstream tools. See `docs/AGENT_INTEROPERABILITY.md` for the tool list.
Downstream MCP calls remain internal implementation details recorded in the execution
journal. Direct passthrough/proxy mode is deferred and would require allowlists,
namespacing, schema validation, per-tool policy, audit logging, output sanitisation, and
protection against recursive MCP loops.

## Security and privacy

See `docs/MCP_SECURITY_AND_TRUST_MODEL.md`. Key points: annotations are untrusted hints;
local policy is authoritative; the manifest stores references only; Chrome DevTools and
Playwright client-work defaults enforce isolation and disable telemetry/CrUX sharing.
