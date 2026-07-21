"""Direct Collaboration Driver v1 (Issue #14) — assembly + worker-side helpers."""
from __future__ import annotations

from core.collaboration.budget import BudgetPolicy
from core.collaboration.reviewer_client import FixtureReviewerClient
from core.collaboration.service import (
    CollaborationCycle,
    build_reviewer_driver,
    record_ack,
    resolve_git_head,
    submit_worker_message,
)
from core.collaboration.session_delivery import ClaudeSessionDelivery, SessionRegistry
from core.collaboration.store import CollaborationStore

_SHA = "a" * 40


def _bound_cycle(tmp_path, responder, *, session="b93d32d1-7c96-4489-945b-2a49df494349",
                 bind_thread="t-1", runner=None, deliver_head=_SHA):
    reg = SessionRegistry(str(tmp_path / "sessions.json"))
    if bind_thread:
        reg.bind(bind_thread, session)
    runs = {"n": 0}

    def _runner(cmd, **kw):
        runs["n"] += 1
        return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    delivery = ClaudeSessionDelivery(reg, str(tmp_path), exe_resolver=lambda: "claude.exe",
                                     runner=runner or _runner, head_resolver=lambda: deliver_head)
    cycle = CollaborationCycle(str(tmp_path), str(tmp_path),
                               reviewer_client=FixtureReviewerClient(responder),
                               policy=BudgetPolicy(backoff_base_seconds=0.0),
                               registry=reg, delivery=delivery)
    return cycle, reg, runs


def test_resolve_git_head_of_this_repo_is_a_full_sha():
    head = resolve_git_head(".")
    assert head == "" or len(head) == 40


def test_submit_worker_message_enqueues_an_open_request(tmp_path):
    submit_worker_message(str(tmp_path), kind="CHECKPOINT", thread_id="t-1", body="ready",
                          head_sha=_SHA, branch="feat/x", pr_number=14,
                          requested_next_action="GO/NO-GO")
    store = CollaborationStore(str(tmp_path))
    opens = store.open_requests()
    assert len(opens) == 1
    assert opens[0]["kind"] == "CHECKPOINT"


def test_record_ack_appends_an_acknowledgement(tmp_path):
    record_ack(str(tmp_path), thread_id="t-1", decision_key="deckey", note="applied")
    store = CollaborationStore(str(tmp_path))
    assert [m["kind"] for m in store.thread("t-1")["messages"]] == ["ACKNOWLEDGEMENT"]


def test_build_reviewer_driver_wires_a_working_loop(tmp_path):
    submit_worker_message(str(tmp_path), kind="QUESTION", thread_id="t-1", body="retry policy?",
                          head_sha=_SHA, branch="feat/x")
    client = FixtureReviewerClient(lambda m: {"decision_type": "RESPONSE", "message": "use backoff"})
    driver = build_reviewer_driver(str(tmp_path), str(tmp_path), reviewer_client=client,
                                   policy=BudgetPolicy(backoff_base_seconds=0.0))
    # head_resolver reads git in tmp_path (not a repo) -> "" -> stale check skipped, review proceeds.
    out = driver.process_once()
    assert out["status"] == "reviewed"
    kinds = [m["kind"] for m in CollaborationStore(str(tmp_path)).thread("t-1")["messages"]]
    assert kinds == ["QUESTION", "RESPONSE"]


def test_cycle_reviews_then_delivers_to_bound_session(tmp_path):
    submit_worker_message(str(tmp_path), kind="QUESTION", thread_id="t-1", body="retry policy?",
                          head_sha=_SHA, branch="feat/x")
    cycle, reg, runs = _bound_cycle(
        tmp_path, lambda m: {"decision_type": "RESPONSE", "message": "use backoff with jitter"})
    out = cycle.tick()
    assert out["review"]["status"] == "reviewed"
    assert any(d["status"] == "delivered" for d in out["deliveries"])   # reviewer->delivery connected
    assert runs["n"] == 1                                               # the bound session was resumed


def test_cycle_does_not_deliver_without_a_session_binding(tmp_path):
    submit_worker_message(str(tmp_path), kind="QUESTION", thread_id="t-1", body="q",
                          head_sha=_SHA, branch="feat/x")
    cycle, reg, runs = _bound_cycle(
        tmp_path, lambda m: {"decision_type": "RESPONSE", "message": "a"}, bind_thread=None)
    out = cycle.tick()
    assert out["review"]["status"] == "reviewed"
    assert out["deliveries"] == []                                     # nothing woken
    assert runs["n"] == 0


def test_cycle_restart_does_not_redeliver(tmp_path):
    submit_worker_message(str(tmp_path), kind="QUESTION", thread_id="t-1", body="q",
                          head_sha=_SHA, branch="feat/x")
    cycle, reg, runs = _bound_cycle(
        tmp_path, lambda m: {"decision_type": "RESPONSE", "message": "a"})
    cycle.tick()
    cycle.tick()                                                       # simulated restart tick
    assert runs["n"] == 1                                             # delivered exactly once


def test_cycle_escalates_terminal_delivery_failure_to_owner(tmp_path):
    # branch head moved after review -> delivery is stale -> durable NEEDS_OWNER, owner_action True.
    submit_worker_message(str(tmp_path), kind="QUESTION", thread_id="t-1", body="q",
                          head_sha=_SHA, branch="feat/x")
    cycle, reg, runs = _bound_cycle(
        tmp_path, lambda m: {"decision_type": "RESPONSE", "message": "a"}, deliver_head="e" * 40)
    out = cycle.tick()
    assert any(d["status"] == "stale" for d in out["deliveries"])
    assert out["owner_action"] is True
    kinds = [m["kind"] for m in CollaborationStore(str(tmp_path)).thread("t-1")["messages"]]
    assert "NEEDS_OWNER" in kinds                                     # durable, owner-visible


def test_resolve_branch_head_is_safe(tmp_path):
    from core.collaboration.service import resolve_branch_head
    head = resolve_branch_head(".", "feat/direct-collaboration-driver-v1")
    assert head == "" or len(head) == 40
    injected = resolve_branch_head(".", "; rm -rf /")                 # invalid ref -> safe fallback
    assert injected == "" or len(injected) == 40
