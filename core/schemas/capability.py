"""Capability and CapabilityProfile schemas — Phase 8.0 (ARK universal work layer).

Two distinct concepts (do not conflate):

- Capability      : an ATOMIC ability (e.g. web_navigation, database_read).
- CapabilityProfile: a reusable BUNDLE of capabilities for a work category
                     (e.g. web_app_audit references several atomic capabilities).

The atomic Capability registry is the intelligent source of truth about what the
Factory can do. Profiles only reference capability names; they never redefine them.

SAFETY / DESIGN NOTES:
- Every capability carries a capability_class used by the ToolPolicyEngine.
- default_requires_approval is True for anything that is not purely read/compute.
- Planning-only foundation. No runtime dispatch is attached in Phase 8.0.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from core.schemas.base import SchemaMixin

# Action risk classes shared with the MCP descriptors and ToolPolicyEngine.
CAPABILITY_CLASSES = frozenset({
    "read", "compute", "write", "financial", "external_communication", "destructive",
})

# The atomic capability vocabulary (extensible via config, not hardcoded elsewhere).
ATOMIC_CAPABILITIES = frozenset({
    "repository_read", "repository_write",
    "web_navigation", "dom_inspection", "browser_form_interaction",
    "api_contract_analysis", "api_read_execution",
    "database_read", "database_write",
    "code_generation", "code_modification", "test_execution",
    "deployment_write", "external_communication", "financial_action",
    "evidence_collection", "delivery_assembly",
})

# Named, reusable profiles (bundles). Names only — bundles live in capabilities/profiles/.
CAPABILITY_PROFILES = frozenset({
    "research_only", "code_project", "web_app_audit", "api_project",
    "data_project", "automation_project", "mvp_launch_audit", "technical_writing",
})


@dataclass
class Capability(SchemaMixin):
    """An atomic ability the Factory can plan for and (later) execute."""

    name: str = ""                              # must be one of ATOMIC_CAPABILITIES
    title: str = ""
    description: str = ""
    capability_class: str = "read"
    default_requires_approval: bool = True
    candidate_backends: List[str] = field(default_factory=list)
    candidate_mcp_servers: List[str] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> Capability:
        return super().from_dict(data)


@dataclass
class CapabilityProfile(SchemaMixin):
    """A reusable bundle of atomic capabilities for a work category."""

    name: str = ""                              # e.g. "web_app_audit"
    title: str = ""
    description: str = ""
    capabilities: List[str] = field(default_factory=list)   # references atomic names
    candidate_backends: List[str] = field(default_factory=list)
    candidate_mcp_servers: List[str] = field(default_factory=list)
    default_policy: str = "planning_only"
    evidence_expectations: List[str] = field(default_factory=list)
    delivery_shape: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> CapabilityProfile:
        return super().from_dict(data)
