"""Independent reviewer client + strict output schema (Issue #14.B).

The reviewer is a bounded, read-only actor with respect to source: it receives a system contract, the
bounded evidence for one exact SHA, and one request envelope, and must return a structured decision.
It is given NO capability to merge, write source, run shell, or send externally — the client only maps
text in to structured text out. ``validate_reviewer_output`` enforces a strict schema so a malformed or
off-contract model answer is rejected (the driver then fails closed to NEEDS_OWNER) rather than being
silently applied.

Two implementations share the interface: ``FixtureReviewerClient`` (deterministic, drives CI + the
whole lifecycle without a network) and ``OpenAIReviewerClient`` (the real, owner-gated live path).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Protocol

_DECISION_VERDICTS = {"GO", "NO-GO", "COMMENT"}
# Which reviewer decision_type is valid as a reply to each request kind.
_ALLOWED_OUTPUT = {
    "QUESTION": {"RESPONSE"},
    "PROPOSAL": {"CRITIQUE", "RECOMMENDATION"},
    "CHECKPOINT": {"DECISION"},
}
_FULL_SHA_LEN = 40


class ReviewerSchemaError(ValueError):
    """Raised when reviewer output does not match the strict expected schema."""


@dataclass
class ReviewerResult:
    decision_type: str
    message: str
    verdict: str = ""
    reviewed_sha: str = ""
    confidence: str = ""
    blockers: List[str] = field(default_factory=list)
    evidence_used: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {"decision_type": self.decision_type, "message": self.message,
                "verdict": self.verdict, "reviewed_sha": self.reviewed_sha,
                "confidence": self.confidence, "blockers": list(self.blockers),
                "evidence_used": list(self.evidence_used)}


def validate_reviewer_output(raw: Dict[str, Any], *, request_kind: str,
                             expected_sha: str) -> ReviewerResult:
    if not isinstance(raw, dict):
        raise ReviewerSchemaError("reviewer output must be a JSON object")
    allowed = _ALLOWED_OUTPUT.get(request_kind)
    if allowed is None:
        raise ReviewerSchemaError(f"unsupported request_kind: {request_kind!r}")
    decision_type = str(raw.get("decision_type", "")).strip().upper()
    if decision_type not in allowed:
        raise ReviewerSchemaError(
            f"decision_type {decision_type!r} is not allowed for a {request_kind}; "
            f"expected one of {sorted(allowed)}")
    message = str(raw.get("message", "")).strip()
    if not message:
        raise ReviewerSchemaError("reviewer message must be non-empty")

    verdict = ""
    reviewed = ""
    if decision_type == "DECISION":
        verdict = str(raw.get("verdict", "")).strip().upper()
        if verdict not in _DECISION_VERDICTS:
            raise ReviewerSchemaError("DECISION requires a verdict of GO, NO-GO, or COMMENT")
        reviewed = str(raw.get("reviewed_sha", "")).strip().lower()
        if len(reviewed) != _FULL_SHA_LEN or reviewed != str(expected_sha).strip().lower():
            raise ReviewerSchemaError("reviewed_sha must echo the exact reviewed head SHA")

    blockers = [str(b).strip() for b in (raw.get("blockers") or []) if str(b).strip()]
    evidence_used = [str(e).strip() for e in (raw.get("evidence_used") or []) if str(e).strip()]
    return ReviewerResult(decision_type=decision_type, message=message, verdict=verdict,
                          reviewed_sha=reviewed, confidence=str(raw.get("confidence", "")).strip(),
                          blockers=blockers, evidence_used=evidence_used)


class ReviewerClient(Protocol):
    def review(self, *, system_contract: str, evidence: Dict[str, Any],
               message: Dict[str, Any]) -> Dict[str, Any]:
        ...


class FixtureReviewerClient:
    """Deterministic reviewer used by CI and by the offline lifecycle E2E (no network)."""

    def __init__(self, responder: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
        self._responder = responder
        self.calls = 0
        self.last_system_contract = ""
        self.last_evidence: Dict[str, Any] = {}
        self.last_message: Dict[str, Any] = {}

    def review(self, *, system_contract: str, evidence: Dict[str, Any],
               message: Dict[str, Any]) -> Dict[str, Any]:
        self.calls += 1
        self.last_system_contract = system_contract
        self.last_evidence = evidence
        self.last_message = message
        return self._responder(message)
