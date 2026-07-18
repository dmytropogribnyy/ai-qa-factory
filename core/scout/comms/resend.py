"""Optional secondary Resend email provider (Final Independent Acceptance, v2.0.1).

A genuine Resend transactional-API adapter for verified darrowcode.com senders only. Gmail is the
primary provider for v2.0.1 acceptance; Resend stays adapter-ready when no local key is supplied.
The HTTP transport is injected (deterministic tests use a fake transport, no network, no key); the
API key comes from an environment reference only. Exactly one recipient, no CC/BCC, no arbitrary
SMTP fallback. Errors are sanitized and bounded. The real transport refuses to run under the CI
external-send guard.
"""
from __future__ import annotations

import os
from typing import Any, Callable, Dict, Optional

from core.scout.comms.gmail import (
    EXTERNAL_SEND_DISABLED_ENV,
    TransportError,
    TransportTimeout,
    classify_http_status,
)
from core.scout.comms.providers import (
    ACCEPTED,
    FAILED_DEFINITE,
    ProviderError,
    ProviderMetadata,
    ProviderTimeout,
    SendEnvelope,
    SendResult,
)

RESEND_ENDPOINT = "https://api.resend.com/emails"
RESEND_PROVIDER_ID = "resend_email"
ALLOWED_SENDER_DOMAIN = "darrowcode.com"


class ResendError(ProviderError):
    pass


class ResendConfigError(ResendError):
    pass


def real_resend_transport(api_key: str, payload: Dict[str, Any], *, timeout: float = 30.0
                          ) -> Dict[str, Any]:
    """Genuine Resend HTTP transport (standard library). Refuses under the CI external-send guard."""
    if os.environ.get(EXTERNAL_SEND_DISABLED_ENV):
        raise TransportError("external send disabled by CI guard", before_transmission=True)
    import json
    import urllib.error
    import urllib.request
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(RESEND_ENDPOINT, data=data, method="POST", headers={
        "Authorization": f"Bearer {api_key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return {"status_code": resp.status, "body": json.loads(raw) if raw else {}}
    except urllib.error.HTTPError as exc:
        try:
            body = json.loads(exc.read().decode("utf-8", errors="replace") or "{}")
        except (ValueError, OSError):
            body = {}
        return {"status_code": exc.code, "body": body}
    except TimeoutError as exc:
        raise TransportTimeout("resend read timeout") from exc
    except urllib.error.URLError as exc:
        raise TransportError("resend connection failure", before_transmission=True) from exc


class ResendProvider:
    def __init__(self, *, from_email: str, reply_to: str,
                 transport: Callable[[str, Dict[str, Any]], Dict[str, Any]],
                 api_key_provider: Callable[[], str], readiness: str = "adapter-ready") -> None:
        if from_email and not from_email.endswith("@" + ALLOWED_SENDER_DOMAIN):
            raise ResendConfigError(f"resend sender must be a verified {ALLOWED_SENDER_DOMAIN} address")
        self.metadata = ProviderMetadata(provider_id=RESEND_PROVIDER_ID, channel="email",
                                         readiness=readiness, auth_ref="RESEND_API_KEY",
                                         idempotency_support=True, terms_review_status="reviewed_ok")
        self._from_email = from_email
        self._reply_to = reply_to
        self._transport = transport
        self._api_key_provider = api_key_provider

    def sender(self) -> tuple:
        return (self._from_email, "QA Radar")

    def send(self, envelope: SendEnvelope) -> SendResult:
        if not self._from_email:
            raise ResendConfigError("resend sender is not configured (no verified domain address)")
        if "," in envelope.recipient or not envelope.recipient.strip():
            raise ResendError("resend requires exactly one recipient (no CC/BCC, no multiple)")
        payload = {"from": self._from_email, "to": [envelope.recipient], "subject": envelope.subject,
                   "text": envelope.body}
        if self._reply_to:
            payload["reply_to"] = self._reply_to
        try:
            api_key = self._api_key_provider()
        except Exception as exc:  # noqa: BLE001
            raise ProviderError(f"resend key unavailable: {type(exc).__name__}") from None
        if not api_key:
            raise ResendConfigError("resend API key is not configured (env reference only)")
        try:
            resp = self._transport(api_key, payload)
        except TransportTimeout:
            raise ProviderTimeout("resend ambiguous read timeout after transmission") from None
        except TransportError as exc:
            if exc.before_transmission:
                raise ProviderError("resend definite failure before transmission") from None
            raise ProviderTimeout("resend ambiguous transport error") from None
        status = int(resp.get("status_code", 0))
        body = resp.get("body") or {}
        if status in (200, 201):
            mid = body.get("id")
            if not mid:
                raise ProviderTimeout("resend success without an id (ambiguous)")
            return SendResult(outcome=ACCEPTED, provider_message_id=str(mid),
                              provider_id=RESEND_PROVIDER_ID)
        return SendResult(outcome=FAILED_DEFINITE, provider_id=RESEND_PROVIDER_ID,
                          error=f"resend_{classify_http_status(status)}")

    def readiness(self) -> Dict[str, Any]:
        return {"provider_id": RESEND_PROVIDER_ID, "readiness": self.metadata.readiness,
                "sender": self._from_email, "configured": bool(self._from_email), "live_accepted": False}


def resend_config_from_env(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    e = env if env is not None else os.environ
    return {"from_email": e.get("RESEND_FROM_EMAIL", ""), "reply_to": e.get("RESEND_REPLY_TO", ""),
            "api_key_ref": "RESEND_API_KEY", "api_key_present": bool(e.get("RESEND_API_KEY"))}
