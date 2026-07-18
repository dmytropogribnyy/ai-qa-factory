"""Outbound provider abstraction (Final Phase II).

A narrow provider interface. Built-in:
- `DeterministicLocalSinkProvider` (mandatory): no network; writes a sanitized envelope to a
  confined local sink; drives the full E2E; supports scripted delivery/reply/bounce/opt-out
  simulation. **Never** counts as live-accepted.
- `SandboxProvider`: no real external recipient.
- `RealEmailAdapter`: adapter-ready; credentials from an env-var reference only; sends only when
  explicitly configured AND live-approved; no arbitrary-SMTP fallback; never required by tests.

No provider stores raw secrets; provider errors are sanitized.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.scout.comms.snapshots import body_hash as _body_hash
from core.scout.comms.snapshots import canonical_hash

# Send result outcomes.
ACCEPTED, FAILED_DEFINITE, OUTCOME_UNKNOWN = "ACCEPTED", "FAILED_DEFINITE", "OUTCOME_UNKNOWN"
_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")


@dataclass
class SendEnvelope:
    """The EXACT approved payload handed to a provider in memory. The recipient/subject/body are
    the authoritative approved values; a provider that must not see plaintext (the local sink)
    stores only ``sanitized()``. Never logged or published in plaintext."""
    recipient: str
    subject: str
    body: str
    channel: str
    revision_id: str
    message_id: str
    idempotency_key: str
    correlation_id: str = ""
    from_email: str = ""
    from_name: str = ""

    def sanitized(self) -> Dict[str, Any]:
        """A bounded, secret-free view: hashes instead of the plaintext recipient/body."""
        return {"channel": self.channel, "recipient_hash": canonical_hash(self.recipient),
                "subject_hash": canonical_hash(self.subject), "body_hash": _body_hash(
                    self.subject, self.body), "revision_id": self.revision_id,
                "message_id": self.message_id, "idempotency_key": self.idempotency_key,
                "correlation_id": self.correlation_id}


class ProviderError(Exception):
    pass


class ProviderTimeout(ProviderError):
    """Ambiguous outcome — the caller must treat this as OUTCOME_UNKNOWN (never auto-retry)."""


@dataclass
class ProviderMetadata:
    provider_id: str = ""
    provider_version: str = "1.0.0"
    channel: str = "email"
    readiness: str = "fixture-tested"     # fixture-tested|adapter-ready|configured|sandbox-accepted|live-accepted
    auth_ref: str = ""                    # env var NAME only, never a secret
    idempotency_support: bool = False
    sandbox_support: bool = False
    max_recipients_per_call: int = 1
    rate_limit_per_min: int = 0
    terms_review_status: str = "not_reviewed"

    def __post_init__(self) -> None:
        if self.auth_ref and not _ENV_NAME_RE.match(self.auth_ref):
            raise ProviderError("auth_ref must be an environment-variable name, not a value")
        if self.max_recipients_per_call != 1:
            raise ProviderError("max_recipients_per_call must be 1 (no bulk send)")

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


@dataclass
class SendResult:
    outcome: str = OUTCOME_UNKNOWN
    provider_message_id: str = ""
    error: str = ""
    provider_id: str = ""
    detail: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {"outcome": self.outcome, "provider_message_id": self.provider_message_id,
                "error": self.error, "provider_id": self.provider_id, "detail": self.detail}


class DeterministicLocalSinkProvider:
    """Writes a sanitized envelope to a confined local sink. No network. Never live-accepted."""

    def __init__(self, sink_dir: str, *, provider_id: str = "local_sink",
                 outcome: str = ACCEPTED, raise_timeout: bool = False,
                 scripted_events: Optional[List[str]] = None) -> None:
        self.metadata = ProviderMetadata(provider_id=provider_id, readiness="fixture-tested",
                                         idempotency_support=True, sandbox_support=True,
                                         terms_review_status="reviewed_ok")
        self._sink = Path(sink_dir)
        self._outcome = outcome
        self._raise_timeout = raise_timeout
        self.scripted_events = list(scripted_events or [])

    def sender(self) -> tuple:
        return ("qa@local.sink", "QA Radar (local sink)")

    def send(self, envelope: SendEnvelope) -> SendResult:
        if self._raise_timeout:
            raise ProviderTimeout("simulated ambiguous timeout")
        self._sink.mkdir(parents=True, exist_ok=True)
        # Filesystem-safe id (the idempotency key is 'sha256:<hex>' — strip the colon).
        raw = (envelope.idempotency_key or "x").replace("sha256:", "").replace(":", "")
        mid = "local-" + (raw or "x")[:24]
        # Store ONLY the sanitized envelope — no plaintext recipient/body, bounded.
        safe = {**envelope.sanitized(), "provider_message_id": mid}
        (self._sink / f"{mid}.json").write_text(json.dumps(safe, indent=2, sort_keys=True),
                                                encoding="utf-8")
        return SendResult(outcome=self._outcome, provider_message_id=mid,
                          provider_id=self.metadata.provider_id)

    def readiness(self) -> Dict[str, Any]:
        return {"provider_id": self.metadata.provider_id, "readiness": "fixture-tested",
                "network": False, "live_accepted": False}


class SandboxProvider:
    """A sandbox that accepts but reaches no real external recipient."""

    def __init__(self, *, provider_id: str = "sandbox") -> None:
        self.metadata = ProviderMetadata(provider_id=provider_id, readiness="sandbox-accepted",
                                         sandbox_support=True, terms_review_status="reviewed_ok")

    def send(self, envelope: SendEnvelope) -> SendResult:
        return SendResult(outcome=ACCEPTED, provider_message_id="sandbox-" +
                          (envelope.idempotency_key or "x")[:24],
                          provider_id=self.metadata.provider_id, detail={"sandbox": True})

    def readiness(self) -> Dict[str, Any]:
        return {"provider_id": self.metadata.provider_id, "readiness": "sandbox-accepted",
                "live_accepted": False}


class RealEmailAdapter:
    """Real email adapter (e.g. Resend/Gmail). Adapter-ready; only sends when explicitly configured
    (credential present) AND live-approved. No arbitrary-SMTP fallback; fails clearly otherwise."""

    def __init__(self, metadata: ProviderMetadata, *,
                 cred_present: Callable[[str], bool] = lambda _n: False) -> None:
        self.metadata = metadata
        self._cred_present = cred_present

    @property
    def configured(self) -> bool:
        return bool(self.metadata.auth_ref) and self._cred_present(self.metadata.auth_ref)

    def send(self, envelope: SendEnvelope) -> SendResult:
        if not self.configured:
            raise ProviderError(f"provider {self.metadata.provider_id!r} is not configured "
                                "(no credential); no fallback is used")
        # A genuinely configured adapter would call its API here. With no live credential in this
        # environment there is nothing to call, and fabricating a send is not allowed.
        raise ProviderError("live provider adapter has no configured backend to call")

    def readiness(self) -> Dict[str, Any]:
        level = "configured" if self.configured else "adapter-ready"
        return {"provider_id": self.metadata.provider_id, "readiness": level,
                "configured": self.configured, "live_accepted": False}


class ProviderRegistry:
    def __init__(self) -> None:
        self._p: Dict[str, Any] = {}

    def register(self, provider) -> None:
        self._p[provider.metadata.provider_id] = provider

    def get(self, provider_id: str):
        if provider_id not in self._p:
            raise ProviderError(f"unknown provider: {provider_id!r}")
        return self._p[provider_id]

    def snapshot(self) -> List[Dict[str, Any]]:
        return [{"metadata": p.metadata.to_dict(), "readiness": p.readiness()}
                for _, p in sorted(self._p.items())]
