"""One run, one answer — whichever surface is asked.

The Observer and the Dashboard read the same runs and used to classify them separately: one by the
shape of the run id, the other by what the run declared about itself. A campaign minted with an
ordinary production-shaped id but launched as acceptance was then real work on one screen and a
diagnostic on the other, and there was no way to tell from either screen which was true.

The classifier is shared now. What this module pins is that it STAYS shared — a divergence here is
invisible in ordinary use, because both numbers are individually plausible and nobody compares them
until an audit does.

The two runs below are chosen so a surface that classifies by id alone gets BOTH of them wrong: a
production-shaped id that declared itself acceptance, and a smoke-shaped id that declared itself
production. A declaration is the run's own statement and outranks any reading of its name.
"""
from __future__ import annotations

import json

import pytest

_DECLARED_DIAGNOSTIC = "campaign-acme-20260728T090000Z-ab12cd"   # production-SHAPED id
_DECLARED_PRODUCTION = "smoke-a"                                 # diagnostic-SHAPED id
_PLAIN_PRODUCTION = "campaign-real-20260728T100000Z-ff99aa"


@pytest.fixture
def stand(tmp_path):
    scout = tmp_path / "scout"
    (scout / "_runcontrol").mkdir(parents=True)
    for run_id, purpose in ((_DECLARED_DIAGNOSTIC, "acceptance"),
                            (_DECLARED_PRODUCTION, "production"),
                            (_PLAIN_PRODUCTION, "production")):
        (scout / "_runcontrol" / f"{run_id}.json").write_text(
            json.dumps({"campaign_id": run_id, "status": "COMPLETED"}), encoding="utf-8")
        (scout / run_id).mkdir()
        (scout / run_id / "config.json").write_text(
            json.dumps({"campaign_name": "x", "run_purpose": purpose}), encoding="utf-8")
        (scout / run_id / "state.json").write_text(
            json.dumps({"status": "COMPLETED", "prospects": {}}), encoding="utf-8")
    return str(tmp_path)


def test_the_declaration_outranks_the_shape_of_the_id(stand):
    """Both surfaces depend on this being true; asserting it once here makes the parity tests below
    about AGREEMENT rather than about both being wrong in the same way."""
    from core.scout.canonical_runs import campaign_counts

    assert campaign_counts(stand) == {"production": 2, "diagnostic": 1, "total": 3}


def test_the_observer_counts_what_the_dashboard_counts(stand):
    from core.scout.canonical_runs import campaign_counts
    from core.scout.observer_api import ObserverAPI

    observed = ObserverAPI(stand).campaign_counts()
    canonical = campaign_counts(stand)

    assert {k: observed[k] for k in canonical} == canonical


def test_every_campaign_row_carries_the_same_verdict_on_both_surfaces(stand):
    """Totals can agree while individual rows disagree — two errors cancelling is not parity."""
    from core.scout.canonical_runs import canonical_campaigns
    from core.scout.observer_api import ObserverAPI

    listed = ObserverAPI(stand).list_campaigns(include_diagnostics=True)
    observer = {row["campaign_id"]: bool(row["diagnostic"]) for row in listed["campaigns"]}
    dashboard = {row["campaign_id"]: bool(row["diagnostic"])
                 for row in canonical_campaigns(stand, include_diagnostics=True)}

    assert observer == dashboard
    assert observer[_DECLARED_DIAGNOSTIC] is True
    assert observer[_DECLARED_PRODUCTION] is False


def test_the_observers_own_totals_agree_with_its_own_rows(stand):
    """The counters shipped beside the list must describe that list."""
    from core.scout.observer_api import ObserverAPI

    listed = ObserverAPI(stand).list_campaigns(include_diagnostics=True)
    rows = listed["campaigns"]

    assert listed["diagnostic_total"] == sum(1 for r in rows if r["diagnostic"])
    assert listed["production_total"] == sum(1 for r in rows if not r["diagnostic"])


def test_the_observer_says_which_build_produced_its_counts(stand):
    """A shared classifier only makes two processes agree while both are running it. This one is
    long-lived, so its answer is dated by the build that gave it — which is how the 10/1-versus-5/6
    disagreement gets explained rather than investigated."""
    from core.scout.observer_api import ObserverAPI

    build = ObserverAPI(stand).campaign_counts()["build"]

    assert build and build != "unknown"


def test_hiding_diagnostics_hides_exactly_the_diagnostic_rows(stand):
    from core.scout.observer_api import ObserverAPI

    production_only = ObserverAPI(stand).list_campaigns(include_diagnostics=False)
    ids = [row["campaign_id"] for row in production_only["campaigns"]]

    assert _DECLARED_DIAGNOSTIC not in ids
    assert sorted(ids) == sorted([_DECLARED_PRODUCTION, _PLAIN_PRODUCTION])
    assert production_only["production_total"] == 2
