"""v3.0.0 Milestone 0 — Gmail identity integrity via the official injectable verifier (deterministic).

No real Google client, no OAuth flow, no network, no credential, no email. The production path uses
google.oauth2.id_token.verify_oauth2_token; tests inject a fake verifier with realistic claims.
"""
from __future__ import annotations

import base64
import json

import pytest

from core.scout.comms.gmail import (
    EXTERNAL_SEND_DISABLED_ENV,
    GMAIL_SEND_SCOPE,
    GmailConfigError,
    gmail_scope_blockers,
)
from core.scout.comms.gmail_oauth import (
    official_id_token_verifier,
    parse_client_config,
    prove_current_identity,
    validate_scopes,
    verify_gmail_identity,
    verify_identity_claims,
)

_EXPECTED = "dipptrue@gmail.com"
_AUD = "aud-123.apps.googleusercontent.com"


def _jwt(payload: dict) -> str:
    def part(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{part({'alg': 'RS256'})}.{part(payload)}.signature"


def _claims(email=_EXPECTED, *, iss="https://accounts.google.com", sub="sub-1", verified=True,
            aud=_AUD):
    return {"iss": iss, "sub": sub, "email": email, "email_verified": verified, "aud": aud}


def _verifier(claims, *, sig_valid=True, enforce_aud=True):
    def _verify(id_token, audience):
        if not sig_valid:
            raise GmailConfigError("id-token verification failed: invalid signature")
        if enforce_aud and claims.get("aud") != audience:
            raise GmailConfigError("id-token verification failed: wrong audience")
        return claims
    return _verify


# --- claim-content validation (verify_identity_claims) --------------------------------------------

def test_valid_claims_return_email():
    assert verify_identity_claims(_claims(), expected_account=_EXPECTED) == _EXPECTED


@pytest.mark.parametrize("claims", [
    _claims(iss="https://evil.example"),          # wrong issuer
    {k: v for k, v in _claims().items() if k != "sub"},   # missing subject
    _claims(verified=False),                       # email_verified False
    {k: v for k, v in _claims().items() if k != "email_verified"},  # email_verified missing
    {k: v for k, v in _claims().items() if k != "email"},  # missing email
    _claims("someone-else@gmail.com"),            # wrong email
])
def test_bad_claims_rejected(claims):
    with pytest.raises(GmailConfigError):
        verify_identity_claims(claims, expected_account=_EXPECTED)


# --- verifier-level rejection (verify_gmail_identity) ---------------------------------------------

def test_forged_signature_rejected():
    with pytest.raises(GmailConfigError):
        verify_gmail_identity(_jwt(_claims()), audience=_AUD, expected_account=_EXPECTED,
                              verifier=_verifier(_claims(), sig_valid=False))


def test_wrong_audience_rejected():
    with pytest.raises(GmailConfigError):  # configured audience differs from the token's aud
        verify_gmail_identity(_jwt(_claims()), audience="other-audience", expected_account=_EXPECTED,
                              verifier=_verifier(_claims(aud=_AUD)))


def test_missing_id_token_and_audience_rejected():
    with pytest.raises(GmailConfigError):
        verify_gmail_identity("", audience=_AUD, expected_account=_EXPECTED,
                              verifier=_verifier(_claims()))
    with pytest.raises(GmailConfigError):
        verify_gmail_identity(_jwt(_claims()), audience="", expected_account=_EXPECTED,
                              verifier=_verifier(_claims()))


def test_decoded_valid_jwt_is_not_proof_when_signature_invalid():
    # The JWT payload decodes to a valid verified email, but a forged signature must still be rejected
    # (the system relies on the official verifier, never the manual base64 decode).
    forged = _jwt({"email": _EXPECTED, "email_verified": True, "iss": "https://accounts.google.com",
                   "sub": "s", "aud": _AUD})
    with pytest.raises(GmailConfigError):
        verify_gmail_identity(forged, audience=_AUD, expected_account=_EXPECTED,
                              verifier=_verifier(_claims(), sig_valid=False))


# --- official verifier guard + scopes + client config --------------------------------------------

def test_official_verifier_refuses_under_external_send_guard(monkeypatch):
    monkeypatch.setenv(EXTERNAL_SEND_DISABLED_ENV, "1")
    with pytest.raises(GmailConfigError):     # refuses BEFORE any import or network call
        official_id_token_verifier(_jwt(_claims()), _AUD)


def test_scope_validation():
    assert validate_scopes([GMAIL_SEND_SCOPE, "openid", "email"]) == []
    assert "missing_send_scope" in validate_scopes(["openid", "email"])
    assert "missing_openid_scope" in gmail_scope_blockers([GMAIL_SEND_SCOPE, "email"])
    assert "missing_email_scope" in gmail_scope_blockers([GMAIL_SEND_SCOPE, "openid"])
    assert "forbidden_scope" in gmail_scope_blockers(
        [GMAIL_SEND_SCOPE, "openid", "email", "https://www.googleapis.com/auth/gmail.readonly"])
    # Google's canonical email scope is accepted in place of the short form.
    assert validate_scopes([GMAIL_SEND_SCOPE, "openid",
                            "https://www.googleapis.com/auth/userinfo.email"]) == []


def test_parse_client_config_exposes_client_id_not_secret(tmp_path):
    p = tmp_path / "client_secret.json"
    p.write_text(json.dumps({"installed": {"client_id": "abc.apps", "client_secret": "TOP_SECRET",
                                           "redirect_uris": ["http://localhost"]}}), encoding="utf-8")
    meta = parse_client_config(str(p))
    assert meta["client_id"] == "abc.apps" and meta["client_secret_present"] is True
    assert "TOP_SECRET" not in json.dumps(meta)     # the secret value is never exposed


# --- live identity prover (prove_current_identity) ------------------------------------------------

def _configured(tmp_path, *, email=_EXPECTED):
    client = tmp_path / "client_secret.json"
    client.write_text(json.dumps({"installed": {"client_id": _AUD, "client_secret": "s",
                                                 "redirect_uris": ["http://localhost"]}}),
                      encoding="utf-8")
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"token": "a", "refresh_token": "r", "id_token": _jwt(_claims(email)),
                                 "account": email, "scopes": [GMAIL_SEND_SCOPE, "openid", "email"]}),
                     encoding="utf-8")
    return {"expected_account": _EXPECTED, "client_json": str(client), "token_json": str(token)}


def test_prove_current_identity_success(tmp_path):
    cfg = _configured(tmp_path)
    assert prove_current_identity(cfg, verifier=_verifier(_claims())) == _EXPECTED


def test_prove_current_identity_fails_on_invalid_signature(tmp_path):
    cfg = _configured(tmp_path)
    with pytest.raises(GmailConfigError):
        prove_current_identity(cfg, verifier=_verifier(_claims(), sig_valid=False))
