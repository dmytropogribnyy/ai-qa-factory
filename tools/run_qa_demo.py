"""Run QA Evidence & Retest: real local Chromium + axe, predefined repair, targeted retest.

    .venv/Scripts/python.exe tools/run_qa_demo.py [--output-dir outputs] [--run-id ID]

Prints concise JSON (status, run_id, report path). Exit code 0 only for FIX_VERIFIED. The target
is always the owned local fixture; there is no external target argument. See docs/QA_DEMO.md.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.scout.qa_demo import run_qa_demo  # noqa: E402
from core.scout.store import RunStore, StoreError  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", default="outputs", help="output root (default: outputs)")
    parser.add_argument("--run-id", default=f"demo-qa-{uuid.uuid4().hex[:12]}",
                        help="new run id matching demo-qa-[a-zA-Z0-9_-]+ (default: fresh)")
    args = parser.parse_args(argv)
    try:
        result = run_qa_demo(args.output_dir, args.run_id)
    except (ValueError, FileExistsError, StoreError) as exc:
        print(json.dumps({"status": "REFUSED", "run_id": args.run_id, "reason": str(exc)}))
        return 2
    report = RunStore(args.output_dir, args.run_id).root / result["report_html"]
    print(json.dumps({"status": result["status"], "run_id": result["run_id"],
                      "reason": result["reason"], "report": str(report)}, indent=2))
    return 0 if result["status"] == "FIX_VERIFIED" else 1


if __name__ == "__main__":
    sys.exit(main())
