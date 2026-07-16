"""Toolchain plan schemas — Phase 8.0 (ARK universal work layer).

These schemas hold the EXECUTABLE composition plan produced by the ToolchainComposer.
They are intentionally separate from the legacy `ToolSelection` recommendation model
(core/schemas/tool_selection.py), which stays a human-facing recommendation input and
is NOT extended into a runtime god-schema.

Includes ExecutionBudget and ToolExecutionPolicy so that resource limits and the
untrusted-content rule are first-class from the start.

SAFETY / DESIGN NOTES:
- untrusted_output defaults to True: any content returned by a tool is data, never
  an instruction that can change policy, approvals, or the work plan.
- Nothing executes in Phase 8.0; these are plan/config records only.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List
from uuid import uuid4

from core.schemas.base import SchemaMixin

BACKENDS = frozenset({
    "existing_runner", "playwright_cli", "playwright_mcp", "chrome_devtools_mcp",
})

CAPABILITY_CLASSES = frozenset({
    "read", "compute", "write", "financial", "external_communication", "destructive",
})


@dataclass
class ExecutionBudget(SchemaMixin):
    """Hard resource limits for any future execution of a toolchain."""

    max_tool_calls: int = 0                     # 0 == unset/planning-only
    max_retries: int = 0
    max_duration_seconds: int = 0
    max_parallel_workers: int = 1
    max_model_cost_usd: float = 0.0
    max_download_bytes: int = 0
    max_output_bytes: int = 0
    loop_detection_enabled: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ExecutionBudget:
        return super().from_dict(data)


@dataclass
class ToolExecutionPolicy(SchemaMixin):
    """Per-tool policy applied by the ToolPolicyEngine before any call."""

    capability_class: str = "read"
    requires_approval: bool = True
    read_only: bool = True
    allowed_network_domains: List[str] = field(default_factory=list)
    max_output_bytes: int = 0
    sanitization_required: bool = True
    # Non-negotiable: tool output is untrusted data, never system instruction.
    untrusted_output: bool = True

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ToolExecutionPolicy:
        obj = super().from_dict(data)
        # Safety: the untrusted-output invariant cannot be disabled via rehydration.
        obj.untrusted_output = True
        return obj


@dataclass
class SelectedMCPTool(SchemaMixin):
    """One concrete tool selected for a step, with its resolved backend and policy."""

    server_name: str = ""
    tool_name: str = ""
    capability: str = ""                        # atomic capability this step realises
    capability_class: str = "read"
    backend: str = "existing_runner"
    requires_approval: bool = True
    policy: ToolExecutionPolicy = field(default_factory=ToolExecutionPolicy)
    notes: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "server_name": self.server_name,
            "tool_name": self.tool_name,
            "capability": self.capability,
            "capability_class": self.capability_class,
            "backend": self.backend,
            "requires_approval": self.requires_approval,
            "policy": self.policy.to_dict(),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> SelectedMCPTool:
        known = {
            "server_name", "tool_name", "capability", "capability_class",
            "backend", "requires_approval", "notes",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        policy = data.get("policy")
        kwargs["policy"] = (
            ToolExecutionPolicy.from_dict(policy) if isinstance(policy, dict)
            else ToolExecutionPolicy()
        )
        return cls(**kwargs)


@dataclass
class ToolchainPlan(SchemaMixin):
    """A composed, not-yet-executed toolchain for a work packet."""

    id: str = field(default_factory=lambda: str(uuid4()))
    project_id: str = ""
    work_packet_ref: str = ""
    profile: str = ""
    steps: List[SelectedMCPTool] = field(default_factory=list)
    budget: ExecutionBudget = field(default_factory=ExecutionBudget)
    approvals_required: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "project_id": self.project_id,
            "work_packet_ref": self.work_packet_ref,
            "profile": self.profile,
            "steps": [s.to_dict() for s in self.steps],
            "budget": self.budget.to_dict(),
            "approvals_required": list(self.approvals_required),
            "notes": list(self.notes),
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> ToolchainPlan:
        known = {
            "id", "project_id", "work_packet_ref", "profile",
            "approvals_required", "notes", "created_at",
        }
        kwargs: Dict[str, Any] = {k: v for k, v in data.items() if k in known}
        kwargs["steps"] = [
            SelectedMCPTool.from_dict(s) if isinstance(s, dict) else s
            for s in data.get("steps", [])
        ]
        budget = data.get("budget")
        kwargs["budget"] = (
            ExecutionBudget.from_dict(budget) if isinstance(budget, dict)
            else ExecutionBudget()
        )
        return cls(**kwargs)
