"""Phase 5M — Build CI/CD Config CLI.

Generates a CI/CD pipeline configuration (GitHub Actions or GitLab CI)
for running Playwright smoke tests.

Blocked flags: --password, --token, --secret, --api-key, --cookie,
               --pat, --access-token, --bearer, --db-url, --connection-string, --dsn
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_BLOCKED_FLAGS = (
    "--password", "--token", "--secret", "--api-key", "--cookie",
    "--pat", "--access-token", "--bearer", "--db-url",
    "--connection-string", "--dsn",
)

_ARTIFACT_DIR = "27_cicd"
_VALID_PLATFORMS = ("github_actions", "gitlab_ci", "azure_devops")


def _check_blocked_flags(argv: list[str]) -> None:
    for flag in _BLOCKED_FLAGS:
        if flag in argv:
            print(f"[BLOCKED] Flag '{flag}' is not allowed. Exit 2.", file=sys.stderr)
            sys.exit(2)


def main(argv: list[str] | None = None) -> int:
    _check_blocked_flags(argv if argv is not None else sys.argv[1:])

    parser = argparse.ArgumentParser(
        description="Generate CI/CD pipeline configuration for Playwright smoke tests."
    )
    parser.add_argument("--project-id", required=True, help="Project identifier")
    parser.add_argument(
        "--platform",
        default="github_actions",
        choices=list(_VALID_PLATFORMS),
        help="CI/CD platform (default: github_actions)",
    )
    parser.add_argument(
        "--scaffold-root",
        default="03_framework/playwright",
        help="Path to Playwright scaffold (default: 03_framework/playwright)",
    )
    parser.add_argument("--outputs-root", default="outputs", help="Root outputs directory")
    parser.add_argument("--no-write", action="store_true", help="Skip writing artifacts")

    args = parser.parse_args(argv)

    from core.cicd_builder import CICDBuilder

    output_dir = Path(args.outputs_root) / args.project_id / _ARTIFACT_DIR

    builder = CICDBuilder()
    config = builder.build(
        project_id=args.project_id,
        platform=args.platform,
        scaffold_root=args.scaffold_root,
        output_dir=str(output_dir),
        write=not args.no_write,
    )
    builder.build_manifest(
        config,
        output_dir=str(output_dir),
        write=not args.no_write,
    )

    print(f"[OK] Generated {args.platform} config: {config.workflow_filename}")
    print(f"     Steps: {', '.join(config.steps_included)}")
    if not args.no_write:
        print(f"[OK] Artifacts written to {output_dir}")
    print("     [NOTE] auto_pr_creation_allowed=False — copy files to your repo manually")
    print("     [NOTE] human_review_required=True — review before committing to CI")

    return 0


if __name__ == "__main__":
    sys.exit(main())
