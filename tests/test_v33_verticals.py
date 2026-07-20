"""v3.3 operator workflow — per-vertical QA profile selection + bounded fail-closed flows.

Deterministic (fake duck-typed pages). The load-bearing invariant across every vertical:
`crossed_boundary` is ALWAYS False — a flow stops before submit/reserve/book/order/pay/signup,
verifies cleanup for reversible state, and marks itself non-client-safe on any unexpected state.
"""
from __future__ import annotations

from core.scout.pipeline.browser_qa import CLEAR_CART_JS, READ_CART_JS
from core.scout.presets import (
    SITE_TYPE_B2B_SAAS,
    SITE_TYPE_BOOKING,
    SITE_TYPE_ECOMMERCE,
    SITE_TYPE_MARKETPLACE,
    SITE_TYPE_PERSONAL,
    SITE_TYPE_PROFESSIONAL,
    SUPPORTED_SITE_TYPES,
)
from core.scout.public_action_policy import (
    MODE_PASSIVE,
    PolicyStop,
    check_action,
    is_irreversible,
    is_reversible,
)
from core.scout.verticals import (
    FLOW_BOOKING,
    FLOW_CART,
    FLOW_FORM,
    FLOW_PASSIVE,
    FLOW_SAAS,
    run_vertical_flow,
    select_profile,
)
from core.scout.verticals import ACTIONS_JS, FORM_VALIDATION_JS


class _FakePage:
    def __init__(self, *, labels=None, form=None, cart_cleanup=True, click_raises=False,
                 goto_raises=False):
        self._labels = labels or []
        self._form = form or {"form": True, "required": 2, "client_validation": True}
        self._cart = ""
        self._cart_cleanup = cart_cleanup
        self._click_raises = click_raises
        self._goto_raises = goto_raises

    def goto(self, url, **kw):
        if self._goto_raises:
            raise RuntimeError("navigation failed")

    def click(self, selector):
        if self._click_raises:
            raise RuntimeError("element not found")
        self._cart = "synthetic-item"

    def evaluate(self, js):
        if js == ACTIONS_JS:
            return list(self._labels)
        if js == FORM_VALIDATION_JS:
            return dict(self._form)
        if js == READ_CART_JS:
            return self._cart
        if js == CLEAR_CART_JS:
            if self._cart_cleanup:
                self._cart = ""
            return self._cart
        return None


# --- profile selection -------------------------------------------------------------------------
def test_every_site_type_maps_to_a_profile():
    for st in SUPPORTED_SITE_TYPES:
        p = select_profile(st)
        assert p.site_type == st
        assert p.interaction_mode in ("public_passive", "public_reversible")


def test_profile_flow_mapping():
    assert select_profile(SITE_TYPE_ECOMMERCE).flow == FLOW_CART
    assert select_profile(SITE_TYPE_BOOKING).flow == FLOW_BOOKING
    assert select_profile(SITE_TYPE_B2B_SAAS).flow == FLOW_SAAS
    assert select_profile(SITE_TYPE_PROFESSIONAL).flow == FLOW_FORM
    assert select_profile(SITE_TYPE_PERSONAL).flow == FLOW_PASSIVE
    assert select_profile(SITE_TYPE_PERSONAL).interaction_mode == MODE_PASSIVE


def test_unknown_site_type_falls_back_safely():
    assert select_profile("nonsense").flow  # commercial default, no crash


# --- policy guard ------------------------------------------------------------------------------
def test_policy_blocks_irreversible_and_allows_reversible():
    assert is_irreversible("Reserve now") is True
    assert is_irreversible("Add to cart") is False
    assert is_reversible("Search") is True
    assert is_reversible("Book now") is False       # irreversible always wins
    try:
        check_action("Complete purchase")
        assert False, "should have stopped"
    except PolicyStop as ps:
        assert ps.action


def test_ambiguous_action_fails_closed():
    try:
        check_action("Frobnicate widget")
        assert False
    except PolicyStop as ps:
        assert ps.boundary == "ambiguous_action_fail_closed"


# --- the never-cross-boundary invariant across flows -------------------------------------------
def test_booking_stops_before_reserve_and_never_crosses():
    page = _FakePage(labels=["Check availability", "Reserve now"])
    res = run_vertical_flow(page, "http://fixture/booking", select_profile(SITE_TYPE_BOOKING))
    assert res.crossed_boundary is False
    assert res.stopped_before_boundary is True
    assert "reserve" in res.boundary.lower()
    assert any("reversible:Check availability" in s for s in res.steps)


def test_saas_inspects_signup_but_never_submits():
    page = _FakePage(labels=["Sign up", "Pricing", "Get started"])
    res = run_vertical_flow(page, "http://fixture/saas", select_profile(SITE_TYPE_B2B_SAAS))
    assert res.crossed_boundary is False
    assert res.stopped_before_boundary is True      # detected sign up, did not click


def test_form_validation_never_submits():
    page = _FakePage(labels=["Submit"], form={"form": True, "required": 3,
                                              "client_validation": True})
    res = run_vertical_flow(page, "http://fixture/contact", select_profile(SITE_TYPE_PROFESSIONAL))
    assert res.crossed_boundary is False
    assert res.stopped_before_boundary is True
    assert any("form_inspected" in s for s in res.steps)


def test_marketplace_browse_stops_before_order():
    page = _FakePage(labels=["Search", "Filter", "Message seller", "Order now"])
    res = run_vertical_flow(page, "http://fixture/mkt", select_profile(SITE_TYPE_MARKETPLACE))
    assert res.crossed_boundary is False
    assert res.stopped_before_boundary is True


def test_cart_flow_cleanup_verified_is_client_safe_capable():
    page = _FakePage(cart_cleanup=True)
    res = run_vertical_flow(page, "http://fixture/cart", select_profile(SITE_TYPE_ECOMMERCE))
    assert res.cleanup_verified is True
    assert res.client_safe_capable is True
    assert res.crossed_boundary is False


def test_cart_flow_cleanup_failure_is_not_client_safe():
    page = _FakePage(cart_cleanup=False)
    res = run_vertical_flow(page, "http://fixture/cart", select_profile(SITE_TYPE_ECOMMERCE))
    assert res.cleanup_verified is False
    assert res.client_safe_capable is False         # unclean session can never be client-safe


def test_flow_failclosed_on_navigation_error():
    page = _FakePage(goto_raises=True)
    res = run_vertical_flow(page, "http://fixture/booking", select_profile(SITE_TYPE_BOOKING))
    assert res.client_safe_capable is False
    assert res.crossed_boundary is False
    assert res.observations and res.observations[0].from_clean_session is False


def test_passive_profile_performs_no_interaction():
    page = _FakePage(labels=["Reserve now"])
    res = run_vertical_flow(page, "http://fixture/portfolio", select_profile(SITE_TYPE_PERSONAL))
    assert res.flow == FLOW_PASSIVE
    assert res.crossed_boundary is False
    assert res.stopped_before_boundary is False     # nothing interacted with at all
