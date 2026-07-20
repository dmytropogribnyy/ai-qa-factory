# MCP Readiness Audit — v3.2 (bounded, nine-section)

**Final SHA:** `9b047a1` (branch `feature/v3.1.0-operator-dashboard`, PR #1 draft).
Executed against the real installed/runtime state — **not** package presence. This is the queued
deliverable from `docs/V32_RELEASE_REVIEW_STATUS.md` (P1 item 1). Canonical semantics from
`core/orchestration/service_capability.py`: **Live Verified / Fixture Verified / Needs Client /
Needs Operator / Declared**. Nothing is upgraded to Live Verified merely because code or a manifest
entry exists.

## 1. Scope & canonical semantics

Two distinct planes, never conflated:
- **Factory product runtime** — the standalone AI QA Factory process (CLI + Dashboard + CI). By
  design it makes **no live MCP call**; every server in `config/mcp_servers.v2.yaml` is
  `enabled: false`, read-only by default, `readiness: declared_in_manifest`.
- **Developer-agent session** — the Claude Code / VS Code agent, which MAY use `developer_agent_only`
  servers. Live probes here are agent-plane evidence, not Factory-plane readiness.

## 2. Factory product posture (authoritative)

`config/mcp_servers.v2.yaml` declares 14 servers (context7, playwright_mcp, chrome_devtools_mcp,
github_mcp, postman_mcp, sentry_mcp, browserstack_mcp, atlassian_rovo_mcp, resend, gmail,
google_drive, cloudflare, supabase, stripe) — **all `enabled: false`, all `declared_in_manifest`**.
`mcp_snapshot.py` reports `live_discovery_performed=false`. Enforced by `assert_available_to_factory`
(a `developer_agent_only` server is refused to the Factory process) — tested. **Factory-plane class
for every connector: Declared.** This is correct and honest, not a gap.

## 3. Developer-agent session probes (real evidence, this session, SHA 9b047a1)

| Server | Probe (read-only) | Result |
|---|---|---|
| GitHub MCP | `get_me` | **Live Verified** — returned the authenticated login + profile (no write) |
| Context7 MCP | `resolve-library-id("Playwright")` | **Live Verified** — returned real library IDs/metadata |
| Desktop Commander | `claude mcp list` (prior session) | Connected (health-checked at CLI; tools not surfaced here) |

Only harmless read-only calls were made; no write, no external side effect, no secret exposed.

## 4. Per-connector classification (nine connector groups)

| # | Connector | Factory plane | Agent plane (this session) | What it would take to raise |
|---|---|---|---|---|
| 1 | GitHub (MCP / `gh` CLI) | Declared | **Live Verified** (get_me) + `gh` authenticated | already usable by the agent; Factory uses `gh` CLI, not MCP |
| 2 | Context7 | Declared | **Live Verified** (resolve-library-id) | n/a — agent docs lookup only |
| 3 | Playwright MCP | Declared | Declared (Factory uses deterministic Playwright, not MCP) | operator connects in `/mcp`; Factory never depends on it |
| 4 | Chrome DevTools MCP | Declared | Declared | operator connects in `/mcp` for perf/console |
| 5 | Desktop Commander | Declared | Connected (CLI health only) | optional operator tooling; never a Factory dependency |
| 6 | Gmail / Resend / Google Drive | Declared | Not used by the agent | **Gmail SEND/READ is a first-party OAuth integration (not this MCP)** — see `EMAIL_IDENTITY_AND_MAILBOX_POLICY.md`; Resend optional/secondary |
| 7 | Postman / BrowserStack / Sentry / Atlassian | Declared | Not connected | **Needs Operator** to connect + **Needs Client** for a target account |
| 8 | Cloudflare / Supabase / Stripe | Declared | Not connected | **Needs Client** (client account) — per-engagement onboarding, not a Factory defect |
| 9 | Lovable (design consult) | Declared (optional) | Available, unused | optional post-v3.2 UX consultation only; never a runtime/deployment dependency |

Client-specific accounts, staging URLs, repositories, and read-only databases are **per-engagement
onboarding inputs** (Needs Client), never counted as Factory defects.

## 5. Security boundary (unchanged, enforced)

Disabled-by-default servers; tool allowlists; read-only defaults; **secrets referenced by env-var NAME
only** (never values in repo/logs/state/evidence); version pinning; domain/filesystem allowlists;
approval gates for writes; no live MCP in product or CI; no MCP installer or credential entry over
HTTP. Windows VS Code MCP sandboxing is **not** relied on as the security boundary.

## 6. Redacted evidence

- GitHub `get_me` → login `dmytropogribnyy` (public profile fields only; no token shown).
- Context7 `resolve-library-id` → `/microsoft/playwright` et al. (public library metadata).
- No credential, token, or private datum was read or written by any probe.

## 7. Raising a connector (owner/operator actions)

- Agent-plane: `/mcp` connect in Claude Code (operator), then a harmless read-only call → Live Verified.
- Factory-plane: intentionally remains Declared in v3.2 (no live MCP in product); a future phase would
  add a bounded operator-local inventory/health flow (configured → connected → authenticated →
  tools-callable) that never stores secrets or installs MCPs from Dashboard input.

## 8. Non-goals held

No second orchestrator; no live MCP in the Factory runtime or CI; no MCP install/credential entry over
HTTP; MCP servers are optional operator/agent capabilities, **not** proof of Factory runtime readiness.

## 9. Conclusion

Factory-plane MCP readiness is **Declared across the board — correct and honest for v3.2**. Agent-plane
GitHub and Context7 are **Live Verified** by real read-only probes. Everything else is Declared / Needs
Operator / Needs Client with an exact raise path. No connector is overstated as Live Verified on code
presence alone.
