"""Role-scoped MCP tool catalog (Issue #74, A3.5 control-plane hardening).

The `qa-factory` MCP server published ONE catalog — `ALL_TOOL_SCHEMAS` = the read-only Observer tools
PLUS the seven planning tools — on **both** stdio and authenticated HTTP. The transport documented and
operated as a read-only Observer therefore exposed `apply_self_healing_fixes`, whose
`approve_code_modification` and `outputs_root` are caller-supplied and which writes into spec files
when `dry_run=false`.

These tests pin the least-privilege contract, reusing the role-scoped catalog pattern the review-relay
server already implements (one server, one logical implementation, a role-filtered catalog):

- the default role is the RESTRICTED one, so an existing launcher that sets no role becomes safe
  without being reconfigured;
- the observer catalog contains only genuinely non-mutating tools;
- a tool outside the active role's catalog is refused at dispatch, on every transport;
- active diagnostics (`deep=true` launches Chromium + network) are an operator capability, and are
  REFUSED rather than silently downgraded — a silent downgrade would let the caller believe a deep
  probe ran.
"""
from __future__ import annotations

import json

import pytest

from integrations.mcp import server as mcp_server

# Tools that mutate state, write files, or launch active probes. None may appear in the observer role.
MUTATING_TOOLS = {
    "analyze_project",
    "run_quality_audit",
    "run_flaky_test_analysis",
    "generate_delivery_pack",
    "propose_self_healing_fixes",
    "apply_self_healing_fixes",
    "observer_export_ai_review_bundle",   # mkdir + write_text under <output_root>/scout/_bundles
}


def test_default_role_is_the_restricted_one(monkeypatch):
    """Fail closed: a launcher that sets no role — including the live tunnel — gets the observer
    catalog, so the fix takes effect without reconfiguring the running tunnel."""
    monkeypatch.delenv("AIQA_MCP_ROLE", raising=False)
    assert mcp_server.server_role() == "observer"


def test_an_unknown_role_value_falls_back_to_observer(monkeypatch):
    monkeypatch.setenv("AIQA_MCP_ROLE", "superuser")
    assert mcp_server.server_role() == "observer"


def test_observer_catalog_exposes_no_mutating_tool():
    exposed = set(mcp_server.tool_names("observer"))
    leaked = sorted(exposed & MUTATING_TOOLS)
    assert leaked == [], f"mutating tools exposed on the read-only Observer role: {leaked}"


def test_observer_catalog_still_exposes_the_read_only_surface():
    exposed = set(mcp_server.tool_names("observer"))
    # The external controller legitimately reads health and campaign state over this transport.
    assert "qa_factory_health" in exposed
    assert "observer_get_project_overview" in exposed
    assert "observer_list_campaigns" in exposed
    assert "observer_get_evidence_manifest" in exposed


def test_operator_catalog_is_unchanged_and_complete():
    """NEGATIVE control: least privilege must not remove capability from the operator role."""
    exposed = set(mcp_server.tool_names("operator"))
    for name in MUTATING_TOOLS:
        assert name in exposed, f"operator role lost {name}"
    assert "qa_factory_health" in exposed


def test_a_tool_outside_the_active_role_is_refused_at_dispatch(monkeypatch):
    monkeypatch.setenv("AIQA_MCP_ROLE", "observer")
    out = json.loads(mcp_server._call_handler("apply_self_healing_fixes", {
        "project_id": "p", "approve_code_modification": True, "dry_run": False}))
    assert out["status"] == "blocked"
    assert "role" in out.get("reason", "").lower()


def test_the_same_tool_is_reachable_under_the_operator_role(monkeypatch):
    """Discriminating: the refusal above must come from the ROLE, not from the tool being broken."""
    monkeypatch.setenv("AIQA_MCP_ROLE", "operator")
    out = json.loads(mcp_server._call_handler("apply_self_healing_fixes", {}))
    # Reaches the handler, which then applies its own guard — a different refusal than the role gate.
    assert "role" not in out.get("reason", "").lower()


def test_deep_readiness_is_refused_for_the_observer_role(monkeypatch):
    """`deep=true` launches Chromium + network probes. It must not masquerade as passive read-only,
    and must be REFUSED rather than silently downgraded to a shallow probe."""
    monkeypatch.setenv("AIQA_MCP_ROLE", "observer")
    out = json.loads(mcp_server._call_handler("observer_get_system_readiness", {"deep": True}))
    assert out["status"] == "blocked"
    assert "deep" in out.get("reason", "").lower()


def test_shallow_readiness_remains_available_to_the_observer_role(monkeypatch):
    monkeypatch.setenv("AIQA_MCP_ROLE", "observer")
    out = json.loads(mcp_server._call_handler("observer_get_system_readiness", {"deep": False}))
    assert out.get("status") != "blocked"


def test_health_advertises_only_the_active_role_catalog(monkeypatch):
    """`qa_factory_health.available_modules` previously listed all seven planning tools regardless of
    exposure, advertising write tools to a read-only caller."""
    monkeypatch.setenv("AIQA_MCP_ROLE", "observer")
    out = json.loads(mcp_server._call_handler("qa_factory_health", {}))
    assert "apply_self_healing_fixes" not in out.get("available_modules", [])


@pytest.mark.parametrize("role", ["observer", "operator"])
def test_every_exposed_tool_has_a_handler(role):
    """A catalog entry with no handler would be a dead advertised capability."""
    known = set(mcp_server.OBSERVER_HANDLERS) | set(mcp_server.HANDLERS)
    missing = sorted(set(mcp_server.tool_names(role)) - known)
    assert missing == [], f"exposed with no handler: {missing}"


# --- review follow-up: least privilege must be an ALLOWLIST, not a denylist -------------------------
def test_an_unknown_tool_defaults_to_operator_only(monkeypatch):
    """A denylist silently exposes anything added later. A new Observer tool - a future write or
    active probe - must NOT reach the read-only role just because nobody remembered to deny it."""
    added = {"name": "observer_future_mutating_tool", "description": "x", "inputSchema": {}}
    monkeypatch.setattr(mcp_server, "ALL_TOOL_SCHEMAS",
                        list(mcp_server.ALL_TOOL_SCHEMAS) + [added])
    assert "observer_future_mutating_tool" not in mcp_server.tool_names("observer")
    assert "observer_future_mutating_tool" in mcp_server.tool_names("operator")


def test_every_currently_exposed_read_only_tool_is_explicitly_classified():
    """The allowlist must cover the real catalog, or a genuine read tool silently disappears."""
    observer = set(mcp_server.tool_names("observer"))
    assert len([n for n in observer if n.startswith("observer_")]) == 19
    assert observer <= set(mcp_server.READ_ONLY_TOOLS)
