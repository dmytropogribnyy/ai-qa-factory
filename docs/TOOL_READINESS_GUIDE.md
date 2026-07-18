# Tool Readiness Guide

See honest tool readiness any time:

```powershell
python main.py tool-status          # human-readable table
python main.py tool-status --json   # machine snapshot
```

or open the dashboard **Tool Readiness** page (`/tools`).

## Availability domains

- **INTERNAL_RUNNER** - built into the repo (e.g. the Playwright browser acceptance, the API
  runner). Ready out of the box.
- **LOCAL_FACTORY_TOOL** - a local binary the standalone runtime uses (git, gh, python, ruff, node,
  playwright). Health-checked by presence on PATH.
- **CLAUDE_SESSION_TOOL** - an MCP available to Claude Code in your IDE session (e.g. GitHub MCP,
  Context7, Chrome DevTools MCP). Shown as `declared` here; connect it in Claude Code (`/mcp`) to use
  it. A ChatGPT/Claude connector is **not** a local Factory credential and is never reused as one.
- **EXTERNAL_SERVICE_REQUIRES_SETUP** - needs independent local authorization (Sentry, BrowserStack,
  Atlassian, Postman, Gmail send).

## Readiness ladder (honest)

`declared` -> `available-in-session` -> `configured` -> `authenticated` -> `health-checked` ->
`tools-discovered` -> `fixture-tested` -> `sandbox-accepted` -> `live-accepted`; plus `unavailable`,
`blocked-by-auth`, `blocked-by-policy`. A manifest entry is **never** called a working integration,
and nothing is `live-accepted` without recorded evidence.

## Missing tools

Each missing tool shows one clear setup line and a **fallback** (e.g. Sentry -> use supplied logs;
BrowserStack -> local Playwright; GitHub MCP -> `gh` CLI). A missing optional tool never blocks
unrelated work. No secret value is ever shown.
