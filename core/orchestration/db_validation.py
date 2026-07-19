"""Safe read-only database validation (v3.2 Section 7.3 / 7.12).

Real adapters for SQLite (stdlib), PostgreSQL, and MySQL. Every query is guarded read-only: only a
single SELECT/PRAGMA/EXPLAIN/SHOW/WITH-select statement is allowed; any mutation (INSERT/UPDATE/
DELETE/DROP/ALTER/CREATE/TRUNCATE/GRANT/…) is refused. Database MUTATION is never the default and
requires an explicit, separate authorization path (not provided here). PostgreSQL/MySQL run only
when the driver is installed and a connection is provided; otherwise readiness is honestly reported
as Client Validation Required.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Any, List, Optional, Tuple

_ALLOWED_START = re.compile(r"^\s*(select|with|pragma|explain|show)\b", re.IGNORECASE)
_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|grant|revoke|replace|merge|attach|"
    r"vacuum|reindex|copy|call|do|commit|rollback)\b", re.IGNORECASE)


class UnsafeQueryError(ValueError):
    """Raised when a query is not a safe, single read-only statement."""


@dataclass
class QueryResult:
    columns: List[str]
    rows: List[Tuple[Any, ...]]
    engine: str
    read_only: bool = True


def assert_read_only(sql: str) -> None:
    """Refuse anything that is not a single read-only statement."""
    if sql is None or not sql.strip():
        raise UnsafeQueryError("empty query")
    # Reject multiple statements (a trailing ';' is allowed).
    body = sql.strip().rstrip(";")
    if ";" in body:
        raise UnsafeQueryError("multiple statements are not allowed")
    if not _ALLOWED_START.match(body):
        raise UnsafeQueryError("only SELECT/WITH/PRAGMA/EXPLAIN/SHOW read queries are allowed")
    if _FORBIDDEN.search(body):
        raise UnsafeQueryError("mutation keywords are not allowed in read-only validation")


def sqlite_read_only_query(db_path: str, sql: str, params: Optional[tuple] = None) -> QueryResult:
    """Run a guarded read-only query against a SQLite file (opened in ``mode=ro``)."""
    assert_read_only(sql)
    uri = f"file:{db_path}?mode=ro"
    con = sqlite3.connect(uri, uri=True)
    try:
        cur = con.execute(sql, params or ())
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
        return QueryResult(columns=cols, rows=rows, engine="sqlite")
    finally:
        con.close()


def _driver_available(name: str) -> bool:
    import importlib.util
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def postgres_read_only_query(dsn: str, sql: str, params: Optional[tuple] = None) -> QueryResult:
    """Guarded read-only query against PostgreSQL. Requires psycopg2 (Client Validation Required if
    the driver or a connection is not available)."""
    assert_read_only(sql)
    if not _driver_available("psycopg2"):
        raise UnsafeQueryError("psycopg2 not installed (Client Validation Required)")
    import psycopg2  # type: ignore
    con = psycopg2.connect(dsn)
    try:
        con.set_session(readonly=True, autocommit=True)
        cur = con.cursor()
        cur.execute(sql, params or ())
        rows = cur.fetchall()
        cols = [d[0] for d in cur.description] if cur.description else []
        return QueryResult(columns=cols, rows=list(rows), engine="postgresql")
    finally:
        con.close()


def mysql_read_only_query(*, host: str, user: str, password: str, database: str, sql: str,
                          params: Optional[tuple] = None, port: int = 3306) -> QueryResult:
    """Guarded read-only query against MySQL. Requires pymysql (Client Validation Required otherwise).
    The password is used only for the live connection and is never persisted."""
    assert_read_only(sql)
    if not _driver_available("pymysql"):
        raise UnsafeQueryError("pymysql not installed (Client Validation Required)")
    import pymysql  # type: ignore
    con = pymysql.connect(host=host, user=user, password=password, database=database, port=port)
    try:
        with con.cursor() as cur:
            cur.execute("SET SESSION TRANSACTION READ ONLY")
            cur.execute(sql, params or ())
            rows = cur.fetchall()
            cols = [d[0] for d in cur.description] if cur.description else []
        return QueryResult(columns=cols, rows=list(rows), engine="mysql")
    finally:
        con.close()


def engine_readiness() -> dict:
    """Honest readiness for each DB engine in this environment."""
    return {"sqlite": "Fixture Verified",
            "postgresql": "Runtime Available" if _driver_available("psycopg2")
            else "Client Validation Required",
            "mysql": "Runtime Available" if _driver_available("pymysql")
            else "Client Validation Required"}
