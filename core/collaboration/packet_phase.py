"""Canonical protocol phase for a product packet, derived from persisted evidence (Issue #17 P0-1).

A product packet is only *complete* when its bound Direct-Driver collaboration thread shows the
required canonical boundary — at minimum a proposal that was reviewed and acknowledged, plus an
exact-SHA CHECKPOINT decision of GO. This is derived from the SAME immutable ``_review_relay``
collaboration store the reviewer already writes to (no second state store); a writer process merely
exiting ``ok`` never advances the phase. Keeping the derivation pure and injectable means the relaunch
loop can be unit-tested without a network and the completion gate cannot be spoofed by a return code.
"""
from __future__ import annotations

from typing import Any, Dict, List

from core.collaboration.store import CollaborationStore

PHASE_NEW = "new"
PHASE_PROPOSED = "proposed"
PHASE_PROPOSAL_ACKED = "proposal_acked"
PHASE_CHECKPOINTED = "checkpointed"
PHASE_DECIDED_NOGO = "decided_nogo"
PHASE_DECIDED_GO = "decided_go"

# Reviewer replies to a PROPOSAL (any one of these closes the proposal round).
_PROPOSAL_REPLY = {"RESPONSE", "CRITIQUE", "RECOMMENDATION"}


def derive_phase(messages: List[Dict[str, Any]], *, head_sha: str = "") -> str:
    """Highest canonical phase evidenced by a thread's messages. ``head_sha`` (when known) enforces the
    exact-SHA gate: a GO recorded against a different head does not complete this packet."""
    kinds = [str(m.get("kind", "")) for m in messages]
    has_proposal = "PROPOSAL" in kinds
    has_reply = any(k in _PROPOSAL_REPLY for k in kinds)
    has_ack = "ACKNOWLEDGEMENT" in kinds
    has_checkpoint = "CHECKPOINT" in kinds
    proposal_complete = has_proposal and has_reply and has_ack

    sha = str(head_sha or "").strip().lower()
    decisions = [m for m in messages if str(m.get("kind", "")) == "DECISION"]
    if sha:
        decisions = [m for m in decisions if str(m.get("reviewed_sha", "")).lower() == sha]
    go = any(str(m.get("verdict", "")).upper() == "GO" for m in decisions)
    nogo = any(str(m.get("verdict", "")).upper() in ("NO-GO", "NOGO") for m in decisions)

    if go and proposal_complete:
        return PHASE_DECIDED_GO
    if nogo:
        return PHASE_DECIDED_NOGO
    if has_checkpoint:
        return PHASE_CHECKPOINTED
    if proposal_complete:
        return PHASE_PROPOSAL_ACKED
    if has_proposal:
        return PHASE_PROPOSED
    return PHASE_NEW


def is_complete(phase: str) -> bool:
    """A packet may be marked done ONLY at this boundary (exact-SHA GO on a reviewed+acked proposal)."""
    return phase == PHASE_DECIDED_GO


def packet_thread_id(packet: Dict[str, Any]) -> str:
    """The collaboration thread a packet's protocol lives on (defaults to the packet id)."""
    return str(packet.get("thread_id") or packet.get("packet_id") or "")


def phase_for_packet(output_root: str, packet: Dict[str, Any]) -> str:
    """Read the packet's bound collaboration thread and return the phase it evidences."""
    thread_id = packet_thread_id(packet)
    if not thread_id:
        return PHASE_NEW
    messages = CollaborationStore(output_root).thread(thread_id).get("messages", [])
    return derive_phase(messages, head_sha=str(packet.get("head_sha", "") or ""))
