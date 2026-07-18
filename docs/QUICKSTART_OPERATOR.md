# Operator Quickstart (Windows)

Two surfaces, one product. **Client work** happens in **Claude Code** (VS Code chat). **Scout**
prospecting happens in the **local web dashboard**. Both share the same project state and evidence.

Nothing is sent, scanned, or authorized automatically. Gmail live-send is optional and separate.

## One-time setup

```powershell
scripts\setup-local.ps1     # verify Python, create .venv, install requirements.txt, check storage
```

## Every day

```powershell
scripts\start-local.ps1     # open the dashboard at http://127.0.0.1:8765 (Ctrl+C to stop)
scripts\doctor-local.ps1    # readiness check (Python, imports, storage, tool readiness)
scripts\stop-local.ps1      # stop the dashboard
```

## Cheat sheet - CLIENT WORK (Claude Code)

1. Open the AI QA Factory repo in VS Code and open Claude Code.
2. Paste the Upwork/direct job text, URL, budget, deadline, attachments.
3. Say: **"Only analyze; do not start implementation."** (or run
   `python main.py analyze-job --text "<brief>"`).
4. Review the **verdict** (RECOMMENDED_TO_TAKE / TAKE_AFTER_CLARIFICATION /
   TAKE_AFTER_ACCESS_OR_TOOL_SETUP / NOT_RECOMMENDED), the **client questions**, the **effort/risk**,
   the **selected tools**, and the **honest reasons to reject**.
5. **Approve the plan** before any execution.
6. Ask Claude to start; track progress and blockers.
7. Review validation and the **delivery package**, then send the prepared result to the client.

See [CLIENT_WORK_OPERATOR_GUIDE.md](CLIENT_WORK_OPERATOR_GUIDE.md).

## Cheat sheet - SCOUT (local dashboard)

1. `scripts\start-local.ps1` and open the dashboard.
2. Create a campaign with simple filters (country / industry / keywords / depth).
3. Start it; watch progress; pause / resume / stop safely as needed.
4. Review found companies, verified findings, and evidence.
5. Review the public contact and its provenance.
6. Edit the prepared draft; **Open in Gmail** and personally decide whether to send.
7. **Mark contacted.**

See [SCOUT_OPERATOR_GUIDE.md](SCOUT_OPERATOR_GUIDE.md),
[TOOL_READINESS_GUIDE.md](TOOL_READINESS_GUIDE.md), and
[TROUBLESHOOTING_OPERATOR.md](TROUBLESHOOTING_OPERATOR.md).

## Safety

Read-only public scanning only. No purchases, no form submissions, no login/CAPTCHA bypass, no bulk
or automatic outreach. Every external email is individually, explicitly approved by you. Secrets are
never printed or committed. See [SAFETY_RULES.md](SAFETY_RULES.md).
