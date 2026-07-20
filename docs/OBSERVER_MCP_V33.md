# Observer MCP — read-only project observability (v3.3)

A **thin, read-only** adapter that exposes the existing `core.scout.observer_api.ObserverAPI` as
MCP tools on the **existing** `qa-factory` MCP server (`integrations/mcp/server.py`). No second
server, no second data model — the same persisted source-of-truth the Dashboard uses. All tools are
read-only, secret-redacted, evidence-root path-confined, and bounded. **No control/write tools in
this increment.**

## Local startup

```powershell
pip install mcp                       # transport dependency (optional; handlers work without it)
$env:AIQA_OUTPUT_ROOT = "D:\1QA AI\ai-qa-factory\outputs"   # server-side root (NOT a tool arg)
python tools/run_mcp_server.py --list-tools                 # 26 tools: 7 planning + 19 observer
python tools/run_mcp_server.py                              # start stdio MCP server
```

The project/output root is configured **server-side** via `AIQA_OUTPUT_ROOT` (default `outputs`).
It is never supplied as an unrestricted tool argument.

## MCP client configuration

Claude Code / Claude Desktop / VS Code (`mcpServers`):

```json
{
  "mcpServers": {
    "qa-factory": {
      "command": "python",
      "args": ["tools/run_mcp_server.py"],
      "env": { "AIQA_OUTPUT_ROOT": "D:\\1QA AI\\ai-qa-factory\\outputs" }
    }
  }
}
```

## Read-only tool catalog

| Tool | Purpose |
|------|---------|
| `observer_get_project_overview` | campaigns + analyzed-site counts |
| `observer_get_system_readiness` | readiness probes (`deep=true` launches Chromium + network) |
| `observer_get_release_readiness` | release-readiness summary |
| `observer_get_storage_status` | evidence storage usage |
| `observer_list_campaigns` | paginated campaigns + run state + counters |
| `observer_get_campaign` / `observer_get_run_progress` | campaign snapshot / progress |
| `observer_get_run_stop_reason` | exact stop reason |
| `observer_get_updates_since` | **incremental event feed** since a cursor index |
| `observer_list_targets` / `observer_get_target` | analyzed-site history / target detail + brain |
| `observer_get_target_test_plan` / `observer_get_target_decision_history` | plan / decision trail |
| `observer_list_findings` / `observer_get_finding` | campaign findings |
| `observer_get_evidence_manifest` / `observer_get_evidence_item` | evidence (relative refs; item = metadata + sha256) |
| `observer_get_activity_log` | paginated event log |
| `observer_export_ai_review_bundle` | write campaign-scoped JSON+MD bundle, return paths + integrity |

## Permission model

- **Read-only by default.** No control/write MCP tools exist in this increment.
- Secrets (Tavily key, tokens, cookies, credentials) are **redacted** by ObserverAPI.
- Evidence access is **path-confined** to the output root; traversal returns a structured error.
- Outputs are **bounded** (pagination + max event window + max evidence-item bytes).
- Errors are structured (`{"status":"error","message":...}`) — no tracebacks, no secrets.
- **Never exposed:** shell/PowerShell/SQL, arbitrary filesystem, browser control, command
  execution, environment variables, tokens, cookies, credentials.

## Evidence export (MCP-independent fallback)

If MCP is not yet connected, call `ObserverAPI.export_ai_review_bundle(campaign_id)` (or the
Dashboard **Export evidence** action) to produce `outputs/scout/_bundles/<id>/AI_REVIEW_BUNDLE.json`
+ `.md` (campaign-scoped, redacted, relative refs, integrity sha256). An external assistant can
review a run from that file alone.

## Secure remote connection

Bind local by default. For remote access use an approved secure tunnel (HTTPS/authenticated MCP
tunnel) — never expose the whole Dashboard publicly to support MCP. Keep `AIQA_OUTPUT_ROOT` scoped
to the project output dir.

## Limitations by client

- **Claude Code / Desktop / VS Code:** supported via the stdio server config above.
- **ChatGPT custom app:** requires the operator/workspace to configure an MCP connection per the
  user's ChatGPT plan; not vendor-coupled. Connection is an **operator/client configuration step**,
  not implemented here.

## MCP status (honest)

1. **MCP server implemented** — yes (existing `qa-factory` stdio server, extended additively).
2. **Observer tools exposed** — yes (19 read-only tools; original 7 planning tools regression-safe).
3. **Compatible MCP client smoke-tested** — handler/dispatch/catalog verified deterministically;
   full stdio transport requires `pip install mcp`.
4. **ChatGPT connection** — still requires operator/client configuration (not automatable here).

## Troubleshooting

- `--list-tools` shows only 7 tools → old build; ensure `observer_handlers` is importable.
- Observer tools return `queued`/empty → no campaign under `AIQA_OUTPUT_ROOT`; check the path.
- `ImportError: mcp` on start → `pip install mcp` (handlers/tests work without it).
- Evidence item `error: path escapes the output root` → the `ref` must be relative to the output root.
