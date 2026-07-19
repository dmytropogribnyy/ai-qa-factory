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
    print("AI QA Factory / ARK Prospect QA Radar v2.0.2 - complete local product demo (LOCAL SINK)")
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
    # The public send command uses the PRODUCTION runtime registry (local_sink + gmail_personal +
    # optional resend) — never the deterministic demo registry.
    from core.scout.comms.runtime import build_runtime_provider_registry
    return build_runtime_provider_registry(str(Path(db_path).parent / "sink"))


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


def _open(args):
    """Open the memory DB and return (db, mem, comms) or (None, None, None) after printing an error."""
    if not args.db:
        print("ERROR: --db is required", file=sys.stderr)
        return None, None, None
    try:
        db = MemoryDB(args.db)
    except MemoryError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return None, None, None
    return db, MemoryRepository(db), CommsRepository(db)


def _read_body(args) -> str:
    """Read the draft body from a file (preferred; never echoes into shell history) or --body."""
    if getattr(args, "body_file", None):
        return Path(args.body_file).read_text(encoding="utf-8")
    return args.body or ""


# --- one-at-a-time human review commands (no bulk / approve-all) ----------------------------------

def cmd_draft_create(args) -> int:
    from core.scout.comms.approval import ApprovalError, build_revision
    from core.scout.comms.review import preview_hash_for
    db, mem, comms = _open(args)
    if db is None:
        return 1
    for req in ("draft_id", "company_id", "contact_id", "finding_id", "subject"):
        if not getattr(args, req, None):
            print(f"ERROR: --{req.replace('_', '-')} is required", file=sys.stderr)
            db.close()
            return 1
    try:
        rid = build_revision(mem, comms, draft_id=args.draft_id, company_id=args.company_id,
                             contact_id=args.contact_id, finding_id=args.finding_id,
                             channel=args.channel or "email", subject=args.subject,
                             body=_read_body(args), now=_now(), creator=args.reviewer or "operator")
    except (ApprovalError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        db.close()
        return 1
    print(f"Created immutable revision: {rid}")
    print(f"reviewed_content_hash: {preview_hash_for(comms, rid)}")
    print(f"Next: scout draft-preview --db {args.db} --draft-revision {rid}")
    db.close()
    return 0


def cmd_draft_preview(args) -> int:
    from core.scout.comms.review import review_preview
    db, mem, comms = _open(args)
    if db is None:
        return 1
    if not args.draft_revision:
        print("ERROR: --draft-revision is required", file=sys.stderr)
        db.close()
        return 1
    try:
        p = review_preview(mem, comms, args.draft_revision)
    except KeyError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        db.close()
        return 1
    print("=== REVIEW PREVIEW (exact content) ===")
    print(f"  revision:   {p['revision_id']} (#{p['revision_number']})  state={p['state']}"
          f"  superseded={p['superseded']}")
    print(f"  company:    {p['company_id']}   contact: {p['contact_id']}")
    print(f"  recipient:  {p['recipient']}   channel: {p['channel']}")
    print(f"  subject:    {p['subject']}")
    print(f"  finding:    {p['finding_id']}  {p['finding_title']}")
    cp = p["contact_provenance"]
    print(f"  provenance: source={cp['source_category']} published={cp['publicly_published_for_contact']}"
          f" terms={cp['terms_review_status']} person={cp['person_class']}")
    print(f"  expires:    {p['expires_at']}")
    print("  --- body ---")
    print(p["body"])
    print("  ------------")
    print(f"reviewed_content_hash: {p['reviewed_content_hash']}")
    print("To approve exactly this content:")
    print(f"  scout draft-approve --db {args.db} --draft-revision {p['revision_id']} "
          f"--reviewer <you> --reviewed-content-hash {p['reviewed_content_hash']} --confirm APPROVE")
    db.close()
    return 0


def cmd_draft_edit(args) -> int:
    from core.scout.comms.approval import ApprovalError, edit_revision
    from core.scout.comms.review import preview_hash_for
    db, mem, comms = _open(args)
    if db is None:
        return 1
    if not args.draft_revision or not args.subject:
        print("ERROR: --draft-revision and --subject are required", file=sys.stderr)
        db.close()
        return 1
    try:
        new_rid = edit_revision(mem, comms, args.draft_revision, subject=args.subject,
                                body=_read_body(args), now=_now())
    except (ApprovalError, OSError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        db.close()
        return 1
    print(f"Edited -> new immutable revision: {new_rid} (old revision superseded, its approval invalidated)")
    print(f"reviewed_content_hash: {preview_hash_for(comms, new_rid)}")
    db.close()
    return 0


def cmd_draft_approve(args) -> int:
    from core.scout.comms.approval import ApprovalError, approve_revision
    db, mem, comms = _open(args)
    if db is None:
        return 1
    if not args.draft_revision or not (args.reviewer or "").strip():
        print("ERROR: --draft-revision and --reviewer are required", file=sys.stderr)
        db.close()
        return 1
    if args.confirm != "APPROVE":
        print("ERROR: typed confirmation required (--confirm APPROVE)", file=sys.stderr)
        db.close()
        return 1
    if not args.reviewed_content_hash:
        print("ERROR: --reviewed-content-hash is required (from draft-preview)", file=sys.stderr)
        db.close()
        return 1
    try:
        aid = approve_revision(mem, comms, args.draft_revision, reviewer=args.reviewer, now=_now(),
                               reviewed_content_hash=args.reviewed_content_hash)
    except ApprovalError as exc:
        print(f"ERROR: approval refused: {exc}", file=sys.stderr)
        db.close()
        return 2
    print(f"Approved: {aid}  (single-use; sending is a SEPARATE command)")
    db.close()
    return 0


def cmd_draft_reject(args) -> int:
    from core.scout.comms.repository import R_REJECTED
    db, mem, comms = _open(args)
    if db is None:
        return 1
    if not args.draft_revision or not (args.reviewer or "").strip():
        print("ERROR: --draft-revision and --reviewer are required", file=sys.stderr)
        db.close()
        return 1
    try:
        comms.transition_revision(args.draft_revision, R_REJECTED, _now())
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: {exc}", file=sys.stderr)
        db.close()
        return 1
    mem.add_review_item(f"reject-{args.draft_revision}", "draft_review", args.draft_revision,
                        None, _now())
    print(f"Rejected revision {args.draft_revision} (audited).  reason: {args.reason or '(none)'}")
    db.close()
    return 0


def cmd_draft_revoke(args) -> int:
    db, mem, comms = _open(args)
    if db is None:
        return 1
    approval_id = args.approval_id or (f"ap-{args.draft_revision}" if args.draft_revision else "")
    if not approval_id:
        print("ERROR: --approval-id or --draft-revision is required", file=sys.stderr)
        db.close()
        return 1
    comms.revoke_approval(approval_id, args.reason or "revoked by reviewer", _now())
    print(f"Revoked approval {approval_id} (audited).  reason: {args.reason or '(none)'}")
    db.close()
    return 0


def cmd_draft_status(args) -> int:
    db, mem, comms = _open(args)
    if db is None:
        return 1
    if not args.draft_revision:
        print("ERROR: --draft-revision is required", file=sys.stderr)
        db.close()
        return 1
    rev = comms.get_revision(args.draft_revision)
    if rev is None:
        print("ERROR: unknown revision", file=sys.stderr)
        db.close()
        return 1
    ap = comms.get_approval(f"ap-{args.draft_revision}")
    print(f"Revision {rev['revision_id']} (#{rev['revision_number']})  state={rev['state']}"
          f"  superseded={bool(rev['superseded'])}  expires={rev['expires_at']}")
    print(f"Approval: {(ap or {}).get('state', '(none)')}  consumed={(ap or {}).get('consumed', 0)}")
    print("Lifecycle:")
    for e in comms.lifecycle_events("revision", rev["revision_id"]):
        print(f"  [{e['at']}] revision {e['event']}")
    if ap:
        for e in comms.lifecycle_events("approval", ap["approval_id"]):
            print(f"  [{e['at']}] approval {e['event']}")
    db.close()
    return 0


# --- Gmail + provider commands --------------------------------------------------------------------

def _gmail_config(args) -> dict:
    from core.scout.comms.gmail import gmail_config_from_env
    cfg = gmail_config_from_env()
    if getattr(args, "client_config", None):
        cfg["client_json"] = args.client_config
    if getattr(args, "token_store", None):
        cfg["token_json"] = args.token_store
    if getattr(args, "expected_account", None):
        cfg["expected_account"] = args.expected_account
    return cfg


def cmd_gmail_status(args) -> int:
    from core.scout.comms.gmail_oauth import gmail_status
    status = gmail_status(_gmail_config(args))
    print("Gmail provider status (no token values shown):")
    for k in ("readiness", "client_config_present", "token_present", "refreshable",
              "authorized_account", "expected_account", "expected_account_match", "scopes"):
        print(f"  {k:22} {status[k]}")
    return 0


def cmd_gmail_auth(args) -> int:
    from core.scout.comms.gmail import GmailConfigError
    from core.scout.comms.gmail_oauth import authorize
    cfg = _gmail_config(args)
    if not cfg["client_json"] or not cfg["token_json"]:
        print("ERROR: --client-config and --token-store are required (or set GMAIL_OAUTH_CLIENT_JSON "
              "/ GMAIL_OAUTH_TOKEN_JSON)", file=sys.stderr)
        return 1
    try:
        result = authorize(client_config_path=cfg["client_json"], token_store_path=cfg["token_json"],
                           expected_account=cfg["expected_account"])
    except GmailConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Authorized account: {result['account']}  scopes: {', '.join(result['scopes'])}")
    if result["permissions"]["warning"]:
        print(f"WARNING: {result['permissions']['warning']}", file=sys.stderr)
    return 0


def cmd_gmail_revoke_local_token(args) -> int:
    from core.scout.comms.gmail_oauth import revoke_local_token
    cfg = _gmail_config(args)
    if not cfg["token_json"]:
        print("ERROR: --token-store is required", file=sys.stderr)
        return 1
    if args.confirm != "REVOKE":
        print("ERROR: typed confirmation required (--confirm REVOKE)", file=sys.stderr)
        return 1
    result = revoke_local_token(cfg["token_json"])
    print(f"Local token removed: {result['removed_local_token']}. {result['note']}")
    return 0


# --- Technical QA test inbox (read-only; the SECOND, distinct identity) ----------------------------

def _test_inbox_config(args) -> dict:
    from core.scout.comms.test_inbox import test_inbox_config_from_env
    cfg = test_inbox_config_from_env()
    if getattr(args, "client_config", None):
        cfg["client_json"] = args.client_config
    if getattr(args, "token_store", None):
        cfg["token_json"] = args.token_store
    if getattr(args, "expected_account", None):
        cfg["expected_account"] = args.expected_account
    if getattr(args, "send_token_store", None):
        cfg["send_token_json"] = args.send_token_store
    return cfg


def cmd_test_inbox_status(args) -> int:
    from core.scout.comms.test_inbox import test_inbox_status
    status = test_inbox_status(_test_inbox_config(args))
    print("Gmail QA Test Inbox status (read-only; no token values shown):")
    for k in ("readiness", "client_config_present", "token_present", "refreshable",
              "distinct_token_store", "authorized_account", "expected_account", "scopes_ok",
              "expected_account_claim_match", "scopes"):
        print(f"  {k:26} {status[k]}")
    return 0


def cmd_test_inbox_auth(args) -> int:
    from core.scout.comms.gmail import GmailConfigError
    from core.scout.comms.test_inbox import authorize_test_inbox
    cfg = _test_inbox_config(args)
    if not cfg["client_json"] or not cfg["token_json"]:
        print("ERROR: --client-config and --token-store are required (or set "
              "GMAIL_TEST_OAUTH_CLIENT_JSON / GMAIL_TEST_OAUTH_TOKEN_JSON). The token store MUST be a "
              "distinct file from the send token — see docs/EMAIL_IDENTITY_AND_MAILBOX_POLICY.md",
              file=sys.stderr)
        return 1
    try:
        result = authorize_test_inbox(
            client_config_path=cfg["client_json"], token_store_path=cfg["token_json"],
            send_token_store_path=cfg.get("send_token_json", ""),
            expected_account=cfg["expected_account"])
    except GmailConfigError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"Authorized read-only test inbox: {result['account']}  "
          f"scopes: {', '.join(result['scopes'])}")
    if result["permissions"]["warning"]:
        print(f"WARNING: {result['permissions']['warning']}", file=sys.stderr)
    return 0


def cmd_provider_status(args) -> int:
    from core.scout.comms.gmail_oauth import gmail_status
    print("Providers (readiness; none live-accepted without a recorded controlled acceptance):")
    print("  local_sink       fixture-tested   (no network; drives tests/demos)")
    gs = gmail_status(_gmail_config(args))
    print(f"  gmail_personal   {gs['readiness']}   sender=dipptrue@gmail.com  "
          f"expected_match={gs['expected_account_match']}")
    from core.scout.comms.resend import resend_config_from_env
    rc = resend_config_from_env()
    print(f"  resend_email     {'configured' if rc['api_key_present'] and rc['from_email'] else 'adapter-ready'}"
          f"   darrowcode.com-only (secondary, optional)")
    return 0


def run_comms_cli(args) -> int:
    return {"radar-demo": cmd_radar_demo, "send": cmd_send,
            "outreach-control": cmd_outreach_control, "comms-status": cmd_comms_status,
            "draft-create": cmd_draft_create, "draft-preview": cmd_draft_preview,
            "draft-edit": cmd_draft_edit, "draft-approve": cmd_draft_approve,
            "draft-reject": cmd_draft_reject, "draft-revoke": cmd_draft_revoke,
            "draft-status": cmd_draft_status, "gmail-auth": cmd_gmail_auth,
            "gmail-status": cmd_gmail_status, "gmail-revoke-local-token": cmd_gmail_revoke_local_token,
            "provider-status": cmd_provider_status,
            "test-inbox-auth": cmd_test_inbox_auth, "test-inbox-status": cmd_test_inbox_status,
            }[args.action](args)
