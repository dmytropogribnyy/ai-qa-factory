# v3.2 release-review status — per-item classification

Response to the independent review (PR #1). **No merge, no tag; PR draft.** Each item is classified
**fixed now**, **honestly deferred** (with roadmap text), or **not applicable**, with evidence.

## Hosted-CI failure (previous SHA)
**Fixed.** The 4 core-deterministic failures were the new resolver tests globally patching
`os.name="nt"` → `WindowsPath` on Linux. Corrected by injecting the OS name
(`ClaudeCodeWorker(os_name=…)`); the resolver keeps host-native `Path` for real files and the Windows
branch is exercised logically. Linux coverage for wrapper rejection / override precedence /
missing-native failure / derived native path retained; real Windows behaviour covered by
`windows-smoke`. Evidence: `tests/test_v32_claude_worker.py`. The A/B root-cause evidence (native
`claude.exe` passes, `.CMD` shim fails) is retained.

## P0

| Item | Status | Evidence |
|---|---|---|
| **P0-A** canonical docs/memory drift | **Fixed** | `CLAUDE.md`, `docs/WORK_EXECUTION_MODEL.md`, `.env.example` now distinguish the planning-only ARK `work` from the IMPLEMENTED client-work lifecycle + bounded worker + approval/access boundaries + v3.2 naming; `tests/test_v32_docs_consistency.py` locks the critical statements against drift. |
| **P0-B** Gmail read-only vs send-scope | **Fixed** | Relabelled to the approval-gated SEND provider (`gmail.send + openid + email`, never auto-sends); readiness derives from scope + refresh + expected-account validation (not token presence) and caps at Connected offline (identity is live-proven at send time). `tests/test_v32_access_bootstrap.py`. |
| **P0-C** capability-specific readiness | **Fixed** | Docker CLI == Installed only (no daemon implied); a required access prerequisite is satisfied only when genuinely Verified/Authenticated (not merely Installed/Connected/Runtime-Available). The matrix already separates claude_code Installed vs claude_worker Ready, Playwright import vs the @playwright/test runtime, and MCP Declared vs callable. `tests/test_v32_capability_integrity.py`. |
| **P0-D** representative multi-file acceptance | **Fixed** | `tests/test_v32_golden_multifile_lifecycle.py`: a multi-file project with a cross-file defect through the real lifecycle — worker impl, structured pre-approved validation argv (never HTTP), failing-before validation with redacted/confined evidence, operator-triggered resume/repair, passing-after, review, prepared delivery with per-file hash + package digest, fresh-process resume + re-hash. Auto-repair claim narrowed: repair is operator-triggered, not a self-looping agent (contract + a guard test). Real TS/Playwright execution is separately proven by the browser-acceptance job. |
| **P0-E** client-repo trust/isolation | **Fixed (bounded gate; full isolation deferred)** | `core/orchestration/execution_trust.py` + wiring: trusted/approved-repo-only execution (`EXECUTION_APPROVED.json` from `approve`, or `AIQA_TRUSTED_ROOTS`) with explicit CLI + Dashboard refusal for untrusted; private-work-dir preflight (`git check-ignore`, fail closed) so client artifacts never enter the public repo/CI; credential-stripped validation subprocess env. True OS-level sandboxing (Docker/WSL/Windows-Sandbox) is documented **future work** — not simulated. `tests/test_v32_execution_trust.py`. |

## P1

1. **MCP lifecycle** — *Partially fixed; remainder in the bounded MCP readiness audit (queued) + roadmap.* `mcp_snapshot.py` is honestly config-only (`live_discovery_performed=false`). Manual live verification done: `claude mcp list` inventory; harmless read-only tool calls **Live-Verified** GitHub (`get_me`) and Context7 (`resolve-library-id`); Desktop Commander `✔ Connected`. An in-product operator-local inventory/health flow distinguishing configured → connected → authenticated → tools-callable is the MCP-audit deliverable; it will never store secrets or install MCPs from Dashboard input.
2. **Desktop Commander MCP** — **Fixed.** Optional operator integration in Access/Settings (never a runtime dependency, never a Dashboard shell); verified `✔ Connected` (plugin scope, stdio) via `claude mcp list`. Its tools are not surfaced to this agent session, so it is health-checked at CLI level, not tool-call-verified from here (honest).
3. **Scout autonomy** — **Fixed (documented).** `CLAUDE.md` + contract state that real autonomous prospect sourcing is unavailable without a configured trusted/licensed discovery provider; fixture/file seeds are not live discovery. A durable service/watchdog is deferred and, if built, must reuse the existing queue (no second orchestrator).
4. **Reproducibility / dependency pinning** — *Honestly deferred (roadmap).* Pinning Python + Playwright runtime versions and hardening Actions refs is a coherent standalone change; done in a dedicated follow-up to avoid destabilising this review batch. Today CI uses `cache: pip` and the deterministic core needs no external services.
5. **Secret storage (keyring)** — *Honestly deferred (roadmap).* Long-lived OAuth/PAT material should move to OS keyring/credential storage. Today the product references secrets by env-var **name** only (never values in repo/logs/state/evidence) and GitHub PAT rotation is an operator action — safe, but keyring is the intended hardening.

## Non-goals held
One dashboard / state-evidence store / orchestrator; no duplicate Claude chat/terminal in the
Dashboard; no arbitrary command / MCP installer / credential entry over HTTP; no CAPTCHA
solving/bypass on public Scout; Upwork intake manual; MCPs (Desktop Commander/Lovable/…) are optional
operator capabilities, not proof of product runtime readiness. **main + tags unchanged; PR draft.**
