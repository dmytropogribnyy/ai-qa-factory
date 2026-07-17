"""ToolchainComposer — Phase 8.1 (deterministic, no MCP invocation).

Maps a CapabilityPlan to a ToolchainPlan. Because Phase 8.1 has no live discovery, an
MCP-preferred capability produces an UNRESOLVED candidate step (empty tool_name,
availability_verified=False) — never a fabricated concrete tool. Existing in-repo
backends are marked resolvable.
"""
from __future__ import annotations

from core.schemas.capability_plan import CapabilityPlan
from core.schemas.toolchain_plan import (
    ToolchainPlan, SelectedMCPTool, ToolExecutionPolicy, ExecutionBudget,
)

# Map capability availability -> step resolution status.
_AVAIL_TO_RESOLUTION = {
    "available": "existing_backend_available",
    "requires_discovery": "mcp_discovery_required",
    "candidate": "mcp_server_candidate",
    "requires_auth_setup": "auth_setup_required",
    "blocked": "capability_blocked",
    "missing": "capability_missing",
}


class ToolchainComposer:
    """Deterministic toolchain composition without MCP invocation."""

    def compose(self, plan: CapabilityPlan) -> ToolchainPlan:
        steps: list[SelectedMCPTool] = []
        approvals: list[str] = []

        for pc in plan.planned:
            resolution = _AVAIL_TO_RESOLUTION.get(pc.availability, "capability_missing")
            is_mcp_candidate = resolution in (
                "mcp_discovery_required", "mcp_server_candidate", "auth_setup_required",
            )
            backend = pc.candidate_backend or ("existing_runner" if not is_mcp_candidate else "")
            policy = ToolExecutionPolicy(
                capability_class=pc.capability_class,
                requires_approval=pc.requires_approval,
                read_only=(pc.capability_class == "read"),
            )
            step = SelectedMCPTool(
                server_name=pc.candidate_mcp_server if is_mcp_candidate else "",
                tool_name="",  # never fabricated; concrete tool waits for Phase 8.3
                capability=pc.capability,
                capability_class=pc.capability_class,
                backend=backend,
                requires_approval=pc.requires_approval,
                resolution_status=resolution,
                selection_basis=(
                    "in-repo backend available"
                    if resolution == "existing_backend_available"
                    else "MCP candidate; requires Phase 8.3 discovery before a tool can be named"
                    if is_mcp_candidate
                    else "no backend or candidate available"
                ),
                discovery_required=is_mcp_candidate,
                availability_verified=(resolution == "existing_backend_available"),
                policy=policy,
            )
            steps.append(step)
            if pc.requires_approval and resolution != "capability_missing":
                approvals.append(f"{pc.capability} ({pc.capability_class})")

        return ToolchainPlan(
            project_id=plan.project_id,
            work_packet_ref=plan.work_packet_ref,
            profile=plan.profile,
            steps=steps,
            budget=ExecutionBudget(),  # unset in planning-only mode
            approvals_required=sorted(set(approvals)),
            notes=["Phase 8.1 planning-only: no MCP tool was invoked or named"],
        )
