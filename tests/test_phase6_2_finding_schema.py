"""Phase 6.2 tests -- Structured Finding Schema, RiskMatrix, finding adapters.

~90 tests covering:
  - Finding dataclass (construction, to_dict, from_dict, defaults)
  - Severity / FindingCategory / FindingStatus / Confidence enums
  - risk_score function
  - RiskMatrix (sorting, grouping, summary, top_n)
  - findings_from_api_contract adapter
  - findings_from_secret_scan adapter
  - Integration: adapters -> RiskMatrix -> summary
  - ClientAuditResult / ModuleResult structured fields (schema-only)
"""
from __future__ import annotations


from core.schemas.finding import (
    Confidence,
    Finding,
    FindingCategory,
    FindingStatus,
    Severity,
)
from core.risk.risk_matrix import RiskMatrix, risk_score
from core.risk.finding_adapters import (
    findings_from_api_contract,
    findings_from_secret_scan,
)
from core.schemas.client_audit import ClientAuditResult, ModuleResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_finding(
    fid: str = "TEST-001",
    severity: Severity = Severity.MEDIUM,
    category: FindingCategory = FindingCategory.API,
    confidence: Confidence = Confidence.HIGH,
    status: FindingStatus = FindingStatus.OPEN,
    source_module: str = "test_module",
    tags: list[str] | None = None,
) -> Finding:
    return Finding(
        id=fid,
        title=f"Test finding {fid}",
        description="A test finding",
        severity=severity,
        category=category,
        source_module=source_module,
        confidence=confidence,
        status=status,
        tags=tags or [],
    )


# ---------------------------------------------------------------------------
# TestSeverityEnum
# ---------------------------------------------------------------------------

class TestSeverityEnum:
    def test_all_values_present(self) -> None:
        values = {s.value for s in Severity}
        assert values == {"critical", "high", "medium", "low", "info"}

    def test_str_subclass(self) -> None:
        assert isinstance(Severity.CRITICAL, str)
        assert Severity.HIGH == "high"

    def test_ordering_by_value(self) -> None:
        assert Severity("critical") == Severity.CRITICAL
        assert Severity("info") == Severity.INFO

    def test_five_levels(self) -> None:
        assert len(list(Severity)) == 5


# ---------------------------------------------------------------------------
# TestFindingCategoryEnum
# ---------------------------------------------------------------------------

class TestFindingCategoryEnum:
    def test_eleven_categories(self) -> None:
        assert len(list(FindingCategory)) == 11

    def test_all_values(self) -> None:
        expected = {
            "functional", "api", "security", "performance", "accessibility",
            "ux", "reliability", "maintainability", "configuration",
            "documentation", "unknown",
        }
        assert {c.value for c in FindingCategory} == expected

    def test_str_subclass(self) -> None:
        assert isinstance(FindingCategory.API, str)
        assert FindingCategory.SECURITY == "security"


# ---------------------------------------------------------------------------
# TestFindingStatusEnum
# ---------------------------------------------------------------------------

class TestFindingStatusEnum:
    def test_five_statuses(self) -> None:
        assert len(list(FindingStatus)) == 5

    def test_all_values(self) -> None:
        expected = {"open", "accepted_risk", "false_positive", "fixed", "needs_review"}
        assert {s.value for s in FindingStatus} == expected

    def test_str_subclass(self) -> None:
        assert isinstance(FindingStatus.OPEN, str)


# ---------------------------------------------------------------------------
# TestConfidenceEnum
# ---------------------------------------------------------------------------

class TestConfidenceEnum:
    def test_three_levels(self) -> None:
        assert len(list(Confidence)) == 3

    def test_values(self) -> None:
        assert {c.value for c in Confidence} == {"high", "medium", "low"}

    def test_str_subclass(self) -> None:
        assert isinstance(Confidence.HIGH, str)


# ---------------------------------------------------------------------------
# TestFindingConstruction
# ---------------------------------------------------------------------------

class TestFindingConstruction:
    def test_required_fields(self) -> None:
        f = Finding(
            id="F-001",
            title="Test",
            description="Desc",
            severity=Severity.HIGH,
            category=FindingCategory.API,
            source_module="mod",
        )
        assert f.id == "F-001"
        assert f.severity == Severity.HIGH
        assert f.category == FindingCategory.API

    def test_default_confidence_medium(self) -> None:
        f2 = Finding(
            id="X", title="T", description="D",
            severity=Severity.LOW, category=FindingCategory.FUNCTIONAL,
            source_module="m",
        )
        assert f2.confidence == Confidence.MEDIUM

    def test_default_status_open(self) -> None:
        f = Finding(
            id="X", title="T", description="D",
            severity=Severity.INFO, category=FindingCategory.UNKNOWN,
            source_module="m",
        )
        assert f.status == FindingStatus.OPEN

    def test_default_tags_empty_list(self) -> None:
        f = _make_finding()
        assert f.tags == []

    def test_default_optional_strings_empty(self) -> None:
        f = Finding(
            id="X", title="T", description="D",
            severity=Severity.INFO, category=FindingCategory.UNKNOWN,
            source_module="m",
        )
        assert f.affected_area == ""
        assert f.evidence == ""
        assert f.recommendation == ""
        assert f.client_impact == ""
        assert f.created_at == ""

    def test_full_construction(self) -> None:
        f = Finding(
            id="SEC-001",
            title="Critical issue",
            description="Details here",
            severity=Severity.CRITICAL,
            category=FindingCategory.SECURITY,
            source_module="passive_security",
            affected_area="login page",
            evidence="header missing",
            recommendation="Add header",
            client_impact="Exposure to XSS",
            confidence=Confidence.HIGH,
            status=FindingStatus.NEEDS_REVIEW,
            tags=["security", "header"],
            created_at="2026-01-01T00:00:00",
        )
        assert f.severity == Severity.CRITICAL
        assert f.tags == ["security", "header"]
        assert f.status == FindingStatus.NEEDS_REVIEW


# ---------------------------------------------------------------------------
# TestFindingToDict
# ---------------------------------------------------------------------------

class TestFindingToDict:
    def test_to_dict_returns_dict(self) -> None:
        f = _make_finding("API-001", severity=Severity.HIGH)
        d = f.to_dict()
        assert isinstance(d, dict)

    def test_severity_serialized_as_value(self) -> None:
        f = _make_finding(severity=Severity.CRITICAL)
        assert f.to_dict()["severity"] == "critical"

    def test_category_serialized_as_value(self) -> None:
        f = _make_finding(category=FindingCategory.SECURITY)
        assert f.to_dict()["category"] == "security"

    def test_confidence_serialized_as_value(self) -> None:
        f = _make_finding(confidence=Confidence.LOW)
        assert f.to_dict()["confidence"] == "low"

    def test_status_serialized_as_value(self) -> None:
        f = _make_finding(status=FindingStatus.NEEDS_REVIEW)
        assert f.to_dict()["status"] == "needs_review"

    def test_all_keys_present(self) -> None:
        f = _make_finding()
        d = f.to_dict()
        required_keys = {
            "id", "title", "description", "severity", "category",
            "source_module", "affected_area", "evidence", "recommendation",
            "client_impact", "confidence", "status", "tags", "created_at",
        }
        assert required_keys == set(d.keys())

    def test_tags_serialized_as_list(self) -> None:
        f = _make_finding(tags=["a", "b"])
        assert f.to_dict()["tags"] == ["a", "b"]


# ---------------------------------------------------------------------------
# TestFindingFromDict
# ---------------------------------------------------------------------------

class TestFindingFromDict:
    def test_roundtrip(self) -> None:
        f = _make_finding("ROUND-001", severity=Severity.HIGH, confidence=Confidence.LOW)
        d = f.to_dict()
        f2 = Finding.from_dict(d)
        assert f2.id == f.id
        assert f2.severity == f.severity
        assert f2.confidence == f.confidence

    def test_from_dict_defaults_info_severity(self) -> None:
        f = Finding.from_dict({"id": "X", "title": "T", "description": "D",
                                "source_module": "m"})
        assert f.severity == Severity.INFO

    def test_from_dict_defaults_unknown_category(self) -> None:
        f = Finding.from_dict({"id": "X", "title": "T", "description": "D",
                                "source_module": "m"})
        assert f.category == FindingCategory.UNKNOWN

    def test_from_dict_defaults_medium_confidence(self) -> None:
        f = Finding.from_dict({"id": "X", "title": "T", "description": "D",
                                "source_module": "m"})
        assert f.confidence == Confidence.MEDIUM

    def test_from_dict_defaults_open_status(self) -> None:
        f = Finding.from_dict({"id": "X", "title": "T", "description": "D",
                                "source_module": "m"})
        assert f.status == FindingStatus.OPEN

    def test_from_dict_full(self) -> None:
        data = {
            "id": "SEC-999",
            "title": "Big problem",
            "description": "Bad thing happened",
            "severity": "critical",
            "category": "security",
            "source_module": "scanner",
            "affected_area": "auth",
            "evidence": "found it",
            "recommendation": "fix it",
            "client_impact": "user data exposed",
            "confidence": "high",
            "status": "needs_review",
            "tags": ["critical", "auth"],
            "created_at": "2026-05-01",
        }
        f = Finding.from_dict(data)
        assert f.severity == Severity.CRITICAL
        assert f.status == FindingStatus.NEEDS_REVIEW
        assert f.tags == ["critical", "auth"]


# ---------------------------------------------------------------------------
# TestRiskScore
# ---------------------------------------------------------------------------

class TestRiskScore:
    def test_critical_high_confidence(self) -> None:
        f = _make_finding(severity=Severity.CRITICAL, confidence=Confidence.HIGH)
        assert risk_score(f) == 5.0

    def test_high_high_confidence(self) -> None:
        f = _make_finding(severity=Severity.HIGH, confidence=Confidence.HIGH)
        assert risk_score(f) == 4.0

    def test_medium_high_confidence(self) -> None:
        f = _make_finding(severity=Severity.MEDIUM, confidence=Confidence.HIGH)
        assert risk_score(f) == 3.0

    def test_low_high_confidence(self) -> None:
        f = _make_finding(severity=Severity.LOW, confidence=Confidence.HIGH)
        assert risk_score(f) == 2.0

    def test_info_high_confidence(self) -> None:
        f = _make_finding(severity=Severity.INFO, confidence=Confidence.HIGH)
        assert risk_score(f) == 1.0

    def test_critical_medium_confidence(self) -> None:
        f = _make_finding(severity=Severity.CRITICAL, confidence=Confidence.MEDIUM)
        assert risk_score(f) == 3.75

    def test_critical_low_confidence(self) -> None:
        f = _make_finding(severity=Severity.CRITICAL, confidence=Confidence.LOW)
        assert risk_score(f) == 2.5

    def test_info_low_confidence(self) -> None:
        f = _make_finding(severity=Severity.INFO, confidence=Confidence.LOW)
        assert risk_score(f) == 0.5

    def test_returns_float(self) -> None:
        f = _make_finding()
        assert isinstance(risk_score(f), float)


# ---------------------------------------------------------------------------
# TestRiskMatrixSorting
# ---------------------------------------------------------------------------

class TestRiskMatrixSorting:
    def test_sorted_by_risk_descending(self) -> None:
        f_low = _make_finding("LOW-001", severity=Severity.LOW, confidence=Confidence.HIGH)
        f_high = _make_finding("HIGH-001", severity=Severity.HIGH, confidence=Confidence.HIGH)
        f_crit = _make_finding("CRIT-001", severity=Severity.CRITICAL, confidence=Confidence.HIGH)
        rm = RiskMatrix([f_low, f_high, f_crit])
        ordered = rm.sorted_by_risk()
        assert ordered[0].id == "CRIT-001"
        assert ordered[1].id == "HIGH-001"
        assert ordered[2].id == "LOW-001"

    def test_tie_broken_by_id_ascending(self) -> None:
        f_a = _make_finding("AAA-001", severity=Severity.HIGH, confidence=Confidence.HIGH)
        f_b = _make_finding("BBB-001", severity=Severity.HIGH, confidence=Confidence.HIGH)
        rm = RiskMatrix([f_b, f_a])
        ordered = rm.sorted_by_risk()
        assert ordered[0].id == "AAA-001"
        assert ordered[1].id == "BBB-001"

    def test_empty_findings_sorted_empty(self) -> None:
        rm = RiskMatrix([])
        assert rm.sorted_by_risk() == []

    def test_single_finding(self) -> None:
        f = _make_finding()
        rm = RiskMatrix([f])
        assert rm.sorted_by_risk() == [f]

    def test_top_n_returns_n(self) -> None:
        findings = [_make_finding(f"F-{i:03d}") for i in range(10)]
        rm = RiskMatrix(findings)
        assert len(rm.top_n(5)) == 5

    def test_top_n_fewer_than_n(self) -> None:
        findings = [_make_finding("F-001"), _make_finding("F-002")]
        rm = RiskMatrix(findings)
        assert len(rm.top_n(5)) == 2

    def test_top_n_empty(self) -> None:
        rm = RiskMatrix([])
        assert rm.top_n(5) == []


# ---------------------------------------------------------------------------
# TestRiskMatrixGrouping
# ---------------------------------------------------------------------------

class TestRiskMatrixGrouping:
    def test_by_severity_all_levels_present(self) -> None:
        f = _make_finding(severity=Severity.HIGH)
        rm = RiskMatrix([f])
        grouped = rm.by_severity()
        assert set(grouped.keys()) == {"critical", "high", "medium", "low", "info"}

    def test_by_severity_correct_placement(self) -> None:
        f_crit = _make_finding("C-001", severity=Severity.CRITICAL)
        f_info = _make_finding("I-001", severity=Severity.INFO)
        rm = RiskMatrix([f_crit, f_info])
        grouped = rm.by_severity()
        assert len(grouped["critical"]) == 1
        assert len(grouped["info"]) == 1
        assert grouped["high"] == []

    def test_by_category_only_non_empty(self) -> None:
        f = _make_finding(category=FindingCategory.SECURITY)
        rm = RiskMatrix([f])
        grouped = rm.by_category()
        assert "security" in grouped
        assert "api" not in grouped

    def test_by_source_module(self) -> None:
        f1 = _make_finding("F-001", source_module="mod_a")
        f2 = _make_finding("F-002", source_module="mod_b")
        f3 = _make_finding("F-003", source_module="mod_a")
        rm = RiskMatrix([f1, f2, f3])
        grouped = rm.by_source_module()
        assert len(grouped["mod_a"]) == 2
        assert len(grouped["mod_b"]) == 1

    def test_count_by_severity(self) -> None:
        f_crit = _make_finding("C-001", severity=Severity.CRITICAL)
        f_high = _make_finding("H-001", severity=Severity.HIGH)
        f_high2 = _make_finding("H-002", severity=Severity.HIGH)
        rm = RiskMatrix([f_crit, f_high, f_high2])
        counts = rm.count_by_severity()
        assert counts["critical"] == 1
        assert counts["high"] == 2
        assert counts["medium"] == 0

    def test_count_by_category(self) -> None:
        f1 = _make_finding(category=FindingCategory.API)
        f2 = _make_finding(category=FindingCategory.API)
        f3 = _make_finding(category=FindingCategory.SECURITY)
        rm = RiskMatrix([f1, f2, f3])
        counts = rm.count_by_category()
        assert counts["api"] == 2
        assert counts["security"] == 1
        assert "functional" not in counts


# ---------------------------------------------------------------------------
# TestRiskMatrixSummary
# ---------------------------------------------------------------------------

class TestRiskMatrixSummary:
    def test_summary_keys(self) -> None:
        rm = RiskMatrix([_make_finding()])
        s = rm.summary()
        assert "total" in s
        assert "by_severity" in s
        assert "by_category" in s
        assert "top_risks" in s
        assert "has_critical" in s
        assert "has_high" in s
        assert "recommended_next_actions" in s

    def test_summary_total(self) -> None:
        rm = RiskMatrix([_make_finding("A"), _make_finding("B")])
        assert rm.summary()["total"] == 2

    def test_summary_has_critical_true(self) -> None:
        f = _make_finding(severity=Severity.CRITICAL)
        rm = RiskMatrix([f])
        assert rm.summary()["has_critical"] is True

    def test_summary_has_critical_false(self) -> None:
        f = _make_finding(severity=Severity.HIGH)
        rm = RiskMatrix([f])
        assert rm.summary()["has_critical"] is False

    def test_summary_has_high_true(self) -> None:
        f = _make_finding(severity=Severity.HIGH)
        rm = RiskMatrix([f])
        assert rm.summary()["has_high"] is True

    def test_summary_empty_findings(self) -> None:
        rm = RiskMatrix([])
        s = rm.summary()
        assert s["total"] == 0
        assert "No findings generated" in s["recommended_next_actions"][0]

    def test_summary_next_actions_critical(self) -> None:
        f = _make_finding(severity=Severity.CRITICAL)
        rm = RiskMatrix([f])
        actions = rm.summary()["recommended_next_actions"]
        assert any("CRITICAL" in a for a in actions)

    def test_summary_next_actions_high(self) -> None:
        f = _make_finding(severity=Severity.HIGH)
        rm = RiskMatrix([f])
        actions = rm.summary()["recommended_next_actions"]
        assert any("HIGH" in a for a in actions)

    def test_summary_top_risks_serialized(self) -> None:
        f = _make_finding("TT-001", severity=Severity.CRITICAL)
        rm = RiskMatrix([f])
        top = rm.summary()["top_risks"]
        assert len(top) == 1
        assert top[0]["id"] == "TT-001"
        assert isinstance(top[0]["severity"], str)

    def test_defensive_copy(self) -> None:
        findings = [_make_finding("A-001")]
        rm = RiskMatrix(findings)
        findings.clear()
        assert rm.summary()["total"] == 1


# ---------------------------------------------------------------------------
# TestFindingsFromApiContract
# ---------------------------------------------------------------------------

class TestFindingsFromApiContract:
    def test_no_issues_empty_list(self) -> None:
        result = findings_from_api_contract(
            project_id="proj", source_file="spec.json",
            blocked_count=0, requires_approval_count=0, parse_errors=[],
        )
        assert result == []

    def test_blocked_count_produces_high_finding(self) -> None:
        result = findings_from_api_contract(
            project_id="proj", source_file="spec.json",
            blocked_count=3, requires_approval_count=0, parse_errors=[],
        )
        assert len(result) == 1
        assert result[0].severity == Severity.HIGH
        assert result[0].category == FindingCategory.API
        assert "3" in result[0].title or "3" in result[0].description

    def test_requires_approval_produces_medium_finding(self) -> None:
        result = findings_from_api_contract(
            project_id="proj", source_file="spec.json",
            blocked_count=0, requires_approval_count=5, parse_errors=[],
        )
        assert len(result) == 1
        assert result[0].severity == Severity.MEDIUM
        assert result[0].category == FindingCategory.API

    def test_parse_errors_produces_low_finding(self) -> None:
        result = findings_from_api_contract(
            project_id="proj", source_file="spec.json",
            blocked_count=0, requires_approval_count=0,
            parse_errors=["err1", "err2"],
        )
        assert len(result) == 1
        assert result[0].severity == Severity.LOW
        assert result[0].category == FindingCategory.DOCUMENTATION

    def test_all_three_issues_three_findings(self) -> None:
        result = findings_from_api_contract(
            project_id="proj", source_file="spec.json",
            blocked_count=2, requires_approval_count=4,
            parse_errors=["e1"],
        )
        assert len(result) == 3

    def test_finding_ids_contain_project_id(self) -> None:
        result = findings_from_api_contract(
            project_id="myproject", source_file="spec.json",
            blocked_count=1, requires_approval_count=0, parse_errors=[],
        )
        assert "MYPROJECT" in result[0].id

    def test_blocked_finding_status_needs_review(self) -> None:
        result = findings_from_api_contract(
            project_id="p", source_file="s.json",
            blocked_count=1, requires_approval_count=0, parse_errors=[],
        )
        assert result[0].status == FindingStatus.NEEDS_REVIEW

    def test_approval_finding_status_needs_review(self) -> None:
        result = findings_from_api_contract(
            project_id="p", source_file="s.json",
            blocked_count=0, requires_approval_count=1, parse_errors=[],
        )
        assert result[0].status == FindingStatus.NEEDS_REVIEW

    def test_parse_error_finding_status_open(self) -> None:
        result = findings_from_api_contract(
            project_id="p", source_file="s.json",
            blocked_count=0, requires_approval_count=0, parse_errors=["e1"],
        )
        assert result[0].status == FindingStatus.OPEN

    def test_blocked_finding_high_confidence(self) -> None:
        result = findings_from_api_contract(
            project_id="p", source_file="s.json",
            blocked_count=1, requires_approval_count=0, parse_errors=[],
        )
        assert result[0].confidence == Confidence.HIGH

    def test_source_file_in_evidence_or_description(self) -> None:
        result = findings_from_api_contract(
            project_id="p", source_file="api_spec.json",
            blocked_count=1, requires_approval_count=0, parse_errors=[],
        )
        assert "api_spec.json" in result[0].description or "api_spec.json" in result[0].affected_area


# ---------------------------------------------------------------------------
# TestFindingsFromSecretScan
# ---------------------------------------------------------------------------

class TestFindingsFromSecretScan:
    def test_passed_scan_empty_list(self) -> None:
        result = findings_from_secret_scan("proj", secret_scan_passed=True)
        assert result == []

    def test_failed_scan_one_critical_finding(self) -> None:
        result = findings_from_secret_scan("proj", secret_scan_passed=False)
        assert len(result) == 1
        assert result[0].severity == Severity.CRITICAL
        assert result[0].category == FindingCategory.SECURITY

    def test_failed_scan_with_blocked_files(self) -> None:
        result = findings_from_secret_scan(
            "proj", secret_scan_passed=False,
            blocked_files=["storageState.json", ".env"],
        )
        assert len(result) == 1
        assert "storageState.json" in result[0].description or "storageState.json" in result[0].evidence

    def test_failed_scan_status_open(self) -> None:
        result = findings_from_secret_scan("proj", secret_scan_passed=False)
        assert result[0].status == FindingStatus.OPEN

    def test_failed_scan_high_confidence(self) -> None:
        result = findings_from_secret_scan("proj", secret_scan_passed=False)
        assert result[0].confidence == Confidence.HIGH

    def test_failed_scan_id_contains_project_id(self) -> None:
        result = findings_from_secret_scan("myproj", secret_scan_passed=False)
        assert "MYPROJ" in result[0].id

    def test_passed_scan_none_blocked_files(self) -> None:
        result = findings_from_secret_scan("proj", secret_scan_passed=True, blocked_files=None)
        assert result == []

    def test_failed_scan_source_module_delivery(self) -> None:
        result = findings_from_secret_scan("proj", secret_scan_passed=False)
        assert result[0].source_module == "client_delivery_pack"


# ---------------------------------------------------------------------------
# TestAdapterToRiskMatrixIntegration
# ---------------------------------------------------------------------------

class TestAdapterToRiskMatrixIntegration:
    def test_api_contract_findings_in_matrix(self) -> None:
        findings = findings_from_api_contract(
            project_id="integ", source_file="spec.json",
            blocked_count=1, requires_approval_count=2, parse_errors=["e1"],
        )
        rm = RiskMatrix(findings)
        s = rm.summary()
        assert s["total"] == 3
        assert s["has_high"] is True

    def test_secret_scan_critical_in_matrix(self) -> None:
        findings = findings_from_secret_scan("integ", secret_scan_passed=False)
        rm = RiskMatrix(findings)
        s = rm.summary()
        assert s["has_critical"] is True

    def test_no_issues_empty_matrix(self) -> None:
        findings_api = findings_from_api_contract(
            project_id="p", source_file="s.json",
            blocked_count=0, requires_approval_count=0, parse_errors=[],
        )
        findings_scan = findings_from_secret_scan("p", secret_scan_passed=True)
        all_f = findings_api + findings_scan
        rm = RiskMatrix(all_f)
        assert rm.summary()["total"] == 0

    def test_combined_findings_sorted_by_risk(self) -> None:
        findings_api = findings_from_api_contract(
            project_id="p", source_file="s.json",
            blocked_count=1, requires_approval_count=0, parse_errors=[],
        )
        findings_scan = findings_from_secret_scan("p", secret_scan_passed=False)
        rm = RiskMatrix(findings_api + findings_scan)
        ordered = rm.sorted_by_risk()
        assert ordered[0].severity == Severity.CRITICAL

    def test_summary_by_severity_has_all_keys(self) -> None:
        findings = findings_from_api_contract(
            project_id="p", source_file="s.json",
            blocked_count=1, requires_approval_count=0, parse_errors=[],
        )
        rm = RiskMatrix(findings)
        by_sev = rm.summary()["by_severity"]
        assert set(by_sev.keys()) == {"critical", "high", "medium", "low", "info"}


# ---------------------------------------------------------------------------
# TestClientAuditResultStructuredFields
# ---------------------------------------------------------------------------

class TestClientAuditResultStructuredFields:
    def test_structured_findings_default_empty(self) -> None:
        r = ClientAuditResult(project_id="p", mode="safe_audit", status="ok")
        assert r.structured_findings == []

    def test_total_findings_default_zero(self) -> None:
        r = ClientAuditResult(project_id="p", mode="safe_audit", status="ok")
        assert r.total_findings == 0

    def test_findings_by_severity_default_empty_dict(self) -> None:
        r = ClientAuditResult(project_id="p", mode="safe_audit", status="ok")
        assert r.findings_by_severity == {}

    def test_findings_by_category_default_empty_dict(self) -> None:
        r = ClientAuditResult(project_id="p", mode="safe_audit", status="ok")
        assert r.findings_by_category == {}

    def test_top_risks_default_empty_list(self) -> None:
        r = ClientAuditResult(project_id="p", mode="safe_audit", status="ok")
        assert r.top_risks == []

    def test_risk_summary_default_empty_dict(self) -> None:
        r = ClientAuditResult(project_id="p", mode="safe_audit", status="ok")
        assert r.risk_summary == {}

    def test_safety_invariants_enforced(self) -> None:
        r = ClientAuditResult(
            project_id="p", mode="safe_audit", status="ok",
            raw_secrets_allowed=True,
            destructive_actions_allowed=True,
            production_write_allowed=True,
            auto_send_allowed=True,
            client_delivery_auto_approved=True,
            human_review_required=False,
            approved_for_client_delivery=True,
        )
        assert r.raw_secrets_allowed is False
        assert r.destructive_actions_allowed is False
        assert r.production_write_allowed is False
        assert r.auto_send_allowed is False
        assert r.client_delivery_auto_approved is False
        assert r.human_review_required is True
        assert r.approved_for_client_delivery is False

    def test_structured_findings_accepts_finding_list(self) -> None:
        f = _make_finding("F-001")
        r = ClientAuditResult(
            project_id="p", mode="safe_audit", status="ok",
            structured_findings=[f],
            total_findings=1,
        )
        assert len(r.structured_findings) == 1
        assert r.structured_findings[0].id == "F-001"


# ---------------------------------------------------------------------------
# TestModuleResultFindingsField
# ---------------------------------------------------------------------------

class TestModuleResultFindingsField:
    def test_findings_default_empty_list(self) -> None:
        mr = ModuleResult(name="test", status="ok")
        assert mr.findings == []

    def test_findings_accepts_finding_objects(self) -> None:
        f = _make_finding("MR-001")
        mr = ModuleResult(name="test", status="ok", findings=[f])
        assert len(mr.findings) == 1
        assert mr.findings[0].id == "MR-001"
