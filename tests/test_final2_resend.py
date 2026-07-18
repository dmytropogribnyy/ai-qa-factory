"""Final Independent Acceptance (v2.0.1) — optional Resend secondary adapter (deterministic)."""
from __future__ import annotations

import pytest

from core.scout.comms.gmail import EXTERNAL_SEND_DISABLED_ENV, TransportError, TransportTimeout
from core.scout.comms.providers import ProviderError, ProviderTimeout, SendEnvelope
from core.scout.comms.resend import (
    ResendConfigError,
    ResendError,
    ResendProvider,
    real_resend_transport,
    resend_config_from_env,
)

_FROM = "qa@darrowcode.com"


def _envelope(recipient="owner@darrowcode.com", subject="Note", body="Body."):
    return SendEnvelope(recipient=recipient, subject=subject, body=body, channel="email",
                        revision_id="rev-1", message_id="m-1", idempotency_key="k", from_email=_FROM)


class _Capture:
    def __init__(self, *, status=200, body=None, raise_exc=None):
        self.calls = 0
        self.payload = None
        self._status, self._body, self._raise = status, body or {"id": "re-1"}, raise_exc

    def __call__(self, key, payload):
        self.calls += 1
        self.key, self.payload = key, payload
        if self._raise:
            raise self._raise
        return {"status_code": self._status, "body": self._body}


def _provider(transport, *, from_email=_FROM, reply_to="dipptrue@gmail.com", key="re_key"):
    return ResendProvider(from_email=from_email, reply_to=reply_to, transport=transport,
                          api_key_provider=lambda: key)


def test_sender_must_be_darrowcode_domain():
    with pytest.raises(ResendConfigError):
        ResendProvider(from_email="dipptrue@gmail.com", reply_to="", transport=_Capture(),
                       api_key_provider=lambda: "k")


def test_exact_payload_and_reply_to_reach_transport():
    cap = _Capture()
    result = _provider(cap).send(_envelope(recipient="p@darrowcode.com", subject="Hi", body="Exact."))
    assert cap.calls == 1 and cap.key == "re_key"
    assert cap.payload["from"] == _FROM and cap.payload["to"] == ["p@darrowcode.com"]
    assert cap.payload["subject"] == "Hi" and cap.payload["text"] == "Exact."
    assert cap.payload["reply_to"] == "dipptrue@gmail.com"
    assert result.outcome == "ACCEPTED" and result.provider_message_id == "re-1"


def test_multiple_recipients_rejected():
    with pytest.raises(ResendError):
        _provider(_Capture()).send(_envelope(recipient="a@darrowcode.com, b@darrowcode.com"))


def test_missing_key_is_config_error():
    prov = ResendProvider(from_email=_FROM, reply_to="", transport=_Capture(),
                          api_key_provider=lambda: "")
    with pytest.raises(ResendConfigError):
        prov.send(_envelope())


def test_http_error_is_sanitized_definite():
    result = _provider(_Capture(status=422, body={"message": "leak"})).send(_envelope(body="secret"))
    assert result.outcome == "FAILED_DEFINITE" and "secret" not in result.error and "leak" not in result.error


def test_read_timeout_is_ambiguous():
    with pytest.raises(ProviderTimeout):
        _provider(_Capture(raise_exc=TransportTimeout("t"))).send(_envelope())


def test_connect_failure_before_send_is_definite():
    with pytest.raises(ProviderError):
        _provider(_Capture(raise_exc=TransportError("x", before_transmission=True))).send(_envelope())


def test_external_send_guard_blocks_real_transport(monkeypatch):
    monkeypatch.setenv(EXTERNAL_SEND_DISABLED_ENV, "1")
    with pytest.raises(TransportError) as exc:
        real_resend_transport("key", {"from": _FROM, "to": ["x@darrowcode.com"]})
    assert exc.value.before_transmission is True


def test_config_from_env_is_reference_only():
    cfg = resend_config_from_env({"RESEND_FROM_EMAIL": _FROM, "RESEND_API_KEY": "re_secret"})
    assert cfg["from_email"] == _FROM and cfg["api_key_ref"] == "RESEND_API_KEY"
    assert cfg["api_key_present"] is True and "re_secret" not in str(cfg)
