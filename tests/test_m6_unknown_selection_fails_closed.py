"""M6, round 4 — an unreadable selection is unknown, not empty.

Round 3 bound the record to the promoted run's persisted `check_families` and then trusted that read
unconditionally. `_run_check_families()` collapsed four different facts into one empty list:

  * no run id at all,
  * `config.json` missing            -> `StoreError`,
  * `config.json` corrupt            -> `StoreCorruptionError`,
  * a config with no `check_families` key or a non-list value,

and a fifth, genuinely different fact — a run that really did select nothing — produced the same
value. The plan then published `coverage_verified=true` and a decision saying its selection came
"verbatim from the promoted run's persisted check_families", for a file it never managed to read.

The same gap sat one field over: a configured name that no executor provides was dropped from
`checks_selected` and the record still called itself verified, though part of what the run asked for
cannot be accounted for at all.

Empty is a fact. Unknown is the absence of one. Encoding them identically is what let the confidence
built for a successful read attach itself to a failed one.

Not in scope: adding executors, migrating persisted artifacts, letting a plan drive execution.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.scout.campaign_service import CampaignService
from core.scout.observer_api import ObserverAPI
from core.scout.presets import build_config
from core.scout.store import RunStore

_GOOD = "scout-20260731t100000z-good"
_MISSING = "scout-20260731t100000z-missing"
_CORRUPT = "scout-20260731t100000z-corrupt"
_NOKEY = "scout-20260731t100000z-nokey"
_UNKNOWNID = "scout-20260731t100000z-unknownid"
_EMPTY = "scout-20260731t100000z-empty"


def _config_path(tmp_path: Path, run_id: str) -> Path:
    return Path(RunStore(str(tmp_path), run_id).root) / "config.json"


def _seed(tmp_path: Path) -> None:
    """Six runs: one healthy, four whose selection cannot be established, one truly empty."""
    RunStore(str(tmp_path), _GOOD).write_config(
        {"campaign_name": "m6", "browser_mode": "static",
         "check_families": ["links", "seo", "business_flow"]})
    RunStore(str(tmp_path), _UNKNOWNID).write_config(
        {"campaign_name": "m6", "browser_mode": "static",
         "check_families": ["links", "not_a_real_executor"]})
    RunStore(str(tmp_path), _EMPTY).write_config(
        {"campaign_name": "m6", "browser_mode": "static", "check_families": []})
    RunStore(str(tmp_path), _NOKEY).write_config(
        {"campaign_name": "m6", "browser_mode": "static"})

    # A run directory that exists with no config at all -> StoreError on read.
    _config_path(tmp_path, _MISSING).parent.mkdir(parents=True, exist_ok=True)
    # A config that is real bytes on disk but not JSON -> StoreCorruptionError on read.
    corrupt = _config_path(tmp_path, _CORRUPT)
    corrupt.parent.mkdir(parents=True, exist_ok=True)
    corrupt.write_bytes(b'{"campaign_name": "m6", "check_families": ["links"')


def _promoted(domain: str, run_id: str) -> dict:
    return {"promotion_decision": "promoted", "registrable_domain": domain,
            "commercial_score": 62,
            "commercial_scorecard": {"dimensions": [{"name": "audit_opportunity", "value": 30}]},
            "country_hint": "US", "business_name": domain.split(".")[0].title(),
            "industry_hint": "ecommerce", "reason_codes": ["pricing_page"],
            "promoted_scout_run": run_id}


_CASES = {"good.test": _GOOD, "missing.test": _MISSING, "corrupt.test": _CORRUPT,
          "nokey.test": _NOKEY, "unknownid.test": _UNKNOWNID, "empty.test": _EMPTY}


def _plans(tmp_path: Path) -> dict:
    """Drive the real `_persist_brain` and read every plan back through Observer."""
    _seed(tmp_path)
    svc = CampaignService(output_dir=str(tmp_path))
    cfg = build_config("safe-live-acceptance", provider_allowlist=["tavily"],
                       output_dir=str(tmp_path), overrides={"strategy": "balanced"})
    svc._persist_brain(cfg, {"candidates": [_promoted(d, r) for d, r in _CASES.items()]})
    api = ObserverAPI(str(tmp_path))
    return {d: (api.get_target_test_plan(d).get("plan") or {}) for d in _CASES}


def test_the_fixture_really_produces_a_plan_for_every_case(tmp_path):
    """Guard on the setup: a case that silently produced no plan would prove nothing below."""
    plans = _plans(tmp_path)
    for domain, plan in plans.items():
        assert plan, f"{domain}: no plan was surfaced through Observer at all"
        assert plan.get("schema") == "scout-target-test-plan/v2", (domain, plan.get("schema"))


# --- an unreadable selection may not be published as verified coverage ----------------------------

@pytest.mark.parametrize("domain", ["missing.test", "corrupt.test", "nokey.test"])
def test_an_unreadable_run_config_is_not_verified_coverage(domain, tmp_path):
    plan = _plans(tmp_path)[domain]
    assert plan.get("coverage_verified") is False, (
        f"{domain}: the run's check_families could not be read, and the record is published as "
        f"verified coverage anyway: {plan}"
    )


@pytest.mark.parametrize("domain", ["missing.test", "corrupt.test", "nokey.test"])
def test_an_unreadable_run_config_is_not_reported_as_a_persisted_selection(domain, tmp_path):
    plan = _plans(tmp_path)[domain]
    said = " ".join(str(d) for d in (plan.get("decisions") or []))
    assert "verbatim from the promoted run's persisted check_families" not in said, (
        f"{domain}: the record claims its selection came from a persisted config it never read: "
        f"{plan.get('decisions')}"
    )
    assert plan.get("selection_status") == "unavailable", (
        f"{domain}: nothing distinguishes 'we could not read the selection' from 'the run selected "
        f"nothing': selection_status={plan.get('selection_status')!r}"
    )


@pytest.mark.parametrize("domain", ["missing.test", "corrupt.test", "nokey.test"])
def test_an_unknown_selection_does_not_deny_the_flow_either(domain, tmp_path):
    """Fail closed in both directions: not knowing is not the same as knowing it was absent."""
    plan = _plans(tmp_path)[domain]
    said = " ".join(str(d) for d in (plan.get("decisions") or []))
    assert "did not select business_flow" not in said, (
        f"{domain}: the selection could not be read, yet the record asserts what it did not "
        f"contain: {plan.get('decisions')}"
    )
    assert plan.get("flow") in ("", None), (
        f"{domain}: flow={plan.get('flow')!r} states a fact about a selection that was never read"
    )


def test_a_configured_name_with_no_executor_leaves_the_record_unverified(tmp_path):
    """Part of what the run asked for cannot be accounted for, so the record is not complete."""
    plan = _plans(tmp_path)["unknownid.test"]
    assert plan.get("checks_selected") == ["links"]
    assert plan.get("unrunnable_selected") == ["not_a_real_executor"], (
        f"the dropped name is not recorded as a structured gap: {plan}"
    )
    assert plan.get("coverage_verified") is False, (
        "the run configured a family this product cannot run, and the record still calls itself "
        f"verified: {plan}"
    )


# --- the counterparts, so 'unverified' cannot become a blanket disclaimer -------------------------

def test_a_readable_selection_is_still_verified(tmp_path):
    plan = _plans(tmp_path)["good.test"]
    assert plan.get("selection_status") == "persisted"
    assert plan.get("coverage_verified") is True, plan
    assert sorted(plan.get("checks_selected") or []) == ["business_flow", "links", "seo"]


def test_a_run_that_genuinely_selected_nothing_is_verified_and_says_so(tmp_path):
    """`check_families: []` is a fact that was read successfully — the opposite of unknown."""
    plan = _plans(tmp_path)["empty.test"]
    assert plan.get("selection_status") == "persisted"
    assert plan.get("checks_selected") == []
    assert plan.get("coverage_verified") is True, (
        f"a successfully read empty selection is being treated as an unreadable one: {plan}"
    )


def test_the_persisted_record_still_carries_no_derived_label(tmp_path):
    """Round 2's invariant, re-proved through this path."""
    _plans(tmp_path)
    paths = sorted((Path(tmp_path) / "scout" / "_campaigns").glob("*/BRAIN_DECISIONS.json"))
    assert paths, "the real boundary wrote no brain record"
    for decision in json.loads(paths[0].read_text(encoding="utf-8"))["decisions"]:
        assert "coverage_verified" not in decision["plan"]
        assert "legacy_vocabulary" not in decision["plan"]
