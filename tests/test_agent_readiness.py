"""tests/test_agent_readiness.py — Phase 2B-AGENT: agent readiness checks.

Verifies that:
- all required agent contract docs exist
- agent_readiness_audit.py runs cleanly
- audit returns PASS on the current repo
- audit does not call external services
- AGENT_CONTRACT contains required sections
- PHASE_CONTRACTS contains required sections
- ARTIFACT_CONTRACTS contains required sections
- AGENT_HANDOFF_TEMPLATE contains required sections
- outputs/ is gitignored
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_DOCS = _ROOT / "docs"
_TOOLS = _ROOT / "tools"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _contains(path: Path, keyword: str) -> bool:
    return keyword.lower() in _read(path).lower()


# ---------------------------------------------------------------------------
# Required docs exist
# ---------------------------------------------------------------------------

class TestRequiredAgentDocExist:
    def test_agent_contract_exists(self):
        assert (_DOCS / "AGENT_CONTRACT.md").exists()

    def test_phase_contracts_exists(self):
        assert (_DOCS / "PHASE_CONTRACTS.md").exists()

    def test_artifact_contracts_exists(self):
        assert (_DOCS / "ARTIFACT_CONTRACTS.md").exists()

    def test_agent_handoff_template_exists(self):
        assert (_DOCS / "AGENT_HANDOFF_TEMPLATE.md").exists()

    def test_docs_manifest_exists(self):
        assert (_DOCS / "DOCS_MANIFEST.md").exists()

    def test_documentation_governance_exists(self):
        assert (_DOCS / "DOCUMENTATION_GOVERNANCE.md").exists()

    def test_safety_rules_exists(self):
        assert (_DOCS / "SAFETY_RULES.md").exists()

    def test_commands_exists(self):
        assert (_DOCS / "COMMANDS.md").exists()

    def test_schema_foundation_exists(self):
        assert (_DOCS / "SCHEMA_FOUNDATION.md").exists()

    def test_agent_readiness_audit_script_exists(self):
        assert (_TOOLS / "agent_readiness_audit.py").exists()


# ---------------------------------------------------------------------------
# agent_readiness_audit.py behavior
# ---------------------------------------------------------------------------

class TestAgentReadinessAuditScript:
    def test_audit_is_importable(self):
        spec = importlib.util.spec_from_file_location(
            "agent_readiness_audit", _TOOLS / "agent_readiness_audit.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        assert hasattr(mod, "main")
        assert hasattr(mod, "_run_checks")

    def test_audit_returns_zero_exit_code(self, tmp_path, monkeypatch):
        monkeypatch.chdir(_ROOT)
        spec = importlib.util.spec_from_file_location(
            "agent_readiness_audit", _TOOLS / "agent_readiness_audit.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        result = mod.main(["--no-write"])
        assert result == 0, "agent_readiness_audit should return 0 (PASS) on this repo"

    def test_audit_run_checks_returns_all_passed(self, monkeypatch):
        monkeypatch.chdir(_ROOT)
        spec = importlib.util.spec_from_file_location(
            "agent_readiness_audit", _TOOLS / "agent_readiness_audit.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        checks = mod._run_checks()
        failed = [c for c in checks if not c["passed"] and c["required"]]
        assert not failed, f"Required checks failed: {[c['message'] for c in failed]}"

    def test_audit_json_output_contains_result(self, monkeypatch, capsys):
        monkeypatch.chdir(_ROOT)
        spec = importlib.util.spec_from_file_location(
            "agent_readiness_audit", _TOOLS / "agent_readiness_audit.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.main(["--json"])
        captured = capsys.readouterr()
        output = json.loads(captured.out)
        assert "result" in output
        assert output["result"] == "PASS"
        assert "checks" in output

    def test_audit_does_not_call_external_services(self):
        source = (_TOOLS / "agent_readiness_audit.py").read_text(encoding="utf-8")
        forbidden = ["requests", "httpx", "aiohttp", "urllib.request.urlopen",
                     "subprocess.run", "subprocess.call"]
        for f in forbidden:
            assert f not in source, f"audit tool must not use {f}"

    def test_audit_does_not_modify_docs(self, monkeypatch, tmp_path):
        monkeypatch.chdir(_ROOT)
        agent_contract = _DOCS / "AGENT_CONTRACT.md"
        before = agent_contract.read_text(encoding="utf-8")
        spec = importlib.util.spec_from_file_location(
            "agent_readiness_audit", _TOOLS / "agent_readiness_audit.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.main(["--no-write"])
        after = agent_contract.read_text(encoding="utf-8")
        assert before == after, "audit must not modify docs"

    def test_audit_writes_to_outputs_when_allowed(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        # Copy agent contract docs into tmp so checks pass, then check output is written
        # Using _ROOT directly — audit writes to _ROOT/outputs/agent_audit/
        # so just run with default (write) and verify outputs exist after
        monkeypatch.chdir(_ROOT)
        spec = importlib.util.spec_from_file_location(
            "agent_readiness_audit", _TOOLS / "agent_readiness_audit.py"
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        mod.main([])  # no --no-write
        report_json = _ROOT / "outputs" / "agent_audit" / "agent_readiness_report.json"
        report_md = _ROOT / "outputs" / "agent_audit" / "AGENT_READINESS_REPORT.md"
        assert report_json.exists()
        assert report_md.exists()


# ---------------------------------------------------------------------------
# AGENT_CONTRACT content
# ---------------------------------------------------------------------------

class TestAgentContractContent:
    _path = _DOCS / "AGENT_CONTRACT.md"

    def test_has_forbidden_actions_section(self):
        assert _contains(self._path, "forbidden agent actions")

    def test_has_required_final_report_format_section(self):
        assert _contains(self._path, "required final report format")

    def test_forbids_url_fetching(self):
        assert _contains(self._path, "do not fetch url")

    def test_forbids_credential_use(self):
        assert _contains(self._path, "do not use credentials")

    def test_forbids_staging_outputs(self):
        assert _contains(self._path, "do not stage")

    def test_forbids_browser_execution(self):
        assert _contains(self._path, "do not open browser")

    def test_forbids_playwright_execution(self):
        assert _contains(self._path, "do not run playwright")

    def test_forbids_external_api_calls(self):
        assert _contains(self._path, "do not call external api")

    def test_has_safety_phrase_requirements(self):
        assert _contains(self._path, "safety phrase")

    def test_has_git_hygiene_section(self):
        assert _contains(self._path, "git hygiene") or _contains(self._path, "git status")

    def test_has_source_of_truth_hierarchy(self):
        assert _contains(self._path, "source-of-truth")

    def test_references_handoff_template(self):
        assert _contains(self._path, "agent_handoff_template")


# ---------------------------------------------------------------------------
# PHASE_CONTRACTS content
# ---------------------------------------------------------------------------

class TestPhaseContractsContent:
    _path = _DOCS / "PHASE_CONTRACTS.md"

    def test_has_allowed_actions(self):
        assert _contains(self._path, "allowed actions")

    def test_has_blocked_actions(self):
        assert _contains(self._path, "blocked actions")

    def test_has_acceptance_criteria(self):
        assert _contains(self._path, "acceptance criteria")

    def test_marks_phase_2a_implemented(self):
        content = _read(self._path)
        assert "Phase 2A" in content and "[implemented]" in content

    def test_marks_phase_2b_implemented(self):
        content = _read(self._path)
        assert "Phase 2B" in content and "[implemented]" in content

    def test_marks_future_phases_planned(self):
        assert _contains(self._path, "[planned]")

    def test_phase_2a_blocked_actions_include_url_fetching(self):
        assert _contains(self._path, "no url fetching")

    def test_phase_2b_blocked_actions_include_no_scaffold(self):
        content = _read(self._path)
        assert "playwright scaffold" in content.lower() or "scaffold" in content.lower()

    def test_has_cross_phase_rules(self):
        assert _contains(self._path, "cross-phase")


# ---------------------------------------------------------------------------
# ARTIFACT_CONTRACTS content
# ---------------------------------------------------------------------------

class TestArtifactContractsContent:
    _path = _DOCS / "ARTIFACT_CONTRACTS.md"

    def test_documents_00_project_path(self):
        assert _contains(self._path, "outputs/<project_id>/00_project/")

    def test_tests_reserved_for_workbench_self_tests(self):
        content = _read(self._path)
        assert "workbench self-tests" in content.lower()

    def test_outputs_never_committed(self):
        assert _contains(self._path, "never committed") or _contains(self._path, "never commit")

    def test_distinguishes_machine_vs_human_readable(self):
        assert _contains(self._path, "machine-readable")
        assert _contains(self._path, "human-readable")

    def test_documents_future_folder_structure(self):
        assert _contains(self._path, "03_framework") or _contains(self._path, "02_strategy")

    def test_client_draft_requires_human_review(self):
        assert _contains(self._path, "human review") or _contains(self._path, "human_review_required")

    def test_99_internal_never_client_facing(self):
        assert _contains(self._path, "99_internal") or _contains(self._path, "never client")

    def test_documents_json_format_notes(self):
        assert _contains(self._path, "utf-8") or _contains(self._path, "iso 8601")


# ---------------------------------------------------------------------------
# AGENT_HANDOFF_TEMPLATE content
# ---------------------------------------------------------------------------

class TestAgentHandoffTemplateContent:
    _path = _DOCS / "AGENT_HANDOFF_TEMPLATE.md"

    def test_has_tests_section(self):
        assert _contains(self._path, "tests run")

    def test_has_docs_audit_section(self):
        assert _contains(self._path, "docs audit")

    def test_has_git_status_section(self):
        assert _contains(self._path, "git status")

    def test_has_safety_boundary_section(self):
        assert _contains(self._path, "safety boundary")

    def test_has_blockers_section(self):
        assert _contains(self._path, "blockers")

    def test_has_recommended_next_step_section(self):
        assert _contains(self._path, "recommended next step")

    def test_has_intentionally_not_implemented_section(self):
        assert _contains(self._path, "intentionally not implemented")

    def test_has_secrets_section(self):
        assert _contains(self._path, "secrets") or _contains(self._path, "redaction")

    def test_has_generated_artifacts_section(self):
        assert _contains(self._path, "generated artifacts")

    def test_has_changed_files_section(self):
        assert _contains(self._path, "changed files")

    def test_references_agent_contract(self):
        assert _contains(self._path, "agent_contract")


# ---------------------------------------------------------------------------
# .gitignore check
# ---------------------------------------------------------------------------

class TestGitignore:
    def test_outputs_is_gitignored(self):
        gitignore = _ROOT / ".gitignore"
        content = _read(gitignore)
        assert "outputs/" in content, ".gitignore must include 'outputs/'"
