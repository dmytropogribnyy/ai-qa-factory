"""Phase 5N tests — Passive security runner and schema."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from core.passive_security_runner import PassiveSecurityRunner
from core.schemas.passive_security import (
    HEADER_GUIDANCE,
    OWASP_SECURITY_HEADERS,
    PassiveSecurityReport,
    SecurityHeaderCheck,
)

_MOCK_HEADERS_ALL_PRESENT = {
    "strict-transport-security": "max-age=31536000; includeSubDomains",
    "content-security-policy": "default-src 'self'",
    "x-content-type-options": "nosniff",
    "x-frame-options": "DENY",
    "referrer-policy": "strict-origin-when-cross-origin",
}

_MOCK_HEADERS_PARTIAL = {
    "x-content-type-options": "nosniff",
    "x-frame-options": "SAMEORIGIN",
}


# ---------------------------------------------------------------------------
# TestPassiveSecuritySchemas — dataclass safety invariants
# ---------------------------------------------------------------------------

class TestPassiveSecuritySchemas:
    def test_report_read_only_hardcoded(self):
        r = PassiveSecurityReport(read_only=False)
        assert r.read_only is True

    def test_report_active_scan_blocked(self):
        r = PassiveSecurityReport(active_scan_allowed=True)
        assert r.active_scan_allowed is False

    def test_report_exploit_blocked(self):
        r = PassiveSecurityReport(exploit_attempts_allowed=True)
        assert r.exploit_attempts_allowed is False

    def test_report_auth_bypass_blocked(self):
        r = PassiveSecurityReport(auth_bypass_allowed=True)
        assert r.auth_bypass_allowed is False

    def test_report_destructive_blocked(self):
        r = PassiveSecurityReport(destructive_actions_allowed=True)
        assert r.destructive_actions_allowed is False

    def test_report_human_review_required(self):
        r = PassiveSecurityReport(human_review_required=False)
        assert r.human_review_required is True

    def test_report_defaults_planning_only(self):
        assert PassiveSecurityReport().status == "planning_only"

    def test_report_headers_checked_empty_by_default(self):
        assert PassiveSecurityReport().headers_checked == []

    def test_report_headers_found_empty_by_default(self):
        assert PassiveSecurityReport().headers_found == []

    def test_report_headers_missing_empty_by_default(self):
        assert PassiveSecurityReport().headers_missing == []

    def test_report_to_dict_contains_safety_flags(self):
        d = PassiveSecurityReport().to_dict()
        assert d["read_only"] is True
        assert d["active_scan_allowed"] is False
        assert d["exploit_attempts_allowed"] is False
        assert d["auth_bypass_allowed"] is False
        assert d["destructive_actions_allowed"] is False
        assert d["human_review_required"] is True

    def test_report_from_dict_injection_blocked(self):
        d = PassiveSecurityReport().to_dict()
        d["read_only"] = False
        d["active_scan_allowed"] = True
        d["exploit_attempts_allowed"] = True
        d["auth_bypass_allowed"] = True
        d["human_review_required"] = False
        r = PassiveSecurityReport.from_dict(d)
        assert r.read_only is True
        assert r.active_scan_allowed is False
        assert r.exploit_attempts_allowed is False
        assert r.auth_bypass_allowed is False
        assert r.human_review_required is True

    def test_owasp_headers_tuple_nonempty(self):
        assert len(OWASP_SECURITY_HEADERS) >= 4

    def test_owasp_headers_contains_hsts(self):
        assert "strict-transport-security" in OWASP_SECURITY_HEADERS

    def test_owasp_headers_contains_csp(self):
        assert "content-security-policy" in OWASP_SECURITY_HEADERS

    def test_header_guidance_nonempty(self):
        assert len(HEADER_GUIDANCE) >= 4

    def test_security_header_check_defaults(self):
        c = SecurityHeaderCheck()
        assert c.present is False
        assert c.check_status == "not_checked"

    def test_security_header_check_to_dict(self):
        c = SecurityHeaderCheck(header_name="hsts", present=True, check_status="present")
        d = c.to_dict()
        assert d["header_name"] == "hsts"
        assert d["present"] is True

    def test_report_to_dict_status_present(self):
        assert "status" in PassiveSecurityReport().to_dict()


# ---------------------------------------------------------------------------
# TestPassiveSecurityRunner — generate_plan behaviour
# ---------------------------------------------------------------------------

class TestPassiveSecurityRunner:
    def test_generate_plan_returns_report(self, tmp_path):
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        assert isinstance(r.generate_plan(), PassiveSecurityReport)

    def test_generate_plan_status_planning_only(self, tmp_path):
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        assert r.generate_plan().status == "planning_only"

    def test_generate_plan_project_id_set(self, tmp_path):
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        assert r.generate_plan().project_id == "proj-sec"

    def test_generate_plan_target_url_set(self, tmp_path):
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        assert r.generate_plan().target_url == "https://example.com"

    def test_generate_plan_headers_checked_nonempty(self, tmp_path):
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        assert len(r.generate_plan().headers_checked) > 0

    def test_generate_plan_checks_all_not_checked(self, tmp_path):
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        for check in r.generate_plan().headers_checked:
            assert check.check_status == "not_checked"

    def test_generate_plan_safety_invariants(self, tmp_path):
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        report = r.generate_plan()
        assert report.read_only is True
        assert report.active_scan_allowed is False
        assert report.exploit_attempts_allowed is False
        assert report.auth_bypass_allowed is False
        assert report.human_review_required is True

    def test_generate_plan_creates_spec_file(self, tmp_path):
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        r.generate_plan()
        assert (tmp_path / "proj-sec" / "31_passive_security" / "passive_security.generated.spec.ts").exists()

    def test_generate_plan_creates_report_json(self, tmp_path):
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        r.generate_plan()
        assert (tmp_path / "proj-sec" / "31_passive_security" / "passive_security_report.json").exists()

    def test_generate_plan_creates_summary_md(self, tmp_path):
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        r.generate_plan()
        assert (tmp_path / "proj-sec" / "31_passive_security" / "passive_security_summary.md").exists()

    def test_generate_plan_creates_security_headers_json(self, tmp_path):
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        r.generate_plan()
        assert (tmp_path / "proj-sec" / "31_passive_security" / "security_headers.json").exists()

    def test_generate_plan_no_write_no_files(self, tmp_path):
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        r.generate_plan(write_files=False)
        assert not (tmp_path / "proj-sec").exists()

    def test_report_json_parseable(self, tmp_path):
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        r.generate_plan()
        d = json.loads(
            (tmp_path / "proj-sec" / "31_passive_security" / "passive_security_report.json").read_text(
                encoding="utf-8"
            )
        )
        assert d["project_id"] == "proj-sec"

    def test_report_json_safety_flags(self, tmp_path):
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        r.generate_plan()
        d = json.loads(
            (tmp_path / "proj-sec" / "31_passive_security" / "passive_security_report.json").read_text(
                encoding="utf-8"
            )
        )
        assert d["active_scan_allowed"] is False
        assert d["exploit_attempts_allowed"] is False


# ---------------------------------------------------------------------------
# TestPassiveSecuritySpecContent — generated spec quality
# ---------------------------------------------------------------------------

class TestPassiveSecuritySpecContent:
    def _spec(self, tmp_path) -> str:
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        r.generate_plan()
        return (
            tmp_path / "proj-sec" / "31_passive_security" / "passive_security.generated.spec.ts"
        ).read_text(encoding="utf-8")

    def test_spec_imports_playwright(self, tmp_path):
        assert "@playwright/test" in self._spec(tmp_path)

    def test_spec_contains_target_url(self, tmp_path):
        assert "https://example.com" in self._spec(tmp_path)

    def test_spec_has_passive_security_tag(self, tmp_path):
        assert "@passive-security" in self._spec(tmp_path)

    def test_spec_checks_hsts(self, tmp_path):
        assert "strict-transport-security" in self._spec(tmp_path)

    def test_spec_checks_csp(self, tmp_path):
        assert "content-security-policy" in self._spec(tmp_path)

    def test_spec_has_test_describe(self, tmp_path):
        assert "test.describe(" in self._spec(tmp_path)

    def test_spec_has_planning_notice(self, tmp_path):
        assert "planning_only" in self._spec(tmp_path)

    def test_spec_has_human_review_notice(self, tmp_path):
        assert "human review" in self._spec(tmp_path).lower()

    def test_summary_has_draft_notice(self, tmp_path):
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        r.generate_plan()
        content = (
            tmp_path / "proj-sec" / "31_passive_security" / "passive_security_summary.md"
        ).read_text(encoding="utf-8")
        assert "DRAFT" in content or "planning_only" in content


# ---------------------------------------------------------------------------
# TestPassiveSecurityExecution — approved path with mocked HEAD request
# ---------------------------------------------------------------------------

class TestPassiveSecurityExecution:
    def test_execute_without_approval_raises(self, tmp_path):
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        with pytest.raises(ValueError, match="approve-public-readonly"):
            r.execute(approve_public_readonly=False)

    def test_execute_approved_all_present_returns_executed(self, tmp_path):
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        with patch("core.passive_security_runner._fetch_response_headers", return_value=_MOCK_HEADERS_ALL_PRESENT):
            report = r.execute(approve_public_readonly=True)
        assert report.status == "executed"

    def test_execute_approved_all_present_no_missing(self, tmp_path):
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        with patch("core.passive_security_runner._fetch_response_headers", return_value=_MOCK_HEADERS_ALL_PRESENT):
            report = r.execute(approve_public_readonly=True)
        assert report.missing_headers == 0

    def test_execute_approved_partial_detects_missing(self, tmp_path):
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        with patch("core.passive_security_runner._fetch_response_headers", return_value=_MOCK_HEADERS_PARTIAL):
            report = r.execute(approve_public_readonly=True)
        assert report.missing_headers > 0
        assert len(report.headers_missing) > 0

    def test_execute_approved_partial_found_headers(self, tmp_path):
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        with patch("core.passive_security_runner._fetch_response_headers", return_value=_MOCK_HEADERS_PARTIAL):
            report = r.execute(approve_public_readonly=True)
        assert "x-content-type-options" in report.headers_found

    def test_execute_approved_safety_invariants_intact(self, tmp_path):
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        with patch("core.passive_security_runner._fetch_response_headers", return_value=_MOCK_HEADERS_ALL_PRESENT):
            report = r.execute(approve_public_readonly=True)
        assert report.read_only is True
        assert report.active_scan_allowed is False
        assert report.exploit_attempts_allowed is False
        assert report.auth_bypass_allowed is False
        assert report.human_review_required is True

    def test_execute_approved_creates_report_json(self, tmp_path):
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        with patch("core.passive_security_runner._fetch_response_headers", return_value=_MOCK_HEADERS_ALL_PRESENT):
            r.execute(approve_public_readonly=True)
        assert (tmp_path / "proj-sec" / "31_passive_security" / "passive_security_report.json").exists()

    def test_execute_approved_creates_headers_json(self, tmp_path):
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        with patch("core.passive_security_runner._fetch_response_headers", return_value=_MOCK_HEADERS_ALL_PRESENT):
            r.execute(approve_public_readonly=True)
        assert (tmp_path / "proj-sec" / "31_passive_security" / "security_headers.json").exists()

    def test_execute_approved_report_json_status_executed(self, tmp_path):
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        with patch("core.passive_security_runner._fetch_response_headers", return_value=_MOCK_HEADERS_ALL_PRESENT):
            r.execute(approve_public_readonly=True)
        d = json.loads(
            (tmp_path / "proj-sec" / "31_passive_security" / "passive_security_report.json").read_text(
                encoding="utf-8"
            )
        )
        assert d["status"] == "executed"

    def test_execute_approved_summary_shows_executed(self, tmp_path):
        r = PassiveSecurityRunner("proj-sec", "https://example.com", str(tmp_path))
        with patch("core.passive_security_runner._fetch_response_headers", return_value=_MOCK_HEADERS_ALL_PRESENT):
            r.execute(approve_public_readonly=True)
        content = (
            tmp_path / "proj-sec" / "31_passive_security" / "passive_security_summary.md"
        ).read_text(encoding="utf-8")
        assert "Executed" in content or "executed" in content


# ---------------------------------------------------------------------------
# TestCLIPassiveSecurity — CLI tool
# ---------------------------------------------------------------------------

_CLI = [sys.executable, "tools/run_passive_security_smoke.py"]
_CWD = str(Path(__file__).parent.parent)


class TestCLIPassiveSecurity:
    def test_no_args_exits_2(self):
        r = subprocess.run(_CLI, capture_output=True, cwd=_CWD)
        assert r.returncode == 2

    def test_help_exits_0(self):
        r = subprocess.run([*_CLI, "--help"], capture_output=True, cwd=_CWD)
        assert r.returncode == 0

    def test_blocked_flag_active_scan_exits_1(self):
        r = subprocess.run(
            [*_CLI, "--project-id", "x", "--target-url", "http://x.com", "--active-scan"],
            capture_output=True, cwd=_CWD,
        )
        assert r.returncode == 1

    def test_blocked_flag_exploit_exits_1(self):
        r = subprocess.run(
            [*_CLI, "--project-id", "x", "--target-url", "http://x.com", "--exploit"],
            capture_output=True, cwd=_CWD,
        )
        assert r.returncode == 1

    def test_blocked_flag_bypass_auth_exits_1(self):
        r = subprocess.run(
            [*_CLI, "--project-id", "x", "--target-url", "http://x.com", "--bypass-auth"],
            capture_output=True, cwd=_CWD,
        )
        assert r.returncode == 1

    def test_execute_without_approval_exits_1(self):
        r = subprocess.run(
            [*_CLI, "--project-id", "x", "--target-url", "http://x.com", "--execute", "--no-write"],
            capture_output=True, cwd=_CWD,
        )
        assert r.returncode == 1

    def test_plan_mode_exits_0(self, tmp_path):
        r = subprocess.run(
            [
                *_CLI, "--project-id", "x", "--target-url", "http://x.com",
                "--no-write", "--outputs-root", str(tmp_path),
            ],
            capture_output=True, cwd=_CWD,
        )
        assert r.returncode == 0

    def test_plan_mode_output_contains_status(self, tmp_path):
        r = subprocess.run(
            [
                *_CLI, "--project-id", "x", "--target-url", "http://x.com",
                "--no-write", "--outputs-root", str(tmp_path),
            ],
            capture_output=True, text=True, cwd=_CWD,
        )
        assert "planning_only" in r.stdout
