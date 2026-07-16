"""MCP server/tool descriptor schemas — Phase 8.0 (ARK MCP-consumption layer).

These schemas describe MCP servers and tools that the ARK Factory may consume as a
CLIENT. They are the normalised internal model produced later (Phase 8.3) by live
discovery. In Phase 8.0 they are foundation only: no discovery, no tool calls.

CRITICAL TRUST RULE:
- Server-provided tool annotations are UNTRUSTED HINTS (declared_annotations).
- The authoritative permission is local_policy_classification, decided by ARK.
- availability to the standalone Factory process is separate from availability to
  the Claude agent (see MCP_AVAILABILITY_SCOPES).

SAFETY / DESIGN NOTES:
- command_or_url_ref and auth_ref hold reference labels / env-var names, never
  secrets, tokens, cookies, or secret-bearing URLs.
- enabled defaults to False; sensitive servers must be explicitly enabled.
- Client-work profiles must pin versions; do not depend on "@latest".
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

from core.schemas.base import SchemaMixin

MCP_TRANSPORTS = frozenset({"stdio", "http", "sse"})

MCP_TRUST_LEVELS = frozenset({"trusted", "semi_trusted", "untrusted"})

MCP_HEALTH_STATUSES = frozenset({
    "unknown", "reachable", "unreachable", "needs_authentication",
})

# Independent availability scopes (a server may hold several at once).
MCP_AVAILABILITY_SCOPES = frozenset({
    "available_to_claude_agent",
    "available_to_factory_process",
    "requires_factory_auth_setup",
    "configured_but_unreachable",
    "known_candidate_not_configured",
})

# Version handling policy — client-work profiles must not use rolling "@latest".
VERSION_POLICIES = frozenset({"pinned", "range", "latest_dev_only"})

CAPABILITY_CLASSES = frozenset({
    "read", "compute", "write", "financial", "external_communication", "destructive",
})


@dataclass
class MCPServerDescriptor(SchemaMixin):
    """Normalised descriptor for one MCP server ARK may consume as a client."""

    name: str = ""
    transport: str = "stdio"
    command_or_url_ref: str = ""                # command template or safe URL reference
    auth_ref: str = ""                          # env-var name / credential reference, not a secret
    enabled: bool = False
    trust_level: str = "untrusted"
    provenance: str = ""                        # where this server config came from
    allowed_workspace_roots: List[str] = field(default_factory=list)
    health_status: str = "unknown"
    capability_classes: List[str] = field(default_factory=list)
    availability_scopes: List[str] = field(default_factory=list)
    # Version / reproducibility (Phase 8.0 correction #6)
    package_or_server_version: str = ""
    version_policy: str = "pinned"
    last_verified_version: str = ""
    discovery_schema_version: str = ""
    upgrade_requires_review: bool = True
    # Discovery bookkeeping (populated only in Phase 8.3+)
    discovered_at: str = ""
    last_checked_at: str = ""
    degraded_reason: str = ""

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MCPServerDescriptor:
        # Descriptor round-trips faithfully; enable/trust decisions are made by the
        # ToolPolicyEngine at plan time, not silently during rehydration.
        return super().from_dict(data)


@dataclass
class MCPToolDescriptor(SchemaMixin):
    """Normalised descriptor for one tool exposed by an MCP server."""

    server_name: str = ""
    tool_name: str = ""
    title: str = ""
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)
    output_schema: Dict[str, Any] = field(default_factory=dict)
    # Server-provided hints — UNTRUSTED.
    declared_annotations: Dict[str, Any] = field(default_factory=dict)
    # ARK-authoritative classification.
    local_policy_classification: str = "read"
    requires_approval: bool = True
    read_only: bool = True
    external_write: bool = False
    financial: bool = False
    destructive: bool = False
    external_communication: bool = False
    idempotency: str = "unknown"
    timeout_seconds: int = 60
    enabled: bool = False
    trust_status: str = "untrusted"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> MCPToolDescriptor:
        return super().from_dict(data)
