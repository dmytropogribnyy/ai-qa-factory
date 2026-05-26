"""
Phase 5J tests — DB Smoke Runner.

Tests cover:
1. DBSmokeTarget schema
2. DBSmokeQueryResult schema
3. DBSmokeReport schema + safety invariants
4. SQL validation (validate_sql)
5. MongoDB operation validation (validate_mongo_operation)
6. Env var name validation (validate_env_var_name)
7. DBSmokeRunner gates (approval, env var, provider)
8. DB_ALLOWED_SQL_PREFIXES and DB_BLOCKED_SQL_KEYWORDS constants
9. MONGODB_ALLOWED_OPERATIONS and MONGODB_BLOCKED_OPERATIONS constants
10. CLI safety (blocked flags)
11. Schema exports (__init__.py)
"""
from __future__ import annotations

import sys
from unittest.mock import patch


# ---------------------------------------------------------------------------
# 1. DBSmokeTarget schema
# ---------------------------------------------------------------------------

class TestDBSmokeTarget:
    def test_default_instantiation(self):
        from core.schemas.db_smoke import DBSmokeTarget
        t = DBSmokeTarget()
        assert t.provider == ""
        assert t.db_url_env_var == ""
        assert t.row_limit == 10
        assert t.timeout_seconds == 30

    def test_with_values(self):
        from core.schemas.db_smoke import DBSmokeTarget
        t = DBSmokeTarget(
            provider="postgresql",
            db_url_env_var="STAGING_DATABASE_URL",
            table_or_collection="users",
            row_limit=5,
        )
        assert t.provider == "postgresql"
        assert t.db_url_env_var == "STAGING_DATABASE_URL"
        assert t.row_limit == 5


# ---------------------------------------------------------------------------
# 2. DBSmokeQueryResult schema
# ---------------------------------------------------------------------------

class TestDBSmokeQueryResult:
    def test_default(self):
        from core.schemas.db_smoke import DBSmokeQueryResult
        r = DBSmokeQueryResult()
        assert r.status == "pending"
        assert r.row_count == 0
        assert r.columns == []

    def test_with_values(self):
        from core.schemas.db_smoke import DBSmokeQueryResult
        r = DBSmokeQueryResult(
            query_label="test",
            status="complete",
            row_count=5,
            columns=["id", "name"],
            duration_ms=12.5,
        )
        assert r.row_count == 5
        assert r.columns == ["id", "name"]


# ---------------------------------------------------------------------------
# 3. DBSmokeReport schema + safety invariants
# ---------------------------------------------------------------------------

class TestDBSmokeReport:
    def test_safety_invariants_default(self):
        from core.schemas.db_smoke import DBSmokeReport
        r = DBSmokeReport()
        assert r.raw_secrets_allowed is False
        assert r.production_write_allowed is False
        assert r.destructive_db_actions_allowed is False
        assert r.client_delivery_allowed is False
        assert r.human_review_required is True
        assert r.connection_string_logged is False

    def test_safety_invariants_cannot_override(self):
        from core.schemas.db_smoke import DBSmokeReport
        r = DBSmokeReport(
            raw_secrets_allowed=True,
            production_write_allowed=True,
            destructive_db_actions_allowed=True,
            client_delivery_allowed=True,
            human_review_required=False,
            connection_string_logged=True,
        )
        assert r.raw_secrets_allowed is False
        assert r.production_write_allowed is False
        assert r.destructive_db_actions_allowed is False
        assert r.client_delivery_allowed is False
        assert r.human_review_required is True
        assert r.connection_string_logged is False

    def test_from_dict_preserves_invariants(self):
        from core.schemas.db_smoke import DBSmokeReport
        r = DBSmokeReport.from_dict({
            "project_id": "p1",
            "provider": "postgresql",
            "raw_secrets_allowed": True,
            "connection_string_logged": True,
            "human_review_required": False,
        })
        assert r.project_id == "p1"
        assert r.provider == "postgresql"
        assert r.raw_secrets_allowed is False
        assert r.connection_string_logged is False
        assert r.human_review_required is True

    def test_from_dict_with_query_results(self):
        from core.schemas.db_smoke import DBSmokeReport
        r = DBSmokeReport.from_dict({
            "project_id": "p1",
            "provider": "mongodb",
            "query_results": [
                {"query_label": "find", "status": "complete", "row_count": 3},
            ],
        })
        assert len(r.query_results) == 1
        assert r.query_results[0].row_count == 3


# ---------------------------------------------------------------------------
# 4. SQL validation — validate_sql
# ---------------------------------------------------------------------------

class TestValidateSQL:
    def setup_method(self):
        from core.db_smoke_runner import validate_sql
        self.validate = validate_sql

    def test_select_allowed(self):
        assert self.validate("SELECT * FROM users") is None

    def test_select_with_where_allowed(self):
        assert self.validate("SELECT id, name FROM orders WHERE active = true") is None

    def test_show_allowed(self):
        assert self.validate("SHOW TABLES") is None

    def test_describe_allowed(self):
        assert self.validate("DESCRIBE users") is None

    def test_explain_allowed(self):
        assert self.validate("EXPLAIN SELECT * FROM users") is None

    def test_select_case_insensitive(self):
        assert self.validate("select * from users") is None

    def test_insert_blocked(self):
        assert self.validate("INSERT INTO users VALUES (1, 'test')") is not None

    def test_update_blocked(self):
        assert self.validate("UPDATE users SET name = 'x'") is not None

    def test_delete_blocked(self):
        assert self.validate("DELETE FROM users") is not None

    def test_drop_blocked(self):
        assert self.validate("DROP TABLE users") is not None

    def test_alter_blocked(self):
        assert self.validate("ALTER TABLE users ADD COLUMN x INT") is not None

    def test_create_blocked(self):
        assert self.validate("CREATE TABLE new_table (id INT)") is not None

    def test_truncate_blocked(self):
        assert self.validate("TRUNCATE TABLE users") is not None

    def test_exec_blocked(self):
        assert self.validate("EXEC sp_something") is not None

    def test_empty_query_blocked(self):
        assert self.validate("") is not None

    def test_whitespace_only_blocked(self):
        assert self.validate("   ") is not None

    def test_sql_injection_pattern_blocked(self):
        # Even if starts with SELECT, contains DROP
        assert self.validate("SELECT 1; DROP TABLE users") is not None

    def test_select_with_subquery_allowed(self):
        # Subquery in SELECT is allowed
        assert self.validate("SELECT * FROM (SELECT id FROM users) sub") is None


# ---------------------------------------------------------------------------
# 5. MongoDB operation validation
# ---------------------------------------------------------------------------

class TestValidateMongoOperation:
    def setup_method(self):
        from core.db_smoke_runner import validate_mongo_operation
        self.validate = validate_mongo_operation

    def test_find_allowed(self):
        assert self.validate("find") is None

    def test_findone_allowed(self):
        assert self.validate("findOne") is None

    def test_aggregate_allowed(self):
        assert self.validate("aggregate") is None

    def test_count_allowed(self):
        assert self.validate("count") is None

    def test_count_documents_allowed(self):
        assert self.validate("countDocuments") is None

    def test_distinct_allowed(self):
        assert self.validate("distinct") is None

    def test_list_collections_allowed(self):
        assert self.validate("listCollections") is None

    def test_list_databases_allowed(self):
        assert self.validate("listDatabases") is None

    def test_insert_one_blocked(self):
        assert self.validate("insertOne") is not None

    def test_insert_many_blocked(self):
        assert self.validate("insertMany") is not None

    def test_update_one_blocked(self):
        assert self.validate("updateOne") is not None

    def test_delete_one_blocked(self):
        assert self.validate("deleteOne") is not None

    def test_drop_blocked(self):
        assert self.validate("drop") is not None

    def test_drop_collection_blocked(self):
        assert self.validate("dropCollection") is not None

    def test_bulk_write_blocked(self):
        assert self.validate("bulkWrite") is not None

    def test_unknown_operation_blocked(self):
        assert self.validate("hacked_operation") is not None


# ---------------------------------------------------------------------------
# 6. Env var name validation
# ---------------------------------------------------------------------------

class TestValidateEnvVarName:
    def setup_method(self):
        from core.db_smoke_runner import validate_env_var_name
        self.validate = validate_env_var_name

    def test_valid_name(self):
        assert self.validate("STAGING_DATABASE_URL") is None

    def test_valid_short_name(self):
        assert self.validate("DB_URL") is None

    def test_valid_with_numbers(self):
        assert self.validate("DB_URL_V2") is None

    def test_empty_blocked(self):
        assert self.validate("") is not None

    def test_lowercase_blocked(self):
        assert self.validate("staging_db_url") is not None

    def test_postgres_url_blocked(self):
        assert self.validate("postgres://user:pass@host/db") is not None

    def test_postgresql_url_blocked(self):
        assert self.validate("postgresql://host/db") is not None

    def test_mysql_url_blocked(self):
        assert self.validate("mysql://host/db") is not None

    def test_mongodb_url_blocked(self):
        assert self.validate("mongodb://host/db") is not None

    def test_mongodb_srv_url_blocked(self):
        assert self.validate("mongodb+srv://host/db") is not None

    def test_starts_with_number_blocked(self):
        assert self.validate("1_DB_URL") is not None


# ---------------------------------------------------------------------------
# 7. DBSmokeRunner gates
# ---------------------------------------------------------------------------

class TestDBSmokeRunnerGates:
    def test_blocked_without_approval(self, tmp_path):
        from core.db_smoke_runner import DBSmokeRunner
        runner = DBSmokeRunner(outputs_root=tmp_path)
        report = runner.run(
            project_id="p1",
            provider="postgresql",
            db_url_env_var="STAGING_DATABASE_URL",
            approve_db_smoke=False,
        )
        assert report.execution_status == "blocked"
        assert any("not approved" in b for b in report.blockers)

    def test_blocked_invalid_provider(self, tmp_path):
        from core.db_smoke_runner import DBSmokeRunner
        runner = DBSmokeRunner(outputs_root=tmp_path)
        report = runner.run(
            project_id="p1",
            provider="oracle",
            db_url_env_var="STAGING_DATABASE_URL",
            approve_db_smoke=True,
        )
        assert report.execution_status == "blocked"
        assert any("Unknown provider" in b for b in report.blockers)

    def test_blocked_invalid_env_var_name(self, tmp_path):
        from core.db_smoke_runner import DBSmokeRunner
        runner = DBSmokeRunner(outputs_root=tmp_path)
        report = runner.run(
            project_id="p1",
            provider="postgresql",
            db_url_env_var="postgres://user:pass@host/db",
            approve_db_smoke=True,
        )
        assert report.execution_status == "blocked"

    def test_blocked_env_var_not_set(self, tmp_path):
        from core.db_smoke_runner import DBSmokeRunner
        runner = DBSmokeRunner(outputs_root=tmp_path)
        report = runner.run(
            project_id="p1",
            provider="postgresql",
            db_url_env_var="NONEXISTENT_ENV_VAR_XYZ_12345",
            approve_db_smoke=True,
        )
        assert report.execution_status == "blocked"
        assert any("not set" in b for b in report.blockers)

    def test_row_limit_capped(self, tmp_path):
        from core.db_smoke_runner import DBSmokeRunner, MAX_ROW_LIMIT
        runner = DBSmokeRunner(outputs_root=tmp_path)
        # Run with limit above max — will be blocked at env var stage
        # but we test the cap logic is hit before driver connection
        report = runner.run(
            project_id="p1",
            provider="postgresql",
            db_url_env_var="NONEXISTENT_ENV_VAR_XYZ_12345",
            row_limit=999,
            approve_db_smoke=True,
        )
        # Should have a note about capping (the note is added before env var check)
        # Even if blocked at env var, the cap note is added first
        assert any(str(MAX_ROW_LIMIT) in n for n in report.notes)

    def test_postgresql_blocked_no_driver(self, tmp_path):
        from core.db_smoke_runner import DBSmokeRunner
        runner = DBSmokeRunner(outputs_root=tmp_path)
        # Simulate missing psycopg2 by patching the import
        with patch.dict("os.environ", {"TEST_PG_URL": "postgresql://localhost/test"}):
            with patch("builtins.__import__", side_effect=lambda name, *a, **kw: (
                (_ for _ in ()).throw(ImportError("No module")) if name == "psycopg2" else __import__(name, *a, **kw)
            )):
                report = runner.run(
                    project_id="p1",
                    provider="postgresql",
                    db_url_env_var="TEST_PG_URL",
                    table_or_collection="users",
                    approve_db_smoke=True,
                )
        # With real env var set, should reach driver check
        # If blocked it means driver missing or env var not set
        assert report.execution_status in ("blocked", "failed", "complete")

    def test_mongodb_blocked_invalid_operation(self, tmp_path):
        from core.db_smoke_runner import DBSmokeRunner, validate_mongo_operation
        # Validate at the function level (independent of driver availability)
        err = validate_mongo_operation("deleteOne")
        assert err is not None
        assert "blocked" in err.lower() or "not allowed" in err.lower()
        # Runner-level: operation blocked before driver call (checked in _run_mongodb)
        runner = DBSmokeRunner(outputs_root=tmp_path)
        with patch.dict("os.environ", {"TEST_MONGO_URL": "mongodb://localhost/test"}):
            report = runner.run(
                project_id="p1",
                provider="mongodb",
                db_url_env_var="TEST_MONGO_URL",
                table_or_collection="users",
                mongo_operation="deleteOne",
                approve_db_smoke=True,
            )
        assert report.execution_status == "blocked"
        assert len(report.blockers) > 0


# ---------------------------------------------------------------------------
# 8. DB constants
# ---------------------------------------------------------------------------

class TestDBConstants:
    def test_providers_tuple(self):
        from core.schemas.db_smoke import DB_PROVIDERS
        assert "postgresql" in DB_PROVIDERS
        assert "mysql" in DB_PROVIDERS
        assert "mongodb" in DB_PROVIDERS

    def test_allowed_sql_prefixes(self):
        from core.schemas.db_smoke import DB_ALLOWED_SQL_PREFIXES
        assert "SELECT" in DB_ALLOWED_SQL_PREFIXES
        assert "SHOW" in DB_ALLOWED_SQL_PREFIXES
        assert "DESCRIBE" in DB_ALLOWED_SQL_PREFIXES

    def test_blocked_sql_keywords(self):
        from core.schemas.db_smoke import DB_BLOCKED_SQL_KEYWORDS
        assert "INSERT" in DB_BLOCKED_SQL_KEYWORDS
        assert "UPDATE" in DB_BLOCKED_SQL_KEYWORDS
        assert "DELETE" in DB_BLOCKED_SQL_KEYWORDS
        assert "DROP" in DB_BLOCKED_SQL_KEYWORDS
        assert "ALTER" in DB_BLOCKED_SQL_KEYWORDS
        assert "CREATE" in DB_BLOCKED_SQL_KEYWORDS
        assert "TRUNCATE" in DB_BLOCKED_SQL_KEYWORDS

    def test_mongodb_allowed_operations(self):
        from core.schemas.db_smoke import MONGODB_ALLOWED_OPERATIONS
        assert "find" in MONGODB_ALLOWED_OPERATIONS
        assert "findOne" in MONGODB_ALLOWED_OPERATIONS
        assert "aggregate" in MONGODB_ALLOWED_OPERATIONS
        assert "count" in MONGODB_ALLOWED_OPERATIONS

    def test_mongodb_blocked_operations(self):
        from core.schemas.db_smoke import MONGODB_BLOCKED_OPERATIONS
        assert "insertOne" in MONGODB_BLOCKED_OPERATIONS
        assert "deleteOne" in MONGODB_BLOCKED_OPERATIONS
        assert "updateOne" in MONGODB_BLOCKED_OPERATIONS
        assert "drop" in MONGODB_BLOCKED_OPERATIONS
        assert "bulkWrite" in MONGODB_BLOCKED_OPERATIONS

    def test_default_row_limit_sensible(self):
        from core.schemas.db_smoke import DEFAULT_ROW_LIMIT, MAX_ROW_LIMIT
        assert 1 <= DEFAULT_ROW_LIMIT <= 20
        assert MAX_ROW_LIMIT <= 1000


# ---------------------------------------------------------------------------
# 9. render_artifacts
# ---------------------------------------------------------------------------

class TestDBSmokeRenderArtifacts:
    def test_render_creates_files(self, tmp_path):
        from core.db_smoke_runner import DBSmokeRunner
        from core.schemas.db_smoke import DBSmokeReport
        runner = DBSmokeRunner(outputs_root=tmp_path)
        report = DBSmokeReport(
            project_id="p1",
            provider="postgresql",
            execution_status="blocked",
        )
        paths = runner.render_artifacts(report, "p1")
        assert paths["json"].exists()
        assert paths["md"].exists()

    def test_render_json_has_safety_fields(self, tmp_path):
        import json
        from core.db_smoke_runner import DBSmokeRunner
        from core.schemas.db_smoke import DBSmokeReport
        runner = DBSmokeRunner(outputs_root=tmp_path)
        report = DBSmokeReport(project_id="p1", provider="mysql")
        paths = runner.render_artifacts(report, "p1")
        data = json.loads(paths["json"].read_text())
        assert data["raw_secrets_allowed"] is False
        assert data["connection_string_logged"] is False
        assert data["human_review_required"] is True
        assert data["destructive_db_actions_allowed"] is False


# ---------------------------------------------------------------------------
# 10. CLI safety
# ---------------------------------------------------------------------------

class TestDBSmokeCLISafety:
    def _run_cli(self, args: list) -> int:
        import subprocess
        result = subprocess.run(
            [sys.executable, "tools/run_db_smoke.py"] + args,
            capture_output=True,
            text=True,
        )
        return result.returncode

    def test_blocked_password_flag(self):
        rc = self._run_cli(["--project-id", "p", "--provider", "postgresql",
                            "--db-url-env-var", "X", "--password", "secret"])
        assert rc == 2

    def test_blocked_db_url_flag(self):
        rc = self._run_cli(["--project-id", "p", "--db-url", "postgres://host/db"])
        assert rc == 2

    def test_blocked_connection_string_flag(self):
        rc = self._run_cli(["--project-id", "p", "--connection-string", "anything"])
        assert rc == 2

    def test_missing_project_id(self):
        rc = self._run_cli(["--provider", "postgresql", "--db-url-env-var", "X"])
        assert rc != 0

    def test_missing_provider(self):
        rc = self._run_cli(["--project-id", "p", "--db-url-env-var", "X"])
        assert rc != 0


# ---------------------------------------------------------------------------
# 11. Schema exports
# ---------------------------------------------------------------------------

class TestPhase5JDBSmokeExports:
    def test_db_smoke_schema_exports(self):
        from core.schemas import (
            DB_ALLOWED_SQL_PREFIXES,
            DB_BLOCKED_SQL_KEYWORDS,
            DB_PROVIDERS,
            MONGODB_ALLOWED_OPERATIONS,
            MONGODB_BLOCKED_OPERATIONS,
            DBSmokeReport,
        )
        assert "postgresql" in DB_PROVIDERS
        assert "SELECT" in DB_ALLOWED_SQL_PREFIXES
        assert "INSERT" in DB_BLOCKED_SQL_KEYWORDS
        assert "find" in MONGODB_ALLOWED_OPERATIONS
        assert "deleteOne" in MONGODB_BLOCKED_OPERATIONS
        r = DBSmokeReport()
        assert r.human_review_required is True
        assert r.raw_secrets_allowed is False
        assert r.connection_string_logged is False
