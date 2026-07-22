"""Issue #17 P0-1 — a packet's canonical protocol phase is derived from persisted Direct-Driver
evidence, never from a writer process return code."""
from __future__ import annotations

from core.collaboration.envelopes import make_envelope
from core.collaboration.packet_phase import (
    PHASE_CHECKPOINTED,
    PHASE_DECIDED_GO,
    PHASE_DECIDED_NOGO,
    PHASE_NEW,
    PHASE_PROPOSAL_ACKED,
    PHASE_PROPOSED,
    derive_phase,
    is_complete,
    phase_for_packet,
)
from core.collaboration.store import CollaborationStore

_SHA = "a" * 40
_OTHER = "b" * 40


def test_derive_phase_progression():
    assert derive_phase([]) == PHASE_NEW
    assert derive_phase([{"kind": "PROPOSAL"}]) == PHASE_PROPOSED
    acked = [{"kind": "PROPOSAL"}, {"kind": "RECOMMENDATION"}, {"kind": "ACKNOWLEDGEMENT"}]
    assert derive_phase(acked) == PHASE_PROPOSAL_ACKED
    checkpointed = acked + [{"kind": "CHECKPOINT", "head_sha": _SHA}]
    assert derive_phase(checkpointed, head_sha=_SHA) == PHASE_CHECKPOINTED
    nogo = checkpointed + [{"kind": "DECISION", "verdict": "NO-GO", "reviewed_sha": _SHA}]
    assert derive_phase(nogo, head_sha=_SHA) == PHASE_DECIDED_NOGO
    go = checkpointed + [{"kind": "DECISION", "verdict": "GO", "reviewed_sha": _SHA}]
    assert derive_phase(go, head_sha=_SHA) == PHASE_DECIDED_GO
    assert is_complete(derive_phase(go, head_sha=_SHA))


def test_go_for_a_different_sha_does_not_complete_the_packet():
    # The exact-SHA gate: a GO recorded against another head must not complete THIS packet.
    go = [{"kind": "PROPOSAL"}, {"kind": "RECOMMENDATION"}, {"kind": "ACKNOWLEDGEMENT"},
          {"kind": "CHECKPOINT", "head_sha": _SHA},
          {"kind": "DECISION", "verdict": "GO", "reviewed_sha": _OTHER}]
    assert derive_phase(go, head_sha=_SHA) != PHASE_DECIDED_GO


def test_go_without_proposal_ack_is_not_a_complete_boundary():
    # Reviewer's minimum boundary requires proposal response + ACK AND an exact-SHA decision.
    go_only = [{"kind": "CHECKPOINT", "head_sha": _SHA},
               {"kind": "DECISION", "verdict": "GO", "reviewed_sha": _SHA}]
    assert not is_complete(derive_phase(go_only, head_sha=_SHA))


def test_phase_for_packet_reads_the_bound_collab_thread(tmp_path):
    output_root = str(tmp_path)
    store = CollaborationStore(output_root)
    packet = {"packet_id": "pkt-20260722T000000Z-abcdef01", "head_sha": _SHA, "branch": "feat/x"}
    # Empty thread -> the packet has not started the protocol.
    assert phase_for_packet(output_root, packet) == PHASE_NEW

    # Build a full PROPOSAL -> RECOMMENDATION -> ACK -> CHECKPOINT -> DECISION(GO) chain on the
    # thread bound to the packet (thread_id == packet_id).
    tid = packet["packet_id"]
    proposal = store.append(make_envelope(kind="PROPOSAL", thread_id=tid, actor="claude-worker",
                                          body="plan", head_sha=_SHA, branch="feat/x"))
    rec = store.append(make_envelope(kind="RECOMMENDATION", thread_id=tid, actor="gpt-reviewer",
                                     body="ok", head_sha=_SHA, branch="feat/x",
                                     in_reply_to=proposal["idempotency_key"]))
    store.append(make_envelope(kind="ACKNOWLEDGEMENT", thread_id=tid, actor="claude-worker",
                               body="ack", in_reply_to=rec["idempotency_key"]))
    checkpoint = store.append(make_envelope(kind="CHECKPOINT", thread_id=tid, actor="claude-worker",
                                            body="done", head_sha=_SHA, branch="feat/x"))
    store.append(make_envelope(kind="DECISION", thread_id=tid, actor="gpt-reviewer", body="go",
                               head_sha=_SHA, branch="feat/x", verdict="GO", reviewed_sha=_SHA,
                               in_reply_to=checkpoint["idempotency_key"]))
    assert phase_for_packet(output_root, packet) == PHASE_DECIDED_GO
