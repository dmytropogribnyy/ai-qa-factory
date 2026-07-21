"""Direct Collaboration Driver v1 (Issue #14.B) — the autonomous reviewer loop."""
from __future__ import annotations

from core.collaboration.budget import BudgetLedger, BudgetPolicy
from core.collaboration.envelopes import make_envelope
from core.collaboration.reviewer_client import FixtureReviewerClient
from core.collaboration.reviewer_driver import ReviewerDriver
from core.collaboration.store import CollaborationStore

_SHA = "a" * 40
_MOVED = "d" * 40


def _driver(tmp_path, responder, *, head=_SHA, policy=None):
    store = CollaborationStore(str(tmp_path))
    budget = BudgetLedger(str(tmp_path), policy=policy or BudgetPolicy(
        per_thread_calls=5, per_thread_usd=5.0, daily_calls=20, daily_usd=20.0, max_retries=2,
        backoff_base_seconds=0.0), clock=lambda: "2026-07-21T20:00:00+00:00")
    client = FixtureReviewerClient(responder)
    driver = ReviewerDriver(store, budget, client, repo_root=str(tmp_path),
                            head_resolver=lambda: head,
                            git_runner=lambda args: "core/x.py" if "name-only" in args else "diff",
                            clock=lambda: "2026-07-21T20:00:00+00:00", sleep=lambda _s: None)
    return store, budget, client, driver


def _checkpoint(store, thread="t-1"):
    return store.append(make_envelope(kind="CHECKPOINT", thread_id=thread, actor="claude-worker",
                                      body="slice ready", head_sha=_SHA, branch="feat/x",
                                      pr_number=14, requested_next_action="GO/NO-GO"))


def test_process_once_reviews_open_checkpoint_and_posts_a_go(tmp_path):
    store, budget, client, driver = _driver(
        tmp_path, lambda m: {"decision_type": "DECISION", "verdict": "GO",
                             "reviewed_sha": m["head_sha"], "message": "scope verified"})
    cp = _checkpoint(store)
    result = driver.process_once()
    assert result["status"] == "reviewed"
    decision = store.latest_decision("t-1")
    assert decision["verdict"] == "GO"
    assert decision["in_reply_to"] == cp["idempotency_key"]
    assert decision["reviewed_sha"] == _SHA
    assert store.open_requests() == []                      # request answered
    assert budget.usage("t-1")["thread_calls"] == 1
    assert client.calls == 1


def test_no_duplicate_processing_across_restart(tmp_path):
    store, budget, client, driver = _driver(
        tmp_path, lambda m: {"decision_type": "DECISION", "verdict": "GO",
                             "reviewed_sha": m["head_sha"], "message": "ok"})
    _checkpoint(store)
    driver.process_once()
    driver.process_once()                                   # simulated restart / second tick
    assert client.calls == 1                                # no duplicate API call
    assert len([m for m in store.thread("t-1")["messages"] if m["kind"] == "DECISION"]) == 1


def test_budget_cap_fails_closed_to_needs_owner(tmp_path):
    store, budget, client, driver = _driver(
        tmp_path, lambda m: {"decision_type": "DECISION", "verdict": "GO",
                             "reviewed_sha": m["head_sha"], "message": "ok"},
        policy=BudgetPolicy(per_thread_calls=1, daily_calls=99, backoff_base_seconds=0.0))
    budget.record("t-1", calls=1, usd=0.0)                  # thread already at its call cap
    _checkpoint(store)
    result = driver.process_once()
    assert result["status"] in ("blocked", "needs_owner")
    assert client.calls == 0                                # never called the model
    assert any(m["kind"] == "NEEDS_OWNER" for m in store.thread("t-1")["messages"])
    assert driver.health()["stage"] == "NEEDS_OWNER"


def test_stale_checkpoint_is_rejected_without_spending(tmp_path):
    # Branch head moved after the checkpoint: the driver must not fabricate a fresh GO for a stale head.
    store, budget, client, driver = _driver(
        tmp_path, lambda m: {"decision_type": "DECISION", "verdict": "GO",
                             "reviewed_sha": m["head_sha"], "message": "ok"}, head=_MOVED)
    _checkpoint(store)                                      # checkpoint bound to _SHA, head now _MOVED
    result = driver.process_once()
    assert result["status"] in ("stale", "needs_owner", "blocked")
    assert client.calls == 0
    assert store.latest_decision("t-1") is None            # no GO/NO-GO recorded for the moved head


def test_malformed_model_output_fails_closed(tmp_path):
    store, budget, client, driver = _driver(
        tmp_path, lambda m: {"decision_type": "DECISION", "message": "no verdict here"})
    _checkpoint(store)
    result = driver.process_once()
    assert result["status"] in ("schema_error", "needs_owner", "blocked")
    assert store.latest_decision("t-1") is None            # malformed output never persisted as a decision
    assert any(m["kind"] == "NEEDS_OWNER" for m in store.thread("t-1")["messages"])


def test_question_gets_a_response(tmp_path):
    store, budget, client, driver = _driver(
        tmp_path, lambda m: {"decision_type": "RESPONSE", "message": "use exponential backoff"})
    store.append(make_envelope(kind="QUESTION", thread_id="t-q", actor="claude-worker",
                               body="retry policy?", head_sha=_SHA, branch="feat/x"))
    driver.process_once()
    kinds = [m["kind"] for m in store.thread("t-q")["messages"]]
    assert kinds == ["QUESTION", "RESPONSE"]


def test_health_reports_stage_actor_and_spend(tmp_path):
    store, budget, client, driver = _driver(
        tmp_path, lambda m: {"decision_type": "DECISION", "verdict": "NO-GO",
                             "reviewed_sha": m["head_sha"], "message": "fix tests",
                             "blockers": ["failing test x"]})
    _checkpoint(store)
    driver.process_once()
    h = driver.health()
    assert h["stage"] in ("REVIEWING", "IDLE")
    assert h["processed"] == 1
    assert h["last_error"] == ""
    assert "daily_calls" in h["budget"]
