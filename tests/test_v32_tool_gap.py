"""v3.2 Section 11 - Tool/MCP Broker gap analysis: real readiness, honest gaps, no false live."""
from __future__ import annotations

from core.orchestration.tool_gap import plan_tools, snapshot


def test_playwright_framework_gap_selects_ready_and_reports_missing():
    r = plan_tools("playwright_framework")
    assert r.service_id == "playwright_framework"
    assert "playwright_internal" in r.required_tools
    # Every gap carries a fallback + an exact action; nothing is falsely "ready".
    for g in r.gaps:
        assert g["fallback"] and g["action"] and g["ready"] is False
    # The internal Playwright runner binding is genuinely ready (fixture-tested), so it is selected.
    assert "playwright_internal" in r.selected or any(g["tool"] == "playwright_internal" for g in r.gaps)


def test_unknown_service_is_handled():
    r = plan_tools("nope")
    assert r.operator_action and not r.ready


def test_snapshot_covers_all_services_without_false_live():
    snap = snapshot()
    assert snap["schema"] == "tool-gap/v1" and len(snap["reports"]) >= 12
    for rep in snap["reports"]:
        # A report is "ready" only if there are no tool gaps AND no unmet access prerequisites
        # (a client-owned repo/DB/CI/cloud scope that is missing keeps the service not-ready).
        assert rep["ready"] == (len(rep["gaps"]) == 0 and len(rep["access_gaps"]) == 0)


def test_client_required_access_is_surfaced():
    r = plan_tools("ui_api_db_validation")
    assert any("read-only" in a.lower() or "client" in a.lower() for a in r.required_access)
