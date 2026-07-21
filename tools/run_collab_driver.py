"""Run the autonomous collaboration cycle (Issue #14.B/C — reviewer CONNECTED to delivery).

Owner-gated live path: needs an OpenAI key (OPENAI_API_KEY env or ~/.aiqa/openai.key). Each tick
reviews one pending request via the OpenAI reviewer under budget + retry guardrails, then delivers
every undelivered reply into its bound Claude session — no manual glue. Bounded by design: a poll loop
with a hard iteration cap, fail-closed on needs_owner/blocked, never a hidden unlimited loop.

    python tools/run_collab_driver.py --once
    python tools/run_collab_driver.py --poll 15 --max-iterations 200
"""
from __future__ import annotations

import argparse
import json
import sys
import time

from core.collaboration.service import CollaborationCycle


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="AI QA Factory collaboration cycle (review + deliver)")
    ap.add_argument("--output-root", default="outputs")
    ap.add_argument("--repo-root", default=".")
    ap.add_argument("--reviewer-id", default="gpt-reviewer")
    ap.add_argument("--session-file", default=".aiqa_collab_sessions.json")
    ap.add_argument("--once", action="store_true", help="run a single review+deliver tick and exit")
    ap.add_argument("--poll", type=float, default=10.0, help="seconds between polls (loop mode)")
    ap.add_argument("--max-iterations", type=int, default=500, help="hard cap on loop iterations")
    args = ap.parse_args(argv)

    from core.collaboration.session_delivery import SessionRegistry
    cycle = CollaborationCycle(args.output_root, args.repo_root, reviewer_id=args.reviewer_id,
                               registry=SessionRegistry(args.session_file))

    if args.once:
        print(json.dumps(cycle.tick(), ensure_ascii=False, default=str))
        return 0

    for _ in range(max(1, args.max_iterations)):
        outcome = cycle.tick()
        print(json.dumps(outcome, ensure_ascii=False, default=str))
        if outcome["review"]["status"] in ("needs_owner", "blocked"):
            return 2                                        # fail closed: stop for the owner
        time.sleep(max(0.0, args.poll))
    return 0


if __name__ == "__main__":
    sys.exit(main())
