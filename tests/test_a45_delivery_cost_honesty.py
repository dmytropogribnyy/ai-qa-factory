"""A4.5 foundation closure — an unknown delivery cost is not a free delivery.

The reviewer's spend was made honest earlier in Issue #74: an unpriced call records ``usd: null``
with ``cost_known: false``, and the USD cap reports itself unenforceable rather than passing at a
fabricated $0. The delivery worker's cost sat beside it on the same `/collab` screen and still
lied: four distinct unknown conditions in ``_parse_claude_result`` — unparseable stdout, non-dict
stdout, absent ``total_cost_usd``, malformed ``total_cost_usd`` — all returned ``0.0``. That value
was then persisted into the delivery marker as fact, summed by the monitor, and rendered as
``$0.0000``. A subscription-billed run legitimately omits ``total_cost_usd``, so the common case
reported a definite zero.

Second, smaller defect in the same reader: a marker that could not be parsed was ``continue``d, so
it vanished from the ``delivered`` count as well. A dropped record makes a total wrong while it is
still presented as right, with no signal that anything was dropped.
"""
from __future__ import annotations

import json

import pytest

from core.collaboration.session_delivery import ClaudeSessionDelivery


@pytest.mark.parametrize("stdout, why", [
    ("not json at all", "unparseable stdout"),
    ("[]", "stdout that is not an object"),
    ("{}", "no total_cost_usd field at all (the subscription-billed case)"),
    (json.dumps({"total_cost_usd": None}), "an explicit null cost"),
    (json.dumps({"total_cost_usd": "free"}), "a malformed cost"),
    (json.dumps({"total_cost_usd": float("nan")}), "a non-finite cost"),
    (json.dumps({"total_cost_usd": -1.0}), "a negative cost"),
])
def test_an_unknown_delivery_cost_is_none_not_zero(stdout, why):
    cost, _model = ClaudeSessionDelivery._parse_claude_result(stdout)
    assert cost is None, f"{why} must be UNKNOWN, not a definite $0.00"


def test_a_real_cost_is_still_parsed():
    """Control: the fix must not discard a genuine price."""
    cost, model = ClaudeSessionDelivery._parse_claude_result(
        json.dumps({"total_cost_usd": 0.0123, "modelUsage": {"claude-x": {}}}))
    assert cost == pytest.approx(0.0123) and model == "claude-x"


def test_a_genuine_zero_cost_is_still_zero():
    """Zero is a legitimate price and must remain distinguishable from unknown."""
    cost, _ = ClaudeSessionDelivery._parse_claude_result(json.dumps({"total_cost_usd": 0.0}))
    assert cost == 0.0 and cost is not None


# --- the monitor must report what it does not know ------------------------------------------------

def _marker(root, name, body):
    base = root / "_review_relay" / "collab_delivery"
    base.mkdir(parents=True, exist_ok=True)
    (base / name).write_text(body, encoding="utf-8")


def test_the_monitor_reports_unpriced_deliveries_rather_than_summing_them_as_zero(tmp_path):
    from core.collaboration.monitor import CollaborationMonitor
    _marker(tmp_path, "a.json", json.dumps({"delivered_at": "t", "claude_cost_usd": 1.5,
                                            "cost_known": True}))
    _marker(tmp_path, "b.json", json.dumps({"delivered_at": "t", "claude_cost_usd": None,
                                            "cost_known": False}))
    snap = CollaborationMonitor(str(tmp_path), head_resolver=lambda: "a" * 40).snapshot()
    dl = snap["delivery"]
    assert dl["delivered"] == 2
    assert dl["unpriced_deliveries"] == 1
    assert dl["cost_known"] is False, "one unpriced delivery makes the total not fully known"
    assert dl["claude_cost_usd"] == pytest.approx(1.5), "the known part is still reported"


def test_the_monitor_reports_a_fully_priced_total_as_known(tmp_path):
    from core.collaboration.monitor import CollaborationMonitor
    _marker(tmp_path, "a.json", json.dumps({"delivered_at": "t", "claude_cost_usd": 2.0,
                                            "cost_known": True}))
    dl = CollaborationMonitor(str(tmp_path), head_resolver=lambda: "a" * 40).snapshot()["delivery"]
    assert dl["cost_known"] is True and dl["unpriced_deliveries"] == 0


def test_a_legacy_marker_without_provenance_counts_as_unpriced(tmp_path):
    """Markers written before `cost_known` carry `claude_cost_usd: 0.0` as a fabricated fact."""
    from core.collaboration.monitor import CollaborationMonitor
    _marker(tmp_path, "old.json", json.dumps({"delivered_at": "t", "claude_cost_usd": 0.0}))
    dl = CollaborationMonitor(str(tmp_path), head_resolver=lambda: "a" * 40).snapshot()["delivery"]
    assert dl["unpriced_deliveries"] == 1 and dl["cost_known"] is False


def test_an_unreadable_marker_is_counted_not_silently_dropped(tmp_path):
    """A dropped record is a wrong total presented as right."""
    from core.collaboration.monitor import CollaborationMonitor
    _marker(tmp_path, "a.json", json.dumps({"delivered_at": "t", "claude_cost_usd": 1.0,
                                            "cost_known": True}))
    _marker(tmp_path, "torn.json", "{half written")
    dl = CollaborationMonitor(str(tmp_path), head_resolver=lambda: "a" * 40).snapshot()["delivery"]
    assert dl["unreadable_markers"] == 1, "the reader must say it could not read one"
    assert dl["cost_known"] is False, "an unreadable marker may have carried cost"


def test_a_legacy_marker_with_a_real_non_zero_cost_is_still_counted(tmp_path):
    """The refinement an existing test forced, and it was right to.

    A first cut treated every marker without `cost_known` as unpriced. But the fabricated default
    was exactly 0.0 — a legacy marker carrying 0.021 could only have come from a real parsed price,
    and discarding it would erase real historical spend to avoid a fabricated zero. So the legacy
    judgement is made on the VALUE: zero is the fabrication, non-zero is evidence.
    """
    from core.collaboration.monitor import CollaborationMonitor
    _marker(tmp_path, "legacy.json", json.dumps({"delivered_at": "t", "claude_cost_usd": 0.021}))
    dl = CollaborationMonitor(str(tmp_path), head_resolver=lambda: "a" * 40).snapshot()["delivery"]
    assert dl["claude_cost_usd"] == pytest.approx(0.021)
    assert dl["unpriced_deliveries"] == 0 and dl["cost_known"] is True


def test_the_dashboard_says_unknown_rather_than_a_dollar_zero():
    """The screen is where the lie was visible: `$0.0000` for a cost nobody knew."""
    from core.scout.dashboard import _delivery_cost_text
    assert _delivery_cost_text({"cost_known": True, "claude_cost_usd": 0.5}) == "$0.5000"
    unknown = _delivery_cost_text({"cost_known": False, "unpriced_deliveries": 3,
                                   "claude_cost_usd": 0.0})
    assert "unknown" in unknown and "3 unpriced" in unknown
    assert "$0.0000" not in unknown
    partial = _delivery_cost_text({"cost_known": False, "unpriced_deliveries": 1,
                                   "claude_cost_usd": 2.5})
    assert "at least $2.5000" in partial and "unknown" in partial
