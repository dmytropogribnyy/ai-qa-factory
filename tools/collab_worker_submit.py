"""Worker-side Direct-Driver submission CLI (Issue #17).

A fresh, session-independent Claude writer uses THIS to submit its canonical-protocol messages
(``PROPOSAL`` / ``CHECKPOINT`` / ``QUESTION``) and to ``ACKNOWLEDGEMENT`` a reviewer decision, into the
shared Direct-Driver collaboration store held by the CONTROLLER (``--output-root``). It is a thin, safe
wrapper over ``core.collaboration.service``: it only appends an immutable, redacted, SHA-bound envelope —
it can never merge, review, run shell, or send anything externally. Code-bound kinds fail closed unless a
valid full head SHA + branch are provided; the head SHA is resolved from the writer's own worktree when
not given explicitly.

    python tools/collab_worker_submit.py --output-root <controller-outputs> --thread <packet_id> \
        --kind PROPOSAL --branch feat/x --body-file plan.md
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from core.collaboration.envelopes import EnvelopeError  # noqa: E402
from core.collaboration.service import (  # noqa: E402
    record_ack,
    resolve_branch_head,
    resolve_git_head,
    submit_worker_message,
)
from core.collaboration.store import CollaborationStoreError  # noqa: E402

_REQUEST_KINDS = ("QUESTION", "PROPOSAL", "CHECKPOINT")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="AI QA Factory worker-side Direct-Driver submit")
    ap.add_argument("--output-root", required=True,
                    help="the CONTROLLER output root that holds _review_relay (the shared store)")
    ap.add_argument("--thread", required=True, help="collaboration thread id (== product packet id)")
    ap.add_argument("--kind", required=True, choices=sorted((*_REQUEST_KINDS, "ACKNOWLEDGEMENT")))
    ap.add_argument("--body", default="")
    ap.add_argument("--body-file", default="", help="read the body from this file (overrides --body)")
    ap.add_argument("--branch", default="")
    ap.add_argument("--head-sha", default="", help="exact full 40-char head SHA (auto-resolved if omitted)")
    ap.add_argument("--pr", default=None)
    ap.add_argument("--in-reply-to", default="", help="required for ACKNOWLEDGEMENT (the decision key)")
    ap.add_argument("--evidence", nargs="*", default=None)
    ap.add_argument("--next-action", default="")
    ap.add_argument("--workspace", default=".", help="worktree used to resolve head_sha/branch")
    args = ap.parse_args(argv)

    body = Path(args.body_file).read_text(encoding="utf-8") if args.body_file else args.body

    if args.kind == "ACKNOWLEDGEMENT":
        if not str(args.in_reply_to).strip():
            print("ACKNOWLEDGEMENT requires --in-reply-to (the reviewer decision key)", file=sys.stderr)
            return 2
        try:
            rec = record_ack(args.output_root, thread_id=args.thread,
                             decision_key=args.in_reply_to, note=body or "decision received")
        except (EnvelopeError, CollaborationStoreError) as exc:
            print(f"ack rejected: {exc}", file=sys.stderr)
            return 2
        print(rec.get("message_id", ""))
        return 0

    head = str(args.head_sha or "").strip().lower()
    if not head:
        head = (resolve_branch_head(args.workspace, args.branch) if args.branch
                else resolve_git_head(args.workspace))
    try:
        rec = submit_worker_message(args.output_root, kind=args.kind, thread_id=args.thread, body=body,
                                    head_sha=head, branch=args.branch, pr_number=args.pr,
                                    evidence_refs=args.evidence, requested_next_action=args.next_action)
    except (EnvelopeError, CollaborationStoreError) as exc:
        # Fail closed: a code-bound message without a valid exact head SHA + branch must never persist.
        print(f"submit rejected: {exc}", file=sys.stderr)
        return 2
    print(rec.get("message_id", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
