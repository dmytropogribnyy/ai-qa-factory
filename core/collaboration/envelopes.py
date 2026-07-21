"""Bounded, SHA-bound collaboration envelopes (Issue #14.A).

An *envelope* is one immutable message in a collaboration thread between the Claude worker, the
independent GPT reviewer, and (for escalations) the owner. Envelopes are the only vocabulary the
driver speaks; every code-related message binds to the EXACT full head SHA it concerns, so a decision
can never be silently applied to a moved branch (stale-SHA rejection, E2E #4).

This module is pure: it validates and shapes payloads and redacts the body at construction time, so a
secret can never reach the store or the OpenAI API. Persistence lives in ``store.py``.
"""
from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from core.orchestration.content_safety import redact_intake_text

# The minimal message vocabulary required for real autonomous engineering (Issue #14.A).
MESSAGE_KINDS = {
    "QUESTION", "RESPONSE",
    "PROPOSAL", "CRITIQUE", "RECOMMENDATION",
    "CHECKPOINT", "DECISION",
    "ACKNOWLEDGEMENT", "NEEDS_OWNER",
}
# Kinds that concern a specific commit and therefore MUST bind to an exact full head SHA + branch.
CODE_BOUND_KINDS = {
    "QUESTION", "RESPONSE", "PROPOSAL", "CRITIQUE", "RECOMMENDATION", "CHECKPOINT", "DECISION",
}
DECISION_VERDICTS = {"GO", "NO-GO", "COMMENT"}

_FULL_SHA = re.compile(r"^[0-9a-f]{40}$")
_SAFE_THREAD = re.compile(r"^[0-9A-Za-z._-]{1,120}$")
_MAX_EVIDENCE_REFS = 64
_MAX_REF_LEN = 400


class EnvelopeError(ValueError):
    """Raised for an invalid or unbound collaboration envelope."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _redact(value: Any, *, limit: int) -> str:
    # Redact FIRST, then bound the length (length-sensitive patterns must see the whole secret).
    return redact_intake_text(str(value or "").strip()).text[:limit]


def _require_full_sha(label: str, value: str) -> str:
    sha = str(value or "").strip().lower()
    if not _FULL_SHA.fullmatch(sha):
        raise EnvelopeError(f"{label} must be an exact full 40-character hexadecimal commit SHA")
    return sha


def _clean_refs(evidence_refs: Optional[List[Any]]) -> List[str]:
    refs = [_redact(r, limit=_MAX_REF_LEN) for r in (evidence_refs or []) if str(r or "").strip()]
    if len(refs) > _MAX_EVIDENCE_REFS:
        raise EnvelopeError(f"at most {_MAX_EVIDENCE_REFS} evidence refs are allowed")
    return refs


def _fingerprint(kind: str, thread_id: str, head_sha: str, verdict: str, in_reply_to: str,
                 body: str) -> str:
    # Stable across retry attempts (attempt is deliberately excluded) but unique per logical message
    # and per SHA, so retries dedupe while a different commit is always a distinct action (Issue #14.E).
    material = "\x1f".join((kind, thread_id, head_sha, verdict, in_reply_to, body))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


def make_envelope(
    *,
    kind: str,
    thread_id: str,
    actor: str,
    body: str = "",
    head_sha: str = "",
    branch: str = "",
    pr_number: Any = None,
    evidence_refs: Optional[List[Any]] = None,
    requested_next_action: str = "",
    verdict: str = "",
    reviewed_sha: str = "",
    in_reply_to: str = "",
    attempt: int = 1,
) -> Dict[str, Any]:
    """Validate + shape one immutable, redacted, SHA-bound collaboration envelope."""
    if kind not in MESSAGE_KINDS:
        raise EnvelopeError(f"unknown envelope kind: {kind!r}")
    thread = str(thread_id or "").strip()
    if not _SAFE_THREAD.fullmatch(thread):
        raise EnvelopeError("thread_id must be 1-120 chars of [A-Za-z0-9._-]")
    who = _redact(actor, limit=80)
    if not who:
        raise EnvelopeError("actor is required")

    sha = ""
    branch_clean = _redact(branch, limit=200)
    if kind in CODE_BOUND_KINDS:
        sha = _require_full_sha("head_sha", head_sha)
        if not branch_clean:
            raise EnvelopeError("branch is required for code-bound envelopes")

    verdict_clean = ""
    reviewed = ""
    if kind == "DECISION":
        verdict_clean = str(verdict or "").strip().upper()
        if verdict_clean not in DECISION_VERDICTS:
            raise EnvelopeError("DECISION requires a verdict of GO, NO-GO, or COMMENT")
        reviewed = _require_full_sha("reviewed_sha", reviewed_sha or head_sha)

    pr: Optional[int] = None
    if pr_number not in (None, ""):
        try:
            pr = max(1, int(pr_number))
        except (TypeError, ValueError) as exc:
            raise EnvelopeError("pr_number must be a positive integer") from exc

    try:
        attempt_n = max(1, int(attempt))
    except (TypeError, ValueError) as exc:
        raise EnvelopeError("attempt must be a positive integer") from exc

    body_clean = _redact(body, limit=16000)
    in_reply = _redact(in_reply_to, limit=120)
    return {
        "kind": kind,
        "thread_id": thread,
        "actor": who,
        "body": body_clean,
        "head_sha": sha,
        "branch": branch_clean,
        "pr_number": pr,
        "evidence_refs": _clean_refs(evidence_refs),
        "requested_next_action": _redact(requested_next_action, limit=200),
        "verdict": verdict_clean,
        "reviewed_sha": reviewed,
        "in_reply_to": in_reply,
        "attempt": attempt_n,
        "created_at": _now(),
        "idempotency_key": _fingerprint(kind, thread, sha, verdict_clean, in_reply, body_clean),
    }
