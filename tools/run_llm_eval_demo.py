"""Run LLM Output Evaluation: grade baseline vs candidate outputs offline.

    .venv/Scripts/python.exe tools/run_llm_eval_demo.py [--output-dir outputs] [--run-id ID]
                                                        [--responses recorded.json]

Default mode FIXTURE grades the constructed example outputs in fixtures/llm_eval_demo; with
--responses it grades locally recorded outputs (user-declared provenance, never verified). No
model or provider is called and no key is requested. Prints concise JSON (verdict, pass counts,
improved/regressed case ids, report path). Exit 0 for IMPROVED/STABLE, 1 for REGRESSION_DETECTED
(the evaluation completed; the demo policy rejects the candidate), 2 when refused.
See docs/LLM_EVALUATION.md.
"""
from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.llm_eval_demo import run_llm_eval_demo  # noqa: E402
from core.scout.store import RunStore, StoreError  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--output-dir", default="outputs", help="output root (default: outputs)")
    parser.add_argument("--run-id", default=f"demo-llm-{uuid.uuid4().hex[:12]}",
                        help="new run id matching demo-llm-[A-Za-z0-9_-]+ (default: fresh)")
    parser.add_argument("--responses", default=None,
                        help="optional local recorded-responses JSON (see the fixtures README)")
    args = parser.parse_args(argv)
    try:
        result = run_llm_eval_demo(args.output_dir, args.run_id, responses_path=args.responses)
    except (ValueError, OSError, StoreError) as exc:
        print(json.dumps({"status": "REFUSED", "run_id": args.run_id, "reason": str(exc)}))
        return 2
    cmp = result["comparison"]
    report = RunStore(args.output_dir, args.run_id).root / result["report_html"]
    print(json.dumps({
        "status": result["status"], "run_id": result["run_id"], "mode": result["mode"],
        "verdict": result["verdict"],
        "baseline": {k: cmp["baseline"][k] for k in ("total", "passed", "failed", "pass_rate")},
        "candidate": {k: cmp["candidate"][k] for k in ("total", "passed", "failed", "pass_rate")},
        "improved": cmp["improved"], "regressed": cmp["regressed"],
        "provider_called": result["provider_called"],
        "note": "demo comparison policy, not release authorization",
        "report": str(report),
    }, indent=2))
    return 1 if result["verdict"] == "REGRESSION_DETECTED" else 0


if __name__ == "__main__":
    sys.exit(main())
