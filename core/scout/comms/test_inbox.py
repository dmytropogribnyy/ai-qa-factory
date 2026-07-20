"""Technical QA test-inbox adapter (v3.2 final email architecture — read-only, bounded).

The SECOND email identity, strictly separate from the Scout SEND provider (core/scout/comms/gmail.py):

  * identity ``drdiplextech@gmail.com`` (+ per-project ``drdiplextech+<slug>@gmail.com`` aliases);
  * a SEPARATE token store authorized for ``gmail.readonly + openid + email`` ONLY — the read token
    can never send, and the send token can never read (the two scope policies list each other's core
    scope as *forbidden*, so a single mixed token fails BOTH policies);
  * a distinct token FILE from the send store (a shared file fails closed);
  * NOT a generic mailbox reader: retrieval is limited to messages addressed to an authorized test
    alias, within a narrow time window, correlated to an expected sender/subject. There is no
    "list my inbox" method and none is exposed through the Dashboard/HTTP.

Like the sender, the HTTP transport and token provider are INJECTED so deterministic tests exercise
the exact request with a fake transport and no network, no Google client library, and no credential.
The real transport refuses to run under the CI external guard. Token/client-secret values are never
read, printed, returned, logged, or persisted; only bounded, redacted correlation facts are returned.
"""
from __future__ import annotations

import os
import re
from typing import Any, Callable, Dict, List, Optional

from core.scout.comms.gmail import (
    EXTERNAL_SEND_DISABLED_ENV,
    GmailConfigError,
    GmailError,
)
from core.scout.comms.gmail_oauth import (
    READINESS_ADAPTER,
    READINESS_AUTHORIZED,
    READINESS_CLIENT,
    build_token_provider,
    parse_client_config,
    read_token_store,
)

# --- read-only scope policy (the exact inverse of the send policy) --------------------------------
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"
GMAIL_IDENTITY_SCOPES = ("openid", "email")
REQUIRED_TEST_INBOX_SCOPES = (GMAIL_READONLY_SCOPE, *GMAIL_IDENTITY_SCOPES)
# Scopes that must NEVER appear on the read-only test-inbox token (send/modify/compose/full mail).
FORBIDDEN_TEST_INBOX_SCOPES = frozenset({
    "https://www.googleapis.com/auth/gmail.send", "https://mail.google.com/",
    "https://www.googleapis.com/auth/gmail.modify", "https://www.googleapis.com/auth/gmail.compose",
    "https://www.googleapis.com/auth/gmail.insert", "https://www.googleapis.com/auth/gmail.settings.basic"})
_EMAIL_SCOPES = frozenset({"email", "https://www.googleapis.com/auth/userinfo.email"})

TEST_INBOX_EXPECTED_DEFAULT = "drdiplextech@gmail.com"
TEST_ALIAS_TEMPLATE_DEFAULT = "drdiplextech+{project_id}@gmail.com"
GMAIL_LIST_ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/messages"
GMAIL_GET_ENDPOINT = "https://gmail.googleapis.com/gmail/v1/users/me/messages/{id}"
_MAX_CORRELATED_RESULTS = 10          # hard cap; a correlated flow yields one/a few messages
_MAX_WINDOW_DAYS = 14                 # a bounded window; never an open-ended scan


class TestInboxError(GmailError):
    """A test-inbox retrieval failure (sanitized; never leaks message bodies or tokens)."""


class TestAliasError(GmailConfigError):
    """A malformed project id / test alias — fails closed before any interpolation or search."""


def test_inbox_scope_blockers(granted) -> List[str]:
    """Read-only policy: required gmail.readonly + openid + email; NO send/modify/compose/full scope.
    A token carrying a send scope is a *mixed* token and is refused here (and by the send policy)."""
    scopes = set(granted or [])
    blockers: List[str] = []
    if GMAIL_READONLY_SCOPE not in scopes:
        blockers.append("missing_readonly_scope")
    if "openid" not in scopes:
        blockers.append("missing_openid_scope")
    if not (scopes & _EMAIL_SCOPES):
        blockers.append("missing_email_scope")
    if scopes & FORBIDDEN_TEST_INBOX_SCOPES:
        blockers.append("forbidden_scope")          # e.g. a mixed send+read token
    return blockers


# --- safe per-project alias -----------------------------------------------------------------------
_SLUG_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{0,38}[a-z0-9])?$")


def safe_project_slug(project_id: str) -> str:
    """Validate + normalise a project id into a plus-address slug. Fails closed on anything that is
    not a bounded lowercase ``[a-z0-9-]`` token (no dots/plus/@/spaces, no leading/trailing/double
    dash), so a hostile project id can never inject headers or widen the address."""
    if not isinstance(project_id, str):
        raise TestAliasError("project id must be a string")
    slug = project_id.strip().lower()
    if not slug or "--" in slug or not _SLUG_RE.match(slug):
        raise TestAliasError(
            "unsafe project id for a test alias: use 1-40 chars of a-z, 0-9, single dashes")
    return slug


def build_test_alias(template: str, project_id: str, *, plus_addressing: bool = True) -> str:
    """Build ``drdiplextech+<slug>@gmail.com`` from a validated slug. With ``plus_addressing=False``
    (a target that rejects plus addressing) fall back to the base mailbox address."""
    if "{project_id}" not in (template or ""):
        raise TestAliasError("alias template must contain the {project_id} placeholder")
    slug = safe_project_slug(project_id)
    base = template.replace("+{project_id}", "").replace("{project_id}", "")
    return base if not plus_addressing else template.replace("{project_id}", slug)


def test_inbox_config_from_env(env: Optional[Dict[str, str]] = None) -> Dict[str, str]:
    """Read the test-inbox configuration from environment references only (never secret values).
    The client config MAY fall back to the shared Desktop OAuth client, but the token store must be a
    DISTINCT file (there is deliberately no fallback to the send token)."""
    e = env if env is not None else os.environ
    client = e.get("GMAIL_TEST_OAUTH_CLIENT_JSON", "") or e.get("GMAIL_OAUTH_CLIENT_JSON", "")
    return {"expected_account": e.get("GMAIL_TEST_EXPECTED_ACCOUNT", TEST_INBOX_EXPECTED_DEFAULT),
            "test_mailbox": e.get("AIQA_TEST_MAILBOX", TEST_INBOX_EXPECTED_DEFAULT),
            "alias_template": e.get("AIQA_TEST_ALIAS_TEMPLATE", TEST_ALIAS_TEMPLATE_DEFAULT),
            "client_json": client,
            "token_json": e.get("GMAIL_TEST_OAUTH_TOKEN_JSON", ""),
            # The send token store — only used to assert the two stores are DISTINCT files.
            "send_token_json": e.get("GMAIL_OAUTH_TOKEN_JSON", "")}


def _same_file(a: str, b: str) -> bool:
    if not a or not b:
        return False
    try:
        return os.path.exists(a) and os.path.exists(b) and os.path.samefile(a, b)
    except OSError:
        return os.path.normcase(os.path.abspath(a)) == os.path.normcase(os.path.abspath(b))


def test_inbox_status(config: Dict[str, str]) -> Dict[str, Any]:
    """Report test-inbox readiness WITHOUT any token value, derived INDEPENDENTLY from the actual
    client config, token, exact readonly scopes, refreshability, and expected-account claim. Fails
    closed on a mixed token (send scope present), a wrong account, or a token store shared with the
    send identity. The account is only a CANDIDATE offline; live proof is a cryptographic id-token
    check at retrieval time."""
    expected = config.get("expected_account", TEST_INBOX_EXPECTED_DEFAULT)
    status: Dict[str, Any] = {
        "expected_account": expected, "client_config_present": False, "token_present": False,
        "refreshable": False, "authorized_account": "", "account_claim": "",
        "expected_account_claim_match": False, "distinct_token_store": True, "scopes": [],
        "scopes_ok": False, "identity_verification": "not-authorized", "readiness": READINESS_ADAPTER}
    # A shared token FILE collapses the two identities — fail closed regardless of anything else.
    if _same_file(config.get("token_json", ""), config.get("send_token_json", "")):
        status["distinct_token_store"] = False
        return status
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
                  scopes_ok=(not test_inbox_scope_blockers(token["scopes"])))
    if token["has_refresh_token"]:
        status["readiness"] = READINESS_AUTHORIZED
    status["expected_account_claim_match"] = bool(
        claim and claim == expected and token["has_refresh_token"] and status["scopes_ok"])
    status["identity_verification"] = (
        "live-required" if status["expected_account_claim_match"] else "unverified")
    return status


def build_readonly_token_provider(token_store_path: str) -> Callable[[], str]:
    """A refreshing access-token provider pinned to the READ-ONLY scopes (never the send scopes)."""
    return build_token_provider(token_store_path, scopes=list(REQUIRED_TEST_INBOX_SCOPES))


def authorize_test_inbox(*, client_config_path: str, token_store_path: str,
                         send_token_store_path: str = "",
                         expected_account: str = TEST_INBOX_EXPECTED_DEFAULT,
                         open_browser: bool = True) -> Dict[str, Any]:
    """Loopback consent for the READ-ONLY test inbox (gmail.readonly + openid + email). Refuses to
    write over the send token store. Reuses the hardened shared flow with the read-only scope policy."""
    from core.scout.comms.gmail_oauth import authorize
    if send_token_store_path and _same_file(token_store_path, send_token_store_path):
        raise TestAliasError("the test-inbox token must be a DISTINCT file from the send token")
    return authorize(client_config_path=client_config_path, token_store_path=token_store_path,
                     expected_account=expected_account, open_browser=open_browser,
                     scopes=list(REQUIRED_TEST_INBOX_SCOPES),
                     scope_validator=test_inbox_scope_blockers)


def _gmail_search_query(*, alias: str, newer_than_days: int, from_email: str = "",
                        subject_contains: str = "") -> str:
    """Build a NARROW Gmail search query. Always constrained to an exact ``to:`` alias and a bounded
    ``newer_than`` window; optionally correlated to an expected sender and subject. Never open-ended."""
    days = max(1, min(int(newer_than_days), _MAX_WINDOW_DAYS))
    parts = [f"to:{alias}", f"newer_than:{days}d"]
    if from_email:
        parts.append(f"from:{from_email}")
    if subject_contains:
        parts.append(f'subject:"{subject_contains}"')
    return " ".join(parts)


def real_readonly_transports():
    """Return ``(list_transport, get_transport)`` backed by urllib. Both refuse under the CI external
    guard so no network call happens in CI. Metadata format only — the full body is never fetched."""
    def _refuse_if_guarded() -> None:
        if os.environ.get(EXTERNAL_SEND_DISABLED_ENV):
            raise TestInboxError("external retrieval disabled by CI guard")

    def _get_json(url: str, token: str, timeout: float = 30.0) -> Dict[str, Any]:
        import json
        import urllib.error
        import urllib.request
        req = urllib.request.Request(url, method="GET",
                                     headers={"Authorization": f"Bearer {token}"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            raise TestInboxError(f"test-inbox http error {exc.code}") from None
        except (urllib.error.URLError, TimeoutError):
            raise TestInboxError("test-inbox transport failure") from None

    def list_transport(token: str, query: str, max_results: int) -> List[str]:
        _refuse_if_guarded()
        import urllib.parse
        n = max(1, min(int(max_results), _MAX_CORRELATED_RESULTS))
        url = f"{GMAIL_LIST_ENDPOINT}?{urllib.parse.urlencode({'q': query, 'maxResults': n})}"
        body = _get_json(url, token)
        return [str(m.get("id")) for m in body.get("messages", []) if m.get("id")][:n]

    def get_transport(token: str, message_id: str) -> Dict[str, Any]:
        _refuse_if_guarded()
        import urllib.parse
        headers = "&".join(f"metadataHeaders={h}" for h in ("From", "To", "Subject", "Date"))
        url = (f"{GMAIL_GET_ENDPOINT.format(id=urllib.parse.quote(message_id))}"
               f"?format=metadata&{headers}")           # metadata only; never format=full
        return _get_json(url, token)

    return list_transport, get_transport


def _header(message: Dict[str, Any], name: str) -> str:
    for h in (message.get("payload", {}) or {}).get("headers", []) or []:
        if str(h.get("name", "")).lower() == name.lower():
            return str(h.get("value", ""))
    return ""


class TestInboxReader:
    """Bounded, correlated retrieval from the technical test inbox. There is intentionally NO generic
    "list messages" surface: every read is pinned to an authorized test alias, a narrow window, and
    an expected sender/subject, and only bounded redacted correlation facts are returned."""

    def __init__(self, *, expected_account: str, test_mailbox: str,
                 list_transport: Callable[[str, str, int], List[str]],
                 get_transport: Callable[[str, str], Dict[str, Any]],
                 token_provider: Callable[[], str],
                 status_provider: Optional[Callable[[], Dict[str, Any]]] = None,
                 identity_prover: Optional[Callable[[], str]] = None) -> None:
        self._expected_account = expected_account
        self._test_mailbox = test_mailbox.lower()
        self._list = list_transport
        self._get = get_transport
        self._token_provider = token_provider
        self._status_provider = status_provider
        self._identity_prover = identity_prover

    def _assert_alias_belongs_to_test_mailbox(self, alias: str) -> None:
        """Refuse to search for any ``to:`` that is not the test mailbox or one of its plus-aliases —
        this is what stops the adapter from being repurposed as a generic mailbox reader."""
        a = (alias or "").strip().lower()
        local, _, domain = self._test_mailbox.partition("@")
        base_local = local.split("+", 1)[0]
        alias_local, _, alias_domain = a.partition("@")
        alias_base = alias_local.split("+", 1)[0]
        if not a or alias_domain != domain or alias_base != base_local:
            raise TestInboxError("refusing to read: the alias is not this test mailbox")

    def preflight(self) -> List[str]:
        """Fail-closed readiness: readonly scope, refreshable, distinct store, and (when wired) a
        cryptographic identity proof of the expected test account."""
        blockers: List[str] = []
        if self._status_provider is not None:
            s = self._status_provider() or {}
            if not s.get("distinct_token_store", True):
                blockers.append("test_inbox_token_shares_send_store")
            if not s.get("client_config_present"):
                blockers.append("test_inbox_oauth_client_not_configured")
            elif not s.get("token_present"):
                blockers.append("test_inbox_not_authorized")
            elif not s.get("refreshable"):
                blockers.append("test_inbox_token_not_refreshable")
            blockers.extend("test_inbox_" + b for b in test_inbox_scope_blockers(s.get("scopes", [])))
        if self._identity_prover is not None:
            try:
                proven = self._identity_prover()
            except Exception:  # noqa: BLE001 - any verification failure is fail-closed
                proven = ""
            if proven != self._expected_account:
                blockers.append("test_inbox_identity_unverified")
        return sorted(set(blockers))

    def correlated_search(self, *, alias: str, newer_than_days: int = 1, from_email: str = "",
                          subject_contains: str = "", max_results: int = 5) -> List[Dict[str, str]]:
        """Retrieve ONLY messages tightly correlated to an authorized test-alias flow. Returns bounded
        redacted facts (id + From/To/Subject/Date + a redacted snippet); never the full body, never
        an uncorrelated message, never a persisted dump of unrelated personal mail."""
        from core.orchestration.content_safety import redact_intake_text
        self._assert_alias_belongs_to_test_mailbox(alias)
        blockers = self.preflight()
        if blockers:
            raise TestInboxError(f"test inbox not ready: {','.join(blockers)}")
        token = self._token_provider()
        query = _gmail_search_query(alias=alias, newer_than_days=newer_than_days,
                                    from_email=from_email, subject_contains=subject_contains)
        ids = self._list(token, query, max(1, min(int(max_results), _MAX_CORRELATED_RESULTS)))
        out: List[Dict[str, str]] = []
        want_from = from_email.strip().lower()
        for mid in ids[:_MAX_CORRELATED_RESULTS]:
            msg = self._get(token, mid) or {}
            to_h, from_h = _header(msg, "To"), _header(msg, "From")
            # Re-verify correlation client-side: the message MUST be addressed to the exact alias, and
            # (when an expected sender is given) from that sender. Anything else is silently dropped.
            if alias.lower() not in to_h.lower():
                continue
            if want_from and want_from not in from_h.lower():
                continue
            out.append({
                "id": str(mid), "to": to_h, "from": from_h,
                "subject": redact_intake_text(_header(msg, "Subject")).text[:200],
                "date": _header(msg, "Date"),
                # A bounded, redacted preview only (Gmail's own snippet) — never the full body.
                "snippet": redact_intake_text(str(msg.get("snippet", ""))).text[:200]})
        return out
