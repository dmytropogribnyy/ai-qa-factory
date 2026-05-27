"""Phase 5P — Client Delivery Pack.

Aggregates outputs from previous phases, generates a client-ready report package,
runs a secret scan, and creates a ZIP archive.

Safety rules:
- approved_for_client_delivery=False — never auto-approved
- human_review_required=True — always required
- auto_send_to_client=False — never sends automatically
- secret_scan_before_delivery=True — always scans before ZIP creation
- Excludes storageState, .env, credentials, cookies, tokens from ZIP
"""
from __future__ import annotations

import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from core.schemas.client_delivery import (
    ClientDeliveryManifest,
    DeliveryArtifact,
    SecretScanResult,
)

APP_VERSION = "5.8.0"

BLOCKED_DELIVERY_FILENAME_PATTERNS = (
    "storagestate",
    ".env",
    "credential",
    "authsession",
    "cookie",
    "token",
    "password",
    "api_key",
    "secret",
    "session",
)


# ---------------------------------------------------------------------------
# Secret scanner
# ---------------------------------------------------------------------------

class SecretScanner:
    """Scan a directory for files that should not be in client delivery."""

    def scan(self, directory: Path) -> SecretScanResult:
        blocked: List[str] = []
        scanned = 0
        for f in sorted(directory.rglob("*")):
            if not f.is_file():
                continue
            scanned += 1
            name_lower = f.name.lower()
            for fragment in BLOCKED_DELIVERY_FILENAME_PATTERNS:
                if fragment in name_lower:
                    blocked.append(f.name)
                    break
        return SecretScanResult(scanned_files=scanned, blocked_files=blocked)


# ---------------------------------------------------------------------------
# HTML generator (no external dependencies)
# ---------------------------------------------------------------------------

def _inline_md(text: str) -> str:
    text = re.sub(r'\*\*(.+?)\*\*', r'<strong>\1</strong>', text)
    text = re.sub(r'`([^`]+)`', r'<code>\1</code>', text)
    return text


def _md_to_html(md_content: str, title: str) -> str:
    lines = md_content.split('\n')
    html_lines: List[str] = []
    in_ul = False

    for line in lines:
        stripped = line.strip()
        if stripped == '---':
            if in_ul:
                html_lines.append('</ul>')
                in_ul = False
            html_lines.append('<hr>')
        elif line.startswith('#### '):
            if in_ul:
                html_lines.append('</ul>')
                in_ul = False
            html_lines.append(f'<h4>{_inline_md(line[5:])}</h4>')
        elif line.startswith('### '):
            if in_ul:
                html_lines.append('</ul>')
                in_ul = False
            html_lines.append(f'<h3>{_inline_md(line[4:])}</h3>')
        elif line.startswith('## '):
            if in_ul:
                html_lines.append('</ul>')
                in_ul = False
            html_lines.append(f'<h2>{_inline_md(line[3:])}</h2>')
        elif line.startswith('# '):
            if in_ul:
                html_lines.append('</ul>')
                in_ul = False
            html_lines.append(f'<h1>{_inline_md(line[2:])}</h1>')
        elif stripped.startswith('- ') or stripped.startswith('* '):
            if not in_ul:
                html_lines.append('<ul>')
                in_ul = True
            html_lines.append(f'  <li>{_inline_md(stripped[2:])}</li>')
        elif stripped == '':
            if in_ul:
                html_lines.append('</ul>')
                in_ul = False
            html_lines.append('')
        else:
            if in_ul:
                html_lines.append('</ul>')
                in_ul = False
            html_lines.append(f'<p>{_inline_md(stripped)}</p>')

    if in_ul:
        html_lines.append('</ul>')

    body = '\n'.join(html_lines)
    return (
        '<!DOCTYPE html>\n<html lang="en">\n<head>\n'
        f'<meta charset="UTF-8">\n<title>{title}</title>\n'
        '<style>\n'
        'body{font-family:Arial,sans-serif;max-width:900px;margin:40px auto;'
        'padding:0 24px;color:#222;line-height:1.65}\n'
        'h1{border-bottom:2px solid #333;padding-bottom:6px}\n'
        'h2{margin-top:28px;color:#1a1a2e}\nh3{color:#16213e}\n'
        'code{background:#f5f5f5;padding:1px 5px;border-radius:3px;font-size:.9em}\n'
        'hr{border:none;border-top:1px solid #ccc;margin:20px 0}\n'
        '.notice{background:#fff8e1;border-left:4px solid #f9a825;'
        'padding:10px 16px;margin-bottom:20px;font-size:.95em}\n'
        'ul{padding-left:24px}li{margin:3px 0}\n'
        '</style>\n</head>\n<body>\n'
        '<div class="notice">DRAFT - Pending human review. '
        'Not approved for client delivery.</div>\n'
        f'{body}\n</body>\n</html>'
    )


# ---------------------------------------------------------------------------
# Source data collector
# ---------------------------------------------------------------------------

def _collect_source_data(project_id: str, outputs_root: Path) -> dict:
    project_dir = outputs_root / project_id
    data: dict = {
        "project_id": project_id,
        "project_dir_exists": project_dir.exists(),
        "has_qa_report": False,
        "has_api_contract": False,
        "has_generated_tests": False,
        "has_cicd": False,
        "api_endpoints": 0,
        "safe_endpoints": 0,
        "approval_endpoints": 0,
        "blocked_endpoints": 0,
        "api_spec_title": "",
        "api_base_url": "",
        "cicd_platform": "",
        "generated_test_files": [],
        "qa_summary_excerpt": "",
        # Phase 5N
        "has_accessibility": False,
        "a11y_status": "planning_only",
        "a11y_checks_planned": 0,
        "has_performance": False,
        "perf_status": "planning_only",
        "perf_endpoints": 0,
        "has_passive_security": False,
        "sec_status": "planning_only",
        "sec_total_checked": 0,
        "sec_missing_headers": 0,
        # Phase 5O
        "has_flaky_analysis": False,
        "flaky_total_risks": 0,
        "flaky_weak_selectors": 0,
        "flaky_proposals": 0,
        "flaky_stability_score": 0.0,
    }

    if not project_dir.exists():
        return data

    qa_dir = project_dir / "14_qa_report"
    if qa_dir.exists():
        data["has_qa_report"] = True
        for f in qa_dir.glob("*.md"):
            try:
                data["qa_summary_excerpt"] = f.read_text(encoding="utf-8")[:800]
                break
            except OSError:
                pass

    api_dir = project_dir / "25_api_contract"
    if api_dir.exists():
        data["has_api_contract"] = True
        for f in api_dir.glob("*.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                data["api_endpoints"] = d.get("total_endpoints", 0)
                data["safe_endpoints"] = d.get("safe_readonly_count", 0)
                data["approval_endpoints"] = d.get("requires_approval_count", 0)
                data["blocked_endpoints"] = d.get("blocked_count", 0)
                data["api_spec_title"] = d.get("spec_title", "")
                data["api_base_url"] = d.get("base_url", "")
                break
            except (OSError, json.JSONDecodeError):
                pass

    tests_dir = project_dir / "26_generated_tests"
    if tests_dir.exists():
        data["has_generated_tests"] = True
        data["generated_test_files"] = [f.name for f in tests_dir.glob("*.ts")]

    cicd_dir = project_dir / "27_cicd"
    if cicd_dir.exists():
        data["has_cicd"] = True
        for f in cicd_dir.glob("*.yml"):
            if "github" in f.name.lower():
                data["cicd_platform"] = "GitHub Actions"
            elif "gitlab" in f.name.lower():
                data["cicd_platform"] = "GitLab CI"

    # Phase 5N — Accessibility
    a11y_dir = project_dir / "29_accessibility"
    if a11y_dir.exists():
        data["has_accessibility"] = True
        for f in a11y_dir.glob("accessibility_report.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                data["a11y_status"] = d.get("status", "planning_only")
                data["a11y_checks_planned"] = len(d.get("checks_planned", []))
                break
            except (OSError, json.JSONDecodeError):
                pass

    # Phase 5N — Performance
    perf_dir = project_dir / "30_performance"
    if perf_dir.exists():
        data["has_performance"] = True
        for f in perf_dir.glob("performance_report.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                data["perf_status"] = d.get("status", "planning_only")
                data["perf_endpoints"] = len(d.get("endpoints_to_measure", []))
                break
            except (OSError, json.JSONDecodeError):
                pass

    # Phase 5N — Passive Security
    sec_dir = project_dir / "31_passive_security"
    if sec_dir.exists():
        data["has_passive_security"] = True
        for f in sec_dir.glob("passive_security_report.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                data["sec_status"] = d.get("status", "planning_only")
                data["sec_total_checked"] = d.get("total_headers_checked", 0)
                data["sec_missing_headers"] = d.get("missing_headers", 0)
                break
            except (OSError, json.JSONDecodeError):
                pass

    # Phase 5O — Flaky Test Analyzer
    flaky_dir = project_dir / "32_flaky_test_analyzer"
    if flaky_dir.exists():
        data["has_flaky_analysis"] = True
        for f in flaky_dir.glob("flaky_test_analysis.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                data["flaky_total_risks"] = d.get("total_risks", 0)
                break
            except (OSError, json.JSONDecodeError):
                pass
        for f in flaky_dir.glob("selector_stability.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                data["flaky_weak_selectors"] = d.get("weak_count", 0)
                data["flaky_stability_score"] = d.get("stability_score", 0.0)
                break
            except (OSError, json.JSONDecodeError):
                pass
        for f in flaky_dir.glob("self_healing_proposals.json"):
            try:
                d = json.loads(f.read_text(encoding="utf-8"))
                data["flaky_proposals"] = d.get("total_proposals", 0)
                break
            except (OSError, json.JSONDecodeError):
                pass

    return data


# ---------------------------------------------------------------------------
# Content generators
# ---------------------------------------------------------------------------

def _generate_qa_report(project_id: str, data: dict, generated_at: str) -> str:
    sources = []
    if data["has_qa_report"]:
        sources.append("QA evidence report")
    if data["has_api_contract"]:
        ep = data["api_endpoints"]
        safe = data["safe_endpoints"]
        sources.append(f"API contract ({ep} endpoints, {safe} safe_readonly)")
    if data["has_generated_tests"]:
        sources.append("generated Playwright test stubs")
    if data["has_cicd"]:
        platform = data["cicd_platform"] or "CI/CD"
        sources.append(f"{platform} workflow config")

    sources_str = (
        "\n".join(f"- {s}" for s in sources)
        if sources
        else "- No prior phase outputs found"
    )
    test_files_str = (
        "\n".join(f"- `{f}`" for f in data["generated_test_files"])
        if data["generated_test_files"]
        else "- No generated test files found"
    )

    # Dynamic results table
    ep = data["api_endpoints"]
    safe = data["safe_endpoints"]
    approval = data["approval_endpoints"]
    blocked = data["blocked_endpoints"]
    if ep > 0:
        api_row = f"| API contract | {ep} endpoints | {safe} safe, {approval} approval-required, {blocked} blocked |"
    else:
        api_row = "| API contract | Planning artifact | Endpoints classified |"

    # Phase 5N rows — distinguish executed vs planning_only per GPT guidance
    _status_label = {
        "executed": "Executed",
        "partial": "Partial execution",
        "planning_only": "Generated checks only; execution requires approval",
    }

    if data["has_accessibility"]:
        a11y_label = _status_label.get(data["a11y_status"], "Generated checks only; execution requires approval")
        a11y_row = f"| Accessibility (WCAG AA) | {a11y_label} | {data['a11y_checks_planned']} checks planned |"
    else:
        a11y_row = ""

    if data["has_performance"]:
        perf_label = _status_label.get(data["perf_status"], "Generated checks only; execution requires approval")
        perf_row = f"| Performance smoke | {perf_label} | LCP<2500ms, FCP<1800ms thresholds |"
    else:
        perf_row = ""

    if data["has_passive_security"]:
        sec_label = _status_label.get(data["sec_status"], "Generated checks only; execution requires approval")
        if data["sec_status"] == "executed":
            sec_detail = f"{data['sec_total_checked']} headers checked, {data['sec_missing_headers']} missing"
        else:
            sec_detail = "OWASP headers planned"
        sec_row = f"| Passive security | {sec_label} | {sec_detail} |"
    else:
        sec_row = ""

    if data["has_flaky_analysis"]:
        flaky_row = (
            f"| Flaky test analysis | Static analysis | "
            f"{data['flaky_total_risks']} risks, "
            f"stability {data['flaky_stability_score']}/100, "
            f"{data['flaky_proposals']} proposals |"
        )
    else:
        flaky_row = ""

    phase5n_rows = "\n".join(r for r in [a11y_row, perf_row, sec_row, flaky_row] if r)

    # QA evidence excerpt
    excerpt = data["qa_summary_excerpt"]
    if excerpt:
        qa_excerpt_block = (
            "\n**From QA evidence report:**\n\n"
            + "\n".join(f"> {ln}" for ln in excerpt.splitlines()[:20])
            + "\n"
        )
    else:
        qa_excerpt_block = (
            "\nNo automated test execution evidence found. "
            "Run tests and generate QA report before delivery.\n"
        )

    # Evidence paths
    evidence_lines = []
    if data["has_qa_report"]:
        evidence_lines.append(f"- QA evidence report: `outputs/{project_id}/14_qa_report/`")
    if data["has_api_contract"]:
        title = data["api_spec_title"]
        label = f" ({title})" if title else ""
        evidence_lines.append(
            f"- API contract{label}: `outputs/{project_id}/25_api_contract/api_contract_inventory.json`"
        )
    if data["has_generated_tests"]:
        for tf in data["generated_test_files"]:
            evidence_lines.append(f"- Generated test: `outputs/{project_id}/26_generated_tests/{tf}`")
    if data["has_cicd"]:
        platform = data["cicd_platform"] or "CI/CD"
        evidence_lines.append(f"- {platform} config: `outputs/{project_id}/27_cicd/`")
    evidence_str = (
        "\n".join(evidence_lines) if evidence_lines
        else "- No evidence artifacts from previous phases"
    )

    return f"""\
# QA Report — {project_id}

**Prepared by:** AI QA Factory v{APP_VERSION}
**Generated:** {generated_at}
**Status:** Draft — pending human review
**Approved for client delivery:** No

---

## 1. Executive Summary

Automated QA analysis was performed for project `{project_id}`. The AI QA Factory
pipeline ran static analysis, API contract inspection, and test skeleton generation.
All outputs are planning artifacts and require senior QA review before client delivery.

**Key findings:**
- All generated artifacts are planning-only — no production systems were touched
- API endpoints classified by safety level before any test generation
- CI/CD configuration generated but not committed to any repository
- Human review required at every gate before execution

---

## 2. Scope Tested

**Project ID:** `{project_id}`

**Sources analyzed:**
{sources_str}

**Testing type:** Static analysis and planning artifact generation
**Execution environment:** Local, approval-gated
**Production access:** None

---

## 3. Environment / Inputs

- **Tool:** AI QA Factory v{APP_VERSION}
- **Generated:** {generated_at}
- **Execution mode:** Local, no production access
- **Network access:** Not used for test execution
- **Credentials used:** None (planning phase only)

---

## 4. What Was Automated

- API contract import and endpoint safety classification
- Playwright API smoke test skeleton generation (`safe_readonly` endpoints only)
- CI/CD pipeline configuration generation
- Client delivery package assembly with secret scan

**Not automated — requires human:**
- Actual test execution against live systems
- Credential setup for dedicated test accounts
- CI/CD deployment and repo configuration
- Client review and sign-off

---

## 5. Test Results Summary

| Category | Status | Notes |
|----------|--------|-------|
{api_row}
| Browser smoke tests | Stubs generated | Requires review before execution |
| Mobile viewport | Stubs available | Review required |
| Auth flows | Not included | Requires test account setup |
| CI/CD config | Generated | Manual copy required |
{phase5n_rows}

**Generated test files:**
{test_files_str}
{qa_excerpt_block}

---

## 6. Bugs / Suspected Issues

No automated defect detection was performed in this planning phase.
See `Bug_Report.md` for the structured defect template.

Actual defect identification requires test execution against a staging environment
and senior QA review of generated test stubs against acceptance criteria.

---

## 7. Risks & Blockers

See `Risk_Matrix.md` for the full risk breakdown.

**Top risks:**
- No dedicated test environment configured yet
- Test accounts not provisioned
- Generated tests not executed against real system

---

## 8. Evidence

See `Evidence_Index.md` for all available evidence artifacts.

**Available artifacts:**
{evidence_str}

---

## 9. Generated Test Cases

See `Test_Cases.csv` for the structured test case list.

**Test skeleton files:**
{test_files_str}

All generated test files are planning artifacts. Review before execution.

---

## 10. Automation & CI Recommendations

See `Recommendations.md` for full recommendations.

**Priority actions:**
1. Review and approve generated CI/CD configuration
2. Set up dedicated test accounts (no production credentials)
3. Execute smoke tests in staging environment first
4. Review all blocked endpoints before any API testing

---

## 11. Next Steps

1. Senior QA reviews this report and customizes all sections
2. Execute generated smoke tests in staging environment
3. Document actual defects in `Bug_Report.md`
4. Complete `Delivery_Checklist.md` before client delivery
5. Obtain sign-off before sending to client
"""


def _generate_bug_report(project_id: str, generated_at: str) -> str:
    return f"""\
# Bug Report — {project_id}

**Prepared by:** AI QA Factory v{APP_VERSION}
**Generated:** {generated_at}
**Status:** Draft — populate after test execution

---

## Summary

| Severity | Count | Status |
|----------|-------|--------|
| Critical | TBD | Not tested yet |
| High | TBD | Not tested yet |
| Medium | TBD | Not tested yet |
| Low | TBD | Not tested yet |

---

## Bug Template

**ID:** BUG-001
**Title:** [Short description]
**Severity:** Critical / High / Medium / Low
**Priority:** P1 / P2 / P3
**Status:** New / In Progress / Fixed / Closed
**Environment:** Staging

**Steps to reproduce:**
1. Step one
2. Step two
3. Expected result: [what should happen]
4. Actual result: [what actually happens]

**Evidence:** [Link to screenshot/video/trace]

---

## Suspected Issues (from static analysis)

- No automated defect detection performed in planning phase
- API endpoints classified `blocked_by_default` require careful manual testing
- See `Risk_Matrix.md` for potential risk areas requiring investigation

---

## Notes

Populate this document after test execution in staging environment.
Do not include production defects without proper authorization.
"""


def _generate_test_cases_csv(project_id: str, data: dict) -> str:
    rows = [
        "ID,Title,Type,Status,Priority,Notes",
        f'TC-001,"Homepage loads ({project_id})",Smoke,Review Required,P1,Browser smoke stub',
        'TC-002,"API health endpoint returns 200",API Smoke,Review Required,P1,Requires test env',
        'TC-003,"Safe API endpoints respond with valid schema",API Schema,Review Required,P2,safe_readonly only',
        'TC-004,"Mobile viewport renders correctly",Mobile,Review Required,P2,Emulation mode',
        'TC-005,"Auth flow completes (test account)",Auth,Not Implemented,P2,Needs test account',
        'TC-006,"POST endpoints require approval before test",API Classification,Automated,P1,Classifier gate',
        'TC-007,"DELETE endpoints always blocked",API Classification,Automated,P1,Hardcoded block',
        'TC-008,"CI/CD workflow contains no hardcoded secrets",CI/CD Security,Automated,P1,Content scan',
        'TC-009,"Generated report contains no credentials",Delivery Security,Automated,P1,Secret scan',
        'TC-010,"ZIP package excludes storageState files",Delivery Security,Automated,P1,Pre-zip scan',
    ]
    if data.get("has_api_contract") and data.get("api_endpoints"):
        rows.append(
            f'TC-011,"API contract: {data["api_endpoints"]} endpoints classified",'
            'API Contract,Automated,P1,Classification report'
        )
    return "\n".join(rows)


def _generate_risk_matrix(project_id: str, generated_at: str) -> str:
    return f"""\
# Risk Matrix — {project_id}

**Generated:** {generated_at}
**Review required:** Yes — populate with project-specific risks

---

| ID | Risk | Severity | Likelihood | Status | Mitigation |
|----|------|----------|------------|--------|------------|
| R-001 | Test credentials exposed | High | Low | Mitigated | No credentials stored; env vars only |
| R-002 | Production data modified | Critical | Low | Blocked | All production writes blocked by default |
| R-003 | CAPTCHA blocking automated tests | Medium | Medium | Known | CAPTCHA bypass always blocked |
| R-004 | Flaky tests due to network conditions | Medium | Medium | Monitor | Retry logic in CI config |
| R-005 | Missing test coverage for edge cases | Medium | High | Review | Senior QA sign-off required |
| R-006 | Generated tests executed without review | High | Low | Blocked | executable_without_approval=False |
| R-007 | CI/CD config committed without review | Medium | Low | Blocked | client_repo_writeback_allowed=False |
| R-008 | Secrets in delivery package | High | Low | Mitigated | Secret scan before packaging |

---

## Open Risks

- Populate this section after project-specific risk assessment
- Assign owners and resolution dates before client delivery
"""


def _generate_recommendations(project_id: str, data: dict, generated_at: str) -> str:
    platform = data.get("cicd_platform", "GitHub Actions") or "GitHub Actions"
    return f"""\
# Automation & CI Recommendations — {project_id}

**Generated:** {generated_at}

---

## Immediate Actions

1. **Review generated CI/CD configuration** — The {platform} workflow in `27_cicd/`
   is ready for review. Copy to your repository after approval.

2. **Set up dedicated test accounts** — Automated tests must use dedicated,
   non-production credentials managed via CI secret stores.

3. **Schedule smoke runs** — Configure CI to run on every PR and nightly on main.

4. **Review blocked API endpoints** — Endpoints classified `blocked_by_default`
   (DELETE, payment, admin, refund paths) require manual review before any testing.

---

## Test Coverage Recommendations

- API smoke tests cover `safe_readonly` endpoints only
- POST/PUT/PATCH endpoints require explicit approval per test cycle
- Browser smoke tests cover public read-only flows only
- Mobile viewport tests use emulation — validate on real devices before release

---

## CI/CD Setup Steps

1. Copy the generated workflow to `.github/workflows/` (or equivalent)
2. Ensure `npm ci` and Playwright install steps are present
3. Set `BASE_URL` secret in your CI secret store (never hardcode)
4. Run pipeline manually first and verify artifact uploads
5. Review test results before merging

---

## Long-Term Recommendations

- Add accessibility checks (axe-core) — Phase 5N candidate
- Add performance budget assertions (LCP < 2.5s) — Phase 5N candidate
- Implement visual regression baseline on first stable run
- Set up notifications for test failures
- Implement self-healing selectors — Phase 5O candidate

---

## Security Recommendations

- All API credentials via CI secret store only — never hardcode
- Rotate test account credentials quarterly
- Review storageState files — never commit to repository
- Scan all delivery artifacts for secrets before every client send
"""


def _generate_evidence_index(project_id: str, data: dict, generated_at: str) -> str:
    entries: List[str] = []
    if data["has_qa_report"]:
        entries.append(f"- **QA Evidence Report:** `outputs/{project_id}/14_qa_report/`")
    if data["has_api_contract"]:
        entries.append(
            f"- **API Contract Report:** `outputs/{project_id}/25_api_contract/api_contract_inventory.json`"
        )
    if data["has_generated_tests"]:
        for tf in data["generated_test_files"]:
            entries.append(f"- **Generated Test:** `outputs/{project_id}/26_generated_tests/{tf}`")
    if data["has_cicd"]:
        entries.append(f"- **CI/CD Config:** `outputs/{project_id}/27_cicd/`")
    if data["has_accessibility"]:
        a11y_note = (
            f"(status: {data['a11y_status']})"
            if data.get("a11y_status") != "planning_only"
            else "(generated checks only; execution requires approval)"
        )
        entries.append(
            f"- **Accessibility Report** {a11y_note}: `outputs/{project_id}/29_accessibility/`"
        )
    if data["has_performance"]:
        perf_note = (
            f"(status: {data['perf_status']})"
            if data.get("perf_status") != "planning_only"
            else "(generated checks only; execution requires approval)"
        )
        entries.append(
            f"- **Performance Smoke Report** {perf_note}: `outputs/{project_id}/30_performance/`"
        )
    if data["has_passive_security"]:
        sec_note = (
            f"(status: {data['sec_status']}, {data['sec_missing_headers']} headers missing)"
            if data.get("sec_status") == "executed"
            else "(generated checks only; execution requires approval)"
        )
        entries.append(
            f"- **Passive Security Report** {sec_note}: `outputs/{project_id}/31_passive_security/`"
        )
    if data["has_flaky_analysis"]:
        flaky_note = (
            f"({data['flaky_total_risks']} risks, "
            f"selector stability {data['flaky_stability_score']}/100, "
            f"{data['flaky_proposals']} proposals)"
        )
        entries.append(
            f"- **Flaky Test Analysis** {flaky_note}: `outputs/{project_id}/32_flaky_test_analyzer/`"
        )
    if not entries:
        entries.append("- No evidence artifacts from previous phases found")
        entries.append("- Run earlier pipeline phases to generate evidence")

    entries_str = "\n".join(entries)
    return f"""\
# Evidence Index — {project_id}

**Generated:** {generated_at}

---

## Available Artifacts

{entries_str}

---

## Evidence Collection Notes

- Screenshots and videos are collected on test failure only (retain-on-failure)
- Traces retained on failure for debugging purposes
- No raw credentials or auth tokens included in evidence
- All evidence files must be reviewed before inclusion in client delivery

---

## Evidence Checklist

- [ ] Screenshots reviewed — no sensitive data visible
- [ ] Videos reviewed — no credential entry recorded
- [ ] Traces reviewed — no tokens or cookies exposed
- [ ] Log files scanned for secrets
- [ ] Evidence linked to specific test cases in `Test_Cases.csv`
"""


def _generate_delivery_checklist(project_id: str, generated_at: str) -> str:
    return f"""\
# Delivery Checklist — {project_id}

**Generated:** {generated_at}
**Status:** Not approved — complete all items before client delivery

---

## Review

- [ ] Senior QA has reviewed `QA_Report.md`
- [ ] `Bug_Report.md` reviewed and all issues triaged
- [ ] `Test_Cases.csv` validated against actual test execution results
- [ ] `Risk_Matrix.md` reviewed and all risks addressed or accepted
- [ ] `Recommendations.md` reviewed for accuracy and relevance

## Security

- [ ] No credentials in any delivery artifact
- [ ] `storageState` files excluded from package
- [ ] `.env` files excluded from package
- [ ] No API keys in CI/CD configuration
- [ ] Evidence files reviewed for sensitive data
- [ ] Secret scan passed (check `client_delivery_manifest.json`)

## Content

- [ ] Executive Summary customized for this client
- [ ] Client name and project name correct throughout
- [ ] All links in `Evidence_Index.md` are valid
- [ ] Screenshots/videos reviewed before inclusion
- [ ] All placeholder sections replaced with real findings

## Sign-off

- [ ] QA Lead sign-off obtained
- [ ] Legal/compliance check completed (if required)
- [ ] Delivery method agreed with client
- [ ] Final ZIP package verified and tested

---

**Important:** `approved_for_client_delivery` is always `false` by default.
Completing this checklist does not automatically approve the package.
Manual sign-off is always required.
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class ClientDeliveryPack:
    """Aggregate phase outputs and generate a client-ready delivery package."""

    def __init__(self, outputs_root: str = "outputs") -> None:
        self.outputs_root = Path(outputs_root)

    def build(
        self,
        project_id: str,
        include_screenshots: bool = False,
        include_generated_tests: bool = True,
        include_cicd: bool = True,
        write: bool = True,
        output_dir: Optional[str] = None,
    ) -> ClientDeliveryManifest:
        """Build the client delivery pack for *project_id*.

        Args:
            project_id: Project identifier.
            include_screenshots: Include screenshot references in report.
            include_generated_tests: Include generated test file references.
            include_cicd: Include CI/CD config references.
            write: Write artifacts to disk. If False, returns manifest only.
            output_dir: Override output directory (default: outputs/<id>/28_client_delivery/).

        Returns:
            ClientDeliveryManifest with safety invariants always enforced.
        """
        generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        data = _collect_source_data(project_id, self.outputs_root)

        delivery_dir = (
            Path(output_dir)
            if output_dir
            else self.outputs_root / project_id / "28_client_delivery"
        )
        if write:
            delivery_dir.mkdir(parents=True, exist_ok=True)

        qa_report_md = _generate_qa_report(project_id, data, generated_at)
        qa_report_html = _md_to_html(qa_report_md, f"QA Report — {project_id}")
        bug_report_md = _generate_bug_report(project_id, generated_at)
        test_cases_csv = _generate_test_cases_csv(project_id, data)
        risk_matrix_md = _generate_risk_matrix(project_id, generated_at)
        recommendations_md = _generate_recommendations(project_id, data, generated_at)
        evidence_index_md = _generate_evidence_index(project_id, data, generated_at)
        delivery_checklist_md = _generate_delivery_checklist(project_id, generated_at)

        artifacts: List[DeliveryArtifact] = []

        def _write(filename: str, content: str, artifact_type: str) -> DeliveryArtifact:
            if write:
                fp = delivery_dir / filename
                fp.write_text(content, encoding="utf-8")
                size = fp.stat().st_size
            else:
                size = len(content.encode("utf-8"))
            return DeliveryArtifact(
                filename=filename,
                artifact_type=artifact_type,
                relative_path=f"{project_id}/28_client_delivery/{filename}",
                size_bytes=size,
            )

        artifacts.append(_write("QA_Report.md", qa_report_md, "qa_report_md"))
        artifacts.append(_write("QA_Report.html", qa_report_html, "qa_report_html"))
        artifacts.append(_write("Bug_Report.md", bug_report_md, "bug_report"))
        artifacts.append(_write("Test_Cases.csv", test_cases_csv, "test_cases_csv"))
        artifacts.append(_write("Risk_Matrix.md", risk_matrix_md, "risk_matrix"))
        artifacts.append(_write("Recommendations.md", recommendations_md, "recommendations"))
        artifacts.append(_write("Evidence_Index.md", evidence_index_md, "evidence_index"))
        artifacts.append(_write("Delivery_Checklist.md", delivery_checklist_md, "delivery_checklist"))

        # Secret scan
        scanner = SecretScanner()
        scan_result = scanner.scan(delivery_dir) if write else SecretScanResult(scanned_files=0)

        # Manifest JSON
        manifest_notes = [
            f"Generated by AI QA Factory v{APP_VERSION}",
            "Human review required before client delivery",
            f"Secret scan: {'passed' if scan_result.scan_passed else 'FAILED — review blocked files'}",
        ]
        manifest_dict: dict = {
            "project_id": project_id,
            "generated_at": generated_at,
            "total_artifacts": len(artifacts) + 2,  # +manifest +zip
            "secret_scan": scan_result.to_dict(),
            "notes": manifest_notes,
            "approved_for_client_delivery": False,
            "human_review_required": True,
            "auto_send_to_client": False,
            "secret_scan_before_delivery": True,
            "raw_secrets_included": False,
        }
        manifest_json = json.dumps(manifest_dict, indent=2)
        if write:
            (delivery_dir / "client_delivery_manifest.json").write_text(manifest_json, encoding="utf-8")

        artifacts.append(DeliveryArtifact(
            filename="client_delivery_manifest.json",
            artifact_type="manifest",
            relative_path=f"{project_id}/28_client_delivery/client_delivery_manifest.json",
            size_bytes=len(manifest_json.encode("utf-8")),
        ))

        # ZIP — exclude blocked filenames and the zip itself
        zip_filename = "client_delivery.zip"
        zip_size = 0
        if write:
            zip_path = delivery_dir / zip_filename
            blocked_in_scan = set(scan_result.blocked_files)
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in sorted(delivery_dir.iterdir()):
                    if f.is_file() and f.name != zip_filename and f.name not in blocked_in_scan:
                        zf.write(f, f.name)
            zip_size = zip_path.stat().st_size

        artifacts.append(DeliveryArtifact(
            filename=zip_filename,
            artifact_type="zip_package",
            relative_path=f"{project_id}/28_client_delivery/{zip_filename}",
            size_bytes=zip_size,
        ))

        return ClientDeliveryManifest(
            project_id=project_id,
            generated_at=generated_at,
            total_artifacts=len(artifacts),
            artifacts=artifacts,
            secret_scan=scan_result,
            notes=manifest_notes,
        )
