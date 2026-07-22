"""Pull-first worker reply path for the session-independent writer (Issue #17, GPT direction).

Push delivery binds a thread to a Claude session id, which a fresh detached writer does not have while
it is still running — a bootstrap cycle. So the writer instead PULLS over the same Direct-Driver store:
it submits a request, blocks on a bounded local wait for the reply correlated by exact ``in_reply_to``,
ACKs, implements, checkpoints. Everything here is a thin, testable layer over the canonical
``core.collaboration`` write path — no second store, no MCP, no network, no spend while waiting.

Phase idempotency is the key safety property: a restart re-runs ``submit_request`` but never creates a
second GPT request (one PROPOSAL per thread; one CHECKPOINT per exact head SHA), so the reviewer is
never asked twice and the writer resumes from the persisted phase instead of repeating a completed one.
"""
from __future__ import annotations

import time as _time
from typing import Any, Callable, Dict, Optional

from core.collaboration.packet_phase import (
    PHASE_CHECKPOINTED,
    PHASE_DECIDED_GO,
    PHASE_DECIDED_NOGO,
    PHASE_NEW,
    PHASE_PROPOSAL_ACKED,
    PHASE_PROPOSED,
    phase_for_packet,
)
from core.collaboration.service import (
    record_ack,
    resolve_branch_head,
    resolve_git_head,
    submit_worker_message,
)
from core.collaboration.store import CollaborationStore

_REQUEST_KINDS = ("QUESTION", "PROPOSAL", "CHECKPOINT")
_REPLY_KINDS = {"RESPONSE", "CRITIQUE", "RECOMMENDATION", "DECISION"}

_NEXT_ACTION = {
    PHASE_NEW: "submit a PROPOSAL of your plan",
    PHASE_PROPOSED: "wait for the reviewer reply, then ACK it",
    PHASE_PROPOSAL_ACKED: "implement + test, then submit an exact-SHA CHECKPOINT",
    PHASE_CHECKPOINTED: "wait for the CHECKPOINT decision, then ACK it",
    PHASE_DECIDED_NOGO: "address the NO-GO blockers, then submit a new exact-SHA CHECKPOINT",
    PHASE_DECIDED_GO: "complete — an exact-SHA GO was recorded",
}


def _resolve_head(workspace: str, branch: str, head_sha: str) -> str:
    head = str(head_sha or "").strip().lower()
    if head:
        return head
    return resolve_branch_head(workspace, branch) if branch else resolve_git_head(workspace)


def _existing_request(store: CollaborationStore, thread_id: str, kind: str,
                      head_sha: str) -> Optional[Dict[str, Any]]:
    """The already-submitted request of this kind for the thread (per exact head for a CHECKPOINT), so a
    restart returns it instead of asking the reviewer again."""
    for m in store.thread(thread_id)["messages"]:
        if m.get("kind") != kind:
            continue
        if kind == "CHECKPOINT" and head_sha and str(m.get("head_sha", "")).lower() != head_sha.lower():
            continue
        return m
    return None


def submit_request(output_root: str, *, thread_id: str, kind: str, body: str, branch: str,
                   head_sha: str = "", pr_number: Any = None, workspace: str = ".") -> Dict[str, Any]:
    """Phase-idempotent submit of a QUESTION / PROPOSAL / CHECKPOINT. Returns the existing request
    (``duplicate=True``) rather than duplicating a GPT request on restart."""
    if kind not in _REQUEST_KINDS:
        raise ValueError(f"submit_request kind must be one of {_REQUEST_KINDS}, got {kind!r}")
    head = _resolve_head(workspace, branch, head_sha)
    store = CollaborationStore(output_root)
    existing = _existing_request(store, thread_id, kind, head)
    if existing is not None:
        return {"message_id": existing.get("message_id"),
                "idempotency_key": existing.get("idempotency_key"), "duplicate": True, "head_sha": head}
    rec = submit_worker_message(output_root, kind=kind, thread_id=thread_id, body=body,
                                head_sha=head, branch=branch, pr_number=pr_number)
    return {"message_id": rec.get("message_id"), "idempotency_key": rec.get("idempotency_key"),
            "duplicate": False, "head_sha": head}


def find_reply(output_root: str, *, thread_id: str, in_reply_to: str) -> Optional[Dict[str, Any]]:
    """The reviewer reply on THIS thread correlated by exact ``in_reply_to`` (no cross-thread, no
    stray-reply match)."""
    target = str(in_reply_to or "")
    if not target:
        return None
    for m in CollaborationStore(output_root).thread(thread_id)["messages"]:
        if m.get("kind") in _REPLY_KINDS and str(m.get("in_reply_to", "")) == target:
            return m
    return None


def wait_for_reply(output_root: str, *, thread_id: str, in_reply_to: str, timeout_s: float,
                   poll_s: float = 2.0, clock: Optional[Callable[[], float]] = None,
                   sleep: Optional[Callable[[float], None]] = None) -> Optional[Dict[str, Any]]:
    """Block (bounded, free — no GPT call, no store writes) until the correlated reply appears or the
    timeout elapses. Returns the reply, or None on timeout (a free retry state)."""
    clock = clock or _time.monotonic
    sleep = sleep if sleep is not None else _time.sleep
    deadline = clock() + max(0.0, float(timeout_s))
    while True:
        reply = find_reply(output_root, thread_id=thread_id, in_reply_to=in_reply_to)
        if reply is not None:
            return reply
        if clock() >= deadline:
            return None
        sleep(max(0.0, float(poll_s)))


def ack(output_root: str, *, thread_id: str, decision_key: str, note: str = "") -> Dict[str, Any]:
    """Acknowledge a reviewer reply. Idempotent: a restart replaying the same ACK is a store no-op."""
    return record_ack(output_root, thread_id=thread_id, decision_key=decision_key,
                      note=note or "decision received")


def worker_status(output_root: str, packet: Dict[str, Any]) -> Dict[str, Any]:
    """Where a fresh/resumed writer must continue from, derived from persisted thread evidence — so it
    never repeats a completed phase."""
    phase = phase_for_packet(output_root, packet)
    return {"phase": phase, "next_action": _NEXT_ACTION.get(phase, _NEXT_ACTION[PHASE_NEW])}
