"""Phase 5N — Passive security schema.

Safety invariants (hardcoded in __post_init__):
- read_only=True
- active_scan_allowed=False
- exploit_attempts_allowed=False
- auth_bypass_allowed=False
- destructive_actions_allowed=False
- human_review_required=True
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from core.schemas.base import SchemaMixin

OWASP_SECURITY_HEADERS = (
    "strict-transport-security",
    "content-security-policy",
    "x-content-type-options",
    "x-frame-options",
    "referrer-policy",
)

HEADER_GUIDANCE = {
    "strict-transport-security": "Enforce HTTPS; max-age >= 15552000 (6 months).",
    "content-security-policy": "Define allowed sources to mitigate XSS.",
    "x-content-type-options": "Should be 'nosniff' to prevent MIME sniffing.",
    "x-frame-options": "Should be 'DENY' or 'SAMEORIGIN' to prevent clickjacking.",
    "referrer-policy": "Should be 'strict-origin-when-cross-origin' or stricter.",
}


@dataclass
class SecurityHeaderCheck(SchemaMixin):
    """Result for one OWASP security header (template — populated after execution)."""
    header_name: str = ""
    present: bool = False
    value: str = ""
    guidance: str = ""
    check_status: str = "not_checked"  # present | missing | not_checked | blocked


@dataclass
class PassiveSecurityReport(SchemaMixin):
    """Passive security smoke plan/result — read-only HTTP header inspection only."""
    project_id: str = ""
    generated_at: str = ""
    target_url: str = ""
    headers_checked: List[SecurityHeaderCheck] = field(default_factory=list)
    total_headers_checked: int = 0
    missing_headers: int = 0
    generated_test_file: str = ""
    notes: List[str] = field(default_factory=list)
    # Execution status tracking
    status: str = "planning_only"  # planning_only | executed | partial
    headers_found: List[str] = field(default_factory=list)
    headers_missing: List[str] = field(default_factory=list)
    # Safety invariants
    read_only: bool = True
    active_scan_allowed: bool = False
    exploit_attempts_allowed: bool = False
    auth_bypass_allowed: bool = False
    destructive_actions_allowed: bool = False
    human_review_required: bool = True

    def __post_init__(self) -> None:
        self.read_only = True
        self.active_scan_allowed = False
        self.exploit_attempts_allowed = False
        self.auth_bypass_allowed = False
        self.destructive_actions_allowed = False
        self.human_review_required = True
