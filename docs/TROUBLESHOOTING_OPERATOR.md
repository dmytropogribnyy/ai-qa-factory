# Operator Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `Python 3.12 was not found` | Python not on PATH | Install Python 3.12, reopen the terminal, re-run `scripts\setup-local.ps1` |
| `Virtual environment missing` | setup not run | `scripts\setup-local.ps1` |
| dependency install failed | offline / proxy | Check your internet/proxy, re-run setup |
| `outputs\ is not writable` | permissions | Run from a user-writable folder; check the directory ACLs |
| dashboard URL not reachable | not started / wrong port | `scripts\start-local.ps1 [port]`; open the printed `http://127.0.0.1:<port>` |
| dashboard won't stop | stray process | `scripts\stop-local.ps1 [port]` |
| a tool shows `unavailable` | binary not on PATH | Follow the setup line from `python main.py tool-status` |
| a tool shows `blocked-by-auth` | not authorized locally | Follow its setup (e.g. Gmail: `docs\GMAIL_PROVIDER_SETUP.md`); optional tools don't block other work |
| GitHub MCP shows `declared` | session MCP not connected | Connect it in Claude Code (`/mcp`); the local `gh` CLI is the fallback |
| analyze-job says `NOT_RECOMMENDED` | outside proven capability / no access / unbounded / impossible deadline | Read `FEASIBILITY_SUMMARY.md`; use the smaller in-scope slice in `PROPOSAL_DRAFT.md` or gather the missing access first |

## Principles

- Errors state what failed, whether your data is safe, whether you can retry, and what to do next -
  raw stack traces are not the normal operator response (diagnostics keep the detail).
- Nothing is scanned or emailed automatically. Gmail live-send is optional and separate.
- Paths with spaces (e.g. `D:\1QA AI\ai-qa-factory`) are supported; the scripts locate the repo via
  `$PSScriptRoot`, never a hardcoded path.
- If unsure, run `scripts\doctor-local.ps1`.
