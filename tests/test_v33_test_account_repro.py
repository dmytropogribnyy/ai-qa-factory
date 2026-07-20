"""v3.3 — Mode-3 test-account approval gate + structured bug-reproduction context (bounded)."""
from __future__ import annotations

import pytest

from core.scout.repro_context import (
    REPRO_NOT,
    REPRO_REPRODUCED,
    ReproError,
    ReproResult,
    build_repro_context,
)
from core.scout.test_account import STATUS_APPROVED, STATUS_PENDING
from core.scout.test_account import TestAccountError as _TAError
from core.scout.test_account import (
    approve_test_account,
    guard_signup_step,
    request_test_account,
)
from core.scout.test_account import test_account_alias as _alias


# --- Mode-3 test-account gate ------------------------------------------------------------------
def test_alias_is_correlated_and_isolated():
    assert _alias("Shop.Example.com") == "drdiplextech+aiqa-shop-example-com@gmail.com"


def test_request_is_pending_and_unusable():
    auth = request_test_account("example.com")
    assert auth.status == STATUS_PENDING
    with pytest.raises(_TAError):
        guard_signup_step(auth, step_label="enter email")   # not approved => refused


def test_approval_requires_free_and_clear_terms():
    with pytest.raises(_TAError):
        approve_test_account("example.com", operator="op", free_signup_confirmed=False,
                             terms_clear=True)
    with pytest.raises(_TAError):
        approve_test_account("example.com", operator="op", free_signup_confirmed=True,
                             terms_clear=False)
    auth = approve_test_account("example.com", operator="op", free_signup_confirmed=True,
                                terms_clear=True)
    assert auth.status == STATUS_APPROVED
    assert auth.constraints["no_payment"] and auth.constraints["no_phone"]


def test_forbidden_steps_refused_even_when_approved():
    auth = approve_test_account("example.com", operator="op", free_signup_confirmed=True,
                                terms_clear=True)
    guard_signup_step(auth, step_label="enter email address")   # allowed
    for bad in ("Enter credit card number", "Add phone for SMS", "Subscribe to newsletter",
                "Start paid trial (auto-renew)", "Solve CAPTCHA"):
        with pytest.raises(_TAError):
            guard_signup_step(auth, step_label=bad)


# --- structured reproduction context -----------------------------------------------------------
def test_build_repro_context_captures_enough_to_return_later():
    ctx = build_repro_context(
        finding={"finding_id": "f1", "reproduction_steps": ["open /pricing", "toggle annual"],
                 "expected": "price updates", "actual": "price NaN", "evidence_refs": ["shot-1"],
                 "confidence": "high"},
        target_url="https://example.com/pricing", permitted_scope=["https://example.com/pricing"],
        stop_boundary="checkout", cleanup_required=False)
    assert ctx.finding_id == "f1"
    assert ctx.steps and ctx.prior_evidence == ["shot-1"]
    assert ctx.stop_boundary == "checkout"
    assert ctx.repro_confidence == "high"


def test_repro_result_never_carries_video_when_not_reproduced():
    with pytest.raises(ReproError):
        ReproResult(finding_id="f1", outcome=REPRO_NOT, video_ref="clip.webm")
    ok = ReproResult(finding_id="f1", outcome=REPRO_REPRODUCED, video_ref="clip.webm",
                     cleanup_verified=True)
    assert ok.is_client_safe_capable is True


def test_reproduced_but_unclean_is_not_client_safe():
    r = ReproResult(finding_id="f1", outcome=REPRO_REPRODUCED, cleanup_verified=False)
    assert r.is_client_safe_capable is False
