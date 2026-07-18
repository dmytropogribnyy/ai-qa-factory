"""Communication repository (Final Phase II).

Transactional CRUD over the schema-v2 tables. State transitions are enforced HERE (and by DB
constraints), never by arbitrary field updates: a revision supersedes rather than mutating, an
approval is single-use (an atomic UPDATE consumes it exactly once), and an outbound message is
reserved at most once per idempotency key. Terminal states are historical/append-only. No secrets
or raw provider payloads are stored.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

from core.scout.memory.db import MemoryDB, MemoryError

# Draft-revision states.
R_DRAFT, R_PENDING, R_APPROVED, R_RESERVED, R_CONSUMED = (
    "DRAFT", "PENDING_REVIEW", "APPROVED", "RESERVED_FOR_SEND", "CONSUMED")
R_REJECTED, R_EXPIRED, R_SUPERSEDED, R_INVALIDATED = (
    "REJECTED", "EXPIRED", "SUPERSEDED", "INVALIDATED")
# Approval states.
A_PENDING, A_APPROVED, A_CONSUMED, A_REJECTED, A_EXPIRED, A_REVOKED, A_INVALIDATED = (
    "PENDING", "APPROVED", "CONSUMED", "REJECTED", "EXPIRED", "REVOKED", "INVALIDATED")
# Outbound message states.
M_PREPARED, M_RESERVED, M_IN_PROGRESS, M_ACCEPTED = (
    "PREPARED", "RESERVED", "PROVIDER_CALL_IN_PROGRESS", "ACCEPTED")
M_DELIVERED, M_BOUNCED, M_REPLIED, M_OPTED_OUT = "DELIVERED", "BOUNCED", "REPLIED", "OPTED_OUT"
M_FAILED, M_UNKNOWN, M_CANCELLED = "FAILED_DEFINITE", "OUTCOME_UNKNOWN", "CANCELLED"
# Send-attempt outcomes.
ATT_ACCEPTED, ATT_FAILED, ATT_UNKNOWN, ATT_CANCELLED = (
    "ACCEPTED", "FAILED_DEFINITE", "OUTCOME_UNKNOWN", "CANCELLED_BEFORE_PROVIDER")

# Explicit allowed state transitions. Anything not listed (terminal rewrite, state skipping, an
# unknown state) is rejected. Every accepted transition appends an immutable lifecycle event.
_REVISION_TRANSITIONS = {
    R_DRAFT: {R_PENDING, R_REJECTED, R_SUPERSEDED, R_INVALIDATED},
    R_PENDING: {R_APPROVED, R_REJECTED, R_SUPERSEDED, R_INVALIDATED},
    R_APPROVED: {R_RESERVED, R_SUPERSEDED, R_INVALIDATED},
    R_RESERVED: {R_CONSUMED, R_INVALIDATED},
}
_APPROVAL_TRANSITIONS = {
    A_PENDING: {A_APPROVED, A_REJECTED},
    A_APPROVED: {A_CONSUMED, A_REVOKED, A_EXPIRED, A_INVALIDATED},
}
_MESSAGE_TRANSITIONS = {
    M_PREPARED: {M_RESERVED, M_CANCELLED},
    M_RESERVED: {M_IN_PROGRESS, M_CANCELLED},
    M_IN_PROGRESS: {M_ACCEPTED, M_FAILED, M_UNKNOWN},
    M_ACCEPTED: {M_DELIVERED, M_BOUNCED, M_REPLIED, M_OPTED_OUT},
    M_DELIVERED: {M_REPLIED, M_OPTED_OUT},
    M_REPLIED: {M_OPTED_OUT},
}


class CommsError(MemoryError):
    pass


class CommsRepository:
    def __init__(self, db: MemoryDB) -> None:
        self.db = db

    @staticmethod
    def _event(c, subject_type: str, subject_ref: str, event: str, detail: str, at: str) -> None:
        """Append an immutable lifecycle/state event inside the caller's transaction."""
        c.execute("INSERT INTO lifecycle_events (subject_type, subject_ref, event, detail, at) "
                  "VALUES (?,?,?,?,?)", (subject_type, subject_ref, event, detail[:200], at))

    def lifecycle_events(self, subject_type: str, subject_ref: str) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.db.query(
            "SELECT * FROM lifecycle_events WHERE subject_type=? AND subject_ref=? ORDER BY event_id",
            (subject_type, subject_ref))]

    # --- draft revisions --------------------------------------------------
    def next_revision_number(self, draft_id: str) -> int:
        rows = self.db.query("SELECT MAX(revision_number) AS n FROM draft_revisions WHERE draft_id=?",
                             (draft_id,))
        return (rows[0]["n"] or 0) + 1

    def create_revision(self, rev: Dict[str, Any]) -> str:
        import json as _json
        with self.db.transaction() as c:
            c.execute(
                "INSERT INTO draft_revisions (revision_id, draft_id, revision_number, company_id, "
                "contact_id, channel, finding_id, evidence_ids, recipient_hash, subject, body, "
                "body_hash, disclosure_hash, finding_hash, evidence_hash, contact_provenance_hash, "
                "suppression_hash, generated_at, expires_at, creator, state) VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'PENDING_REVIEW')",
                (rev["revision_id"], rev["draft_id"], rev["revision_number"], rev["company_id"],
                 rev.get("contact_id", ""), rev["channel"], rev.get("finding_id", ""),
                 _json.dumps(rev.get("evidence_ids", [])), rev.get("recipient_hash", ""),
                 rev.get("subject", ""), rev.get("body", ""), rev.get("body_hash", ""),
                 rev.get("disclosure_hash", ""), rev.get("finding_hash", ""),
                 rev.get("evidence_hash", ""), rev.get("contact_provenance_hash", ""),
                 rev.get("suppression_hash", ""), rev["generated_at"], rev.get("expires_at", ""),
                 rev.get("creator", "")))
        return rev["revision_id"]

    def get_revision(self, revision_id: str) -> Optional[Dict[str, Any]]:
        rows = self.db.query("SELECT * FROM draft_revisions WHERE revision_id=?", (revision_id,))
        return dict(rows[0]) if rows else None

    def supersede_revision(self, revision_id: str, now: str = "") -> None:
        with self.db.transaction() as c:
            cur = c.execute("UPDATE draft_revisions SET state='SUPERSEDED', superseded=1 "
                            "WHERE revision_id=? AND state IN ('DRAFT','PENDING_REVIEW','APPROVED')",
                            (revision_id,))
            if cur.rowcount == 1:
                self._event(c, "revision", revision_id, "->SUPERSEDED", "edited/superseded", now)

    def transition_revision(self, revision_id: str, to_state: str, now: str) -> None:
        """Guarded draft-revision transition (rejects terminal rewrite / skipping / unknown state)."""
        rev = self.get_revision(revision_id)
        if rev is None:
            raise CommsError(f"unknown revision: {revision_id!r}")
        frm = rev["state"]
        if to_state not in _REVISION_TRANSITIONS.get(frm, frozenset()):
            raise CommsError(f"invalid_revision_transition:{frm}->{to_state}")
        superseded = 1 if to_state in (R_SUPERSEDED, R_INVALIDATED) else 0
        with self.db.transaction() as c:
            cur = c.execute("UPDATE draft_revisions SET state=?, superseded=CASE WHEN ? THEN 1 "
                            "ELSE superseded END WHERE revision_id=? AND state=?",
                            (to_state, superseded, revision_id, frm))
            if cur.rowcount != 1:
                raise CommsError(f"revision_transition_conflict:{revision_id}")
            self._event(c, "revision", revision_id, f"{frm}->{to_state}", "", now)

    def transition_approval(self, approval_id: str, to_state: str, now: str, *, reason: str = "") -> None:
        """Guarded approval transition (rejects terminal rewrite / skipping / unknown state)."""
        ap = self.get_approval(approval_id)
        if ap is None:
            raise CommsError(f"unknown approval: {approval_id!r}")
        frm = ap["state"]
        if to_state not in _APPROVAL_TRANSITIONS.get(frm, frozenset()):
            raise CommsError(f"invalid_approval_transition:{frm}->{to_state}")
        with self.db.transaction() as c:
            cur = c.execute("UPDATE approval_records SET state=?, invalidated_at=CASE WHEN ? "
                            "THEN ? ELSE invalidated_at END, invalidation_reason=? "
                            "WHERE approval_id=? AND state=?",
                            (to_state, 1 if to_state in (A_INVALIDATED, A_REVOKED, A_EXPIRED) else 0,
                             now, reason, approval_id, frm))
            if cur.rowcount != 1:
                raise CommsError(f"approval_transition_conflict:{approval_id}")
            self._event(c, "approval", approval_id, f"{frm}->{to_state}", reason, now)

    # --- approvals --------------------------------------------------------
    def create_approval(self, ap: Dict[str, Any]) -> str:
        rev = self.get_revision(ap["revision_id"])
        if rev is None:
            raise CommsError("approval references an unknown revision")
        if rev["superseded"] or rev["state"] not in (R_PENDING, R_DRAFT):
            raise CommsError("approval can only bind to a current (non-superseded) revision")
        # Proof-of-reviewed-content is mandatory: an approval can never be created without it.
        if not (ap.get("reviewed_content_hash") or "").strip():
            raise CommsError("reviewed_content_hash is required to create an approval")
        with self.db.transaction() as c:
            c.execute(
                "INSERT INTO approval_records (approval_id, revision_id, recipient_hash, body_hash, "
                "disclosure_hash, finding_hash, evidence_hash, contact_provenance_hash, "
                "suppression_hash, channel, reviewer, decision, reason, approved_at, expires_at, "
                "reviewed_content_hash, state, single_use, consumed) VALUES "
                "(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'APPROVED', 1, 0)",
                (ap["approval_id"], ap["revision_id"], ap["recipient_hash"], ap["body_hash"],
                 ap["disclosure_hash"], ap["finding_hash"], ap["evidence_hash"],
                 ap["contact_provenance_hash"], ap["suppression_hash"], ap["channel"],
                 ap["reviewer"], ap.get("decision", "approve"), ap.get("reason", ""),
                 ap["approved_at"], ap.get("expires_at", ""), ap.get("reviewed_content_hash", "")))
            c.execute("UPDATE draft_revisions SET state='APPROVED' WHERE revision_id=?",
                      (ap["revision_id"],))
            self._event(c, "approval", ap["approval_id"], "->APPROVED", ap["reviewer"],
                        ap["approved_at"])
            self._event(c, "revision", ap["revision_id"], "->APPROVED", "", ap["approved_at"])
        return ap["approval_id"]

    def get_approval(self, approval_id: str) -> Optional[Dict[str, Any]]:
        rows = self.db.query("SELECT * FROM approval_records WHERE approval_id=?", (approval_id,))
        return dict(rows[0]) if rows else None

    def reject_approval(self, approval_id: str, reviewer: str, reason: str, now: str) -> None:
        with self.db.transaction() as c:
            cur = c.execute("UPDATE approval_records SET state='REJECTED', reason=?, reviewer=? "
                            "WHERE approval_id=? AND state='PENDING'", (reason, reviewer, approval_id))
            if cur.rowcount == 1:
                self._event(c, "approval", approval_id, "->REJECTED", reason, now)

    def revoke_approval(self, approval_id: str, reason: str, now: str) -> None:
        with self.db.transaction() as c:
            cur = c.execute("UPDATE approval_records SET state='REVOKED', invalidated_at=?, "
                            "invalidation_reason=? WHERE approval_id=? AND state IN ('APPROVED','PENDING')",
                            (now, reason, approval_id))
            if cur.rowcount == 1:
                self._event(c, "approval", approval_id, "->REVOKED", reason, now)

    def invalidate_approval(self, approval_id: str, reason: str, now: str) -> None:
        with self.db.transaction() as c:
            cur = c.execute("UPDATE approval_records SET state='INVALIDATED', invalidated_at=?, "
                            "invalidation_reason=? WHERE approval_id=? AND state IN ('APPROVED','PENDING')",
                            (now, reason, approval_id))
            if cur.rowcount == 1:
                self._event(c, "approval", approval_id, "->INVALIDATED", reason, now)

    def consume_approval(self, approval_id: str) -> bool:
        """Atomic single-use: succeeds exactly once, only from APPROVED + not consumed."""
        with self.db.transaction() as c:
            cur = c.execute("UPDATE approval_records SET consumed=1, state='CONSUMED' "
                            "WHERE approval_id=? AND state='APPROVED' AND consumed=0", (approval_id,))
        return cur.rowcount == 1

    # --- outbound messages / attempts ------------------------------------
    def reserve_message(self, msg: Dict[str, Any]) -> tuple:
        """Reserve at most one message per idempotency key. Returns (message_id, created)."""
        existing = self.db.query("SELECT message_id FROM outbound_messages WHERE idempotency_key=?",
                                 (msg["idempotency_key"],))
        if existing:
            return existing[0]["message_id"], False
        try:
            with self.db.transaction() as c:
                c.execute(
                    "INSERT INTO outbound_messages (message_id, revision_id, approval_id, company_id, "
                    "contact_id, channel, provider_id, idempotency_key, state, created_at, "
                    "reserved_at, updated_at) VALUES (?,?,?,?,?,?,?,?, 'RESERVED', ?,?,?)",
                    (msg["message_id"], msg["revision_id"], msg["approval_id"], msg["company_id"],
                     msg.get("contact_id", ""), msg["channel"], msg["provider_id"],
                     msg["idempotency_key"], msg["now"], msg["now"], msg["now"]))
        except sqlite3.IntegrityError:
            row = self.db.query("SELECT message_id FROM outbound_messages WHERE idempotency_key=?",
                                (msg["idempotency_key"],))
            return (row[0]["message_id"] if row else msg["message_id"]), False
        return msg["message_id"], True

    def reserve_and_authorize(self, msg: Dict[str, Any], approval_id: str) -> tuple:
        """Atomically (one transaction): idempotency-check, consume the approval exactly once, and
        reserve the message. Returns (message_id, 'reserved' | 'idempotent_existing'). Raises
        CommsError('approval_not_consumable') — rolling back — if the approval is not consumable."""
        with self.db.transaction() as c:
            ex = c.execute("SELECT message_id FROM outbound_messages WHERE idempotency_key=?",
                           (msg["idempotency_key"],)).fetchall()
            if ex:
                return ex[0]["message_id"], "idempotent_existing"
            cur = c.execute("UPDATE approval_records SET consumed=1, state='CONSUMED' "
                            "WHERE approval_id=? AND state='APPROVED' AND consumed=0", (approval_id,))
            if cur.rowcount != 1:
                raise CommsError("approval_not_consumable")
            c.execute(
                "INSERT INTO outbound_messages (message_id, revision_id, approval_id, company_id, "
                "contact_id, channel, provider_id, idempotency_key, state, created_at, reserved_at, "
                "updated_at) VALUES (?,?,?,?,?,?,?,?, 'RESERVED', ?,?,?)",
                (msg["message_id"], msg["revision_id"], approval_id, msg["company_id"],
                 msg.get("contact_id", ""), msg["channel"], msg["provider_id"],
                 msg["idempotency_key"], msg["now"], msg["now"], msg["now"]))
            c.execute("UPDATE draft_revisions SET state='RESERVED_FOR_SEND' WHERE revision_id=?",
                      (msg["revision_id"],))
            self._event(c, "approval", approval_id, "->CONSUMED", "reserved for send", msg["now"])
            self._event(c, "message", msg["message_id"], "->RESERVED", "", msg["now"])
            self._event(c, "revision", msg["revision_id"], "->RESERVED_FOR_SEND", "", msg["now"])
        return msg["message_id"], "reserved"

    def transition_message(self, message_id: str, to_state: str, now: str, *,
                           provider_message_id: str = "", error: str = "", sent: bool = False) -> None:
        """Guarded outbound-message transition: only an ALLOWED edge succeeds; any invalid/terminal/
        skipping/unknown transition raises. Every transition appends a lifecycle event."""
        msg = self.get_message(message_id)
        if msg is None:
            raise CommsError(f"unknown message: {message_id!r}")
        frm = msg["state"]
        if to_state not in _MESSAGE_TRANSITIONS.get(frm, frozenset()):
            raise CommsError(f"invalid_message_transition:{frm}->{to_state}")
        with self.db.transaction() as c:
            cur = c.execute(
                "UPDATE outbound_messages SET state=?, updated_at=?, "
                "provider_message_id=COALESCE(NULLIF(?,''), provider_message_id), "
                "last_error=?, sent_at=CASE WHEN ? THEN ? ELSE sent_at END "
                "WHERE message_id=? AND state=?",
                (to_state, now, provider_message_id, error[:400], 1 if sent else 0, now,
                 message_id, frm))
            if cur.rowcount != 1:
                raise CommsError(f"message_transition_conflict:{message_id}")
            self._event(c, "message", message_id, f"{frm}->{to_state}", error[:200], now)

    def get_message(self, message_id: str) -> Optional[Dict[str, Any]]:
        rows = self.db.query("SELECT * FROM outbound_messages WHERE message_id=?", (message_id,))
        return dict(rows[0]) if rows else None

    def add_attempt(self, att: Dict[str, Any]) -> str:
        with self.db.transaction() as c:
            c.execute("INSERT INTO send_attempts (attempt_id, message_id, provider, request_hash, "
                      "idempotency_key, attempt_number, started_at, finished_at, outcome, "
                      "provider_response_ref, ambiguity_state, error) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                      (att["attempt_id"], att["message_id"], att["provider"], att.get("request_hash", ""),
                       att.get("idempotency_key", ""), att.get("attempt_number", 1), att["started_at"],
                       att.get("finished_at", ""), att.get("outcome", ""),
                       att.get("provider_response_ref", ""), att.get("ambiguity_state", ""),
                       att.get("error", "")[:400]))
        return att["attempt_id"]

    def finalize_attempt(self, attempt_id: str, *, outcome: str, finished_at: str,
                         provider_response_ref: str = "", ambiguity_state: str = "",
                         error: str = "") -> None:
        with self.db.transaction() as c:
            cur = c.execute(
                "UPDATE send_attempts SET outcome=?, finished_at=?, provider_response_ref=?, "
                "ambiguity_state=?, error=? WHERE attempt_id=?",
                (outcome, finished_at, provider_response_ref, ambiguity_state, error[:400],
                 attempt_id))
            if cur.rowcount != 1:
                raise CommsError(f"unknown attempt: {attempt_id!r}")

    def attempts_for(self, message_id: str) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.db.query(
            "SELECT * FROM send_attempts WHERE message_id=? ORDER BY attempt_number", (message_id,))]

    def messages_in_state(self, *states: str) -> List[Dict[str, Any]]:
        qs = ",".join("?" for _ in states)
        return [dict(r) for r in self.db.query(
            f"SELECT * FROM outbound_messages WHERE state IN ({qs})", states)]

    # --- provider + contact events ---------------------------------------
    def add_provider_event(self, ev: Dict[str, Any]) -> bool:
        """Idempotent by dedup_key. Returns True if newly inserted, False if a duplicate."""
        try:
            with self.db.transaction() as c:
                c.execute("INSERT INTO provider_events (event_id, provider, provider_version, "
                          "message_ref, thread_ref, normalized_type, provider_ts, received_ts, "
                          "metadata, signature_status, dedup_key, processing_result) "
                          "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                          (ev["event_id"], ev.get("provider", ""), ev.get("provider_version", ""),
                           ev.get("message_ref", ""), ev.get("thread_ref", ""), ev["normalized_type"],
                           ev.get("provider_ts", ""), ev["received_ts"],
                           json.dumps(ev.get("metadata", {}))[:2000], ev.get("signature_status", "n/a"),
                           ev["dedup_key"], ev.get("processing_result", "")))
            return True
        except sqlite3.IntegrityError:
            return False

    def add_contact_event(self, contact_id: str, company_id: str, event_type: str, detail: str,
                          now: str) -> None:
        with self.db.transaction() as c:
            c.execute("INSERT INTO contact_events (contact_id, company_id, event_type, detail, at) "
                      "VALUES (?,?,?,?,?)", (contact_id, company_id, event_type, detail, now))

    def contact_event_types(self, contact_id: str) -> set:
        return {r["event_type"] for r in self.db.query(
            "SELECT DISTINCT event_type FROM contact_events WHERE contact_id=?", (contact_id,))}

    # --- real persisted gate records (schema v3) --------------------------
    def record_suppression_check(self, rec: Dict[str, Any]) -> str:
        with self.db.transaction() as c:
            c.execute("INSERT OR REPLACE INTO suppression_checks (check_id, company_id, contact_id, "
                      "result, blockers, content_hash, generated_at, expires_at) VALUES (?,?,?,?,?,?,?,?)",
                      (rec["check_id"], rec["company_id"], rec.get("contact_id", ""),
                       rec.get("result", ""), json.dumps(rec.get("blockers", [])),
                       rec.get("content_hash", ""), rec["generated_at"], rec.get("expires_at", "")))
        return rec["check_id"]

    def get_suppression_check(self, check_id: str) -> Optional[Dict[str, Any]]:
        rows = self.db.query("SELECT * FROM suppression_checks WHERE check_id=?", (check_id,))
        return dict(rows[0]) if rows else None

    def record_revalidation(self, rec: Dict[str, Any]) -> str:
        with self.db.transaction() as c:
            c.execute("INSERT OR REPLACE INTO pre_send_revalidations (revalidation_id, company_id, "
                      "contact_id, revision_id, approval_id, result, blockers, content_hash, "
                      "generated_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                      (rec["revalidation_id"], rec["company_id"], rec.get("contact_id", ""),
                       rec.get("revision_id", ""), rec.get("approval_id", ""), rec.get("result", ""),
                       json.dumps(rec.get("blockers", [])), rec.get("content_hash", ""),
                       rec["generated_at"], rec.get("expires_at", "")))
        return rec["revalidation_id"]

    def get_revalidation(self, revalidation_id: str) -> Optional[Dict[str, Any]]:
        rows = self.db.query("SELECT * FROM pre_send_revalidations WHERE revalidation_id=?",
                             (revalidation_id,))
        return dict(rows[0]) if rows else None

    def record_policy_decision(self, rec: Dict[str, Any]) -> str:
        with self.db.transaction() as c:
            c.execute("INSERT OR REPLACE INTO policy_decisions (decision_id, company_id, contact_id, "
                      "channel, country, result, content_hash, generated_at, expires_at) "
                      "VALUES (?,?,?,?,?,?,?,?,?)",
                      (rec["decision_id"], rec["company_id"], rec.get("contact_id", ""),
                       rec.get("channel", "email"), rec.get("country", ""), rec.get("result", ""),
                       rec.get("content_hash", ""), rec["generated_at"], rec.get("expires_at", "")))
        return rec["decision_id"]

    def get_policy_decision(self, decision_id: str) -> Optional[Dict[str, Any]]:
        rows = self.db.query("SELECT * FROM policy_decisions WHERE decision_id=?", (decision_id,))
        return dict(rows[0]) if rows else None

    # --- controls ---------------------------------------------------------
    def set_control(self, scope: str, state: str, extra: Optional[Dict[str, Any]] = None) -> None:
        with self.db.transaction() as c:
            c.execute("INSERT INTO outreach_controls (scope, state, extra) VALUES (?,?,?) "
                      "ON CONFLICT(scope) DO UPDATE SET state=excluded.state, extra=excluded.extra",
                      (scope, state, json.dumps(extra or {})))

    def get_control(self, scope: str) -> str:
        rows = self.db.query("SELECT state FROM outreach_controls WHERE scope=?", (scope,))
        return rows[0]["state"] if rows else ("DISABLED" if scope == "__global_outreach__" else "RUNNING")

    def add_allowlist(self, normalized_value: str, note: str, now: str) -> None:
        with self.db.transaction() as c:
            c.execute("INSERT OR IGNORE INTO recipient_allowlist (normalized_value, note, added_at) "
                      "VALUES (?,?,?)", (normalized_value, note, now))

    def is_allowlisted(self, normalized_value: str) -> bool:
        return bool(self.db.query("SELECT 1 FROM recipient_allowlist WHERE normalized_value=?",
                                  (normalized_value,)))

    # --- followups / commercial ------------------------------------------
    def add_followup_plan(self, plan: Dict[str, Any]) -> None:
        with self.db.transaction() as c:
            c.execute("INSERT OR REPLACE INTO followup_plans (plan_id, company_id, contact_id, "
                      "parent_message_id, sequence_no, state, reason, created_at) "
                      "VALUES (?,?,?,?,?,?,?,?)",
                      (plan["plan_id"], plan["company_id"], plan.get("contact_id", ""),
                       plan.get("parent_message_id", ""), plan.get("sequence_no", 1),
                       plan.get("state", "ELIGIBLE"), plan.get("reason", ""), plan["created_at"]))

    def add_commercial_event(self, company_id: str, event_type: str, now: str, *, value: float = 0.0,
                             currency: str = "", source: str = "fixture") -> None:
        with self.db.transaction() as c:
            c.execute("INSERT INTO commercial_events (company_id, event_type, value, currency, "
                      "source, at) VALUES (?,?,?,?,?,?)",
                      (company_id, event_type, value, currency, source, now))

    def commercial_events(self) -> List[Dict[str, Any]]:
        return [dict(r) for r in self.db.query("SELECT * FROM commercial_events ORDER BY id")]

    def count(self, table: str) -> int:
        allowed = {"draft_revisions", "approval_records", "outbound_messages", "send_attempts",
                   "provider_events", "contact_events", "followup_plans", "commercial_events"}
        if table not in allowed:
            raise CommsError(f"unknown table: {table!r}")
        return int(self.db.query(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"])
