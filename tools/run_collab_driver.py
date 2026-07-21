"""Run the autonomous collaboration reviewer driver (Issue #14.B).

Owner-gated live path: needs an OpenAI key (OPENAI_API_KEY env or ~/.aiqa/openai.key). It watches the
collaboration store for unanswered questions/proposals/checkpoints, reviews the exact SHA via the
OpenAI API under budget + retry guardrails, and posts immutable replies. Bounded by design — a poll
loop with a hard iteration cap, never a hidden unlimited loop.

    python tools/run_collab_driver.py --once
    python tools/run_collab_driver.py --poll 15 --max-iterations 200
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from core.collaboration.service import build_reviewer_driver


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="AI QA Factory collaboration reviewer driver")
    ap.add_argument("--output-root", default="outputs")
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--reviewer-id", default="gpt-reviewer")
    ap.add_argument("--once", action="store_true", help="process a single pending request and exit")
    ap.add_argument("--poll", type=float, default=10.0, help="seconds between polls (loop mode)")
    ap.add_argument("--max-iterations", type=int, default=500, help="hard cap on loop iterations")
    args = ap.parse_args(argv)

    driver = build_reviewer_driver(args.output_root, args.repo_root, reviewer_id=args.reviewer_id)

    if args.once:
        print(json.dumps(driver.process_once(), ensure_ascii=False))
        return 0

    for _ in range(max(1, args.max_iterations)):
        outcome = driver.process_once()
        print(json.dumps({**outcome, "health": driver.health()}, ensure_ascii=False))
        if outcome["status"] in ("needs_owner", "blocked"):
            return 2                                        # fail closed: stop for the owner
        time.sleep(max(0.0, args.poll))
    return 0


if __name__ == "__main__":
    sys.exit(main())
