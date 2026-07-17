"""Pre-send pipeline CLI (Final Phase I).

Commands (wired into `scout`):
  presend-demo  — run the bundled deterministic complete pre-send demo (no network/browser; nothing sent).
  db-status     — show the memory database schema version + integrity + row counts.
  db-backup     — back up the memory database (integrity-verified).
  db-restore    — restore the memory database from a backup.
  review-list   — list the human review queue.
  doctor        — environment readiness check.

There is no send command anywhere.
"""
from __future__ import annotations

import sys
from typing import Any, Dict

from core.scout.memory.db import MemoryDB, MemoryError
from core.scout.memory.repository import MemoryRepository


def cmd_presend_demo(args) -> int:
    from core.scout.pipeline.demo import run_presend_demo
    try:
        summary = run_presend_demo(args.output)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print("AI QA Factory / ARK Prospect QA Radar v1.9.0 - complete pre-send demo")
    print(f"Campaign: {summary['campaign_id']}  companies={summary['companies']}  "
          f"verified_findings={summary['verified_findings']}")
    print(f"Contacts: {summary['contacts']}  drafts (pending review): {summary['drafts']}  "
          f"review items: {summary['review_items']}")
    print(f"Memory DB: {summary['memory_db']}  (companies={summary['companies_in_memory']}, "
          f"drafts={summary['drafts_in_memory']})")
    print(f"Report: {summary['report_dir']}")
    print(f"Nothing was sent (any_sent={summary['any_sent']}).")
    return 0


def _open_db(args) -> MemoryDB:
    return MemoryDB(args.db)


def cmd_db_status(args) -> int:
    try:
        db = _open_db(args)
    except MemoryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    repo = MemoryRepository(db)
    print(f"Database: {args.db}")
    print(f"Schema version: {db.current_version()}   integrity_ok: {db.integrity_ok()}")
    for table in ("companies", "domains", "contacts", "findings", "drafts", "review_queue", "jobs"):
        print(f"  {table:14} {repo.count(table)}")
    db.close()
    return 0


def cmd_db_backup(args) -> int:
    try:
        db = _open_db(args)
        dest = db.backup(args.dest)
        db.close()
    except MemoryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Backup written: {dest}")
    return 0


def cmd_db_restore(args) -> int:
    try:
        db = MemoryDB.restore(args.db, args.dest)
        print(f"Restored to {args.dest}  schema version {db.current_version()}")
        db.close()
    except MemoryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


def cmd_review_list(args) -> int:
    try:
        db = _open_db(args)
    except MemoryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    repo = MemoryRepository(db)
    rows = repo.review_items()
    print(f"Review queue ({len(rows)} items):")
    for r in rows:
        print(f"  [{r['state']}] {r['queue']:24} {r['subject_ref']}")
    db.close()
    return 0


def cmd_doctor(args) -> int:
    checks: Dict[str, Any] = {}
    checks["python"] = sys.version.split()[0]
    checks["playwright"] = _has("playwright")
    checks["axe_core"] = _has("axe_core_python")
    import os
    checks["output_writable"] = os.access(args.output or ".", os.W_OK)
    print("Environment doctor:")
    for k, v in checks.items():
        print(f"  {k:18} {v}")
    # Final Phase II readiness (safe: reports state, never enables sending).
    if getattr(args, "db", None) and os.path.exists(args.db):
        from core.scout.comms.repository import CommsRepository
        db = MemoryDB(args.db)
        comms = CommsRepository(db)
        print("Communication readiness:")
        print(f"  schema_version     {db.current_version()}   integrity_ok {db.integrity_ok()}")
        print(f"  global_outreach    {comms.get_control('__global_outreach__')} "
              f"(kill: {comms.get_control('__kill__')})")
        print(f"  draft_revisions    {comms.count('draft_revisions')}   "
              f"approvals {comms.count('approval_records')}   "
              f"outbound {comms.count('outbound_messages')}")
        db.close()
    manifest = os.path.join("config", "mcp_servers.v2.yaml")
    if os.path.exists(manifest):
        from core.scout.integrations.mcp import audit, load_manifest
        a = audit(load_manifest(manifest), factory_process=True)
        print(f"MCP integrations: {a['total']} declared, valid={a['valid']}, "
              f"discovery={a['discovery_source']} (all disabled by default; none live-accepted).")
    print("Deterministic pipeline needs neither a browser nor axe; both are optional for real "
          "acceptance. Sending is DISABLED by default and CLI-gated. Nothing here sends anything.")
    return 0


def _has(pkg: str) -> bool:
    import importlib.util
    return importlib.util.find_spec(pkg) is not None


def cmd_mcp_audit(args) -> int:
    import json
    import os
    from pathlib import Path

    from core.scout.integrations.mcp import audit, discovery_snapshot, gap_report, load_manifest
    manifest = os.path.join("config", "mcp_servers.v2.yaml")
    if not os.path.exists(manifest):
        print(f"ERROR: manifest not found: {manifest}", file=sys.stderr)
        return 1
    entries = load_manifest(manifest)
    out = Path(args.output or "outputs") / "mcp"
    out.mkdir(parents=True, exist_ok=True)
    snaps = {"MCP_DISCOVERY_SNAPSHOT.json": discovery_snapshot(entries),
             "MCP_HEALTH_AND_READINESS.json": audit(entries, factory_process=True),
             "MCP_CAPABILITY_GAP_REPORT.json": gap_report(entries)}
    for name, data in snaps.items():
        (out / name).write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    health = snaps["MCP_HEALTH_AND_READINESS.json"]
    print(f"MCP audit: {health['total']} servers declared, valid={health['valid']}, "
          f"discovery_source={health['discovery_source']}")
    print(f"  All disabled by default; none live-accepted. Snapshots -> {out}")
    return 0


def run_presend_cli(args) -> int:
    return {
        "presend-demo": cmd_presend_demo, "db-status": cmd_db_status, "db-backup": cmd_db_backup,
        "db-restore": cmd_db_restore, "review-list": cmd_review_list, "doctor": cmd_doctor,
        "mcp-audit": cmd_mcp_audit,
    }[args.action](args)
