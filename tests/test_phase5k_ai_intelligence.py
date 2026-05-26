"""
Phase 5K — AI Intelligence Core tests.

Covers:
- IntakeClassification, IntakeReport schemas
- TestScenario, TestOracleReport schemas
- EvidenceGap, EvidenceCoverageItem, EvidenceIntelligenceReport schemas
- IntakeAgent.analyze() classification + risk scoring
- IntakeAgent.render_artifacts()
- TestOracle.generate() + generate_from_classification()
- TestOracle.render_artifacts()
- EvidenceIntelligence.analyze() + render_artifacts()
- CLI safety tests (blocked flags)
- Phase 5K exports
"""
from __future__ import annotations

import json
import subprocess
import sys


# ---------------------------------------------------------------------------
# TestIntakeClassificationSchema
# ---------------------------------------------------------------------------

class TestIntakeClassificationSchema:
    def test_default_classification_unknown(self):
        from core.schemas.intake import IntakeClassification
        c = IntakeClassification()
        assert c.classification == "unknown"

    def test_default_confidence_zero(self):
        from core.schemas.intake import IntakeClassification
        c = IntakeClassification()
        assert c.confidence == 0.0

    def test_default_risk_level_medium(self):
        from core.schemas.intake import IntakeClassification
        c = IntakeClassification()
        assert c.risk_level == "medium"

    def test_to_dict_includes_all_fields(self):
        from core.schemas.intake import IntakeClassification
        c = IntakeClassification(classification="api_testing", confidence=0.8)
        d = c.to_dict()
        assert d["classification"] == "api_testing"
        assert d["confidence"] == 0.8


# ---------------------------------------------------------------------------
# TestIntakeReportSchema
# ---------------------------------------------------------------------------

class TestIntakeReportSchema:
    def test_raw_input_stored_false_hardcoded(self):
        from core.schemas.intake import IntakeReport
        r = IntakeReport(project_id="p", raw_input_stored=True)
        assert r.raw_input_stored is False

    def test_credentials_in_output_false_hardcoded(self):
        from core.schemas.intake import IntakeReport
        r = IntakeReport(project_id="p", credentials_in_output=True)
        assert r.credentials_in_output is False

    def test_safe_to_deliver_false_hardcoded(self):
        from core.schemas.intake import IntakeReport
        r = IntakeReport(project_id="p", safe_to_deliver=True)
        assert r.safe_to_deliver is False

    def test_human_review_required_true_hardcoded(self):
        from core.schemas.intake import IntakeReport
        r = IntakeReport(project_id="p", human_review_required=False)
        assert r.human_review_required is True

    def test_from_dict_preserves_safety_invariants(self):
        from core.schemas.intake import IntakeReport
        r = IntakeReport.from_dict({
            "project_id": "p",
            "raw_input_stored": True,
            "credentials_in_output": True,
            "safe_to_deliver": True,
            "human_review_required": False,
        })
        assert r.raw_input_stored is False
        assert r.credentials_in_output is False
        assert r.safe_to_deliver is False
        assert r.human_review_required is True

    def test_from_dict_preserves_llm_calls_made(self):
        from core.schemas.intake import IntakeReport
        r = IntakeReport.from_dict({"project_id": "p", "llm_calls_made": True})
        assert r.llm_calls_made is True

    def test_to_dict_includes_classification(self):
        from core.schemas.intake import IntakeReport, IntakeClassification
        r = IntakeReport(
            project_id="p",
            classification=IntakeClassification(classification="auth_testing"),
        )
        d = r.to_dict()
        assert isinstance(d["classification"], dict)
        assert d["classification"]["classification"] == "auth_testing"


# ---------------------------------------------------------------------------
# TestTestScenarioSchema
# ---------------------------------------------------------------------------

class TestTestScenarioSchema:
    def test_default_priority_2(self):
        from core.schemas.test_oracle import TestScenario
        s = TestScenario(name="test")
        assert s.priority == 2

    def test_default_risk_score_half(self):
        from core.schemas.test_oracle import TestScenario
        s = TestScenario(name="test")
        assert s.risk_score == 0.5

    def test_deferred_false_by_default(self):
        from core.schemas.test_oracle import TestScenario
        s = TestScenario(name="test")
        assert s.deferred is False

    def test_to_dict_round_trip(self):
        from core.schemas.test_oracle import TestScenario
        s = TestScenario(name="login test", priority=1, risk_score=0.9, tags=["auth"])
        d = s.to_dict()
        assert d["name"] == "login test"
        assert d["tags"] == ["auth"]


# ---------------------------------------------------------------------------
# TestTestOracleReportSchema
# ---------------------------------------------------------------------------

class TestTestOracleReportSchema:
    def test_raw_input_stored_false_hardcoded(self):
        from core.schemas.test_oracle import TestOracleReport
        r = TestOracleReport(project_id="p", raw_input_stored=True)
        assert r.raw_input_stored is False

    def test_executable_without_approval_false_hardcoded(self):
        from core.schemas.test_oracle import TestOracleReport
        r = TestOracleReport(project_id="p", executable_without_approval=True)
        assert r.executable_without_approval is False

    def test_safe_to_deliver_false_hardcoded(self):
        from core.schemas.test_oracle import TestOracleReport
        r = TestOracleReport(project_id="p", safe_to_deliver=True)
        assert r.safe_to_deliver is False

    def test_human_review_required_true_hardcoded(self):
        from core.schemas.test_oracle import TestOracleReport
        r = TestOracleReport(project_id="p", human_review_required=False)
        assert r.human_review_required is True

    def test_from_dict_preserves_safety_invariants(self):
        from core.schemas.test_oracle import TestOracleReport
        r = TestOracleReport.from_dict({
            "project_id": "p",
            "executable_without_approval": True,
            "safe_to_deliver": True,
        })
        assert r.executable_without_approval is False
        assert r.safe_to_deliver is False
        assert r.human_review_required is True

    def test_from_dict_deserializes_scenarios(self):
        from core.schemas.test_oracle import TestOracleReport, TestScenario
        r = TestOracleReport.from_dict({
            "project_id": "p",
            "scenarios": [{"name": "login test", "priority": 1, "risk_score": 0.9, "tags": [], "coverage_area": "auth", "deferred": False, "defer_reason": ""}],
        })
        assert len(r.scenarios) == 1
        assert isinstance(r.scenarios[0], TestScenario)


# ---------------------------------------------------------------------------
# TestEvidenceSchemas
# ---------------------------------------------------------------------------

class TestEvidenceSchemas:
    def test_evidence_gap_defaults(self):
        from core.schemas.evidence_intelligence import EvidenceGap
        g = EvidenceGap()
        assert g.area == ""
        assert g.severity == "medium"

    def test_evidence_coverage_item_defaults(self):
        from core.schemas.evidence_intelligence import EvidenceCoverageItem
        item = EvidenceCoverageItem()
        assert item.present is False
        assert item.artifact_count == 0

    def test_report_network_calls_false_hardcoded(self):
        from core.schemas.evidence_intelligence import EvidenceIntelligenceReport
        r = EvidenceIntelligenceReport(project_id="p", network_calls_made=True)
        assert r.network_calls_made is False

    def test_report_execution_performed_false_hardcoded(self):
        from core.schemas.evidence_intelligence import EvidenceIntelligenceReport
        r = EvidenceIntelligenceReport(project_id="p", execution_performed=True)
        assert r.execution_performed is False

    def test_report_safe_to_deliver_false_hardcoded(self):
        from core.schemas.evidence_intelligence import EvidenceIntelligenceReport
        r = EvidenceIntelligenceReport(project_id="p", safe_to_deliver=True)
        assert r.safe_to_deliver is False

    def test_report_human_review_required_true_hardcoded(self):
        from core.schemas.evidence_intelligence import EvidenceIntelligenceReport
        r = EvidenceIntelligenceReport(project_id="p", human_review_required=False)
        assert r.human_review_required is True

    def test_from_dict_preserves_safety(self):
        from core.schemas.evidence_intelligence import EvidenceIntelligenceReport
        r = EvidenceIntelligenceReport.from_dict({
            "project_id": "p",
            "network_calls_made": True,
            "execution_performed": True,
            "safe_to_deliver": True,
        })
        assert r.network_calls_made is False
        assert r.execution_performed is False
        assert r.safe_to_deliver is False
        assert r.human_review_required is True


# ---------------------------------------------------------------------------
# TestIntakeAgentClassify
# ---------------------------------------------------------------------------

class TestIntakeAgentClassify:
    def _agent(self, tmp_path):
        from core.intake_agent import IntakeAgent
        return IntakeAgent(outputs_root=tmp_path)

    def test_classifies_auth_testing(self, tmp_path):
        agent = self._agent(tmp_path)
        report = agent.analyze("Test login and authentication with JWT tokens", "p")
        assert report.classification.classification == "auth_testing"

    def test_classifies_api_testing(self, tmp_path):
        agent = self._agent(tmp_path)
        report = agent.analyze("Test the REST API endpoints and check HTTP response codes", "p")
        assert report.classification.classification == "api_testing"

    def test_classifies_mobile_testing(self, tmp_path):
        agent = self._agent(tmp_path)
        report = agent.analyze("Test responsive mobile layout on iOS and Android smartphones", "p")
        assert report.classification.classification == "mobile_testing"

    def test_classifies_database_testing(self, tmp_path):
        agent = self._agent(tmp_path)
        report = agent.analyze("Query the database table and verify SQL records", "p")
        assert report.classification.classification == "database_testing"

    def test_classifies_visual_testing(self, tmp_path):
        agent = self._agent(tmp_path)
        report = agent.analyze("Visual regression test using screenshot baseline comparison", "p")
        assert report.classification.classification == "visual_testing"

    def test_classifies_unknown_for_empty_keywords(self, tmp_path):
        agent = self._agent(tmp_path)
        report = agent.analyze("xyz abc 123 random words with no test intent", "p")
        assert report.classification.classification == "unknown"

    def test_confidence_is_between_0_and_1(self, tmp_path):
        agent = self._agent(tmp_path)
        report = agent.analyze("Login authentication with JWT session token and password", "p")
        assert 0.0 <= report.classification.confidence <= 1.0

    def test_high_risk_payment_keyword(self, tmp_path):
        agent = self._agent(tmp_path)
        report = agent.analyze("Test the checkout payment billing transaction flow", "p")
        assert report.classification.risk_level == "critical"

    def test_low_risk_read_only_keyword(self, tmp_path):
        agent = self._agent(tmp_path)
        report = agent.analyze("Test the read-only public page display and search results", "p")
        assert report.classification.risk_level == "low"

    def test_recommended_modules_for_api(self, tmp_path):
        agent = self._agent(tmp_path)
        report = agent.analyze("Test the REST API endpoints and JSON response", "p")
        assert "api_smoke" in report.classification.recommended_modules

    def test_recommended_modules_for_auth(self, tmp_path):
        agent = self._agent(tmp_path)
        report = agent.analyze("Test login authentication and session management", "p")
        assert "browser" in report.classification.recommended_modules

    def test_evidence_keywords_non_empty_for_match(self, tmp_path):
        agent = self._agent(tmp_path)
        report = agent.analyze("Login with credentials and manage session JWT", "p")
        assert len(report.classification.evidence_keywords) > 0


# ---------------------------------------------------------------------------
# TestIntakeAgentAnalyze
# ---------------------------------------------------------------------------

class TestIntakeAgentAnalyze:
    def _agent(self, tmp_path):
        from core.intake_agent import IntakeAgent
        return IntakeAgent(outputs_root=tmp_path)

    def test_empty_input_blocked(self, tmp_path):
        agent = self._agent(tmp_path)
        report = agent.analyze("", "my-project")
        assert len(report.blockers) > 0

    def test_whitespace_only_blocked(self, tmp_path):
        agent = self._agent(tmp_path)
        report = agent.analyze("   \n  ", "my-project")
        assert len(report.blockers) > 0

    def test_missing_project_id_blocked(self, tmp_path):
        agent = self._agent(tmp_path)
        report = agent.analyze("Test login flow", "")
        assert len(report.blockers) > 0

    def test_raw_input_length_stored(self, tmp_path):
        agent = self._agent(tmp_path)
        text = "Test the login authentication"
        report = agent.analyze(text, "p")
        assert report.raw_input_length == len(text)

    def test_raw_input_not_in_to_dict(self, tmp_path):
        agent = self._agent(tmp_path)
        secret = "my-secret-password-123"
        report = agent.analyze(f"Login with {secret}", "p")
        d = report.to_dict()
        # Raw text must not appear in any string value in the dict
        d_str = str(d)
        assert secret not in d_str

    def test_intake_mode_is_heuristic(self, tmp_path):
        agent = self._agent(tmp_path)
        report = agent.analyze("Test API endpoint", "p")
        assert report.intake_mode == "heuristic"

    def test_llm_calls_made_false_in_heuristic(self, tmp_path):
        agent = self._agent(tmp_path)
        report = agent.analyze("Test API endpoint", "p")
        assert report.llm_calls_made is False


# ---------------------------------------------------------------------------
# TestIntakeAgentRenderArtifacts
# ---------------------------------------------------------------------------

class TestIntakeAgentRenderArtifacts:
    def test_creates_json_and_md(self, tmp_path):
        from core.intake_agent import IntakeAgent
        agent = IntakeAgent(outputs_root=tmp_path)
        report = agent.analyze("Test REST API response codes", "test-project")
        paths = agent.render_artifacts(report, "test-project")
        assert paths["json"].exists()
        assert paths["md"].exists()

    def test_json_has_safety_fields(self, tmp_path):
        from core.intake_agent import IntakeAgent
        agent = IntakeAgent(outputs_root=tmp_path)
        report = agent.analyze("Test API endpoint", "test-project")
        paths = agent.render_artifacts(report, "test-project")
        data = json.loads(paths["json"].read_text(encoding="utf-8"))
        assert data["raw_input_stored"] is False
        assert data["credentials_in_output"] is False
        assert data["human_review_required"] is True

    def test_json_does_not_contain_raw_input(self, tmp_path):
        from core.intake_agent import IntakeAgent
        agent = IntakeAgent(outputs_root=tmp_path)
        secret = "SuperSecretToken999"
        report = agent.analyze(f"Test login with {secret}", "test-project")
        paths = agent.render_artifacts(report, "test-project")
        content = paths["json"].read_text(encoding="utf-8")
        assert secret not in content

    def test_artifacts_in_22_intake_dir(self, tmp_path):
        from core.intake_agent import IntakeAgent
        agent = IntakeAgent(outputs_root=tmp_path)
        report = agent.analyze("Test API", "test-project")
        paths = agent.render_artifacts(report, "test-project")
        assert "22_intake" in str(paths["json"])


# ---------------------------------------------------------------------------
# TestTestOracleGenerate
# ---------------------------------------------------------------------------

class TestTestOracleGenerate:
    def _oracle(self, tmp_path):
        from core.test_oracle import TestOracle
        return TestOracle(outputs_root=tmp_path)

    def test_generates_auth_scenarios(self, tmp_path):
        oracle = self._oracle(tmp_path)
        report = oracle.generate_from_classification("auth_testing", "p")
        assert report.total_scenarios > 0
        names = [s.name for s in report.scenarios]
        assert any("login" in n.lower() or "Login" in n for n in names)

    def test_generates_api_scenarios(self, tmp_path):
        oracle = self._oracle(tmp_path)
        report = oracle.generate_from_classification("api_testing", "p")
        assert report.total_scenarios > 0
        assert report.source_classification == "api_testing"

    def test_all_classifications_produce_scenarios(self, tmp_path):
        from core.schemas.intake import INTAKE_CLASSIFICATIONS
        oracle = self._oracle(tmp_path)
        for cls in INTAKE_CLASSIFICATIONS:
            report = oracle.generate_from_classification(cls, "p")
            assert report.total_scenarios > 0, f"No scenarios for {cls}"

    def test_scenarios_have_valid_priority(self, tmp_path):
        oracle = self._oracle(tmp_path)
        report = oracle.generate_from_classification("api_testing", "p")
        for s in report.scenarios:
            assert s.priority in (1, 2, 3)

    def test_scenarios_have_valid_risk_score(self, tmp_path):
        oracle = self._oracle(tmp_path)
        report = oracle.generate_from_classification("auth_testing", "p")
        for s in report.scenarios:
            assert 0.0 <= s.risk_score <= 1.0

    def test_performance_has_deferred_scenarios(self, tmp_path):
        oracle = self._oracle(tmp_path)
        report = oracle.generate_from_classification("performance_testing", "p")
        assert len(report.deferred_scenarios) > 0
        assert all(s.deferred for s in report.deferred_scenarios)

    def test_security_has_deferred_scenarios(self, tmp_path):
        oracle = self._oracle(tmp_path)
        report = oracle.generate_from_classification("security_testing", "p")
        assert len(report.deferred_scenarios) > 0

    def test_generate_from_intake_report(self, tmp_path):
        from core.intake_agent import IntakeAgent
        from core.test_oracle import TestOracle
        agent = IntakeAgent(outputs_root=tmp_path)
        oracle = TestOracle(outputs_root=tmp_path)
        intake_report = agent.analyze("Test the REST API endpoints", "p")
        oracle_report = oracle.generate(intake_report=intake_report, project_id="p")
        assert oracle_report.total_scenarios > 0

    def test_generate_from_blocked_intake_returns_blocker(self, tmp_path):
        from core.schemas.intake import IntakeReport
        from core.test_oracle import TestOracle
        oracle = TestOracle(outputs_root=tmp_path)
        bad_intake = IntakeReport(project_id="p")
        bad_intake.blockers.append("empty input")
        report = oracle.generate(intake_report=bad_intake, project_id="p")
        assert len(report.blockers) > 0

    def test_missing_project_id_blocked(self, tmp_path):
        oracle = self._oracle(tmp_path)
        report = oracle.generate_from_classification("api_testing", "")
        assert len(report.blockers) > 0


# ---------------------------------------------------------------------------
# TestTestOracleRenderArtifacts
# ---------------------------------------------------------------------------

class TestTestOracleRenderArtifacts:
    def test_creates_json_and_md(self, tmp_path):
        from core.test_oracle import TestOracle
        oracle = TestOracle(outputs_root=tmp_path)
        report = oracle.generate_from_classification("api_testing", "proj")
        paths = oracle.render_artifacts(report, "proj")
        assert paths["json"].exists()
        assert paths["md"].exists()

    def test_json_has_safety_fields(self, tmp_path):
        from core.test_oracle import TestOracle
        oracle = TestOracle(outputs_root=tmp_path)
        report = oracle.generate_from_classification("auth_testing", "proj")
        paths = oracle.render_artifacts(report, "proj")
        data = json.loads(paths["json"].read_text(encoding="utf-8"))
        assert data["raw_input_stored"] is False
        assert data["executable_without_approval"] is False
        assert data["human_review_required"] is True

    def test_artifacts_in_23_test_oracle_dir(self, tmp_path):
        from core.test_oracle import TestOracle
        oracle = TestOracle(outputs_root=tmp_path)
        report = oracle.generate_from_classification("api_testing", "proj")
        paths = oracle.render_artifacts(report, "proj")
        assert "23_test_oracle" in str(paths["json"])

    def test_md_contains_scenario_names(self, tmp_path):
        from core.test_oracle import TestOracle
        oracle = TestOracle(outputs_root=tmp_path)
        report = oracle.generate_from_classification("api_testing", "proj")
        paths = oracle.render_artifacts(report, "proj")
        md = paths["md"].read_text(encoding="utf-8")
        assert any(s.name in md for s in report.scenarios)


# ---------------------------------------------------------------------------
# TestEvidenceIntelligenceAnalyze
# ---------------------------------------------------------------------------

class TestEvidenceIntelligenceAnalyze:
    def _ei(self, tmp_path):
        from core.evidence_intelligence import EvidenceIntelligence
        return EvidenceIntelligence(outputs_root=tmp_path)

    def test_missing_project_id_blocked(self, tmp_path):
        ei = self._ei(tmp_path)
        report = ei.analyze(project_id="")
        assert len(report.blockers) > 0

    def test_nonexistent_project_dir_returns_zero_score(self, tmp_path):
        ei = self._ei(tmp_path)
        report = ei.analyze(project_id="no-such-project")
        assert report.overall_coverage_score == 0.0

    def test_empty_project_dir_has_gaps(self, tmp_path):
        ei = self._ei(tmp_path)
        # Create project dir but no artifact subdirs
        (tmp_path / "my-project").mkdir()
        report = ei.analyze(project_id="my-project")
        assert len(report.gaps) > 0
        assert report.overall_coverage_score == 0.0

    def test_full_coverage_score_1(self, tmp_path):
        from core.schemas.evidence_intelligence import EVIDENCE_ARTIFACT_DIR_MAP
        ei = self._ei(tmp_path)
        project_dir = tmp_path / "full-project"
        # Create all artifact dirs
        for area_dir in EVIDENCE_ARTIFACT_DIR_MAP.values():
            (project_dir / area_dir).mkdir(parents=True, exist_ok=True)
        report = ei.analyze(project_id="full-project")
        assert report.overall_coverage_score == 1.0
        assert len(report.gaps) == 0

    def test_partial_coverage_score_between_0_and_1(self, tmp_path):
        from core.schemas.evidence_intelligence import EVIDENCE_ARTIFACT_DIR_MAP
        ei = self._ei(tmp_path)
        project_dir = tmp_path / "partial"
        dirs = list(EVIDENCE_ARTIFACT_DIR_MAP.values())
        # Create half the dirs
        for d in dirs[:len(dirs)//2]:
            (project_dir / d).mkdir(parents=True, exist_ok=True)
        report = ei.analyze(project_id="partial")
        assert 0.0 < report.overall_coverage_score < 1.0

    def test_high_severity_gap_counted(self, tmp_path):
        ei = self._ei(tmp_path)
        (tmp_path / "p").mkdir()
        report = ei.analyze(project_id="p", areas_to_check=["auth"])
        # auth has severity=high
        assert report.high_severity_gap_count == 1

    def test_areas_to_check_filters_coverage(self, tmp_path):
        ei = self._ei(tmp_path)
        (tmp_path / "p").mkdir()
        report = ei.analyze(project_id="p", areas_to_check=["api", "mobile"])
        assert len(report.coverage_items) == 2

    def test_network_calls_made_always_false(self, tmp_path):
        ei = self._ei(tmp_path)
        (tmp_path / "p").mkdir()
        report = ei.analyze(project_id="p")
        assert report.network_calls_made is False

    def test_execution_performed_always_false(self, tmp_path):
        ei = self._ei(tmp_path)
        (tmp_path / "p").mkdir()
        report = ei.analyze(project_id="p")
        assert report.execution_performed is False


# ---------------------------------------------------------------------------
# TestEvidenceIntelligenceRenderArtifacts
# ---------------------------------------------------------------------------

class TestEvidenceIntelligenceRenderArtifacts:
    def test_creates_json_and_md(self, tmp_path):
        from core.evidence_intelligence import EvidenceIntelligence
        ei = EvidenceIntelligence(outputs_root=tmp_path)
        (tmp_path / "proj").mkdir()
        report = ei.analyze(project_id="proj")
        paths = ei.render_artifacts(report, "proj")
        assert paths["json"].exists()
        assert paths["md"].exists()

    def test_json_has_safety_fields(self, tmp_path):
        from core.evidence_intelligence import EvidenceIntelligence
        ei = EvidenceIntelligence(outputs_root=tmp_path)
        (tmp_path / "proj2").mkdir()
        report = ei.analyze(project_id="proj2")
        paths = ei.render_artifacts(report, "proj2")
        data = json.loads(paths["json"].read_text(encoding="utf-8"))
        assert data["network_calls_made"] is False
        assert data["execution_performed"] is False
        assert data["human_review_required"] is True

    def test_artifacts_in_24_dir(self, tmp_path):
        from core.evidence_intelligence import EvidenceIntelligence
        ei = EvidenceIntelligence(outputs_root=tmp_path)
        (tmp_path / "proj3").mkdir()
        report = ei.analyze(project_id="proj3")
        paths = ei.render_artifacts(report, "proj3")
        assert "24_evidence_intelligence" in str(paths["json"])

    def test_json_includes_coverage_score(self, tmp_path):
        from core.evidence_intelligence import EvidenceIntelligence
        ei = EvidenceIntelligence(outputs_root=tmp_path)
        (tmp_path / "proj4").mkdir()
        report = ei.analyze(project_id="proj4")
        paths = ei.render_artifacts(report, "proj4")
        data = json.loads(paths["json"].read_text(encoding="utf-8"))
        assert "overall_coverage_score" in data


# ---------------------------------------------------------------------------
# TestIntakeCLISafety
# ---------------------------------------------------------------------------

class TestIntakeCLISafety:
    def _run_blocked(self, flag: str):
        return subprocess.run(
            [sys.executable, "tools/run_intake_agent.py",
             "--project-id", "p",
             flag, "value"],
            capture_output=True, text=True,
        )

    def test_blocked_flag_password(self):
        result = self._run_blocked("--password")
        assert result.returncode == 2
        assert "BLOCKED" in result.stderr

    def test_blocked_flag_token(self):
        result = self._run_blocked("--token")
        assert result.returncode == 2

    def test_blocked_flag_secret(self):
        result = self._run_blocked("--secret")
        assert result.returncode == 2

    def test_blocked_flag_api_key(self):
        result = self._run_blocked("--api-key")
        assert result.returncode == 2

    def test_missing_project_id_exits_nonzero(self):
        result = subprocess.run(
            [sys.executable, "tools/run_intake_agent.py"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0

    def test_missing_input_exits_2(self):
        result = subprocess.run(
            [sys.executable, "tools/run_intake_agent.py",
             "--project-id", "p"],
            capture_output=True, text=True,
        )
        assert result.returncode == 2


# ---------------------------------------------------------------------------
# TestPhase5KConstants
# ---------------------------------------------------------------------------

class TestPhase5KConstants:
    def test_intake_classifications_includes_unknown(self):
        from core.schemas.intake import INTAKE_CLASSIFICATIONS
        assert "unknown" in INTAKE_CLASSIFICATIONS

    def test_intake_classifications_count(self):
        from core.schemas.intake import INTAKE_CLASSIFICATIONS
        assert len(INTAKE_CLASSIFICATIONS) == 9

    def test_intake_risk_levels(self):
        from core.schemas.intake import INTAKE_RISK_LEVELS
        assert "high" in INTAKE_RISK_LEVELS
        assert "critical" in INTAKE_RISK_LEVELS

    def test_test_coverage_areas(self):
        from core.schemas.test_oracle import TEST_COVERAGE_AREAS
        assert "auth" in TEST_COVERAGE_AREAS
        assert "api" in TEST_COVERAGE_AREAS

    def test_evidence_gap_severities(self):
        from core.schemas.evidence_intelligence import EVIDENCE_GAP_SEVERITIES
        assert "critical" in EVIDENCE_GAP_SEVERITIES
        assert "low" in EVIDENCE_GAP_SEVERITIES

    def test_evidence_artifact_dir_map_nonempty(self):
        from core.schemas.evidence_intelligence import EVIDENCE_ARTIFACT_DIR_MAP
        assert len(EVIDENCE_ARTIFACT_DIR_MAP) > 0
        assert "auth" in EVIDENCE_ARTIFACT_DIR_MAP


# ---------------------------------------------------------------------------
# TestPhase5KExports
# ---------------------------------------------------------------------------

class TestPhase5KExports:
    def test_intake_report_importable_from_schemas(self):
        from core.schemas import IntakeReport
        assert IntakeReport is not None

    def test_intake_classification_importable(self):
        from core.schemas import IntakeClassification
        assert IntakeClassification is not None

    def test_test_oracle_report_importable(self):
        from core.schemas import TestOracleReport
        assert TestOracleReport is not None

    def test_test_scenario_importable(self):
        from core.schemas import TestScenario
        assert TestScenario is not None

    def test_evidence_intelligence_report_importable(self):
        from core.schemas import EvidenceIntelligenceReport
        assert EvidenceIntelligenceReport is not None

    def test_evidence_gap_importable(self):
        from core.schemas import EvidenceGap
        assert EvidenceGap is not None

    def test_intake_agent_importable(self):
        from core.intake_agent import IntakeAgent
        assert callable(IntakeAgent)

    def test_test_oracle_importable(self):
        from core.test_oracle import TestOracle
        assert callable(TestOracle)

    def test_evidence_intelligence_importable(self):
        from core.evidence_intelligence import EvidenceIntelligence
        assert callable(EvidenceIntelligence)
