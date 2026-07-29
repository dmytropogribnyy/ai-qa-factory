"""An expectation nobody established cannot be violated.

The filter scenario reported a defect whenever a checkbox was ticked and the result list stayed the
same. That reads as an oracle and is not one: it assumes the control applies itself, and that the
chosen facet must exclude something. Neither is true of the commonest filter on the web — a group of
checkboxes above a separate **Apply** button. Ticking one there is SUPPOSED to change nothing until
the button is pressed, so correct behaviour was being sent to a stranger as a functional defect.

A defect claim needs two positive facts, and this module refuses to let either be assumed:

1. the control applies itself — no submit-style control sits with it, so nothing else was meant to
   happen first;
2. the site itself said the filter took effect — it moved to a filtered URL, or offered a way to
   clear the filter it did not offer before.

Without both, the honest outcome is that this scenario did not apply here. The recording is still
kept and still explained; it simply is not an accusation.

The package side of the same rule: a clip of a control working is not a reproduction of a defect,
and it does not travel to a client counted as one, or without a record saying what it showed.
"""
from __future__ import annotations

import json
import zipfile

import pytest

from core.scout.interaction_scenario import (OUTCOME_DEFECT, OUTCOME_NOT_APPLICABLE, SCENARIO_FILTER,
                                             ScenarioResult, classify, finding_from)

_DOMAIN = "filtershop.example"
_ITEMS = ["24", "Blue mug", "Red mug", "Green mug"]


def _measure(**over):
    """One measurement of the page: what a filter would be judged on."""
    base = {"control_engaged": True, "result_count": 24, "item_signature": list(_ITEMS),
            "url": f"https://{_DOMAIN}/shop", "apply_control": "", "clear_control": "",
            "facet_count": None}
    base.update(over)
    return base


def _classify(baseline, observed):
    return classify(SCENARIO_FILTER, baseline, observed, action_performed=True, cleanup_ok=True)


# --- 1. the control must be the kind that applies itself ------------------------------------------

def test_a_checkbox_beside_an_apply_button_is_not_a_defect():
    """The exact shape that was being reported: a facet group with its own Apply button."""
    outcome, reason = _classify(_measure(control_engaged=False, apply_control="Apply filters"),
                                _measure(apply_control="Apply filters"))

    assert outcome == OUTCOME_NOT_APPLICABLE
    assert "Apply filters" in reason


def test_the_same_page_analysed_twice_yields_no_actionable_finding():
    """Two identical passes over the fixture shape. Neither may produce a finding — a defect that
    depends on nothing but our own assumption would appear in both, twice as convincingly."""
    outcomes = []
    for _ in range(2):
        outcome, reason = _classify(_measure(control_engaged=False, apply_control="Apply"),
                                    _measure(apply_control="Apply"))
        outcomes.append(outcome)
        result = ScenarioResult(scenario=SCENARIO_FILTER, outcome=outcome, reason=reason,
                                url=f"https://{_DOMAIN}/shop", action_performed=True,
                                cleanup_ok=True, observed=_measure(apply_control="Apply"))
        assert finding_from(result, run_id="r", prospect_ref="p") is None

    assert outcomes == [OUTCOME_NOT_APPLICABLE, OUTCOME_NOT_APPLICABLE]


# --- 2. and the site must have said the filter took effect ----------------------------------------

def test_a_filter_that_never_signalled_it_applied_is_not_a_defect():
    """No Apply button, but nothing says the site considers the filter active either. Silence is not
    evidence of a broken filter — it is the absence of an oracle."""
    outcome, reason = _classify(_measure(control_engaged=False), _measure())

    assert outcome == OUTCOME_NOT_APPLICABLE
    assert "not" in reason.lower()


def test_an_applied_filter_that_changed_nothing_claims_nothing_without_a_witness():
    """The site moved to a filtered URL and the identical list came back — and that is still not a
    defect, because every visible item may legitimately match the chosen facet (filter "In stock"
    on a page where everything is). Application proves application. A defect needs machine proof
    that at least one listed item fails the facet, and this page offers none."""
    outcome, reason = _classify(
        _measure(control_engaged=False),
        _measure(url=f"https://{_DOMAIN}/shop?colour=blue"))

    assert outcome == OUTCOME_NOT_APPLICABLE
    assert "match" in reason.lower()


def test_a_clear_control_appearing_without_a_witness_still_claims_nothing():
    """Same rule for the other application signal: a "Clear filters" affordance proves the filter
    is in effect, not that any listed item fails it."""
    outcome, _ = _classify(_measure(control_engaged=False),
                           _measure(clear_control="Clear all filters"))

    assert outcome == OUTCOME_NOT_APPLICABLE


# --- 3. and a defect claim needs the page's own arithmetic to conflict ----------------------------

def test_a_filter_showing_more_results_than_its_facet_promises_is_a_defect():
    """The one generic machine-checkable witness: the facet's own count. The page says 5 items
    match "Blue", confirms the filter applied, and keeps listing 24 — by the site's own two
    numbers at least 19 listed results cannot match the facet."""
    outcome, reason = _classify(
        _measure(control_engaged=False, facet_count=5),
        _measure(url=f"https://{_DOMAIN}/shop?colour=blue", facet_count=5))

    assert outcome == OUTCOME_DEFECT
    assert "24" in reason and "5" in reason


def test_a_clear_filter_affordance_with_a_witness_is_also_the_site_saying_so():
    outcome, _ = _classify(_measure(control_engaged=False, facet_count=5),
                           _measure(clear_control="Clear all filters", facet_count=5))

    assert outcome == OUTCOME_DEFECT


def test_a_facet_that_covers_every_listed_item_is_not_a_defect():
    """"In stock (24)" over 24 results that stay 24: the filter changed nothing because nothing
    needed to change. The numbers agree, so there is no witness and no claim."""
    outcome, reason = _classify(
        _measure(control_engaged=False, facet_count=24),
        _measure(url=f"https://{_DOMAIN}/shop?instock=1", facet_count=24))

    assert outcome == OUTCOME_NOT_APPLICABLE


def test_the_finding_states_the_sites_own_numbers_not_an_assumption():
    """The old finding text asserted "the same non-matching items remain listed" — a claim nothing
    machine-checked. The finding must carry the proven arithmetic instead."""
    baseline = _measure(control_engaged=False, facet_count=5)
    observed = _measure(url=f"https://{_DOMAIN}/shop?colour=blue", facet_count=5)
    outcome, reason = _classify(baseline, observed)
    result = ScenarioResult(scenario=SCENARIO_FILTER, outcome=outcome, reason=reason,
                            url=f"https://{_DOMAIN}/shop", control_label="Blue",
                            action_performed=True, cleanup_ok=True,
                            baseline=baseline, observed=observed)

    finding = finding_from(result, run_id="r", prospect_ref="p")

    assert finding is not None
    assert "5" in finding.actual and "24" in finding.actual
    assert "non-matching items remain" not in finding.actual


# --- 3. the package calls the recording what it is ------------------------------------------------

@pytest.fixture
def packaged(tmp_path):
    from core.scout.campaign_service import CampaignService
    from core.scout.client_evidence import build_client_evidence_bundle
    from core.scout.discovery.analyzed_registry import ANALYZED, AnalyzedSiteRegistry
    from core.scout.store import RunStore

    store = RunStore(str(tmp_path), "run-trace")
    store.write_config({"campaign_name": "adhoc", "run_purpose": "production",
                        "video_mode": "auto"})
    store.save_state({"status": "COMPLETED", "prospects": {
        "01": {"status": "DONE", "url": f"https://{_DOMAIN}/", "verified_findings": 1,
               "verified_defects": 1, "interaction_video_ref": "interaction.webm"}}})
    store.save_prospect_artifact("01", "findings.json", {"verified": [
        {"title": "Image missing alt text", "severity": "medium", "signature": "a11y-1",
         "url": f"https://{_DOMAIN}/", "category": "accessibility"}]})
    store.save_prospect_artifact("01", "interaction_scenario.json", {
        "scenario": SCENARIO_FILTER, "outcome": OUTCOME_NOT_APPLICABLE,
        "reason": "the page has a separate 'Apply filters' control, so ticking this filter is not "
                  "expected to change the results on its own",
        "url": f"https://{_DOMAIN}/shop", "control_label": "Blue", "action": "check",
        "action_performed": True, "cleanup_ok": True,
        "steps": ["opened the page", "ticked 'Blue'", "unticked 'Blue'"]})
    (store.prospect_dir("01") / "interaction.webm").write_bytes(b"\x1a\x45\xdf\xa3" + bytes(2048))
    AnalyzedSiteRegistry(str(tmp_path)).record_analysis(_DOMAIN, status=ANALYZED,
                                                        campaign_id="run-trace")

    detail = CampaignService(str(tmp_path)).target_detail(_DOMAIN, run="run-trace")
    bundle = build_client_evidence_bundle(str(tmp_path), run_id="run-trace", prospect_id="01",
                                          domain=_DOMAIN, detail=detail)
    with zipfile.ZipFile(bundle.path) as archive:
        return {name.split("/", 1)[1]: archive.read(name)
                for name in archive.namelist() if "/" in name}


def _text(packaged, name):
    return packaged[name].decode("utf-8")


def test_the_clip_is_not_counted_as_a_reproduction(packaged):
    """A client reading "1 reproduction video" believes a defect was reproduced for them."""
    readme = _text(packaged, "00-README.html")
    summary = _text(packaged, "Evidence/Technical/scan-summary.md")

    assert "1</strong> reproduction video" not in readme
    assert "Reproduction videos included: **1**" not in summary
    assert "recorded interaction" in readme.lower()
    assert "recorded interaction" in summary.lower()


def test_the_clip_travels_with_a_record_of_what_it_showed(packaged):
    """The alternative to excluding it: an honest, structured account beside the clip."""
    record = json.loads(_text(packaged, "Evidence/Technical/interaction.json"))

    assert record["outcome"] == OUTCOME_NOT_APPLICABLE
    assert "Apply filters" in record["reason"]
    assert record["cleanup_ok"] is True
    assert "Blue" in record["control_label"]


def test_the_recording_is_still_named_for_what_it_is(packaged):
    assert any(name.startswith("Evidence/Videos/interaction-") for name in packaged)
    assert not any(name.startswith("Evidence/Videos/reproduction-") for name in packaged)
