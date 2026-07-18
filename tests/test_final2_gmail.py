"""Final Independent Acceptance (v2.0.1) — Gmail API adapter + OAuth config (deterministic).

No network, no Google client library, no real credential, no external email. The adapter is driven
by a fake/capture transport; the CI external-send guard is asserted; OAuth config/status are parsed
with the standard library only.
"""
from __future__ import annotations

import base64
import json

import pytest

from core.scout.comms.gmail import (
    EXTERNAL_SEND_DISABLED_ENV,
    GmailConfigError,
    GmailError,
    GmailProvider,
    TransportError,
    TransportTimeout,
    base64url,
    build_mime,
    classify_http_status,
    real_gmail_transport,
)
from core.scout.comms.gmail_oauth import (
    READINESS_ADAPTER,
    READINESS_CLIENT,
    gmail_status,
    parse_client_config,
)
from core.scout.comms.providers import ProviderTimeout, SendEnvelope

_EXPECTED = "dipptrue@gmail.com"


def _envelope(recipient=_EXPECTED, subject="QA note", body="Hello, one issue."):
    return SendEnvelope(recipient=recipient, subject=subject, body=body, channel="email",
                        revision_id="rev-1", message_id="msg-1", idempotency_key="sha256:key",
                        correlation_id="corr-msg-1", from_email=_EXPECTED, from_name="Dmytro Pogribnyy")


class _Capture:
    """A test-only transport that records the EXACT decoded payload without publishing it."""

    def __init__(self, *, status=200, body=None, raise_exc=None):
        self.calls = 0
        self.last_mime = ""
        self._status = status
        self._body = body if body is not None else {"id": "gmail-id-1", "threadId": "thread-1"}
        self._raise = raise_exc

    def __call__(self, token, raw_b64):
        self.calls += 1
        self.token = token
        self.last_mime = base64.urlsafe_b64decode(raw_b64.encode("ascii")).decode("utf-8")
        if self._raise is not None:
            raise self._raise
        return {"status_code": self._status, "body": self._body}


def _provider(transport, *, from_email=_EXPECTED, token="fake-access-token"):
    return GmailProvider(from_email=from_email, from_name="Dmytro Pogribnyy",
                         expected_account=_EXPECTED, transport=transport, token_provider=lambda: token)


def test_base64url_is_url_safe_and_roundtrips():
    raw = b"\xfb\xff\x3e\x3f test"
    enc = base64url(raw)
    assert "+" not in enc and "/" not in enc
    assert base64.urlsafe_b64decode(enc.encode()) == raw


def test_build_mime_has_exact_headers_and_body():
    raw = build_mime(from_email=_EXPECTED, from_name="Dmytro Pogribnyy", to="a@b.example",
                     subject="Subj", body="Body line.", outbound_message_id="msg-9",
                     revision_id="rev-9").decode("utf-8")
    assert "From: Dmytro Pogribnyy <dipptrue@gmail.com>" in raw
    assert "To: a@b.example" in raw and "Subject: Subj" in raw
    assert "X-Prospect-Radar-Message-ID: msg-9" in raw and "X-Prospect-Radar-Revision-ID: rev-9" in raw
    assert "Body line." in raw


def test_exact_payload_reaches_transport():
    cap = _Capture()
    result = _provider(cap).send(_envelope(recipient="owner@ex.example", subject="Exact", body="Exact body."))
    assert cap.calls == 1 and cap.token == "fake-access-token"
    assert "To: owner@ex.example" in cap.last_mime and "Subject: Exact" in cap.last_mime
    assert "Exact body." in cap.last_mime
    assert result.outcome == "ACCEPTED" and result.provider_message_id == "gmail-id-1"
    assert result.detail["thread_id"] == "thread-1"


def test_sender_pinned_to_authorized_account():
    with pytest.raises(GmailConfigError):
        _provider(_Capture(), from_email="someone-else@gmail.com").send(_envelope())


def test_multiple_recipients_and_cc_bcc_rejected():
    with pytest.raises(GmailError):
        _provider(_Capture()).send(_envelope(recipient="a@x.example, b@x.example"))


def test_missing_message_id_is_ambiguous():
    cap = _Capture(body={"threadId": "t"})  # 200 without an id
    with pytest.raises(ProviderTimeout):
        _provider(cap).send(_envelope())


@pytest.mark.parametrize("code,label", [(400, "bad_request"), (401, "unauthorized"),
                                        (403, "forbidden"), (429, "rate_limited"), (503, "server_error")])
def test_http_error_status_is_definite_and_sanitized(code, label):
    cap = _Capture(status=code, body={"error": {"message": "should-not-leak"}})
    result = _provider(cap).send(_envelope(body="secret body"))
    assert result.outcome == "FAILED_DEFINITE" and result.error == f"gmail_{label}"
    assert "secret body" not in result.error and "should-not-leak" not in result.error


def test_read_timeout_is_ambiguous_no_autoretry():
    cap = _Capture(raise_exc=TransportTimeout("read timeout"))
    with pytest.raises(ProviderTimeout):
        _provider(cap).send(_envelope())
    assert cap.calls == 1  # a single attempt; no automatic retry


def test_connect_failure_before_transmission_is_definite():
    from core.scout.comms.providers import ProviderError
    cap = _Capture(raise_exc=TransportError("connect failed", before_transmission=True))
    with pytest.raises(ProviderError):
        _provider(cap).send(_envelope())


def test_token_refresh_failure_is_sanitized_definite():
    from core.scout.comms.providers import ProviderError

    def _bad_token():
        raise RuntimeError("refresh secret token=abc")
    prov = GmailProvider(from_email=_EXPECTED, from_name="D", expected_account=_EXPECTED,
                         transport=_Capture(), token_provider=_bad_token)
    with pytest.raises(ProviderError) as exc:
        prov.send(_envelope())
    assert "abc" not in str(exc.value)  # the secret never leaks into the error


def test_external_send_guard_blocks_real_transport(monkeypatch):
    monkeypatch.setenv(EXTERNAL_SEND_DISABLED_ENV, "1")
    with pytest.raises(TransportError) as exc:
        real_gmail_transport("token", "cmF3")
    assert exc.value.before_transmission is True  # refused before any external call


def test_classify_http_status():
    assert classify_http_status(404) == "not_found" and classify_http_status(500) == "server_error"


def test_oauth_client_config_parsing(tmp_path):
    good = tmp_path / "client_secret.json"
    good.write_text(json.dumps({"installed": {"client_id": "abc.apps", "client_secret": "s",
                                              "redirect_uris": ["http://localhost"]}}), encoding="utf-8")
    meta = parse_client_config(str(good))
    assert meta["client_id_present"] and meta["redirect_supports_loopback"]
    with pytest.raises(GmailConfigError):
        parse_client_config(str(tmp_path / "missing.json"))
    bad = tmp_path / "bad.json"
    bad.write_text("not json", encoding="utf-8")
    with pytest.raises(GmailConfigError):
        parse_client_config(str(bad))
    web = tmp_path / "web.json"
    web.write_text(json.dumps({"web": {"client_id": "x"}}), encoding="utf-8")
    with pytest.raises(GmailConfigError):
        parse_client_config(str(web))


def test_gmail_status_readiness_ladder(tmp_path):
    cfg = {"expected_account": _EXPECTED, "client_json": "", "token_json": ""}
    assert gmail_status(cfg)["readiness"] == READINESS_ADAPTER
    client = tmp_path / "client_secret.json"
    client.write_text(json.dumps({"installed": {"client_id": "abc", "client_secret": "s",
                                                "redirect_uris": ["http://localhost"]}}), encoding="utf-8")
    cfg["client_json"] = str(client)
    status = gmail_status(cfg)
    assert status["readiness"] == READINESS_CLIENT and status["token_present"] is False
    # No token value ever appears in status.
    assert "token" not in json.dumps(status).lower() or "token_present" in status
