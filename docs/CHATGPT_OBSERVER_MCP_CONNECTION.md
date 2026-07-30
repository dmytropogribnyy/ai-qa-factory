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

- **Local + Claude clients → stdio (works now).** Verified end-to-end.
- **ChatGPT → authenticated streamable-HTTP (BUILT + verified locally).** The existing server now also
  serves the SAME 26 tools over streamable-HTTP behind a **bearer token** (`AIQA_MCP_TOKEN`), bound to
  `127.0.0.1` by default — one logical implementation, no second server. Verified: an authorized
  client lists 26 tools and calls `observer_get_project_overview`; an unauthenticated request gets
  **401**. Report: `outputs/mcp_acceptance/MCP_HTTP_ACCEPTANCE.md`.
- **What Claude will NOT do automatically:** install a tunnel, open a public port, change the
  firewall, or log into your ChatGPT account. Exposing the loopback endpoint over a public HTTPS URL
  (a tunnel) and adding the connector in ChatGPT are **owner steps** (section M).

## C1. Run the authenticated HTTP endpoint (loopback)

```powershell
# set a bearer token for this session (this script never prints it):
$env:AIQA_MCP_TOKEN = [Convert]::ToBase64String((1..24 | % { Get-Random -Max 256 }))
powershell -ExecutionPolicy Bypass -File tools\observer_mcp.ps1 -Action http-test   # verify
powershell -ExecutionPolicy Bypass -File tools\observer_mcp.ps1 -Action http         # serve on 127.0.0.1:8770/mcp
```

> **The Observer MCP endpoint is 8770. The operator Dashboard is 8765, and it is never the tunnel
> target.** The Dashboard authenticates nothing on its read paths — `_guard_mutation` covers
> state-changing endpoints only, so every GET is protected solely by the loopback bind. A tunnel
> terminates that bind locally, so exposing the Dashboard's port would serve findings, evidence,
> contacts and client packages to the internet with no credential in front of them.
> `AIQA_MCP_TOKEN` guards the MCP server; it cannot guard the Dashboard, which never reads it.

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

## J1. Autostart at Windows logon (Task Scheduler)

So the tunnel is up whenever you're logged in — no manual PowerShell, ChatGPT works without VS Code
open. The secret lives ONLY in the user env var (HKCU), never in git/scripts/task-args/logs.

```powershell
# one-time: store the key in the USER environment (value not echoed by this)
[Environment]::SetEnvironmentVariable('CONTROL_PLANE_API_KEY','<your key>','User')

# register + manage the autostart (idempotent)
powershell -ExecutionPolicy Bypass -File tools\observer_tunnel_autostart.ps1 -Action install
powershell -ExecutionPolicy Bypass -File tools\observer_tunnel_autostart.ps1 -Action start
powershell -ExecutionPolicy Bypass -File tools\observer_tunnel_autostart.ps1 -Action status
powershell -ExecutionPolicy Bypass -File tools\observer_tunnel_autostart.ps1 -Action restart
powershell -ExecutionPolicy Bypass -File tools\observer_tunnel_autostart.ps1 -Action stop
powershell -ExecutionPolicy Bypass -File tools\observer_tunnel_autostart.ps1 -Action uninstall
```
- Task **"AI QA Factory Observer Tunnel"**: at logon +20s, hidden, non-admin (Limited), single
  instance, restart-on-failure, working dir `C:\aiqa`.
- The task action runs `tools\tunnel-client.exe run --profile ai-qa-factory` directly, with
  `--log.file` pointing at
  `%LOCALAPPDATA%\AIQA-Observer-Tunnel\tunnel-client.service.jsonl`. Keeping the long-lived executable
  as the task action prevents its lifetime from being coupled to a PowerShell console/launcher.
  Task arguments contain no key. `tools\start_observer_tunnel.ps1` remains available for manual
  diagnostics only.
- Rollback: `-Action uninstall` removes the task (env var + tunnel profile left intact).

## K. Secrets

Never paste secrets into ChatGPT or this repo. The server reads no secrets for the read-only tools.
`AIQA_OUTPUT_ROOT` is a path, not a secret. Docs use placeholders only.

## L. Troubleshooting

- `mcp NOT installed` → `.\.venv\Scripts\python.exe -m pip install mcp`.
- `doctor` shows only 7 tools → old build; ensure `integrations/mcp/observer_handlers.py` is present.
- smoke `FAIL ... absolute_path` → update to this build (paths are relativized here).
- ParserError running the `.ps1` → run with `-ExecutionPolicy Bypass -File` as shown.

## M. Exact remaining ChatGPT owner-side actions

The authenticated HTTP endpoint already works locally (section C/C1). Only **three owner steps** remain:

**1. Publish a public HTTPS URL for the MCP endpoint (a tunnel).** No tunnel is installed; Claude
will not auto-install or expose one (it publishes your read-only QA data).

**Point it at the MCP server's own port — the default is `8770` — and never at the Dashboard.**
Confirm what is actually listening before you expose anything:

```powershell
# the MCP server must answer here, and the Dashboard must NOT be what you publish
Get-NetTCPConnection -LocalPort 8770 -State Listen | Select-Object OwningProcess
```

Get the exact tunnel command from that tool's **official docs / `--help`** (do not copy tunnel
commands from memory), e.g. a cloudflared *quick tunnel* (label it clearly **temporary** — not a
permanent production endpoint). Keep `AIQA_MCP_TOKEN` set: it is what makes the public URL require a
bearer token, and the MCP server refuses to start without it.

> **Why the port matters.** `8765` is the operator Dashboard, and it is **never the tunnel target**.
> The Dashboard has no authentication on read paths — its one guard covers state-changing endpoints,
> so every GET relies on the loopback bind alone. A tunnel terminates that bind locally, so anyone
> with the URL would receive findings, evidence, contacts and client packages.
> `AIQA_MCP_TOKEN` cannot protect it: the Dashboard never reads that variable.
>
> If you only need the reviewer to reach the Observer, prefer the outbound route in section J1 — the
> tunnel client spawns the MCP server over stdio and opens **no inbound port at all**, so there is
> nothing exposed to get wrong.

**2. Add the connector in ChatGPT.** In your ChatGPT account (labels vary by plan — use what you
actually see): **Settings → Apps / Connectors**, possibly under *Advanced Settings* / *Developer
mode* → *Create app / Create custom connector / Add MCP server*. Enter:
- **URL:** `https://<your-tunnel-domain>/mcp`
- **Auth:** Bearer token = your `AIQA_MCP_TOKEN` (paste it in the ChatGPT connector auth field —
  **never paste it into a normal chat message**).
Then **Scan / Refresh Tools** and confirm the `observer_*` tools appear. Enable the app in a new
conversation.

**3. Live acceptance.** Ask ChatGPT to call `observer_get_project_overview`, then
`observer_list_campaigns`, and confirm no write/control tool is offered. Only after ChatGPT itself
returns real state is the status **"ChatGPT Observer MCP connected and live-accepted."**

> Claude prepared and verified everything up to the tunnel + ChatGPT UI. Steps 1–2 are owner-only
> (they expose your data publicly and use your ChatGPT account); Claude does not perform them.
