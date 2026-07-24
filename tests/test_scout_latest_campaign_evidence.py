"""Target cards and Observer must resolve the newest persisted campaign decision."""
from __future__ import annotations

import urllib.request

from core.scout.campaign_service import CampaignService
from core.scout.dashboard import start_dashboard
from core.scout.observer_api import ObserverAPI
from core.scout.service import ScoutService
from core.scout.store import RunStore


def _run(output, run_id: str, finding_title: str, screenshot_name: str) -> None:
    store = RunStore(str(output), run_id)
    store.write_config({"campaign_name": "freshness-regression"})
    store.save_state({
        "status": "COMPLETED",
        "prospects": {
            "01-amasty": {
                "url": "https://amasty.com/",
                "status": "DONE",
            },
        },
    })
    store.save_prospect_artifact("01-amasty", "observation.json", {
        "url": "https://amasty.com/",
        "final_url": "https://amasty.com/",
        "status": 200,
        "timing_ms": {"load": 10},
    })
    store.save_prospect_artifact("01-amasty", "findings.json", {
        "verified": [{
            "finding_id": f"id-{run_id}",
            "signature": f"sig-{run_id}",
            "severity": "medium",
            "category": "seo",
            "title": finding_title,
            "business_impact": "Persisted campaign-specific impact",
            "url": "https://amasty.com/",
            "evidence_refs": [],
            "confidence": "high",
        }],
        "rejected": [],
    })
    store.save_bytes(["prospects", "01-amasty", screenshot_name], b"PNG")


def _brain(campaign_id: str, at: str, run_id: str, priority: str) -> dict:
    return {
        "campaign_id": campaign_id,
        "at": at,
        "decisions": [{
            "domain": "amasty.com",
            "priority": priority,
            "scout_run": run_id,
            "brain": {"marker": run_id},
        }],
    }


def test_target_and_observer_select_latest_persisted_campaign(tmp_path):
    service = CampaignService(str(tmp_path))
    _run(tmp_path, "run-old", "old campaign finding", "old.png")
    _run(tmp_path, "run-new", "fresh campaign finding", "fresh.png")

    # Deliberately create the old decision first and give it the lexically later directory name.
    # The former glob-first implementation therefore returned stale evidence on real filesystems.
    service._write(
        "z-old-campaign",
        "BRAIN_DECISIONS.json",
        _brain("z-old-campaign", "2026-07-22T14:52:52+00:00", "run-old", "C"),
    )
    service._write(
        "a-new-campaign",
        "BRAIN_DECISIONS.json",
        _brain("a-new-campaign", "2026-07-22T16:38:24+00:00", "run-new", "A"),
    )

    detail = service.target_detail("amasty.com")
    assert detail["scout_run"] == "run-new"
    assert detail["brain"]["priority"] == "A"
    assert [f["title"] for f in detail["findings"]] == ["fresh campaign finding"]
    assert detail["media"] == ["prospects/01-amasty/fresh.png"]

    observed = ObserverAPI(str(tmp_path)).get_target("amasty.com")
    assert observed["scout_run"] == "run-new"
    assert observed["brain"]["priority"] == "A"

    dashboard, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        with urllib.request.urlopen(
            f"{url}/scout/target?domain=amasty.com", timeout=5
        ) as response:
            html = response.read().decode("utf-8")
    finally:
        dashboard.shutdown()
        dashboard.server_close()
    assert "fresh campaign finding" in html
    assert "old campaign finding" not in html
    assert "Policy ceiling" in html
    assert "Current automatic Scout execution uses read-only navigation" in html
    assert "Recheck / Reproduce / Record short video" not in html


def test_legacy_brains_without_timestamp_use_stable_campaign_fallback(tmp_path):
    service = CampaignService(str(tmp_path))
    service._write(
        "a-legacy",
        "BRAIN_DECISIONS.json",
        _brain("a-legacy", "", "run-a", "C"),
    )
    service._write(
        "z-legacy",
        "BRAIN_DECISIONS.json",
        _brain("z-legacy", "not-a-date", "run-z", "B"),
    )
    (service._campaign_dir("malformed") / "BRAIN_DECISIONS.json").write_text(
        "[]", encoding="utf-8"
    )

    decision = service._brain_for_domain("amasty.com")
    assert decision is not None
    assert decision["scout_run"] == "run-z"
    assert decision["priority"] == "B"
