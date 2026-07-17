# MCP & VS Code Integration Matrix (Final Phase II)

**Honest status:** a manifest entry is **not** a working integration. Every server in
`config/mcp_servers.v2.yaml` is **disabled by default**, read-only by default, and at most
**declared_in_manifest** — none is health-checked, tools-discovered, configured, sandbox-accepted,
or live-accepted. There is no live MCP call in the product or in CI.

**Windows security boundary.** The primary development host is Windows; VS Code MCP sandboxing is
**not** relied on as the security boundary. The boundary is: disabled-by-default servers, tool
allowlists, read-only defaults, environment-secret references (never values), version pinning,
process isolation, domain/filesystem allowlists, the Final Phase II approval gates, and audit
logging.

**Agent vs Factory.** Servers marked `developer_agent_only` are usable by the VS Code / Claude
agent **only** — they are **not** available to the standalone Factory process. Assuming otherwise
is a confirmed adversarial defect (enforced by `assert_available_to_factory` and tested).

## Integration classes

`developer_agent_only` · `optional_factory_runtime` · `external_communication` ·
`deployment_only` · `post_v2_candidate`

## Server matrix

| Server | Publisher | Class | Capabilities | Default mode | Readiness | Factory? | Approval | Fallback |
|---|---|---|---|---|---|---|---|---|
| Context7 | Upstash | developer_agent_only | read | read-only | declared | no | no | internal docs lookup |
| Playwright MCP | Microsoft | developer_agent_only | read/write | read-only | declared | no | yes | deterministic Scout Playwright/CLI |
| Chrome DevTools MCP | Google | developer_agent_only | read | read-only | declared | no | no | Scout chrome_perf_observation |
| GitHub MCP | GitHub | developer_agent_only | read/write | read-only | declared | no | yes (writes) | `gh` CLI |
| Postman MCP | Postman | post_v2_candidate | read/write | read-only | declared | no | yes | api_contract_importer |
| Sentry MCP | Sentry | post_v2_candidate | read | read-only | declared | no | yes | — |
| BrowserStack MCP | BrowserStack | post_v2_candidate | read/write (paid) | read-only | declared | no | yes + cost budget | local Chromium |
| Atlassian Rovo MCP | Atlassian | post_v2_candidate | read/write | read-only | declared | no | yes | — |
| Resend | Resend | external_communication | read/send | read-only | declared | no | yes (FP II gates) | FP II RealEmailAdapter |
| Gmail | Google | external_communication | read/send | read-only | declared | no | yes (FP II gates) | FP II approval gates |
| Google Drive | Google | post_v2_candidate | read | read-only | declared | no | yes | local file import |
| Cloudflare | Cloudflare | deployment_only | read/write | read-only | declared | no | yes | none (no cloud in v2.0) |
| Supabase | Supabase | post_v2_candidate | read/write | read-only | declared | no | yes | local SQLite memory |
| Stripe | Stripe | post_v2_candidate | read/financial | read-only | declared | no | yes | manual commercial events |

Priority integrations (GitHub read-only repos/PRs/actions/code_security; Postman minimal+code;
Sentry HITL analysis; BrowserStack optional paid with strict budgets; Playwright/DevTools agent-side
diagnostics that do **not** replace the Scout runtime; Atlassian approval-gated; Resend/Gmail only
through the FP II approval + revalidation gates) are captured in the manifest with read-only defaults
and approval requirements. None is enabled.

## Snapshots

`scout mcp-audit --output <dir>` writes (from the manifest, honestly labelled — no live discovery):

- `MCP_DISCOVERY_SNAPSHOT.json` — declared toolsets only (`live_tools_list: false`).
- `MCP_HEALTH_AND_READINESS.json` — per-server validation + factory-readiness (agent-only →
  `unavailable_to_factory_process`).
- `MCP_CAPABILITY_GAP_REPORT.json` — the gap from `declared_in_manifest` to live for each server.

## VS Code workspace

`.vscode/extensions.json` recommends (installation is never automatic): GitHub Copilot, Playwright
Test for VS Code, Python, Pylance, Ruff, SonarQube for IDE, Snyk Security, Container Tools, GitLens.
`.vscode/mcp.json.example` is an **example** (not loaded) with all servers disabled and env-ref
credentials.

## Adversarial guards (tested)

Malformed tool schema; duplicate/namespaced tools; excessive tool count; write tool in read-only
mode; external-communication/financial tool without approval; secret leakage from MCP output; prompt
injection in MCP output (treated as untrusted data, never instructions); partial/timeout result
never treated as success; recursive MCP loops; version mismatch; and the agent-only-assumed-by-
Factory defect. No live paid call, browser-cloud session, ticket/repository write, message send, or
financial operation is required by CI.
