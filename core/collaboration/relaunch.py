"""Session-independent writer relaunch (Issue #17).

The task-managed supervisor calls ``relaunch_once`` each cycle. It recovers any orphaned claim, picks
the next *eligible* pending product packet, atomically claims it (attributable owner + lease), and
launches a bounded Claude writer (the existing ``ClaudeCodeWorker`` adapter — a fresh ``claude``
process, NOT the interactive session) to do the next protocol step. A persisted packet means a
brand-new session continues exactly where the last one stopped. No second orchestrator or state store.

Three truth/recovery guarantees close the GPT NO-GO on PR #19 (Issue #17):

- **Completion is evidence-gated (P0-1).** A successful writer process is NOT a completed product
  packet. ``done`` is set only when the packet's bound Direct-Driver thread evidences the exact-SHA GO
  boundary (see ``packet_phase``); otherwise the loop keeps driving the canonical protocol.
- **Crashed writers are recovered (P0-2).** A claim carries an owner + lease; a writer that dies after
  claiming never freezes the queue — an expired lease is reclaimed to pending, resumable, next cycle.
- **Failures back off and cap (P0-3).** A transient/quota failure sets ``next_retry_at`` (exponential
  to a cap) so the next cycles are FREE no-ops until then — never a per-interval relaunch; a hard total
  launch cap turns any runaway into a durable, owner-visible ``needs_owner`` stop, surfaced in /collab.
"""
from __future__ import annotations

import os
import socket
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional

from core.collaboration.packet_phase import is_complete, phase_for_packet
from core.collaboration.product_packet import ProductPacketStore, _iso, _now_dt
from core.orchestration.claude_worker import WorkOrder

# A product writer needs to read/edit/write source and run tests, git and the collab CLIs.
_WRITER_TOOLS = ["Edit", "Write", "Read", "Bash"]

# P0-3: bounded, durable retry policy. A transient/quota failure backs off (a free no-op until the
# retry time — never a per-interval Claude relaunch) with exponential growth to a cap; a hard total
# launch cap turns an otherwise endless loop into a durable, owner-visible NEEDS_OWNER stop.
# The total launch cap must leave headroom for the multi-step canonical protocol (propose ->
# ack/implement/checkpoint -> read decision is several ok steps) plus a few transient retries, while
# still turning any runaway into a durable stop. Conservative + configurable per deployment.
RELAUNCH_MAX_ATTEMPTS = 8
BACKOFF_BASE_S = 60
BACKOFF_CAP_S = 3600


def _backoff_seconds(attempts: int) -> int:
    return int(min(BACKOFF_CAP_S, BACKOFF_BASE_S * (2 ** (max(1, int(attempts)) - 1))))


def _owner_token() -> str:
    """A best-effort, attributable owner id for a claim (P0-2) — not a security boundary."""
    try:
        host = socket.gethostname()
    except OSError:
        host = "?"
    return f"pid-{os.getpid()}@{host}"


# P0-1: the writer must be told that a passing process run is NOT completion — the canonical
# Direct-Driver protocol on the packet's bound thread is, and it completes only on an exact-SHA GO.
_PROTOCOL = (
    "Follow the canonical Direct-Driver protocol on collaboration thread '{tid}' (thread_id == this "
    "packet id): submit a PROPOSAL for your plan, wait for the GPT reviewer's response and ACK it, then "
    "implement with tests and real evidence and submit an exact-SHA CHECKPOINT. This packet is complete "
    "ONLY when the reviewer records a GO decision on that exact head SHA — a successful process exit is "
    "not completion.")


def build_default_order(packet: Dict[str, Any], *, max_budget_usd: float = 2.0,
                        timeout_s: int = 1800) -> WorkOrder:
    tid = str(packet.get("thread_id") or packet.get("packet_id") or "").strip()
    step = (packet.get("next_action") or packet.get("objective") or "").strip()
    objective = f"{step}\n\n{_PROTOCOL.format(tid=tid)}"
    acceptance = ((packet.get("acceptance", "") or "").strip()
                  + f"\n\nCompletion boundary: an exact-SHA GPT GO on the CHECKPOINT for thread '{tid}' "
                    "(proposal reviewed + ACKed first).").strip()
    return WorkOrder(
        project_id=packet["packet_id"],
        objective=objective,
        acceptance=acceptance,
        allowed_tools=list(_WRITER_TOOLS),
        max_budget_usd=max_budget_usd,
        timeout_s=timeout_s,
        session_id=str(packet.get("writer_session", "")))


def _handle_not_ok(store: ProductPacketStore, claimed: Dict[str, Any], now: datetime,
                   max_attempts: int, *, reason: str, session_id: str,
                   status_key: str) -> Dict[str, Any]:
    """A failed launch (exhausted quota, transient error, or a launch exception) follows one durable
    path (P0-3): back off until a computed retry time, or — once the total launch cap is reached —
    escalate to a durable, owner-visible NEEDS_OWNER stop. Never an instant per-interval relaunch."""
    pid = claimed["packet_id"]
    attempts = int(claimed.get("attempts", 0))
    writer_session = session_id or claimed.get("writer_session", "")
    if attempts >= max_attempts:
        store.update(pid, status="needs_owner", writer_session=writer_session, next_retry_at="",
                     last_result=f"exhausted {attempts} attempts: {reason}"[:400])
        return {"status": "needs_owner", "packet_id": pid, "reason": reason, "attempts": attempts}
    retry_at = _iso(now + timedelta(seconds=_backoff_seconds(attempts)))
    store.update(pid, status="pending", writer_session=writer_session, next_retry_at=retry_at,
                 last_result=f"retry: {reason}"[:400])
    return {"status": status_key, "ok": False, "retry": True, "packet_id": pid,
            "reason": reason, "next_retry_at": retry_at}


def _handle_incomplete(store: ProductPacketStore, claimed: Dict[str, Any], now: datetime,
                       max_attempts: int, *, phase: str, session_id: str) -> Dict[str, Any]:
    """An ok writer step that did NOT reach the GO boundary (P0-1): record the evidenced phase and
    continue on a bounded, capped cadence — a short fixed wait (so the reviewer can respond before the
    next step), and a durable NEEDS_OWNER stop once the total launch cap is reached. Never a false done."""
    pid = claimed["packet_id"]
    attempts = int(claimed.get("attempts", 0))
    writer_session = session_id or claimed.get("writer_session", "")
    if attempts >= max_attempts:
        store.update(pid, status="needs_owner", phase=phase, writer_session=writer_session,
                     next_retry_at="",
                     last_result=f"did not reach GO within {attempts} launches (phase={phase})")
        return {"status": "needs_owner", "packet_id": pid, "phase": phase, "attempts": attempts}
    retry_at = _iso(now + timedelta(seconds=BACKOFF_BASE_S))
    store.update(pid, status="pending", phase=phase, writer_session=writer_session,
                 next_retry_at=retry_at,
                 last_result=f"writer step ok; awaiting protocol completion (phase={phase})")
    return {"status": "launched", "ok": True, "complete": False, "packet_id": pid,
            "phase": phase, "next_retry_at": retry_at}


def relaunch_once(store: ProductPacketStore, worker: Any, *, workspace: str = ".",
                  build_order: Callable[[Dict[str, Any]], WorkOrder] = build_default_order,
                  resume: bool = True, now: Optional[datetime] = None, owner: Optional[str] = None,
                  max_attempts: int = RELAUNCH_MAX_ATTEMPTS,
                  completion_check: Optional[Callable[[Dict[str, Any]], str]] = None) -> Dict[str, Any]:
    """One relaunch cycle: recover any orphaned claim, then claim the next eligible pending packet and
    launch a bounded writer on it. Free no-op while idle, backing off, or blocked. Completion is gated
    on persisted protocol evidence (``completion_check``), never on the worker return code (P0-1)."""
    dt = _now_dt(now)
    check = completion_check or (lambda pkt: phase_for_packet(store.output_root, pkt))
    # P0-2: reclaim any claim left behind by a dead writer BEFORE the single-writer / eligibility checks,
    # so a crashed run never freezes the queue at writer_busy forever.
    store.recover_orphaned_claims(now=dt)
    # One writer at a time: never launch a second while a packet is genuinely in progress.
    if any(p.get("status") == "in_progress" for p in store.list()):
        return {"status": "writer_busy"}
    pending = store.next_pending(now=dt)
    if not pending:
        # Distinguish "nothing to do" from "waiting out a backoff" so /collab tells the truth (P0-3).
        waiting = any(p.get("status") == "pending" for p in store.list())
        return {"status": "backoff" if waiting else "idle"}
    claimed = store.claim(pending["packet_id"], owner=owner or _owner_token(), now=dt)
    if claimed is None:
        return {"status": "claimed_elsewhere"}          # a concurrent cycle already took it

    pid = claimed["packet_id"]
    order = build_order(claimed)
    resume_session = str(claimed.get("writer_session", "")) if (resume and claimed.get("attempts", 0) > 1) else ""
    try:
        result = worker.run(order, workspace, resume_session=resume_session)
    except Exception as exc:  # noqa: BLE001 - a launch failure must release the packet, never crash
        return _handle_not_ok(store, claimed, dt, max_attempts,
                              reason=f"launch error: {type(exc).__name__}: {exc}",
                              session_id="", status_key="launch_error")

    session_id = str(getattr(result, "session_id", "") or "")
    if bool(getattr(result, "ok", False)):
        # P0-1: a successful process is NOT a completed product packet. Mark done ONLY when the bound
        # collaboration thread evidences the exact-SHA GO boundary; otherwise keep driving the protocol.
        phase = str(check(claimed) or "new")
        if is_complete(phase):
            store.update(pid, status="done", phase=phase,
                         writer_session=session_id or claimed.get("writer_session", ""),
                         last_result=f"packet complete: exact-SHA GPT GO (phase={phase})")
            return {"status": "completed", "ok": True, "complete": True, "packet_id": pid,
                    "phase": phase}
        return _handle_incomplete(store, claimed, dt, max_attempts, phase=phase, session_id=session_id)
    # Not ok (e.g., exhausted quota / transient failure): durable backoff or capped escalation (P0-3).
    reason = str(getattr(result, "reason", "") or "writer not ok")
    return _handle_not_ok(store, claimed, dt, max_attempts, reason=reason, session_id=session_id,
                          status_key="launched")


def _packet_view(packet: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Compact, truthful packet view for /collab: phase, attempts, backoff, next action (P0-1/3)."""
    if not packet:
        return None
    return {"packet_id": packet.get("packet_id"), "status": packet.get("status"),
            "phase": packet.get("phase", "new"), "attempts": packet.get("attempts", 0),
            "next_retry_at": packet.get("next_retry_at", ""), "objective": packet.get("objective", ""),
            "last_result": packet.get("last_result", ""), "pr_number": packet.get("pr_number")}


def summary(store: ProductPacketStore) -> Dict[str, Any]:
    packets = store.list()
    by_status: Dict[str, int] = {}
    for p in packets:
        by_status[p.get("status", "?")] = by_status.get(p.get("status", "?"), 0) + 1
    active = next((p for p in packets if p.get("status") == "in_progress"), None)
    nxt = next((p for p in packets if p.get("status") == "pending"), None)
    needs_owner = [_packet_view(p) for p in packets if p.get("status") == "needs_owner"]
    return {"total": len(packets), "by_status": by_status,
            "active": _packet_view(active), "next_pending": _packet_view(nxt),
            "needs_owner": needs_owner}
