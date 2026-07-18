"""Transactional SQLite company/site memory — database core (Final Phase I).

A narrow, repository-owned SQLite abstraction with an explicit schema version, transactional
migrations (an interrupted migration rolls back and leaves the version unchanged), foreign keys,
uniqueness/integrity constraints, backup/restore, and fail-closed corruption detection. It stores
no secrets, no raw credentials, and no uncontrolled provider payloads; it never silently falls
back to an empty/default database.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import List, Optional, Tuple


class MemoryError(Exception):
    pass


class MemoryCorruptionError(MemoryError):
    pass


class MigrationError(MemoryError):
    pass


SCHEMA_VERSION = 3

# Each migration is (version, [DDL statements]). Applied atomically in ascending order.
_MIGRATION_1: List[str] = [
    """CREATE TABLE campaigns (
        campaign_id TEXT PRIMARY KEY, name TEXT NOT NULL, config_version INTEGER NOT NULL DEFAULT 1,
        status TEXT NOT NULL DEFAULT 'ACTIVE', created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE companies (
        company_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL,
        canonical_name TEXT NOT NULL DEFAULT '', primary_domain TEXT NOT NULL DEFAULT '',
        identity_state TEXT NOT NULL DEFAULT 'unknown', confidence TEXT NOT NULL DEFAULT 'low',
        first_seen_at TEXT NOT NULL, last_seen_at TEXT NOT NULL,
        FOREIGN KEY (campaign_id) REFERENCES campaigns(campaign_id) ON DELETE CASCADE
    )""",
    """CREATE TABLE company_aliases (
        alias_id INTEGER PRIMARY KEY AUTOINCREMENT, company_id TEXT NOT NULL, alias TEXT NOT NULL,
        FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE,
        UNIQUE (company_id, alias)
    )""",
    """CREATE TABLE domains (
        domain_id INTEGER PRIMARY KEY AUTOINCREMENT, company_id TEXT NOT NULL,
        hostname TEXT NOT NULL, relation TEXT NOT NULL DEFAULT 'unknown',
        FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE,
        UNIQUE (hostname)
    )""",
    """CREATE TABLE suppression (
        suppression_id INTEGER PRIMARY KEY AUTOINCREMENT, company_id TEXT, domain TEXT,
        mode TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
        FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE
    )""",
    """CREATE TABLE scan_sessions (
        session_id TEXT PRIMARY KEY, campaign_id TEXT NOT NULL, company_id TEXT NOT NULL,
        url TEXT NOT NULL DEFAULT '', profile TEXT NOT NULL DEFAULT 'unknown',
        status TEXT NOT NULL DEFAULT 'COMPLETED', started_at TEXT NOT NULL,
        FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE
    )""",
    """CREATE TABLE findings (
        finding_id TEXT NOT NULL, session_id TEXT NOT NULL, company_id TEXT NOT NULL,
        capability TEXT NOT NULL DEFAULT '', category TEXT NOT NULL DEFAULT 'functional',
        severity TEXT NOT NULL DEFAULT 'low', title TEXT NOT NULL DEFAULT '',
        root_impact_key TEXT NOT NULL DEFAULT '', verification_state TEXT NOT NULL DEFAULT 'UNVERIFIED',
        lifecycle_state TEXT NOT NULL DEFAULT 'ACTIVE', client_safe INTEGER NOT NULL DEFAULT 0,
        first_seen_at TEXT NOT NULL DEFAULT '', last_seen_at TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (finding_id, session_id),
        FOREIGN KEY (session_id) REFERENCES scan_sessions(session_id) ON DELETE CASCADE
    )""",
    """CREATE TABLE evidence (
        evidence_id TEXT PRIMARY KEY, finding_id TEXT NOT NULL DEFAULT '',
        session_id TEXT NOT NULL, evidence_type TEXT NOT NULL DEFAULT '',
        content_hash TEXT NOT NULL DEFAULT '', storage_ref TEXT NOT NULL DEFAULT '',
        sanitization_status TEXT NOT NULL DEFAULT 'unsanitized', client_safe INTEGER NOT NULL DEFAULT 0,
        retention_deadline TEXT NOT NULL DEFAULT '',
        FOREIGN KEY (session_id) REFERENCES scan_sessions(session_id) ON DELETE CASCADE
    )""",
    """CREATE TABLE contacts (
        contact_id TEXT PRIMARY KEY, company_id TEXT NOT NULL, channel TEXT NOT NULL,
        normalized_value TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'UNVERIFIED',
        data_subject_category TEXT NOT NULL DEFAULT 'unknown', source_category TEXT NOT NULL DEFAULT '',
        manual_review_required INTEGER NOT NULL DEFAULT 0, last_verified_at TEXT NOT NULL DEFAULT '',
        FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE,
        UNIQUE (company_id, channel, normalized_value)
    )""",
    """CREATE TABLE site_fingerprints (
        fingerprint_id INTEGER PRIMARY KEY AUTOINCREMENT, company_id TEXT NOT NULL,
        url TEXT NOT NULL DEFAULT '', content_hash TEXT NOT NULL DEFAULT '',
        metadata_hash TEXT NOT NULL DEFAULT '', captured_at TEXT NOT NULL,
        FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE
    )""",
    """CREATE TABLE audit_offers (
        offer_id TEXT PRIMARY KEY, company_id TEXT NOT NULL, offer_type TEXT NOT NULL,
        rationale TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
        FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE
    )""",
    """CREATE TABLE disclosure_manifests (
        manifest_id TEXT PRIMARY KEY, company_id TEXT NOT NULL, ready INTEGER NOT NULL DEFAULT 0,
        blockers TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
        FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE
    )""",
    """CREATE TABLE drafts (
        draft_id TEXT PRIMARY KEY, company_id TEXT NOT NULL, contact_id TEXT NOT NULL DEFAULT '',
        channel TEXT NOT NULL DEFAULT 'email', content_hash TEXT NOT NULL DEFAULT '',
        review_state TEXT NOT NULL DEFAULT 'PENDING_REVIEW', sent INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL, expires_at TEXT NOT NULL DEFAULT '',
        FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE,
        CHECK (sent = 0)
    )""",
    """CREATE TABLE review_queue (
        item_id TEXT PRIMARY KEY, queue TEXT NOT NULL, subject_ref TEXT NOT NULL DEFAULT '',
        company_id TEXT, state TEXT NOT NULL DEFAULT 'PENDING', reviewer TEXT NOT NULL DEFAULT '',
        decision TEXT NOT NULL DEFAULT '', reason TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL, decided_at TEXT NOT NULL DEFAULT '',
        FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE
    )""",
    """CREATE TABLE lifecycle_events (
        event_id INTEGER PRIMARY KEY AUTOINCREMENT, subject_type TEXT NOT NULL,
        subject_ref TEXT NOT NULL, event TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '',
        at TEXT NOT NULL
    )""",
    """CREATE TABLE jobs (
        job_id TEXT PRIMARY KEY, queue TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}',
        state TEXT NOT NULL DEFAULT 'PENDING', attempts INTEGER NOT NULL DEFAULT 0,
        max_attempts INTEGER NOT NULL DEFAULT 3, lease_owner TEXT NOT NULL DEFAULT '',
        lease_expires_at TEXT NOT NULL DEFAULT '', last_error TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL, updated_at TEXT NOT NULL
    )""",
    """CREATE TABLE retention_state (
        subject_ref TEXT PRIMARY KEY, klass TEXT NOT NULL DEFAULT '',
        state TEXT NOT NULL DEFAULT 'ACTIVE', purge_after TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL
    )""",
    "CREATE INDEX idx_findings_company ON findings(company_id)",
    "CREATE INDEX idx_contacts_company ON contacts(company_id)",
    "CREATE INDEX idx_jobs_queue_state ON jobs(queue, state)",
]

# Final Phase II — approved communication history (additive; v1 tables + no-send drafts kept).
_MIGRATION_2: List[str] = [
    """CREATE TABLE draft_revisions (
        revision_id TEXT PRIMARY KEY, draft_id TEXT NOT NULL, revision_number INTEGER NOT NULL,
        company_id TEXT NOT NULL, contact_id TEXT NOT NULL DEFAULT '', channel TEXT NOT NULL,
        finding_id TEXT NOT NULL DEFAULT '', evidence_ids TEXT NOT NULL DEFAULT '[]',
        recipient_hash TEXT NOT NULL DEFAULT '', subject TEXT NOT NULL DEFAULT '',
        body TEXT NOT NULL DEFAULT '', body_hash TEXT NOT NULL DEFAULT '',
        disclosure_hash TEXT NOT NULL DEFAULT '', finding_hash TEXT NOT NULL DEFAULT '',
        evidence_hash TEXT NOT NULL DEFAULT '', contact_provenance_hash TEXT NOT NULL DEFAULT '',
        suppression_hash TEXT NOT NULL DEFAULT '', generated_at TEXT NOT NULL,
        expires_at TEXT NOT NULL DEFAULT '', creator TEXT NOT NULL DEFAULT '',
        state TEXT NOT NULL DEFAULT 'DRAFT', superseded INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE,
        UNIQUE (draft_id, revision_number)
    )""",
    """CREATE TABLE approval_records (
        approval_id TEXT PRIMARY KEY, revision_id TEXT NOT NULL, recipient_hash TEXT NOT NULL,
        body_hash TEXT NOT NULL, disclosure_hash TEXT NOT NULL, finding_hash TEXT NOT NULL,
        evidence_hash TEXT NOT NULL, contact_provenance_hash TEXT NOT NULL,
        suppression_hash TEXT NOT NULL, channel TEXT NOT NULL, reviewer TEXT NOT NULL,
        decision TEXT NOT NULL, reason TEXT NOT NULL DEFAULT '', approved_at TEXT NOT NULL,
        expires_at TEXT NOT NULL DEFAULT '', invalidated_at TEXT NOT NULL DEFAULT '',
        invalidation_reason TEXT NOT NULL DEFAULT '', reviewed_content_hash TEXT NOT NULL DEFAULT '',
        state TEXT NOT NULL DEFAULT 'PENDING', single_use INTEGER NOT NULL DEFAULT 1,
        consumed INTEGER NOT NULL DEFAULT 0,
        FOREIGN KEY (revision_id) REFERENCES draft_revisions(revision_id) ON DELETE CASCADE,
        CHECK (consumed IN (0,1))
    )""",
    """CREATE TABLE outbound_messages (
        message_id TEXT PRIMARY KEY, revision_id TEXT NOT NULL, approval_id TEXT NOT NULL,
        company_id TEXT NOT NULL, contact_id TEXT NOT NULL DEFAULT '', channel TEXT NOT NULL,
        provider_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'PREPARED',
        provider_message_id TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL,
        reserved_at TEXT NOT NULL DEFAULT '', sent_at TEXT NOT NULL DEFAULT '',
        updated_at TEXT NOT NULL, last_error TEXT NOT NULL DEFAULT '',
        FOREIGN KEY (revision_id) REFERENCES draft_revisions(revision_id) ON DELETE CASCADE,
        FOREIGN KEY (approval_id) REFERENCES approval_records(approval_id) ON DELETE CASCADE,
        UNIQUE (idempotency_key)
    )""",
    """CREATE TABLE send_attempts (
        attempt_id TEXT PRIMARY KEY, message_id TEXT NOT NULL, provider TEXT NOT NULL,
        request_hash TEXT NOT NULL DEFAULT '', idempotency_key TEXT NOT NULL DEFAULT '',
        attempt_number INTEGER NOT NULL DEFAULT 1, started_at TEXT NOT NULL,
        finished_at TEXT NOT NULL DEFAULT '', outcome TEXT NOT NULL DEFAULT '',
        provider_response_ref TEXT NOT NULL DEFAULT '', ambiguity_state TEXT NOT NULL DEFAULT '',
        error TEXT NOT NULL DEFAULT '',
        FOREIGN KEY (message_id) REFERENCES outbound_messages(message_id) ON DELETE CASCADE
    )""",
    """CREATE TABLE provider_events (
        event_id TEXT PRIMARY KEY, provider TEXT NOT NULL DEFAULT '',
        provider_version TEXT NOT NULL DEFAULT '', message_ref TEXT NOT NULL DEFAULT '',
        thread_ref TEXT NOT NULL DEFAULT '', normalized_type TEXT NOT NULL,
        provider_ts TEXT NOT NULL DEFAULT '', received_ts TEXT NOT NULL,
        metadata TEXT NOT NULL DEFAULT '{}', signature_status TEXT NOT NULL DEFAULT 'n/a',
        dedup_key TEXT NOT NULL, processing_result TEXT NOT NULL DEFAULT '',
        UNIQUE (dedup_key)
    )""",
    """CREATE TABLE contact_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, contact_id TEXT NOT NULL, company_id TEXT NOT NULL,
        event_type TEXT NOT NULL, detail TEXT NOT NULL DEFAULT '', at TEXT NOT NULL,
        FOREIGN KEY (contact_id) REFERENCES contacts(contact_id) ON DELETE CASCADE
    )""",
    """CREATE TABLE followup_plans (
        plan_id TEXT PRIMARY KEY, company_id TEXT NOT NULL, contact_id TEXT NOT NULL DEFAULT '',
        parent_message_id TEXT NOT NULL DEFAULT '', sequence_no INTEGER NOT NULL DEFAULT 1,
        state TEXT NOT NULL DEFAULT 'ELIGIBLE', reason TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL,
        FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE
    )""",
    """CREATE TABLE commercial_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT, company_id TEXT NOT NULL DEFAULT '',
        event_type TEXT NOT NULL, value REAL NOT NULL DEFAULT 0, currency TEXT NOT NULL DEFAULT '',
        source TEXT NOT NULL DEFAULT 'fixture', at TEXT NOT NULL
    )""",
    """CREATE TABLE outreach_controls (
        scope TEXT PRIMARY KEY, state TEXT NOT NULL DEFAULT 'DISABLED', extra TEXT NOT NULL DEFAULT '{}'
    )""",
    """CREATE TABLE recipient_allowlist (
        normalized_value TEXT PRIMARY KEY, note TEXT NOT NULL DEFAULT '', added_at TEXT NOT NULL DEFAULT ''
    )""",
    # Sending is DISABLED by default: seed the global outreach control off.
    "INSERT INTO outreach_controls (scope, state) VALUES ('__global_outreach__', 'DISABLED')",
    "CREATE INDEX idx_revisions_draft ON draft_revisions(draft_id)",
    "CREATE INDEX idx_messages_state ON outbound_messages(state)",
    "CREATE INDEX idx_provider_events_type ON provider_events(normalized_type)",
]

# Final Independent Acceptance (v2.0.1) — complete contact provenance and real, persisted gate
# records (suppression checks, pre-send revalidations, policy decisions). Additive: all v1/v2
# tables and no-send draft history are preserved. Synthetic string references (e.g. "reval-live")
# are replaced by rows with resolvable immutable ids, content hashes, and expiry.
_MIGRATION_3: List[str] = [
    """CREATE TABLE contact_provenance (
        provenance_id TEXT PRIMARY KEY, contact_id TEXT NOT NULL, company_id TEXT NOT NULL,
        source_category TEXT NOT NULL DEFAULT '', source_url TEXT NOT NULL DEFAULT '',
        source_evidence_ref TEXT NOT NULL DEFAULT '', extraction_method TEXT NOT NULL DEFAULT '',
        observed_at TEXT NOT NULL DEFAULT '', last_verified_at TEXT NOT NULL DEFAULT '',
        freshness_deadline TEXT NOT NULL DEFAULT '',
        publicly_published_for_contact INTEGER NOT NULL DEFAULT 0,
        terms_review_status TEXT NOT NULL DEFAULT 'unreviewed', source_version TEXT NOT NULL DEFAULT '',
        confidence TEXT NOT NULL DEFAULT 'low', data_subject_category TEXT NOT NULL DEFAULT 'unknown',
        person_class TEXT NOT NULL DEFAULT 'generic', manual_review_required INTEGER NOT NULL DEFAULT 0,
        manual_review_ref TEXT NOT NULL DEFAULT '', named_person_review_result TEXT NOT NULL DEFAULT '',
        suppression_check_ref TEXT NOT NULL DEFAULT '', normalized_source_hash TEXT NOT NULL DEFAULT '',
        state TEXT NOT NULL DEFAULT 'ACTIVE', created_at TEXT NOT NULL,
        FOREIGN KEY (contact_id) REFERENCES contacts(contact_id) ON DELETE CASCADE,
        CHECK (state IN ('ACTIVE','SUPERSEDED')),
        CHECK (publicly_published_for_contact IN (0,1)),
        CHECK (manual_review_required IN (0,1))
    )""",
    """CREATE TABLE suppression_checks (
        check_id TEXT PRIMARY KEY, company_id TEXT NOT NULL, contact_id TEXT NOT NULL DEFAULT '',
        result TEXT NOT NULL DEFAULT '', blockers TEXT NOT NULL DEFAULT '[]',
        content_hash TEXT NOT NULL DEFAULT '', generated_at TEXT NOT NULL,
        expires_at TEXT NOT NULL DEFAULT '',
        FOREIGN KEY (company_id) REFERENCES companies(company_id) ON DELETE CASCADE
    )""",
    """CREATE TABLE pre_send_revalidations (
        revalidation_id TEXT PRIMARY KEY, company_id TEXT NOT NULL, contact_id TEXT NOT NULL DEFAULT '',
        revision_id TEXT NOT NULL DEFAULT '', approval_id TEXT NOT NULL DEFAULT '',
        result TEXT NOT NULL DEFAULT '', blockers TEXT NOT NULL DEFAULT '[]',
        content_hash TEXT NOT NULL DEFAULT '', generated_at TEXT NOT NULL,
        expires_at TEXT NOT NULL DEFAULT ''
    )""",
    """CREATE TABLE policy_decisions (
        decision_id TEXT PRIMARY KEY, company_id TEXT NOT NULL, contact_id TEXT NOT NULL DEFAULT '',
        channel TEXT NOT NULL DEFAULT 'email', country TEXT NOT NULL DEFAULT '',
        result TEXT NOT NULL DEFAULT '', content_hash TEXT NOT NULL DEFAULT '',
        generated_at TEXT NOT NULL, expires_at TEXT NOT NULL DEFAULT ''
    )""",
    "CREATE INDEX idx_provenance_contact ON contact_provenance(contact_id, state)",
    "CREATE INDEX idx_suppression_checks_company ON suppression_checks(company_id)",
]

MIGRATIONS: List[Tuple[int, List[str]]] = [
    (1, _MIGRATION_1), (2, _MIGRATION_2), (3, _MIGRATION_3)]


class MemoryDB:
    """A narrow SQLite handle. All writes go through repository methods (this owns schema)."""

    def __init__(self, path: str, migrations: Optional[List[Tuple[int, List[str]]]] = None) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._conn = sqlite3.connect(str(self.path), isolation_level=None)
        except sqlite3.Error as exc:  # unreadable/locked file
            raise MemoryError(f"cannot open database: {exc}") from exc
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._verify_integrity_on_open()
        self.migrate(migrations or MIGRATIONS)

    # --- integrity --------------------------------------------------------
    def _verify_integrity_on_open(self) -> None:
        try:
            row = self._conn.execute("PRAGMA integrity_check").fetchone()
        except sqlite3.DatabaseError as exc:
            raise MemoryCorruptionError(f"database is corrupt: {exc}") from exc
        if row is None or (row[0] or "").lower() != "ok":
            raise MemoryCorruptionError(f"integrity check failed: {row[0] if row else 'no result'}")

    def integrity_ok(self) -> bool:
        try:
            row = self._conn.execute("PRAGMA integrity_check").fetchone()
            fk = self._conn.execute("PRAGMA foreign_key_check").fetchall()
        except sqlite3.DatabaseError:
            return False
        return bool(row) and (row[0] or "").lower() == "ok" and not fk

    # --- migrations -------------------------------------------------------
    def current_version(self) -> int:
        self._conn.execute("CREATE TABLE IF NOT EXISTS schema_meta "
                           "(id INTEGER PRIMARY KEY CHECK (id=1), version INTEGER NOT NULL)")
        row = self._conn.execute("SELECT version FROM schema_meta WHERE id=1").fetchone()
        return int(row["version"]) if row else 0

    def migrate(self, migrations: List[Tuple[int, List[str]]]) -> None:
        version = self.current_version()
        for target, statements in sorted(migrations, key=lambda m: m[0]):
            if target <= version:
                continue
            try:
                self._conn.execute("BEGIN")
                for stmt in statements:
                    self._conn.execute(stmt)
                self._conn.execute("INSERT OR REPLACE INTO schema_meta (id, version) VALUES (1, ?)",
                                   (target,))
                self._conn.execute("COMMIT")
            except sqlite3.Error as exc:
                # An interrupted/failed migration rolls back atomically; version is unchanged.
                self._conn.execute("ROLLBACK")
                raise MigrationError(f"migration to v{target} failed and was rolled back: {exc}") from exc
            version = target

    # --- transactions -----------------------------------------------------
    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        return self._conn.execute(sql, params)

    def query(self, sql: str, params: tuple = ()) -> List[sqlite3.Row]:
        return self._conn.execute(sql, params).fetchall()

    def transaction(self):
        return _Transaction(self._conn)

    # --- backup / restore -------------------------------------------------
    def backup(self, dest_path: str) -> str:
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(str(dest)) as bck:
            self._conn.backup(bck)
        return str(dest)

    @staticmethod
    def restore(backup_path: str, dest_path: str) -> "MemoryDB":
        src, dest = Path(backup_path), Path(dest_path)
        if not src.exists():
            raise MemoryError(f"backup not found: {backup_path}")
        dest.parent.mkdir(parents=True, exist_ok=True)
        # Verify the backup opens + passes integrity before replacing the destination.
        probe = sqlite3.connect(str(src))
        try:
            row = probe.execute("PRAGMA integrity_check").fetchone()
            if not row or (row[0] or "").lower() != "ok":
                raise MemoryCorruptionError("backup failed integrity check; refusing to restore")
        finally:
            probe.close()
        import shutil
        shutil.copyfile(src, dest)
        return MemoryDB(str(dest))

    def close(self) -> None:
        try:
            self._conn.close()
        except sqlite3.Error:
            pass


class _Transaction:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def __enter__(self):
        self._conn.execute("BEGIN")
        return self._conn

    def __exit__(self, exc_type, exc, tb):
        if exc_type is None:
            self._conn.execute("COMMIT")
        else:
            self._conn.execute("ROLLBACK")
        return False
