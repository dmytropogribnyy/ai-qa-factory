# Tool Readiness Guide

See honest tool readiness any time:

```powershell
python main.py tool-status          # human-readable table
python main.py tool-status --json   # machine snapshot
```

or open the dashboard **Tool Readiness** page (`/tools`).

## Availability domains

- **INTERNAL_RUNNER** - built into the repo (the API runner, the Playwright runner). Its readiness
  comes from a real **production binding** (an importable module + a callable adapter + a bounded
  health check), never from a test file. The API runner is `fixture-tested` (its health check parses
  a fixture OpenAPI and generates stubs in-process); the Playwright runner is `health-checked` (its
  in-repo binding is present) with the browser runtime (Node/Chromium) reported separately and never
  claimed `live-accepted`. Without its binding, an internal tool stays `declared`.
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
`blocked-by-auth`, `blocked-by-policy`. A manifest entry is **never** called a working integration, a
test file is **never** a runtime binding, and nothing is `live-accepted` without recorded evidence.

## Missing tools

Each missing tool shows one clear setup line and a **fallback** (e.g. Sentry -> use supplied logs;
BrowserStack -> local Playwright; GitHub MCP -> `gh` CLI). A missing optional tool never blocks
unrelated work. No secret value is ever shown.
