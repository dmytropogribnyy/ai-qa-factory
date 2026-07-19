"""v3.2 P0-A - canonical start-here docs must reflect the IMPLEMENTED product and cannot drift back
to "planning-only / no executor / v5.0.8". These assertions lock the critical status statements."""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _read(rel: str) -> str:
    return (_ROOT / rel).read_text(encoding="utf-8")


def test_claude_md_reflects_implemented_client_work_execution():
    t = _read("CLAUDE.md")
    # The client-work lifecycle + bounded Claude worker are IMPLEMENTED (not planning-only).
    assert "IMPLEMENTED" in t and "ClaudeWorkerExecutor" in t and "v3.2" in t
    # It must NOT claim the client-work execution surface has no executor / is planning-only overall.
    low = t.lower()
    assert "no executor" not in low
    # "planning-only" may appear ONLY scoped to the ARK `main.py work` command.
    for line in t.splitlines():
        if "planning-only" in line.lower():
            assert "work" in line.lower() and ("ark" in line.lower() or "main.py work" in line.lower())


def test_work_execution_model_is_implemented_not_planned():
    t = _read("docs/WORK_EXECUTION_MODEL.md")
    assert "IMPLEMENTED" in t
    assert "No executor and no MCP calls exist yet" not in t


def test_env_example_is_v32_and_honest():
    t = _read(".env.example")
    assert "v5.0.8" not in t and "v3.2" in t
    # Gmail is honestly the approval-gated SEND provider; the template explicitly clarifies it is
    # NOT a read-only inbox (rather than silently claiming read-only capability).
    assert "gmail.send" in t and "not a read-only inbox" in t.lower()
    # The worker override is documented and warns against wrappers.
    assert "AIQA_CLAUDE_BIN" in t and ".cmd" in t.lower()


# --- canonical email identity/scope/role consistency (cannot drift) -------------------------------
_POLICY = "docs/EMAIL_IDENTITY_AND_MAILBOX_POLICY.md"
_SEND_ACCOUNT = "dipptrue@gmail.com"
_TEST_ACCOUNT = "drdiplextexh@gmail.com"
_SEND_SCOPE = "gmail.send"
_READ_SCOPE = "gmail.readonly"


def test_canonical_email_policy_pins_the_two_identities_and_scopes():
    t = _read(_POLICY)
    # Both identities, each bound to its OWN scope, are present in the canonical matrix.
    assert _SEND_ACCOUNT in t and _TEST_ACCOUNT in t
    assert _SEND_SCOPE in t and _READ_SCOPE in t
    low = t.lower()
    # The hard separation rule (send can't read; read can't send) is stated.
    assert "can never read" in low and "can never send" in low
    # The plus-alias template and the bounded (non-generic) retrieval rule are stated.
    assert "drdiplextexh+" in t and "{project_id}" in t
    assert "not" in low and "generic" in low            # "not a general mailbox reader"
    # All ten required sections are present (numbered headings 1..10).
    for n in range(1, 11):
        assert f"## {n}." in t, f"missing canonical section {n}"


def test_env_example_declares_both_identities_with_distinct_token_stores():
    t = _read(".env.example")
    assert "GMAIL_OAUTH_TOKEN_JSON" in t and "GMAIL_TEST_OAUTH_TOKEN_JSON" in t   # distinct stores
    assert f"GMAIL_EXPECTED_ACCOUNT={_SEND_ACCOUNT}" in t
    assert f"GMAIL_TEST_EXPECTED_ACCOUNT={_TEST_ACCOUNT}" in t
    assert "gmail.readonly" in t and "AIQA_TEST_ALIAS_TEMPLATE" in t
    assert _POLICY.split("/")[-1] in t                  # references the canonical doc


def test_operator_docs_reference_the_canonical_policy():
    name = _POLICY.split("/")[-1]
    for doc in ("docs/GMAIL_PROVIDER_SETUP.md", "docs/CLIENT_WORK_OPERATOR_GUIDE.md",
                "docs/DASHBOARD_OPERATOR_GUIDE.md"):
        assert name in _read(doc), f"{doc} must reference {name}"


def test_code_and_docs_agree_on_identities_and_scopes():
    # The canonical accounts/scopes in the doc must match the values the CODE actually enforces, so a
    # doc edit that drifts from the implementation fails here.
    from core.scout.comms.gmail import EXPECTED_ACCOUNT_DEFAULT, GMAIL_SEND_SCOPE
    from core.scout.comms.test_inbox import (
        GMAIL_READONLY_SCOPE,
        TEST_ALIAS_TEMPLATE_DEFAULT,
        TEST_INBOX_EXPECTED_DEFAULT,
    )
    assert EXPECTED_ACCOUNT_DEFAULT == _SEND_ACCOUNT
    assert TEST_INBOX_EXPECTED_DEFAULT == _TEST_ACCOUNT
    assert GMAIL_SEND_SCOPE.endswith(_SEND_SCOPE) and GMAIL_READONLY_SCOPE.endswith(_READ_SCOPE)
    t = _read(_POLICY)
    assert TEST_ALIAS_TEMPLATE_DEFAULT in t
    # The read policy forbids the send scope and vice-versa (mutual exclusion in code).
    from core.scout.comms.gmail import FORBIDDEN_GMAIL_SCOPES
    from core.scout.comms.test_inbox import FORBIDDEN_TEST_INBOX_SCOPES
    assert GMAIL_READONLY_SCOPE in FORBIDDEN_GMAIL_SCOPES        # send token can't hold readonly
    assert GMAIL_SEND_SCOPE in FORBIDDEN_TEST_INBOX_SCOPES       # read token can't hold send
