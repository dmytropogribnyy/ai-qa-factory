"""What the recorder must refuse to touch, and why refusing is the whole licence.

Scout clicks a control on a stranger's website. The only thing that makes that acceptable is that
the action is reversible, that we can tell it was reversed, and that nothing was written to anybody's
server. Each of those was checked partially or not at all:

* the control was screened with a DENY list — a label that failed to match a forbidden word was
  allowed, so an unlabelled control and a bare "Add" both passed;
* the select's own label was screened and the option it was about to be switched TO was not;
* a comment in the finder claimed the select was checked for a submit-on-change form. No such check
  existed anywhere in the file;
* the request router allowed any method to an allow-listed domain, so a POST fired by a click went
  out because the DOMAIN was permitted — permission to read read as permission to write.

These are unit tests over the screening functions and the router, not browser tests: they pin the
decisions, and the browser acceptance tests exercise the same code against a real page.
"""
from __future__ import annotations

import pytest

from core.scout.interaction_scenario import (OUTCOME_NOT_APPLICABLE, OUTCOME_NOT_RUN,
                                             SAFE_HTTP_METHODS, SCENARIO_ADD_REMOVE,
                                             SCENARIO_FILTER, SCENARIO_SELECT, classify,
                                             safe_option, screen_candidate)


def _candidate(**over):
    return {"kind": SCENARIO_FILTER, "label": "Blue", "selector": "[data-aiqa-control]",
            "click_selector": "[data-aiqa-click]", "side_effect": "", **over}


# --- an unreadable control is refused, not guessed at ----------------------------------------------

@pytest.mark.parametrize("label", ["", "   ", "x", None])
def test_a_control_with_no_readable_label_is_refused(label):
    """An empty-label select was allowed: nothing about it could be checked, and it was clicked."""
    allowed, reason = screen_candidate(_candidate(kind=SCENARIO_SELECT, label=label))

    assert allowed is False
    assert "no readable label" in reason


def test_a_label_that_is_not_a_label_is_refused():
    allowed, reason = screen_candidate(_candidate(label="x" * 200))

    assert allowed is False
    assert "a person would read" in reason


# --- the deny list is still enforced, and is no longer the only thing enforced ---------------------

@pytest.mark.parametrize("label", ["Subscribe", "Place order", "Confirm payment", "Create account"])
def test_a_control_crossing_an_irreversible_boundary_is_refused(label):
    allowed, reason = screen_candidate(_candidate(label=label))

    assert allowed is False
    assert "irreversible boundary" in reason


# --- an ADD control is recognised by its label, because there the label IS the action --------------

@pytest.mark.parametrize("label", ["Add", "Add item", "Add another", "Add row"])
def test_an_ambiguous_add_control_is_refused(label):
    """A bare "Add" says nothing about what it adds. Failing to match a forbidden word is not consent."""
    allowed, reason = screen_candidate(_candidate(kind=SCENARIO_ADD_REMOVE, label=label))

    assert allowed is False
    assert "reversible action" in reason


def test_a_known_reversible_add_control_is_allowed():
    """Fail-closed must not become fail-always: a named, reversible action still runs."""
    allowed, reason = screen_candidate(_candidate(kind=SCENARIO_ADD_REMOVE, label="Add to cart"))

    assert allowed is True and reason == ""


def test_a_filter_facet_value_is_allowed_even_though_no_list_contains_it():
    """A filter is recognised by SHAPE. "Blue" could never appear on a list of approved actions."""
    assert screen_candidate(_candidate(label="Blue"))[0] is True
    assert screen_candidate(_candidate(label="Under $50"))[0] is True


# --- form / onchange side effects: the check the finder's comment promised -------------------------

@pytest.mark.parametrize("effect", [
    "the control submits or resets a form",
    "the control runs an inline handler that submits a form",
    "the control is inside a form that does not use GET",
    "the surrounding form runs an onsubmit handler",
])
def test_a_control_with_a_form_side_effect_is_refused(effect):
    allowed, reason = screen_candidate(_candidate(kind=SCENARIO_SELECT, label="Sort by",
                                                  side_effect=effect))

    assert allowed is False
    assert reason == effect


# --- the option a select is switched TO is screened, not only the select ---------------------------

@pytest.mark.parametrize("option", ["Place order", "Confirm payment", "Subscribe"])
def test_an_irreversible_option_is_refused(option):
    """The select passing its own label check says nothing about what is inside it."""
    allowed, reason = safe_option(option)

    assert allowed is False
    assert "irreversible boundary" in reason


@pytest.mark.parametrize("option", ["", "  ", "x"])
def test_an_unreadable_option_is_refused(option):
    assert safe_option(option)[0] is False


def test_an_ordinary_option_is_allowed():
    assert safe_option("Price: low to high") == (True, "")


# --- nothing found at all vs something found and declined -----------------------------------------

def test_no_candidate_at_all_is_reported_differently_from_a_refusal():
    """"There was nothing here" and "there was something and we would not touch it" are not the
    same fact, and an operator reading the run needs to be able to tell them apart."""
    allowed, reason = screen_candidate(None)

    assert allowed is False
    assert "no reversible control" in reason


# --- the wire: reading a site is not permission to write to it ------------------------------------

class _Route:
    def __init__(self, method, url):
        self.request = type("R", (), {"method": method, "url": url})()
        self.action = ""

    def continue_(self):
        self.action = "continue"

    def abort(self):
        self.action = "abort"


def _backend():
    from core.scout.backends import PlaywrightBackend
    backend = PlaywrightBackend.__new__(PlaywrightBackend)
    backend._url_allowed = lambda url: "allowed.example" in str(url)
    return backend


@pytest.mark.parametrize("method", sorted(SAFE_HTTP_METHODS))
def test_a_read_is_allowed_through(method):
    from core.scout.interaction_scenario import ScenarioResult
    result, route = ScenarioResult(), _Route(method, "https://allowed.example/data")

    _backend()._route_readonly(route, result)

    assert route.action == "continue"
    assert result.blocked_requests == []


@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE"])
def test_a_write_to_an_allowed_domain_is_still_blocked(method):
    """The exact hole: same-domain writes went out because the DOMAIN was permitted."""
    from core.scout.interaction_scenario import ScenarioResult
    result, route = ScenarioResult(), _Route(method, "https://allowed.example/cart/add")

    _backend()._route_readonly(route, result)

    assert route.action == "abort"
    assert result.blocked_requests == [{"method": method, "url": "https://allowed.example/cart/add"}]


def test_a_request_to_another_domain_is_blocked_whatever_its_method():
    from core.scout.interaction_scenario import ScenarioResult
    result, route = ScenarioResult(), _Route("GET", "https://elsewhere.example/pixel")

    _backend()._route_readonly(route, result)

    assert route.action == "abort"


# --- what the outcome may be once a write was refused or a cleanup failed --------------------------

def test_a_refused_write_makes_the_result_unjudgeable_rather_than_a_defect():
    """The page is missing a response it would normally have had — because WE stopped it. Calling
    that a defect reports our own guard as the site's fault."""
    outcome, reason = classify(SCENARIO_FILTER, {"result_count": 10, "control_label": "Blue"},
                               {"result_count": 10, "control_engaged": True},
                               action_performed=True, cleanup_ok=True, blocked_writes=1)

    assert outcome == OUTCOME_NOT_APPLICABLE
    assert "would have changed data" in reason


def test_an_unverified_restore_is_not_applicable_rather_than_a_trace():
    outcome, reason = classify(SCENARIO_SELECT, {"selected_label": "A"}, {"selected_label": "B"},
                               action_performed=True, cleanup_ok=False)

    assert outcome == OUTCOME_NOT_APPLICABLE
    assert "restored" in reason


def test_a_clean_reversible_filter_still_reaches_its_verdict():
    """The guards must not swallow the outcome they exist to protect.

    The page states the filter is now in effect — it offers to clear it — and returns the same ten
    results. That pair is the defect; an unchanged list on its own is not (see
    tests/test_scout_interaction_oracle.py).
    """
    outcome, _reason = classify(SCENARIO_FILTER, {"result_count": 10, "control_label": "Blue"},
                                {"result_count": 10, "control_engaged": True,
                                 "clear_control": "Clear all filters"},
                                action_performed=True, cleanup_ok=True)

    assert outcome == "defect"


def test_an_action_that_never_ran_is_still_not_run():
    outcome, _reason = classify(SCENARIO_FILTER, {}, {}, action_performed=False, cleanup_ok=False)

    assert outcome == OUTCOME_NOT_RUN


def test_a_not_applicable_scenario_never_keeps_a_clip():
    from core.scout.interaction_scenario import ScenarioResult

    refused = ScenarioResult(scenario=SCENARIO_SELECT, outcome=OUTCOME_NOT_APPLICABLE,
                             action_performed=True, cleanup_ok=False)

    assert refused.keeps_video is False
