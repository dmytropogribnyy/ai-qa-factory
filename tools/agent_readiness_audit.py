"""agent_readiness_audit.py — check whether the repository is agent-safe.

Verifies that required agent operating contract docs, artifact contracts, and
tooling exist and contain the expected key content. Dependency-free: no external
calls, no LLM calls, no automatic rewrites.

Usage:
    python tools/agent_readiness_audit.py
    python tools/agent_readiness_audit.py --no-write
    python tools/agent_readiness_audit.py --json

Exit codes:
    0 = all required checks passed
    1 = one or more required checks failed
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_OUTPUTS_ROOT = _PROJECT_ROOT / "outputs" / "agent_audit"


# ---------------------------------------------------------------------------
# Check definitions
# ---------------------------------------------------------------------------

def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError):
        return ""


def _file_exists(rel: str) -> tuple[bool, str]:
    path = _PROJECT_ROOT / rel
    ok = path.exists() and path.is_file()
    return ok, f"EXISTS: {rel}"


def _content_contains(rel: str, keyword: str, description: str) -> tuple[bool, str]:
    content = _read(_PROJECT_ROOT / rel)
    ok = keyword.lower() in content.lower()
    return ok, description


def _gitignore_contains(pattern: str) -> tuple[bool, str]:
    gitignore = _read(_PROJECT_ROOT / ".gitignore")
    ok = pattern in gitignore
    return ok, f".gitignore contains '{pattern}'"


def _run_checks() -> list[dict]:
    checks = []

    def add(check_id: str, name: str, ok: bool, message: str, required: bool = True) -> None:
        checks.append({
            "id": check_id,
            "name": name,
            "passed": ok,
            "message": message,
            "required": required,
        })

    # ------------------------------------------------------------------
    # Required agent contract docs
    # ------------------------------------------------------------------
    for rel in [
        "docs/AGENT_CONTRACT.md",
        "docs/PHASE_CONTRACTS.md",
        "docs/ARTIFACT_CONTRACTS.md",
        "docs/AGENT_HANDOFF_TEMPLATE.md",
    ]:
        ok, msg = _file_exists(rel)
        add(f"file:{rel}", f"File exists: {rel}", ok, msg)

    # ------------------------------------------------------------------
    # Required governance and safety docs
    # ------------------------------------------------------------------
    for rel in [
        "docs/DOCS_MANIFEST.md",
        "docs/DOCUMENTATION_GOVERNANCE.md",
        "docs/SAFETY_RULES.md",
        "docs/COMMANDS.md",
        "docs/SCHEMA_FOUNDATION.md",
        "docs/RUNBOOK.md",
    ]:
        ok, msg = _file_exists(rel)
        add(f"file:{rel}", f"File exists: {rel}", ok, msg)

    # ------------------------------------------------------------------
    # Required tools
    # ------------------------------------------------------------------
    ok, msg = _file_exists("tools/docs_audit.py")
    add("file:tools/docs_audit.py", "File exists: tools/docs_audit.py", ok, msg)

    # ------------------------------------------------------------------
    # .gitignore protections
    # ------------------------------------------------------------------
    ok, msg = _gitignore_contains("outputs/")
    add("gitignore:outputs", "outputs/ is gitignored", ok, msg)

    # ------------------------------------------------------------------
    # AGENT_CONTRACT content checks
    # ------------------------------------------------------------------
    contract = "docs/AGENT_CONTRACT.md"

    ok, msg = _content_contains(
        contract, "forbidden agent actions",
        "AGENT_CONTRACT contains 'Forbidden Agent Actions' section",
    )
    add("contract:forbidden_actions", msg, ok, msg)

    ok, msg = _content_contains(
        contract, "required final report format",
        "AGENT_CONTRACT contains 'Required Final Report Format' section",
    )
    add("contract:final_report_format", msg, ok, msg)

    ok, msg = _content_contains(
        contract, "do not fetch url",
        "AGENT_CONTRACT forbids URL fetching",
    )
    add("contract:no_url_fetch", msg, ok, msg)

    ok, msg = _content_contains(
        contract, "do not stage",
        "AGENT_CONTRACT forbids staging outputs/",
    )
    add("contract:no_stage_outputs", msg, ok, msg)

    ok, msg = _content_contains(
        contract, "do not use credentials",
        "AGENT_CONTRACT forbids credential use",
    )
    add("contract:no_credentials", msg, ok, msg)

    ok, msg = _content_contains(
        contract, "safety phrase",
        "AGENT_CONTRACT defines safety phrase requirements",
    )
    add("contract:safety_phrases", msg, ok, msg)

    # ------------------------------------------------------------------
    # PHASE_CONTRACTS content checks
    # ------------------------------------------------------------------
    phase_c = "docs/PHASE_CONTRACTS.md"

    ok, msg = _content_contains(
        phase_c, "allowed actions",
        "PHASE_CONTRACTS contains 'Allowed Actions' sections",
    )
    add("phase:allowed_actions", msg, ok, msg)

    ok, msg = _content_contains(
        phase_c, "blocked actions",
        "PHASE_CONTRACTS contains 'Blocked Actions' sections",
    )
    add("phase:blocked_actions", msg, ok, msg)

    ok, msg = _content_contains(
        phase_c, "acceptance criteria",
        "PHASE_CONTRACTS contains 'Acceptance Criteria' sections",
    )
    add("phase:acceptance_criteria", msg, ok, msg)

    ok, msg = _content_contains(
        phase_c, "[implemented]",
        "PHASE_CONTRACTS marks implemented phases with [implemented]",
    )
    add("phase:implemented_marker", msg, ok, msg)

    ok, msg = _content_contains(
        phase_c, "[planned]",
        "PHASE_CONTRACTS marks future phases with [planned]",
    )
    add("phase:planned_marker", msg, ok, msg)

    # ------------------------------------------------------------------
    # ARTIFACT_CONTRACTS content checks
    # ------------------------------------------------------------------
    artifact_c = "docs/ARTIFACT_CONTRACTS.md"

    ok, msg = _content_contains(
        artifact_c, "outputs/<project_id>/00_project/",
        "ARTIFACT_CONTRACTS documents outputs/<project_id>/00_project/ path",
    )
    add("artifact:00_project_path", msg, ok, msg)

    ok, msg = _content_contains(
        artifact_c, "reserved exclusively for workbench self-tests",
        "ARTIFACT_CONTRACTS states tests/ is reserved for Workbench self-tests",
    )
    add("artifact:tests_reserved", msg, ok, msg)

    ok, msg = _content_contains(
        artifact_c, "never committed",
        "ARTIFACT_CONTRACTS states outputs/ is never committed",
    )
    add("artifact:outputs_not_committed", msg, ok, msg)

    ok, msg = _content_contains(
        artifact_c, "machine-readable",
        "ARTIFACT_CONTRACTS distinguishes machine-readable vs human-readable",
    )
    add("artifact:machine_readable", msg, ok, msg)

    # ------------------------------------------------------------------
    # AGENT_HANDOFF_TEMPLATE content checks
    # ------------------------------------------------------------------
    template = "docs/AGENT_HANDOFF_TEMPLATE.md"

    for keyword, label in [
        ("tests run", "Tests"),
        ("docs audit", "Docs audit"),
        ("git status", "Git status"),
        ("safety boundary", "Safety boundary"),
        ("blockers", "Blockers"),
        ("recommended next step", "Recommended next step"),
        ("intentionally not implemented", "Intentionally not implemented"),
    ]:
        ok, msg = _content_contains(
            template, keyword,
            f"AGENT_HANDOFF_TEMPLATE includes '{label}' section",
        )
        add(f"template:{keyword.replace(' ', '_')}", msg, ok, msg)

    return checks


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def _print_report(checks: list[dict], write: bool) -> int:
    passed = [c for c in checks if c["passed"]]
    failed = [c for c in checks if not c["passed"]]
    required_failed = [c for c in failed if c["required"]]

    width = 72
    print()
    print("=" * width)
    print("  Agent Readiness Audit — Guided QA Automation Workbench")
    print("=" * width)
    print(f"  {len(checks)} checks run | {len(required_failed)} error(s) | {len(passed)} passed")
    print()

    if required_failed:
        print("  FAILED (required):")
        for c in required_failed:
            print(f"    [FAIL] {c['message']}")
        print()

    optional_failed = [c for c in failed if not c["required"]]
    if optional_failed:
        print("  FAILED (optional):")
        for c in optional_failed:
            print(f"    [WARN] {c['message']}")
        print()

    print("  PASSED:")
    for c in passed:
        print(f"    [OK]   {c['message']}")
    print()

    if not required_failed:
        print("  Recommended next action:")
        print("    Repository is agent-ready. Safe to proceed to Phase 2C.")
        print()
        print("  Result: [PASS]")
    else:
        print("  Recommended next action:")
        print("    Fix failed required checks before proceeding.")
        print()
        print("  Result: [FAIL]")

    print("=" * width)
    print()

    if write:
        _write_outputs(checks, passed, failed, required_failed)

    return 1 if required_failed else 0


def _write_outputs(
    checks: list[dict],
    passed: list[dict],
    failed: list[dict],
    required_failed: list[dict],
) -> None:
    _OUTPUTS_ROOT.mkdir(parents=True, exist_ok=True)

    # JSON
    summary = {
        "total": len(checks),
        "passed": len(passed),
        "failed": len(failed),
        "required_failed": len(required_failed),
        "result": "PASS" if not required_failed else "FAIL",
        "checks": checks,
    }
    (_OUTPUTS_ROOT / "agent_readiness_report.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    # Markdown
    lines = [
        "# Agent Readiness Report",
        "",
        f"**Checks:** {len(checks)} | **Passed:** {len(passed)} | "
        f"**Failed:** {len(failed)} | **Result:** {'PASS' if not required_failed else 'FAIL'}",
        "",
    ]
    if required_failed:
        lines += ["## Failed (required)", ""]
        for c in required_failed:
            lines.append(f"- [FAIL] {c['message']}")
        lines.append("")
    lines += ["## Passed", ""]
    for c in passed:
        lines.append(f"- [OK] {c['message']}")
    lines += [
        "",
        "---",
        "",
        "_Generated by `tools/agent_readiness_audit.py`. "
        "No external calls. No automatic fixes._",
        "",
    ]
    (_OUTPUTS_ROOT / "AGENT_READINESS_REPORT.md").write_text(
        "\n".join(lines), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Check whether the repository is agent-safe.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--no-write",
        dest="no_write",
        action="store_true",
        help="Print results only; do not write output files.",
    )
    p.add_argument(
        "--json",
        dest="output_json",
        action="store_true",
        help="Print JSON summary to stdout (implies --no-write).",
    )
    return p


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    checks = _run_checks()

    if args.output_json:
        passed = [c for c in checks if c["passed"]]
        failed = [c for c in checks if not c["passed"]]
        required_failed = [c for c in failed if c["required"]]
        print(json.dumps({
            "total": len(checks),
            "passed": len(passed),
            "failed": len(failed),
            "required_failed": len(required_failed),
            "result": "PASS" if not required_failed else "FAIL",
            "checks": checks,
        }, indent=2, ensure_ascii=False))
        return 1 if required_failed else 0

    write = not args.no_write
    return _print_report(checks, write=write)


if __name__ == "__main__":
    sys.exit(main())
