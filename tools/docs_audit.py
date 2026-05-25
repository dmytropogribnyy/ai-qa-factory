"""
docs_audit.py — Documentation freshness audit for the Guided QA Automation Workbench.

Usage:
    python tools/docs_audit.py              # run audit, write reports to outputs/docs_audit/
    python tools/docs_audit.py --no-write   # run audit, print only (no file output)

Exit codes:
    0 — all required docs present, no hard errors
    1 — missing required docs or hard contradictions found

Rules:
    - Warns for wording/coverage issues (subjective)
    - Fails (exit 1) only for missing required docs or obvious hard contradictions
    - Makes no external calls
    - Does not modify documentation files
    - Does not use LLM or external services
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

# Ensure UTF-8 output on Windows (cp1252 default breaks Unicode symbols)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_DOCS: list[tuple[str, str]] = [
    ("README.md",                           "Public overview / entry point"),
    ("docs/VISION.md",                      "Product vision and direction"),
    ("docs/RUNBOOK.md",                     "Operational workflow guide"),
    ("docs/COMMANDS.md",                    "CLI command reference"),
    ("docs/APPROVAL_MODEL.md",              "Approval and risk model"),
    ("docs/SAFETY_RULES.md",               "Safety rules — non-negotiable"),
    ("docs/TOOLING_DECISIONS.md",          "Tooling choices and rationale"),
    ("docs/SCHEMA_FOUNDATION.md",          "Schema layer overview"),
    ("docs/DOCUMENTATION_GOVERNANCE.md",   "Docs governance rules"),
    ("docs/DOCS_MANIFEST.md",              "Documentation manifest / registry"),
]

# Docs that must be source-of-truth docs (checked for existence only here)
SOURCE_OF_TRUTH_DOCS = [
    "README.md",
    "docs/VISION.md",
    "docs/RUNBOOK.md",
    "docs/COMMANDS.md",
    "docs/APPROVAL_MODEL.md",
    "docs/SAFETY_RULES.md",
    "docs/TOOLING_DECISIONS.md",
    "docs/SCHEMA_FOUNDATION.md",
    "docs/DOCUMENTATION_GOVERNANCE.md",
    "docs/DOCS_MANIFEST.md",
]

# Features that are foundation-only / not yet runtime.
# Audit warns if docs describe these as "implemented" without a qualifier.
# Each entry: (feature_label, search_terms_that_suggest_runtime_claim, qualifying_terms_that_make_it_ok)
FOUNDATION_ONLY_FEATURES: list[tuple[str, list[str], list[str]]] = [
    (
        "credential/auth execution",
        ["auth execution", "executes auth", "runs auth", "run-auth-smoke", "auth-check"],
        ["planned", "foundation-only", "schema-only", "not implemented", "deferred",
         "future", "[planned]", "phase 2", "phase 3", "no runtime", "not yet"],
    ),
    (
        "mobile/native execution",
        ["appium", "maestro", "ios simulator", "android emulator", "native execution",
         "run-tests.*mobile", "mobile execution"],
        ["planned", "foundation-only", "schema-only", "not implemented", "deferred",
         "optional", "future", "[planned]", "advisory", "phase 2", "phase 3", "not yet",
         "experience"],  # "Tosca/Maestro experience" = client skill, not runtime claim
    ),
    (
        "cleanup runtime deletion",
        ["deletes files", "removes files", "cleanup apply", "apply cleanup",
         "confirmed deletion", "executes cleanup"],
        ["planned", "dry-run", "dry run", "dry_run", "not implemented", "deferred",
         "requires approval", "schema-only", "[planned]", "foundation-only",
         "explicit approval", "phase 2"],
    ),
    (
        "n8n/external HTTP calls",
        ["sends http", "posts to n8n", "triggers webhook", "webhook call",
         "http request to", "calls n8n"],
        ["planned", "not implemented", "deferred", "optional", "future",
         "schema-only", "[planned]", "no http calls", "without", "must not",
         "never", "violation"],
    ),
    (
        "LangGraph runtime",
        ["langgraph is used", "using langgraph", "langgraph runs", "langgraph backend"],
        ["optional", "not added", "not yet", "future", "planned", "deferred",
         "optional future", "not mandatory"],
    ),
    (
        "Allure adapter",
        ["allure is installed", "allure generates", "allure runs", "requires allure"],
        ["optional", "not in requirements", "not mandatory", "future", "advisory",
         "when to use", "client explicitly", "when the client"],
    ),
    (
        "LangSmith adapter",
        ["langsmith is required", "langsmith runs", "requires langsmith"],
        ["optional", "not mandatory", "future", "advisory", "not in requirements"],
    ),
    (
        "Playwright MCP runtime",
        ["playwright mcp is required", "playwright mcp runs", "mcp controls browser",
         "requires mcp server"],
        ["optional", "not mandatory", "not reintroduce", "guide only", "advisory",
         "not a required", "not managed"],
    ),
]

# Commands that should be marked [implemented] in COMMANDS.md
KNOWN_IMPLEMENTED_COMMANDS = [
    "system-health", "capabilities", "agents", "prescreen", "filter",
    "batch-filter", "upwork", "plan", "test-design", "scaffold",
    "audit", "review", "delivery", "full", "run-tests", "ask", "mcp-guide",
]

# Docs to skip for the foundation-only feature scan (legacy, stale, or generated docs
# that predate the governance policy and cannot be easily qualified without rewriting).
SKIP_FOUNDATION_SCAN: set[str] = {
    "docs/AI_QA_Factory_Concept_and_Implementation_Plan_v7_validation_hardened.md",
    "docs/PRESCREENING_AND_EXECUTION_COCKPIT.md",
    "docs/PROJECT_EXTENSIONS_SELF_HEALTH_TEST_DESIGN.md",
    "docs/V507_CODE_DOC_SYNC_NOTES.md",
    "docs/V508_MODEL_ROUTING_NOTES.md",
    "docs/REPO_STRATEGIC_READINESS_AUDIT_v1.md",
    "docs/GLOBAL_AUDIT_AND_REAL_TESTING_READINESS.md",
    "docs/DEMO_SITE_TESTING_REPORT_v1.md",
    "docs/LOVABLE_UI_PLAN.md",
    "docs/LANGGRAPH_V5_NOTE.md",
}

# ---------------------------------------------------------------------------
# Check helpers
# ---------------------------------------------------------------------------

CheckResult = dict[str, Any]


def make_check(
    doc_path: str,
    check_type: str,
    passed: bool,
    severity: str,
    finding: str,
    recommended_action: str = "",
    related_file: str | None = None,
) -> CheckResult:
    return {
        "doc_path": doc_path,
        "check_type": check_type,
        "passed": passed,
        "severity": severity,
        "finding": finding,
        "recommended_action": recommended_action,
        "related_file": related_file,
    }


def read_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def check_required_docs(root: Path) -> list[CheckResult]:
    results = []
    for rel, purpose in REQUIRED_DOCS:
        full = root / rel
        exists = full.exists()
        results.append(make_check(
            doc_path=rel,
            check_type="missing_doc",
            passed=exists,
            severity="error" if not exists else "info",
            finding=f"{'EXISTS' if exists else 'MISSING'}: {rel} — {purpose}",
            recommended_action="" if exists else f"Create {rel}",
        ))
    return results


def check_commands_md_markings(root: Path) -> list[CheckResult]:
    """Warn if known-implemented commands are not marked [implemented]."""
    results = []
    commands_path = root / "docs" / "COMMANDS.md"
    if not commands_path.exists():
        return results
    content = read_file(commands_path)
    for cmd in KNOWN_IMPLEMENTED_COMMANDS:
        if f"`{cmd}`" in content or f"### `{cmd}`" in content:
            # Check that [implemented] appears near it
            idx = content.find(f"`{cmd}`")
            snippet = content[max(0, idx - 20): idx + 120]
            if "[implemented]" not in snippet.lower():
                results.append(make_check(
                    doc_path="docs/COMMANDS.md",
                    check_type="implemented_command_marking",
                    passed=False,
                    severity="warning",
                    finding=f"Command `{cmd}` exists in COMMANDS.md but may be missing [implemented] marker",
                    recommended_action=f"Ensure `{cmd}` has `[implemented]` marker",
                ))
    # Check that docs-audit / docs-check appear as planned
    for planned_cmd in ("docs-audit", "docs-check", "docs-freshness-report"):
        if planned_cmd in content:
            idx = content.find(planned_cmd)
            snippet = content[max(0, idx - 10): idx + 120]
            if "[planned]" not in snippet.lower() and "[implemented]" not in snippet.lower():
                results.append(make_check(
                    doc_path="docs/COMMANDS.md",
                    check_type="planned_command_marking",
                    passed=False,
                    severity="warning",
                    finding=f"Command `{planned_cmd}` found but missing [planned] or [implemented] marker",
                    recommended_action=f"Mark `{planned_cmd}` as [planned] or [implemented]",
                ))
    return results


def check_foundation_only_features(root: Path) -> list[CheckResult]:
    """Warn if docs describe foundation-only features as fully-implemented runtime."""
    results = []
    doc_files = list((root / "docs").glob("*.md")) + [root / "README.md"]
    for doc_file in doc_files:
        if not doc_file.exists():
            continue
        rel = str(doc_file.relative_to(root)).replace("\\", "/")
        if rel in SKIP_FOUNDATION_SCAN:
            continue  # legacy/stale doc — skip foundation scan
        content = read_file(doc_file).lower()
        for feature_label, claim_terms, ok_terms in FOUNDATION_ONLY_FEATURES:
            for claim in claim_terms:
                if claim.lower() in content:
                    # Check if a qualifying / hedging term appears nearby
                    idx = content.find(claim.lower())
                    # Look in a 300-char window around the match
                    window = content[max(0, idx - 150): idx + 150]
                    ok = any(ok.lower() in window for ok in ok_terms)
                    if not ok:
                        results.append(make_check(
                            doc_path=rel,
                            check_type="runtime_claim_without_implementation",
                            passed=False,
                            severity="warning",
                            finding=(
                                f"'{claim}' found in {rel} near text that may describe "
                                f"{feature_label} as implemented (no qualifying term nearby)"
                            ),
                            recommended_action=(
                                f"Add 'planned', 'foundation-only', 'not implemented', or "
                                f"'[planned]' qualifier near the mention of {feature_label}"
                            ),
                        ))
    return results


def check_docs_manifest_lists_source_of_truth(root: Path) -> list[CheckResult]:
    """Warn if DOCS_MANIFEST.md doesn't mention core source-of-truth docs."""
    results = []
    manifest_path = root / "docs" / "DOCS_MANIFEST.md"
    if not manifest_path.exists():
        return results
    content = read_file(manifest_path)
    for doc in SOURCE_OF_TRUTH_DOCS[:6]:  # check the core 6
        if doc not in content and os.path.basename(doc) not in content:
            results.append(make_check(
                doc_path="docs/DOCS_MANIFEST.md",
                check_type="source_of_truth_conflict",
                passed=False,
                severity="warning",
                finding=f"DOCS_MANIFEST.md does not mention {doc}",
                recommended_action=f"Add {doc} to DOCS_MANIFEST.md",
            ))
    return results


def check_schema_foundation_mentions_documentation(root: Path) -> list[CheckResult]:
    """Warn if SCHEMA_FOUNDATION.md doesn't mention the documentation schema."""
    sf_path = root / "docs" / "SCHEMA_FOUNDATION.md"
    if not sf_path.exists():
        return []
    content = read_file(sf_path)
    if "documentation.py" not in content and "DocumentationRecord" not in content:
        return [make_check(
            doc_path="docs/SCHEMA_FOUNDATION.md",
            check_type="schema_reference_missing",
            passed=False,
            severity="warning",
            finding="SCHEMA_FOUNDATION.md does not mention documentation.py / DocumentationRecord",
            recommended_action="Add documentation schema section to SCHEMA_FOUNDATION.md",
        )]
    return []


# ---------------------------------------------------------------------------
# Main audit runner
# ---------------------------------------------------------------------------

def run_audit(root: Path) -> dict[str, Any]:
    all_checks: list[CheckResult] = []

    all_checks += check_required_docs(root)
    all_checks += check_commands_md_markings(root)
    all_checks += check_foundation_only_features(root)
    all_checks += check_docs_manifest_lists_source_of_truth(root)
    all_checks += check_schema_foundation_mentions_documentation(root)

    errors = [c for c in all_checks if not c["passed"] and c["severity"] == "error"]
    critical = [c for c in all_checks if not c["passed"] and c["severity"] == "critical"]
    warnings = [c for c in all_checks if not c["passed"] and c["severity"] == "warning"]
    hard_failures = errors + critical

    docs_needing_review = sorted({
        c["doc_path"] for c in all_checks if not c["passed"] and c["severity"] in ("error", "warning")
    })
    blockers = [c["finding"] for c in hard_failures]

    summary_parts = [
        f"{len(all_checks)} checks run",
        f"{len(hard_failures)} error(s)",
        f"{len(warnings)} warning(s)",
        f"{len(all_checks) - len(hard_failures) - len(warnings)} passed",
    ]
    summary = " | ".join(summary_parts)

    if hard_failures:
        next_action = "Fix errors listed in blockers before proceeding to next phase."
    elif warnings:
        next_action = "Review warnings above, update docs where appropriate, then re-run."
    else:
        next_action = "Documentation is current. Safe to proceed to the next planned phase."

    return {
        "project_id": "workbench",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "checks": all_checks,
        "docs_current": len(hard_failures) == 0,
        "docs_needing_review": docs_needing_review,
        "blockers": blockers,
        "summary": summary,
        "recommended_next_action": next_action,
        "exit_code": 1 if hard_failures else 0,
    }


# ---------------------------------------------------------------------------
# Output formatting
# ---------------------------------------------------------------------------

SEVERITY_PREFIX = {"info": "  [OK]", "warning": "  [WARN]", "error": "  [ERROR]", "critical": "  [CRIT]"}


def print_report(report: dict[str, Any]) -> None:
    print()
    print("=" * 64)
    print("  Docs Audit — Guided QA Automation Workbench")
    print("=" * 64)
    print(f"  {report['summary']}")
    print()

    failures = [c for c in report["checks"] if not c["passed"]]
    passed = [c for c in report["checks"] if c["passed"]]

    if passed:
        print(f"  PASSED ({len(passed)}):")
        for c in passed:
            print(f"    [OK]  {c['finding']}")
        print()

    if failures:
        print(f"  ISSUES ({len(failures)}):")
        for c in failures:
            prefix = SEVERITY_PREFIX.get(c["severity"], "  ?")
            print(f"{prefix}  {c['finding']}")
            if c.get("recommended_action"):
                print(f"       -> {c['recommended_action']}")
        print()

    if report["blockers"]:
        print("  BLOCKERS (must fix before next phase):")
        for b in report["blockers"]:
            print(f"    [ERROR]  {b}")
        print()

    print("  Recommended next action:")
    print(f"    {report['recommended_next_action']}")
    print()
    status = "[PASS]" if report["docs_current"] else "[FAIL]"
    print(f"  Result: {status}")
    print("=" * 64)
    print()


def write_reports(root: Path, report: dict[str, Any]) -> None:
    out_dir = root / "outputs" / "docs_audit"
    out_dir.mkdir(parents=True, exist_ok=True)

    # JSON report
    json_path = out_dir / "docs_freshness_report.json"
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    # Markdown report
    md_path = out_dir / "DOCS_FRESHNESS_REPORT.md"
    lines = [
        "# Docs Freshness Report — Guided QA Automation Workbench",
        "",
        f"**Generated:** {report['created_at']}  ",
        f"**Result:** {'PASS' if report['docs_current'] else 'FAIL'}  ",
        f"**Summary:** {report['summary']}",
        "",
        "---",
        "",
        "## Checks",
        "",
        "| Doc | Type | Severity | Finding |",
        "|---|---|---|---|",
    ]
    for c in report["checks"]:
        sev = c["severity"].upper() if not c["passed"] else "OK"
        finding = c["finding"].replace("|", "\\|")
        lines.append(f"| {c['doc_path']} | {c['check_type']} | {sev} | {finding} |")

    if report["blockers"]:
        lines += ["", "## Blockers", ""]
        for b in report["blockers"]:
            lines.append(f"- {b}")

    if report["docs_needing_review"]:
        lines += ["", "## Docs Needing Review", ""]
        for d in report["docs_needing_review"]:
            lines.append(f"- `{d}`")

    lines += [
        "",
        "## Recommended Next Action",
        "",
        report["recommended_next_action"],
    ]

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"  Reports written to: {out_dir}/")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description="Docs freshness audit")
    parser.add_argument(
        "--no-write", action="store_true",
        help="Print only, do not write output files"
    )
    parser.add_argument(
        "--root", type=str, default=str(REPO_ROOT),
        help="Repository root (default: auto-detected)"
    )
    args = parser.parse_args()

    root = Path(args.root).resolve()
    report = run_audit(root)
    print_report(report)

    if not args.no_write:
        write_reports(root, report)

    return report["exit_code"]


if __name__ == "__main__":
    sys.exit(main())
