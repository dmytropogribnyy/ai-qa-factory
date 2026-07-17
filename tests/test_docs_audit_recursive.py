"""Docs-audit recursive-scan tests (Phase 8.2).

Proves the foundation/runtime-overclaim scan now covers nested architecture docs, that a
nested source-of-truth file can be required (and missing status detected), that archive
docs keep their intentional exemption, and that the real Prospect Radar spec is present
and registered.
"""
from __future__ import annotations

from pathlib import Path

from tools.docs_audit import (
    check_foundation_only_features,
    check_required_docs,
    REPO_ROOT,
)

_CLAIM = "the crawler sends http requests to the target"          # matches an audit claim term
_QUALIFIED = "planned: the crawler sends http requests (not implemented)"


def _mk(root: Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _findings_for(root: Path):
    return {c["doc_path"] for c in check_foundation_only_features(root) if not c["passed"]}


class TestRecursiveScan:
    def test_nested_architecture_doc_is_scanned(self, tmp_path):
        _mk(tmp_path, "README.md", "")
        _mk(tmp_path, "docs/architecture/OVERCLAIM.md", _CLAIM)
        assert "docs/architecture/OVERCLAIM.md" in _findings_for(tmp_path)

    def test_overclaim_in_nested_doc_flagged_like_toplevel(self, tmp_path):
        _mk(tmp_path, "README.md", "")
        _mk(tmp_path, "docs/TOP.md", _CLAIM)
        _mk(tmp_path, "docs/architecture/NESTED.md", _CLAIM)
        findings = _findings_for(tmp_path)
        assert "docs/TOP.md" in findings and "docs/architecture/NESTED.md" in findings

    def test_qualified_nested_doc_not_flagged(self, tmp_path):
        _mk(tmp_path, "README.md", "")
        _mk(tmp_path, "docs/architecture/QUALIFIED.md", _QUALIFIED)
        assert "docs/architecture/QUALIFIED.md" not in _findings_for(tmp_path)

    def test_archive_doc_is_exempt(self, tmp_path):
        _mk(tmp_path, "README.md", "")
        _mk(tmp_path, "docs/archive/OLD.md", _CLAIM)
        assert "docs/archive/OLD.md" not in _findings_for(tmp_path)

    def test_nested_required_doc_missing_is_detected(self, tmp_path):
        # Temp root has none of the required docs -> the architecture spec is reported missing.
        results = check_required_docs(tmp_path)
        missing = {
            c["doc_path"] for c in results
            if not c["passed"] and c["severity"] == "error"
        }
        assert "docs/architecture/PROSPECT_QA_RADAR_SPEC.md" in missing
        assert "docs/architecture/README.md" in missing


class TestRealSpecPresence:
    def test_spec_present_and_nonempty(self):
        spec = REPO_ROOT / "docs" / "architecture" / "PROSPECT_QA_RADAR_SPEC.md"
        assert spec.exists()
        assert spec.stat().st_size > 1000          # populated, not a stub (no line-count coupling)

    def test_manifest_references_spec(self):
        manifest = (REPO_ROOT / "docs" / "DOCS_MANIFEST.md").read_text(encoding="utf-8")
        assert "architecture/PROSPECT_QA_RADAR_SPEC.md" in manifest

    def test_architecture_index_references_spec(self):
        index = (REPO_ROOT / "docs" / "architecture" / "README.md").read_text(encoding="utf-8")
        assert "PROSPECT_QA_RADAR_SPEC.md" in index
