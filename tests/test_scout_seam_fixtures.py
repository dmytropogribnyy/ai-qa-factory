"""The seam stand must seed EXACTLY the states the inspection depends on — a fixture that
silently drifts would make every later assertion vacuous."""
from __future__ import annotations

from core.scout.campaign_service import CampaignService
from core.scout.operator_state import OperatorStateStore
from core.scout.store import RunStore
from tests.scout_seam_fixtures import RUN_A, RUN_ARCHIVED, RUN_B, build_seam_stand


def test_primary_run_holds_every_seam_state(tmp_path):
    build_seam_stand(str(tmp_path))
    prospects = RunStore(str(tmp_path), RUN_A).load_state()["prospects"]
    by_status = {pid: p["status"] for pid, p in prospects.items()}

    assert by_status == {
        "01-alpha": "DONE",
        "02-beta": "MANUAL_ACTION_REQUIRED",
        "03-gamma": "FAILED",
        "04-delta": "PENDING",
        "05-epsilon": "DONE",
        "06-theta": "DONE",
        "07-eta": "SKIPPED",
    }


def test_delta_is_the_interrupted_state_pending_with_findings_on_disk(tmp_path):
    build_seam_stand(str(tmp_path))
    store = RunStore(str(tmp_path), RUN_A)
    delta = store.load_state()["prospects"]["04-delta"]

    assert delta["status"] == "PENDING"
    assert "verified_findings" not in delta and "verified_defects" not in delta
    findings = store.load_prospect_artifact("04-delta", "findings.json")
    assert len(findings["verified"]) == 2          # the artifact the compact state never learned about


def test_done_targets_carry_counters_that_match_their_artifact(tmp_path):
    build_seam_stand(str(tmp_path))
    store = RunStore(str(tmp_path), RUN_A)
    state = store.load_state()["prospects"]

    for pid in ("01-alpha", "05-epsilon", "06-theta"):
        verified = store.load_prospect_artifact(pid, "findings.json")["verified"]
        defects = [f for f in verified if f["severity"] != "info"]
        assert state[pid]["verified_findings"] == len(verified)
        assert state[pid]["verified_defects"] == len(defects)


def test_epsilon_is_legacy_without_coverage_and_theta_is_clean_with_coverage(tmp_path):
    build_seam_stand(str(tmp_path))
    state = RunStore(str(tmp_path), RUN_A).load_state()["prospects"]

    assert "coverage" not in state["05-epsilon"]                    # legacy run: genuinely unavailable
    assert state["06-theta"]["coverage"] == "adaptive"              # honestly clean, not "unanalyzed"
    assert state["06-theta"]["verified_findings"] == 0


def test_second_run_over_alpha_is_distinguishable_from_the_first(tmp_path):
    build_seam_stand(str(tmp_path))
    a = RunStore(str(tmp_path), RUN_A).load_state()["prospects"]["01-alpha"]
    b = RunStore(str(tmp_path), RUN_B).load_state()["prospects"]["01-alpha"]

    assert (a["verified_findings"], a["verified_defects"]) == (5, 3)
    assert (b["verified_findings"], b["verified_defects"]) == (2, 1)   # pinning is falsifiable
    titles_a = {f["title"] for f in RunStore(str(tmp_path), RUN_A)
                .load_prospect_artifact("01-alpha", "findings.json")["verified"]}
    titles_b = {f["title"] for f in RunStore(str(tmp_path), RUN_B)
                .load_prospect_artifact("01-alpha", "findings.json")["verified"]}
    assert not (titles_a & titles_b)                                  # no shared title to confuse them


def test_zeta_resolves_to_the_run_but_has_no_prospect(tmp_path):
    build_seam_stand(str(tmp_path))
    det = CampaignService(str(tmp_path)).target_detail("zeta.example", run=RUN_A)
    assert det["evidence_status"] == "prospect_not_found"


def test_archived_run_is_marked_archived(tmp_path):
    build_seam_stand(str(tmp_path))
    assert OperatorStateStore(str(tmp_path)).run_archived(RUN_ARCHIVED) is True
