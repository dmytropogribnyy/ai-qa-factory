"""v3.2 final email architecture - the SECOND identity: a read-only technical QA test inbox that is
strictly separated from the Scout SEND provider. Deterministic: injected transports, no network, no
Google client, no credential, no email. Covers two-token separation, scope refusal, account mismatch,
alias filtering, bounded correlation, and the no-secret / no-generic-read guarantees.
"""
from __future__ import annotations

import base64
import json

import pytest

from core.scout.comms.gmail import GMAIL_SEND_SCOPE
from core.scout.comms.test_inbox import (
    FORBIDDEN_TEST_INBOX_SCOPES,
    GMAIL_READONLY_SCOPE,
    TEST_ALIAS_TEMPLATE_DEFAULT,
    build_readonly_token_provider,
    build_test_alias,
    safe_project_slug,
)
# Alias the identifiers whose names begin with `test_`/`Test` so pytest does not mis-collect the
# imported production symbols as test items.
from core.scout.comms.test_inbox import TestAliasError as AliasError
from core.scout.comms.test_inbox import TestInboxError as InboxError
from core.scout.comms.test_inbox import TestInboxReader as InboxReader
from core.scout.comms.test_inbox import test_inbox_config_from_env as _cfg_from_env
from core.scout.comms.test_inbox import test_inbox_scope_blockers as _scope_blockers
from core.scout.comms.test_inbox import test_inbox_status as _status

_MAILBOX = "drdiplextech@gmail.com"
_SENDER = "dipptrue@gmail.com"
_READONLY = [GMAIL_READONLY_SCOPE, "openid", "email"]


def _jwt(email: str) -> str:
    def part(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    payload = {"iss": "https://accounts.google.com", "sub": "s", "email": email,
               "email_verified": True, "aud": "aud"}
    return f"{part({'alg': 'RS256'})}.{part(payload)}.sig"


def _client(tmp_path):
    p = tmp_path / "client_secret.json"
    p.write_text(json.dumps({"installed": {"client_id": "aud", "client_secret": "s",
                                           "redirect_uris": ["http://localhost"]}}), encoding="utf-8")
    return p


def _token(tmp_path, name, *, account=_MAILBOX, scopes=None, refresh=True):
    p = tmp_path / name
    data = {"token": "a", "id_token": _jwt(account), "account": account,
            "scopes": scopes if scopes is not None else _READONLY}
    if refresh:
        data["refresh_token"] = "r"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


# --- scope policy: the read token can never carry a send scope ------------------------------------
def test_readonly_scope_policy_forbids_send_and_requires_readonly():
    assert _scope_blockers(_READONLY) == []
    assert "missing_readonly_scope" in _scope_blockers(["openid", "email"])
    # A MIXED token that also holds gmail.send is refused (identities must not collapse).
    assert "forbidden_scope" in _scope_blockers([*_READONLY, GMAIL_SEND_SCOPE])
    assert GMAIL_SEND_SCOPE in FORBIDDEN_TEST_INBOX_SCOPES


# --- alias slug validation + fallback ------------------------------------------------------------
def test_alias_building_and_slug_validation():
    assert build_test_alias(TEST_ALIAS_TEMPLATE_DEFAULT, "aiqa-selftest") == \
        "drdiplextech+aiqa-selftest@gmail.com"
    # A target that rejects plus addressing falls back to the base mailbox.
    assert build_test_alias(TEST_ALIAS_TEMPLATE_DEFAULT, "aiqa-selftest", plus_addressing=False) == \
        _MAILBOX


@pytest.mark.parametrize("bad", ["", "a..b", "-x", "x-", "a b", "A@b.com", "x--y", "проект", "a+b",
                                 "x" * 41])
def test_malformed_project_id_fails_closed(bad):
    with pytest.raises(AliasError):
        safe_project_slug(bad)
    with pytest.raises(AliasError):
        build_test_alias(TEST_ALIAS_TEMPLATE_DEFAULT, bad)


# --- readiness: independent, and fails closed on mixed store / mixed token / wrong account --------
def test_status_ready_when_readonly_authorized(tmp_path):
    cfg = {"expected_account": _MAILBOX, "client_json": str(_client(tmp_path)),
           "token_json": str(_token(tmp_path, "test_token.json")), "send_token_json": ""}
    st = _status(cfg)
    assert st["scopes_ok"] and st["refreshable"] and st["distinct_token_store"]
    assert st["expected_account_claim_match"] and st["identity_verification"] == "live-required"


def test_status_fails_closed_when_token_store_shared_with_send(tmp_path):
    shared = _token(tmp_path, "shared_token.json")
    cfg = {"expected_account": _MAILBOX, "client_json": str(_client(tmp_path)),
           "token_json": str(shared), "send_token_json": str(shared)}
    st = _status(cfg)
    assert st["distinct_token_store"] is False and st["expected_account_claim_match"] is False


def test_status_fails_closed_on_mixed_send_scope_token(tmp_path):
    tok = _token(tmp_path, "mixed.json", scopes=[*_READONLY, GMAIL_SEND_SCOPE])
    cfg = {"expected_account": _MAILBOX, "client_json": str(_client(tmp_path)),
           "token_json": str(tok), "send_token_json": ""}
    st = _status(cfg)
    assert st["scopes_ok"] is False and st["expected_account_claim_match"] is False


def test_status_fails_closed_on_wrong_account(tmp_path):
    tok = _token(tmp_path, "wrong.json", account="someone-else@gmail.com")
    cfg = {"expected_account": _MAILBOX, "client_json": str(_client(tmp_path)),
           "token_json": str(tok), "send_token_json": ""}
    assert _status(cfg)["expected_account_claim_match"] is False


def test_status_fails_closed_without_refresh_token(tmp_path):
    tok = _token(tmp_path, "norefresh.json", refresh=False)
    cfg = {"expected_account": _MAILBOX, "client_json": str(_client(tmp_path)),
           "token_json": str(tok), "send_token_json": ""}
    assert _status(cfg)["expected_account_claim_match"] is False


def test_config_from_env_never_falls_back_to_send_token(monkeypatch):
    monkeypatch.setenv("GMAIL_OAUTH_CLIENT_JSON", "/shared/client.json")
    monkeypatch.setenv("GMAIL_OAUTH_TOKEN_JSON", "/send/token.json")
    monkeypatch.delenv("GMAIL_TEST_OAUTH_CLIENT_JSON", raising=False)
    monkeypatch.delenv("GMAIL_TEST_OAUTH_TOKEN_JSON", raising=False)
    cfg = _cfg_from_env()
    # The client config MAY reuse the shared Desktop client...
    assert cfg["client_json"] == "/shared/client.json"
    # ...but the token store must be its own; it NEVER inherits the send token.
    assert cfg["token_json"] == "" and cfg["send_token_json"] == "/send/token.json"
    assert cfg["expected_account"] == _MAILBOX


# --- bounded correlated retrieval (injected transports) ------------------------------------------
def _reader(list_transport, get_transport, *, status_ok=True, identity=_MAILBOX):
    return InboxReader(
        expected_account=_MAILBOX, test_mailbox=_MAILBOX,
        list_transport=list_transport, get_transport=get_transport, token_provider=lambda: "tok",
        status_provider=(lambda: {"distinct_token_store": True, "client_config_present": True,
                                  "token_present": True, "refreshable": True, "scopes": _READONLY})
        if status_ok else (lambda: {"distinct_token_store": True, "client_config_present": True,
                                    "token_present": True, "refreshable": True,
                                    "scopes": ["openid", "email"]}),
        identity_prover=(lambda: identity))


def _msg(mid, to, frm, subject, snippet):
    return {"id": mid, "snippet": snippet, "payload": {"headers": [
        {"name": "To", "value": to}, {"name": "From", "value": frm},
        {"name": "Subject", "value": subject}, {"name": "Date", "value": "Sat, 19 Jul 2026 00:00"}]}}


def test_correlated_search_returns_only_the_matching_message():
    alias = "drdiplextech+aiqa-selftest@gmail.com"
    calls = {}
    store = {
        "m1": _msg("m1", alias, _SENDER, "AIQA self-test 42", "hello"),
        # An UNCORRELATED message (different recipient) that the list step might over-return:
        "m2": _msg("m2", "drdiplextech+other@gmail.com", _SENDER, "unrelated", "secret personal note")}

    def _list(token, query, n):
        calls["query"] = query
        return ["m1", "m2"]
    hits = _reader(_list, lambda t, mid: store[mid]).correlated_search(
        alias=alias, from_email=_SENDER, subject_contains="AIQA self-test")
    assert [h["id"] for h in hits] == ["m1"]                    # only the correlated message
    assert f"to:{alias}" in calls["query"] and "newer_than:" in calls["query"]
    assert "secret personal note" not in json.dumps(hits)      # the uncorrelated body never surfaces


def test_reader_refuses_a_foreign_recipient_it_is_not_a_generic_reader():
    r = _reader(lambda *a: [], lambda *a: {})
    for foreign in ["victim@gmail.com", "drdiplextech@evil.com", "attacker+drdiplextech@gmail.com"]:
        with pytest.raises(InboxError):
            r.correlated_search(alias=foreign)


def test_reader_fails_closed_when_scopes_insufficient():
    r = _reader(lambda *a: ["m1"], lambda *a: {}, status_ok=False)
    with pytest.raises(InboxError):
        r.correlated_search(alias="drdiplextech+x@gmail.com")


def test_reader_fails_closed_when_identity_unproven():
    r = _reader(lambda *a: [], lambda *a: {}, identity="someone-else@gmail.com")
    with pytest.raises(InboxError):
        r.correlated_search(alias="drdiplextech+x@gmail.com")


def test_readonly_token_provider_requests_readonly_scopes_only(monkeypatch):
    # The refreshing provider must load credentials with the READ-ONLY scopes, never the send scope.
    captured = {}

    class _FakeCreds:
        valid = True
        token = "access"

    class _Credentials:
        @staticmethod
        def from_authorized_user_file(path, scopes):
            captured["scopes"] = list(scopes)
            return _FakeCreds()

    import sys
    import types
    mod = types.ModuleType("google.oauth2.credentials")
    mod.Credentials = _Credentials
    monkeypatch.setitem(sys.modules, "google.oauth2.credentials", mod)
    req = types.ModuleType("google.auth.transport.requests")
    req.Request = object
    monkeypatch.setitem(sys.modules, "google.auth.transport.requests", req)
    assert build_readonly_token_provider("t.json")() == "access"
    assert GMAIL_READONLY_SCOPE in captured["scopes"] and GMAIL_SEND_SCOPE not in captured["scopes"]


def test_e2e_self_test_send_then_correlated_read_with_two_distinct_tokens():
    # A controlled injected-transport E2E of the exact self-test contract: the SEND identity
    # (dipptrue, send token) sends one message to the test alias; the READ identity (drdiplextech,
    # a DISTINCT read-only token) retrieves only that correlated message. No network, no real token.
    from core.scout.comms.gmail import GmailProvider
    from core.scout.comms.providers import ACCEPTED, SendEnvelope

    alias = build_test_alias(TEST_ALIAS_TEMPLATE_DEFAULT, "aiqa-selftest")
    subject, body = "AIQA self-test", "harmless self-test; please ignore"

    send_calls = {}

    def _send_transport(token, raw_b64):
        send_calls["token"], send_calls["raw"] = token, raw_b64
        return {"status_code": 200, "body": {"id": "sent-1", "threadId": "th-1"}}

    sender = GmailProvider(from_email=_SENDER, from_name="Dmytro Pogribnyy",
                           expected_account=_SENDER, transport=_send_transport,
                           token_provider=lambda: "SEND-TOKEN")
    result = sender.send(SendEnvelope(recipient=alias, subject=subject, body=body, channel="email",
                                      revision_id="r1", message_id="m1", idempotency_key="k1"))
    assert result.outcome == ACCEPTED and send_calls["token"] == "SEND-TOKEN"

    # The delivered message now appears in the test inbox; the reader uses its OWN read token.
    delivered = _msg("sent-1", alias, _SENDER, subject, "harmless self-test; please ignore")
    read_calls = {}

    def _list(token, query, n):
        read_calls["token"], read_calls["query"] = token, query
        return ["sent-1"]

    reader = InboxReader(
        expected_account=_MAILBOX, test_mailbox=_MAILBOX, list_transport=_list,
        get_transport=lambda t, mid: delivered, token_provider=lambda: "READ-TOKEN",
        status_provider=lambda: {"distinct_token_store": True, "client_config_present": True,
                                 "token_present": True, "refreshable": True, "scopes": _READONLY},
        identity_prover=lambda: _MAILBOX)
    hits = reader.correlated_search(alias=alias, from_email=_SENDER, subject_contains=subject)
    assert [h["id"] for h in hits] == ["sent-1"] and hits[0]["to"] == alias
    # The two identities used two DISTINCT tokens; neither token crossed over.
    assert read_calls["token"] == "READ-TOKEN" and read_calls["token"] != send_calls["token"]


def test_no_token_or_secret_value_appears_in_status_or_hits(tmp_path):
    tok = _token(tmp_path, "t.json")
    # Inject a fake secret value to prove it is never surfaced.
    data = json.loads(tok.read_text(encoding="utf-8"))
    data["token"] = "SECRET-ACCESS-TOKEN"
    data["refresh_token"] = "SECRET-REFRESH-TOKEN"
    tok.write_text(json.dumps(data), encoding="utf-8")
    cfg = {"expected_account": _MAILBOX, "client_json": str(_client(tmp_path)),
           "token_json": str(tok), "send_token_json": ""}
    blob = json.dumps(_status(cfg))
    assert "SECRET-ACCESS-TOKEN" not in blob and "SECRET-REFRESH-TOKEN" not in blob
