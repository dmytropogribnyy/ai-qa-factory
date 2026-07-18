"""Phase 8.0 — ARK foundation schema tests.

Covers:
- to_dict / from_dict round-trips for all new schemas
- safety invariants (verification/approval cannot be rehydrated as done)
- untrusted-output invariant is forced True
- WorkRunState canonical state machine integrity
- constant vocabularies
"""
from __future__ import annotations

from core.schemas.requirement import Requirement, REQUIREMENT_TYPES, VERIFICATION_STATUSES
from core.schemas.work_packet import WorkPacket
from core.schemas.capability import (
    Capability, CapabilityProfile, ATOMIC_CAPABILITIES, CAPABILITY_PROFILES,
    CAPABILITY_CLASSES,
)
from core.schemas.capability_plan import CapabilityPlan, PlannedCapability
from core.schemas.mcp_descriptor import (
    MCPServerDescriptor, MCPToolDescriptor, MCP_AVAILABILITY_SCOPES,
    MCP_TRANSPORTS, VERSION_POLICIES,
)
from core.schemas.toolchain_plan import (
    ToolchainPlan, SelectedMCPTool, ToolExecutionPolicy, ExecutionBudget, BACKENDS,
)
from core.schemas.work_run_state import (
    WorkRunState, StateTransition, WORK_RUN_STATES, TERMINAL_STATES, ALLOWED_TRANSITIONS,
)
from core.schemas.work_delivery import WorkDeliveryManifest
from core.schemas.evidence import EvidenceClaim, EVIDENCE_CLAIM_STATUSES
from core.schemas.capability_gap import (
    CapabilityGap, CapabilityGapReport, MCPRecommendation, GAP_KINDS, RECOMMENDATION_ACTIONS,
)


# ---------------------------------------------------------------------------
# Round-trips
# ---------------------------------------------------------------------------

class TestRoundTrips:
    def test_requirement(self):
        r = Requirement(text="login works", requirement_type="functional",
                        acceptance_criteria=["200 on POST /login"])
        assert Requirement.from_dict(r.to_dict()).text == "login works"

    def test_work_packet_nested_requirements(self):
        wp = WorkPacket(project_id="p1", requirements=[Requirement(text="r1")])
        back = WorkPacket.from_dict(wp.to_dict())
        assert back.requirements[0].text == "r1"

    def test_capability_and_profile(self):
        c = Capability(name="web_navigation", capability_class="read")
        assert Capability.from_dict(c.to_dict()).name == "web_navigation"
        p = CapabilityProfile(name="web_app_audit", capabilities=["web_navigation"])
        assert CapabilityProfile.from_dict(p.to_dict()).capabilities == ["web_navigation"]

    def test_capability_plan_nested(self):
        cp = CapabilityPlan(profile="web_app_audit",
                            planned=[PlannedCapability(capability="dom_inspection")])
        assert CapabilityPlan.from_dict(cp.to_dict()).planned[0].capability == "dom_inspection"

    def test_mcp_descriptors(self):
        s = MCPServerDescriptor(name="playwright", transport="stdio",
                                availability_scopes=["available_to_factory_process"])
        assert MCPServerDescriptor.from_dict(s.to_dict()).name == "playwright"
        t = MCPToolDescriptor(server_name="playwright", tool_name="navigate")
        assert MCPToolDescriptor.from_dict(t.to_dict()).tool_name == "navigate"

    def test_toolchain_plan_nested(self):
        tc = ToolchainPlan(steps=[SelectedMCPTool(tool_name="navigate", backend="playwright_mcp")],
                           budget=ExecutionBudget(max_tool_calls=10))
        back = ToolchainPlan.from_dict(tc.to_dict())
        assert back.steps[0].backend == "playwright_mcp"
        assert back.budget.max_tool_calls == 10

    def test_work_run_state_history(self):
        w = WorkRunState(project_id="p1", status="PLANNED",
                         history=[StateTransition(from_state="RECEIVED", to_state="PLANNED")])
        back = WorkRunState.from_dict(w.to_dict())
        assert back.history[0].to_state == "PLANNED"

    def test_capability_gap_report_nested(self):
        rep = CapabilityGapReport(
            required_capabilities=["database_read"],
            gaps=[CapabilityGap(capability="database_read", kind="requires_auth_setup",
                                recommendations=[MCPRecommendation(capability="database_read",
                                                                   action="authenticate",
                                                                   candidate_server="supabase")])],
        )
        back = CapabilityGapReport.from_dict(rep.to_dict())
        assert back.gaps[0].recommendations[0].candidate_server == "supabase"


# ---------------------------------------------------------------------------
# Safety invariants
# ---------------------------------------------------------------------------

class TestSafetyInvariants:
    def test_requirement_cannot_rehydrate_satisfied(self):
        r = Requirement(text="x", verification_status="satisfied")
        assert Requirement.from_dict(r.to_dict()).verification_status == "unverified"

    def test_evidence_claim_cannot_rehydrate_verified(self):
        c = EvidenceClaim(claim_text="x", verification_status="verified")
        assert EvidenceClaim.from_dict(c.to_dict()).verification_status == "unverified"

    def test_delivery_cannot_rehydrate_approved(self):
        d = WorkDeliveryManifest(approved_for_delivery=True)
        assert WorkDeliveryManifest.from_dict(d.to_dict()).approved_for_delivery is False

    def test_untrusted_output_forced_true(self):
        p = ToolExecutionPolicy(untrusted_output=False)
        assert ToolExecutionPolicy.from_dict(p.to_dict()).untrusted_output is True

    def test_toolchain_step_policy_untrusted(self):
        tc = ToolchainPlan(steps=[SelectedMCPTool(policy=ToolExecutionPolicy(untrusted_output=False))])
        back = ToolchainPlan.from_dict(tc.to_dict())
        assert back.steps[0].policy.untrusted_output is True

    def test_mcp_server_defaults_disabled(self):
        assert MCPServerDescriptor().enabled is False
        assert MCPServerDescriptor().trust_level == "untrusted"

    def test_mcp_tool_defaults_gated(self):
        t = MCPToolDescriptor()
        assert t.requires_approval is True
        assert t.read_only is True
        assert t.enabled is False


# ---------------------------------------------------------------------------
# State machine integrity
# ---------------------------------------------------------------------------

class TestWorkRunStateMachine:
    def test_seventeen_states(self):
        # v3.0.2 added DELIVERY_PREPARED (the durable delivery-preparation boundary).
        assert len(WORK_RUN_STATES) == 17
        assert len(set(WORK_RUN_STATES)) == 17
        assert "DELIVERY_PREPARED" in WORK_RUN_STATES

    def test_completed_only_reachable_through_delivery_prepared(self):
        sources = [src for src, targets in ALLOWED_TRANSITIONS.items() if "COMPLETED" in targets]
        assert sources == ["DELIVERY_PREPARED"]

    def test_terminal_states(self):
        assert TERMINAL_STATES == frozenset({"COMPLETED", "FAILED", "CANCELLED"})
        for t in TERMINAL_STATES:
            assert ALLOWED_TRANSITIONS[t] == ()

    def test_transitions_reference_known_states(self):
        assert set(ALLOWED_TRANSITIONS) == set(WORK_RUN_STATES)
        for src, targets in ALLOWED_TRANSITIONS.items():
            for tgt in targets:
                assert tgt in WORK_RUN_STATES, f"{src}->{tgt} not a known state"

    def test_is_terminal_property(self):
        assert WorkRunState(status="COMPLETED").is_terminal is True
        assert WorkRunState(status="EXECUTING").is_terminal is False


class TestWorkRunIdempotency:
    def test_round_trip_preserves_idempotency_and_version(self):
        w = WorkRunState(project_id="p1", run_idempotency_key="run-abc", state_version=3,
                         history=[StateTransition(from_state="RECEIVED", to_state="PLANNED")])
        back = WorkRunState.from_dict(w.to_dict())
        assert back.run_idempotency_key == "run-abc"
        assert back.state_version == 3
        assert back.history[0].to_state == "PLANNED"  # history still rehydrates

    def test_default_state_version_zero(self):
        assert WorkRunState().state_version == 0

    def test_distinct_runs_have_distinct_keys(self):
        assert WorkRunState().run_idempotency_key != WorkRunState().run_idempotency_key

    def test_no_approval_or_verification_granted_via_deserialization(self):
        # A rehydrated run cannot carry approval/verification implicitly; those live on
        # WorkDeliveryManifest / EvidenceClaim, which reset on load (asserted elsewhere).
        w = WorkRunState(status="READY_FOR_DELIVERY", state_version=5)
        back = WorkRunState.from_dict(w.to_dict())
        assert back.is_terminal is False  # READY_FOR_DELIVERY is not COMPLETED
        assert back.status == "READY_FOR_DELIVERY"


# ---------------------------------------------------------------------------
# Constant vocabularies
# ---------------------------------------------------------------------------

class TestConstants:
    def test_frozensets(self):
        for c in (REQUIREMENT_TYPES, VERIFICATION_STATUSES, ATOMIC_CAPABILITIES,
                  CAPABILITY_PROFILES, CAPABILITY_CLASSES, MCP_AVAILABILITY_SCOPES,
                  MCP_TRANSPORTS, VERSION_POLICIES, BACKENDS, EVIDENCE_CLAIM_STATUSES,
                  GAP_KINDS, RECOMMENDATION_ACTIONS):
            assert isinstance(c, frozenset)

    def test_atomic_capability_count(self):
        assert len(ATOMIC_CAPABILITIES) == 17

    def test_profiles(self):
        assert CAPABILITY_PROFILES == frozenset({
            "research_only", "code_project", "web_app_audit", "api_project",
            "data_project", "automation_project", "mvp_launch_audit", "technical_writing",
            "prospect_qa_radar",
        })

    def test_backends(self):
        assert BACKENDS == frozenset({
            "existing_runner", "playwright_cli", "playwright_mcp", "chrome_devtools_mcp",
        })

    def test_availability_scopes(self):
        for s in ("available_to_claude_agent", "available_to_factory_process",
                  "requires_factory_auth_setup", "configured_but_unreachable",
                  "known_candidate_not_configured"):
            assert s in MCP_AVAILABILITY_SCOPES
