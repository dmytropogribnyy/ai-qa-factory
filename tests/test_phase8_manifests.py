"""Phase 8.0 — ARK manifest / config validation tests.

Covers:
- config/mcp_servers.yaml: reference-only (no secrets), no '@latest', versions/policies,
  sensitive servers disabled, availability scopes valid
- capabilities/atomic_capabilities.yaml: classes valid, in sync with schema vocabulary
- capabilities/profiles/*.yaml: reference only known atomic capabilities and profile names
"""
from __future__ import annotations

import re
from pathlib import Path

import yaml

from core.schemas.capability import (
    ATOMIC_CAPABILITIES, CAPABILITY_PROFILES, CAPABILITY_CLASSES,
)
from core.schemas.mcp_descriptor import (
    MCP_TRANSPORTS, MCP_AVAILABILITY_SCOPES, VERSION_POLICIES,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "config" / "mcp_servers.yaml"
ATOMIC = REPO_ROOT / "capabilities" / "atomic_capabilities.yaml"
PROFILES_DIR = REPO_ROOT / "capabilities" / "profiles"

# Obvious secret-bearing tokens that must never appear as values in the manifest.
_SECRET_HINTS = re.compile(r"(sk_live|sk_test|bearer\s|pk_live|xox[baprs]-|ghp_|-----BEGIN)", re.I)


def _load(path: Path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# MCP manifest
# ---------------------------------------------------------------------------

class TestMcpManifest:
    def test_loads(self):
        data = _load(MANIFEST)
        assert isinstance(data, dict) and "servers" in data

    def test_no_at_latest_in_server_commands(self):
        # The rule applies to actual server command/url values, not explanatory comments.
        for s in _load(MANIFEST)["servers"]:
            for key in ("command_template", "url_ref"):
                val = s.get(key, "")
                assert "@latest" not in val, f"{s['name']}.{key} must not use @latest"

    def test_no_obvious_secrets(self):
        raw = MANIFEST.read_text(encoding="utf-8")
        assert not _SECRET_HINTS.search(raw), "manifest must contain references only, no secrets"

    def test_auth_ref_is_env_name_not_value(self):
        for s in _load(MANIFEST)["servers"]:
            auth = s.get("auth_ref", "")
            if auth:
                # env-var style name only (UPPER_SNAKE), never a URL or token value
                assert re.fullmatch(r"[A-Z][A-Z0-9_]*", auth), f"{s['name']} auth_ref not an env name"

    def test_urls_are_redacted_or_public_host(self):
        for s in _load(MANIFEST)["servers"]:
            url = s.get("url_ref", "")
            if url:
                assert url.startswith("ref:"), f"{s['name']} url_ref must be a ref: placeholder"

    def test_server_fields_valid(self):
        for s in _load(MANIFEST)["servers"]:
            assert s["transport"] in MCP_TRANSPORTS
            assert s["version_policy"] in VERSION_POLICIES
            assert s["version_policy"] != "latest_dev_only"  # not for client work
            for scope in s.get("availability_scopes", []):
                assert scope in MCP_AVAILABILITY_SCOPES
            for cls in s.get("capability_classes", []):
                assert cls in CAPABILITY_CLASSES

    def test_all_servers_disabled_in_phase_8_0(self):
        data = _load(MANIFEST)
        assert data.get("default_enabled") is False
        for s in data["servers"]:
            assert s.get("enabled", False) is False, f"{s['name']} must be disabled in 8.0"

    def test_github_marked_unreachable(self):
        gh = next(s for s in _load(MANIFEST)["servers"] if s["name"] == "github")
        assert "configured_but_unreachable" in gh["availability_scopes"]


# ---------------------------------------------------------------------------
# Atomic capability registry
# ---------------------------------------------------------------------------

class TestAtomicCapabilities:
    def test_in_sync_with_schema(self):
        caps = _load(ATOMIC)["capabilities"]
        assert set(caps) == set(ATOMIC_CAPABILITIES), "yaml registry out of sync with schema"

    def test_classes_valid(self):
        for name, spec in _load(ATOMIC)["capabilities"].items():
            assert spec["class"] in CAPABILITY_CLASSES, f"{name} bad class"
            assert isinstance(spec.get("default_requires_approval"), bool)


# ---------------------------------------------------------------------------
# Capability profiles
# ---------------------------------------------------------------------------

class TestCapabilityProfiles:
    def test_eight_profiles(self):
        files = sorted(PROFILES_DIR.glob("*.yaml"))
        assert len(files) == 8

    def test_profiles_reference_known_capabilities(self):
        atomic_names = set(ATOMIC_CAPABILITIES)
        for f in PROFILES_DIR.glob("*.yaml"):
            prof = _load(f)
            assert prof["name"] in CAPABILITY_PROFILES, f"{f.name} unknown profile name"
            for cap in prof.get("capabilities", []):
                assert cap in atomic_names, f"{f.name} references unknown capability {cap}"

    def test_profile_names_match_registry(self):
        names = {_load(f)["name"] for f in PROFILES_DIR.glob("*.yaml")}
        assert names == set(CAPABILITY_PROFILES)
