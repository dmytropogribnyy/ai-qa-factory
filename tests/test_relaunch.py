"""Issue #17 — session-independent writer relaunch cycle."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core.collaboration.product_packet import ProductPacketStore
from core.collaboration.relaunch import (
    BACKOFF_BASE_S,
    RELAUNCH_MAX_ATTEMPTS,
    build_default_order,
    relaunch_once,
    summary,
)

_T0 = datetime(2026, 7, 22, 12, 0, 0, tzinfo=timezone.utc)


class _Worker:
    """Stub bounded worker adapter recording launches and returning a scripted result."""

    def __init__(self, ok=True, session_id="sess-1", reason="", raises=False, cost_usd=0.0):
        self._ok, self._session, self._reason, self._raises = ok, session_id, reason, raises
        self._cost = cost_usd
        self.calls = 0
        self.last_order = None
        self.last_resume = None
        self.last_workspace = None

    def run(self, order, workspace, *, resume_session="", cancel=None):
        self.calls += 1
        self.last_order = order
        self.last_resume = resume_session
        self.last_workspace = workspace
        if self._raises:
            raise RuntimeError("claude not available")
        return type("R", (), {"ok": self._ok, "session_id": self._session, "reason": self._reason,
                              "cost_usd": self._cost})()


def _pkt(store):
    return store.create(objective="Rank Scout findings by commercial value on /scout/target",
                        acceptance="findings ordered by expected value", safety="read-only",
                        next_action="reuse core/scout/priority.py to rank + show confidence")


def test_relaunch_launches_bounded_writer_and_completes_only_on_go(tmp_path):
    store = ProductPacketStore(str(tmp_path))
    p = _pkt(store)
    worker = _Worker(ok=True)
    # P0-1: completion is gated on persisted GO evidence, not the worker return code.
    out = relaunch_once(store, worker, workspace=str(tmp_path), now=_T0,
                        completion_check=lambda pkt: "decided_go")
    assert out["status"] == "completed"
    assert worker.calls == 1
    assert store.get(p["packet_id"])["status"] == "done"
    # The launched WorkOrder reuses the bounded adapter with writer tools + a real budget bound.
    assert "Bash" in worker.last_order.allowed_tools
    assert worker.last_order.max_budget_usd > 0


def test_idle_when_no_pending_packet(tmp_path):
    store = ProductPacketStore(str(tmp_path))
    assert relaunch_once(store, _Worker(), workspace=str(tmp_path))["status"] == "idle"


def test_failed_launch_releases_packet_for_retry(tmp_path):
    # e.g. exhausted Claude quota -> worker not ok -> packet returns to pending (free no-op next cycle).
    store = ProductPacketStore(str(tmp_path))
    p = _pkt(store)
    out = relaunch_once(store, _Worker(ok=False, reason="usage limit reached"),
                        workspace=str(tmp_path))
    assert out["ok"] is False and out["retry"] is True
    assert store.get(p["packet_id"])["status"] == "pending"    # released, will resume after reset


def test_launch_error_is_contained_and_releases_packet(tmp_path):
    store = ProductPacketStore(str(tmp_path))
    p = _pkt(store)
    out = relaunch_once(store, _Worker(raises=True), workspace=str(tmp_path))
    assert out["status"] == "launch_error" and out["retry"] is True
    assert store.get(p["packet_id"])["status"] == "pending"


def test_restart_does_not_relaunch_a_completed_packet(tmp_path):
    store = ProductPacketStore(str(tmp_path))
    _pkt(store)
    worker = _Worker(ok=True)
    go = lambda pkt: "decided_go"  # noqa: E731 - completed via persisted GO evidence
    relaunch_once(store, worker, workspace=str(tmp_path), now=_T0, completion_check=go)      # done
    second = relaunch_once(store, worker, workspace=str(tmp_path), now=_T0 + timedelta(hours=2),
                           completion_check=go)                # simulated restart cycle
    assert second["status"] == "idle"                          # not relaunched
    assert worker.calls == 1                                    # no duplicate writer


def test_ok_run_does_not_complete_a_packet_without_go_evidence(tmp_path):
    # P0-1: a fresh writer that merely exits ok has NOT completed the product packet.
    store = ProductPacketStore(str(tmp_path))
    p = _pkt(store)
    out = relaunch_once(store, _Worker(ok=True), workspace=str(tmp_path), now=_T0,
                        completion_check=lambda pkt: "new")
    assert out["ok"] is True and out.get("complete") is False
    rec = store.get(p["packet_id"])
    assert rec["status"] != "done"                             # not a completed product packet
    assert rec["phase"] == "new"


def test_ok_run_completes_only_on_persisted_exact_sha_go(tmp_path):
    store = ProductPacketStore(str(tmp_path))
    p = _pkt(store)
    out = relaunch_once(store, _Worker(ok=True), workspace=str(tmp_path), now=_T0,
                        completion_check=lambda pkt: "decided_go")
    assert out["status"] == "completed"
    rec = store.get(p["packet_id"])
    assert rec["status"] == "done"
    assert rec["phase"] == "decided_go"


def test_incomplete_ok_run_backs_off_and_caps_to_needs_owner(tmp_path):
    # P0-1 x P0-3: a writer that keeps exiting ok but never reaches GO must neither spin nor falsely
    # complete; it backs off and, at the total launch cap, becomes a durable owner-visible stop.
    store = ProductPacketStore(str(tmp_path))
    p = _pkt(store)
    t = _T0
    for _ in range(RELAUNCH_MAX_ATTEMPTS):
        relaunch_once(store, _Worker(ok=True), workspace=str(tmp_path), now=t,
                      completion_check=lambda pkt: "checkpointed")
        t = t + timedelta(hours=2)
    rec = store.get(p["packet_id"])
    assert rec["status"] == "needs_owner"
    assert rec["phase"] == "checkpointed"


def test_retry_resumes_the_same_writer_session(tmp_path):
    store = ProductPacketStore(str(tmp_path))
    _pkt(store)
    relaunch_once(store, _Worker(ok=False, session_id="sess-x"), workspace=str(tmp_path),
                  now=_T0)                                      # attempt 1 (not ok -> backoff)
    worker2 = _Worker(ok=True, session_id="sess-x")
    relaunch_once(store, worker2, workspace=str(tmp_path),
                  now=_T0 + timedelta(hours=2))                 # past backoff -> attempt 2 resumes
    assert worker2.last_resume == "sess-x"                      # resumed the same writer session


def test_not_ok_sets_durable_backoff_and_free_no_op_until_retry_time(tmp_path):
    # P0-3: a transient/quota failure must not let the supervisor relaunch Claude every interval.
    store = ProductPacketStore(str(tmp_path))
    p = _pkt(store)
    out = relaunch_once(store, _Worker(ok=False, reason="usage limit reached"),
                        workspace=str(tmp_path), now=_T0)
    assert out["ok"] is False and out["retry"] is True
    rec = store.get(p["packet_id"])
    assert rec["status"] == "pending"
    assert rec["next_retry_at"] == (_T0 + timedelta(seconds=BACKOFF_BASE_S)).isoformat(timespec="seconds")
    # A cycle before the retry time launches nothing (free no-op), and truthfully reports backoff.
    worker2 = _Worker(ok=True)
    blocked = relaunch_once(store, worker2, workspace=str(tmp_path), now=_T0 + timedelta(seconds=5))
    assert blocked["status"] == "backoff"
    assert worker2.calls == 0
    # After the retry time it is eligible again.
    worker3 = _Worker(ok=True)
    relaunch_once(store, worker3, workspace=str(tmp_path), now=_T0 + timedelta(hours=2))
    assert worker3.calls == 1


def test_exhausted_attempts_escalate_to_needs_owner(tmp_path):
    # P0-3: a total launch cap turns an endless quota loop into a durable, owner-visible stop.
    store = ProductPacketStore(str(tmp_path))
    p = _pkt(store)
    t = _T0
    for _ in range(RELAUNCH_MAX_ATTEMPTS):
        relaunch_once(store, _Worker(ok=False, reason="usage limit reached"),
                      workspace=str(tmp_path), now=t)
        t = t + timedelta(hours=4)                             # jump past any backoff between attempts
    rec = store.get(p["packet_id"])
    assert rec["status"] == "needs_owner"                      # durable BLOCKED/NEEDS_OWNER, not pending
    assert rec["attempts"] == RELAUNCH_MAX_ATTEMPTS
    # Once escalated it is no longer pending, so no further Claude launch can happen.
    worker = _Worker(ok=False)
    after = relaunch_once(store, worker, workspace=str(tmp_path), now=t)
    assert after["status"] == "idle"
    assert worker.calls == 0


def test_single_writer_no_second_launch_while_one_in_progress(tmp_path):
    store = ProductPacketStore(str(tmp_path))
    _pkt(store)                                            # packet A
    store.create(objective="second packet B")             # packet B pending
    # Manually claim A (simulate an active writer) then attempt a cycle: must not launch a 2nd writer.
    store.claim(store.next_pending()["packet_id"])
    worker = _Worker(ok=True)
    out = relaunch_once(store, worker, workspace=str(tmp_path))
    assert out["status"] == "writer_busy"
    assert worker.calls == 0                               # B was not launched while A is in progress


def test_summary_reports_status_counts(tmp_path):
    store = ProductPacketStore(str(tmp_path))
    _pkt(store)
    s = summary(store)
    assert s["total"] == 1
    assert s["next_pending"] is not None


def test_summary_surfaces_needs_owner_packets(tmp_path):
    # /collab must truthfully surface a capped/escalated packet (P0-3), not silently hide it.
    store = ProductPacketStore(str(tmp_path))
    p = _pkt(store)
    store.update(p["packet_id"], status="needs_owner", last_result="exhausted 8 attempts")
    s = summary(store)
    assert s["by_status"].get("needs_owner") == 1
    assert any(x.get("packet_id") == p["packet_id"] for x in s["needs_owner"])


def test_relaunch_claims_with_packet_lease_seconds(tmp_path):
    # A packet may set a short recovery lease so a killed writer's claim is reclaimed quickly — this is
    # what makes the live kill/resume proof observable instead of waiting out the 45-min default.
    store = ProductPacketStore(str(tmp_path))
    p = _pkt(store)
    store.update(p["packet_id"], lease_seconds=120)
    relaunch_once(store, _Worker(ok=True), workspace=str(tmp_path), now=_T0,
                  completion_check=lambda pkt: "proposed")
    exp = datetime.fromisoformat(store.get(p["packet_id"])["lease_expires_at"])
    assert (exp - _T0).total_seconds() == 120


def test_writer_runs_in_packet_workspace_path_when_set(tmp_path):
    # GPT isolation requirement: the writer runs in the packet's own worktree, never the controller repo.
    store = ProductPacketStore(str(tmp_path))
    p = _pkt(store)
    store.update(p["packet_id"], workspace_path="/isolated/worktree",
                 branch="feat/scout-target-confidence", base_sha="deadbeef")
    worker = _Worker(ok=True)
    relaunch_once(store, worker, workspace=str(tmp_path), now=_T0,
                  completion_check=lambda pkt: "decided_go")
    assert worker.last_workspace == "/isolated/worktree"        # isolated, not the controller workspace


def test_packet_max_launches_overrides_module_cap(tmp_path):
    # GPT money-bound: a conservative per-packet launch cap escalates before the module default (8).
    store = ProductPacketStore(str(tmp_path))
    p = _pkt(store)
    store.update(p["packet_id"], max_launches=2)
    t = _T0
    for _ in range(2):
        relaunch_once(store, _Worker(ok=False, reason="quota"), workspace=str(tmp_path), now=t)
        t = t + timedelta(hours=2)
    rec = store.get(p["packet_id"])
    assert rec["status"] == "needs_owner" and rec["attempts"] == 2


def test_real_dollar_cap_escalates_only_on_actually_charged_api_spend(tmp_path):
    # GPT P1 money-bound: the REAL-dollar cap trips on actually-charged API dollars.
    store = ProductPacketStore(str(tmp_path))
    p = _pkt(store)
    store.update(p["packet_id"], max_total_usd=3.0)
    relaunch_once(store, _Worker(ok=True, cost_usd=2.0), workspace=str(tmp_path), now=_T0,
                  billing_source="api_credits", completion_check=lambda pkt: "proposed")
    rec = store.get(p["packet_id"])
    assert abs(rec["actual_charged_usd"] - 2.0) < 1e-6
    assert rec["billing_source"] == "api_credits"
    relaunch_once(store, _Worker(ok=True, cost_usd=2.0), workspace=str(tmp_path),
                  now=_T0 + timedelta(hours=2), billing_source="api_credits",
                  completion_check=lambda pkt: "proposed")
    rec = store.get(p["packet_id"])
    assert rec["status"] == "needs_owner"                       # 4.0 charged > 3.0 cap -> owner approval
    assert rec["actual_charged_usd"] >= 3.0


def test_subscription_usage_never_trips_the_false_dollar_cap(tmp_path):
    # GPT P1: subscription token-equivalent usage is NOT real dollars; a $ cap must never falsely stop a
    # subscription run (the E2E-observed "false needs_owner"). Usage is still tracked honestly.
    store = ProductPacketStore(str(tmp_path))
    p = _pkt(store)
    store.update(p["packet_id"], max_total_usd=3.0)
    t = _T0
    for _ in range(3):
        relaunch_once(store, _Worker(ok=True, cost_usd=2.0), workspace=str(tmp_path), now=t,
                      billing_source="subscription", completion_check=lambda pkt: "proposed")
        t = t + timedelta(hours=2)
    rec = store.get(p["packet_id"])
    assert rec["status"] != "needs_owner"                       # never a false-dollar-cap stop
    assert rec["actual_charged_usd"] == 0.0                     # nothing really charged
    assert rec["usage_usd_equiv"] >= 6.0                        # but usage is tracked truthfully
    assert rec["billing_source"] == "subscription"


def test_heartbeat_keeps_single_writer_during_a_run_longer_than_the_lease(tmp_path):
    # P0-A regression A: a writer that runs longer than its lease must NOT be reclaimed into a second
    # writer — the live heartbeat renews the claim, and recovery sees the owner (this process) alive.
    import time as _time

    store = ProductPacketStore(str(tmp_path))
    p = _pkt(store)
    store.update(p["packet_id"], lease_seconds=15)             # short lease -> heartbeat renews every ~5s
    seen: dict = {}

    class _LongWorker:
        def run(self, order, workspace, *, resume_session="", cancel=None):
            pid = p["packet_id"]
            first = store.get(pid)["lease_expires_at"]
            deadline = _time.time() + 25
            while _time.time() < deadline:
                cur = store.get(pid)
                if cur["lease_expires_at"] > first:            # heartbeat fired during the run
                    seen["renewed"] = True
                    # a recovery pass with a far-future clock (lease "expired") must NOT reclaim a live owner
                    store.recover_orphaned_claims(now=datetime.now(timezone.utc) + timedelta(days=1))
                    seen["status_during"] = store.get(pid)["status"]
                    break
                _time.sleep(0.2)
            return type("R", (), {"ok": False, "session_id": "s", "reason": "stop", "cost_usd": 0.0})()

    relaunch_once(store, _LongWorker(), workspace=str(tmp_path))
    assert seen.get("renewed") is True                          # the lease was renewed mid-run
    assert seen.get("status_during") == "in_progress"           # never reclaimed while the owner is alive


def test_default_order_carries_the_canonical_protocol_and_thread(tmp_path):
    # P0-1: the writer's WorkOrder must state the canonical protocol + completion boundary, so a fresh
    # session knows a passing run is not completion — an exact-SHA GO on the bound thread is.
    store = ProductPacketStore(str(tmp_path))
    p = _pkt(store)
    order = build_default_order(store.get(p["packet_id"]))
    blob = (order.objective + " " + order.acceptance).upper()
    assert "PROPOSAL" in blob and "CHECKPOINT" in blob and "GO" in blob
    assert p["packet_id"] in (order.objective + order.acceptance)   # thread_id == packet id
