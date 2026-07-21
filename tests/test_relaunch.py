"""Issue #17 — session-independent writer relaunch cycle."""
from __future__ import annotations

from core.collaboration.product_packet import ProductPacketStore
from core.collaboration.relaunch import relaunch_once, summary


class _Worker:
    """Stub bounded worker adapter recording launches and returning a scripted result."""

    def __init__(self, ok=True, session_id="sess-1", reason="", raises=False):
        self._ok, self._session, self._reason, self._raises = ok, session_id, reason, raises
        self.calls = 0
        self.last_order = None
        self.last_resume = None

    def run(self, order, workspace, *, resume_session="", cancel=None):
        self.calls += 1
        self.last_order = order
        self.last_resume = resume_session
        if self._raises:
            raise RuntimeError("claude not available")
        return type("R", (), {"ok": self._ok, "session_id": self._session, "reason": self._reason})()


def _pkt(store):
    return store.create(objective="Rank Scout findings by commercial value on /scout/target",
                        acceptance="findings ordered by expected value", safety="read-only",
                        next_action="reuse core/scout/priority.py to rank + show confidence")


def test_relaunch_launches_bounded_writer_and_marks_done(tmp_path):
    store = ProductPacketStore(str(tmp_path))
    p = _pkt(store)
    worker = _Worker(ok=True)
    out = relaunch_once(store, worker, workspace=str(tmp_path))
    assert out["status"] == "launched" and out["ok"] is True
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
    relaunch_once(store, worker, workspace=str(tmp_path))       # done
    second = relaunch_once(store, worker, workspace=str(tmp_path))  # simulated restart cycle
    assert second["status"] == "idle"                          # not relaunched
    assert worker.calls == 1                                    # no duplicate writer


def test_retry_resumes_the_same_writer_session(tmp_path):
    store = ProductPacketStore(str(tmp_path))
    _pkt(store)
    relaunch_once(store, _Worker(ok=False, session_id="sess-x"), workspace=str(tmp_path))  # attempt 1
    worker2 = _Worker(ok=True, session_id="sess-x")
    relaunch_once(store, worker2, workspace=str(tmp_path))      # attempt 2 -> resume
    assert worker2.last_resume == "sess-x"                      # resumed the same writer session


def test_summary_reports_status_counts(tmp_path):
    store = ProductPacketStore(str(tmp_path))
    _pkt(store)
    s = summary(store)
    assert s["total"] == 1
    assert s["next_pending"] is not None
