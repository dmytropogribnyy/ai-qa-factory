"""Mode-3 isolated test-account approval gate (v3.3, concept §6 / §7).

Only after EXPLICIT per-domain operator approval may Scout create at most ONE free, isolated test
account, using a correlated alias `drdiplextech+aiqa-<safe-domain-slug>@gmail.com` whose
verification email is read from the existing read-only QA test inbox. This module is the GATE and
the constraint set — it never creates an account, submits a form, or reads mail itself; the live
runtime consults it and stops on any refused step. Forbidden even in Mode 3: phone, payment, a
paid/auto-renewing trial, CAPTCHA bypass, newsletter/marketing opt-in, and any outgoing email.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict

# The read-only QA test inbox account (aliases correlate a verification email to a domain).
_INBOX_ACCOUNT = "drdiplextech"

STATUS_PENDING = "pending_approval"
STATUS_APPROVED = "approved"
STATUS_REFUSED = "refused"

# Steps that are NEVER allowed, even inside an approved Mode-3 signup.
FORBIDDEN_STEP_MARKERS = (
    "payment", "credit card", "card number", "billing", "phone", "sms", "mobile number",
    "paid trial", "auto-renew", "subscribe to newsletter", "marketing", "captcha", "verify you are",
    "send email", "send message", "invite",
)


class TestAccountError(RuntimeError):
    """Raised when a Mode-3 step is attempted without approval or crosses a forbidden boundary."""


def safe_domain_slug(domain: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (domain or "").strip().lower()).strip("-")
    return slug[:40] or "site"


def test_account_alias(domain: str) -> str:
    """The correlated, isolated alias for a domain (Gmail sub-addressing on the QA inbox)."""
    return f"{_INBOX_ACCOUNT}+aiqa-{safe_domain_slug(domain)}@gmail.com"


@dataclass
class TestAccountAuthorization:
    domain: str
    alias: str
    status: str = STATUS_PENDING
    approved_by: str = ""
    constraints: Dict[str, bool] = field(default_factory=lambda: {
        "no_phone": True, "no_payment": True, "no_paid_or_autorenew_trial": True,
        "no_captcha_bypass": True, "no_newsletter_optin": True, "no_outgoing_email": True,
        "one_account_max": True, "isolated_credentials_outside_repo": True})

    def to_dict(self) -> Dict[str, Any]:
        return dict(self.__dict__)


def request_test_account(domain: str) -> TestAccountAuthorization:
    """Create a PENDING authorization. It is NOT usable until an operator approves it."""
    return TestAccountAuthorization(domain=domain, alias=test_account_alias(domain))


def approve_test_account(domain: str, *, operator: str, free_signup_confirmed: bool,
                         terms_clear: bool) -> TestAccountAuthorization:
    """Approve a Mode-3 account for ONE domain. Fails closed unless the signup is confirmed FREE
    and the terms/restrictions are clear (§6: stop if terms are unclear)."""
    if not operator.strip():
        raise TestAccountError("an approving operator is required")
    if not free_signup_confirmed:
        raise TestAccountError("refused: signup is not confirmed free (no paid/auto-renew trial)")
    if not terms_clear:
        raise TestAccountError("refused: terms/restrictions are unclear — stop, do not guess")
    auth = request_test_account(domain)
    auth.status = STATUS_APPROVED
    auth.approved_by = operator
    return auth


def guard_signup_step(auth: TestAccountAuthorization, *, step_label: str) -> None:
    """Guard one signup step. Raises unless the account is approved AND the step is not forbidden."""
    if auth.status != STATUS_APPROVED:
        raise TestAccountError("Mode-3 signup requires an approved test account for this domain")
    lab = (step_label or "").strip().lower()
    for marker in FORBIDDEN_STEP_MARKERS:
        if marker in lab:
            raise TestAccountError(f"forbidden Mode-3 step: {marker!r} (stop, never proceed)")
