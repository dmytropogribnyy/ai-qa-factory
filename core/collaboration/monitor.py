"""Owner-visible collaboration monitor read model (Issue #14.D).

A pure read over the SAME canonical store (collaboration threads + driver state + budget ledger). It
stores nothing of its own; it derives, per thread, the operator lifecycle state, the current/next
action, the SHA-bound decision and whether it still matches the live branch head, plus the driver
heartbeat/staleness and spend — so the Dashboard can show one truthful status area without a second
data source. The Dashboard renderer escapes untrusted text; these DTOs carry raw values.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from core.collaboration.budget import BudgetLedger
from core.collaboration.store import CollaborationStore

SCHEMA_VERSION = "collab-monitor/v1"
_TIMELINE_LIMIT = 20

# Latest-message-kind -> (operator state, whose turn, current action, next action).
_REQUEST_STATE = {
    "CHECKPOINT": ("REVIEWING", "gpt-reviewer", "reviewing checkpoint", "GO / NO-GO"),
    "QUESTION": ("REVIEWING", "gpt-reviewer", "answering question", "RESPONSE"),
    "PROPOSAL": ("REVIEWING", "gpt-reviewer", "critiquing proposal", "CRITIQUE / RECOMMENDATION"),
}
_REPLY_STATE = {
    "RESPONSE": ("WORKING", "claude-worker", "reading reviewer response", "ACKNOWLEDGEMENT"),
    "CRITIQUE": ("WORKING", "claude-worker", "addressing critique", "revise or ACKNOWLEDGEMENT"),
    "RECOMMENDATION": ("WORKING", "claude-worker", "applying recommendation", "ACKNOWLEDGEMENT"),
}


def _parse(ts: str) -> Optional[datetime]:
    try:
        return datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None


class CollaborationMonitor:
    def __init__(self, output_root: str, *, head_resolver: Optional[Callable[[], str]] = None,
                 clock: Optional[Callable[[], str]] = None, stale_seconds: int = 120) -> None:
        self._out = output_root
        self._store = CollaborationStore(output_root)
        self._budget = BudgetLedger(output_root)
        # head_resolver(branch) -> that branch's head; per-thread matching, not one global HEAD.
        # Accept both branch-aware and legacy zero-arg resolvers.
        self._head_resolver = head_resolver or (lambda branch="": "")
        self._clock = clock or (lambda: datetime.now(timezone.utc).isoformat(timespec="seconds"))
        self._stale_seconds = stale_seconds
        self._state_path = Path(output_root) / "_review_relay" / "collab_driver" / "state.json"

    def _resolve_head(self, branch: str) -> str:
        try:
            return str(self._head_resolver(branch) or "")
        except TypeError:
            return str(self._head_resolver() or "")   # legacy zero-arg resolver

    def _driver_state(self) -> Dict[str, Any]:
        if self._state_path.exists():
            try:
                data = json.loads(self._state_path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
            except (OSError, ValueError):
                pass
        return {"stage": "IDLE", "processed": 0, "last_error": "", "updated_at": ""}

    def _driver(self) -> Dict[str, Any]:
        state = self._driver_state()
        daily = self._budget.usage("")
        stale = False
        beat = _parse(state.get("updated_at", ""))
        now = _parse(self._clock())
        if beat and now:
            stale = (now - beat).total_seconds() > self._stale_seconds
        return {"stage": state.get("stage", "IDLE"), "processed": state.get("processed", 0),
                "last_error": state.get("last_error", ""), "heartbeat": state.get("updated_at", ""),
                "stale": stale, "model": state.get("model", ""),
                "reasoning_effort": state.get("reasoning_effort", ""),
                "budget": {"daily_calls": daily["daily_calls"], "daily_usd": daily["daily_usd"],
                           "daily_tokens": daily["daily_tokens"],
                           "cap_calls": self._budget.policy.daily_calls,
                           "cap_usd": self._budget.policy.daily_usd}}

    def _thread_view(self, thread_id: str) -> Dict[str, Any]:
        messages = self._store.thread(thread_id)["messages"]
        latest = messages[-1] if messages else {}
        # Derive the LATEST causal cycle, not the first request in the thread.
        request = next((m for m in reversed(messages) if m.get("kind") in _REQUEST_STATE), {})
        decision = next((m for m in reversed(messages) if m.get("kind") == "DECISION"), {})
        replies = [m for m in messages if m.get("kind") in _REPLY_STATE or m.get("kind") == "DECISION"]
        latest_reply = replies[-1] if replies else {}
        # An ACK counts only when it binds to the LATEST reply/decision — not "any old ACK".
        ack_targets = {str(m.get("in_reply_to", "")) for m in messages
                       if m.get("kind") == "ACKNOWLEDGEMENT"}
        acked = bool(latest_reply) and latest_reply.get("idempotency_key") in ack_targets
        # Head is matched per THREAD/branch, not against one process-wide checkout HEAD.
        branch = request.get("branch") or latest.get("branch") or ""
        current_head = self._resolve_head(branch).lower()

        state, actor, action, nxt = "WORKING", "claude-worker", "in progress", ""
        kind = latest.get("kind", "")
        if kind == "NEEDS_OWNER":
            state, actor, action, nxt = "NEEDS_OWNER", "owner", latest.get("body", ""), "owner decision"
        elif kind == "ACKNOWLEDGEMENT":
            state, actor, action, nxt = "DONE", "claude-worker", "cycle complete", "next slice"
        elif kind == "DECISION":
            verdict = decision.get("verdict", "")
            if verdict == "GO":
                state, action, nxt = "WAITING_FOR_CI", "GO received", "merge after green CI"
            elif verdict == "NO-GO":
                state, action, nxt = "FIXING", "addressing NO-GO blockers", "fix + resubmit checkpoint"
            else:
                state, action, nxt = "WORKING", "reviewing COMMENT", "continue"
            actor = "claude-worker"
        elif kind in _REPLY_STATE:
            state, actor, action, nxt = _REPLY_STATE[kind]
        elif kind in _REQUEST_STATE:
            state, actor, action, nxt = _REQUEST_STATE[kind]

        reviewed = str(decision.get("reviewed_sha", "")).lower()
        head = str(current_head or "").lower()
        matches = bool(reviewed) and bool(head) and reviewed == head
        stale_head = bool(reviewed) and bool(head) and reviewed != head
        ci_refs = list(request.get("evidence_refs", []) or latest.get("evidence_refs", []))
        timeline = [{"kind": m.get("kind"), "actor": m.get("actor"), "at": m.get("created_at"),
                     "message_id": m.get("message_id")} for m in messages][-_TIMELINE_LIMIT:]
        return {
            "thread_id": thread_id, "state": state, "actor": actor,
            "current_action": action, "next_action": nxt,
            "branch": request.get("branch", latest.get("branch", "")),
            "pr_number": request.get("pr_number", latest.get("pr_number")),
            "head_sha": request.get("head_sha", latest.get("head_sha", "")),
            "decision": decision.get("verdict", ""), "reviewed_sha": reviewed,
            "reviewed_sha_matches_head": matches, "stale_head": stale_head, "acked": acked,
            "last_event": {"kind": latest.get("kind"), "at": latest.get("created_at")},
            "ci_refs": ci_refs, "timeline": timeline,
        }

    def _delivery(self) -> Dict[str, Any]:
        """Honest delivery telemetry + billing source (invariant 9): how the local Claude worker that
        receives decisions is actually paid for (Max/Pro subscription allocation vs API credits)."""
        from core.collaboration.session_delivery import billing_mode
        base = Path(self._out) / "_review_relay" / "collab_delivery"
        delivered = 0
        cost = 0.0
        model = ""
        if base.is_dir():
            for path in base.glob("*.json"):
                if path.name.endswith((".decision.json", ".attempts.json")):
                    continue
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    continue
                if not isinstance(data, dict) or "delivered_at" not in data:
                    continue
                delivered += 1
                cost += float(data.get("claude_cost_usd") or 0.0)
                model = data.get("claude_model") or model
        bm = billing_mode()
        return {"delivered": delivered, "claude_cost_usd": round(cost, 6), "claude_model": model,
                "billing_source": bm.get("source"), "billing_plan": bm.get("plan", "")}

    def snapshot(self) -> Dict[str, Any]:
        head = self._resolve_head("").lower()             # representative current-branch head
        driver = self._driver()
        delivery = self._delivery()
        threads = [self._thread_view(t) for t in self._store.threads()]
        threads.sort(key=lambda t: t.get("thread_id", ""))
        needs_owner = (driver["stage"] == "NEEDS_OWNER"
                       or any(t["state"] == "NEEDS_OWNER" for t in threads))
        counts = {"active": sum(1 for t in threads if t["state"] not in ("DONE", "NEEDS_OWNER")),
                  "needs_owner": sum(1 for t in threads if t["state"] == "NEEDS_OWNER"),
                  "done": sum(1 for t in threads if t["state"] == "DONE")}
        return {"schema": SCHEMA_VERSION, "generated_at": self._clock(), "current_head": head,
                "driver": driver, "delivery": delivery, "owner_action_required": needs_owner,
                "threads": threads, "counts": counts}
