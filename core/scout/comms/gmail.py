"""Genuine Gmail API send provider (Final Independent Acceptance, v2.0.1).

A real Gmail API adapter (NOT browser automation, SMTP, or an app password): it builds an
RFC-compliant MIME message with the standard library, URL-safe-base64-encodes it, and POSTs
``{"raw": ...}`` to ``users.messages.send``. The HTTP transport and the access-token provider are
INJECTED, so deterministic tests exercise the exact payload with a fake transport and no network,
no Google client library, and no credential. The real transport refuses to run when the CI external
-send guard is set. The sender is pinned to the single authorized account; there is no CC/BCC and
no multiple recipients. Errors are sanitized and bounded — the recipient, body, token, and raw
Gmail response never appear in logs, errors, or artifacts. Exactly-once delivery is NOT claimed.
"""
from __future__ import annotations

import base64
import os
from email.message import EmailMessage
from email.utils import formataddr
from typing import Any, Callable, Dict, Optional

from core.scout.comms.providers import (
    ACCEPTED,
    FAILED_DEFINITE,
    ProviderError,
    ProviderMetadata,
    ProviderTimeout,
    SendEnvelope,
    SendResult,
)

GMAIL_SEND_ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"
GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GMAIL_IDENTITY_SCOPES = ("openid", "email")
REQUIRED_GMAIL_SCOPES = (GMAIL_SEND_SCOPE, *GMAIL_IDENTITY_SCOPES)
# Scopes that must NEVER be requested/stored/used for basic send-only authorization.
FORBIDDEN_GMAIL_SCOPES = frozenset({
    "https://mail.google.com/", "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.readonly", "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.metadata"})
GMAIL_PROVIDER_ID = "gmail_personal"
EXPECTED_ACCOUNT_DEFAULT = "dipptrue@gmail.com"
EXTERNAL_SEND_DISABLED_ENV = "PROSPECT_RADAR_EXTERNAL_SEND_DISABLED"


class GmailError(ProviderError):
    pass


class GmailConfigError(GmailError):
    pass


class TransportTimeout(Exception):
    """A read timeout AFTER the request was transmitted — the outcome is ambiguous."""


class TransportError(Exception):
    """A transport failure. ``before_transmission`` True => the request never left (definite)."""

    def __init__(self, message: str, *, before_transmission: bool = False) -> None:
        super().__init__(message)
        self.before_transmission = before_transmission


def base64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii")


def build_mime(*, from_email: str, from_name: str, to: str, subject: str, body: str,
               outbound_message_id: str, revision_id: str) -> bytes:
    """Build an RFC-compliant plain-text MIME message with deterministic correlation headers."""
    msg = EmailMessage()
    msg["From"] = formataddr((from_name, from_email)) if from_name else from_email
    msg["To"] = to
    msg["Subject"] = subject
    # Deterministic, stable correlation headers (not claimed to be a Gmail idempotency mechanism).
    msg["Message-ID"] = f"<{outbound_message_id}@prospect-radar>"
    msg["X-Prospect-Radar-Message-ID"] = outbound_message_id
    msg["X-Prospect-Radar-Revision-ID"] = revision_id
    msg.set_content(body)
    return msg.as_bytes()


def classify_http_status(status_code: int) -> str:
    return {400: "bad_request", 401: "unauthorized", 403: "forbidden", 404: "not_found",
            429: "rate_limited"}.get(status_code,
                                     "server_error" if 500 <= status_code < 600 else f"http_{status_code}")


def real_gmail_transport(token: str, raw_b64: str, *, timeout: float = 30.0) -> Dict[str, Any]:
    """The genuine HTTP transport (standard-library urllib). Refuses to make any external call when
    the CI external-send guard is set. Returns {"status_code", "body"}; raises TransportTimeout /
    TransportError. No Google client library is required for the POST itself."""
    if os.environ.get(EXTERNAL_SEND_DISABLED_ENV):
        raise TransportError("external send disabled by CI guard", before_transmission=True)
    import json
    import urllib.error
    import urllib.request
    data = json.dumps({"raw": raw_b64}).encode("utf-8")
    req = urllib.request.Request(GMAIL_SEND_ENDPOINT, data=data, method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            return {"status_code": resp.status, "body": json.loads(raw) if raw else {}}
    except urllib.error.HTTPError as exc:  # a definite HTTP error response (4xx/5xx)
        try:
            body = json.loads(exc.read().decode("utf-8", errors="replace") or "{}")
        except (ValueError, OSError):
            body = {}
        return {"status_code": exc.code, "body": body}
    except TimeoutError as exc:  # read timeout — request may already have been transmitted
        raise TransportTimeout("gmail read timeout") from exc
    except urllib.error.URLError as exc:  # connection failure before transmission
        raise TransportError("gmail connection failure", before_transmission=True) from exc


class GmailProvider:
    """Send exactly one approved message through the Gmail API using an injected transport + token
    provider. The sender is pinned to the authorized account; no CC/BCC, no multiple recipients."""

    def __init__(self, *, from_email: str, from_name: str, expected_account: str,
                 transport: Callable[[str, str], Dict[str, Any]],
                 token_provider: Callable[[], str],
                 status_provider: Optional[Callable[[], Dict[str, Any]]] = None,
                 readiness: str = "adapter-ready") -> None:
        self.metadata = ProviderMetadata(provider_id=GMAIL_PROVIDER_ID, channel="email",
                                         readiness=readiness, auth_ref="GMAIL_OAUTH_TOKEN_JSON",
                                         idempotency_support=False, terms_review_status="reviewed_ok")
        self._from_email = from_email
        self._from_name = from_name
        self._expected_account = expected_account
        self._transport = transport
        self._token_provider = token_provider
        self._status_provider = status_provider

    def sender(self) -> tuple:
        return (self._from_email, self._from_name)

    def preflight(self) -> list:
        """Readiness check WITHOUT any network call — proves the operator can send live before the
        send service consumes an approval. Unconfigured/unauthorized/wrong-account/insufficient-scope
        all block. With no status provider (deterministic transport-only tests) it is treated ready."""
        if self._status_provider is None:
            return []
        s = self._status_provider() or {}
        blockers = []
        if not s.get("client_config_present"):
            blockers.append("gmail_oauth_client_not_configured")
        elif not s.get("token_present"):
            blockers.append("gmail_not_authorized")
        elif not s.get("refreshable"):
            blockers.append("gmail_token_not_refreshable")
        scopes = set(s.get("scopes", []))
        if GMAIL_SEND_SCOPE not in scopes:
            blockers.append("gmail_missing_send_scope")
        if scopes & FORBIDDEN_GMAIL_SCOPES:
            blockers.append("gmail_forbidden_scope")
        if not s.get("expected_account_match"):
            blockers.append("gmail_account_not_verified")
        return sorted(set(blockers))

    def send(self, envelope: SendEnvelope) -> SendResult:
        # Sender is pinned to the single authorized account.
        if self._from_email != self._expected_account:
            raise GmailConfigError("gmail sender must be the authorized account")
        # Exactly one recipient; no CC/BCC.
        if "," in envelope.recipient or not envelope.recipient.strip():
            raise GmailError("gmail requires exactly one recipient (no CC/BCC, no multiple)")
        raw = build_mime(from_email=self._from_email, from_name=self._from_name,
                         to=envelope.recipient, subject=envelope.subject, body=envelope.body,
                         outbound_message_id=envelope.message_id, revision_id=envelope.revision_id)
        b64 = base64url(raw)
        try:
            token = self._token_provider()          # real: refreshes; may raise on refresh failure
        except Exception as exc:  # noqa: BLE001 - sanitize any oauth/refresh error
            raise ProviderError(f"gmail token unavailable: {type(exc).__name__}") from None
        try:
            resp = self._transport(token, b64)      # exactly one external call
        except TransportTimeout:
            raise ProviderTimeout("gmail ambiguous read timeout after transmission") from None
        except TransportError as exc:
            if exc.before_transmission:
                raise ProviderError("gmail definite failure before transmission") from None
            raise ProviderTimeout("gmail ambiguous transport error") from None
        return self._classify(resp)

    def _classify(self, resp: Dict[str, Any]) -> SendResult:
        status = int(resp.get("status_code", 0))
        body = resp.get("body") or {}
        if status == 200:
            mid = body.get("id")
            if not mid:
                raise ProviderTimeout("gmail 200 without message id (ambiguous)")
            return SendResult(outcome=ACCEPTED, provider_message_id=str(mid),
                              provider_id=GMAIL_PROVIDER_ID,
                              detail={"thread_id": str(body.get("threadId", ""))})
        return SendResult(outcome=FAILED_DEFINITE, provider_id=GMAIL_PROVIDER_ID,
                          error=f"gmail_{classify_http_status(status)}")

    def readiness(self) -> Dict[str, Any]:
        return {"provider_id": GMAIL_PROVIDER_ID, "readiness": self.metadata.readiness,
                "sender": self._from_email, "expected_account": self._expected_account,
                "live_accepted": False}


def gmail_config_from_env(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Read Gmail configuration from environment references only (never secret values)."""
    e = env if env is not None else os.environ
    return {"from_email": e.get("GMAIL_FROM_EMAIL", EXPECTED_ACCOUNT_DEFAULT),
            "from_name": e.get("GMAIL_FROM_NAME", "Dmytro Pogribnyy"),
            "expected_account": e.get("GMAIL_EXPECTED_ACCOUNT", EXPECTED_ACCOUNT_DEFAULT),
            "client_json": e.get("GMAIL_OAUTH_CLIENT_JSON", ""),
            "token_json": e.get("GMAIL_OAUTH_TOKEN_JSON", "")}
