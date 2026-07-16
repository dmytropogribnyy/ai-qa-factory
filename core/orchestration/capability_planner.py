"""CapabilityPlanner — Phase 8.1 (deterministic, planning-only).

Maps a capability profile to a CapabilityPlan. A manifest MCP server is only ever a
CANDIDATE requiring Phase 8.3 discovery — never marked available merely because it
appears in YAML. No MCP calls, no discovery.
"""
from __future__ import annotations

from core.schemas.capability_plan import CapabilityPlan, PlannedCapability
from core.orchestration.capability_registry import CapabilityRegistry

_MCP_BACKENDS = {"playwright_mcp", "chrome_devtools_mcp"}
_APPROVAL_CLASSES = {"write", "financial", "external_communication", "destructive"}


class CapabilityPlanner:
    """Deterministic capability planning for a profile."""

    def __init__(self, registry: CapabilityRegistry) -> None:
        self._reg = registry

    def plan(self, project_id: str, work_packet_ref: str, profile_name: str) -> CapabilityPlan:
        profile = self._reg.profile(profile_name)
        required = list(profile.capabilities) if profile else []

        planned: list[PlannedCapability] = []
        missing: list[str] = []
        blocked: list[str] = []
        approvals: list[str] = []

        for cap in required:
            spec = self._reg.atomic(cap)
            if spec is None:
                missing.append(cap)
                planned.append(PlannedCapability(
                    capability=cap, availability="missing",
                    reason="capability not in atomic registry",
                ))
                continue

            cls = spec.capability_class
            backends = spec.candidate_backends
            servers = spec.candidate_mcp_servers
            requires_approval = spec.default_requires_approval or cls in _APPROVAL_CLASSES
            requires_discovery = False
            candidate_backend = ""
            candidate_server = servers[0] if servers else ""

            if cls == "destructive":
                availability = "blocked"
                blocked.append(cap)
            elif backends and backends[0] in _MCP_BACKENDS:
                availability = "requires_discovery"
                requires_discovery = True
                candidate_backend = backends[0]
            elif "existing_runner" in backends:
                availability = "available"
                candidate_backend = "existing_runner"
            elif "playwright_cli" in backends:
                availability = "available"
                candidate_backend = "playwright_cli"
            elif servers:
                availability = "candidate"
                requires_discovery = True
            else:
                availability = "missing"
                missing.append(cap)

            if requires_approval and availability not in ("missing",):
                approvals.append(f"{cap} ({cls})")

            planned.append(PlannedCapability(
                capability=cap,
                availability=availability,
                capability_class=cls,
                candidate_backend=candidate_backend,
                candidate_mcp_server=candidate_server,
                requires_approval=requires_approval,
                requires_discovery=requires_discovery,
                reason="planning-only; no discovery performed" if requires_discovery else "",
            ))

        return CapabilityPlan(
            project_id=project_id,
            work_packet_ref=work_packet_ref,
            profile=profile_name,
            required_capabilities=required,
            planned=planned,
            missing_capabilities=missing,
            blocked_capabilities=blocked,
            approvals_required=approvals,
            notes=["Phase 8.1 planning-only: MCP servers are candidates pending Phase 8.3 discovery"],
        )
