"""Company/site memory repository (Final Phase I).

Typed, transactional CRUD over the SQLite memory. Enforces uniqueness/integrity: a domain maps
to at most one company (cross-provider duplicates never create a second company — a conflict is
surfaced for review, never auto-merged); contacts dedup per company/channel/value; drafts can
never be marked sent (a DB CHECK backs the application invariant). All writes are idempotent
(INSERT OR REPLACE / OR IGNORE with deterministic ids) so importing existing file runs twice is
safe. Timestamps are UTC ISO strings; no secrets or raw payloads are stored.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Any, Dict, List, Optional

from core.scout.memory.db import MemoryDB, MemoryError


class CompanyConflict(MemoryError):
    """Raised when a domain already belongs to a different company (never auto-merged)."""


class SendBlocked(MemoryError):
    """Raised if anything attempts to mark a draft as sent in Final Phase I."""


class MemoryRepository:
    def __init__(self, db: MemoryDB) -> None:
        self.db = db

    # --- campaigns / companies -------------------------------------------
    def upsert_campaign(self, campaign_id: str, name: str, now: str) -> None:
        with self.db.transaction() as c:
            c.execute("INSERT INTO campaigns (campaign_id, name, created_at, updated_at) "
                      "VALUES (?,?,?,?) ON CONFLICT(campaign_id) DO UPDATE SET "
                      "name=excluded.name, updated_at=excluded.updated_at",
                      (campaign_id, name, now, now))

    def upsert_company(self, company_id: str, campaign_id: str, canonical_name: str,
                       primary_domain: str, now: str, *, identity_state: str = "confirmed_same",
                       confidence: str = "low") -> None:
        with self.db.transaction() as c:
            c.execute(
                "INSERT INTO companies (company_id, campaign_id, canonical_name, primary_domain, "
                "identity_state, confidence, first_seen_at, last_seen_at) VALUES (?,?,?,?,?,?,?,?) "
                "ON CONFLICT(company_id) DO UPDATE SET canonical_name=excluded.canonical_name, "
                "last_seen_at=excluded.last_seen_at, identity_state=excluded.identity_state",
                (company_id, campaign_id, canonical_name, primary_domain, identity_state,
                 confidence, now, now))

    def add_domain(self, company_id: str, hostname: str, relation: str = "primary") -> None:
        """Attach a domain to a company. If the hostname already belongs to a *different*
        company, raise CompanyConflict (never auto-merge)."""
        existing = self.db.query("SELECT company_id FROM domains WHERE hostname=?", (hostname,))
        if existing and existing[0]["company_id"] != company_id:
            raise CompanyConflict(f"domain {hostname!r} already belongs to "
                                  f"{existing[0]['company_id']!r}")
        with self.db.transaction() as c:
            c.execute("INSERT OR IGNORE INTO domains (company_id, hostname, relation) "
                      "VALUES (?,?,?)", (company_id, hostname, relation))

    def add_alias(self, company_id: str, alias: str) -> None:
        with self.db.transaction() as c:
            c.execute("INSERT OR IGNORE INTO company_aliases (company_id, alias) VALUES (?,?)",
                      (company_id, alias))

    def add_suppression(self, company_id: Optional[str], domain: str, mode: str, reason: str,
                        now: str) -> None:
        with self.db.transaction() as c:
            c.execute("INSERT INTO suppression (company_id, domain, mode, reason, created_at) "
                      "VALUES (?,?,?,?,?)", (company_id, domain, mode, reason, now))

    def is_suppressed(self, company_id: str, mode: Optional[str] = None) -> bool:
        if mode:
            rows = self.db.query("SELECT 1 FROM suppression WHERE company_id=? AND mode=?",
                                 (company_id, mode))
        else:
            rows = self.db.query("SELECT 1 FROM suppression WHERE company_id=?", (company_id,))
        return bool(rows)

    # --- sessions / findings / evidence ----------------------------------
    def add_session(self, session_id: str, campaign_id: str, company_id: str, url: str,
                    profile: str, now: str) -> None:
        with self.db.transaction() as c:
            c.execute("INSERT OR REPLACE INTO scan_sessions (session_id, campaign_id, company_id, "
                      "url, profile, status, started_at) VALUES (?,?,?,?,?, 'COMPLETED', ?)",
                      (session_id, campaign_id, company_id, url, profile, now))

    def upsert_finding(self, f: Dict[str, Any], session_id: str, company_id: str) -> None:
        with self.db.transaction() as c:
            c.execute(
                "INSERT OR REPLACE INTO findings (finding_id, session_id, company_id, capability, "
                "category, severity, title, root_impact_key, verification_state, lifecycle_state, "
                "client_safe, first_seen_at, last_seen_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (f["finding_id"], session_id, company_id, f.get("capability", ""),
                 f.get("category", "functional"), f.get("severity", "low"), f.get("title", ""),
                 f.get("root_impact_key", ""), f.get("verification_state", "UNVERIFIED"),
                 f.get("lifecycle_state", "ACTIVE"), 1 if f.get("is_client_safe") else 0,
                 f.get("first_seen_at", now_of(f)), f.get("last_seen_at", now_of(f))))

    def add_evidence(self, e: Dict[str, Any], session_id: str) -> None:
        with self.db.transaction() as c:
            c.execute(
                "INSERT OR REPLACE INTO evidence (evidence_id, finding_id, session_id, "
                "evidence_type, content_hash, storage_ref, sanitization_status, client_safe, "
                "retention_deadline) VALUES (?,?,?,?,?,?,?,?,?)",
                (e["evidence_id"], e.get("finding_id", ""), session_id, e.get("evidence_type", ""),
                 e.get("content_hash", ""), e.get("storage_ref", ""),
                 e.get("sanitization_status", "unsanitized"), 1 if e.get("client_safe") else 0,
                 e.get("retention_deadline", "")))

    # --- contacts ---------------------------------------------------------
    def upsert_contact(self, contact: Dict[str, Any]) -> None:
        with self.db.transaction() as c:
            c.execute(
                "INSERT INTO contacts (contact_id, company_id, channel, normalized_value, status, "
                "data_subject_category, source_category, manual_review_required, last_verified_at) "
                "VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(company_id, channel, normalized_value) "
                "DO UPDATE SET status=excluded.status, "
                "manual_review_required=excluded.manual_review_required, "
                "last_verified_at=excluded.last_verified_at",
                (contact["contact_id"], contact["company_id"], contact["channel"],
                 contact["normalized_value"], contact.get("status", "UNVERIFIED"),
                 contact.get("data_subject_category", "unknown"),
                 contact.get("source_category", ""),
                 1 if contact.get("manual_review_required") else 0,
                 contact.get("last_verified_at", "")))

    def contacts_for(self, company_id: str) -> List[sqlite3.Row]:
        return self.db.query("SELECT * FROM contacts WHERE company_id=?", (company_id,))

    # --- offers / disclosure / drafts / review ---------------------------
    def add_offer(self, offer_id: str, company_id: str, offer_type: str, rationale: str,
                  now: str) -> None:
        with self.db.transaction() as c:
            c.execute("INSERT OR REPLACE INTO audit_offers (offer_id, company_id, offer_type, "
                      "rationale, created_at) VALUES (?,?,?,?,?)",
                      (offer_id, company_id, offer_type, rationale, now))

    def add_disclosure(self, manifest_id: str, company_id: str, ready: bool, blockers: List[str],
                       now: str) -> None:
        with self.db.transaction() as c:
            c.execute("INSERT OR REPLACE INTO disclosure_manifests (manifest_id, company_id, "
                      "ready, blockers, created_at) VALUES (?,?,?,?,?)",
                      (manifest_id, company_id, 1 if ready else 0, json.dumps(blockers), now))

    def add_draft(self, draft_id: str, company_id: str, contact_id: str, channel: str,
                  content_hash: str, now: str, expires_at: str) -> None:
        with self.db.transaction() as c:
            # sent stays 0 — the CHECK (sent=0) makes "sent" unrepresentable in Final Phase I.
            c.execute("INSERT OR REPLACE INTO drafts (draft_id, company_id, contact_id, channel, "
                      "content_hash, review_state, sent, created_at, expires_at) "
                      "VALUES (?,?,?,?,?, 'PENDING_REVIEW', 0, ?, ?)",
                      (draft_id, company_id, contact_id, channel, content_hash, now, expires_at))

    def mark_draft_sent(self, draft_id: str) -> None:
        """Explicitly forbidden in Final Phase I — always raises (no send exists)."""
        raise SendBlocked("sending is not available in Final Phase I")

    def add_review_item(self, item_id: str, queue: str, subject_ref: str, company_id: Optional[str],
                        now: str) -> None:
        with self.db.transaction() as c:
            c.execute("INSERT OR REPLACE INTO review_queue (item_id, queue, subject_ref, "
                      "company_id, state, created_at) VALUES (?,?,?,?, 'PENDING', ?)",
                      (item_id, queue, subject_ref, company_id, now))

    def decide_review_item(self, item_id: str, reviewer: str, decision: str, reason: str,
                           now: str) -> None:
        with self.db.transaction() as c:
            c.execute("UPDATE review_queue SET state='DECIDED', reviewer=?, decision=?, reason=?, "
                      "decided_at=? WHERE item_id=?", (reviewer, decision, reason, now, item_id))

    def review_items(self, queue: Optional[str] = None) -> List[sqlite3.Row]:
        if queue:
            return self.db.query("SELECT * FROM review_queue WHERE queue=?", (queue,))
        return self.db.query("SELECT * FROM review_queue", ())

    # --- fingerprints / lifecycle ----------------------------------------
    def add_fingerprint(self, company_id: str, url: str, content_hash: str, metadata_hash: str,
                        now: str) -> None:
        with self.db.transaction() as c:
            c.execute("INSERT INTO site_fingerprints (company_id, url, content_hash, "
                      "metadata_hash, captured_at) VALUES (?,?,?,?,?)",
                      (company_id, url, content_hash, metadata_hash, now))

    def latest_fingerprint(self, company_id: str, url: str) -> Optional[sqlite3.Row]:
        rows = self.db.query("SELECT * FROM site_fingerprints WHERE company_id=? AND url=? "
                             "ORDER BY fingerprint_id DESC LIMIT 1", (company_id, url))
        return rows[0] if rows else None

    def add_event(self, subject_type: str, subject_ref: str, event: str, detail: str,
                  now: str) -> None:
        with self.db.transaction() as c:
            c.execute("INSERT INTO lifecycle_events (subject_type, subject_ref, event, detail, at) "
                      "VALUES (?,?,?,?,?)", (subject_type, subject_ref, event, detail, now))

    # --- counts / read ----------------------------------------------------
    def count(self, table: str) -> int:
        allowed = {"companies", "domains", "contacts", "findings", "evidence", "drafts",
                   "review_queue", "audit_offers", "disclosure_manifests", "scan_sessions",
                   "suppression", "jobs", "site_fingerprints"}
        if table not in allowed:
            raise MemoryError(f"unknown table: {table!r}")
        return int(self.db.query(f"SELECT COUNT(*) AS n FROM {table}")[0]["n"])


def now_of(f: Dict[str, Any]) -> str:
    return f.get("first_seen_at") or f.get("last_seen_at") or ""
