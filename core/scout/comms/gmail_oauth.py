"""Local Gmail OAuth 2.0 Desktop-App authorization (Final Independent Acceptance, v2.0.1).

A loopback installed-app flow requesting only the send scope (plus openid/email to prove the
authenticated identity). It verifies the authorized account is exactly the expected account and
never requests gmail.modify/readonly/compose/metadata for basic sending. Credentials are supplied
locally by the user; the client config and token store are never committed. Tokens are never
printed, never stored in SQLite, never placed in outputs/, and never appear in exceptions. Config
parsing and status are pure standard library (CI-safe); only the real authorize/refresh use the
Google client libraries, imported lazily so the deterministic core never needs them.
"""
from __future__ import annotations

import base64
import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from core.scout.comms.gmail import (
    EXPECTED_ACCOUNT_DEFAULT,
    EXTERNAL_SEND_DISABLED_ENV,
    FORBIDDEN_GMAIL_SCOPES,
    REQUIRED_GMAIL_SCOPES,
    GmailConfigError,
    gmail_scope_blockers,
)

# Readiness ladder (honest; never claim a higher rung than proven).
READINESS_ADAPTER = "adapter-ready"
READINESS_CLIENT = "OAuth-client-configured"
READINESS_AUTHORIZED = "user-authorized"
READINESS_ACCOUNT = "expected-account-verified"
READINESS_CONTROLLED = "controlled-address-accepted"
READINESS_LIVE = "live-accepted"

FORBIDDEN_SCOPES = FORBIDDEN_GMAIL_SCOPES        # re-export for back-compat
REQUESTED_SCOPES = list(REQUIRED_GMAIL_SCOPES)
_GOOGLE_ISSUERS = frozenset({"accounts.google.com", "https://accounts.google.com"})


def validate_scopes(granted) -> List[str]:
    """Required send + openid + email scopes present; no forbidden scope (delegates to gmail policy)."""
    return gmail_scope_blockers(granted)


def _decode_id_token_claim(id_token: str) -> str:
    """NON-AUTHORITATIVE: decode a JWT payload's email claim for offline DISPLAY only. This does NOT
    verify the signature and must never be used as identity proof (see verify_gmail_identity)."""
    if not id_token:
        return ""
    try:
        parts = id_token.split(".")
        if len(parts) < 2:
            return ""
        payload_b64 = parts[1] + "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64.encode("ascii")))
    except (ValueError, TypeError, json.JSONDecodeError):
        return ""
    if payload.get("email") and payload.get("email_verified"):
        return str(payload["email"])
    return ""


def official_id_token_verifier(id_token: str, audience: str) -> Dict[str, Any]:
    """PRODUCTION verifier: cryptographic signature + audience + expiry + issued-at via Google's
    official library (google.oauth2.id_token.verify_oauth2_token). Refuses under the external-send
    guard so CI performs no identity-network call. Returns the verified claims; raises on failure."""
    if os.environ.get(EXTERNAL_SEND_DISABLED_ENV):
        raise GmailConfigError("identity verification refused: external-send guard is set")
    try:
        from google.auth.transport.requests import Request  # type: ignore
        from google.oauth2 import id_token as google_id_token  # type: ignore
    except ImportError as exc:
        raise GmailConfigError(
            "Gmail identity verification requires the optional Google client libraries") from exc
    try:
        return dict(google_id_token.verify_oauth2_token(id_token, Request(), audience))
    except Exception as exc:  # noqa: BLE001 - the library raises ValueError on any invalid token
        raise GmailConfigError(f"id-token verification failed: {type(exc).__name__}") from None


def verify_identity_claims(claims: Dict[str, Any], *, expected_account: str) -> str:
    """Validate already-signature/audience/expiry-verified claims and return the proven email.
    Fail-closed on a non-Google issuer, missing subject, unverified email, or the wrong account."""
    if not isinstance(claims, dict):
        raise GmailConfigError("identity claims malformed")
    if claims.get("iss") not in _GOOGLE_ISSUERS:
        raise GmailConfigError("id-token issuer is not Google")
    if not claims.get("sub"):
        raise GmailConfigError("id-token has no subject")
    if claims.get("email_verified") is not True:
        raise GmailConfigError("id-token email is not verified")
    email = claims.get("email")
    if not email:
        raise GmailConfigError("id-token has no email")
    if email != expected_account:
        raise GmailConfigError("id-token email is not the expected account")
    return str(email)


def verify_gmail_identity(id_token: str, *, audience: str, expected_account: str,
                          verifier: Callable[[str, str], Dict[str, Any]] = official_id_token_verifier
                          ) -> str:
    """Authoritatively prove the authorized account: the injected verifier checks signature/audience/
    expiry, then the claims are validated. Never a decoded-JWT shortcut. Returns the proven email."""
    if not id_token:
        raise GmailConfigError("no id-token to verify")
    if not audience:
        raise GmailConfigError("no OAuth client_id audience configured")
    claims = verifier(id_token, audience)
    return verify_identity_claims(claims, expected_account=expected_account)


def parse_client_config(path: str) -> Dict[str, Any]:
    """Parse and validate an installed-app OAuth client config. Returns bounded metadata only
    (never the client secret value). Raises GmailConfigError on a missing/malformed file."""
    p = Path(path)
    if not p.exists():
        raise GmailConfigError("OAuth client config file not found")
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError) as exc:
        raise GmailConfigError(f"OAuth client config is not valid JSON: {type(exc).__name__}") from None
    block = data.get("installed") or data.get("web")
    if not isinstance(block, dict) or not block.get("client_id"):
        raise GmailConfigError("OAuth client config is not an installed/desktop app config")
    if data.get("web") and not data.get("installed"):
        raise GmailConfigError("a web client config is not a desktop/installed app config")
    return {"client_id_present": bool(block.get("client_id")),
            # The client_id is NOT a secret; it is the audience for id-token verification. The
            # client_secret is never exposed or returned.
            "client_id": str(block.get("client_id", "")),
            "client_secret_present": bool(block.get("client_secret")),
            "redirect_supports_loopback": any(
                "127.0.0.1" in u or "localhost" in u for u in block.get("redirect_uris", []))
            or bool(block.get("client_secret"))}


def read_token_store(path: str) -> Optional[Dict[str, Any]]:
    """Read bounded, secret-free facts from a stored token (scopes, account, refreshability). Never
    returns token/refresh-token VALUES."""
    p = Path(path)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {"malformed": True}
    return {"malformed": False, "account": data.get("account", ""),
            "scopes": list(data.get("scopes", [])), "has_refresh_token": bool(data.get("refresh_token")),
            "has_token": bool(data.get("token")),
            # NON-AUTHORITATIVE candidate account (decoded, unverified) — for DISPLAY only. The
            # authoritative account is proven by verify_gmail_identity at live preflight.
            "account_claim": _decode_id_token_claim(data.get("id_token", ""))}


def _read_raw_id_token(path: str) -> str:
    """Read the raw stored id-token JWT for verification only (never returned by read_token_store)."""
    p = Path(path)
    if not p.exists():
        return ""
    try:
        return str(json.loads(p.read_text(encoding="utf-8")).get("id_token", "") or "")
    except (ValueError, OSError):
        return ""


def gmail_status(config: Dict[str, str]) -> Dict[str, Any]:
    """Report Gmail readiness WITHOUT any token value. Offline decode is NON-AUTHORITATIVE: it can
    show a candidate account but never grants expected-account-verified — that rung requires a live
    cryptographic identity proof (see verify_gmail_identity)."""
    expected = config.get("expected_account", EXPECTED_ACCOUNT_DEFAULT)
    status: Dict[str, Any] = {"expected_account": expected, "client_config_present": False,
                              "token_present": False, "refreshable": False, "authorized_account": "",
                              "account_claim": "", "expected_account_match": False,
                              "expected_account_claim_match": False, "scopes": [], "scopes_ok": False,
                              "identity_verification": "not-authorized", "readiness": READINESS_ADAPTER}
    try:
        parse_client_config(config.get("client_json", ""))
        status["client_config_present"] = True
        status["readiness"] = READINESS_CLIENT
    except GmailConfigError:
        return status
    token = read_token_store(config.get("token_json", ""))
    if not token or token.get("malformed") or not token.get("has_token"):
        return status
    claim = token.get("account_claim", "")
    status.update(token_present=True, refreshable=bool(token["has_refresh_token"]),
                  authorized_account=claim, account_claim=claim, scopes=token["scopes"],
                  scopes_ok=(not validate_scopes(token["scopes"])))
    if token["has_refresh_token"]:
        status["readiness"] = READINESS_AUTHORIZED
    # A decoded claim is only a candidate; the ladder stops at user-authorized until a live proof.
    status["expected_account_claim_match"] = bool(
        claim and claim == expected and token["has_refresh_token"] and status["scopes_ok"])
    status["identity_verification"] = (
        "live-required" if status["expected_account_claim_match"] else "unverified")
    return status


def harden_file_permissions(path: str) -> Dict[str, Any]:
    """Best-effort restrict a credential file to the current user; warn if it cannot be hardened."""
    p = Path(path)
    if not p.exists():
        return {"hardened": False, "warning": "file does not exist"}
    if os.name == "posix":
        try:
            os.chmod(p, 0o600)
            return {"hardened": True, "warning": ""}
        except OSError as exc:
            return {"hardened": False, "warning": f"chmod failed: {type(exc).__name__}"}
    # Windows: POSIX mode bits are not the security boundary; warn clearly.
    return {"hardened": False,
            "warning": "on Windows, file-mode hardening is best-effort only; protect this file via "
                       "NTFS ACLs / a user-only directory (a future OS-keyring backend is planned)"}


def authorize(*, client_config_path: str, token_store_path: str,
              expected_account: str = EXPECTED_ACCOUNT_DEFAULT,
              open_browser: bool = True) -> Dict[str, Any]:
    """Run the loopback installed-app consent flow, verify the account, and store the token. Uses
    the Google client libraries (imported lazily). Never prints or returns token values."""
    parse_client_config(client_config_path)  # fail fast on a bad config
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
    except ImportError as exc:
        raise GmailConfigError(
            "Gmail OAuth requires the optional Google client libraries "
            "(pip install -r requirements-gmail.txt)") from exc
    audience = parse_client_config(client_config_path)["client_id"]
    flow = InstalledAppFlow.from_client_secrets_file(client_config_path, scopes=REQUESTED_SCOPES)
    creds = flow.run_local_server(port=0, open_browser=open_browser)  # loopback, not out-of-band
    return finalize_authorization(creds, build, token_store_path=token_store_path, audience=audience,
                                  expected_account=expected_account)


def finalize_authorization(creds: Any, build: Any, *, token_store_path: str, audience: str,
                           expected_account: str = EXPECTED_ACCOUNT_DEFAULT,
                           verifier: Callable[[str, str], Dict[str, Any]] = official_id_token_verifier
                           ) -> Dict[str, Any]:
    """Validate scopes, prove the account with AUTHORITATIVE verification, and atomically store the
    token. Raises a sanitized GmailConfigError (and writes NO token) on invalid scopes, an
    unprovable/invalid account, or a wrong account. Deterministically testable via an injected
    verifier + fake build."""
    granted = sorted(set(getattr(creds, "scopes", []) or []))
    scope_blockers = validate_scopes(granted)
    if scope_blockers:
        raise GmailConfigError(
            f"authorization returned invalid scopes ({','.join(scope_blockers)}); refusing to store")
    verified_email = _prove_account_at_authorize(creds, build, audience=audience,
                                                 expected_account=expected_account, verifier=verifier)
    _write_token_atomic(token_store_path, creds, verified_email, granted)
    return {"account": verified_email, "scopes": granted,
            "permissions": harden_file_permissions(token_store_path)}


def _prove_account_at_authorize(creds: Any, build: Any, *, audience: str, expected_account: str,
                                verifier: Callable[[str, str], Dict[str, Any]]) -> str:
    """Prove the account fail-closed. A present id-token MUST verify authoritatively (no fall-through
    on failure); only an ABSENT id-token falls back to a strict authenticated userinfo lookup."""
    id_tok = getattr(creds, "id_token", "") or ""
    if id_tok:
        return verify_gmail_identity(id_tok, audience=audience, expected_account=expected_account,
                                     verifier=verifier)
    email = _strict_userinfo_email(creds, build)
    if not email:
        raise GmailConfigError("could not prove the authorized Google account; refusing to store token")
    if email != expected_account:
        raise GmailConfigError("authorized a different account than expected; refusing to store token")
    return email


def _strict_userinfo_email(creds: Any, build: Any) -> str:
    """Authenticated userinfo fallback: missing verified_email or verified_email=False fails closed."""
    try:
        info = build("oauth2", "v2", credentials=creds).userinfo().get().execute() or {}
    except Exception:  # noqa: BLE001 - never leak provider internals; treat as unproven
        return ""
    if info.get("verified_email") is not True:      # missing or False -> fail closed
        return ""
    return str(info.get("email") or "")


def prove_current_identity(config: Dict[str, str], *,
                           verifier: Callable[[str, str], Dict[str, Any]] = official_id_token_verifier
                           ) -> str:
    """Authoritatively prove the CURRENT authorized identity for a live send (used as the Gmail
    provider's identity prover). Verifies the stored id-token's signature/audience/expiry via the
    injected verifier. Raises fail-closed on any failure."""
    audience = parse_client_config(config.get("client_json", ""))["client_id"]
    id_tok = _read_raw_id_token(config.get("token_json", ""))
    return verify_gmail_identity(id_tok, audience=audience,
                                 expected_account=config.get("expected_account", EXPECTED_ACCOUNT_DEFAULT),
                                 verifier=verifier)


def _write_token_atomic(token_store_path: str, creds: Any, account: str, scopes: List[str]) -> None:
    """Write the token via an atomic local-file replace; a partial temp file is always removed."""
    p = Path(token_store_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.loads(creds.to_json())
    payload["account"] = account
    payload["account_verified"] = True
    payload["scopes"] = list(scopes)
    id_token = getattr(creds, "id_token", "") or ""
    if id_token:
        payload["id_token"] = id_token
    tmp = p.with_name(p.name + ".tmp")
    try:
        tmp.write_text(json.dumps(payload), encoding="utf-8")
        os.replace(tmp, p)                       # atomic replace
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
    harden_file_permissions(token_store_path)


def build_token_provider(token_store_path: str) -> Callable[[], str]:
    """Return a callable that loads + refreshes local credentials and returns a fresh access token.
    Uses the Google client libraries lazily. Never prints the token."""
    def _provider() -> str:
        try:
            from google.auth.transport.requests import Request  # type: ignore
            from google.oauth2.credentials import Credentials  # type: ignore
        except ImportError as exc:
            raise GmailConfigError("Gmail send requires the optional Google client libraries") from exc
        creds = Credentials.from_authorized_user_file(token_store_path, REQUESTED_SCOPES)
        if not creds.valid:
            creds.refresh(Request())
        return creds.token
    return _provider


def revoke_local_token(token_store_path: str) -> Dict[str, Any]:
    """Remove ONLY the local credential file (does not revoke Google-side access)."""
    p = Path(token_store_path)
    existed = p.exists()
    if existed:
        p.unlink()
    return {"removed_local_token": existed, "note": "local token only; Google-side access unchanged"}


def _warn(message: str) -> None:
    print(f"WARNING: {message}", file=sys.stderr)
