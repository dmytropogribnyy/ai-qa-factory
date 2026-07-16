"""Phase 8.0 — ARK documentation consistency tests.

Covers:
- all new architecture docs exist
- every new doc is registered in docs/DOCS_MANIFEST.md
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANIFEST = REPO_ROOT / "docs" / "DOCS_MANIFEST.md"

DOCS = [
    "docs/PRODUCT_VISION_2026.md",
    "docs/UNIVERSAL_WORK_FACTORY.md",
    "docs/MCP_ORCHESTRATION_ARCHITECTURE.md",
    "docs/MCP_SECURITY_AND_TRUST_MODEL.md",
    "docs/AGENT_INTEROPERABILITY.md",
    "docs/WORK_EXECUTION_MODEL.md",
    "docs/REUSE_MAP_PHASE8.md",
    "AGENTS.md",
    "CLAUDE.md",
]


class TestPhase8Docs:
    def test_all_docs_exist(self):
        missing = [d for d in DOCS if not (REPO_ROOT / d).exists()]
        assert not missing, f"missing docs: {missing}"

    def test_all_docs_registered_in_manifest(self):
        manifest = MANIFEST.read_text(encoding="utf-8")
        unregistered = [d for d in DOCS if d not in manifest and Path(d).name not in manifest]
        assert not unregistered, f"docs not registered in DOCS_MANIFEST: {unregistered}"

    def test_docs_are_nonempty(self):
        for d in DOCS:
            assert (REPO_ROOT / d).stat().st_size > 200, f"{d} looks empty"
