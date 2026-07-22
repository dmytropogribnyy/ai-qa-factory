"""Session-independent writer relaunch (Issue #17).

The task-managed supervisor calls ``relaunch_once`` each cycle. It recovers any orphaned claim, picks
the next *eligible* pending product packet, atomically claims it (attributable owner + lease + fencing
token), and launches a bounded Claude writer (the existing ``ClaudeCodeWorker`` adapter — a fresh
``claude`` process, NOT the interactive session) to do the next protocol step. A persisted packet means
a brand-new session continues exactly where the last one stopped. No second orchestrator or state store.

Truth/recovery guarantees (Issue #17, closing the GPT NO-GO on PR #19):

- **Completion is evidence-gated (P0-1).** A successful writer process is NOT a completed product
  packet. ``done`` is set only when the packet's bound Direct-Driver thread evidences the exact-SHA GO
  boundary (see ``packet_phase``); otherwise the loop keeps driving the canonical protocol.
- **Exactly one writer (P0-A).** A live heartbeat renews the claim while ``worker.run()`` is alive, and
  every heartbeat/terminal update is gated on the current ``claim_token`` — a stale owner or a reused
  PID is a no-op. Recovery reclaims only when the lease is expired AND the owner process tree is provably
  dead (``recover_orphaned_claims``); an expired lease alone never spawns a second writer.
- **Failures back off and cap (P0-3).** A transient/quota failure sets ``next_retry_at`` (exponential to
  a cap) so the next cycles are FREE no-ops; a hard total launch cap turns any runaway into a durable,
  owner-visible ``needs_owner`` stop. A REAL-dollar spend cap trips only on actually-charged API dollars,
  never on subscription token-equivalent usage (honest billing).
"""
from __future__ import annotations

import os
import socket
import threading
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, Optional

from core.collaboration.packet_phase import is_complete, phase_for_packet
from core.collaboration.process_liveness import descendant_pids, local_host
from core.collaboration.product_packet import DEFAULT_LEASE_SECONDS, ProductPacketStore, _iso, _now_dt
from core.orchestration.claude_worker import WorkOrder

# A product writer needs to read/edit/write source and run tests, git and the collab CLIs.
_WRITER_TOOLS = ["Edit", "Write", "Read", "Bash"]

# P0-3: bounded, durable retry policy (see module docstring).
RELAUNCH_MAX_ATTEMPTS = 8
BACKOFF_BASE_S = 60
BACKOFF_CAP_S = 3600

# P0-A: heartbeat cadence — renew the claim well within the lease while the writer runs. Bounded to a
# sane ceiling with a safe floor so a short test lease still stays fresh and a long lease is not spammed.
HEARTBEAT_MAX_S = 30
HEARTBEAT_MIN_S = 5


def _backoff_seconds(attempts: int) -> int:
    return int(min(BACKOFF_CAP_S, BACKOFF_BASE_S * (2 ** (max(1, int(attempts)) - 1))))


def _owner_token() -> str:
    """A best-effort, attributable owner id for a claim (P0-2) — not a security boundary."""
    try:
        host = socket.gethostname()
    except OSError:
        host = "?"
    return f"pid-{os.getpid()}@{host}"


def _heartbeat_interval(lease_seconds: int) -> float:
    return float(max(HEARTBEAT_MIN_S, min(HEARTBEAT_MAX_S, int(lease_seconds) / 3)))


def _heartbeat_loop(store: ProductPacketStore, packet_id: str, claim_token: str, lease_seconds: int,
                    stop: threading.Event) -> None:
    """Renew the claim's lease + refresh the FULL owner process subtree (recursively — a reparented
    grandchild survivor was the P0-A gap) each interval while the writer genuinely runs. The interval is
    well within the lease (<= lease/3), so the tree is captured long before the lease could expire; the
    incomplete-capture window before the first tick is covered fail-closed by ``owner_liveness`` (a lone
    recorded pid is never proof of tree death). Stops as soon as ``stop`` is set (the writer returned) or
    the claim is lost/taken over (heartbeat no-op)."""
    interval = _heartbeat_interval(lease_seconds)
    while not stop.wait(interval):
        try:
            pids = [os.getpid(), *descendant_pids(os.getpid())]
            if store.heartbeat(packet_id, claim_token=claim_token, lease_seconds=lease_seconds,
                               owner_pids=pids) is None:
                return                                   # claim gone / superseded -> stop heartbeating
        except Exception:                                # noqa: BLE001 - a heartbeat must never crash the run
            return


def _billing_source(env: Optional[Dict[str, str]] = None) -> str:
    """How the WRITER subprocess is billed: the worker strips the API key by default (subscription),
    unless ``AIQA_WORKER_USE_API`` is set (real Anthropic API dollars). Mirrors
    ``ClaudeCodeWorker._subprocess_env``."""
    env = env if env is not None else dict(os.environ)
    use_api = str(env.get("AIQA_WORKER_USE_API", "")).strip().lower() in ("1", "true", "yes", "on")
    return "api_credits" if use_api else "subscription"


# P0-1 protocol contract embedded in the writer's Work Order (unchanged).
_PROTOCOL = (
    "You are a session-independent writer; a successful process exit is NOT completion. Follow the "
    "canonical Direct-Driver protocol on collaboration thread '{tid}' (thread_id == this packet id): "
    "submit a PROPOSAL of your plan, wait for the GPT reviewer's response and ACK it, implement with "
    "tests and real evidence, then submit an exact-SHA CHECKPOINT. Drive it with the pull-first worker "
    "CLI 'tools/collab_worker.py' (subcommands proposal / wait --in-reply-to <key> / ack --decision-key "
    "<key> / checkpoint / status), always with --thread '{tid}' --output-root <controller outputs> "
    "--branch <this worktree branch>; the exact commands are in the next action above. proposal and "
    "checkpoint are restart-idempotent and 'wait' blocks free on the local store — never re-submit a "
    "request you already sent. This packet is complete ONLY when the reviewer records a GO decision on "
    "that exact head SHA.")


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


def _cap_reason(attempts: int, launch_cap: int, charged: float, max_total_usd: float) -> str:
    """Which conservative bound (if any) has been reached — the total launch cap (usage/quota bound,
    always in force) or the total REAL-dollar spend cap (only actually-charged API dollars, never
    subscription token-equivalent usage). Empty string means neither: keep going."""
    if attempts >= launch_cap:
        return f"launch cap {launch_cap} reached"
    if max_total_usd and charged >= max_total_usd:
        return f"API spend cap ${max_total_usd:.2f} reached (charged ${charged:.2f})"
    return ""


def _resolve(store: ProductPacketStore, claimed: Dict[str, Any], **changes: Any) -> Optional[Dict[str, Any]]:
    """Token-gated terminal write by THIS claim owner (P0-A): a no-op if a newer claim has taken over."""
    return store.resolve(claimed["packet_id"], claim_token=str(claimed.get("claim_token", "")), **changes)


def _billing_changes(source: str, usage: float, charged: float) -> Dict[str, Any]:
    return {"usage_usd_equiv": round(usage, 6), "actual_charged_usd": round(charged, 6),
            "billing_source": source}


def _handle_not_ok(store: ProductPacketStore, claimed: Dict[str, Any], now: datetime, launch_cap: int,
                   *, reason: str, session_id: str, status_key: str, usage: float, charged: float,
                   source: str, max_total_usd: float) -> Dict[str, Any]:
    """A failed launch (exhausted quota, transient error, or a launch exception) follows one durable
    path (P0-3): back off until a computed retry time, or — once a conservative bound is reached
    (launch cap OR real-dollar spend cap) — escalate to a durable, owner-visible NEEDS_OWNER stop."""
    pid = claimed["packet_id"]
    attempts = int(claimed.get("attempts", 0))
    writer_session = session_id or claimed.get("writer_session", "")
    bill = _billing_changes(source, usage, charged)
    cap = _cap_reason(attempts, launch_cap, charged, max_total_usd)
    if cap:
        _resolve(store, claimed, status="needs_owner", writer_session=writer_session, next_retry_at="",
                 last_result=f"stopped ({cap}); last: {reason}"[:400], **bill)
        return {"status": "needs_owner", "packet_id": pid, "reason": reason, "attempts": attempts,
                **bill}
    retry_at = _iso(now + timedelta(seconds=_backoff_seconds(attempts)))
    _resolve(store, claimed, status="pending", writer_session=writer_session, next_retry_at=retry_at,
             last_result=f"retry: {reason}"[:400], **bill)
    return {"status": status_key, "ok": False, "retry": True, "packet_id": pid,
            "reason": reason, "next_retry_at": retry_at, **bill}


def _handle_incomplete(store: ProductPacketStore, claimed: Dict[str, Any], now: datetime,
                       launch_cap: int, *, phase: str, session_id: str, usage: float, charged: float,
                       source: str, max_total_usd: float) -> Dict[str, Any]:
    """An ok writer step that did NOT reach the GO boundary (P0-1): record the evidenced phase and
    continue on a bounded, capped cadence — a short fixed wait, and a durable NEEDS_OWNER stop once a
    conservative bound is reached. Never a false done."""
    pid = claimed["packet_id"]
    attempts = int(claimed.get("attempts", 0))
    writer_session = session_id or claimed.get("writer_session", "")
    bill = _billing_changes(source, usage, charged)
    cap = _cap_reason(attempts, launch_cap, charged, max_total_usd)
    if cap:
        _resolve(store, claimed, status="needs_owner", phase=phase, writer_session=writer_session,
                 next_retry_at="", last_result=f"stopped ({cap}) at phase={phase}; needs owner approval "
                 "to continue", **bill)
        return {"status": "needs_owner", "packet_id": pid, "phase": phase, "attempts": attempts, **bill}
    retry_at = _iso(now + timedelta(seconds=BACKOFF_BASE_S))
    _resolve(store, claimed, status="pending", phase=phase, writer_session=writer_session,
             next_retry_at=retry_at,
             last_result=f"writer step ok; awaiting protocol completion (phase={phase})", **bill)
    return {"status": "launched", "ok": True, "complete": False, "packet_id": pid,
            "phase": phase, "next_retry_at": retry_at, **bill}


def relaunch_once(store: ProductPacketStore, worker: Any, *, workspace: str = ".",
                  build_order: Callable[[Dict[str, Any]], WorkOrder] = build_default_order,
                  resume: bool = True, now: Optional[datetime] = None, owner: Optional[str] = None,
                  max_attempts: int = RELAUNCH_MAX_ATTEMPTS,
                  billing_source: Optional[str] = None,
                  completion_check: Optional[Callable[[Dict[str, Any]], str]] = None) -> Dict[str, Any]:
    """One relaunch cycle: recover any orphaned claim, then claim the next eligible pending packet and
    launch a bounded writer on it under a live heartbeat (P0-A). Free no-op while idle, backing off, or
    blocked. Completion is gated on persisted protocol evidence (``completion_check``), never on the
    worker return code (P0-1)."""
    dt = _now_dt(now)
    check = completion_check or (lambda pkt: phase_for_packet(store.output_root, pkt))
    source = billing_source or _billing_source()
    # P0-A: reclaim only claims whose owner process tree is provably dead (recover_orphaned_claims does
    # the liveness fencing) BEFORE the single-writer / eligibility checks.
    store.recover_orphaned_claims(now=dt)
    # One writer at a time, fail closed: never launch a second while a packet is in progress OR blocked.
    # A `blocked` packet is a claim whose owner liveness is unknowable (host mismatch / incomplete tree
    # capture) — its writer MAY still be alive, so launching another would risk two writers.
    if any(p.get("status") in ("in_progress", "blocked") for p in store.list()):
        return {"status": "writer_busy"}
    pending = store.next_pending(now=dt)
    if not pending:
        waiting = any(p.get("status") == "pending" for p in store.list())
        return {"status": "backoff" if waiting else "idle"}
    lease_seconds = int(pending.get("lease_seconds") or DEFAULT_LEASE_SECONDS)
    claimed = store.claim(pending["packet_id"], owner=owner or _owner_token(), now=dt,
                          lease_seconds=lease_seconds, owner_pids=[os.getpid()], owner_host=local_host())
    if claimed is None:
        return {"status": "claimed_elsewhere"}          # a concurrent cycle already took it

    pid = claimed["packet_id"]
    launch_cap = int(claimed.get("max_launches") or max_attempts)
    max_total_usd = float(claimed.get("max_total_usd") or 0.0)
    prior_usage = float(claimed.get("usage_usd_equiv", 0.0) or 0.0)
    prior_charged = float(claimed.get("actual_charged_usd", 0.0) or 0.0)
    run_workspace = str(claimed.get("workspace_path") or "").strip() or workspace
    order = build_order(claimed)
    resume_session = str(claimed.get("writer_session", "")) if (resume and claimed.get("attempts", 0) > 1) else ""

    # P0-A: keep the claim's lease fresh + owner process tree current while the writer runs, so an
    # expired lease is never mistaken for a dead writer. The heartbeat always stops in finally.
    stop = threading.Event()
    hb = threading.Thread(target=_heartbeat_loop,
                          args=(store, pid, str(claimed.get("claim_token", "")), lease_seconds, stop),
                          daemon=True)
    hb.start()
    try:
        result = worker.run(order, run_workspace, resume_session=resume_session)
    except Exception as exc:  # noqa: BLE001 - a launch failure must release the packet, never crash
        return _handle_not_ok(store, claimed, dt, launch_cap,
                              reason=f"launch error: {type(exc).__name__}: {exc}",
                              session_id="", status_key="launch_error", usage=prior_usage,
                              charged=prior_charged, source=source, max_total_usd=max_total_usd)
    finally:
        stop.set()
        hb.join(timeout=2)

    cost = float(getattr(result, "cost_usd", 0.0) or 0.0)
    usage = prior_usage + cost
    charged = prior_charged + (cost if source == "api_credits" else 0.0)
    session_id = str(getattr(result, "session_id", "") or "")
    if bool(getattr(result, "ok", False)):
        # P0-1: a successful process is NOT a completed product packet. Mark done ONLY when the bound
        # thread evidences the exact-SHA GO boundary; otherwise keep driving the protocol.
        phase = str(check(claimed) or "new")
        if is_complete(phase):
            _resolve(store, claimed, status="done", phase=phase,
                     writer_session=session_id or claimed.get("writer_session", ""),
                     last_result=f"packet complete: exact-SHA GPT GO (phase={phase})",
                     **_billing_changes(source, usage, charged))
            return {"status": "completed", "ok": True, "complete": True, "packet_id": pid,
                    "phase": phase, **_billing_changes(source, usage, charged)}
        return _handle_incomplete(store, claimed, dt, launch_cap, phase=phase, session_id=session_id,
                                  usage=usage, charged=charged, source=source, max_total_usd=max_total_usd)
    reason = str(getattr(result, "reason", "") or "writer not ok")
    return _handle_not_ok(store, claimed, dt, launch_cap, reason=reason, session_id=session_id,
                          status_key="launched", usage=usage, charged=charged, source=source,
                          max_total_usd=max_total_usd)


def _packet_view(packet: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Compact, truthful packet view for /collab: phase, attempts, backoff, one live writer's fencing
    health (claim owner/token/heartbeat/lease), and honest billing split (P0-A / P1)."""
    if not packet:
        return None
    return {"packet_id": packet.get("packet_id"), "status": packet.get("status"),
            "phase": packet.get("phase", "new"), "attempts": packet.get("attempts", 0),
            "next_retry_at": packet.get("next_retry_at", ""), "objective": packet.get("objective", ""),
            "last_result": packet.get("last_result", ""), "pr_number": packet.get("pr_number"),
            "branch": packet.get("branch", ""), "workspace_path": packet.get("workspace_path", ""),
            "billing_source": packet.get("billing_source", ""),
            "usage_usd_equiv": packet.get("usage_usd_equiv", 0.0),
            "actual_charged_usd": packet.get("actual_charged_usd", 0.0),
            "max_total_usd": packet.get("max_total_usd", 0.0),
            "max_launches": packet.get("max_launches", 0),
            "claim_owner": packet.get("claim_owner", ""),
            "owner_pids": packet.get("owner_pids", []),
            "heartbeat_at": packet.get("heartbeat_at", ""),
            "lease_expires_at": packet.get("lease_expires_at", "")}


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
