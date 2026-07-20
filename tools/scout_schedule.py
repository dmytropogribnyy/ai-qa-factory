"""Thin, opt-in Windows Task Scheduler wrapper for live Scout discovery (v3.3).

Registers a DISABLED-by-default scheduled task that invokes the canonical Scout CLI by campaign id.
No new scheduler service, no overlapping runs (the campaign-run acquires a run-lock), fresh-process
resume is preserved, and the TAVILY_API_KEY is NEVER embedded in the task command (it is read from the
outside-repo secret at run time). "Run discovery now" is the plain CLI. Commands:

    python tools/scout_schedule.py create  --campaign-id <id> --countries us,de --industries "B2B SaaS" [--time 09:00]
    python tools/scout_schedule.py status  --campaign-id <id>
    python tools/scout_schedule.py enable  --campaign-id <id>
    python tools/scout_schedule.py disable --campaign-id <id>
    python tools/scout_schedule.py remove  --campaign-id <id>
    python tools/scout_schedule.py run-now --campaign-id <id> [same discovery args]
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_PY = sys.executable


def task_name(campaign_id: str) -> str:
    safe = "".join(c for c in campaign_id if c.isalnum() or c in "-_")[:80] or "campaign"
    return f"AIQA-Scout-Discovery-{safe}"


def discovery_cli_args(args) -> list:
    """The canonical CLI invocation (no secret is ever included)."""
    cli = [_PY, "main.py", "scout", "campaign-run", "--live-provider", "tavily",
           "--approve-live-discovery", "--campaign-id", args.campaign_id]
    if args.countries:
        cli += ["--countries", args.countries]
    if args.industries:
        cli += ["--industries", args.industries]
    if getattr(args, "business_types", None):
        cli += ["--business-types", args.business_types]
    if getattr(args, "keywords", None):
        cli += ["--keywords", args.keywords]
    cli += ["--tavily-max-results", str(getattr(args, "max_results", 10)),
            "--tavily-max-requests", str(getattr(args, "max_requests", 8)),
            "--output", getattr(args, "output", "outputs")]
    return cli


# Supported scheduled modes. "manual" has no scheduled trigger (use run-now).
SCHEDULE_MODES = ("manual", "daily", "weekdays", "weekly", "once")


class ScheduleModeError(ValueError):
    """Raised for an unknown mode or 'manual' (which has no scheduled task)."""


def schedule_trigger_args(mode: str, *, time: str = "09:00", day: str = "MON",
                          start_date: str = "") -> list:
    """The schtasks /SC trigger fragment for a scheduled mode. 'manual' raises (no task).

    Every scheduled mode still runs the same bounded campaign with the same ceilings/safety/
    dedup/recovery/stop-reasons — only the trigger differs."""
    m = (mode or "daily").lower()
    if m == "daily":
        return ["/SC", "DAILY", "/ST", time]
    if m == "weekdays":
        return ["/SC", "WEEKLY", "/D", "MON,TUE,WED,THU,FRI", "/ST", time]
    if m == "weekly":
        return ["/SC", "WEEKLY", "/D", day, "/ST", time]
    if m == "once":
        from datetime import date
        return ["/SC", "ONCE", "/SD", start_date or date.today().strftime("%Y/%m/%d"), "/ST", time]
    if m == "manual":
        raise ScheduleModeError("manual mode has no scheduled task; use 'run-now'")
    raise ScheduleModeError(f"unknown schedule mode: {mode!r}")


def build_create_argv(args) -> list:
    """Build the schtasks /Create argv. Creates the task DISABLED by default. The command it runs is
    the canonical CLI — NEVER the API key."""
    inner = " ".join(f'"{a}"' if " " in a else a for a in discovery_cli_args(args))
    tr = f'cmd /c cd /d "{REPO}" && {inner}'
    trigger = schedule_trigger_args(getattr(args, "mode", "daily"),
                                    time=getattr(args, "time", "09:00"),
                                    day=getattr(args, "day", "MON"))
    return ["schtasks", "/Create", "/TN", task_name(args.campaign_id), "/TR", tr,
            *trigger, "/F", "/DISABLE"]


def _run(argv: list) -> int:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=30, check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        print(f"ERROR: {exc}")
        return 1
    out = (p.stdout or "") + (p.stderr or "")
    print(out.strip())
    return p.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description="Opt-in Task Scheduler for live Scout discovery")
    ap.add_argument("action", choices=["create", "status", "enable", "disable", "remove", "run-now"])
    ap.add_argument("--campaign-id", required=True)
    ap.add_argument("--countries", default="")
    ap.add_argument("--industries", default="")
    ap.add_argument("--business-types", dest="business_types", default="")
    ap.add_argument("--keywords", default="")
    ap.add_argument("--mode", default="daily", choices=list(SCHEDULE_MODES))
    ap.add_argument("--day", default="MON")
    ap.add_argument("--time", default="09:00")
    ap.add_argument("--max-results", dest="max_results", type=int, default=10)
    ap.add_argument("--max-requests", dest="max_requests", type=int, default=8)
    ap.add_argument("--output", default="outputs")
    args = ap.parse_args()
    tn = task_name(args.campaign_id)

    if args.action == "run-now":                       # plain CLI; overlap-guarded by the run-lock
        return _run(discovery_cli_args(args))
    if args.action == "create":
        if args.mode == "manual":
            print("mode=manual has no scheduled task; use 'run-now' to run on demand.")
            return 2
        print(f"Creating DISABLED {args.mode} task {tn} (enable explicitly). Key is NOT in the task.")
        return _run(build_create_argv(args))
    if args.action == "status":
        return _run(["schtasks", "/Query", "/TN", tn, "/FO", "LIST", "/V"])
    if args.action == "enable":
        return _run(["schtasks", "/Change", "/TN", tn, "/ENABLE"])
    if args.action == "disable":
        return _run(["schtasks", "/Change", "/TN", tn, "/DISABLE"])
    if args.action == "remove":
        return _run(["schtasks", "/Delete", "/TN", tn, "/F"])
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
