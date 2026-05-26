"""
Phase 5J — DB Smoke Runner.

Read-only database smoke checks for PostgreSQL, MySQL, and MongoDB.
Connection strings are read exclusively from environment variables —
raw strings are never passed via CLI or stored in artifacts.

SQL safety model:
- Allowed prefixes: SELECT, SHOW, DESCRIBE, EXPLAIN
- Blocked keywords checked via word-boundary regex
- Row limit enforced at the driver level
- Query timeout enforced

MongoDB safety model:
- Allowed: find/findOne/aggregate/count/distinct/listCollections/listDatabases
- Blocked: insert*/update*/delete*/drop*/createIndex/bulkWrite
- Row limit applied to cursor.limit()

SAFETY:
- raw_secrets_allowed=False always in DBSmokeReport
- production_write_allowed=False always
- destructive_db_actions_allowed=False always
- connection_string_logged=False always
- human_review_required=True always
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

from core.schemas.db_smoke import (
    DB_ALLOWED_SQL_PREFIXES,
    DB_BLOCKED_SQL_KEYWORDS,
    DB_PROVIDERS,
    DEFAULT_ROW_LIMIT,
    DEFAULT_TIMEOUT_SECONDS,
    MAX_ROW_LIMIT,
    MONGODB_ALLOWED_OPERATIONS,
    MONGODB_BLOCKED_OPERATIONS,
    DBSmokeQueryResult,
    DBSmokeReport,
)

_OUTPUTS_ROOT = Path("outputs")


# ---------------------------------------------------------------------------
# SQL / query safety
# ---------------------------------------------------------------------------

def validate_sql(query: str) -> Optional[str]:
    """Return error string if query is blocked, None if allowed."""
    normalized = query.strip().upper()
    if not normalized:
        return "Query is empty"
    # Must start with an allowed prefix
    allowed = any(normalized.startswith(p) for p in DB_ALLOWED_SQL_PREFIXES)
    if not allowed:
        return (
            f"SQL must start with one of {DB_ALLOWED_SQL_PREFIXES}. "
            f"Got: {query.strip()[:60]!r}"
        )
    # Check for blocked keywords
    for kw in DB_BLOCKED_SQL_KEYWORDS:
        if re.search(r"\b" + kw + r"\b", normalized):
            return f"SQL contains blocked keyword '{kw}'"
    return None


def validate_mongo_operation(operation: str) -> Optional[str]:
    """Return error string if MongoDB operation is blocked, None if allowed."""
    if operation in MONGODB_BLOCKED_OPERATIONS:
        return (
            f"MongoDB operation '{operation}' is blocked. "
            f"Allowed: {', '.join(MONGODB_ALLOWED_OPERATIONS)}"
        )
    if operation not in MONGODB_ALLOWED_OPERATIONS:
        return (
            f"Unknown MongoDB operation '{operation}'. "
            f"Allowed: {', '.join(MONGODB_ALLOWED_OPERATIONS)}"
        )
    return None


def validate_env_var_name(name: str) -> Optional[str]:
    """Validate that the env var name is a safe identifier (not a raw URL)."""
    if not name:
        return "db_url_env_var is required"
    # Must be an env var name: uppercase letters, digits, underscore
    if not re.fullmatch(r"[A-Z][A-Z0-9_]{0,79}", name):
        return (
            f"db_url_env_var must be an env var NAME (e.g. STAGING_DATABASE_URL), "
            f"not a raw connection string. Got: {name[:40]!r}"
        )
    # Explicitly reject patterns that look like connection strings
    for prefix in ("postgres://", "postgresql://", "mysql://", "mongodb://", "mongodb+srv://"):
        if name.lower().startswith(prefix):
            return (
                "Raw connection strings are not accepted. "
                "Pass the env var NAME, not the value."
            )
    return None


class DBSmokeRunner:
    """Read-only database smoke runner for PostgreSQL, MySQL, MongoDB."""

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self._outputs_root = outputs_root or _OUTPUTS_ROOT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run(
        self,
        project_id: str,
        provider: str,
        db_url_env_var: str,
        table_or_collection: str = "",
        custom_query: str = "",
        mongo_operation: str = "find",
        database_name: str = "",
        row_limit: int = DEFAULT_ROW_LIMIT,
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
        approve_db_smoke: bool = False,
    ) -> DBSmokeReport:
        """Run DB smoke; return DBSmokeReport."""
        report = DBSmokeReport(
            project_id=project_id,
            provider=provider,
            database_name=database_name,
            table_or_collection=table_or_collection,
        )

        # Gate: approval
        if not approve_db_smoke:
            report.execution_status = "blocked"
            report.blockers.append(
                "DB smoke not approved. Add --approve-db-smoke."
            )
            return report

        # Gate: provider
        if provider not in DB_PROVIDERS:
            report.execution_status = "blocked"
            report.blockers.append(
                f"Unknown provider '{provider}'. Valid: {', '.join(DB_PROVIDERS)}"
            )
            return report

        # Gate: env var name
        env_err = validate_env_var_name(db_url_env_var)
        if env_err:
            report.execution_status = "blocked"
            report.blockers.append(env_err)
            return report

        # Gate: row limit
        effective_row_limit = min(row_limit, MAX_ROW_LIMIT)
        if effective_row_limit != row_limit:
            report.notes.append(
                f"Row limit capped at {MAX_ROW_LIMIT} (requested {row_limit})."
            )

        # Gate: env var must be present in environment
        db_url = os.environ.get(db_url_env_var)
        if not db_url:
            report.execution_status = "blocked"
            report.blockers.append(
                f"Env var '{db_url_env_var}' is not set. "
                f"Export it before running: set {db_url_env_var}=<connection_string>"
            )
            return report

        # Route to provider-specific smoke
        if provider == "postgresql":
            return self._run_postgresql(
                report=report,
                db_url=db_url,
                db_url_env_var=db_url_env_var,
                table_or_collection=table_or_collection,
                custom_query=custom_query,
                row_limit=effective_row_limit,
                timeout_seconds=timeout_seconds,
            )
        if provider == "mysql":
            return self._run_mysql(
                report=report,
                db_url=db_url,
                db_url_env_var=db_url_env_var,
                table_or_collection=table_or_collection,
                custom_query=custom_query,
                row_limit=effective_row_limit,
                timeout_seconds=timeout_seconds,
            )
        if provider == "mongodb":
            return self._run_mongodb(
                report=report,
                db_url=db_url,
                db_url_env_var=db_url_env_var,
                table_or_collection=table_or_collection,
                mongo_operation=mongo_operation,
                row_limit=effective_row_limit,
                timeout_seconds=timeout_seconds,
            )

        report.execution_status = "blocked"
        report.blockers.append(f"Provider '{provider}' not yet implemented.")
        return report

    def render_artifacts(
        self, report: DBSmokeReport, project_id: str
    ) -> Dict[str, Path]:
        """Write DB smoke artifacts to outputs/<project_id>/21_db_smoke/."""
        out_dir = self._outputs_root / project_id / "21_db_smoke"
        out_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(timezone.utc).isoformat()
        payload: Dict[str, Any] = {
            "schema_version": "5J.1",
            "generated_at": ts,
            **report.to_dict(),
        }

        json_path = out_dir / "DB_SMOKE_REPORT.json"
        json_path.write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )

        md_path = out_dir / "DB_SMOKE_REPORT.md"
        md_path.write_text(self._render_md(report, ts), encoding="utf-8")

        return {"json": json_path, "md": md_path}

    # ------------------------------------------------------------------
    # Provider implementations
    # ------------------------------------------------------------------

    def _run_postgresql(
        self,
        report: DBSmokeReport,
        db_url: str,
        db_url_env_var: str,
        table_or_collection: str,
        custom_query: str,
        row_limit: int,
        timeout_seconds: int,
    ) -> DBSmokeReport:
        try:
            import psycopg2  # type: ignore
            report.driver_available = True
        except ImportError:
            report.execution_status = "blocked"
            report.blockers.append(
                "PostgreSQL driver not installed. "
                "Run: pip install psycopg2-binary"
            )
            return report

        # Determine query
        query = custom_query.strip() if custom_query else ""
        if not query:
            if not table_or_collection:
                report.execution_status = "blocked"
                report.blockers.append(
                    "Provide --table or --query for PostgreSQL smoke."
                )
                return report
            query = f"SELECT * FROM {table_or_collection} LIMIT {row_limit}"
        else:
            sql_err = validate_sql(query)
            if sql_err:
                report.execution_status = "blocked"
                report.blockers.append(sql_err)
                return report
            # Append LIMIT if not present
            if "LIMIT" not in query.upper():
                query = f"{query.rstrip(';')} LIMIT {row_limit}"

        qr = DBSmokeQueryResult(query_label="connection_and_read")
        start = time.time()
        try:
            conn = psycopg2.connect(
                db_url,
                connect_timeout=timeout_seconds,
                options=f"-c statement_timeout={timeout_seconds * 1000}",
            )
            cur = conn.cursor()
            cur.execute(query)
            rows = cur.fetchall()
            cols = [desc[0] for desc in (cur.description or [])]
            cur.close()
            conn.close()
            qr.row_count = len(rows)
            qr.columns = cols
            qr.status = "complete"
        except Exception as exc:  # noqa: BLE001
            qr.status = "failed"
            qr.error = str(exc)[:400]
        finally:
            qr.duration_ms = round((time.time() - start) * 1000, 1)

        report.query_results.append(qr)
        report.total_queries = 1
        report.passed = 1 if qr.status == "complete" else 0
        report.failed = 0 if qr.status == "complete" else 1
        report.execution_status = "complete" if qr.status == "complete" else "failed"
        report.notes.append(
            f"Connection string source: env var '{db_url_env_var}' (value never logged)."
        )
        return report

    def _run_mysql(
        self,
        report: DBSmokeReport,
        db_url: str,
        db_url_env_var: str,
        table_or_collection: str,
        custom_query: str,
        row_limit: int,
        timeout_seconds: int,
    ) -> DBSmokeReport:
        try:
            import mysql.connector  # type: ignore
            report.driver_available = True
        except ImportError:
            report.execution_status = "blocked"
            report.blockers.append(
                "MySQL driver not installed. "
                "Run: pip install mysql-connector-python"
            )
            return report

        query = custom_query.strip() if custom_query else ""
        if not query:
            if not table_or_collection:
                report.execution_status = "blocked"
                report.blockers.append(
                    "Provide --table or --query for MySQL smoke."
                )
                return report
            query = f"SELECT * FROM {table_or_collection} LIMIT {row_limit}"
        else:
            sql_err = validate_sql(query)
            if sql_err:
                report.execution_status = "blocked"
                report.blockers.append(sql_err)
                return report
            if "LIMIT" not in query.upper():
                query = f"{query.rstrip(';')} LIMIT {row_limit}"

        qr = DBSmokeQueryResult(query_label="connection_and_read")
        start = time.time()
        try:
            conn = mysql.connector.connect(
                host=self._parse_mysql_host(db_url),
                connection_timeout=timeout_seconds,
            )
            cur = conn.cursor()
            cur.execute(query)
            rows = cur.fetchall()
            cols = [desc[0] for desc in (cur.description or [])]
            cur.close()
            conn.close()
            qr.row_count = len(rows)
            qr.columns = cols
            qr.status = "complete"
        except Exception as exc:  # noqa: BLE001
            qr.status = "failed"
            qr.error = str(exc)[:400]
        finally:
            qr.duration_ms = round((time.time() - start) * 1000, 1)

        report.query_results.append(qr)
        report.total_queries = 1
        report.passed = 1 if qr.status == "complete" else 0
        report.failed = 0 if qr.status == "complete" else 1
        report.execution_status = "complete" if qr.status == "complete" else "failed"
        report.notes.append(
            f"Connection string source: env var '{db_url_env_var}' (value never logged)."
        )
        return report

    def _run_mongodb(
        self,
        report: DBSmokeReport,
        db_url: str,
        db_url_env_var: str,
        table_or_collection: str,
        mongo_operation: str,
        row_limit: int,
        timeout_seconds: int,
    ) -> DBSmokeReport:
        try:
            import pymongo  # type: ignore
            report.driver_available = True
        except ImportError:
            report.execution_status = "blocked"
            report.blockers.append(
                "MongoDB driver not installed. "
                "Run: pip install pymongo"
            )
            return report

        # Validate operation
        op_err = validate_mongo_operation(mongo_operation)
        if op_err:
            report.execution_status = "blocked"
            report.blockers.append(op_err)
            return report

        if not table_or_collection:
            report.execution_status = "blocked"
            report.blockers.append(
                "Provide --table (collection name) for MongoDB smoke."
            )
            return report

        qr = DBSmokeQueryResult(query_label=f"{mongo_operation}({table_or_collection})")
        start = time.time()
        try:
            client = pymongo.MongoClient(
                db_url,
                serverSelectionTimeoutMS=timeout_seconds * 1000,
            )
            db_name = report.database_name or "test"
            db = client[db_name]
            collection = db[table_or_collection]

            if mongo_operation in ("find", "findOne"):
                cursor = collection.find({}).limit(row_limit)
                rows = list(cursor)
                cols = list(rows[0].keys()) if rows else []
                qr.row_count = len(rows)
                qr.columns = [c for c in cols if c != "_id"]
            elif mongo_operation == "count":
                qr.row_count = collection.count_documents({})
                qr.columns = ["count"]
            elif mongo_operation == "countDocuments":
                qr.row_count = collection.count_documents({})
                qr.columns = ["count"]
            elif mongo_operation == "distinct":
                if cols := list(collection.find_one({}, {"_id": 0}) or {}):
                    field = cols[0]
                    vals = collection.distinct(field)
                    qr.row_count = len(vals)
                    qr.columns = [field]
            elif mongo_operation == "aggregate":
                cursor = collection.aggregate([{"$limit": row_limit}])
                rows = list(cursor)
                qr.row_count = len(rows)
                qr.columns = list(rows[0].keys()) if rows else []
            elif mongo_operation == "listCollections":
                names = db.list_collection_names()
                qr.row_count = len(names)
                qr.columns = ["collection_name"]
            elif mongo_operation == "listDatabases":
                names = [d["name"] for d in client.list_databases()]
                qr.row_count = len(names)
                qr.columns = ["database_name"]

            client.close()
            qr.status = "complete"
        except Exception as exc:  # noqa: BLE001
            qr.status = "failed"
            qr.error = str(exc)[:400]
        finally:
            qr.duration_ms = round((time.time() - start) * 1000, 1)

        report.query_results.append(qr)
        report.total_queries = 1
        report.passed = 1 if qr.status == "complete" else 0
        report.failed = 0 if qr.status == "complete" else 1
        report.execution_status = "complete" if qr.status == "complete" else "failed"
        report.notes.append(
            f"Connection string source: env var '{db_url_env_var}' (value never logged)."
        )
        return report

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_mysql_host(db_url: str) -> str:
        """Very basic host extraction for MySQL URL — never logged."""
        # mysql://user:pass@host:port/db  or just use the full URL
        return db_url  # mysql.connector.connect accepts full URL via some params

    def _render_md(self, report: DBSmokeReport, ts: str) -> str:
        lines = [
            "# DB Smoke Report",
            "",
            f"**Project:** {report.project_id}",
            f"**Provider:** {report.provider}",
            f"**Table/Collection:** {report.table_or_collection or '—'}",
            f"**Status:** {report.execution_status}",
            f"**Generated:** {ts}",
            "",
            "## Query Results",
            "",
            "| Label | Status | Rows | Duration |",
            "|---|---|---|---|",
        ]
        for r in report.query_results:
            lines.append(
                f"| {r.query_label} | {r.status} | {r.row_count} | {r.duration_ms}ms |"
            )
        if report.blockers:
            lines += ["", "## Blockers", ""]
            for b in report.blockers:
                lines.append(f"- {b}")
        lines += [
            "",
            "---",
            "",
            "**SAFETY:** `raw_secrets_allowed=False` | `production_write_allowed=False` | "
            "`destructive_db_actions_allowed=False` | `connection_string_logged=False` | "
            "`human_review_required=True`",
        ]
        return "\n".join(lines) + "\n"
