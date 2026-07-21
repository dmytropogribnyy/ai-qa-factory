"""Direct Collaboration Driver v1 (Issue #14) — assembly + worker-side helpers."""
from __future__ import annotations

from core.collaboration.budget import BudgetPolicy
from core.collaboration.reviewer_client import FixtureReviewerClient
from core.collaboration.service import (
    build_reviewer_driver,
    record_ack,
    resolve_git_head,
    submit_worker_message,
)
from core.collaboration.store import CollaborationStore

_SHA = "a" * 40


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
    submit_worker_message(str(tmp_path), kind="CHECKPOINT", thread_id="t-1", body="ready",
                          head_sha=_SHA, branch="feat/x")
    client = FixtureReviewerClient(lambda m: {"decision_type": "DECISION", "verdict": "GO",
                                              "reviewed_sha": m["head_sha"], "message": "ok"})
    driver = build_reviewer_driver(str(tmp_path), str(tmp_path), reviewer_client=client,
                                   policy=BudgetPolicy(backoff_base_seconds=0.0))
    # head_resolver reads git in tmp_path (not a repo) -> "" -> stale check skipped, review proceeds.
    out = driver.process_once()
    assert out["status"] == "reviewed"
    assert CollaborationStore(str(tmp_path)).latest_decision("t-1")["verdict"] == "GO"
