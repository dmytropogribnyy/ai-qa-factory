"""
Documentation governance schema tests — Phase 1B-DOCS.

Covers:
- DocumentationRecord safe defaults and roundtrip
- DocumentationManifest safe defaults and nested from_dict
- DocumentationFreshnessCheck safe defaults and roundtrip
- DocumentationFreshnessReport safe defaults and nested from_dict
- DOC_TYPES, DOC_STATUSES, DOC_UPDATE_TRIGGERS constants
- __init__.py exports
"""
from __future__ import annotations

import os
import subprocess
import sys

from core.schemas.documentation import (
    DocumentationFreshnessCheck,
    DocumentationFreshnessReport,
    DocumentationManifest,
    DocumentationRecord,
)
from core.schemas.constants import DOC_TYPES, DOC_STATUSES, DOC_UPDATE_TRIGGERS


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

class TestDocConstants:
    def test_doc_types_frozenset(self):
        assert isinstance(DOC_TYPES, frozenset)
        for t in ("vision", "readme", "runbook", "commands", "safety",
                  "approval_model", "tooling_decisions", "schema_foundation",
                  "project_types", "reporting", "troubleshooting",
                  "docs_governance", "docs_manifest", "generated_report",
                  "internal_note", "client_facing", "unknown"):
            assert t in DOC_TYPES

    def test_doc_statuses_frozenset(self):
        assert isinstance(DOC_STATUSES, frozenset)
        for s in ("current", "needs_review", "stale", "planned", "deprecated", "unknown"):
            assert s in DOC_STATUSES

    def test_doc_update_triggers_frozenset(self):
        assert isinstance(DOC_UPDATE_TRIGGERS, frozenset)
        for t in ("schema_changed", "command_added", "command_removed",
                  "workflow_changed", "safety_rule_changed", "approval_model_changed",
                  "tool_added", "integration_added", "reporting_changed",
                  "evidence_changed", "cleanup_changed", "ai_resilience_changed",
                  "auth_changed", "mobile_changed", "credential_changed",
                  "version_changed", "phase_completed"):
            assert t in DOC_UPDATE_TRIGGERS


# ---------------------------------------------------------------------------
# DocumentationRecord
# ---------------------------------------------------------------------------

class TestDocumentationRecord:
    def test_safe_defaults(self):
        r = DocumentationRecord()
        assert r.path == ""
        assert r.title == ""
        assert r.doc_type == "unknown"
        assert r.source_of_truth is False
        assert r.generated is False
        assert r.owner == ""
        assert r.update_triggers == []
        assert r.related_code_paths == []
        assert r.related_schema_modules == []
        assert r.related_commands == []
        assert r.last_reviewed_at is None
        assert r.status == "unknown"
        assert r.notes == []

    def test_id_auto_generated(self):
        r = DocumentationRecord()
        assert len(r.id) > 0

    def test_source_of_truth_flag(self):
        r = DocumentationRecord(path="docs/SAFETY_RULES.md", source_of_truth=True, status="current")
        assert r.source_of_truth is True
        assert r.status == "current"

    def test_roundtrip(self):
        r = DocumentationRecord(
            path="docs/COMMANDS.md",
            title="Command Reference",
            doc_type="commands",
            source_of_truth=True,
            status="current",
            update_triggers=["command_added", "command_removed"],
            related_schema_modules=["automation_plan"],
            notes=["Updated in Phase 1B-DOCS"],
        )
        d = r.to_dict()
        r2 = DocumentationRecord.from_dict(d)
        assert r2.path == "docs/COMMANDS.md"
        assert r2.doc_type == "commands"
        assert r2.source_of_truth is True
        assert r2.status == "current"
        assert "command_added" in r2.update_triggers
        assert r2.last_reviewed_at is None

    def test_from_dict_ignores_unknown_fields(self):
        r = DocumentationRecord.from_dict({"path": "README.md", "unknown_key": "ignored"})
        assert r.path == "README.md"


# ---------------------------------------------------------------------------
# DocumentationManifest
# ---------------------------------------------------------------------------

class TestDocumentationManifest:
    def test_safe_defaults(self):
        m = DocumentationManifest()
        assert m.project_id == ""
        assert m.docs == []
        assert m.source_of_truth_docs == []
        assert m.generated_docs == []
        assert m.notes == []

    def test_roundtrip_empty(self):
        m = DocumentationManifest(project_id="workbench")
        d = m.to_dict()
        m2 = DocumentationManifest.from_dict(d)
        assert m2.project_id == "workbench"
        assert m2.docs == []

    def test_nested_docs_reconstructed_as_typed(self):
        m = DocumentationManifest(
            project_id="workbench",
            docs=[
                DocumentationRecord(path="README.md", doc_type="readme", status="current"),
                DocumentationRecord(path="docs/SAFETY_RULES.md", doc_type="safety", source_of_truth=True),
            ],
        )
        d = m.to_dict()
        assert isinstance(d["docs"][0], dict)
        m2 = DocumentationManifest.from_dict(d)
        assert len(m2.docs) == 2
        assert isinstance(m2.docs[0], DocumentationRecord)
        assert m2.docs[0].path == "README.md"
        assert m2.docs[1].source_of_truth is True

    def test_from_dict_nested_dicts_become_records(self):
        raw = {
            "project_id": "p1",
            "docs": [{"path": "docs/COMMANDS.md", "doc_type": "commands", "status": "current"}],
            "source_of_truth_docs": ["docs/COMMANDS.md"],
        }
        m = DocumentationManifest.from_dict(raw)
        assert isinstance(m.docs[0], DocumentationRecord)
        assert m.docs[0].doc_type == "commands"
        assert "docs/COMMANDS.md" in m.source_of_truth_docs


# ---------------------------------------------------------------------------
# DocumentationFreshnessCheck
# ---------------------------------------------------------------------------

class TestDocumentationFreshnessCheck:
    def test_safe_defaults(self):
        c = DocumentationFreshnessCheck()
        assert c.doc_path == ""
        assert c.check_type == "unknown"
        assert c.passed is True
        assert c.severity == "info"
        assert c.finding == ""
        assert c.recommended_action == ""
        assert c.related_file is None
        assert c.notes == []

    def test_id_auto_generated(self):
        c = DocumentationFreshnessCheck()
        assert len(c.id) > 0

    def test_failed_check(self):
        c = DocumentationFreshnessCheck(
            doc_path="docs/SCHEMA_FOUNDATION.md",
            check_type="schema_reference_missing",
            passed=False,
            severity="warning",
            finding="documentation.py not mentioned",
            recommended_action="Add documentation schema section",
        )
        assert c.passed is False
        assert c.severity == "warning"

    def test_roundtrip(self):
        c = DocumentationFreshnessCheck(
            doc_path="docs/COMMANDS.md",
            check_type="planned_command_marking",
            passed=True,
            severity="info",
            finding="All planned commands correctly marked [planned]",
        )
        d = c.to_dict()
        c2 = DocumentationFreshnessCheck.from_dict(d)
        assert c2.doc_path == "docs/COMMANDS.md"
        assert c2.check_type == "planned_command_marking"
        assert c2.passed is True


# ---------------------------------------------------------------------------
# DocumentationFreshnessReport
# ---------------------------------------------------------------------------

class TestDocumentationFreshnessReport:
    def test_safe_defaults(self):
        r = DocumentationFreshnessReport()
        assert r.project_id == ""
        assert r.docs_current is False
        assert r.checks == []
        assert r.docs_needing_review == []
        assert r.blockers == []
        assert r.summary == ""
        assert r.recommended_next_action == ""
        assert r.created_at != ""

    def test_docs_current_defaults_false(self):
        r = DocumentationFreshnessReport()
        assert r.docs_current is False

    def test_nested_checks_reconstructed_as_typed(self):
        check = DocumentationFreshnessCheck(
            doc_path="README.md",
            check_type="missing_doc",
            passed=False,
            severity="error",
            finding="README.md not found",
        )
        report = DocumentationFreshnessReport(
            project_id="workbench",
            checks=[check],
            docs_needing_review=["README.md"],
            blockers=["README.md missing"],
        )
        d = report.to_dict()
        assert isinstance(d["checks"][0], dict)
        r2 = DocumentationFreshnessReport.from_dict(d)
        assert len(r2.checks) == 1
        assert isinstance(r2.checks[0], DocumentationFreshnessCheck)
        assert r2.checks[0].passed is False
        assert r2.checks[0].severity == "error"
        assert r2.docs_current is False

    def test_from_dict_nested_dicts_become_checks(self):
        raw = {
            "project_id": "p1",
            "checks": [
                {"doc_path": "docs/SAFETY_RULES.md", "check_type": "missing_doc",
                 "passed": True, "severity": "info", "finding": "File exists"}
            ],
        }
        r = DocumentationFreshnessReport.from_dict(raw)
        assert isinstance(r.checks[0], DocumentationFreshnessCheck)
        assert r.checks[0].doc_path == "docs/SAFETY_RULES.md"

    def test_roundtrip_with_checks(self):
        report = DocumentationFreshnessReport(
            project_id="workbench",
            checks=[
                DocumentationFreshnessCheck(
                    doc_path="docs/COMMANDS.md",
                    check_type="planned_command_marking",
                    passed=True,
                    severity="info",
                ),
            ],
            docs_current=True,
            summary="All required docs present.",
            recommended_next_action="Proceed to Phase 2.",
        )
        d = report.to_dict()
        r2 = DocumentationFreshnessReport.from_dict(d)
        assert r2.docs_current is True
        assert r2.summary == "All required docs present."
        assert len(r2.checks) == 1
        assert r2.checks[0].check_type == "planned_command_marking"


# ---------------------------------------------------------------------------
# __init__.py exports
# ---------------------------------------------------------------------------

class TestDocumentationPackageExports:
    def test_documentation_classes_importable(self):
        import core.schemas as s
        assert s.DocumentationRecord is not None
        assert s.DocumentationManifest is not None
        assert s.DocumentationFreshnessCheck is not None
        assert s.DocumentationFreshnessReport is not None

    def test_documentation_constants_importable(self):
        import core.schemas as s
        assert "commands" in s.DOC_TYPES
        assert "current" in s.DOC_STATUSES
        assert "schema_changed" in s.DOC_UPDATE_TRIGGERS


# ---------------------------------------------------------------------------
# docs_audit.py — basic structural tests
# ---------------------------------------------------------------------------

class TestDocsAuditScript:
    def test_audit_script_exists(self):
        script = os.path.join(
            os.path.dirname(__file__), "..", "tools", "docs_audit.py"
        )
        assert os.path.exists(script), "tools/docs_audit.py must exist"

    def test_audit_script_runs_without_error(self):
        script = os.path.join(
            os.path.dirname(__file__), "..", "tools", "docs_audit.py"
        )
        result = subprocess.run(
            [sys.executable, script, "--no-write"],
            capture_output=True,
            text=True,
            cwd=os.path.join(os.path.dirname(__file__), ".."),
        )
        # Exit 0 = all required docs present and no hard errors
        # Exit 1 = missing required docs or hard contradictions (fail the test)
        assert result.returncode == 0, (
            f"docs_audit.py exited {result.returncode}.\n"
            f"STDOUT:\n{result.stdout}\n"
            f"STDERR:\n{result.stderr}"
        )

    def test_audit_script_makes_no_external_calls(self):
        # Verify the script doesn't import requests, httpx, urllib.request for external calls
        script_path = os.path.join(
            os.path.dirname(__file__), "..", "tools", "docs_audit.py"
        )
        with open(script_path, encoding="utf-8") as f:
            source = f.read()
        for forbidden in ("requests.get", "httpx.get", "urllib.request.urlopen"):
            assert forbidden not in source, (
                f"docs_audit.py must not make external calls ({forbidden})"
            )
