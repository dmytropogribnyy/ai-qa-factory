"""Issue #17 — billing honesty: an ANTHROPIC_API_KEY in the environment overrides the OAuth login, so
billing_mode must report api_credits (not falsely 'subscription') even when a Pro/Max login exists."""
from __future__ import annotations

from core.collaboration.session_delivery import billing_mode


def _with_oauth(tmp_path, plan="pro"):
    cred = tmp_path / ".claude"
    cred.mkdir(parents=True, exist_ok=True)
    (cred / ".credentials.json").write_text('{"claudeAiOauth":{"subscriptionType":"%s"}}' % plan,
                                             encoding="utf-8")
    return tmp_path


def test_env_api_key_is_reported_as_api_credits_even_with_a_subscription(tmp_path):
    home = _with_oauth(tmp_path)                             # a real Pro subscription is logged in
    mode = billing_mode(env={"ANTHROPIC_API_KEY": "sk-ant-x"}, home=home)
    assert mode["source"] == "api_credits"                  # the env key overrides OAuth -> API billing
    assert "overrides" in mode["plan"].lower() and "pro" in mode["plan"].lower()


def test_no_env_key_reports_the_subscription(tmp_path):
    home = _with_oauth(tmp_path, plan="max")
    mode = billing_mode(env={"PATH": "/x"}, home=home)      # no API key in env
    assert mode["source"] == "subscription" and mode["plan"] == "max"


def test_auth_token_in_env_also_counts_as_api(tmp_path):
    mode = billing_mode(env={"ANTHROPIC_AUTH_TOKEN": "tok"}, home=_with_oauth(tmp_path))
    assert mode["source"] == "api_credits"


def test_unknown_when_no_key_and_no_credentials(tmp_path):
    mode = billing_mode(env={"PATH": "/x"}, home=tmp_path)  # no .claude credentials file
    assert mode["source"] == "unknown"
