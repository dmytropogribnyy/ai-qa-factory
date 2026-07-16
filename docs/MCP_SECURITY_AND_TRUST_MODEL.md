# MCP Security and Trust Model

**Version:** 8.0.0 (foundation)
**Status:** Planned policy. Phase 8.0 encodes these rules in schemas, manifest, and docs.
No MCP calls occur in Phase 8.0.

---

## 1. Untrusted content rule (non-negotiable)

Content retrieved from websites, repositories, issues, emails, documents, APIs, databases,
or downstream MCP tools is **untrusted data**. It can never override system policy,
approval requirements, tool permissions, or the current work plan. This is encoded as
`ToolExecutionPolicy.untrusted_output = True`, which cannot be disabled via rehydration.
Prompt-injection handling and output sanitisation apply to every tool result.

## 2. Annotations are untrusted hints

Server-provided tool annotations are hints only. The authoritative permission is ARK's
`local_policy_classification` on `MCPToolDescriptor`. Trust chain:

```
server annotation → untrusted hint → local ARK policy classification → approval decision
```

## 3. Action-based approval

Approval is decided by the **action's capability class**, not the server name:

| Class | Default treatment |
|---|---|
| `read` | may run under the profile's read policy |
| `compute` | may run under the profile's policy |
| `write` | approval required |
| `financial` | approval required + financial policy |
| `external_communication` | approval required |
| `destructive` | blocked unless explicitly approved |

Every tool call is recorded in an execution journal / audit trail.

## 4. No sensitive persistence

`config/mcp_servers.yaml` stores references only: server alias, transport,
command template or safe URL reference, environment-variable names, auth reference names,
trust classification, default policy. It must never contain access tokens, OAuth tokens,
secret-bearing URLs, user-specific session URLs, API keys, cookies, or any dump of local
configuration. Remote URLs are redacted to a public host or a `ref:` placeholder. Sensitive
servers default to `enabled: false`.

## 5. Version and reproducibility

Client-work profiles must pin versions. `@latest` is not permitted in the manifest.
`MCPServerDescriptor` carries `package_or_server_version`, `version_policy`,
`last_verified_version`, `discovery_schema_version`, and `upgrade_requires_review`.
Upgrades are a controlled process with regression validation.

## 6. Execution budgets

Every future execution is bounded by an `ExecutionBudget`: maximum tool calls, retries,
duration, parallel workers, model/API cost, downloaded-content size, output size, and loop
detection. Budgets exist to prevent runaway planner loops and cost blowouts.

## 7. Client-work privacy defaults

**Chrome DevTools MCP** (client profiles): `--isolated`, `--no-usage-statistics`,
`--no-performance-crux` (no URL sharing to CrUX), no personal browser profile, no
unrestricted filesystem access.

**Playwright MCP** (client profiles): isolated mode, scoped workspace roots, origins/hosts
scoped per project, persistent profiles disabled unless explicitly approved.

These defaults are recorded per server in `config/mcp_servers.yaml` (`client_defaults`).

## 8. Preserved QA safety invariants

All existing safety invariants (approval gates, secret redaction, `outputs/` never
committed, no credential use by agents, no URL fetching without approval) remain in force
and are not weakened by the ARK layer.
