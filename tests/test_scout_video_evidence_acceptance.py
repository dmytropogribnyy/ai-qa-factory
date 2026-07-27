"""Real-browser acceptance for reproduction video — the one evidence type nothing else proves.

The deterministic video tests drive the gates with fakes: they prove the DECISION (keep only a
genuinely replayed defect, never a page-load clip) but not that a real Chromium context actually
records a file. These do, against the bundled fixture site, and they pin both directions:

- a dead conversion entry is replayed, misbehaves, and yields a real `.webm` bound to the finding;
- the same run with a working entry keeps no video at all -- absence is a verdict, not a failure.

No external site is touched and no side effect is performed: the reproduction navigates, observes,
and stops.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from core.scout.backends import PlaywrightBackend
from core.scout.config import ScoutRunConfig
from core.scout.engine import ScoutEngine, P_DONE
from core.scout.store import RunStore
from tests.scout_fixtures import serve_fixtures


def _chromium_available() -> bool:
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            b = p.chromium.launch(headless=True)
            b.close()
        return True
    except Exception:
        return False


pytestmark = [
    pytest.mark.playwright_acceptance,
    pytest.mark.skipif(not _chromium_available(),
                       reason="Chromium build not available (run: python -m playwright install chromium)"),
]

_counter = itertools.count()


def _clock():
    return f"2026-07-27T12:00:{next(_counter):02d}+00:00"


def _run(tmp_path, base, host, path, run_id, video_mode):
    cfg = ScoutRunConfig(campaign_name="video", seeds=[f"{base}{path}"],
                         allowed_local_hosts=frozenset({host}), browser_mode="playwright",
                         output_dir=str(tmp_path), max_pages_per_site=4, video_mode=video_mode,
                         resolve_dns=False)
    store = RunStore(str(tmp_path), run_id)
    backend = PlaywrightBackend(policy=cfg.url_policy())
    state = ScoutEngine(cfg, store, backend=backend, clock=_clock).run()
    pid = next(iter(state["prospects"]))
    return store, pid, state["prospects"][pid]


def test_a_dead_conversion_entry_is_replayed_and_recorded(tmp_path):
    with serve_fixtures() as (base, host):
        store, pid, prospect = _run(tmp_path, base, host, "/broken_flow/index.html",
                                    "run-video-yes", "qualified_auto")

    assert prospect["status"] == P_DONE
    record = store.load_prospect_artifact(pid, "reproduction.json")
    assert record, "a qualifying interaction finding recorded no reproduction at all"
    assert record["signature"] == "flow_entry_broken"
    assert record["reproduced"] is True
    assert record["reproduction_status"] == "reproduced"
    assert record["precondition_ok"] is True          # the start page really loaded first
    assert record["cleanup_ok"] is True
    assert record["video_ref"] == "reproduction.webm"

    clip = Path(store.prospect_dir(pid)) / "reproduction.webm"
    assert clip.is_file() and clip.stat().st_size > 1000, "the recorded clip is empty or missing"
    assert not (Path(store.prospect_dir(pid)) / "_vidtmp").exists()      # no stray recordings left
    assert not (Path(store.prospect_dir(pid)) / "_reprotmp").exists()


def test_a_working_flow_entry_records_nothing_however_hard_we_look(tmp_path):
    """The guard that matters most: a page that merely loads must never become "evidence"."""
    with serve_fixtures() as (base, host):
        store, pid, prospect = _run(tmp_path, base, host, "/business_flow/index.html",
                                    "run-video-no", "qualified_auto")

    assert prospect["status"] == P_DONE
    pdir = Path(store.prospect_dir(pid))
    assert not (pdir / "reproduction.webm").exists()
    assert not list(pdir.glob("*.webm")), "a page-load clip was kept as reproduction evidence"


def test_manual_mode_records_nothing_even_for_a_dead_entry(tmp_path):
    """Capture policy wins over opportunity: opt-in means opt-in."""
    with serve_fixtures() as (base, host):
        store, pid, _prospect = _run(tmp_path, base, host, "/broken_flow/index.html",
                                     "run-video-manual", "manual")

    pdir = Path(store.prospect_dir(pid))
    assert not list(pdir.glob("*.webm"))
    assert store.load_prospect_artifact(pid, "reproduction.json") is None


def test_the_client_package_carries_the_video_and_drops_the_excuse(tmp_path):
    """When a video exists the package ships it and stops explaining an absence that is not there."""
    from core.scout.campaign_service import CampaignService
    from core.scout.client_evidence import build_client_evidence_bundle
    import zipfile

    with serve_fixtures() as (base, host):
        store, pid, _prospect = _run(tmp_path, base, host, "/broken_flow/index.html",
                                     "run-video-bundle", "qualified_auto")
        domain = json.loads((store.prospect_dir(pid) / "observation.json").read_text(
            encoding="utf-8"))["final_url"].split("//")[1].split("/")[0]
        detail = CampaignService(str(tmp_path)).target_detail(domain, run="run-video-bundle")
        bundle = build_client_evidence_bundle(str(tmp_path), run_id="run-video-bundle",
                                              prospect_id=pid, domain=domain, detail=detail)

    with zipfile.ZipFile(bundle.path) as archive:
        names = set(archive.namelist())
        summary = archive.read("QA_Evidence_Summary.md").decode("utf-8")

    assert any(n.startswith("evidence/reproduction/") for n in names)
    assert "technical/reproduction.json" in names
    assert "Reproduction videos included: **1**" in summary
    assert "No reproduction video" not in summary
