"""Assembly + worker-side helpers for the Direct Collaboration Driver (Issue #14).

Thin, testable glue that the ``tools/`` CLIs wrap: resolve the current git head, submit worker
envelopes (question / proposal / checkpoint), build a live reviewer driver, and record an
acknowledgement. Keeping this in one module means the launchers are trivial and the wiring is unit
tested without a network.
"""
from __future__ import annotations

import re
import subprocess
from typing import Any, Dict, Optional

from core.collaboration.budget import BudgetLedger, BudgetPolicy
from core.collaboration.envelopes import make_envelope
from core.collaboration.reviewer_client import OpenAIReviewerClient, ReviewerClient
from core.collaboration.reviewer_driver import ReviewerDriver
from core.collaboration.store import CollaborationStore

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")


def resolve_git_head(repo_root: str = ".") -> str:
    try:
        proc = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo_root, capture_output=True,
                              text=True, timeout=15, check=False)
        head = (proc.stdout or "").strip().lower()
        return head if _FULL_SHA.fullmatch(head) else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def submit_worker_message(output_root: str, *, kind: str, thread_id: str, body: str,
                          head_sha: str, branch: str, pr_number: Any = None,
                          evidence_refs: Optional[list] = None,
                          requested_next_action: str = "") -> Dict[str, Any]:
    """Worker (Claude) side: enqueue a QUESTION / PROPOSAL / CHECKPOINT for the reviewer."""
    store = CollaborationStore(output_root)
    envelope = make_envelope(kind=kind, thread_id=thread_id, actor="claude-worker", body=body,
                             head_sha=head_sha, branch=branch, pr_number=pr_number,
                             evidence_refs=evidence_refs, requested_next_action=requested_next_action)
    return store.append(envelope)


def record_ack(output_root: str, *, thread_id: str, decision_key: str, note: str = "") -> Dict[str, Any]:
    """Worker (Claude) side: acknowledge a delivered decision so the loop is auditable end to end."""
    store = CollaborationStore(output_root)
    envelope = make_envelope(kind="ACKNOWLEDGEMENT", thread_id=thread_id, actor="claude-worker",
                             body=note or "decision received", in_reply_to=decision_key)
    return store.append(envelope)


def build_reviewer_driver(output_root: str, repo_root: str = ".", *,
                          reviewer_client: Optional[ReviewerClient] = None,
                          policy: Optional[BudgetPolicy] = None,
                          reviewer_id: str = "gpt-reviewer") -> ReviewerDriver:
    store = CollaborationStore(output_root)
    budget = BudgetLedger(output_root, policy=policy or BudgetPolicy())
    client = reviewer_client or OpenAIReviewerClient()
    return ReviewerDriver(store, budget, client, repo_root=repo_root,
                          head_resolver=lambda: resolve_git_head(repo_root), reviewer_id=reviewer_id)
