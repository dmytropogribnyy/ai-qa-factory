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
    FORBIDDEN_GMAIL_SCOPES,
    GMAIL_SEND_SCOPE,
    REQUIRED_GMAIL_SCOPES,
    GmailConfigError,
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


def validate_scopes(granted) -> List[str]:
    """Return scope blockers: the required send scope must be present and no forbidden scope may be."""
    scopes = set(granted or [])
    blockers: List[str] = []
    if GMAIL_SEND_SCOPE not in scopes:
        blockers.append("missing_send_scope")
    if scopes & FORBIDDEN_GMAIL_SCOPES:
        blockers.append("forbidden_scope")
    return blockers


def _id_token_verified_email(id_token: str) -> str:
    """Decode a Google ID-token JWT payload and return the email ONLY when the claim is present and
    email_verified is true. Offline decode of a signed Google claim (full signature verification is
    done at live preflight); a manually altered top-level 'account' field is never consulted here."""
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
            # The AUTHORITATIVE identity is the verified id-token email claim, never the bare
            # 'account' field (which a user could manually alter).
            "verified_email_claim": _id_token_verified_email(data.get("id_token", ""))}


def gmail_status(config: Dict[str, str]) -> Dict[str, Any]:
    """Report Gmail readiness WITHOUT any token value: client config present, token present/
    refreshable, authorized/expected account, scopes granted, readiness rung."""
    expected = config.get("expected_account", EXPECTED_ACCOUNT_DEFAULT)
    status: Dict[str, Any] = {"expected_account": expected, "client_config_present": False,
                              "token_present": False, "refreshable": False, "authorized_account": "",
                              "expected_account_match": False, "scopes": [], "scopes_ok": False,
                              "readiness": READINESS_ADAPTER}
    try:
        parse_client_config(config.get("client_json", ""))
        status["client_config_present"] = True
        status["readiness"] = READINESS_CLIENT
    except GmailConfigError:
        return status
    token = read_token_store(config.get("token_json", ""))
    if not token or token.get("malformed") or not token.get("has_token"):
        return status
    verified = token.get("verified_email_claim", "")
    status.update(token_present=True, refreshable=bool(token["has_refresh_token"]),
                  authorized_account=verified or token["account"], scopes=token["scopes"],
                  scopes_ok=(not validate_scopes(token["scopes"])))
    if token["has_refresh_token"]:
        status["readiness"] = READINESS_AUTHORIZED
    # expected-account-verified requires a VERIFIED id-token claim matching the expected account,
    # a refresh token, and valid scopes — never the bare 'account' field alone.
    if (verified and verified == expected and token["has_refresh_token"] and status["scopes_ok"]):
        status["expected_account_match"] = True
        status["readiness"] = READINESS_ACCOUNT
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
    flow = InstalledAppFlow.from_client_secrets_file(client_config_path, scopes=REQUESTED_SCOPES)
    creds = flow.run_local_server(port=0, open_browser=open_browser)  # loopback, not out-of-band
    return finalize_authorization(creds, build, token_store_path=token_store_path,
                                  expected_account=expected_account)


def finalize_authorization(creds: Any, build: Any, *, token_store_path: str,
                           expected_account: str = EXPECTED_ACCOUNT_DEFAULT) -> Dict[str, Any]:
    """Validate scopes, prove the account FAIL-CLOSED, and atomically store the token. Raises a
    sanitized GmailConfigError (and writes NO token) on invalid scopes, an unprovable account, or a
    wrong account. Separated from the browser flow so it is deterministically testable."""
    granted = sorted(set(getattr(creds, "scopes", []) or []))
    scope_blockers = validate_scopes(granted)
    if scope_blockers:
        raise GmailConfigError(
            f"authorization returned invalid scopes ({','.join(scope_blockers)}); refusing to store")
    # Prove the authorized identity — never invent expected_account when the lookup fails.
    verified_email = _verified_account(creds, build)
    if not verified_email:
        raise GmailConfigError("could not prove the authorized Google account; refusing to store token")
    if verified_email != expected_account:
        raise GmailConfigError("authorized a different account than expected; refusing to store token")
    _write_token_atomic(token_store_path, creds, verified_email, granted)
    return {"account": verified_email, "scopes": granted,
            "permissions": harden_file_permissions(token_store_path)}


def _verified_account(creds: Any, build: Any) -> str:
    """Prove the authorized account (empty string == unproven -> caller fails closed)."""
    email = _id_token_verified_email(getattr(creds, "id_token", "") or "")
    if email:
        return email
    try:
        info = build("oauth2", "v2", credentials=creds).userinfo().get().execute() or {}
    except Exception:  # noqa: BLE001 - never leak provider internals; treat as unproven
        return ""
    if info.get("email") and info.get("verified_email", True):
        return str(info["email"])
    return ""


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
