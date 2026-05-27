"""Phase 6.2 -- Adapter functions that convert module outputs to Finding objects.

Each adapter takes structured data from a module result and returns a list of
Finding objects. Only real evidence produces findings -- no fake findings are
generated for planning_only mode or empty data.
"""
from __future__ import annotations

from core.schemas.finding import (
    Confidence,
    Finding,
    FindingCategory,
    FindingStatus,
    Severity,
)


def findings_from_api_contract(
    project_id: str,
    source_file: str,
    blocked_count: int,
    requires_approval_count: int,
    parse_errors: list,
) -> list[Finding]:
    """Convert APIContractReport data into Finding objects.

    Only produces findings when there is actual evidence:
    - blocked_count > 0: blocked endpoints are a concrete risk
    - requires_approval_count > 0: approval-required endpoints need review
    - parse_errors: spec quality issue
    """
    findings: list[Finding] = []

    if blocked_count > 0:
        findings.append(Finding(
            id=f"API-BLOCKED-{project_id[:16].upper()}-001",
            title=f"{blocked_count} blocked API endpoint(s) detected",
            description=(
                f"{blocked_count} endpoint(s) in {source_file} have "
                "safety_classification=blocked_by_default (e.g., DELETE or dangerous write operations)."
            ),
            severity=Severity.HIGH,
            category=FindingCategory.API,
            source_module="api_contract_importer",
            affected_area=source_file,
            evidence=f"blocked_count={blocked_count}",
            recommendation=(
                "Review each blocked endpoint. Require explicit approval per the APPROVAL_MODEL "
                "before including in automated test runs. "
                "DELETE and admin-write endpoints must never be tested automatically."
            ),
            client_impact=(
                "Blocked endpoints are not covered by automated testing. "
                "Manual review and approval required before any destructive operations are tested."
            ),
            confidence=Confidence.HIGH,
            status=FindingStatus.NEEDS_REVIEW,
            tags=["api", "blocked", "destructive"],
        ))

    if requires_approval_count > 0:
        findings.append(Finding(
            id=f"API-APPROVAL-{project_id[:16].upper()}-001",
            title=f"{requires_approval_count} API endpoint(s) require explicit approval",
            description=(
                f"{requires_approval_count} endpoint(s) in {source_file} have "
                "safety_classification=requires_approval (e.g., POST, PUT operations that modify data)."
            ),
            severity=Severity.MEDIUM,
            category=FindingCategory.API,
            source_module="api_contract_importer",
            affected_area=source_file,
            evidence=f"requires_approval_count={requires_approval_count}",
            recommendation=(
                "Review and explicitly approve each endpoint via --approve flags before testing. "
                "Ensure test accounts are used and no production data is modified."
            ),
            client_impact=(
                "These endpoints are not covered in automated testing without explicit approval. "
                "Coverage gap exists until approvals are granted."
            ),
            confidence=Confidence.HIGH,
            status=FindingStatus.NEEDS_REVIEW,
            tags=["api", "requires_approval", "write_operation"],
        ))

    if parse_errors:
        findings.append(Finding(
            id=f"API-PARSE-{project_id[:16].upper()}-001",
            title="API specification contains parse errors",
            description=(
                f"{len(parse_errors)} parse error(s) detected in {source_file}. "
                "Errors may cause incomplete endpoint coverage."
            ),
            severity=Severity.LOW,
            category=FindingCategory.DOCUMENTATION,
            source_module="api_contract_importer",
            affected_area=source_file,
            evidence=str(parse_errors[:3]),
            recommendation=(
                "Fix the API specification to eliminate parse errors. "
                "Use an OpenAPI validator to verify the spec before audit."
            ),
            client_impact="Spec parse errors may result in missed endpoints in coverage analysis.",
            confidence=Confidence.HIGH,
            status=FindingStatus.OPEN,
            tags=["api", "documentation", "spec_quality"],
        ))

    return findings


def findings_from_secret_scan(
    project_id: str,
    secret_scan_passed: bool,
    blocked_files: list | None = None,
) -> list[Finding]:
    """Convert secret scan result into Finding objects.

    Only produces a finding when the scan actually fails.
    A passing scan produces no findings.
    """
    if secret_scan_passed:
        return []

    blocked = blocked_files or []
    return [
        Finding(
            id=f"DELIVERY-SCAN-{project_id[:16].upper()}-001",
            title="Secret scan failed: delivery pack contains sensitive data",
            description=(
                "The client delivery pack secret scan detected potential sensitive data. "
                f"Blocked files: {blocked[:5] if blocked else 'see delivery pack log'}."
            ),
            severity=Severity.CRITICAL,
            category=FindingCategory.SECURITY,
            source_module="client_delivery_pack",
            affected_area="28_client_delivery/",
            evidence=f"secret_scan_passed=False, blocked_files={blocked[:5]}",
            recommendation=(
                "Remove all sensitive data from delivery artifacts before sending to client. "
                "Review and exclude: storageState files, .env files, credentials, tokens."
            ),
            client_impact=(
                "CRITICAL: Sending sensitive data to clients is a security and compliance risk. "
                "Delivery must be blocked until scan passes."
            ),
            confidence=Confidence.HIGH,
            status=FindingStatus.OPEN,
            tags=["security", "secret_scan", "delivery", "critical"],
        )
    ]
