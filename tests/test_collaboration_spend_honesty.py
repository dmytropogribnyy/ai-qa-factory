"""Reviewer spend accounting must be honest about unknown cost (Issue #74, A3.5).

`_cost_from_usage` prices real tokens with `AIQA_REVIEWER_PRICE_PER_MTOK_IN/_OUT`, which default to
`"0"` and are documented nowhere. The ledger therefore recorded `usd: 0.0` against real token usage,
and `BudgetPolicy.per_thread_usd` / `daily_usd` read as spend protection while being structurally
incapable of binding.

Observed live during TASK 0: a real reviewer call recorded `calls:1, total_tokens:1503, usd:0.0`.

The contract pinned here: an unpriced call is reported as **cost-unknown**, never as `$0.00`; USD caps
are only claimed as enforced when pricing is actually configured; and the hard call-count caps keep
binding either way.
"""
from __future__ import annotations

import json

from core.collaboration.budget import BudgetLedger, BudgetPolicy


def _priced(monkeypatch, inp="3.00", out="15.00"):
    monkeypatch.setenv("AIQA_REVIEWER_PRICE_PER_MTOK_IN", inp)
    monkeypatch.setenv("AIQA_REVIEWER_PRICE_PER_MTOK_OUT", out)


def _unpriced(monkeypatch):
    monkeypatch.delenv("AIQA_REVIEWER_PRICE_PER_MTOK_IN", raising=False)
    monkeypatch.delenv("AIQA_REVIEWER_PRICE_PER_MTOK_OUT", raising=False)


# --- cost attribution ------------------------------------------------------------------------------
def test_an_unpriced_call_is_cost_unknown_not_zero(monkeypatch, tmp_path):
    from core.collaboration.reviewer_driver import _cost_from_usage

    _unpriced(monkeypatch)
    cost = _cost_from_usage({"input_tokens": 1000, "output_tokens": 500})
    assert cost is None, "unpriced usage must be None (cost-unknown), never 0.0"


def test_a_priced_call_returns_a_real_number(monkeypatch):
    from core.collaboration.reviewer_driver import _cost_from_usage

    _priced(monkeypatch)
    cost = _cost_from_usage({"input_tokens": 1_000_000, "output_tokens": 0})
    assert cost == 3.0


def test_no_usage_at_all_is_also_unknown(monkeypatch):
    from core.collaboration.reviewer_driver import _cost_from_usage

    _priced(monkeypatch)
    assert _cost_from_usage(None) is None      # no usage reported != a free call


# --- ledger ----------------------------------------------------------------------------------------
def test_ledger_records_cost_unknown_without_fabricating_zero(tmp_path):
    ledger = BudgetLedger(str(tmp_path))
    ledger.record("t-1", calls=1, usd=None, input_tokens=1000, output_tokens=503)
    usage = ledger.usage("t-1")
    assert usage["usd_known"] is False
    assert usage["unpriced_calls"] == 1
    assert usage["daily_calls"] == 1           # call accounting is unaffected


def test_ledger_reports_cost_known_when_priced(tmp_path):
    ledger = BudgetLedger(str(tmp_path))
    ledger.record("t-1", calls=1, usd=0.25, input_tokens=10, output_tokens=5)
    usage = ledger.usage("t-1")
    assert usage["usd_known"] is True
    assert usage["unpriced_calls"] == 0
    assert usage["daily_usd"] == 0.25


def test_mixed_priced_and_unpriced_reports_partial_knowledge(tmp_path):
    ledger = BudgetLedger(str(tmp_path))
    ledger.record("t-1", calls=1, usd=0.25, input_tokens=10, output_tokens=5)
    ledger.record("t-1", calls=1, usd=None, input_tokens=10, output_tokens=5)
    usage = ledger.usage("t-1")
    assert usage["usd_known"] is False         # one unpriced call makes the total not trustworthy
    assert usage["unpriced_calls"] == 1
    assert usage["daily_usd"] == 0.25          # still reports what IS known


# --- admission -------------------------------------------------------------------------------------
def test_usd_caps_are_not_claimed_as_enforced_when_pricing_is_unknown(tmp_path):
    ledger = BudgetLedger(str(tmp_path), policy=BudgetPolicy(per_thread_usd=2.0, daily_usd=10.0))
    ledger.record("t-1", calls=1, usd=None, input_tokens=1000, output_tokens=500)
    verdict = ledger.check("t-1")
    assert verdict.allowed is True             # call caps not reached
    assert verdict.usd_enforced is False       # but USD protection must not be claimed


def test_call_caps_still_bind_hard_when_pricing_is_unknown(tmp_path):
    """POSITIVE control: honesty about USD must not weaken the caps that DO work."""
    ledger = BudgetLedger(str(tmp_path), policy=BudgetPolicy(per_thread_calls=2, daily_calls=99))
    for _ in range(2):
        ledger.record("t-1", calls=1, usd=None, input_tokens=1, output_tokens=1)
    verdict = ledger.check("t-1")
    assert verdict.allowed is False
    assert verdict.cap == "per_thread_calls"


def test_usd_caps_are_enforced_when_pricing_is_configured(tmp_path):
    ledger = BudgetLedger(str(tmp_path), policy=BudgetPolicy(per_thread_usd=1.0))
    ledger.record("t-1", calls=1, usd=1.5, input_tokens=10, output_tokens=5)
    verdict = ledger.check("t-1")
    assert verdict.allowed is False
    assert verdict.cap == "per_thread_usd"
    assert verdict.usd_enforced is True


def test_prices_are_not_hardcoded_in_core_logic():
    """The controller forbids baking volatile provider prices into core logic."""
    from pathlib import Path

    src = Path("core/collaboration/reviewer_driver.py").read_text(encoding="utf-8")
    assert "gpt-5" not in src.lower() or "price" not in src.lower().split("gpt-5")[0][-200:], \
        "no per-model price table belongs in core reviewer logic"
    assert "AIQA_REVIEWER_PRICE_PER_MTOK_IN" in src   # pricing stays configuration


def test_ledger_event_is_json_serialisable_with_unknown_cost(tmp_path):
    ledger = BudgetLedger(str(tmp_path))
    ledger.record("t-1", calls=1, usd=None, input_tokens=1, output_tokens=1)
    events = list((tmp_path / "_review_relay" / "collab_budget").glob("*.json"))
    assert events, "no ledger event written"
    data = json.loads(events[0].read_text(encoding="utf-8"))
    assert data["usd"] is None
    assert data["cost_known"] is False
