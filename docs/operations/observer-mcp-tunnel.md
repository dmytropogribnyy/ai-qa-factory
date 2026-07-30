# Observer MCP tunnel — canonical restore runbook

Status: current as of 2026-07-30. Canonical operational reference for reaching the read-only
AI QA Factory Observer MCP from an external ChatGPT connector.

## The one rule

**Do not re-derive this architecture from logs.** Run the existing profile, verify, done.

ChatGPT does **not** reach the Observer through a local HTTP server. The external connector uses an
already-created, stable OpenAI tunnel, and the tunnel client itself launches the Observer as a
**stdio** child process.

## Canonical configuration

| Item | Value |
|---|---|
| Profile name | `ai-qa-factory` |
| Profile file | `%APPDATA%\tunnel-client\ai-qa-factory.yaml` |
| Stable tunnel id | `tunnel_6a5e77892a3c81918f20f44541d4ed65` |
| Tunnel client | `C:\aiqa\tools\tunnel-client.exe` |
| Working root (no spaces) | `C:\aiqa` — an NTFS junction to the canonical checkout |
| Profile MCP command | `C:/aiqa/.venv/Scripts/python.exe C:/aiqa/tools/run_mcp_server.py` |
| Local operator health surface | `http://127.0.0.1:8080` (`/healthz`, `/readyz`) |
| Manual-launch log | `%LOCALAPPDATA%\AIQA-Observer-Tunnel\tunnel-client.manual.jsonl` |
| Secret | `CONTROL_PLANE_API_KEY`, **User** environment scope, never printed |

While the tunnel id is unchanged, the endpoint is unchanged, so **no new tunnel and no connector
rebinding are needed**. Changing the tunnel id or rebinding the connector is an owner decision.

### What this tunnel is, and is not

The client makes an **outbound** connection to the OpenAI control plane, authenticated with
`CONTROL_PLANE_API_KEY`. **No public inbound port is opened on the machine.** There is therefore no
public URL to look for and no bearer authentication to disable. The profile exposes exactly one
command — `run_mcp_server.py` — so the operator **Dashboard is not reachable through the tunnel at
all**: that is a property of the configuration, not a convention.

`127.0.0.1:8770` is a **local auxiliary** Observer HTTP surface used for local verification only. It
is **not** the ChatGPT route. Raising it does nothing for an external reviewer.

## Restore after a reboot

The tunnel is deliberately **not** autostarted, so it must be launched again after every reboot.

First confirm the canonical checkout is on the intended exact `main` and the tree is clean — the
Observer answers with whatever code `C:\aiqa` currently points at.

```powershell
powershell -ExecutionPolicy Bypass -File C:\aiqa\tools\start_observer_tunnel_once.ps1
```

The script is idempotent: if a tunnel is already healthy, or a `tunnel-client` process already
exists, it reports that and starts nothing. It reads the key from the User scope, never prints it,
launches hidden, logs outside the repository, and registers no autostart.

### Three launch paths — do not mix them

| Path | Behaviour | When |
|---|---|---|
| `tools/start_observer_tunnel_once.ps1` | detached one-shot, returns immediately, verifies health | **canonical manual restore** |
| Scheduled Task `AI QA Factory Observer Tunnel` | runs `tunnel-client.exe` directly at logon +20 s, hidden | autostart only, currently **Disabled** |
| `tools/start_observer_tunnel.ps1` | blocks in the foreground until the client exits | when you want the client attached to a terminal |

All three run the **same profile**, so they yield the same tunnel — never a second one. Only one
`tunnel-client` process should exist at a time.

## Verification — in this order

**1. Local (necessary, not sufficient)**

```powershell
& 'C:\aiqa\tools\tunnel-client.exe' health --port 8080
```

Expect `Health OK`. `/healthz` → 200 live and `/readyz` → 200 ready are the same check over HTTP.

**2. Real external call (the only proof)**

From ChatGPT, through the `AI QA Factory Observer` connector:

- health;
- project overview;
- system readiness with `deep: true`;
- any call returning the literal build (e.g. list campaigns).

Success counts as proven **only** when an external MCP call completes and the returned build matches
the intended exact `main`.

A "Connected" badge, visible actions in the ChatGPT UI, a green local health check, and clean
tunnel-client logs are **each insufficient on their own**. In the tunnel log, real external traffic
appears as `dispatcher forwarded command to MCP server` lines with distinct `request_id` values; the
startup self-probe is logged separately and is not evidence of external reachability.

Two version numbers appear and both are correct: `6.3.0` is the MCP surface version, while a value
like `9ea29f76d01a` is the AI QA Factory git build. They are not in conflict.

## If a call still returns 404 / UNAVAILABLE

Check strictly in this order:

1. `tunnel-client profiles list` — the `ai-qa-factory` profile must exist.
2. The `C:\aiqa` junction, `.venv`, and `tools\run_mcp_server.py` must all resolve.
3. `CONTROL_PLANE_API_KEY` must exist in the User scope — verify presence without printing the value.
4. Local health on port 8080.
5. The last lines of `%LOCALAPPDATA%\AIQA-Observer-Tunnel\tunnel-client.manual.jsonl`.
6. Repeat the real external call from ChatGPT.

Do **not** spend time on: raising `127.0.0.1:8770` for ChatGPT's benefit; hunting for a public HTTP
URL; creating a new tunnel; or rebinding the connector before the stable tunnel id is *proven* to
have changed.

## Branch discipline while the tunnel is up

**Never switch the branch of the canonical checkout while the tunnel serves from it.** `C:\aiqa`
points at that same working tree, so a branch switch silently changes the code the external reviewer
is inspecting — an Observer answering from unmerged draft code while reporting itself healthy is
worse than an Observer that is down.

Do development in a separate `git worktree` instead:

```powershell
git worktree add -b my/branch "D:\1QA AI\aiqa-wt-my-branch" main
```

## Autostart — owner decision only

```powershell
powershell -ExecutionPolicy Bypass -File C:\aiqa\tools\observer_tunnel_autostart.ps1 -Action status
```

The canonical task runs `tunnel-client.exe` directly, hidden, with the `ai-qa-factory` profile, 20 s
after logon; `MultipleInstances=IgnoreNew`, restart count 3, interval 1 minute, run level Limited.

Autostart was **deliberately disabled** to reduce background load. Do not enable or reinstall it
without explicit owner approval.
