"""Phase 6.3 -- Client-facing QA Audit Report generator.

Generates a professional, human-readable Markdown report from a
ClientAuditResult and ClientAuditPlan. Language is client-oriented:
explains what was checked, what risks were found, and what to do next.

Safety notice is always included: the report is a draft pending human
review and is never automatically approved for client delivery.

Only real evidence produces findings. If no findings were generated,
the report says so and explains what was and was not tested.
"""
from __future__ import annotations

from pathlib import Path

from core.schemas.client_audit import ClientAuditPlan, ClientAuditResult, SkippedModule
from core.schemas.finding import Finding, Severity

_SEVERITY_LABELS: dict[str, str] = {
    "critical": "Critical",
    "high": "High",
    "medium": "Medium",
    "low": "Low",
    "info": "Informational",
}

_CATEGORY_LABELS: dict[str, str] = {
    "api": "API Contract",
    "security": "Security",
    "performance": "Performance",
    "accessibility": "Accessibility",
    "functional": "Functional",
    "ux": "User Experience",
    "reliability": "Reliability",
    "maintainability": "Maintainability",
    "configuration": "Configuration",
    "documentation": "Documentation",
    "unknown": "Other",
}

_MODULE_LABELS: dict[str, str] = {
    "api_contract_importer": "API Contract Analysis",
    "accessibility_runner": "Accessibility Check",
    "performance_runner": "Performance Check",
    "passive_security_runner": "Security Header Check",
    "client_delivery_pack": "Delivery Pack Assembly",
}


def _severity_label(sev: str) -> str:
    return _SEVERITY_LABELS.get(sev, sev.upper())


def _category_label(cat: str) -> str:
    return _CATEGORY_LABELS.get(cat, cat.title())


def _module_label(mod: str) -> str:
    return _MODULE_LABELS.get(mod, mod.replace("_", " ").title())


def _human_status(module_name: str, status: str) -> str:
    if status == "analysis_only":
        return "Analyzed (read-only)"
    if status == "planning_only":
        return "Planned only (no execution)"
    if status == "executed":
        return "Executed"
    if status == "draft":
        return "Completed (draft artifacts)"
    if status == "failed":
        return "Failed"
    if status == "skipped":
        return "Skipped"
    return status.replace("_", " ").title()


def _finding_severity_sentence(f: Finding) -> str:
    sev = f.severity.value
    cat = _category_label(f.category.value)
    if sev == "critical":
        return f"A critical {cat.lower()} risk was identified that requires immediate attention."
    if sev == "high":
        return f"A high-severity {cat.lower()} risk was identified and should be reviewed before release."
    if sev == "medium":
        return f"A medium-severity {cat.lower()} issue was identified and should be addressed in an upcoming iteration."
    if sev == "low":
        return f"A low-severity {cat.lower()} observation was recorded for improvement consideration."
    return f"An informational {cat.lower()} note was recorded."


def _render_finding(f: Finding, index: int) -> list[str]:
    lines: list[str] = []
    sev_label = _severity_label(f.severity.value)
    cat_label = _category_label(f.category.value)
    conf_label = f.confidence.value.title()
    lines.append(f"### Finding {index}: {f.title}")
    lines.append("")
    lines.append(_finding_severity_sentence(f))
    lines.append("")
    lines.append("| Field | Value |")
    lines.append("|---|---|")
    lines.append(f"| Severity | {sev_label} |")
    lines.append(f"| Category | {cat_label} |")
    if f.affected_area:
        lines.append(f"| Affected Area | {f.affected_area} |")
    lines.append(f"| Confidence | {conf_label} |")
    lines.append(f"| Status | {f.status.value.replace('_', ' ').title()} |")
    lines.append(f"| Source | {_module_label(f.source_module)} |")
    lines.append("")
    if f.client_impact:
        lines.append(f"**Client Impact:** {f.client_impact}")
        lines.append("")
    if f.evidence:
        lines.append(f"**Evidence:** {f.evidence}")
        lines.append("")
    if f.recommendation:
        lines.append(f"**Recommendation:** {f.recommendation}")
        lines.append("")
    return lines


def _recommended_actions(findings: list[Finding]) -> list[str]:
    lines: list[str] = []
    by_sev: dict[str, list[Finding]] = {s.value: [] for s in Severity}
    for f in findings:
        by_sev[f.severity.value].append(f)

    if by_sev["critical"]:
        lines.append(
            "**Immediate action required:** Address all Critical findings before any release or deployment. "
            "These risks have the highest potential for impact and must be resolved or accepted with explicit sign-off."
        )
    if by_sev["high"]:
        lines.append(
            "**Plan for next sprint:** High-severity findings should be assigned to the development team "
            "and tracked as priority items. Delay release if not addressed."
        )
    if by_sev["medium"]:
        lines.append(
            "**Schedule for upcoming iterations:** Medium-severity issues are not release-blockers, "
            "but should be addressed within 1-2 sprints to reduce ongoing risk."
        )
    if by_sev["low"] or by_sev["info"]:
        lines.append(
            "**Backlog / improvement:** Low and informational findings can be added to the product backlog. "
            "Consider addressing them during regular technical debt reduction cycles."
        )
    if not findings:
        lines.append(
            "No findings were generated by the executed modules. "
            "To increase audit coverage, consider: providing an API spec file, "
            "enabling browser execution (--approve-browser-execution), "
            "or providing a target URL for security checks."
        )
    return lines


def generate_client_delivery_report(
    result: ClientAuditResult,
    plan: ClientAuditPlan,
) -> str:
    """Generate a client-facing Markdown report string.

    Returns a complete Markdown document ready to write to client_report.md.
    Does not write any files itself -- the caller handles I/O.
    """
    lines: list[str] = []
    project_id = result.project_id

    # ------------------------------------------------------------------
    # Header + safety notice
    # ------------------------------------------------------------------
    lines += [
        "# QA Audit Report",
        "",
        f"**Project:** {project_id}",
        f"**Audit Mode:** {result.mode.replace('_', ' ').title()}",
        f"**Status:** {result.status.replace('_', ' ').title()}",
        "",
        "> **DRAFT -- PENDING HUMAN REVIEW**",
        "> This report was generated automatically and has not been approved for external distribution.",
        "> A qualified QA engineer must review and sign off on this report before sharing with a client.",
        "> `approved_for_client_delivery = False`",
        "",
        "---",
        "",
    ]

    # ------------------------------------------------------------------
    # 1. Executive Summary
    # ------------------------------------------------------------------
    lines += ["## 1. Executive Summary", ""]
    n_exec = result.modules_executed
    n_plan = result.modules_planning_only
    n_findings = result.total_findings
    blocked = result.blocked_risky_actions

    if n_findings == 0:
        exec_summary = (
            f"The audit for **{project_id}** completed with {n_exec + n_plan} module(s) run. "
            "No findings were generated by the executed modules. "
            "This may indicate a clean audit scope, or that additional approvals are needed "
            "to enable deeper checks."
        )
    elif n_findings == 1:
        exec_summary = (
            f"The audit for **{project_id}** completed with {n_exec + n_plan} module(s) run "
            f"and identified **1 finding** that requires attention."
        )
    else:
        rs = result.risk_summary
        has_critical = rs.get("has_critical", False)
        has_high = rs.get("has_high", False)
        risk_level = "critical risks" if has_critical else ("high-severity risks" if has_high else "risks")
        exec_summary = (
            f"The audit for **{project_id}** completed with {n_exec + n_plan} module(s) run "
            f"and identified **{n_findings} finding(s)**, including {risk_level}. "
            "See the Risk Matrix and Findings sections for details."
        )

    lines += [exec_summary, ""]

    if blocked > 0:
        lines += [
            f"**{blocked} risky action(s) were blocked** during this audit run. "
            "These include destructive operations, production writes, and credential handling. "
            "No blocked actions were executed.",
            "",
        ]

    lines += ["---", ""]

    # ------------------------------------------------------------------
    # 2. Audit Scope
    # ------------------------------------------------------------------
    lines += ["## 2. Audit Scope", ""]
    lines += [
        "| Field | Value |",
        "|---|---|",
        f"| Project ID | {project_id} |",
        f"| Mode | {result.mode} |",
        f"| Modules Executed | {n_exec} |",
        f"| Modules Planning-Only | {n_plan} |",
        f"| Total Findings | {n_findings} |",
        f"| Blocked Risky Actions | {blocked} |",
        "",
    ]
    lines += ["---", ""]

    # ------------------------------------------------------------------
    # 3. Inputs Provided
    # ------------------------------------------------------------------
    lines += ["## 3. Inputs Provided", ""]
    detected = plan.detected_inputs
    input_rows = [
        ("Target URL", "target_url"),
        ("API Spec File", "spec_file"),
        ("Postman Collection", "postman_collection"),
        ("Task Source Report", "task_source_report"),
        ("Scaffold Root", "scaffold_root"),
        ("Browser Execution Approved", "approve_browser"),
        ("Public Readonly Approved", "approve_public_readonly"),
    ]
    for label, key in input_rows:
        val = detected.get(key, False)
        status_str = "Provided" if val else "Not provided"
        lines.append(f"- **{label}:** {status_str}")
    lines += ["", "---", ""]

    # ------------------------------------------------------------------
    # 4. Modules Executed
    # ------------------------------------------------------------------
    lines += ["## 4. Modules Executed", ""]
    if result.module_results:
        lines.append("| Module | Status | Notes |")
        lines.append("|---|---|---|")
        for mr in result.module_results:
            human_mod = _module_label(mr.name)
            human_status = _human_status(mr.name, mr.status)
            note = mr.note or "-"
            lines.append(f"| {human_mod} | {human_status} | {note} |")
    else:
        lines.append("No modules were executed in this run.")
    lines += ["", "---", ""]

    # ------------------------------------------------------------------
    # 5. Modules Skipped
    # ------------------------------------------------------------------
    lines += ["## 5. Modules Not Executed", ""]
    skipped: list[SkippedModule] = plan.skipped_modules
    if skipped:
        lines.append("The following modules were not executed in this audit run:")
        lines.append("")
        for s in skipped:
            human_mod = _module_label(s.name)
            lines.append(f"- **{human_mod}:** {s.reason}")
    else:
        lines.append("All planned modules were executed.")
    lines += ["", "---", ""]

    # ------------------------------------------------------------------
    # 6. Risk Matrix
    # ------------------------------------------------------------------
    lines += ["## 6. Risk Matrix", ""]
    lines.append(f"**Total findings:** {n_findings}")
    lines.append("")

    by_sev = result.findings_by_severity
    if by_sev and any(c > 0 for c in by_sev.values()):
        lines.append("| Severity | Count |")
        lines.append("|---|---|")
        for sev_key in ("critical", "high", "medium", "low", "info"):
            count = by_sev.get(sev_key, 0)
            if count > 0:
                lines.append(f"| {_severity_label(sev_key)} | {count} |")
        lines.append("")

    by_cat = result.findings_by_category
    if by_cat:
        lines.append("| Category | Count |")
        lines.append("|---|---|")
        for cat_key, count in sorted(by_cat.items(), key=lambda x: -x[1]):
            if count > 0:
                lines.append(f"| {_category_label(cat_key)} | {count} |")
        lines.append("")

    top = result.top_risks
    if top:
        lines.append("**Top risks by priority:**")
        lines.append("")
        for i, risk in enumerate(top[:5], 1):
            sev = _severity_label(risk.get("severity", ""))
            title = risk.get("title", "")
            lines.append(f"{i}. [{sev}] {title}")
        lines.append("")

    lines += ["---", ""]

    # ------------------------------------------------------------------
    # 7. Key Findings
    # ------------------------------------------------------------------
    lines += ["## 7. Key Findings", ""]
    findings = result.structured_findings
    if not findings:
        lines += [
            "No findings were produced by the executed modules. "
            "This may be because:",
            "",
            "- All modules ran in planning-only mode (no network or browser access)",
            "- No API spec or target URL was provided",
            "- The audited scope had no detectable issues",
            "",
            "To produce findings, provide an API spec file, enable execution approvals, "
            "or provide a target URL for security and accessibility checks.",
        ]
    else:
        # Sort by risk: critical first
        sev_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
        sorted_findings = sorted(
            findings,
            key=lambda f: (sev_order.get(f.severity.value, 5), f.id),
        )
        for i, f in enumerate(sorted_findings, 1):
            lines += _render_finding(f, i)

    lines += ["---", ""]

    # ------------------------------------------------------------------
    # 8. Evidence Summary
    # ------------------------------------------------------------------
    lines += ["## 8. Evidence Summary", ""]
    if findings:
        lines.append(
            "The following evidence was collected during the audit. "
            "All evidence was gathered through read-only, non-destructive operations."
        )
        lines.append("")
        for f in findings:
            if f.evidence:
                source = _module_label(f.source_module)
                lines.append(f"- **{f.title}** ({source}): {f.evidence}")
        lines.append("")
    else:
        lines.append(
            "No evidence-backed findings were produced. "
            "Additional audit steps with execution approval would provide richer evidence."
        )
    lines += ["", "---", ""]

    # ------------------------------------------------------------------
    # 9. Recommended Actions
    # ------------------------------------------------------------------
    lines += ["## 9. Recommended Actions", ""]
    for action in _recommended_actions(findings):
        lines.append(action)
        lines.append("")
    lines += ["---", ""]

    # ------------------------------------------------------------------
    # 10. What Was Not Tested
    # ------------------------------------------------------------------
    lines += ["## 10. What Was Not Tested", ""]
    not_tested = [
        "Authentication and login flows (no test credentials provided)",
        "Checkout, payment, and order creation (destructive operations are always blocked)",
        "Admin write operations (production writes are always blocked)",
        "Database integrity checks (no DB connection provided)",
        "Load testing and stress testing (out of scope for safe audit)",
        "CAPTCHA bypass or anti-bot circumvention (always blocked)",
        "Manual exploratory testing (automated analysis only)",
    ]
    for item in not_tested:
        lines.append(f"- {item}")
    for s in skipped:
        human_mod = _module_label(s.name)
        lines.append(f"- {human_mod} ({s.reason})")
    lines += ["", "---", ""]

    # ------------------------------------------------------------------
    # 11. Assumptions and Limitations
    # ------------------------------------------------------------------
    lines += ["## 11. Assumptions and Limitations", ""]
    lines += [
        "- All findings are based on automated static analysis and read-only checks.",
        "- No production data was read, modified, or deleted during this audit.",
        "- Findings reflect the state of the system at the time of the audit run.",
        "- Risk scores are deterministic (severity weight x confidence weight) and do not account for business context.",
        "- A finding marked 'High confidence' means the evidence is clear, not that the risk is guaranteed to cause harm.",
        "- Modules that ran in planning-only mode produced no network-based evidence.",
        "",
    ]
    lines += ["---", ""]

    # ------------------------------------------------------------------
    # 12. Next Steps
    # ------------------------------------------------------------------
    lines += ["## 12. Next Steps", ""]
    lines += [
        "1. **Human review:** A qualified QA engineer reviews this report and signs off.",
        "2. **Triage findings:** Assign Critical and High findings to the development team.",
        "3. **Expand coverage:** Provide an API spec, target URL, or test credentials for deeper analysis.",
        "4. **Re-audit:** After remediation, run a follow-up audit to verify findings are resolved.",
        "5. **Client delivery:** Once all findings are triaged and the report is approved, "
        "share with the client via the delivery pack.",
        "",
    ]
    lines += ["---", ""]

    # ------------------------------------------------------------------
    # Footer
    # ------------------------------------------------------------------
    lines += [
        "## Review and Approval",
        "",
        "- [ ] QA engineer reviewed this report",
        "- [ ] All Critical and High findings triaged",
        "- [ ] Report approved for client delivery",
        "",
        "> This report was generated by AI QA Factory. "
        "It is a draft and requires human review before any external use.",
        "",
    ]

    return "\n".join(lines)


def write_client_delivery_report(
    path: Path,
    result: ClientAuditResult,
    plan: ClientAuditPlan,
) -> None:
    """Generate and write client_report.md to the given path."""
    content = generate_client_delivery_report(result, plan)
    path.write_text(content, encoding="utf-8")
