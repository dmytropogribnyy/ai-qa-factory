"""Evidence Manager — Phase 4B.

Creates evidence directory structure and registers existing local artifacts.
No browser evidence collection, no Playwright, no URL fetching, no credentials.

SAFETY: client_visible=False by default. approved_for_client_view=False always.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.schemas.evidence import (
    EvidenceCollection,
    EvidenceQualityGate,
    EvidenceRecord,
    EvidenceRedactionReport,
)

_OUTPUTS_ROOT = Path("outputs")

_SECRET_PATTERNS = ["password", "token", "api_key", "secret", "credential", "auth", "cookie", "session"]


class EvidenceManager:
    """Registers and manages local evidence artifacts. No real evidence collection performed."""

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self._outputs_root = outputs_root or _OUTPUTS_ROOT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_evidence_foundation(
        self,
        project_id: str,
        scaffold_root: Optional[Path] = None,
    ) -> Tuple[EvidenceCollection, EvidenceQualityGate, EvidenceRedactionReport]:
        """Register local artifacts as evidence and return collection, quality gate, redaction report."""
        evidence_dir = self._outputs_root / project_id / "05_evidence"
        evidence_dir.mkdir(parents=True, exist_ok=True)

        sc_root = scaffold_root or (self._outputs_root / project_id / "03_framework" / "playwright")

        records = self._register_artifacts(project_id, sc_root)
        collection = self._build_collection(project_id, evidence_dir, records)
        quality_gate = self._build_quality_gate(project_id, records)
        redaction_report = self._build_redaction_report(project_id, records)

        return collection, quality_gate, redaction_report

    def render_evidence_artifacts(
        self,
        collection: EvidenceCollection,
        quality_gate: EvidenceQualityGate,
        redaction_report: EvidenceRedactionReport,
        project_id: str,
    ) -> Dict[str, Path]:
        """Write evidence artifacts to outputs/<project_id>/05_evidence/."""
        out_dir = self._outputs_root / project_id / "05_evidence"
        out_dir.mkdir(parents=True, exist_ok=True)

        paths: Dict[str, Path] = {}

        p = out_dir / "EVIDENCE_MANIFEST.json"
        p.write_text(json.dumps(collection.to_dict(), indent=2), encoding="utf-8")
        paths["manifest_json"] = p

        p = out_dir / "EVIDENCE_MANIFEST.md"
        p.write_text(self._render_manifest_md(collection), encoding="utf-8")
        paths["manifest_md"] = p

        p = out_dir / "EVIDENCE_QUALITY_GATE.json"
        p.write_text(json.dumps(quality_gate.to_dict(), indent=2), encoding="utf-8")
        paths["quality_gate_json"] = p

        p = out_dir / "EVIDENCE_QUALITY_GATE.md"
        p.write_text(self._render_quality_gate_md(quality_gate), encoding="utf-8")
        paths["quality_gate_md"] = p

        p = out_dir / "EVIDENCE_REDACTION_REPORT.json"
        p.write_text(json.dumps(redaction_report.to_dict(), indent=2), encoding="utf-8")
        paths["redaction_json"] = p

        p = out_dir / "EVIDENCE_REDACTION_REPORT.md"
        p.write_text(self._render_redaction_md(redaction_report), encoding="utf-8")
        paths["redaction_md"] = p

        p = out_dir / "INTERNAL_EVIDENCE_SUMMARY.md"
        p.write_text(self._render_internal_summary_md(collection, quality_gate), encoding="utf-8")
        paths["summary_md"] = p

        return paths

    # ------------------------------------------------------------------
    # Internal: artifact registration
    # ------------------------------------------------------------------

    def _register_artifacts(self, project_id: str, sc_root: Path) -> List[EvidenceRecord]:
        records: List[EvidenceRecord] = []
        eid = 0

        def _add(path: Path, evidence_type: str, title: str, desc: str, phase: str) -> None:
            nonlocal eid
            if path.exists():
                eid += 1
                records.append(EvidenceRecord(
                    id=f"ev_{eid:03d}",
                    evidence_type=evidence_type,
                    path=str(path),
                    title=title,
                    description=desc,
                    source_phase=phase,
                    client_visible=False,
                    internal_only=True,
                    requires_redaction=True,
                    redacted=False,
                ))

        base = self._outputs_root / project_id

        # Phase 2A/2B artifacts
        _add(base / "00_project" / "PROJECT_BLUEPRINT.json",
             "blueprint_artifact", "Project Blueprint (JSON)", "Machine-readable project blueprint.", "2B")
        _add(base / "00_project" / "PROJECT_BLUEPRINT.md",
             "blueprint_artifact", "Project Blueprint (Markdown)", "Human-readable project blueprint.", "2B")
        _add(base / "00_project" / "INPUT_MAP.json",
             "project_artifact", "Input Map (JSON)", "Classified input sources.", "2A")
        _add(base / "00_project" / "TASK_CLASSIFICATION.json",
             "project_artifact", "Task Classification", "Task type and confidence.", "2A")

        # Phase 2C artifacts
        _add(base / "02_strategy" / "QA_STRATEGY.json",
             "strategy_artifact", "QA Strategy (JSON)", "Full QA strategy with layers and risk matrix.", "2C")
        _add(base / "02_strategy" / "QA_STRATEGY.md",
             "strategy_artifact", "QA Strategy (Markdown)", "Human-readable QA strategy.", "2C")

        # Phase 3A artifacts
        _add(sc_root / "FRAMEWORK_SCAFFOLD.json",
             "scaffold_metadata", "Framework Scaffold (JSON)", "Generated Playwright scaffold metadata.", "3A")
        _add(sc_root / "FRAMEWORK_SCAFFOLD.md",
             "scaffold_metadata", "Framework Scaffold (Markdown)", "Human-readable scaffold summary.", "3A")

        # Phase 3B artifacts
        _add(sc_root / "STATIC_VALIDATION_REPORT.json",
             "validation_report", "Static Validation Report (JSON)", "Scaffold static checks.", "3B")
        _add(sc_root / "STATIC_VALIDATION_REPORT.md",
             "validation_report", "Static Validation Report (Markdown)", "Human-readable static validation.", "3B")

        # Phase 3C artifacts
        _add(sc_root / "TOOLCHAIN_VALIDATION_REPORT.json",
             "validation_report", "Toolchain Validation Report (JSON)", "Approval-gated toolchain validation.", "3C")
        _add(sc_root / "TOOLCHAIN_VALIDATION_REPORT.md",
             "validation_report", "Toolchain Validation Report (Markdown)", "Human-readable toolchain validation.", "3C")
        _add(sc_root / "TOOLCHAIN_COMMAND_LOG.md",
             "command_log", "Toolchain Command Log", "Per-command stdout/stderr excerpts.", "3C")

        return records

    def _build_collection(
        self,
        project_id: str,
        evidence_dir: Path,
        records: List[EvidenceRecord],
    ) -> EvidenceCollection:
        internal = sum(1 for r in records if r.internal_only)
        visible = sum(1 for r in records if r.client_visible)
        needs_redaction = sum(1 for r in records if r.requires_redaction)

        return EvidenceCollection(
            project_id=project_id,
            evidence_root=str(evidence_dir),
            records=records,
            client_visible_count=visible,
            internal_only_count=internal,
            redaction_required_count=needs_redaction,
            ready_for_client_review=False,
            notes=[
                "All evidence is internal-only by default.",
                "No real browser or test execution evidence exists yet.",
                "Evidence collection plan is ready; approved execution has not occurred.",
            ],
        )

    def _build_quality_gate(
        self, project_id: str, records: List[EvidenceRecord]
    ) -> EvidenceQualityGate:
        has_cmd_logs = any(r.evidence_type == "command_log" for r in records)
        has_validation = any(r.evidence_type == "validation_report" for r in records)
        has_internal = len(records) > 0

        blockers: List[str] = []
        warnings: List[str] = []

        if not has_cmd_logs:
            warnings.append("No command logs registered — run Phase 3C with --approve-toolchain.")
        if not has_validation:
            blockers.append("No validation reports registered — run Phase 3B and 3C.")
        if not has_internal:
            blockers.append("No evidence records registered — run Phase 3A, 3B, 3C first.")

        blockers.append("approved_for_client_view=False — human review required before any client visibility.")

        return EvidenceQualityGate(
            project_id=project_id,
            has_command_logs=has_cmd_logs,
            has_test_results=False,
            has_screenshots=False,
            has_traces=False,
            has_internal_summary=has_internal,
            has_client_summary=False,
            redaction_complete=False,
            approved_for_client_view=False,
            blockers=blockers,
            warnings=warnings,
            notes=[
                "has_test_results=False — no execution performed.",
                "has_screenshots=False — no browser launched.",
                "has_traces=False — no browser launched.",
            ],
        )

    def _build_redaction_report(
        self, project_id: str, records: List[EvidenceRecord]
    ) -> EvidenceRedactionReport:
        scanned: List[str] = [r.path for r in records]
        return EvidenceRedactionReport(
            project_id=project_id,
            scanned_files=scanned,
            redactions_needed=len(scanned),
            redactions_completed=0,
            secrets_found=[],
            unsafe_paths=[],
            client_visible_blocked=True,
            notes=[
                "Redaction review required before any client visibility.",
                "No secrets reproduced in this report.",
                "All evidence remains internal-only until redaction is confirmed.",
            ],
        )

    # ------------------------------------------------------------------
    # Markdown renderers
    # ------------------------------------------------------------------

    def _render_manifest_md(self, collection: EvidenceCollection) -> str:
        lines = [
            "# Evidence Manifest",
            "",
            "> **INTERNAL ONLY — Not approved for client review.**",
            "",
            f"**Project:** `{collection.project_id}`  ",
            f"**Evidence root:** `{collection.evidence_root}`  ",
            f"**Total records:** {len(collection.records)}  ",
            f"**Client-visible:** {collection.client_visible_count}  ",
            f"**Internal only:** {collection.internal_only_count}  ",
            f"**Redaction required:** {collection.redaction_required_count}  ",
            f"**ready_for_client_review:** {collection.ready_for_client_review}  ",
            "",
            "## Registered Evidence",
            "",
            "| ID | Type | Phase | Title | Internal? |",
            "|---|---|---|---|---|",
        ]
        for r in collection.records:
            lines.append(f"| `{r.id}` | {r.evidence_type} | {r.source_phase} | {r.title} | {r.internal_only} |")
        lines += [
            "",
            "## Notes",
        ]
        for note in collection.notes:
            lines.append(f"- {note}")
        return "\n".join(lines) + "\n"

    def _render_quality_gate_md(self, gate: EvidenceQualityGate) -> str:
        def _check(v: bool) -> str:
            return "✓" if v else "✗"

        lines = [
            "# Evidence Quality Gate",
            "",
            "> **approved_for_client_view: False** — human review required.",
            "",
            f"**Project:** `{gate.project_id}`",
            "",
            "## Checks",
            "",
            f"- {_check(gate.has_command_logs)} Command logs",
            f"- {_check(gate.has_test_results)} Test results",
            f"- {_check(gate.has_screenshots)} Screenshots",
            f"- {_check(gate.has_traces)} Traces",
            f"- {_check(gate.has_internal_summary)} Internal summary",
            f"- {_check(gate.has_client_summary)} Client summary",
            f"- {_check(gate.redaction_complete)} Redaction complete",
            f"- {_check(gate.approved_for_client_view)} Approved for client view",
            "",
        ]
        if gate.blockers:
            lines += ["## Blockers", ""]
            for b in gate.blockers:
                lines.append(f"- {b}")
            lines.append("")
        if gate.warnings:
            lines += ["## Warnings", ""]
            for w in gate.warnings:
                lines.append(f"- {w}")
        return "\n".join(lines) + "\n"

    def _render_redaction_md(self, report: EvidenceRedactionReport) -> str:
        lines = [
            "# Evidence Redaction Report",
            "",
            f"**Project:** `{report.project_id}`  ",
            f"**Files scanned:** {len(report.scanned_files)}  ",
            f"**Redactions needed:** {report.redactions_needed}  ",
            f"**Redactions completed:** {report.redactions_completed}  ",
            f"**client_visible_blocked:** {report.client_visible_blocked}  ",
            "",
            "## Notes",
        ]
        for note in report.notes:
            lines.append(f"- {note}")
        return "\n".join(lines) + "\n"

    def _render_internal_summary_md(
        self,
        collection: EvidenceCollection,
        gate: EvidenceQualityGate,
    ) -> str:
        return f"""# Internal Evidence Summary

> **INTERNAL ONLY — Not for client delivery.**

**Project:** `{collection.project_id}`

## Current Evidence Status

- Evidence records registered: **{len(collection.records)}**
- Client-visible: **{collection.client_visible_count}** (all 0 by default)
- Redaction complete: **{gate.redaction_complete}**
- Approved for client view: **{gate.approved_for_client_view}**

## What Exists

This phase has generated planning and scaffold validation artifacts only.
No browser tests have been run. No test results, screenshots, or traces exist yet.

## What Is Needed Before Client Delivery

1. Complete all items in EXECUTION_APPROVAL_CHECKLIST.md.
2. Run approved browser execution (Phase 4A+ execution).
3. Collect test results, screenshots, and traces.
4. Complete EVIDENCE_REDACTION_REPORT review.
5. Obtain approved_for_client_view = True from human reviewer.
6. Complete CLIENT_REPORT_DRAFT review and approval.

## Safety Boundary

- No execution performed.
- No URL fetching performed.
- No credentials used.
- No external calls performed.
"""
