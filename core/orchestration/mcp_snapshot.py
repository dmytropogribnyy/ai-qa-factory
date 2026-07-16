"""MCP configured-servers snapshot — Phase 8.1 (config-level only).

Produces MCP_CONFIGURED_SERVERS_SNAPSHOT.json from the manifest. This is NOT live
discovery: it records configuration + declared availability with an explicit
`live_discovery_performed=false` and no discovered tools. Real protocol discovery
(tools/list) is Phase 8.3 and writes a separate MCP_DISCOVERY_SNAPSHOT.json.
"""
from __future__ import annotations

from typing import Any, Dict, List

from core.orchestration.capability_registry import CapabilityRegistry
from core.orchestration.providers import ClockProvider


def _factory_status(scopes: List[str]) -> str:
    if "available_to_factory_process" in scopes:
        return "verified"
    if "factory_process_launch_unverified" in scopes:
        return "launch_unverified"
    if "configured_but_unreachable" in scopes:
        return "unreachable"
    if "requires_factory_auth_setup" in scopes:
        return "auth_required"
    return "unknown"


def build_configured_servers_snapshot(
    registry: CapabilityRegistry, clock: ClockProvider
) -> Dict[str, Any]:
    servers: List[Dict[str, Any]] = []
    for s in registry.servers():
        scopes = list(s.get("availability_scopes", []))
        servers.append({
            "name": s.get("name", ""),
            "transport": s.get("transport", ""),
            "configured": True,
            "observation_source": "claude_workspace_config",
            "observed_by": "claude_agent",
            "availability_scopes": scopes,
            "factory_verification_status": _factory_status(scopes),
            "enabled": bool(s.get("enabled", False)),
            "discovered_tools": [],
        })
    return {
        "live_discovery_performed": False,
        "verified_at": clock.now_iso(),
        "note": (
            "Config-level snapshot only. No tools/list performed. Factory-process "
            "availability is unverified until Phase 8.3."
        ),
        "servers": servers,
    }
