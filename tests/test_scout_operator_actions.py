"""Operator UX + evidence freshness contracts.

Archive is reversible, destructive cleanup is explicit/path-confined, queued skips are persisted
without racing state.json, and a manual browser session genuinely waits for Continue before the
same backend proceeds.
"""
from __future__ import annotations

import json
import time
import urllib.request
from pathlib import Path

import pytest

from core.scout.backends import PageObservation
from core.scout.campaign_service import CampaignService
from core.scout.challenge_session import ChallengeSessionManager
from core.scout.dashboard import start_dashboard
from core.scout.discovery.analyzed_registry import AnalyzedSiteRegistry
from core.scout.operator_state import OperatorStateStore
from core.scout.service import ScoutService
from core.scout.store import RunStore, StoreError


def _terminal_run(tmp_path, run_id="run-a"):
    store = RunStore(str(tmp_path), run_id)
    store.save_state({"status": "COMPLETED", "prospects": {
        "01-alpha": {"status": "DONE", "url": "https://alpha.example/",
                     "verified_findings": 1, "verified_defects": 1},
        "02-beta": {"status": "PENDING", "url": "https://beta.example/"},
    }})
    store.save_prospect_artifact("01-alpha", "findings.json",
                                 {"verified": [{"severity": "high", "title": "broken"}]})
    store.save_prospect_artifact("01-alpha", "browser_trace.json", {"events": []})
    (store.prospect_dir("01-alpha") / "landing.png").write_bytes(b"png")
    (store.prospect_dir("01-alpha") / "reproduction.webm").write_bytes(b"video")
    return store


def test_archive_is_reversible_and_hidden_from_default_history(tmp_path):
    reg = AnalyzedSiteRegistry(str(tmp_path))
    reg.record_analysis("alpha.example", campaign_id="run-a")
    ops = OperatorStateStore(str(tmp_path))
    assert len(CampaignService(str(tmp_path)).history()) == 1
    ops.archive_targets(["alpha.example"])
    assert CampaignService(str(tmp_path)).history() == []
    archived = CampaignService(str(tmp_path)).history(filters={"archived": "only"})
    assert [r["domain"] for r in archived] == ["alpha.example"]
    ops.restore_targets(["alpha.example"])
    assert len(CampaignService(str(tmp_path)).history()) == 1


def test_archived_run_moves_from_current_to_archived_campaign_view(tmp_path):
    run_id = "campaign-alpha-20260724t000000z-abcdef"
    control = tmp_path / "scout" / "_runcontrol"
    control.mkdir(parents=True)
    (control / f"{run_id}.json").write_text(
        json.dumps({"campaign_id": run_id}), encoding="utf-8")
    store = RunStore(str(tmp_path), run_id)
    store.save_state({"status": "COMPLETED", "campaign_id": run_id, "prospects": {}})
    OperatorStateStore(str(tmp_path)).archive_run(run_id)

    service = ScoutService(str(tmp_path))
    service.attach(run_id)
    server, url = start_dashboard(service, operator_home=True)
    try:
        with urllib.request.urlopen(f"{url}/scout/campaigns", timeout=5) as response:
            current = response.read().decode("utf-8")
        with urllib.request.urlopen(
            f"{url}/scout/campaigns?archived=1", timeout=5
        ) as response:
            archived = response.read().decode("utf-8")
    finally:
        server.shutdown()
        server.server_close()
    assert f"/scout/progress?id={run_id}" not in current
    assert f"/scout/progress?id={run_id}" in archived
    assert "Archived (1)" in archived and "Current (0)" in archived


def test_skip_queued_persists_a_run_scoped_request_and_refuses_completed(tmp_path):
    _terminal_run(tmp_path)
    result = OperatorStateStore(str(tmp_path)).request_skip(
        "run-a", ["01-alpha", "02-beta"])
    assert result["requested"] == ["02-beta"]
    assert result["refused"] == [{"prospect_id": "01-alpha", "status": "DONE"}]
    actions = RunStore(str(tmp_path), "run-a").load_artifact("operator_actions.json")
    assert actions["skip_prospects"] == ["02-beta"]


def test_delete_heavy_evidence_preserves_summary_and_requires_confirmation(tmp_path):
    store = _terminal_run(tmp_path)
    ops = OperatorStateStore(str(tmp_path))
    export = CampaignService(str(tmp_path)).export_client_evidence(
        "alpha.example", run="run-a")
    export_path = Path(export["path"])
    assert export_path.exists()
    with pytest.raises(StoreError, match="confirmation"):
        ops.delete_heavy_evidence("run-a", ["01-alpha"], confirm=False)
    result = ops.delete_heavy_evidence("run-a", ["01-alpha"], confirm=True)
    assert sorted(x.rsplit("/", 1)[-1] for x in result["removed"]) == [
        "browser_trace.json", "landing.png", "reproduction.webm"]
    assert store.load_prospect_artifact("01-alpha", "findings.json")["verified"]
    assert store.load_prospect_artifact("01-alpha", "evidence_cleanup.json")["summary_preserved"]
    assert not export_path.exists()


def test_delete_run_refuses_active_and_preserves_registry_history(tmp_path):
    _terminal_run(tmp_path)
    AnalyzedSiteRegistry(str(tmp_path)).record_analysis("alpha.example", campaign_id="run-a")
    ops = OperatorStateStore(str(tmp_path))
    with pytest.raises(StoreError, match="active run"):
        ops.delete_run("run-a", confirm=True, active_run_id="run-a", active=True)
    assert ops.delete_run("run-a", confirm=True)["deleted"] is True
    assert not RunStore(str(tmp_path), "run-a").exists()
    assert AnalyzedSiteRegistry(str(tmp_path)).get("alpha.example") is not None


class _WaitingBackend:
    name = "playwright"
    screenshot_dir = None
    screenshot_filename = "landing.png"

    def __init__(self, *, manual_gate, **_kwargs):
        self.manual_gate = manual_gate
        self.cleared = False

    def observe(self, url, _timeout_s, _max_bytes, *, record_video=False, deep_qa=False):
        if not self.cleared:
            blocked = PageObservation(url=url, final_url=url, status=403, ok=False,
                                      backend="playwright", captcha_marker=True,
                                      headings=[{"level": 1, "text": "Verify"}])
            action = self.manual_gate(None, blocked)
            if action != "continue":
                return blocked
            self.cleared = True
        return PageObservation(url=url, final_url=url, status=200, ok=True,
                               backend="playwright", title="Ready",
                               meta_description="Ready", has_viewport_meta=True,
                               headings=[{"level": 1, "text": "Ready"}],
                               landmarks={"main": 1}, axe_status="ok")


def _wait_state(manager, sid, wanted, timeout=3):
    end = time.time() + timeout
    while time.time() < end:
        item = manager.get(sid)
        if item and item["state"] in wanted:
            return item
        time.sleep(0.02)
    return manager.get(sid)


def test_manual_challenge_session_waits_then_completes_same_attempt(tmp_path):
    manager = ChallengeSessionManager(
        str(tmp_path), wait_timeout_s=2,
        backend_factory=lambda **kw: _WaitingBackend(**kw), resolve_dns=False)
    item = manager.start("blocked.example", source_run="old-run")
    waiting = _wait_state(manager, item["id"], {"waiting"})
    assert waiting["state"] == "waiting"
    assert RunStore(str(tmp_path), item["result_run"]).exists()
    manager.signal(item["id"], "continue")
    done = _wait_state(manager, item["id"], {"completed", "failed"})
    assert done["state"] == "completed"
    detail = CampaignService(str(tmp_path)).target_detail(
        "blocked.example", run=item["result_run"])
    assert detail["analysis_complete"] is True


def test_manual_challenge_failure_persists_no_raw_exception_details(tmp_path):
    def broken_backend(**_kwargs):
        raise RuntimeError("Bearer abcdefghijklmnopqrstuvwxyz /private/operator/path")

    manager = ChallengeSessionManager(
        str(tmp_path), wait_timeout_s=1, backend_factory=broken_backend,
        resolve_dns=False)
    item = manager.start("blocked.example")
    failed = _wait_state(manager, item["id"], {"failed"})
    assert failed["state"] == "failed"
    assert "Bearer" not in failed["message"] and "/private/" not in failed["message"]
    persisted = (
        tmp_path / "scout" / "_operator" / "challenge_sessions.json"
    ).read_text(encoding="utf-8")
    assert "abcdefghijklmnopqrstuvwxyz" not in persisted and "/private/" not in persisted


def test_incomplete_page_has_manual_actions_and_hides_outreach(tmp_path):
    store = RunStore(str(tmp_path), "blocked-run")
    store.save_state({"status": "COMPLETED", "prospects": {
        "01-blocked": {"status": "MANUAL_ACTION_REQUIRED",
                       "url": "https://blocked.example/", "reason": "captcha_detected"}}})
    store.save_prospect_artifact("01-blocked", "observation.json",
                                 {"status": 403, "final_url": "https://blocked.example/"})
    service = ScoutService(str(tmp_path))
    service.attach("blocked-run")
    server, url = start_dashboard(service, operator_home=True)
    try:
        with urllib.request.urlopen(
            f"{url}/scout/target?run=blocked-run&domain=blocked.example", timeout=5
        ) as response:
            html = response.read().decode("utf-8")
    finally:
        server.shutdown()
    assert "Open manual check" in html and "Continue check" in html
    assert "Defer" in html and "Skip target" in html
    assert "Outreach draft" not in html and "Start client work" not in html
    assert "Advanced diagnostics" in html


def test_operator_state_file_contains_no_evidence_content(tmp_path):
    _terminal_run(tmp_path)
    OperatorStateStore(str(tmp_path)).archive_targets(["alpha.example"])
    data = json.loads(
        (tmp_path / "scout" / "_operator" / "state.json").read_text(encoding="utf-8"))
    blob = json.dumps(data)
    assert "cookie" not in blob.lower() and "authorization" not in blob.lower()
