"""Operator-first Dashboard information architecture and progressive-disclosure regressions."""
from __future__ import annotations

import http.client
import json
import urllib.request
from pathlib import Path

from core.scout.dashboard import _collab_body, start_dashboard
from core.scout.service import ScoutService
from core.scout.store import RunStore


def _get(url: str) -> str:
    with urllib.request.urlopen(url, timeout=5) as response:
        return response.read().decode("utf-8")


def _seed_work(root: Path, project_id: str, *, status: str) -> None:
    ark = root / project_id / "40_ark_work"
    ark.mkdir(parents=True)
    (ark / "WORK_PACKET.json").write_text(
        json.dumps({"title": f"Client project {project_id}", "created_at": "2026-07-24T10:00:00Z"}),
        encoding="utf-8",
    )
    (ark / "WORK_RUN_STATE.json").write_text(
        json.dumps({"status": status, "updated_at": "2026-07-24T10:05:00Z"}),
        encoding="utf-8",
    )


def _register_campaign(root: Path, campaign_id: str, name: str) -> None:
    control = root / "scout" / "_runcontrol"
    control.mkdir(parents=True, exist_ok=True)
    (control / f"{campaign_id}.json").write_text(
        json.dumps({"campaign_id": campaign_id, "state": "completed"}),
        encoding="utf-8",
    )
    store = RunStore(str(root), campaign_id)
    store.write_config({"campaign_name": name})
    store.save_state({
        "campaign_id": campaign_id,
        "status": "COMPLETED",
        "started_at": "2026-07-24T10:00:00Z",
    })


def test_operator_root_stays_overview_when_a_run_is_attached(tmp_path):
    store = RunStore(str(tmp_path), "run-attached")
    store.save_state({"run_id": "run-attached", "status": "RUNNING", "prospects": {}})
    service = ScoutService(str(tmp_path))
    service.attach("run-attached")
    server, url = start_dashboard(service, operator_home=True)
    try:
        html = _get(url + "/")
    finally:
        server.shutdown()
    assert "<h1>Overview</h1>" in html
    assert 'header class="top"' in html


def test_work_defaults_to_active_and_keeps_completed_in_its_own_view(tmp_path):
    _seed_work(tmp_path, "active-technical-id", status="EXECUTING")
    _seed_work(tmp_path, "completed-technical-id", status="COMPLETED")
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        default_html = _get(url + "/work")
        completed_html = _get(url + "/work?view=completed")
    finally:
        server.shutdown()
    assert "Client project active-technical-id" in default_html
    assert "Client project completed-technical-id" not in default_html
    assert "Client project completed-technical-id" in completed_html
    assert '<div class="muted">active-technical-id</div>' not in default_html


def test_navigation_and_help_are_operator_facing(tmp_path):
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        settings = _get(url + "/settings")
        help_page = _get(url + "/docs")
        tools = _get(url + "/tools")
    finally:
        server.shutdown()
    assert ">Help</a>" in settings
    assert ">Tools</a>" not in settings
    assert "Data &amp; retention" in settings
    assert "Advanced integrations &amp; system diagnostics" in settings
    assert "Use from Claude Code in VS Code" in help_page
    assert "CLAUDE.md" in help_page and "python main.py dashboard" in help_page
    assert "Advanced readiness" in tools
    assert "any_live_accepted=" not in tools


def test_legacy_projects_route_redirects_to_canonical_work(tmp_path):
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    host, port = url.removeprefix("http://").split(":")
    try:
        conn = http.client.HTTPConnection(host, int(port), timeout=5)
        conn.request("GET", "/projects")
        response = conn.getresponse()
        response.read()
        conn.close()
    finally:
        server.shutdown()
    assert response.status == 303
    assert response.getheader("Location") == "/work"


def test_scout_form_hides_diagnostic_presets_by_default(tmp_path):
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        production = _get(url + "/scout/new")
        diagnostics = _get(url + "/scout/new?diagnostics=1")
    finally:
        server.shutdown()
    assert "(diagnostic)" not in production
    assert "Show diagnostic campaign presets" in production
    assert "(diagnostic)" in diagnostics
    assert "Capture screenshots and browser evidence" in production


def test_scout_form_uses_operator_language_and_accessible_choices(tmp_path):
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        html = _get(url + "/scout/new")
    finally:
        server.shutdown()
    assert "Find public business websites worth reviewing" in html
    assert "Campaign setup" in html
    assert "comma-separated" not in html
    assert 'name="industry"' in html
    assert 'class="option-grid"' in html
    assert "Safe, read-only discovery" in html
    assert "Approve live discovery for this campaign" in html
    assert 'role="status" aria-live="polite"' in html
    assert "alert('approve the bounded live run" not in html
    assert "Playwright/Chromium" not in html
    assert "Advanced campaign controls" in html


def test_scout_advanced_controls_are_operator_friendly(tmp_path):
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        html = _get(url + "/scout/new")
    finally:
        server.shutdown()
    assert "Advanced campaign controls" in html
    assert "Targeting refinements" in html
    assert "Run limits" in html
    assert "System readiness" in html
    assert 'name="sitetype"' in html
    assert 'select id="sitetypes" multiple' not in html
    assert "Check system readiness" in html
    assert "Readiness details appear here." not in html
    assert "JSON.stringify(j.preflight" not in html
    assert 'role="status" aria-live="polite" hidden' in html


def test_activity_uses_campaign_name_not_internal_id(tmp_path):
    campaign_id = "campaign-balanced-production-20260724T100000Z-acde12"
    _register_campaign(tmp_path, campaign_id, "DACH SaaS prospects")
    RunStore(str(tmp_path), campaign_id).append_event({
        "at": "2026-07-24T10:00:00+00:00",
        "event": "campaign_started",
    })
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        production = _get(url + "/activity")
        diagnostics = _get(url + "/activity?diagnostics=1")
    finally:
        server.shutdown()
    assert "DACH SaaS prospects" in production
    assert campaign_id not in production
    assert campaign_id in diagnostics


def test_collaboration_hides_completed_and_technical_fields_by_default():
    snap = {
        "owner_action_required": False,
        "counts": {"active": 1, "needs_owner": 0, "done": 1},
        "driver": {
            "stage": "REVIEWING",
            "processed": 1,
            "heartbeat": "2026-07-24T10:00:00+00:00",
            "model": "internal-model",
            "reasoning_effort": "high",
            "budget": {"daily_calls": 1, "cap_calls": 20, "daily_tokens": 100,
                       "daily_usd": 0.1, "cap_usd": 5},
        },
        "threads": [
            {"thread_id": "active-raw-id", "state": "REVIEWING", "actor": "reviewer",
             "current_action": "reviewing", "next_action": "decision", "branch": "feat/x",
             "pr_number": 1, "head_sha": "a" * 40, "decision": "", "ci_refs": [],
             "timeline": []},
            {"thread_id": "done-raw-id", "state": "DONE", "actor": "worker",
             "current_action": "complete", "next_action": "", "branch": "feat/y",
             "pr_number": 2, "head_sha": "b" * 40, "decision": "GO", "ci_refs": [],
             "timeline": []},
        ],
    }
    current = _collab_body(snap)
    completed = _collab_body(snap, show_completed=True)
    assert "Current tasks" in current and "active-raw-id" in current
    assert "done-raw-id" not in current
    assert "Technical details" in current
    assert "Completed" in completed and "done-raw-id" in completed


def test_footer_keeps_build_sha_out_of_ordinary_pages(tmp_path):
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        html = _get(url + "/")
    finally:
        server.shutdown()
    assert "AI QA Factory" in html
    assert "&middot; build" not in html


def test_overview_uses_operator_language_and_progressive_disclosure(tmp_path):
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        html = _get(url + "/")
    finally:
        server.shutdown()
    assert "Active work</span><strong>0</strong>" in html
    assert "Projects 0" not in html
    assert "Nothing needs your attention" in html
    assert "No active client work" in html
    assert "Scout is ready" in html
    assert "Start a Scout campaign" in html
    assert "Refresh now" in html
    assert ">Refresh</button>" not in html


def test_overview_hides_diagnostics_under_advanced_options(tmp_path):
    _register_campaign(tmp_path, "smoke-campaign", "Acceptance smoke")
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        html = _get(url + "/")
    finally:
        server.shutdown()
    assert "<summary>Advanced view options</summary>" in html
    assert "Show diagnostics (1)" in html
    assert html.index("<summary>Advanced view options</summary>") < html.index("Show diagnostics (1)")


def test_theme_control_names_the_theme_it_will_switch_to(tmp_path):
    server, url = start_dashboard(ScoutService(str(tmp_path)), operator_home=True)
    try:
        html = _get(url + "/")
    finally:
        server.shutdown()
    assert 'aria-label="Switch to light theme"' in html
    assert ">Light theme</span>" in html
    assert "next.charAt(0).toUpperCase()+next.slice(1)+' theme'" in html
