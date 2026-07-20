# Connecting AI QA Factory (read-only Observer MCP) to ChatGPT — operator guide

Written for the Windows operator. It covers what is already done, what runs locally, the transport,
exact PowerShell commands, and the **owner-only** ChatGPT steps.

> **Honest boundary:** Claude prepared the server, the local transport, and the smoke test. **Adding
> and approving the custom MCP inside your ChatGPT account is an owner-only action.** Do not consider
> ChatGPT "connected" until ChatGPT itself successfully invokes `observer_get_project_overview`.

## A. What is already implemented (verified)

- `core/scout/observer_api.py` — read-only Observer over the same persisted state the Dashboard uses.
- 19 read-only Observer MCP tools on the **existing** `qa-factory` MCP server (`integrations/mcp/`),
  alongside the 7 legacy planning tools = **26 tools** total.
- Real **stdio transport verified**: `python tools/mcp_smoke.py` connects as a real MCP client and
  calls the tools (report: `outputs/mcp_acceptance/MCP_CONNECTION_ACCEPTANCE.md`). No secrets, no
  absolute paths, no control/write tools.
- Security: `campaign_id` confinement, evidence-root confinement, secret redaction, relative-only
  paths, structured errors (no tracebacks).

## B. What runs locally

The **stdio** MCP server: `python tools/run_mcp_server.py`. MCP clients (Claude Desktop / Claude
Code / Cursor) **spawn this themselves** — there is no long-lived daemon.

## C. Transport selected

- **Local + Claude clients → stdio (works now).** stdio is the safest supported transport and is
  already verified end-to-end.
- **ChatGPT → requires a REMOTE transport.** ChatGPT cannot connect to a local stdio process. No
  tunnel client (cloudflared/ngrok) is installed on this machine, and Claude will **not** auto-install
  one, open a public port, or change the firewall. Preparing the remote endpoint is an owner step
  (see section M). The **one logical tool implementation** (ObserverAPI → Observer handlers) is reused
  regardless of transport — a remote bridge must wrap the *existing* stdio server, never reimplement it.

## D. Prerequisites

```powershell
# from the repo root: D:\1QA AI\ai-qa-factory
.\.venv\Scripts\python.exe -m pip install mcp        # transport dependency (one-time)
```

## E. Exact PowerShell commands (the helper)

```powershell
powershell -ExecutionPolicy Bypass -File tools\observer_mcp.ps1 -Action doctor   # checks + tool list
powershell -ExecutionPolicy Bypass -File tools\observer_mcp.ps1 -Action list     # tool catalog
powershell -ExecutionPolicy Bypass -File tools\observer_mcp.ps1 -Action test     # REAL stdio smoke
powershell -ExecutionPolicy Bypass -File tools\observer_mcp.ps1 -Action start     # manual server (debug)
```
Optional: set the data root the Observer reads (default `<repo>\outputs`):
```powershell
$env:AIQA_OUTPUT_ROOT = "D:\1QA AI\ai-qa-factory\outputs"
```

## F. Expected successful output

- `doctor` → prints repo/python/output-root, `mcp installed`, and **26 tools (7 planning + 19 observer)**.
- `test` → `[mcp-smoke] PASS ... tools=26 observer=19 leaks=none` and writes the acceptance report.

## G-J. Connect / health / stop / update (Claude clients — works today)

Add to your MCP client config (Claude Desktop: `%APPDATA%\Claude\claude_desktop_config.json`;
Claude Code: `~/.claude.json`; Cursor: `~/.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "qa-factory": {
      "command": "D:\\1QA AI\\ai-qa-factory\\.venv\\Scripts\\python.exe",
      "args": ["D:\\1QA AI\\ai-qa-factory\\tools\\run_mcp_server.py"],
      "env": { "AIQA_OUTPUT_ROOT": "D:\\1QA AI\\ai-qa-factory\\outputs" }
    }
  }
}
```
- **Health:** `-Action doctor` / `-Action test`.
- **Stop:** stdio servers exit with their client; there is no daemon to stop.
- **Update after repo changes:** none needed — the client re-spawns the server each session; just
  re-run `-Action test` to reconfirm.

## K. Secrets

Never paste secrets into ChatGPT or this repo. The server reads no secrets for the read-only tools.
`AIQA_OUTPUT_ROOT` is a path, not a secret. Docs use placeholders only.

## L. Troubleshooting

- `mcp NOT installed` → `.\.venv\Scripts\python.exe -m pip install mcp`.
- `doctor` shows only 7 tools → old build; ensure `integrations/mcp/observer_handlers.py` is present.
- smoke `FAIL ... absolute_path` → update to this build (paths are relativized here).
- ParserError running the `.ps1` → run with `-ExecutionPolicy Bypass -File` as shown.

## M. Exact remaining ChatGPT owner-side actions

ChatGPT needs a **remote** MCP endpoint. Two supported owner paths (pick per your ChatGPT plan/UI):

1. **Reuse an existing remote MCP/tunnel** you already used with this ChatGPT account, pointed at a
   bridge that runs the existing stdio server (e.g. a stdio→HTTP MCP bridge). Confirm the exact
   command from that tool's official docs / `--help` — do not copy commands from memory.
2. **Expose the existing stdio server over a temporary authenticated HTTPS MCP endpoint** using an
   official stdio→HTTP MCP bridge + a tunnel (label it clearly *temporary*, never an unauthenticated
   public port). Then, in ChatGPT:
   - open **Settings → Apps / Connectors** (labels vary: *Advanced Settings*, *Developer mode*,
     *Create app / Create custom connector*, *MCP server / Tunnel connection*);
   - add the AI QA Factory MCP endpoint;
   - **Scan / Refresh Tools** and confirm the `observer_*` tools appear;
   - enable the app in a new conversation.

Then the **live acceptance**: ask ChatGPT to call `observer_get_project_overview`, then
`observer_list_campaigns`, and confirm no write/control tool is available. Only after ChatGPT itself
returns real state is the status **"ChatGPT Observer MCP connected and live-accepted."**

The exact UI labels depend on what your ChatGPT plan currently shows — use the options actually
visible in your account as authoritative.
