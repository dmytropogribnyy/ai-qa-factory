"""Bounded Scout browser evidence: two frames, redaction, integrity, and UI/Observer linkage."""
from __future__ import annotations

import hashlib
import json
import urllib.request
from pathlib import Path

import pytest

from core.scout.backends import PageObservation
from core.scout.campaign_service import CampaignService
from core.scout.config import ScoutRunConfig
from core.scout.dashboard import start_dashboard
from core.scout.engine import ScoutEngine
from core.scout.observer_api import ObserverAPI, ObserverError
from core.scout.sanitize import Sanitizer
from core.scout.service import ScoutService
from core.scout.store import RunStore


class _EvidenceBackend:
    name = "playwright"
    screenshot_dir = None
    screenshot_filename = "page.png"

    def __init__(self):
        self.calls = 0

    def observe(self, url, timeout_s, max_bytes, *, record_video=False, deep_qa=False):
        self.calls += 1
        shot = ""
        if self.screenshot_dir:
            p = Path(self.screenshot_dir) / self.screenshot_filename
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(f"PNG-{self.calls}".encode())
            shot = self.screenshot_filename
        return PageObservation(
            url=f"{url}?api_key=do-not-persist#private",
            final_url=f"{url}?token=do-not-persist",
            status=200,
            ok=True,
            backend=self.name,
            screenshot_ref=shot,
            title="Public page",
            console_errors=["Bearer abcdefghijklmnopqrstuvwxyz"],
            failed_resources=[f"{url}/broken.js?secret=do-not-persist"],
            blocked_requests=["http://user:password@10.0.0.5/private?token=x"],
            links=["mailto:person@example.com?subject=private"],
            timing_ms={"load": 12.5},
        )


def _run(tmp_path):
    backend = _EvidenceBackend()
    cfg = ScoutRunConfig(
        campaign_name="bounded-evidence",
        seeds=["https://ex.com/path"],
        browser_mode="playwright",
        video_mode="qualified_auto",
        output_dir=str(tmp_path),
        max_pages_per_site=1,
        resolve_dns=False,
    )
    store = RunStore(str(tmp_path), "run-bounded")
    state = ScoutEngine(cfg, store, backend=backend).run()
    pid = next(iter(state["prospects"]))
    return store, pid


def test_evidence_bundle_keeps_two_frames_redacts_and_cleans(tmp_path):
    store, pid = _run(tmp_path)
    pdir = store.prospect_dir(pid)

    assert (pdir / "landing.png").read_bytes() == b"PNG-1"
    assert (pdir / "verification.png").read_bytes() == b"PNG-2"
    assert not (pdir / "page.png").exists()
    assert not (pdir / "_vidtmp").exists() and not (pdir / "_reprotmp").exists()

    observation_text = (pdir / "observation.json").read_text(encoding="utf-8")
    assert "do-not-persist" not in observation_text
    assert "abcdefghijklmnopqrstuvwxyz" not in observation_text
    observation = json.loads(observation_text)
    assert observation["url"] == "https://ex.com/path"
    assert observation["links"] == ["mailto:[REDACTED_EMAIL]"]
    assert observation["headers"] == {} and observation["raw_headers_stored"] is False
    assert observation["redaction_applied"] is True
    assert Sanitizer().safe_url(
        "https://user:password@example.com:not-a-port/path?token=must-not-persist"
    ) == "https://example.com/path"

    trace = json.loads((pdir / "browser_trace.json").read_text(encoding="utf-8"))
    assert trace["redaction_applied"] is True
    assert trace["raw_dom_stored"] is False and trace["raw_headers_stored"] is False
    assert [p["pass"] for p in trace["passes"]] == ["landing", "verification"]
    assert [p["screenshot_ref"] for p in trace["passes"]] == [
        "landing.png", "verification.png",
    ]
    assert trace["capture_policy"]["video_requires_sequential_reproduction"] is True
    assert "do-not-persist" not in json.dumps(trace)

    manifest = json.loads((pdir / "evidence_manifest.json").read_text(encoding="utf-8"))
    assert manifest["temporary_recordings_present"] is False
    by_ref = {e["ref"]: e for e in manifest["entries"]}
    for ref in ("landing.png", "verification.png", "observation.json", "browser_trace.json"):
        path = pdir / ref
        assert by_ref[ref]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert "/" not in by_ref[ref]["ref"] and "\\" not in by_ref[ref]["ref"]


def test_dashboard_and_observer_link_the_same_promoted_evidence(tmp_path):
    store, pid = _run(tmp_path)
    detail = CampaignService(str(tmp_path)).target_detail(
        "ex.com", run=store.root.name)
    names = {e["name"] for e in detail["evidence_files"]}
    assert {"evidence.json", "browser_trace.json", "evidence_manifest.json"} <= names
    assert {Path(m).name for m in detail["media"]} >= {"landing.png", "verification.png"}

    service = ScoutService(str(tmp_path))
    service.attach(store.root.name)
    server, url = start_dashboard(service, operator_home=True)
    try:
        with urllib.request.urlopen(
            f"{url}/scout/target?run={store.root.name}&domain=ex.com", timeout=5
        ) as response:
            html = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
    assert "Browser trace (redacted)" in html
    assert "Evidence manifest + integrity hashes" in html
    assert "Structured evidence files (diagnostic)" in html
    assert "Raw evidence files" not in html
    assert "landing.png" in html and "verification.png" in html

    campaign = RunStore(str(tmp_path), "campaign-evidence")
    campaign.write_config({"campaign_name": "campaign-evidence"})
    campaign.save_state({
        "status": "COMPLETED",
        "candidates": [{"promoted_scout_run": store.root.name}],
    })
    temp_recording = store.prospect_dir(pid) / "_vidtmp"
    temp_recording.mkdir()
    (temp_recording / "unqualified-page-load.webm").write_bytes(b"not-durable")
    result = ObserverAPI(str(tmp_path)).get_evidence_manifest("campaign-evidence")
    refs = {e["ref"] for e in result["evidence"]}
    assert any(ref.endswith("/browser_trace.json") for ref in refs)
    assert any(ref.endswith("/landing.png") for ref in refs)
    assert all(not Path(ref).is_absolute() for ref in refs)
    assert all("_vidtmp" not in ref and "_reprotmp" not in ref for ref in refs)
    assert all(len(e["sha256"]) == 64 for e in result["evidence"])
    assert any(
        e["ref"].endswith("/landing.png") and e["hash_source"] == "evidence_manifest"
        for e in result["evidence"]
    )


def test_evidence_finalization_failure_is_visible_but_bounded(tmp_path, monkeypatch):
    backend = _EvidenceBackend()
    cfg = ScoutRunConfig(
        campaign_name="bounded-evidence",
        seeds=["https://ex.com/path"],
        browser_mode="playwright",
        output_dir=str(tmp_path),
        max_pages_per_site=1,
        resolve_dns=False,
    )
    store = RunStore(str(tmp_path), "run-finalization-failure")
    engine = ScoutEngine(cfg, store, backend=backend)

    def _fail_manifest(_pid):
        raise OSError("https://secret.example/path?token=must-not-persist")

    monkeypatch.setattr(engine, "_write_evidence_manifest", _fail_manifest)
    state = engine.run()

    assert state["status"] == "COMPLETED"
    events = (store.root / "events.jsonl").read_text(encoding="utf-8")
    assert '"event": "evidence_finalization_failed"' in events
    assert "must-not-persist" not in events and "secret.example" not in events


def test_observer_rejects_symlinked_or_out_of_evidence_paths(tmp_path, monkeypatch):
    store, pid = _run(tmp_path)
    campaign = RunStore(str(tmp_path), "campaign-evidence-confinement")
    campaign.save_state({
        "status": "COMPLETED",
        "candidates": [{"promoted_scout_run": store.root.name}],
    })
    pdir = store.prospect_dir(pid)
    pretend_link = pdir / "pretend-link.json"
    pretend_link.write_text('{"secret": true}', encoding="utf-8")

    original_is_symlink = Path.is_symlink

    def _is_symlink(path):
        return path == pretend_link or original_is_symlink(path)

    monkeypatch.setattr(Path, "is_symlink", _is_symlink)
    observer = ObserverAPI(str(tmp_path))
    manifest = observer.get_evidence_manifest("campaign-evidence-confinement")
    assert all(not e["ref"].endswith("/pretend-link.json") for e in manifest["evidence"])

    with pytest.raises(ObserverError, match="symlink"):
        observer.get_evidence_item(
            f"scout/{store.root.name}/prospects/{pid}/pretend-link.json"
        )
    outside = tmp_path / "operator-private.json"
    outside.write_text('{"private": true}', encoding="utf-8")
    with pytest.raises(ObserverError, match="evidence root"):
        observer.get_evidence_item("operator-private.json")
