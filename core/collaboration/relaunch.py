"""Session-independent writer relaunch (Issue #17).

The task-managed supervisor calls ``relaunch_once`` each cycle. It picks the next pending product
packet, atomically claims it, and launches a bounded Claude writer (the existing ``ClaudeCodeWorker``
adapter — a fresh ``claude`` process, NOT the interactive session) to do the next step. A failed launch
(most importantly: an exhausted Claude quota) releases the packet back to pending, so the next cycle is
a free no-op while blocked and resumes automatically once quota returns — and a persisted packet means
a brand-new session continues exactly where the last one stopped. No second orchestrator or state store.
"""
from __future__ import annotations

from typing import Any, Callable, Dict

from core.collaboration.product_packet import ProductPacketStore
from core.orchestration.claude_worker import WorkOrder

# A product writer needs to read/edit/write source and run tests, git and the collab CLIs.
_WRITER_TOOLS = ["Edit", "Write", "Read", "Bash"]


def build_default_order(packet: Dict[str, Any], *, max_budget_usd: float = 2.0,
                        timeout_s: int = 1800) -> WorkOrder:
    return WorkOrder(
        project_id=packet["packet_id"],
        objective=(packet.get("next_action") or packet.get("objective") or "").strip(),
        acceptance=packet.get("acceptance", ""),
        allowed_tools=list(_WRITER_TOOLS),
        max_budget_usd=max_budget_usd,
        timeout_s=timeout_s,
        session_id=str(packet.get("writer_session", "")))


def relaunch_once(store: ProductPacketStore, worker: Any, *, workspace: str = ".",
                  build_order: Callable[[Dict[str, Any]], WorkOrder] = build_default_order,
                  resume: bool = True) -> Dict[str, Any]:
    """One relaunch cycle: claim the next pending packet and launch a bounded writer on it."""
    # One writer at a time: never launch a second while a packet is in progress.
    if any(p.get("status") == "in_progress" for p in store.list()):
        return {"status": "writer_busy"}
    pending = store.next_pending()
    if not pending:
        return {"status": "idle"}
    claimed = store.claim(pending["packet_id"])
    if claimed is None:
        return {"status": "claimed_elsewhere"}          # a concurrent cycle already took it

    pid = claimed["packet_id"]
    order = build_order(claimed)
    resume_session = str(claimed.get("writer_session", "")) if (resume and claimed.get("attempts", 0) > 1) else ""
    try:
        result = worker.run(order, workspace, resume_session=resume_session)
    except Exception as exc:  # noqa: BLE001 - a launch failure must release the packet, never crash
        store.update(pid, status="pending", last_result=f"launch error: {type(exc).__name__}: {exc}")
        return {"status": "launch_error", "retry": True, "packet_id": pid}

    session_id = str(getattr(result, "session_id", "") or "")
    if bool(getattr(result, "ok", False)):
        store.update(pid, status="done", writer_session=session_id or claimed.get("writer_session", ""),
                     last_result="writer completed the step")
        return {"status": "launched", "ok": True, "packet_id": pid}
    # Not ok (e.g., exhausted quota / transient failure): release for a free retry next cycle.
    reason = str(getattr(result, "reason", "") or "writer not ok")
    store.update(pid, status="pending", writer_session=session_id or claimed.get("writer_session", ""),
                 last_result=f"retry: {reason}"[:400])
    return {"status": "launched", "ok": False, "retry": True, "packet_id": pid, "reason": reason}


def summary(store: ProductPacketStore) -> Dict[str, Any]:
    packets = store.list()
    by_status: Dict[str, int] = {}
    for p in packets:
        by_status[p.get("status", "?")] = by_status.get(p.get("status", "?"), 0) + 1
    active = next((p for p in packets if p.get("status") == "in_progress"), None)
    nxt = next((p for p in packets if p.get("status") == "pending"), None)
    return {"total": len(packets), "by_status": by_status,
            "active": active, "next_pending": nxt}
