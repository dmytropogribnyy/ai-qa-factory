"""Assembly + worker-side helpers for the Direct Collaboration Driver (Issue #14).

Thin, testable glue that the ``tools/`` CLIs wrap: resolve the current git head, submit worker
envelopes (question / proposal / checkpoint), build a live reviewer driver, and record an
acknowledgement. Keeping this in one module means the launchers are trivial and the wiring is unit
tested without a network.
"""
from __future__ import annotations

import re
import subprocess
from typing import Any, Dict, List, Optional

from core.collaboration.budget import BudgetLedger, BudgetPolicy
from core.collaboration.envelopes import make_envelope
from core.collaboration.reviewer_client import OpenAIReviewerClient, ReviewerClient
from core.collaboration.reviewer_driver import ReviewerDriver
from core.collaboration.session_delivery import (
    ClaudeSessionDelivery,
    SessionDeliveryError,
    SessionRegistry,
)
from core.collaboration.store import CollaborationStore, CollaborationStoreError

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_DELIVERABLE = {"RESPONSE", "CRITIQUE", "RECOMMENDATION", "DECISION"}
_DEFAULT_REGISTRY = ".aiqa_collab_sessions.json"


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


def resolve_branch_head(repo_root: str, branch: str) -> str:
    """Read-only head of a specific local branch (P1 — real per-branch matching, not global HEAD)."""
    ref = str(branch or "").strip()
    if not ref or not re.fullmatch(r"[0-9A-Za-z._/-]{1,200}", ref):
        return resolve_git_head(repo_root)
    try:
        proc = subprocess.run(["git", "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}"],
                              cwd=repo_root, capture_output=True, text=True, timeout=15, check=False)
        head = (proc.stdout or "").strip().lower()
        return head if _FULL_SHA.fullmatch(head) else resolve_git_head(repo_root)
    except (OSError, subprocess.SubprocessError):
        return resolve_git_head(repo_root)


def build_reviewer_driver(output_root: str, repo_root: str = ".", *,
                          reviewer_client: Optional[ReviewerClient] = None,
                          policy: Optional[BudgetPolicy] = None,
                          reviewer_id: str = "gpt-reviewer") -> ReviewerDriver:
    from core.collaboration.manifest import build_trusted_manifest
    store = CollaborationStore(output_root)
    budget = BudgetLedger(output_root, policy=policy or BudgetPolicy())
    client = reviewer_client or OpenAIReviewerClient()
    return ReviewerDriver(store, budget, client, repo_root=repo_root,
                          head_resolver=lambda: resolve_git_head(repo_root), reviewer_id=reviewer_id,
                          manifest_provider=lambda sha: build_trusted_manifest(output_root, repo_root, sha))


class CollaborationCycle:
    """One bounded autonomous tick that CONNECTS the reviewer and delivery (Issue #14 P0-1): review a
    pending request, then deliver every undelivered reviewer reply into its bound Claude session. Both
    halves are idempotent (review dedup via open-requests; delivery dedup via the success marker), so a
    restart never duplicates an API review or a Claude resume. It observes ACKs but never blocks on them.
    """

    def __init__(self, output_root: str, repo_root: str = ".", *,
                 reviewer_client: Optional[ReviewerClient] = None,
                 policy: Optional[BudgetPolicy] = None, reviewer_id: str = "gpt-reviewer",
                 registry: Optional[SessionRegistry] = None,
                 delivery: Optional[ClaudeSessionDelivery] = None) -> None:
        self._store = CollaborationStore(output_root)
        self._driver = build_reviewer_driver(output_root, repo_root, reviewer_client=reviewer_client,
                                              policy=policy, reviewer_id=reviewer_id)
        self._registry = registry or SessionRegistry(_DEFAULT_REGISTRY)
        self._delivery = delivery or ClaudeSessionDelivery(
            self._registry, output_root, workspace=repo_root,
            head_resolver=lambda: resolve_git_head(repo_root))

    def _deliver_pending(self) -> List[Dict[str, Any]]:
        results: List[Dict[str, Any]] = []
        for thread_id in self._store.threads():
            if self._registry.session_for(thread_id) is None:
                continue                                   # no bound session -> nothing to wake
            acked = {str(m.get("in_reply_to", "")) for m in self._store.thread(thread_id)["messages"]
                     if m.get("kind") == "ACKNOWLEDGEMENT"}
            for m in self._store.thread(thread_id)["messages"]:
                if m.get("kind") not in _DELIVERABLE:
                    continue
                try:
                    res = self._delivery.deliver(m)
                except SessionDeliveryError as exc:
                    res = {"status": "error", "reason": str(exc)}
                res["acked"] = m.get("idempotency_key") in acked
                # A terminal delivery failure must become a DURABLE owner-visible escalation, so the
                # Dashboard can never show IDLE while delivery is dead (P1).
                if res.get("status") in ("failed_exhausted", "stale", "error"):
                    self._escalate_delivery(thread_id, m, res)
                if res.get("status") != "already_delivered":
                    results.append({"message_id": m.get("message_id"), **res})
        return results

    def _escalate_delivery(self, thread_id: str, reply: Dict[str, Any], res: Dict[str, Any]) -> None:
        detail = (res.get("reason") or res.get("error")
                  or (f"branch moved to {res.get('current_head', '')[:12]}" if res.get("status") == "stale"
                      else f"attempts={res.get('attempts', '')}"))
        try:
            self._store.append(make_envelope(
                kind="NEEDS_OWNER", thread_id=thread_id, actor="collab-driver",
                body=f"terminal delivery failure ({res.get('status')}) for reply "
                     f"{reply.get('message_id')}: {detail}",
                in_reply_to=str(reply.get("idempotency_key", "")),
                requested_next_action="owner must resolve delivery"))
        except CollaborationStoreError:
            pass                                           # idempotent: identical escalation dedupes

    def tick(self) -> Dict[str, Any]:
        review = self._driver.process_once()
        deliveries = self._deliver_pending()
        delivery_terminal = any(d.get("status") in ("failed_exhausted", "stale", "error")
                                for d in deliveries)
        owner_action = (review["status"] in ("needs_owner", "blocked", "stale", "schema_error")
                        or delivery_terminal)
        return {"review": review, "deliveries": deliveries, "owner_action": owner_action,
                "health": self._driver.health()}

    def run(self, *, max_iterations: int = 500) -> List[Dict[str, Any]]:
        """Bounded loop (never unlimited): stop when idle OR on any fail-closed / terminal delivery."""
        ticks: List[Dict[str, Any]] = []
        for _ in range(max(1, max_iterations)):
            outcome = self.tick()
            ticks.append(outcome)
            if outcome["owner_action"] or outcome["review"]["status"] == "idle":
                break
        return ticks
