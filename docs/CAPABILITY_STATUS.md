# Capability Status — AI QA Factory / Scout (operator release)

Nothing built is deleted. Each capability's **code stays in the repo**; only its **default availability**
differs. Statuses: **Production** (used on the main operator path) · **Optional** (present, enable
explicitly / provide a key) · **Experimental** (code kept, off by default, kill-switch) · **Parked**
(kept on a branch, disabled by default, resume only when there's a real need).

| Capability | Status | Default | Where / how |
|---|---|---|---|
| Scout discovery → analysis → Dashboard (findings, severity, confidence, repro, evidence, screenshots, history, dedup) | **Production** | on | `main`; run per `docs/RUNBOOK_SCOUT.md` |
| Bounded, read-only public analysis + honest budget/status | **Production** | on | `main` |
| Per-run report (Markdown + JSON) + Dashboard HTML views | **Production** | on | `outputs/scout/<run>/report/` (e.g. `DISCOVERY_SUMMARY.md`, `VERIFIED_FINDINGS.md`, `*.json`) + `/scout` views + internal `/api/scout/export` review record + exact-target client ZIP |
| Exact-target client evidence ZIP | **Production** | on after completed analysis | ≤20 MiB; structured text secret-scanned; visual media requires review |
| Public contact extraction + copy-only factual draft | **Production** | on after actionable finding | same-domain public contacts preferred; source shown; fixes scoped only after access |
| Manual CAPTCHA/access-check handoff | **Optional** | operator-triggered | visible Chromium waits for Continue/Defer/Skip; no automatic solving/bypass |
| Tavily live discovery | **Optional** | on (key configured) | `python tools/tavily_setup.py`; without a key, use `scout run --seeds` |
| Deep capture (Playwright screenshots/evidence) | **Optional** | selectable | `browser_mode=playwright` (else static) |
| Direct Claude↔GPT review driver + durable supervisor + Dashboard `/collab` | **Production** | on | `main` (Issue #14/#16) — Claude engineers, GPT reviews |
| Gmail send provider | **Experimental** | **off** | present; kill-switch; credentials + exact owner approval required |
| Session-independent autonomous writer | **Parked** | **off (not on `main`)** | branch `feat/session-independent-writer`, PR #19 (draft) — see below |
| CAPTCHA solver | **Not implemented** | — | intentionally absent (policy) |
| Automatic CRM / commercial automation | **Deferred** | — | not started |

## Parked — session-independent writer (Issue #17 / PR #19)
- **Code:** `feat/session-independent-writer` (PR #19, draft) @ `b541a99`.
- **Proven live:** pull-first worker protocol, heartbeat lease renewal, orphan recovery, claim-token +
  host/PID fencing, honest billing, and a full `PROPOSAL → GPT → ACK → implement → commit → CHECKPOINT →
  GO → done` loop on the Pro subscription ($0 real spend).
- **Unproven:** a *provably-sound* single-writer fence needs OS-level tree containment (Windows Job
  Object). The PID-snapshot fence is practically safe but not formally complete (GPT NO-GO round 2).
- **Default:** disabled — `main` does not contain the writer, so nothing auto-launches it.
- **Resume when:** real product usage shows zero-touch autonomous coding has business value; then add the
  Job-Object containment slice, re-review, and merge.

## Safety posture (always on)
Read-only public scenarios only. No automatic outreach send, form submission, login, CAPTCHA
solving/bypass, or irreversible external action by default. Bounded, finite runs with honest budget
accounting.
