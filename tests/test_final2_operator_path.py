"""Final Operator-Path Hotfix (v2.0.2) — Gmail wired into the real CLI + fail-closed OAuth.

Deterministic; no real Google client, no OAuth flow, no network, no real recipient, no real email.
"""
from __future__ import annotations

import base64
import json

import pytest

from core.scout.comms.approval import approve_revision, build_revision
from core.scout.comms.gmail import (
    EXTERNAL_SEND_DISABLED_ENV,
    GMAIL_SEND_SCOPE,
    GmailConfigError,
    GmailProvider,
    TransportError,
    real_gmail_transport,
)
from core.scout.comms.gmail_oauth import (
    READINESS_ACCOUNT,
    READINESS_AUTHORIZED,
    finalize_authorization,
    gmail_status,
    read_token_store,
)
from core.scout.comms.providers import DeterministicLocalSinkProvider, ProviderRegistry, RealEmailAdapter
from core.scout.comms.provenance import fixture_provenance
from core.scout.comms.repository import CommsRepository
from core.scout.comms.review import preview_hash_for
from core.scout.comms.runtime import build_runtime_provider_registry
from core.scout.comms.send import S_ACCEPTED, S_BLOCKED, S_DRY_RUN, SendService
from core.scout.memory.db import MemoryDB
from core.scout.memory.repository import MemoryRepository

_NOW = "2026-07-18T15:00:00+00:00"
_RECIP = "owner@one.example"
_EXPECTED = "dipptrue@gmail.com"


def _jwt(email: str, verified: bool = True) -> str:
    def part(d):
        return base64.urlsafe_b64encode(json.dumps(d).encode()).decode().rstrip("=")
    return f"{part({'alg': 'RS256'})}.{part({'email': email, 'email_verified': verified})}.sig"


def _verified_status():
    return {"client_config_present": True, "token_present": True, "refreshable": True,
            "expected_account_match": True, "scopes": [GMAIL_SEND_SCOPE, "openid", "email"],
            "scopes_ok": True}


class _Capture:
    def __init__(self):
        self.calls = 0
        self.mime = ""

    def __call__(self, token, raw_b64):
        self.calls += 1
        self.mime = base64.urlsafe_b64decode(raw_b64.encode()).decode()
        return {"status_code": 200, "body": {"id": "gmail-1", "threadId": "t-1"}}


class _FakeCreds:
    def __init__(self, scopes, id_token=""):
        self.scopes = scopes
        self.id_token = id_token

    def to_json(self):
        return json.dumps({"token": "a", "refresh_token": "r", "scopes": self.scopes})


def _build_raises(*a, **k):
    raise RuntimeError("no network in tests")


def _fake_verifier(claims, *, sig_valid=True, enforce_aud=True):
    from core.scout.comms.gmail import GmailConfigError

    def _verify(id_token, audience):
        if not sig_valid:
            raise GmailConfigError("id-token verification failed: invalid signature")
        if enforce_aud and claims.get("aud") != audience:
            raise GmailConfigError("id-token verification failed: wrong audience")
        return claims
    return _verify


def _seed(tmp_path, *, transport=None, status=None, identity_prover=None):
    transport = transport if transport is not None else _Capture()
    db = MemoryDB(str(tmp_path / "m.db"))
    mem, comms = MemoryRepository(db), CommsRepository(db)
    mem.upsert_campaign("camp", "Camp", _NOW)
    mem.upsert_company("co-1", "camp", "One", "one.example", _NOW)
    mem.add_session("s1", "camp", "co-1", "https://one.example/", "agency", _NOW)
    mem.upsert_contact({"contact_id": "k1", "company_id": "co-1", "channel": "email",
                        "normalized_value": _RECIP, "status": "VERIFIED",
                        "data_subject_category": "organization", "manual_review_required": False,
                        "last_verified_at": _NOW})
    mem.add_provenance(fixture_provenance("k1", "co-1", _NOW, domain="one.example"))
    mem.upsert_finding({"finding_id": "f1", "capability": "accessibility", "category": "accessibility",
                        "severity": "medium", "title": "Alt", "root_impact_key": "axe:img",
                        "verification_state": "VERIFIED", "lifecycle_state": "ACTIVE",
                        "is_client_safe": True, "first_seen_at": _NOW, "last_seen_at": _NOW}, "s1", "co-1")
    mem.add_evidence({"evidence_id": "e1", "finding_id": "f1", "content_hash": "sha256:aa",
                      "storage_ref": "x", "sanitization_status": "sanitized", "client_safe": True,
                      "retention_deadline": "2026-12-01T00:00:00+00:00"}, "s1")
    reg = ProviderRegistry()
    reg.register(DeterministicLocalSinkProvider(str(tmp_path / "sink")))
    reg.register(GmailProvider(from_email=_EXPECTED, from_name="Dmytro Pogribnyy",
                               expected_account=_EXPECTED, transport=transport,
                               token_provider=lambda: "tok",
                               status_provider=(lambda: status) if status is not None else None,
                               identity_prover=identity_prover))
    svc = SendService(mem, comms, reg, lambda: _NOW)
    rid = build_revision(mem, comms, draft_id="d1", company_id="co-1", contact_id="k1",
                         finding_id="f1", channel="email", subject="A quick QA note",
                         body="Hello, one issue.", now=_NOW)
    aid = approve_revision(mem, comms, rid, reviewer="human", now=_NOW,
                           reviewed_content_hash=preview_hash_for(comms, rid))
    comms.set_control("__global_outreach__", "ENABLED")
    comms.add_allowlist(_RECIP, "test", _NOW)
    return mem, comms, svc, rid, aid, transport


def _send(svc, rid, aid, provider_id="gmail_personal", live=True):
    return svc.send(rid, aid, provider_id, campaign_id="camp", channel="email", live=live,
                    reviewer="human", confirm_recipient=_RECIP)


def _assert_no_state_mutation(comms, aid, rid, transport):
    assert comms.get_approval(aid)["state"] == "APPROVED" and comms.get_approval(aid)["consumed"] == 0
    assert comms.get_revision(rid)["state"] == "APPROVED"
    assert comms.count("outbound_messages") == 0 and comms.count("send_attempts") == 0
    assert transport.calls == 0


# --- BLOCKER 1: runtime registry + CLI wiring + preflight ordering --------------------------------

def test_runtime_registry_contains_gmail(tmp_path):
    reg = build_runtime_provider_registry(str(tmp_path / "sink"), env={})
    gmail = reg.get("gmail_personal")
    assert isinstance(gmail, GmailProvider) and not isinstance(gmail, RealEmailAdapter)
    assert reg.get("local_sink").metadata.provider_id == "local_sink"


def test_cli_send_path_uses_gmail_with_exact_payload(tmp_path, monkeypatch):
    from core.scout.comms.cli import cmd_send
    mem, comms, svc, rid, aid, _ = _seed(tmp_path)
    db_path = str(tmp_path / "m.db")
    cap = _Capture()

    def fake_factory(sink_dir, **kw):
        reg = ProviderRegistry()
        reg.register(DeterministicLocalSinkProvider(sink_dir))
        reg.register(GmailProvider(from_email=_EXPECTED, from_name="Dmytro Pogribnyy",
                                   expected_account=_EXPECTED, transport=cap,
                                   token_provider=lambda: "tok", status_provider=_verified_status,
                                   identity_prover=lambda: _EXPECTED))
        return reg
    monkeypatch.setattr("core.scout.comms.runtime.build_runtime_provider_registry", fake_factory)
    # Freeze cmd_send's clock to the seed time so the approval-TTL check is deterministic (otherwise
    # the fixed-timestamp approval "expires" once wall-clock passes its 24h window — a latent
    # time-bomb unrelated to what this test asserts about the Gmail payload).
    monkeypatch.setattr("core.scout.comms.cli._now", lambda: _NOW)
    from argparse import Namespace
    args = Namespace(db=db_path, draft_revision=rid, provider="gmail_personal", approve_send=True,
                     approval_id=f"ap-{rid}", reviewer="human", confirm_recipient=_RECIP, output="outputs")
    rc = cmd_send(args)
    assert rc == 0 and cap.calls == 1
    assert f"To: {_RECIP}" in cap.mime and "Subject: A quick QA note" in cap.mime
    assert "Hello, one issue." in cap.mime and "From: Dmytro Pogribnyy <dipptrue@gmail.com>" in cap.mime


def test_full_gmail_send_with_verified_status(tmp_path):
    mem, comms, svc, rid, aid, transport = _seed(tmp_path, status=_verified_status(),
                                                 identity_prover=lambda: _EXPECTED)
    out = _send(svc, rid, aid)
    assert out.status == S_ACCEPTED and transport.calls == 1
    assert comms.get_approval(aid)["state"] == "CONSUMED"
    assert comms.get_message(out.message_id)["state"] == "ACCEPTED"


def test_dry_run_never_calls_provider_or_consumes(tmp_path):
    mem, comms, svc, rid, aid, transport = _seed(tmp_path, status=_verified_status(),
                                                 identity_prover=lambda: _EXPECTED)
    out = _send(svc, rid, aid, live=False)
    assert out.status == S_DRY_RUN and transport.calls == 0
    assert comms.get_approval(aid)["state"] == "APPROVED"


@pytest.mark.parametrize("status,blocker", [
    ({"client_config_present": False}, "gmail_oauth_client_not_configured"),
    ({"client_config_present": True, "token_present": False}, "gmail_not_authorized"),
    ({"client_config_present": True, "token_present": True, "refreshable": True,
      "scopes": ["openid", "email"]}, "gmail_missing_send_scope"),
    ({"client_config_present": True, "token_present": True, "refreshable": True,
      "scopes": [GMAIL_SEND_SCOPE, "https://www.googleapis.com/auth/gmail.modify"]},
     "gmail_forbidden_scope"),
])
def test_gmail_preflight_blocks_before_reservation(tmp_path, status, blocker):
    mem, comms, svc, rid, aid, transport = _seed(tmp_path, status=status,
                                                 identity_prover=lambda: _EXPECTED)
    out = _send(svc, rid, aid)
    assert out.status == S_BLOCKED and blocker in out.blockers
    _assert_no_state_mutation(comms, aid, rid, transport)


def test_unverified_identity_blocks_before_reservation(tmp_path):
    # Status is fine, but the authoritative identity proof fails (wrong account / verifier raises).
    def _bad_identity():
        raise RuntimeError("verifier rejected")
    mem, comms, svc, rid, aid, transport = _seed(tmp_path, status=_verified_status(),
                                                 identity_prover=_bad_identity)
    out = _send(svc, rid, aid)
    assert out.status == S_BLOCKED and "gmail_identity_unverified" in out.blockers
    _assert_no_state_mutation(comms, aid, rid, transport)


def test_missing_identity_prover_blocks_live_send(tmp_path):
    # A status-wired provider with NO authoritative identity proof cannot send live.
    mem, comms, svc, rid, aid, transport = _seed(tmp_path, status=_verified_status())
    out = _send(svc, rid, aid)
    assert out.status == S_BLOCKED and "gmail_identity_unverified" in out.blockers
    _assert_no_state_mutation(comms, aid, rid, transport)


def test_unknown_provider_cannot_consume_or_reserve(tmp_path):
    mem, comms, svc, rid, aid, transport = _seed(tmp_path, status=_verified_status())
    out = _send(svc, rid, aid, provider_id="does_not_exist")
    assert out.status == S_BLOCKED and "unknown_provider" in out.blockers
    _assert_no_state_mutation(comms, aid, rid, transport)


def test_external_send_guard_blocks_real_transport(monkeypatch):
    monkeypatch.setenv(EXTERNAL_SEND_DISABLED_ENV, "1")
    with pytest.raises(TransportError) as exc:
        real_gmail_transport("token", "cmF3")
    assert exc.value.before_transmission is True


# --- BLOCKER 2: fail-closed OAuth (finalize_authorization + gmail_status), M0-hardened -------------

_AUD = "client-id-123.apps.googleusercontent.com"


def _claims(email=_EXPECTED, *, iss="https://accounts.google.com", sub="sub-1", verified=True,
            aud=_AUD):
    return {"iss": iss, "sub": sub, "email": email, "email_verified": verified, "aud": aud}


def test_finalize_authorization_success_stores_verified_identity(tmp_path):
    token_path = str(tmp_path / "token.json")
    creds = _FakeCreds([GMAIL_SEND_SCOPE, "openid", "email"], id_token=_jwt(_EXPECTED))
    result = finalize_authorization(creds, _build_raises, token_store_path=token_path, audience=_AUD,
                                    expected_account=_EXPECTED, verifier=_fake_verifier(_claims()))
    assert result["account"] == _EXPECTED
    token = read_token_store(token_path)
    assert token["account_claim"] == _EXPECTED and token["has_refresh_token"]


def test_finalize_authorization_invalid_signature_fails_closed(tmp_path):
    token_path = tmp_path / "token.json"
    creds = _FakeCreds([GMAIL_SEND_SCOPE, "openid", "email"], id_token=_jwt(_EXPECTED))
    with pytest.raises(GmailConfigError):
        finalize_authorization(creds, _build_raises, token_store_path=str(token_path), audience=_AUD,
                               expected_account=_EXPECTED,
                               verifier=_fake_verifier(_claims(), sig_valid=False))
    assert not token_path.exists()  # no token written


def test_finalize_authorization_wrong_account_fails_closed(tmp_path):
    token_path = tmp_path / "token.json"
    creds = _FakeCreds([GMAIL_SEND_SCOPE, "openid", "email"], id_token=_jwt("someone-else@gmail.com"))
    with pytest.raises(GmailConfigError):
        finalize_authorization(creds, _build_raises, token_store_path=str(token_path), audience=_AUD,
                               expected_account=_EXPECTED,
                               verifier=_fake_verifier(_claims("someone-else@gmail.com")))
    assert not token_path.exists()


@pytest.mark.parametrize("scopes", [["openid", "email"],  # missing send
                                    [GMAIL_SEND_SCOPE, "https://mail.google.com/"]])  # forbidden
def test_finalize_authorization_invalid_scopes_fail_closed(tmp_path, scopes):
    token_path = tmp_path / "token.json"
    creds = _FakeCreds(scopes, id_token=_jwt(_EXPECTED))
    with pytest.raises(GmailConfigError):
        finalize_authorization(creds, _build_raises, token_store_path=str(token_path), audience=_AUD,
                               expected_account=_EXPECTED, verifier=_fake_verifier(_claims()))
    assert not token_path.exists()


def _client_config(tmp_path):
    p = tmp_path / "client_secret.json"
    p.write_text(json.dumps({"installed": {"client_id": "abc", "client_secret": "s",
                                           "redirect_uris": ["http://localhost"]}}), encoding="utf-8")
    return str(p)


def test_altered_account_field_is_not_identity_proof(tmp_path):
    # A token file with account=dipptrue but NO id-token claim must NOT verify offline.
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"token": "a", "refresh_token": "r", "account": _EXPECTED,
                                 "scopes": [GMAIL_SEND_SCOPE, "openid", "email"]}), encoding="utf-8")
    status = gmail_status({"expected_account": _EXPECTED, "client_json": _client_config(tmp_path),
                           "token_json": str(token)})
    assert status["expected_account_match"] is False
    assert status["expected_account_claim_match"] is False and status["readiness"] != READINESS_ACCOUNT


def test_offline_status_is_claim_only_and_requires_live_verification(tmp_path):
    token = tmp_path / "token.json"
    token.write_text(json.dumps({"token": "a", "refresh_token": "r", "account": _EXPECTED,
                                 "id_token": _jwt(_EXPECTED),
                                 "scopes": [GMAIL_SEND_SCOPE, "openid", "email"]}), encoding="utf-8")
    status = gmail_status({"expected_account": _EXPECTED, "client_json": _client_config(tmp_path),
                           "token_json": str(token)})
    # A decoded claim is NEVER authoritative: expected-account-verified is not granted offline.
    assert status["expected_account_match"] is False and status["readiness"] == READINESS_AUTHORIZED
    assert status["expected_account_claim_match"] is True
    assert status["identity_verification"] == "live-required" and status["scopes_ok"] is True
