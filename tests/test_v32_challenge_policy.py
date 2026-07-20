"""v3.2 Sections 13-14 - challenge handling: public Scout never solves; solvers always prohibited."""
from __future__ import annotations

import pytest

from core.orchestration.challenge_policy import (
    AUTHORIZED_SESSION,
    CLIENT_TEST_BYPASS,
    HUMAN_CHECKPOINT,
    OBSERVE_ONLY,
    OFFICIAL_TEST_MODE,
    PROHIBITED,
    decide_challenge,
)


def test_public_scout_never_solves_or_bypasses():
    d = decide_challenge(scope="public_scout", challenge="recaptcha")
    assert d.mode == OBSERVE_ONLY and d.allowed is False
    assert "mark blocked" in d.next_action and "never" in d.next_action.lower()


@pytest.mark.parametrize("svc", ["anti-captcha", "2captcha", "CapSolver", "capmonster"])
def test_public_solver_services_are_always_prohibited(svc):
    d = decide_challenge(scope="authorized_client", challenge="recaptcha", solver_service=svc)
    assert d.mode == PROHIBITED and d.allowed is False


def test_authorized_client_official_test_keys():
    d = decide_challenge(scope="authorized_client", challenge="turnstile",
                         authorizations=["official_test_keys"])
    assert d.mode == OFFICIAL_TEST_MODE and d.allowed is True


def test_authorized_client_staging_bypass_and_session():
    assert decide_challenge(scope="authorized_client", challenge="login",
                            authorizations=["staging_bypass"]).mode == CLIENT_TEST_BYPASS
    assert decide_challenge(scope="authorized_client", challenge="login",
                            authorizations=["test_totp"]).mode == AUTHORIZED_SESSION


def test_authorized_client_without_authorization_pauses_for_human():
    d = decide_challenge(scope="authorized_client", challenge="recaptcha")
    assert d.mode == HUMAN_CHECKPOINT and d.allowed is True
    assert "pause" in d.next_action and "resume" in d.next_action


def test_unknown_scope_is_prohibited():
    assert decide_challenge(scope="", challenge="x").mode == PROHIBITED
