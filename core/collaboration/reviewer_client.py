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

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Protocol

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


def load_openai_key(env: Optional[Dict[str, str]] = None) -> str:
    """Owner-gated OpenAI key: env first, then a gitignored local ~/.aiqa/openai.key. Never committed."""
    env = env if env is not None else dict(os.environ)
    key = (env.get("OPENAI_API_KEY") or env.get("AIQA_OPENAI_API_KEY") or "").strip()
    if key:
        return key
    key_file = Path(env.get("AIQA_HOME") or (Path.home() / ".aiqa")) / "openai.key"
    if key_file.is_file():
        return key_file.read_text(encoding="utf-8").strip()
    return ""


class OpenAIReviewerClient:
    """Real, owner-gated reviewer over the OpenAI API. The model receives TEXT only — no tools, so it
    can never merge, write source, run shell, or send externally. ``create`` is injectable so the
    request shaping and JSON parsing are testable without the network or the ``openai`` package."""

    def __init__(self, *, model: Optional[str] = None, api_key: Optional[str] = None,
                 create: Optional[Callable[[str, List[Dict[str, str]]], str]] = None,
                 temperature: Optional[float] = None, reasoning_effort: Optional[str] = None,
                 max_output_chars: int = 20000) -> None:
        # Default to the owner's independent GPT-5.6 reviewer in high-thinking mode; overridable per
        # deployment via env. GO/NO-GO on code is a high-value decision — do not degrade it (invariant 7).
        self._model = model or os.environ.get("AIQA_REVIEWER_MODEL", "gpt-5.6-sol")
        self._api_key = api_key if api_key is not None else load_openai_key()
        self._create = create
        # Sent only when explicitly set: GPT-5 / reasoning models accept only the default temperature,
        # so we omit it by default and let deterministic structure come from the strict JSON schema.
        self._temperature = temperature
        # High reasoning by default; set AIQA_REVIEWER_REASONING_EFFORT="" to omit for non-reasoning models.
        effort = (reasoning_effort if reasoning_effort is not None
                  else os.environ.get("AIQA_REVIEWER_REASONING_EFFORT", "high"))
        self._reasoning_effort = (effort or "").strip()
        self._max_output_chars = max_output_chars

    def _resolve_create(self) -> Callable[[str, List[Dict[str, str]]], str]:
        if self._create is not None:
            return self._create
        if not self._api_key:
            raise ReviewerSchemaError("no OpenAI API key configured (set OPENAI_API_KEY or ~/.aiqa/openai.key)")
        from openai import OpenAI  # lazy: only needed on the live path

        client = OpenAI(api_key=self._api_key)
        temperature = self._temperature
        reasoning_effort = self._reasoning_effort

        def _call(model: str, messages: List[Dict[str, str]]) -> str:
            kwargs: Dict[str, Any] = {"model": model, "messages": messages,
                                      "response_format": {"type": "json_object"}}
            if temperature is not None:
                kwargs["temperature"] = temperature
            if reasoning_effort:
                kwargs["reasoning_effort"] = reasoning_effort
            resp = client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""

        return _call

    def review(self, *, system_contract: str, evidence: Dict[str, Any],
               message: Dict[str, Any]) -> Dict[str, Any]:
        payload = {
            "request_kind": message.get("kind"),
            "instruction": message.get("body", ""),
            "head_sha": message.get("head_sha", ""),
            "branch": message.get("branch", ""),
            "pr_number": message.get("pr_number"),
            "requested_next_action": message.get("requested_next_action", ""),
            "evidence": evidence,
            "required_output_schema": {
                "decision_type": "RESPONSE|CRITIQUE|RECOMMENDATION|DECISION",
                "verdict": "GO|NO-GO|COMMENT (DECISION only)",
                "reviewed_sha": "echo the exact head_sha (DECISION only)",
                "message": "your reasoning",
                "blockers": ["..."], "confidence": "low|medium|high",
                "evidence_used": ["..."]},
        }
        messages = [{"role": "system", "content": system_contract},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)}]
        raw_text = (self._resolve_create()(self._model, messages) or "")[: self._max_output_chars]
        try:
            data = json.loads(raw_text)
        except (ValueError, TypeError) as exc:
            raise ReviewerSchemaError(f"reviewer did not return valid JSON: {exc}") from exc
        if not isinstance(data, dict):
            raise ReviewerSchemaError("reviewer JSON must be an object")
        return data
