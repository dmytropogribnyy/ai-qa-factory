"""A4.5 foundation closure — an UNVERIFIABLE head is not a matching head.

Both stale-head gates were written as ``if current_head and <mismatch>``, so when the head could not
be resolved at all — git missing, a 15 s timeout, a non-hex answer — the check was SKIPPED and the
work proceeded. Both sites carry a comment claiming the opposite:

* `reviewer_driver.process_once`: "Stale head: never fabricate a fresh decision for a moved branch head."
* `session_delivery.deliver`:     "A stale decision must never wake the session (fail closed)."

Prose said fail-closed; the branch said fail-open on unknown. UNKNOWN is not a match — it is the one
state in which neither "current" nor "stale" can be claimed, so the only honest action is to refuse
and say why. The delivery site had a second instance of the same shape: ``if sha and ...`` skipped
the check for a decision carrying no reviewed SHA at all, i.e. an unbindable decision was treated as
bound.

Liveness cost, accepted deliberately: if git cannot answer, collaboration stops instead of guessing.
That is the correct trade for a trust boundary, and the refusal names the cause so it is diagnosable
rather than silent.
"""
from __future__ import annotations

from core.collaboration.budget import BudgetLedger, BudgetPolicy
from core.collaboration.envelopes import make_envelope
from core.collaboration.reviewer_client import FixtureReviewerClient
from core.collaboration.reviewer_driver import ReviewerDriver
from core.collaboration.session_delivery import ClaudeSessionDelivery, SessionRegistry
from core.collaboration.store import CollaborationStore

_SHA = "a" * 40
_SESSION = "b93d32d1-7c96-4489-945b-2a49df494349"


def _complete_git(args):
    return "core/x.py" if "name-only" in args else "diff"


def _go(message):
    return {"decision_type": "DECISION", "verdict": "GO",
            "reviewed_sha": message["head_sha"], "message": "scope verified"}


def _driver(tmp_path, *, head):
    docs = tmp_path / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "COLLABORATIVE_AI_ENGINEERING_MODEL.md").write_text(
        "## 14. Canonical product invariants\n1. Integrated product, not islands.\n", encoding="utf-8")
    store = CollaborationStore(str(tmp_path))
    budget = BudgetLedger(str(tmp_path), policy=BudgetPolicy(
        per_thread_calls=5, per_thread_usd=5.0, daily_calls=20, daily_usd=20.0, max_retries=2,
        backoff_base_seconds=0.0), clock=lambda: "2026-07-21T20:00:00+00:00")
    client = FixtureReviewerClient(_go)
    driver = ReviewerDriver(store, budget, client, repo_root=str(tmp_path),
                            head_resolver=lambda: head, git_runner=_complete_git,
                            manifest_provider=lambda _s: {"present": True, "success": True,
                                                          "summary": "CI success"},
                            clock=lambda: "2026-07-21T20:00:00+00:00", sleep=lambda _s: None)
    return store, client, driver


def _checkpoint(store, head=_SHA):
    env = make_envelope(kind="CHECKPOINT", thread_id="t-1", actor="claude-code",
                        body="slice ready", head_sha=head, branch="main")
    store.append(env)
    return env


# --- the reviewer must not review against a head it cannot verify --------------------------------

def test_an_unresolvable_head_stops_the_reviewer_instead_of_skipping_the_stale_check(tmp_path):
    store, client, driver = _driver(tmp_path, head="")
    _checkpoint(store)
    out = driver.process_once()
    assert out["status"] != "reviewed", "an unverifiable head must not produce a fresh decision"
    assert client.calls == 0, "no paid reviewer call may be made against an unverifiable head"


def test_a_non_hex_head_answer_is_treated_as_unverifiable(tmp_path):
    """A git error string is not a SHA; matching it against the request would compare noise."""
    store, client, driver = _driver(tmp_path, head="fatal: not a git repository")
    _checkpoint(store)
    out = driver.process_once()
    assert out["status"] != "reviewed"
    assert client.calls == 0


def test_a_resolvable_matching_head_still_reviews(tmp_path):
    """Control: the fail-closed branch must not block the normal path."""
    store, client, driver = _driver(tmp_path, head=_SHA)
    _checkpoint(store)
    out = driver.process_once()
    assert out["status"] == "reviewed"
    assert client.calls == 1


def test_a_moved_head_is_still_reported_stale(tmp_path):
    """Control: the pre-existing stale detection is preserved."""
    store, client, driver = _driver(tmp_path, head="d" * 40)
    _checkpoint(store)
    assert driver.process_once()["status"] == "stale"
    assert client.calls == 0


# --- delivery must not wake a session against an unverifiable head -------------------------------

def _delivery(tmp_path, runner, *, head):
    reg = SessionRegistry(str(tmp_path / "s.json"))
    reg.bind("t-1", _SESSION)
    return ClaudeSessionDelivery(reg, str(tmp_path), exe_resolver=lambda: "claude.exe",
                                 runner=runner, head_resolver=lambda: head)


def _reply(sha=_SHA, key="k"):
    dec = make_envelope(kind="RESPONSE", thread_id="t-1", actor="gpt-reviewer", body="reply",
                        head_sha=sha, branch="main", in_reply_to="qkey")
    dec["message_id"] = f"t-1:{key}"
    dec["idempotency_key"] = key
    if sha:
        dec["reviewed_sha"] = sha
    return dec


def test_delivery_refuses_to_wake_a_session_when_the_head_cannot_be_resolved(tmp_path):
    woke = []
    out = _delivery(tmp_path, lambda *a, **k: woke.append(a), head="").deliver(_reply())
    assert out["status"] not in ("delivered", "in_progress"), out
    assert not woke, "no session may be woken against an unverifiable head"


def test_delivery_refuses_a_decision_that_carries_no_reviewed_sha(tmp_path):
    """`if sha and ...` skipped the gate entirely for an unbindable decision."""
    woke = []
    reply = _reply()
    reply.pop("reviewed_sha", None)
    reply["head_sha"] = ""
    out = _delivery(tmp_path, lambda *a, **k: woke.append(a), head=_SHA).deliver(reply)
    assert out["status"] not in ("delivered", "in_progress"), out
    assert not woke, "a decision bound to no SHA must never wake a session"


def test_delivery_still_wakes_on_a_matching_head(tmp_path):
    """Control: the normal delivery path is unaffected."""
    class _Proc:
        returncode = 0
        stdout = "ok"
        stderr = ""

    woke = []

    def _runner(*args, **kwargs):
        woke.append(args)
        return _Proc()

    out = _delivery(tmp_path, _runner, head=_SHA).deliver(_reply())
    assert out["status"] == "delivered", out
    assert woke, "the matching-head path must still wake the session"
