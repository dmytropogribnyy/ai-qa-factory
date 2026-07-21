"""Wait locally for a review-relay decision without invoking Claude or any external service."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))  # noqa: E402

from core.review_relay import ReviewRelay, ReviewRelayError  # noqa: E402


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Wait for an AI QA review-relay decision")
    parser.add_argument("checkpoint_id")
    parser.add_argument("--timeout", type=int, default=3600)
    parser.add_argument("--poll", type=float, default=5.0)
    args = parser.parse_args(argv)
    relay = ReviewRelay(os.environ.get("AIQA_OUTPUT_ROOT", "outputs"))
    deadline = time.monotonic() + max(1, args.timeout)
    while time.monotonic() < deadline:
        try:
            result = relay.get_decision(args.checkpoint_id)
        except ReviewRelayError as exc:
            print(json.dumps({"status": "error", "message": str(exc)}))
            raise SystemExit(1) from exc
        if result.get("status") != "pending":
            print(json.dumps(result, indent=2, ensure_ascii=False))
            return
        time.sleep(max(0.5, args.poll))
    print(json.dumps({"status": "timeout", "checkpoint_id": args.checkpoint_id}))
    raise SystemExit(2)


if __name__ == "__main__":
    main()
