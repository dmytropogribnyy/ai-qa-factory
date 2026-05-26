"""
Phase 5J — CLI: Run DB smoke (read-only).

Usage:
  # PostgreSQL:
  python tools/run_db_smoke.py \\
    --project-id my-project \\
    --provider postgresql \\
    --db-url-env-var STAGING_DATABASE_URL \\
    --table users \\
    --approve-db-smoke

  # MySQL:
  python tools/run_db_smoke.py \\
    --project-id my-project \\
    --provider mysql \\
    --db-url-env-var STAGING_MYSQL_URL \\
    --table orders \\
    --row-limit 5 \\
    --approve-db-smoke

  # MongoDB:
  python tools/run_db_smoke.py \\
    --project-id my-project \\
    --provider mongodb \\
    --db-url-env-var STAGING_MONGO_URL \\
    --table products \\
    --mongo-operation find \\
    --approve-db-smoke

  # Custom SELECT query:
  python tools/run_db_smoke.py \\
    --project-id my-project \\
    --provider postgresql \\
    --db-url-env-var STAGING_DATABASE_URL \\
    --query "SELECT id, email FROM users WHERE active = true" \\
    --approve-db-smoke

SAFETY:
- Connection strings only via env var NAME (--db-url-env-var VARNAME, not the value).
- Raw --db-url, --password, --token, --secret flags are blocked.
- SQL must be SELECT-only (INSERT/UPDATE/DELETE/DROP/ALTER blocked).
- MongoDB: read operations only (insertOne/updateOne/deleteOne/drop blocked).
- Row limit enforced (max 100).
- Timeout enforced.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BLOCKED_FLAGS = (
    "--password", "--token", "--secret", "--api-key",
    "--cookie", "--db-url",  # raw connection strings
    "--connection-string", "--dsn",
)


def _check_blocked_flags(argv: list) -> None:
    for flag in argv:
        flag_lower = flag.lower()
        for blocked in _BLOCKED_FLAGS:
            if flag_lower == blocked or flag_lower.startswith(blocked + "="):
                print(
                    f"[BLOCKED] Flag '{blocked}' is not allowed. "
                    "Pass DB connection string via env var only "
                    "(--db-url-env-var VARNAME).",
                    file=sys.stderr,
                )
                sys.exit(2)


def main() -> None:
    _check_blocked_flags(sys.argv[1:])

    parser = argparse.ArgumentParser(
        description="Phase 5J: Run read-only DB smoke (PostgreSQL / MySQL / MongoDB)."
    )
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--provider", required=True,
                        choices=["postgresql", "mysql", "mongodb"],
                        help="DB provider")
    parser.add_argument("--db-url-env-var", required=True,
                        help="Name of the env var holding the DB connection string "
                             "(NOT the value; e.g. STAGING_DATABASE_URL)")
    parser.add_argument("--table",
                        help="Table or collection name for the smoke query")
    parser.add_argument("--database-name", default="",
                        help="Database name (optional; extracted from URL if not set)")
    parser.add_argument("--query",
                        help="Custom SELECT query (must be SELECT-only)")
    parser.add_argument("--mongo-operation", default="find",
                        help="MongoDB operation: find, findOne, aggregate, count, "
                             "countDocuments, distinct, listCollections, listDatabases")
    parser.add_argument("--row-limit", type=int, default=10,
                        help="Maximum rows to return (default 10, max 100)")
    parser.add_argument("--timeout", type=int, default=30,
                        help="Query timeout in seconds (default 30)")
    parser.add_argument("--approve-db-smoke", action="store_true",
                        help="Confirm approval for DB smoke execution")
    parser.add_argument("--no-write", action="store_true",
                        help="Skip writing artifacts to outputs/")

    args = parser.parse_args()

    from core.db_smoke_runner import DBSmokeRunner
    runner = DBSmokeRunner(outputs_root=Path("outputs"))

    report = runner.run(
        project_id=args.project_id,
        provider=args.provider,
        db_url_env_var=args.db_url_env_var,
        table_or_collection=args.table or "",
        custom_query=args.query or "",
        mongo_operation=args.mongo_operation,
        database_name=args.database_name,
        row_limit=args.row_limit,
        timeout_seconds=args.timeout,
        approve_db_smoke=args.approve_db_smoke,
    )

    print(f"Status:     {report.execution_status}")
    print(f"Provider:   {report.provider}")
    print(f"Driver:     {'available' if report.driver_available else 'not available'}")
    if report.table_or_collection:
        print(f"Target:     {report.table_or_collection}")
    print(f"Queries:    {report.total_queries} total / {report.passed} passed / {report.failed} failed")

    if report.query_results:
        for r in report.query_results:
            print(f"  [{r.query_label}] {r.status} — {r.row_count} rows in {r.duration_ms}ms")
            if r.columns:
                print(f"    Columns: {', '.join(r.columns[:10])}")

    if report.blockers:
        print("\nBlockers:")
        for b in report.blockers:
            print(f"  - {b}")

    if report.notes:
        print("\nNotes:")
        for n in report.notes:
            print(f"  - {n}")

    if not args.no_write and report.execution_status != "blocked":
        paths = runner.render_artifacts(report, args.project_id)
        print("\nArtifacts written:")
        for p in paths.values():
            print(f"  {p}")

    sys.exit(0 if report.execution_status == "complete" else 1)


if __name__ == "__main__":
    main()
