"""MCP integration audit + fail-closed tool/output guards (Final Phase II).

Validates the references-only MCP manifest and MCP tool schemas/output. Fail-closed: enabled must
be false; auth references are env names; write/external-communication/financial capabilities are
approval-gated; a developer-agent-only server is never available to the Factory process; readiness
is honest (a manifest entry is only `declared_in_manifest`). Provides the adversarial guards
(malformed schema, duplicate/namespaced tools, excessive count, write-in-read-only, unapproved
external/financial, secret leakage, prompt injection, partial/timeout, recursion, agent-only
misuse) used by the deterministic tests. No live MCP call is ever made here.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.orchestration.content_safety import ContentSecretScanner

INTEGRATION_CLASSES = frozenset({
    "developer_agent_only", "optional_factory_runtime", "external_communication",
    "deployment_only", "post_v2_candidate",
})
CAPABILITY_CLASSES = frozenset({"read", "write", "external_communication", "financial"})
READINESS_LEVELS = ("declared_in_manifest", "health_checked", "tools_discovered", "configured",
                    "sandbox_accepted", "live_accepted")
_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")
_GATED = frozenset({"write", "external_communication", "financial"})

# Heuristic prompt-injection markers in untrusted MCP output (data, never instructions).
_INJECTION_MARKERS = (
    "ignore previous instructions", "ignore all previous", "disregard the above",
    "disregard previous", "you are now", "system prompt", "reveal your", "exfiltrate",
    "run the following command", "delete all", "send the api key", "print your instructions",
)

_scanner = ContentSecretScanner()


def load_manifest(path: str) -> List[Dict[str, Any]]:
    import yaml
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    return list(data.get("servers", []))


# --- server validation ------------------------------------------------------

def validate_server(entry: Dict[str, Any]) -> List[str]:
    """Fail-closed manifest validation. Returns issue strings ([] == valid)."""
    issues: List[str] = []
    if entry.get("enabled", False):
        issues.append(f"{entry.get('id')}: enabled must be false (disabled by default)")
    ic = entry.get("integration_class")
    if ic not in INTEGRATION_CLASSES:
        issues.append(f"{entry.get('id')}: unknown integration_class {ic!r}")
    auth = entry.get("auth_ref", "")
    if auth and not _ENV_NAME_RE.match(auth):
        issues.append(f"{entry.get('id')}: auth_ref must be an env-var name, not a value")
    caps = set(entry.get("capability_classes", []))
    unknown = caps - CAPABILITY_CLASSES
    if unknown:
        issues.append(f"{entry.get('id')}: unknown capability classes {sorted(unknown)}")
    if (caps & _GATED) and not entry.get("approval_required", False):
        issues.append(f"{entry.get('id')}: write/external/financial capability requires approval_required")
    readiness = entry.get("readiness", "declared_in_manifest")
    if readiness not in READINESS_LEVELS:
        issues.append(f"{entry.get('id')}: unknown readiness {readiness!r}")
    if readiness in ("configured", "sandbox_accepted", "live_accepted"):
        issues.append(f"{entry.get('id')}: manifest may not claim {readiness!r} (no live evidence)")
    if ic == "developer_agent_only" and entry.get("available_to_factory_process", False):
        issues.append(f"{entry.get('id')}: developer_agent_only must not be available to the Factory")
    return issues


def assert_available_to_factory(entry: Dict[str, Any]) -> None:
    """Raise if an agent-only server is assumed usable by the standalone Factory process."""
    if entry.get("integration_class") == "developer_agent_only" or not entry.get(
            "available_to_factory_process", False):
        raise McpIntegrationError(
            f"{entry.get('id')} is developer-agent-only; it is NOT available to the Factory process")


class McpIntegrationError(Exception):
    pass


# --- audit / snapshots ------------------------------------------------------

def audit(entries: List[Dict[str, Any]], *, factory_process: bool = True) -> Dict[str, Any]:
    servers = []
    for e in entries:
        issues = validate_server(e)
        readiness = e.get("readiness", "declared_in_manifest")
        factory_readiness = readiness
        if factory_process and (e.get("integration_class") == "developer_agent_only"
                                or not e.get("available_to_factory_process", False)):
            factory_readiness = "unavailable_to_factory_process"
        servers.append({
            "id": e.get("id"), "publisher": e.get("publisher"),
            "integration_class": e.get("integration_class"), "enabled": e.get("enabled", False),
            "capability_classes": e.get("capability_classes", []),
            "manifest_readiness": readiness, "factory_readiness": factory_readiness,
            "approval_required": e.get("approval_required", False),
            "auth_ref": e.get("auth_ref", ""), "issues": issues,
            "tools_discovered": False,       # honest: no live tools/list from the manifest
        })
    return {"servers": servers, "total": len(servers),
            "valid": all(not s["issues"] for s in servers),
            "discovery_source": "manifest_declared",
            "note": "No live tools/list discovery — all servers are disabled by default."}


def discovery_snapshot(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    return {"discovery_source": "manifest_declared", "live_tools_list": False,
            "servers": [{"id": e.get("id"), "declared_toolsets": e.get("toolsets", []),
                         "transport": e.get("transport"), "readiness": e.get("readiness")}
                        for e in entries],
            "note": "Declared toolsets only. Live discovery requires an explicitly configured, "
                    "enabled server, which is disabled by default."}


def gap_report(entries: List[Dict[str, Any]]) -> Dict[str, Any]:
    gaps = []
    for e in entries:
        needs = []
        if e.get("auth_ref"):
            needs.append("credential")
        if e.get("terms_review") != "reviewed_ok":
            needs.append("terms_review")
        if e.get("readiness") == "declared_in_manifest":
            needs.append("health_check + tools_discovery")
        gaps.append({"id": e.get("id"), "integration_class": e.get("integration_class"),
                     "readiness": e.get("readiness"), "gap_to_live": needs,
                     "fallback_runner": e.get("fallback_runner", "")})
    return {"gaps": gaps, "note": "Every entry is at most declared_in_manifest; none is live-accepted."}


# --- tool / output guards (adversarial) -------------------------------------

def validate_tool(tool: Dict[str, Any], *, mode: str = "read_only",
                  approvals: frozenset = frozenset()) -> List[str]:
    issues: List[str] = []
    if not isinstance(tool, dict) or not tool.get("name") or "inputSchema" not in tool:
        return ["malformed_tool_schema"]
    caps = set(tool.get("capability_classes", ["read"]))
    if mode == "read_only" and "write" in caps and "write" not in approvals:
        issues.append("write_tool_in_read_only_mode")
    if "external_communication" in caps and "external_communication" not in approvals:
        issues.append("external_communication_without_approval")
    if "financial" in caps and "financial" not in approvals:
        issues.append("financial_tool_without_approval")
    return issues


def dedup_tools(tools: List[Dict[str, Any]], *, server_id: str) -> Tuple[List[Dict[str, Any]], List[str]]:
    """Namespace tools by server and drop duplicates. Returns (unique, collisions)."""
    seen: set = set()
    unique: List[Dict[str, Any]] = []
    collisions: List[str] = []
    for t in tools:
        name = t.get("name", "")
        key = f"{server_id}::{name}"
        if key in seen:
            collisions.append(key)
            continue
        seen.add(key)
        unique.append({**t, "namespaced_name": key})
    return unique, collisions


def excessive_tool_count(tools: List[Any], *, limit: int = 80) -> bool:
    return len(tools) > limit


def detect_secret_leak(text: str) -> bool:
    return bool(_scanner.scan_text("mcp", text or ""))


def detect_prompt_injection(text: str) -> bool:
    low = (text or "").lower()
    return any(m in low for m in _INJECTION_MARKERS)


def classify_result(status: str, *, partial: bool = False) -> str:
    """A timeout/partial MCP result is never treated as success."""
    if status in ("timeout", "error"):
        return "FAILED"
    if partial:
        return "PARTIAL"
    if status == "ok":
        return "OK"
    return "UNKNOWN"


def check_recursion(call_stack: List[str], next_server: str, *, max_depth: int = 4) -> None:
    """Guard against recursive MCP loops (a server re-invoking the chain)."""
    if next_server in call_stack:
        raise McpIntegrationError(f"recursive MCP loop detected: {next_server}")
    if len(call_stack) >= max_depth:
        raise McpIntegrationError("MCP call depth exceeded")


def version_mismatch(declared: str, discovered: Optional[str]) -> bool:
    return bool(discovered) and declared not in ("", discovered)
