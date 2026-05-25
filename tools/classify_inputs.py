"""classify_inputs.py — standalone script for Phase 2A input classification.

Usage:
    python tools/classify_inputs.py --input "Need Playwright tests for SaaS dashboard"
    python tools/classify_inputs.py --input "https://app.example.com" --input "brief.txt"
    python tools/classify_inputs.py --input-file brief.txt
    python tools/classify_inputs.py --input "..." --project-id myproject --no-write

classify-only: no URL fetching, no browser execution, no credential use, no external calls.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Ensure project root is on sys.path when run as a script
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from core.workbench_controller import WorkbenchController  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Classify raw inputs without executing anything (Phase 2A).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--input", "-i",
        dest="inputs",
        action="append",
        default=[],
        metavar="TEXT_OR_URL",
        help="Raw input string (URL, text brief, file path). Repeat for multiple inputs.",
    )
    p.add_argument(
        "--input-file",
        dest="input_file",
        metavar="FILE",
        help="Read primary brief text from a file.",
    )
    p.add_argument(
        "--project-id",
        dest="project_id",
        default=None,
        help="Project ID to use (auto-generated if omitted).",
    )
    p.add_argument(
        "--source-platform",
        dest="source_platform",
        default="unknown",
        help="Source platform (upwork, linear, notion, unknown, ...).",
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
        help="Print full JSON result to stdout (implies --no-write).",
    )
    p.add_argument(
        "--with-blueprint",
        dest="with_blueprint",
        action="store_true",
        help="Run Phase 2B: build project blueprint and planning artifacts after Phase 2A classification.",
    )
    return p


def _print_summary(result: dict) -> None:
    pid = result["project_id"]
    im = result["input_map"]
    wr = result["work_request"]
    tc = result["task_classification"]
    ns = result["next_safe_step"]
    has_blueprint = "blueprint" in result

    phase_label = "Phase 2A + 2B" if has_blueprint else "Phase 2A"
    print()
    print("=" * 60)
    print(f"  CLASSIFY INPUTS — {phase_label}")
    print("=" * 60)
    print(f"  Project ID    : {pid}")
    print(f"  Sources       : {len(im.sources)}")
    print(f"  Task type     : {tc.task_type}")
    print(f"  Project type  : {tc.project_type}")
    print(f"  Confidence    : {tc.confidence}")
    print(f"  Title         : {wr.request_title[:60]}")
    if has_blueprint:
        bp = result["blueprint"]
        print(f"  Blueprint type: {bp.project_type}")
        print(f"  Environment   : {bp.environment}")
        print(f"  BP confidence : {bp.confidence_level}")
    print("-" * 60)
    print("  Input sources:")
    for src in im.sources:
        secret_flag = " [SECRETS REDACTED]" if "[REDACTED" in src.raw_value else ""
        # label already starts with [input_type], so print it directly
        print(f"    {src.label[:60]}{secret_flag}")
    print("-" * 60)
    print("  Next safe step:")
    for line in ns.split(". "):
        if line.strip():
            print(f"    {line.strip()}.")
    print("=" * 60)
    print()

    if "artifact_paths" in result:
        print("  Artifacts written:")
        for key, path in result["artifact_paths"].items():
            print(f"    {key}: {path}")
        print()


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    raw_inputs: list[str] = list(args.inputs)
    raw_text = ""

    if args.input_file:
        fp = Path(args.input_file)
        if not fp.exists():
            print(f"[ERROR] Input file not found: {fp}", file=sys.stderr)
            return 1
        try:
            content = fp.read_text(encoding="utf-8")
        except (UnicodeDecodeError, PermissionError) as exc:
            print(f"[ERROR] Cannot read file as text: {fp} ({exc})", file=sys.stderr)
            print("[ERROR] Only plain text files are supported. Binary files (images, archives) must be passed as --input paths.", file=sys.stderr)
            return 1
        raw_inputs.append(content)
        raw_text = content

    if not raw_inputs:
        parser.print_help()
        print("\n[ERROR] Provide at least one --input or --input-file.", file=sys.stderr)
        return 1

    # If no separate raw_text, use joined inputs as the classification text
    if not raw_text:
        raw_text = " ".join(raw_inputs)

    controller = WorkbenchController()

    if args.no_write or args.output_json:
        result = controller.analyze_inputs(
            raw_inputs=raw_inputs,
            raw_text=raw_text,
            source_platform=args.source_platform,
            project_id=args.project_id,
        )
        if args.with_blueprint:
            bp = controller.build_project_blueprint(
                result["input_map"],
                result["work_request"],
                result["task_classification"],
            )
            result["blueprint"] = bp
            result["blueprint_status"] = controller.update_project_status_for_blueprint(
                result["project_id"], bp
            )
    elif args.with_blueprint:
        result = controller.build_context_with_blueprint(
            raw_inputs=raw_inputs,
            raw_text=raw_text,
            source_platform=args.source_platform,
            project_id=args.project_id,
        )
    else:
        result = controller.build_initial_context(
            raw_inputs=raw_inputs,
            raw_text=raw_text,
            source_platform=args.source_platform,
            project_id=args.project_id,
        )

    if args.output_json:
        # Serialize schemas to dicts for JSON output
        output: dict = {
            "project_id": result["project_id"],
            "input_map": result["input_map"].to_dict(),
            "work_request": result["work_request"].to_dict(),
            "task_classification": result["task_classification"].to_dict(),
            "project_status": result["project_status"].to_dict(),
            "next_safe_step": result["next_safe_step"],
        }
        if "blueprint" in result:
            output["blueprint"] = result["blueprint"].to_dict()
            output["blueprint_status"] = result["blueprint_status"].to_dict()
        print(json.dumps(output, indent=2, ensure_ascii=False))
    else:
        _print_summary(result)

    return 0


if __name__ == "__main__":
    sys.exit(main())
