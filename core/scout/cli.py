"""Scout command-line entrypoint (Phase 8.3).

Actions:
  run        — run a bounded read-only scan over explicit public seeds, then export a report.
  demo       — run the deterministic bundled demo site end to end (no external network/browser).
  dashboard  — serve the localhost dashboard for a run (start a fresh run or attach to one).
  control    — send pause/resume/cancel/kill to a running dashboard.
  smoke      — one bounded user-supplied public-site scan.

Everything is read-only: no form submission, login, outreach, or external side effect.
"""
from __future__ import annotations

import json
import sys
import urllib.request
from typing import List, Optional

from core.scout import SCOUT_PRODUCT_NAME, SCOUT_VERSION
from core.scout.config import ScoutRunConfig, fresh_run_id
from core.scout.engine import ScoutEngine
from core.scout.report import build_report
from core.scout.service import ScoutService
from core.scout.store import RunStore


def _split_seeds(value: Optional[str]) -> List[str]:
    if not value:
        return []
    return [s.strip() for s in value.split(",") if s.strip()]


def _run_config(args, seeds, allowed_local_hosts=frozenset(), resolve_dns=True) -> ScoutRunConfig:
    return ScoutRunConfig(
        campaign_name=args.campaign or "adhoc",
        seeds=seeds,
        max_sites=args.max_sites,
        max_pages_per_site=args.max_pages,
        concurrency=args.concurrency,
        browser_mode=args.browser,
        coverage=getattr(args, "coverage", "adaptive") or "adaptive",
        output_dir=args.output,
        resume=args.resume,
        run_id=args.run_id or "",
        allowed_local_hosts=frozenset(allowed_local_hosts),
        resolve_dns=resolve_dns,
    )


def cmd_run(args) -> int:
    seeds = _split_seeds(args.seeds)
    if not seeds:
        print("ERROR: --seeds is required (comma-separated public URLs)", file=sys.stderr)
        return 1
    if args.resume and not args.run_id:
        print("ERROR: --resume requires an explicit --run-id (the run to continue)",
              file=sys.stderr)
        return 1
    try:
        cfg = _run_config(args, seeds)
        # Fresh runs get a unique id (timestamp + entropy) so two identical scans never
        # collide; resume targets an explicit existing run id. The engine fails closed if a
        # fresh id already exists or a resume config does not match.
        cfg.run_id = cfg.run_id or fresh_run_id(cfg.campaign_name)
        store = RunStore(cfg.output_dir, cfg.run_id)
        state = ScoutEngine(cfg, store).run()
        summary = build_report(store)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    _print_summary(state, summary)
    return 0


def cmd_smoke(args) -> int:
    if not args.url:
        print("ERROR: --url is required", file=sys.stderr)
        return 1
    args.seeds = args.url
    return cmd_run(args)


def cmd_demo(args) -> int:
    from core.scout.demo_site import serve_demo_site
    scenarios = ["clean", "broken_link", "accessibility", "seo", "structured_data",
                 "mobile", "presubmit", "business_flow", "captcha", "access_prohibition"]
    with serve_demo_site() as (base, host):
        seeds = [f"{base}/{name}/index.html" for name in scenarios]
        cfg = _run_config(args, seeds, allowed_local_hosts={host}, resolve_dns=False)
        cfg.campaign_name = "scout-demo"
        cfg.resume = False
        cfg.run_id = args.run_id or "scout-demo"
        try:
            store = RunStore(cfg.output_dir, cfg.run_id)
            # The demo deterministically reuses a fixed run id; reset its (confined) run
            # directory first so re-running is clean and does not hit the fresh-run guard.
            store.reset()
            state = ScoutEngine(cfg, store).run()
            summary = build_report(store)
        except Exception as exc:
            print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
            return 1
    print(f"{SCOUT_PRODUCT_NAME} v{SCOUT_VERSION} - deterministic demo")
    _print_summary(state, summary)
    return 0


def cmd_dashboard(args) -> int:
    """Serve the localhost dashboard.

    With ``--seeds`` the dashboard OWNS an active run (start under a single ScoutService),
    so pause/resume/cancel/kill really affect it and the report is built when it finishes.
    With ``--run-id`` (and no seeds) it attaches READ-ONLY to an existing run; controls are
    unavailable (the HTTP API fail-closes with 409) and hidden in the UI.
    """
    from core.scout.dashboard import start_dashboard
    seeds = _split_seeds(args.seeds)
    service = ScoutService(args.output)
    mode = "idle"
    try:
        if seeds:
            cfg = _run_config(args, seeds)
            cfg.run_id = cfg.run_id or fresh_run_id(cfg.campaign_name)
            run_id = service.start(cfg)
            mode = "ACTIVE"
        elif args.run_id:
            service.attach(args.run_id)
            run_id = args.run_id
            mode = "READ-ONLY ATTACHED"
        else:
            # Idle HOME dashboard: serve the localhost home + tool readiness without starting any
            # scan. The operator opens this first, then starts a campaign explicitly.
            run_id = "(none)"
            mode = "HOME (idle)"
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    server, url = start_dashboard(service, port=args.port)
    bound_port = server.server_address[1]
    print(f"Scout dashboard: {url}  (Ctrl+C to stop)")
    print(f"  mode: {mode}   run: {run_id}")
    print(f"  health: {url}/health   status: {url}/api/status")
    try:
        import time
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        server.shutdown()
        print("dashboard stopped")
    finally:
        from core.scout.dashboard import remove_ownership_record
        remove_ownership_record(args.output, bound_port)
    return 0


def cmd_control(args) -> int:
    signal = getattr(args, "signal", None)
    if signal not in ("pause", "resume", "cancel", "kill"):
        print("ERROR: --signal must be pause|resume|cancel|kill", file=sys.stderr)
        return 1
    from core.scout.dashboard import read_csrf_token
    token = read_csrf_token(args.output, args.port)
    if not token:
        print(f"ERROR: no dashboard CSRF token for port {args.port} under {args.output} "
              "(is the dashboard running on this port/output dir?)", file=sys.stderr)
        return 1
    target = f"http://127.0.0.1:{args.port}/api/control?action={signal}"
    try:
        req = urllib.request.Request(target, method="POST", headers={"X-Scout-CSRF": token})
        with urllib.request.urlopen(req, timeout=5) as r:
            print(json.dumps(json.loads(r.read().decode("utf-8")), indent=2))
    except Exception as exc:
        print(f"ERROR: could not reach dashboard at 127.0.0.1:{args.port}: {exc}", file=sys.stderr)
        return 1
    return 0


def _print_summary(state, summary) -> None:
    print(f"Run: {state.get('run_id')}  status={state.get('status')}")
    print(f"Verified findings: {summary['verified_findings']}  "
          f"manual-action: {summary['manual_action_required']}")
    print(f"Report: {summary['report_dir']}")
    for row in summary["shortlist"][:10]:
        print(f"  [{row['priority']}] {row['url']}  defects={row['verified_defects']}")


_DISCOVERY_ACTIONS = frozenset({"campaign-demo", "campaign-plan", "campaign-run", "providers"})
_PRESEND_ACTIONS = frozenset({"presend-demo", "db-status", "db-backup", "db-restore",
                              "review-list", "doctor", "mcp-audit"})
_COMMS_ACTIONS = frozenset({"radar-demo", "send", "outreach-control", "comms-status",
                            "draft-create", "draft-preview", "draft-edit", "draft-approve",
                            "draft-reject", "draft-revoke", "draft-status", "gmail-auth",
                            "gmail-status", "gmail-revoke-local-token", "provider-status",
                            "test-inbox-auth", "test-inbox-status"})


def run_scout_cli(args) -> int:
    if args.action in _DISCOVERY_ACTIONS:
        from core.scout.discovery.cli import run_discovery_cli
        return run_discovery_cli(args)
    if args.action in _PRESEND_ACTIONS:
        from core.scout.pipeline.cli import run_presend_cli
        return run_presend_cli(args)
    if args.action in _COMMS_ACTIONS:
        from core.scout.comms.cli import run_comms_cli
        return run_comms_cli(args)
    return {
        "run": cmd_run, "demo": cmd_demo, "dashboard": cmd_dashboard,
        "control": cmd_control, "smoke": cmd_smoke,
    }[args.action](args)
