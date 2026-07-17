"""Approved-communication CLI (Final Phase II).

Commands (wired into `scout`):
  radar-demo        — deterministic complete-product demo to a LOCAL SINK (nothing sent externally).
  send              — send ONE approved draft revision (dry-run by default; --approve-send goes live).
  outreach-control  — enable/disable/pause/kill outreach (disabled by default).
  comms-status      — show communication counts + control state.

There is NO bulk send / "approve all" / comma-list. Live sending requires an explicit flag, a
non-empty reviewer, and an exact recipient confirmation.
"""
from __future__ import annotations

import sys
from pathlib import Path

from core.scout.comms.repository import CommsRepository
from core.scout.comms.send import (
    S_ACCEPTED,
    S_BLOCKED,
    S_DRY_RUN,
    S_FAILED,
    S_IDEMPOTENT,
    S_UNKNOWN,
    SendService,
)
from core.scout.memory.db import MemoryDB, MemoryError
from core.scout.memory.repository import MemoryRepository

_EXIT = {S_DRY_RUN: 0, S_ACCEPTED: 0, S_IDEMPOTENT: 0, S_BLOCKED: 2, S_FAILED: 3, S_UNKNOWN: 4}


def cmd_radar_demo(args) -> int:
    from core.scout.comms.demo import run_radar_demo
    try:
        s = run_radar_demo(args.output)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print("AI QA Factory / ARK Prospect QA Radar v2.0.0 - complete local product demo (LOCAL SINK)")
    print(f"Campaign: {s['campaign_id']}  send_status={s['send_status']}  "
          f"provider_message_id={s['provider_message_id']}")
    print(f"Delivered={s['delivered']}  replied={s['replied']}  followup={s['followup_state']}")
    m = s["metrics"]
    print(f"Metrics: verified={m['verified_prospects']} approved={m['approved_drafts']} "
          f"accepted={m['sends_accepted']} delivered={m['delivered']} replies={m['replies']}")
    print(f"Zero-incidents: duplicate={m['duplicate_send_incidents']} "
          f"unapproved={m['unapproved_send_incidents']} "
          f"outside_sink={m['side_effect_incidents_outside_sink']}")
    print(f"Report: {s['report_dir']}")
    print(f"No real external message was sent (any_real_send={s['any_real_send']}).")
    return 0


def _registry(db_path: str):
    from core.scout.comms.demo import build_provider_registry
    return build_provider_registry(str(Path(db_path).parent / "sink"))


def cmd_send(args) -> int:
    if not args.db or not args.draft_revision or not args.provider:
        print("ERROR: --db, --draft-revision, and --provider are required", file=sys.stderr)
        return 1
    try:
        db = MemoryDB(args.db)
    except MemoryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    mem, comms = MemoryRepository(db), CommsRepository(db)
    rev = comms.get_revision(args.draft_revision)
    if rev is None:
        print("ERROR: unknown draft revision", file=sys.stderr)
        db.close()
        return 1
    approval_id = args.approval_id or f"ap-{args.draft_revision}"
    camp_rows = db.query("SELECT campaign_id FROM companies WHERE company_id=?", (rev["company_id"],))
    campaign_id = camp_rows[0]["campaign_id"] if camp_rows else "unknown"
    live = bool(args.approve_send)
    svc = SendService(mem, comms, _registry(args.db), lambda: _now())
    outcome = svc.send(args.draft_revision, approval_id, args.provider, campaign_id=campaign_id,
                       channel=rev["channel"], live=live, reviewer=args.reviewer or "",
                       confirm_recipient=args.confirm_recipient or "")
    _print_outcome(outcome, live)
    db.close()
    return _EXIT.get(outcome.status, 1)


def _print_outcome(outcome, live: bool) -> None:
    print(f"Send result: {outcome.status.upper()}  {'(LIVE)' if live else '(DRY-RUN)'}")
    if outcome.recipient:
        print(f"  recipient: {outcome.recipient}")
    if outcome.blockers:
        print(f"  blockers: {', '.join(outcome.blockers)}")
    if outcome.provider_message_id:
        print(f"  provider_message_id: {outcome.provider_message_id}")
    if outcome.note:
        print(f"  note: {outcome.note}")
    if outcome.status == S_UNKNOWN:
        print("  OUTCOME_UNKNOWN: not retried automatically; requires human reconciliation.")


def cmd_outreach_control(args) -> int:
    if not args.db:
        print("ERROR: --db is required", file=sys.stderr)
        return 1
    db = MemoryDB(args.db)
    comms = CommsRepository(db)
    scope = args.scope or "__global_outreach__"
    if scope == "global":
        scope = "__global_outreach__"
    state = {"enable": "ENABLED", "disable": "DISABLED", "pause": "PAUSED"}.get(args.state or "", "")
    if args.state == "kill":
        comms.set_control("__kill__", "KILLED")
        print("Outreach GLOBAL KILL set.")
    elif state:
        comms.set_control(scope, state)
        print(f"Outreach control {scope} -> {state}")
    else:
        print(f"{scope}: {comms.get_control(scope)}   global_kill: {comms.get_control('__kill__')}")
    db.close()
    return 0


def cmd_comms_status(args) -> int:
    if not args.db:
        print("ERROR: --db is required", file=sys.stderr)
        return 1
    db = MemoryDB(args.db)
    comms = CommsRepository(db)
    print(f"Database: {args.db}")
    print(f"Global outreach: {comms.get_control('__global_outreach__')}   "
          f"kill: {comms.get_control('__kill__')}")
    for t in ("draft_revisions", "approval_records", "outbound_messages", "send_attempts",
              "provider_events", "commercial_events"):
        print(f"  {t:18} {comms.count(t)}")
    db.close()
    return 0


def _now() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def run_comms_cli(args) -> int:
    return {"radar-demo": cmd_radar_demo, "send": cmd_send,
            "outreach-control": cmd_outreach_control, "comms-status": cmd_comms_status,
            }[args.action](args)
