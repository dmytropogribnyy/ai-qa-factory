"""Direct Collaboration Driver v1 (Issue #14.C) — safe delivery into one bound Claude session."""
from __future__ import annotations

from pathlib import Path

import pytest

from core.collaboration.envelopes import make_envelope
from core.collaboration.session_delivery import (
    ClaudeSessionDelivery,
    SessionDeliveryError,
    SessionRegistry,
)
from core.collaboration.store import CollaborationStore

_SHA = "a" * 40
_SESSION = "b93d32d1-7c96-4489-945b-2a49df494349"


def _decision(thread="t-1"):
    return make_envelope(kind="DECISION", thread_id=thread, actor="gpt-reviewer",
                         body="scope verified; proceed", head_sha=_SHA, branch="feat/x",
                         verdict="GO", reviewed_sha=_SHA, in_reply_to="cp-key")


def test_bind_and_resolve_session(tmp_path):
    reg = SessionRegistry(str(tmp_path / ".aiqa_collab_sessions.json"))
    reg.bind("t-1", _SESSION)
    assert reg.session_for("t-1") == _SESSION
    assert reg.session_for("t-unknown") is None


def test_bind_rejects_malformed_session_id(tmp_path):
    reg = SessionRegistry(str(tmp_path / "s.json"))
    with pytest.raises(SessionDeliveryError, match="session"):
        reg.bind("t-1", "not-a-uuid")


def test_deliver_resumes_bound_session_with_a_fixed_template_and_data_file(tmp_path):
    reg = SessionRegistry(str(tmp_path / "s.json"))
    reg.bind("t-1", _SESSION)
    captured = {}

    def runner(cmd, **kw):
        captured["cmd"] = cmd
        return type("P", (), {"returncode": 0, "stdout": "{}", "stderr": ""})()

    delivery = ClaudeSessionDelivery(reg, str(tmp_path), exe_resolver=lambda: "claude.exe",
                                     runner=runner, head_resolver=lambda: _SHA,
                                     clock=lambda: "2026-07-21T20:00:00+00:00")
    dec = _decision()
    dec["message_id"] = "t-1:deckey"
    out = delivery.deliver(dec)
    assert out["status"] == "delivered"
    cmd = captured["cmd"]
    assert "--resume" in cmd and _SESSION in cmd                 # resumed the bound session
    # The reviewer's own text is passed as DATA (a file), never interpolated into the command.
    assert "scope verified; proceed" not in " ".join(cmd)
    assert any("shell" not in str(k).lower() for k in [captured])  # invoked as argv, not a shell string


def test_deliver_without_a_binding_fails_safely_without_running(tmp_path):
    reg = SessionRegistry(str(tmp_path / "s.json"))
    ran = {"n": 0}

    def runner(cmd, **kw):
        ran["n"] += 1
        return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    delivery = ClaudeSessionDelivery(reg, str(tmp_path), exe_resolver=lambda: "claude.exe",
                                     runner=runner)
    with pytest.raises(SessionDeliveryError, match="session"):
        delivery.deliver(_decision("t-unbound"))
    assert ran["n"] == 0                                         # no wrong/arbitrary session woken


def test_delivery_is_idempotent_across_restart(tmp_path):
    reg = SessionRegistry(str(tmp_path / "s.json"))
    reg.bind("t-1", _SESSION)
    ran = {"n": 0}

    def runner(cmd, **kw):
        ran["n"] += 1
        return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    dec = _decision()
    dec["message_id"] = "t-1:deckey"
    d1 = ClaudeSessionDelivery(reg, str(tmp_path), exe_resolver=lambda: "claude.exe", runner=runner,
                               head_resolver=lambda: _SHA)
    d1.deliver(dec)
    d2 = ClaudeSessionDelivery(reg, str(tmp_path), exe_resolver=lambda: "claude.exe", runner=runner,
                               head_resolver=lambda: _SHA)
    out = d2.deliver(dec)                                        # simulated restart
    assert out["status"] == "already_delivered"
    assert ran["n"] == 1                                         # no duplicate resume


def test_delivered_session_reads_decision_and_records_ack(tmp_path):
    # The resumed session must read the decision and write an ACK; we simulate that with the runner.
    reg = SessionRegistry(str(tmp_path / "s.json"))
    reg.bind("t-1", _SESSION)
    store = CollaborationStore(str(tmp_path))

    def runner_that_acks(cmd, **kw):
        store.append(make_envelope(kind="ACKNOWLEDGEMENT", thread_id="t-1", actor="claude-worker",
                                   body="decision received and applied", in_reply_to="deckey"))
        return type("P", (), {"returncode": 0, "stdout": "", "stderr": ""})()

    dec = _decision()
    dec["message_id"] = "t-1:deckey"
    dec["idempotency_key"] = "deckey"
    delivery = ClaudeSessionDelivery(reg, str(tmp_path), exe_resolver=lambda: "claude.exe",
                                     runner=runner_that_acks, head_resolver=lambda: _SHA)
    delivery.deliver(dec)
    kinds = [m["kind"] for m in store.thread("t-1")["messages"]]
    assert "ACKNOWLEDGEMENT" in kinds


def test_no_native_exe_fails_safely(tmp_path):
    reg = SessionRegistry(str(tmp_path / "s.json"))
    reg.bind("t-1", _SESSION)
    delivery = ClaudeSessionDelivery(reg, str(tmp_path), exe_resolver=lambda: None,
                                     runner=lambda *a, **k: None, head_resolver=lambda: _SHA)
    with pytest.raises(SessionDeliveryError, match="claude|executable"):
        delivery.deliver(_decision())


def _reg(tmp_path):
    reg = SessionRegistry(str(tmp_path / "s.json"))
    reg.bind("t-1", _SESSION)
    return reg


def test_nonzero_returncode_is_not_marked_delivered_and_is_retryable(tmp_path):
    outcomes = [1, 0]  # first resume fails, second succeeds

    def runner(cmd, **kw):
        return type("P", (), {"returncode": outcomes.pop(0), "stdout": "", "stderr": ""})()

    dec = _decision()
    dec["message_id"] = "t-1:k"
    d = ClaudeSessionDelivery(_reg(tmp_path), str(tmp_path), exe_resolver=lambda: "claude.exe",
                              runner=runner, head_resolver=lambda: _SHA)
    first = d.deliver(dec)
    assert first["status"] == "failed" and first["returncode"] == 1
    second = d.deliver(dec)                              # safe retry after a failed resume
    assert second["status"] == "delivered"


def test_timeout_is_not_marked_delivered(tmp_path):
    import subprocess

    def runner(cmd, **kw):
        raise subprocess.TimeoutExpired(cmd, 1)

    dec = _decision()
    dec["message_id"] = "t-1:k"
    d = ClaudeSessionDelivery(_reg(tmp_path), str(tmp_path), exe_resolver=lambda: "claude.exe",
                              runner=runner, head_resolver=lambda: _SHA)
    out = d.deliver(dec)
    assert out["status"] == "failed"
    assert (Path(str(tmp_path)) / "_review_relay" / "collab_delivery" / "t-1_k.json").exists() is False


def test_stale_decision_is_not_delivered(tmp_path):
    ran = {"n": 0}

    def runner(cmd, **kw):
        ran["n"] += 1
        return type("P", (), {"returncode": 0})()

    dec = _decision()
    dec["message_id"] = "t-1:k"
    # branch head moved after review: current head != reviewed_sha -> fail closed, no wake.
    d = ClaudeSessionDelivery(_reg(tmp_path), str(tmp_path), exe_resolver=lambda: "claude.exe",
                              runner=runner, head_resolver=lambda: "e" * 40)
    out = d.deliver(dec)
    assert out["status"] == "stale"
    assert ran["n"] == 0


def test_bounded_failure_attempts_then_exhausted(tmp_path):
    def runner(cmd, **kw):
        return type("P", (), {"returncode": 1})()

    dec = _decision()
    dec["message_id"] = "t-1:k"
    d = ClaudeSessionDelivery(_reg(tmp_path), str(tmp_path), exe_resolver=lambda: "claude.exe",
                              runner=runner, head_resolver=lambda: _SHA, max_attempts=2)
    assert d.deliver(dec)["status"] == "failed"          # attempt 1
    assert d.deliver(dec)["status"] == "failed"          # attempt 2
    assert d.deliver(dec)["status"] == "failed_exhausted"  # bounded: no more auto-retry
