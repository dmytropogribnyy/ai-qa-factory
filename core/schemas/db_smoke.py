"""Phase 5J — DB Smoke Runner schemas.

Read-only database smoke checks for PostgreSQL, MySQL, and MongoDB.
Connection strings are passed via environment variable NAME only —
raw connection strings are never accepted in CLI args or stored in artifacts.

SQL safety:
- Only SELECT, SHOW, DESCRIBE, EXPLAIN allowed
- INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, EXEC, EXECUTE blocked

MongoDB safety:
- Only find, findOne, aggregate, count, countDocuments, distinct,
  listCollections, listDatabases allowed
- insertOne, insertMany, updateOne, updateMany, deleteOne, deleteMany,
  drop, dropCollection, dropDatabase, replaceOne, bulkWrite blocked

Safety invariants (hardcoded in __post_init__ + from_dict):
- raw_secrets_allowed=False
- production_write_allowed=False
- destructive_db_actions_allowed=False
- client_delivery_allowed=False
- human_review_required=True
- connection_string_logged=False
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from core.schemas.base import SchemaMixin

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DB_PROVIDERS = ("postgresql", "mysql", "mongodb")

DB_SMOKE_STATUSES = ("complete", "failed", "blocked", "error", "skipped")

DB_ALLOWED_SQL_PREFIXES = ("SELECT", "SHOW", "DESCRIBE", "EXPLAIN")

DB_BLOCKED_SQL_KEYWORDS = (
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE",
    "TRUNCATE", "EXEC", "EXECUTE", "GRANT", "REVOKE", "MERGE",
    "REPLACE", "CALL", "LOAD", "IMPORT",
)

MONGODB_ALLOWED_OPERATIONS = (
    "find",
    "findOne",
    "aggregate",
    "count",
    "countDocuments",
    "estimatedDocumentCount",
    "distinct",
    "listCollections",
    "listDatabases",
)

MONGODB_BLOCKED_OPERATIONS = (
    "insertOne",
    "insertMany",
    "updateOne",
    "updateMany",
    "deleteOne",
    "deleteMany",
    "drop",
    "dropCollection",
    "dropDatabase",
    "replaceOne",
    "bulkWrite",
    "createCollection",
    "createIndex",
    "dropIndex",
    "renameCollection",
)

DEFAULT_ROW_LIMIT = 10
DEFAULT_TIMEOUT_SECONDS = 30
MAX_ROW_LIMIT = 100


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------

@dataclass
class DBSmokeTarget(SchemaMixin):
    """Describes the DB smoke target — never contains raw connection strings."""
    provider: str = ""
    db_url_env_var: str = ""           # env var NAME only, never the value
    database_name: str = ""
    table_or_collection: str = ""
    custom_query: str = ""             # must be SELECT-only; validated before use
    mongo_operation: str = "find"      # for MongoDB smoke
    row_limit: int = DEFAULT_ROW_LIMIT
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    notes: List[str] = field(default_factory=list)


@dataclass
class DBSmokeQueryResult(SchemaMixin):
    """Result of a single DB query check."""
    query_label: str = ""
    status: str = "pending"
    row_count: int = 0
    columns: List[str] = field(default_factory=list)
    error: str = ""
    duration_ms: float = 0.0
    blocked_reason: str = ""


@dataclass
class DBSmokeReport(SchemaMixin):
    """Full DB smoke report for one provider+target."""
    project_id: str = ""
    provider: str = ""
    database_name: str = ""
    table_or_collection: str = ""
    execution_status: str = "planned"
    query_results: List[DBSmokeQueryResult] = field(default_factory=list)
    total_queries: int = 0
    passed: int = 0
    failed: int = 0
    duration_seconds: float = 0.0
    driver_available: bool = False
    blockers: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    # Safety — all hardcoded
    raw_secrets_allowed: bool = False
    production_write_allowed: bool = False
    destructive_db_actions_allowed: bool = False
    client_delivery_allowed: bool = False
    human_review_required: bool = True
    connection_string_logged: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "raw_secrets_allowed", False)
        object.__setattr__(self, "production_write_allowed", False)
        object.__setattr__(self, "destructive_db_actions_allowed", False)
        object.__setattr__(self, "client_delivery_allowed", False)
        object.__setattr__(self, "human_review_required", True)
        object.__setattr__(self, "connection_string_logged", False)

    @classmethod
    def from_dict(cls, data: dict) -> "DBSmokeReport":
        results = [
            DBSmokeQueryResult(**r) if isinstance(r, dict) else r
            for r in data.get("query_results", [])
        ]
        obj = cls(
            project_id=str(data.get("project_id", "")),
            provider=str(data.get("provider", "")),
            database_name=str(data.get("database_name", "")),
            table_or_collection=str(data.get("table_or_collection", "")),
            execution_status=str(data.get("execution_status", "planned")),
            query_results=results,
            total_queries=int(data.get("total_queries", 0)),
            passed=int(data.get("passed", 0)),
            failed=int(data.get("failed", 0)),
            duration_seconds=float(data.get("duration_seconds", 0.0)),
            driver_available=bool(data.get("driver_available", False)),
            blockers=list(data.get("blockers", [])),
            notes=list(data.get("notes", [])),
        )
        object.__setattr__(obj, "raw_secrets_allowed", False)
        object.__setattr__(obj, "production_write_allowed", False)
        object.__setattr__(obj, "destructive_db_actions_allowed", False)
        object.__setattr__(obj, "client_delivery_allowed", False)
        object.__setattr__(obj, "human_review_required", True)
        object.__setattr__(obj, "connection_string_logged", False)
        return obj
