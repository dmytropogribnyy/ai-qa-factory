"""CLI: approval-gated local toolchain validation (Phase 3C).

Usage:
  python tools/validate_toolchain.py --project-id <id>
  python tools/validate_toolchain.py --project-id <id> --approve-toolchain
  python tools/validate_toolchain.py --scaffold-root <path> --approve-toolchain
  python tools/validate_toolchain.py --project-id <id> --json
  python tools/validate_toolchain.py --project-id <id> --approve-toolchain --json
  python tools/validate_toolchain.py --project-id <id> --no-write

SAFETY:
- Without --approve-toolchain: no commands executed, all skipped.
- With --approve-toolchain: runs only allowlisted local commands (npm install,
  npm run typecheck, npx playwright test --list).
- Never runs browser tests, never uses external URLs, never uses credentials.
- safe_to_execute_tests remains False always.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.toolchain_validator import ToolchainValidator


def _resolve_root(project_id: str | None, scaffold_root: str | None) -> Path:
    if scaffold_root:
        return Path(scaffold_root)
    if project_id:
        return Path("outputs") / project_id / "03_framework" / "playwright"
    print("ERROR: provide --project-id or --scaffold-root", file=sys.stderr)
    sys.exit(1)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Approval-gated local toolchain validation for Playwright scaffolds (Phase 3C).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Without --approve-toolchain: no commands executed, validation_status=blocked.\n"
            "With --approve-toolchain: runs npm install, typecheck, playwright --list only.\n"
            "Never runs browser tests. Never uses external URLs. Never uses credentials.\n"
            "safe_to_execute_tests remains False always."
        ),
    )
    parser.add_argument(
        "--project-id", metavar="ID",
        help="Project ID (looks up outputs/<id>/03_framework/playwright/)"
    )
    parser.add_argument(
        "--scaffold-root", metavar="PATH",
        help="Direct path to scaffold root directory"
    )
    parser.add_argument(
        "--approve-toolchain", action="store_true",
        help="Grant approval to execute allowlisted local commands (npm install, typecheck, --list)"
    )
    parser.add_argument(
        "--json", action="store_true", dest="json_output",
        help="Output validation report as JSON to stdout"
    )
    parser.add_argument(
        "--no-write", action="store_true",
        help="Skip writing artifact files (dry run)"
    )
    parser.add_argument(
        "--timeout", type=int, default=120, metavar="SECS",
        help="Per-command timeout in seconds (default: 120)"
    )
    args = parser.parse_args(argv)

    root = _resolve_root(args.project_id, args.scaffold_root)
    project_id = args.project_id or root.name

    validator = ToolchainValidator()
    report, approval = validator.validate_toolchain(
        root,
        project_id=project_id,
        approved=args.approve_toolchain,
        command_timeout=args.timeout,
    )

    if args.json_output:
        out = {
            "report": report.to_dict(),
            "approval": approval.to_dict(),
        }
        print(json.dumps(out, indent=2, ensure_ascii=False))
    else:
        status_icon = {
            "pass": "[PASS]", "fail": "[FAIL]", "blocked": "[BLOCKED]",
            "skipped": "[SKIP]", "warning": "[WARN]", "unknown": "[???]",
        }
        icon = status_icon.get(report.validation_status, f"[{report.validation_status.upper()}]")
        approved_str = "APPROVED (--approve-toolchain)" if report.approved else "NOT APPROVED"

        print(f"\nToolchain Validation {icon}")
        print(f"  Project:    {report.project_id}")
        print(f"  Root:       {report.scaffold_root}")
        print(f"  Approved:   {approved_str}")
        print(f"  Commands:   {len(report.commands)}")
        print(f"  Blockers:   {len(report.blockers)}")
        print(f"  Warnings:   {len(report.warnings)}")
        print()

        if report.blockers:
            print("BLOCKERS:")
            for b in report.blockers:
                print(f"  - {b}")
            print()

        if report.commands:
            print("Commands:")
            for cmd in report.commands:
                exit_str = f"exit={cmd.exit_code}" if cmd.exit_code is not None else ""
                skip_str = f"  [{cmd.skipped_reason}]" if cmd.skipped_reason else ""
                print(f"  [{cmd.status.upper()}] {cmd.command} {exit_str}{skip_str}")
            print()

        print("Safety invariants (all must be False):")
        print(f"  browser_execution_performed: {report.browser_execution_performed}")
        print(f"  external_url_used:           {report.external_url_used}")
        print(f"  credentials_used:            {report.credentials_used}")
        print(f"  safe_to_execute_tests:       {report.safe_to_execute_tests}")
        print()

        if not report.approved:
            print("To run toolchain commands, add --approve-toolchain:")
            print(f"  python tools/validate_toolchain.py --project-id {project_id} --approve-toolchain")
            print()

    if not args.no_write and root.exists():
        paths = validator.render_toolchain_artifacts(report, approval, root)
        if not args.json_output:
            print("Artifacts written:")
            for key, path in paths.items():
                print(f"  {key}: {path}")
            print()

    if report.validation_status == "fail":
        return 1
    if report.validation_status == "blocked" and not args.approve_toolchain:
        return 0  # blocked-without-approval is expected, not an error

    return 0


if __name__ == "__main__":
    sys.exit(main())
