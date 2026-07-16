"""CapabilityRegistry — Phase 8.1 (typed loader for capability config).

Loads the atomic capability registry, the capability profiles, and the MCP server
manifest from YAML into typed objects. No network, no discovery — pure file reads.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

import yaml

from core.schemas.capability import Capability, CapabilityProfile

_REPO_ROOT = Path(__file__).resolve().parents[2]


class CapabilityRegistry:
    """Reads capability + MCP configuration from YAML into typed objects."""

    def __init__(self, base_dir: Path | None = None) -> None:
        self._base = Path(base_dir) if base_dir else _REPO_ROOT
        self._atomic: Dict[str, Capability] = {}
        self._profiles: Dict[str, CapabilityProfile] = {}
        self._servers: List[Dict[str, Any]] = []
        self._loaded = False

    def load(self) -> "CapabilityRegistry":
        atomic_path = self._base / "capabilities" / "atomic_capabilities.yaml"
        raw = yaml.safe_load(atomic_path.read_text(encoding="utf-8")) or {}
        for name, spec in (raw.get("capabilities") or {}).items():
            self._atomic[name] = Capability(
                name=name,
                capability_class=spec.get("class", "read"),
                default_requires_approval=bool(spec.get("default_requires_approval", True)),
                candidate_backends=list(spec.get("candidate_backends", [])),
                candidate_mcp_servers=list(spec.get("candidate_mcp_servers", [])),
            )

        prof_dir = self._base / "capabilities" / "profiles"
        for f in sorted(prof_dir.glob("*.yaml")):
            p = yaml.safe_load(f.read_text(encoding="utf-8")) or {}
            self._profiles[p["name"]] = CapabilityProfile(
                name=p["name"],
                title=p.get("title", ""),
                description=p.get("description", ""),
                capabilities=list(p.get("capabilities", [])),
                candidate_backends=list(p.get("candidate_backends", [])),
                candidate_mcp_servers=list(p.get("candidate_mcp_servers", [])),
                default_policy=p.get("default_policy", "planning_only"),
                evidence_expectations=list(p.get("evidence_expectations", [])),
                delivery_shape=list(p.get("delivery_shape", [])),
            )

        manifest_path = self._base / "config" / "mcp_servers.yaml"
        manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) or {}
        self._servers = list(manifest.get("servers", []))
        self._loaded = True
        return self

    def atomic(self, name: str) -> Capability | None:
        return self._atomic.get(name)

    def profile(self, name: str) -> CapabilityProfile | None:
        return self._profiles.get(name)

    def profiles(self) -> Dict[str, CapabilityProfile]:
        return dict(self._profiles)

    def servers(self) -> List[Dict[str, Any]]:
        return list(self._servers)
