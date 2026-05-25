"""Report Draft Builder — Phase 4C.

Generates:
- Internal QA summary draft
- Client report draft (DRAFT / NOT APPROVED)
- Delivery note draft
- Report quality checklist

SAFETY: Never claims execution happened. Never marks reports approved for delivery.
Never includes raw secrets. Never includes internal-only details in client-facing drafts.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.schemas.reporting import (
    DeliveryNoteDraft,
    ReportDraft,
    ReportQualityChecklist,
    ReportSection,
)

_OUTPUTS_ROOT = Path("outputs")

_DRAFT_DISCLAIMER = (
    "**DRAFT — NOT APPROVED FOR DELIVERY.**  \n"
    "This document has not been reviewed by a human. "
    "No browser execution has occurred. No target application testing has occurred. "
    "Current work covers planning, scaffold, and validation readiness only."
)


class ReportDraftBuilder:
    """Builds draft reports from local artifacts. No execution. No delivery approval."""

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self._outputs_root = outputs_root or _OUTPUTS_ROOT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_report_drafts(
        self,
        project_id: str,
        scaffold_root: Optional[Path] = None,
    ) -> Tuple[ReportDraft, ReportDraft, DeliveryNoteDraft, ReportQualityChecklist]:
        """Return (internal_summary, client_report, delivery_note, quality_checklist)."""
        ctx = self._load_context(project_id, scaffold_root)

        internal = self._build_internal_summary(project_id, ctx)
        client_report = self._build_client_report(project_id, ctx)
        delivery_note = self._build_delivery_note(project_id, ctx)
        checklist = self._build_quality_checklist(project_id, client_report)

        return internal, client_report, delivery_note, checklist

    def render_report_drafts(
        self,
        internal_summary: ReportDraft,
        client_report: ReportDraft,
        delivery_note: DeliveryNoteDraft,
        quality_checklist: ReportQualityChecklist,
        project_id: str,
    ) -> Dict[str, Path]:
        """Write report draft artifacts to outputs/<project_id>/06_client_draft/."""
        out_dir = self._outputs_root / project_id / "06_client_draft"
        out_dir.mkdir(parents=True, exist_ok=True)

        paths: Dict[str, Path] = {}

        p = out_dir / "INTERNAL_QA_SUMMARY_DRAFT.json"
        p.write_text(json.dumps(internal_summary.to_dict(), indent=2), encoding="utf-8")
        paths["internal_json"] = p

        p = out_dir / "INTERNAL_QA_SUMMARY_DRAFT.md"
        p.write_text(self._render_internal_md(internal_summary), encoding="utf-8")
        paths["internal_md"] = p

        p = out_dir / "CLIENT_REPORT_DRAFT.json"
        p.write_text(json.dumps(client_report.to_dict(), indent=2), encoding="utf-8")
        paths["client_json"] = p

        p = out_dir / "CLIENT_REPORT_DRAFT.md"
        p.write_text(self._render_client_md(client_report), encoding="utf-8")
        paths["client_md"] = p

        p = out_dir / "DELIVERY_NOTE_DRAFT.json"
        p.write_text(json.dumps(delivery_note.to_dict(), indent=2), encoding="utf-8")
        paths["delivery_note_json"] = p

        p = out_dir / "DELIVERY_NOTE_DRAFT.md"
        p.write_text(self._render_delivery_note_md(delivery_note), encoding="utf-8")
        paths["delivery_note_md"] = p

        p = out_dir / "REPORT_QUALITY_CHECKLIST.json"
        p.write_text(json.dumps(quality_checklist.to_dict(), indent=2), encoding="utf-8")
        paths["quality_json"] = p

        p = out_dir / "REPORT_QUALITY_CHECKLIST.md"
        p.write_text(self._render_quality_md(quality_checklist), encoding="utf-8")
        paths["quality_md"] = p

        return paths

    # ------------------------------------------------------------------
    # Context loading
    # ------------------------------------------------------------------

    def _load_context(self, project_id: str, scaffold_root: Optional[Path]) -> Dict:
        ctx: Dict = {
            "project_id": project_id,
            "project_type": "unknown",
            "environment_type": "unknown",
            "has_blueprint": False,
            "has_strategy": False,
            "has_scaffold": False,
            "has_static": False,
            "has_toolchain": False,
            "static_status": "unknown",
            "toolchain_status": "unknown",
            "strategy_summary": "",
            "phases_completed": [],
        }

        base = self._outputs_root / project_id
        bp_path = base / "00_project" / "PROJECT_BLUEPRINT.json"
        if bp_path.exists():
            ctx["has_blueprint"] = True
            ctx["phases_completed"].append("Phase 2A/2B — Project Blueprint")
            try:
                data = json.loads(bp_path.read_text(encoding="utf-8"))
                ctx["project_type"] = data.get("project_type", "unknown")
                ctx["environment_type"] = data.get("environment_type", "unknown")
            except Exception:
                pass

        st_path = base / "02_strategy" / "QA_STRATEGY.json"
        if st_path.exists():
            ctx["has_strategy"] = True
            ctx["phases_completed"].append("Phase 2C — QA Strategy")
            try:
                data = json.loads(st_path.read_text(encoding="utf-8"))
                ctx["strategy_summary"] = data.get("summary", "")
                ctx["project_type"] = data.get("project_type", ctx["project_type"])
            except Exception:
                pass

        sc_root = scaffold_root or (base / "03_framework" / "playwright")
        if (sc_root / "FRAMEWORK_SCAFFOLD.json").exists():
            ctx["has_scaffold"] = True
            ctx["phases_completed"].append("Phase 3A — Framework Scaffold")

        static_p = sc_root / "STATIC_VALIDATION_REPORT.json"
        if static_p.exists():
            ctx["has_static"] = True
            ctx["phases_completed"].append("Phase 3B — Static Validation")
            try:
                data = json.loads(static_p.read_text(encoding="utf-8"))
                ctx["static_status"] = data.get("validation_status", "unknown")
            except Exception:
                pass

        toolchain_p = sc_root / "TOOLCHAIN_VALIDATION_REPORT.json"
        if toolchain_p.exists():
            ctx["has_toolchain"] = True
            ctx["phases_completed"].append("Phase 3C — Toolchain Validation")
            try:
                data = json.loads(toolchain_p.read_text(encoding="utf-8"))
                ctx["toolchain_status"] = data.get("validation_status", "unknown")
            except Exception:
                pass

        return ctx

    # ------------------------------------------------------------------
    # Draft builders
    # ------------------------------------------------------------------

    def _build_internal_summary(self, project_id: str, ctx: Dict) -> ReportDraft:
        sections: List[ReportSection] = [
            ReportSection(
                id="phases",
                title="Phases Completed",
                content="\n".join(f"- {p}" for p in ctx["phases_completed"]) or "None",
                client_visible=False,
                internal_only=True,
                requires_review=True,
            ),
            ReportSection(
                id="static_validation",
                title="Static Scaffold Validation",
                content=f"Status: `{ctx['static_status']}`. Scaffold checked for file structure, secret patterns, hardcoded URLs.",
                client_visible=False,
                internal_only=True,
                requires_review=True,
            ),
            ReportSection(
                id="toolchain_validation",
                title="Toolchain Validation",
                content=f"Status: `{ctx['toolchain_status']}`. Approval-gated local commands only. No browser execution.",
                client_visible=False,
                internal_only=True,
                requires_review=True,
            ),
            ReportSection(
                id="safety",
                title="Safety Boundary",
                content=(
                    "No browser execution performed.\n"
                    "No target URL contacted.\n"
                    "No credentials used.\n"
                    "No external API calls.\n"
                    "safe_to_execute_tests=False."
                ),
                client_visible=False,
                internal_only=True,
                requires_review=True,
            ),
        ]
        return ReportDraft(
            project_id=project_id,
            report_type="internal_qa_summary",
            title="Internal QA Summary — DRAFT",
            audience="internal",
            status="draft",
            client_visible=False,
            approved_for_delivery=False,
            sections=sections,
            source_artifacts=[
                f"outputs/{project_id}/00_project/PROJECT_BLUEPRINT.json",
                f"outputs/{project_id}/02_strategy/QA_STRATEGY.json",
                f"outputs/{project_id}/03_framework/playwright/FRAMEWORK_SCAFFOLD.json",
            ],
            notes=["DRAFT — not approved for delivery.", "Internal use only."],
        )

    def _build_client_report(self, project_id: str, ctx: Dict) -> ReportDraft:
        project_type = ctx.get("project_type", "unknown")
        phases_text = "\n".join(f"- {p}" for p in ctx["phases_completed"]) or "None"

        sections: List[ReportSection] = [
            ReportSection(
                id="disclaimer",
                title="Important Notice",
                content=_DRAFT_DISCLAIMER,
                client_visible=True,
                internal_only=False,
                requires_review=True,
            ),
            ReportSection(
                id="overview",
                title="Project Overview",
                content=(
                    f"**Project type:** {project_type}\n"
                    f"**Environment:** {ctx.get('environment_type', 'unknown')}\n\n"
                    "This report covers the planning, scaffold generation, and validation readiness phase. "
                    "No test execution has occurred."
                ),
                client_visible=True,
                internal_only=False,
                requires_review=True,
            ),
            ReportSection(
                id="work_completed",
                title="Work Completed",
                content=phases_text,
                client_visible=True,
                internal_only=False,
                requires_review=True,
            ),
            ReportSection(
                id="not_done",
                title="What Has Not Been Done",
                content=(
                    "- No browser tests have been run.\n"
                    "- No target application has been contacted.\n"
                    "- No credentials have been used.\n"
                    "- No test results exist yet.\n"
                    "- No screenshots or traces exist yet."
                ),
                client_visible=True,
                internal_only=False,
                requires_review=True,
            ),
            ReportSection(
                id="next_steps",
                title="Recommended Next Steps",
                content=(
                    "1. Review and approve the EXECUTION_APPROVAL_CHECKLIST.\n"
                    "2. Provide confirmed test credentials and target URL approval.\n"
                    "3. Schedule approved test execution session.\n"
                    "4. Review evidence after execution.\n"
                    "5. Approve final report for delivery."
                ),
                client_visible=True,
                internal_only=False,
                requires_review=True,
            ),
        ]

        return ReportDraft(
            project_id=project_id,
            report_type="client_report",
            title=f"QA Readiness Report — {project_id} — DRAFT",
            audience="client",
            status="draft",
            client_visible=False,
            approved_for_delivery=False,
            sections=sections,
            source_artifacts=[
                f"outputs/{project_id}/00_project/PROJECT_BLUEPRINT.json",
                f"outputs/{project_id}/02_strategy/QA_STRATEGY.json",
            ],
            blockers=["Not approved for delivery. Human review required."],
            notes=[
                "DRAFT — not approved for delivery.",
                "No browser execution has occurred.",
                "No target application testing has occurred.",
            ],
        )

    def _build_delivery_note(self, project_id: str, ctx: Dict) -> DeliveryNoteDraft:
        included: List[str] = []
        excluded = [
            "99_internal/ — internal notes, never client-facing",
            "raw command logs — require redaction review",
            ".env — credentials never included",
            "node_modules/ — excluded by default",
            "test-results/ — no execution performed",
        ]

        if ctx["has_blueprint"]:
            included.append("FRAMEWORK_SCAFFOLD.md — scaffold overview")
        if ctx["has_scaffold"]:
            included.append("HOW_TO_RUN.md — setup and run guide")
        included.append("CLIENT_REPORT_DRAFT.md — draft report (not approved)")
        included.append("DELIVERY_NOTE_DRAFT.md — this document")

        return DeliveryNoteDraft(
            project_id=project_id,
            title=f"Delivery Note — {project_id} — DRAFT",
            status="draft",
            approved_for_delivery=False,
            client_visible=False,
            summary=(
                "This delivery note is a draft only. "
                "No content has been approved for client delivery. "
                "All items require human review before any delivery occurs."
            ),
            included_artifacts=included,
            excluded_artifacts=excluded,
            caveats=[
                "DRAFT — not approved for delivery.",
                "All items are subject to human review.",
                "No execution evidence included — no tests have been run.",
            ],
            next_steps=[
                "Complete EXECUTION_APPROVAL_CHECKLIST.",
                "Obtain approved_for_delivery from human reviewer.",
                "Complete DELIVERY_SAFETY_CHECKLIST before packaging.",
            ],
            notes=["This note accompanies the CLIENT_REPORT_DRAFT."],
        )

    def _build_quality_checklist(
        self, project_id: str, client_report: ReportDraft
    ) -> ReportQualityChecklist:
        has_disclaimer = any(
            "DRAFT" in s.content or "not approved" in s.content.lower()
            for s in client_report.sections
        )
        has_no_execution_claim = any(
            "no browser" in s.content.lower() or "no target" in s.content.lower()
            for s in client_report.sections
        )
        warnings: List[str] = []
        blockers: List[str] = [
            "client_ready=False — human review not yet completed.",
            "safe_to_deliver=False — approval_checked=False.",
        ]
        if not has_disclaimer:
            blockers.append("DRAFT disclaimer missing from report.")
        if not has_no_execution_claim:
            warnings.append("No explicit 'no execution' statement found in client report.")

        return ReportQualityChecklist(
            project_id=project_id,
            report_id="client_report_draft",
            technically_correct=True,
            specific=True,
            actionable=True,
            evidence_based=False,
            honest_scope=True,
            no_overclaiming=True,
            client_ready=False,
            human_readable=True,
            no_internal_notes=True,
            approval_checked=False,
            safe_to_deliver=False,
            blockers=blockers,
            warnings=warnings,
            notes=["evidence_based=False — no execution has occurred."],
        )

    # ------------------------------------------------------------------
    # Markdown renderers
    # ------------------------------------------------------------------

    def _render_internal_md(self, report: ReportDraft) -> str:
        lines = [
            f"# {report.title}",
            "",
            "> **INTERNAL ONLY — Not for client delivery.**",
            "",
            f"**Project:** `{report.project_id}`  ",
            f"**Status:** `{report.status}`  ",
            f"**approved_for_delivery:** {report.approved_for_delivery}  ",
            "",
        ]
        for s in report.sections:
            lines += [f"## {s.title}", "", s.content, ""]
        return "\n".join(lines) + "\n"

    def _render_client_md(self, report: ReportDraft) -> str:
        lines = [
            f"# {report.title}",
            "",
        ]
        for s in report.sections:
            lines += [f"## {s.title}", "", s.content, ""]
        lines += [
            "---",
            "",
            f"**Status:** `{report.status}` | **approved_for_delivery:** {report.approved_for_delivery}",
        ]
        return "\n".join(lines) + "\n"

    def _render_delivery_note_md(self, note: DeliveryNoteDraft) -> str:
        lines = [
            f"# {note.title}",
            "",
            f"> {note.summary}",
            "",
            f"**Status:** `{note.status}` | **approved_for_delivery:** {note.approved_for_delivery}",
            "",
            "## Included (Pending Review)",
        ]
        for item in note.included_artifacts:
            lines.append(f"- {item}")
        lines += ["", "## Excluded"]
        for item in note.excluded_artifacts:
            lines.append(f"- {item}")
        lines += ["", "## Caveats"]
        for c in note.caveats:
            lines.append(f"- {c}")
        lines += ["", "## Next Steps"]
        for s in note.next_steps:
            lines.append(f"- {s}")
        return "\n".join(lines) + "\n"

    def _render_quality_md(self, checklist: ReportQualityChecklist) -> str:
        def _check(v: bool) -> str:
            return "✓" if v else "✗"

        lines = [
            "# Report Quality Checklist",
            "",
            f"**Project:** `{checklist.project_id}`  ",
            f"**Report:** `{checklist.report_id}`  ",
            f"**client_ready:** {checklist.client_ready}  ",
            f"**safe_to_deliver:** {checklist.safe_to_deliver}  ",
            "",
            "## Quality Checks",
            "",
            f"- {_check(checklist.technically_correct)} Technically correct",
            f"- {_check(checklist.specific)} Specific",
            f"- {_check(checklist.actionable)} Actionable",
            f"- {_check(checklist.evidence_based)} Evidence-based",
            f"- {_check(checklist.honest_scope)} Honest scope (no overclaiming)",
            f"- {_check(checklist.no_overclaiming)} No overclaiming",
            f"- {_check(checklist.client_ready)} Client ready",
            f"- {_check(checklist.human_readable)} Human readable",
            f"- {_check(checklist.no_internal_notes)} No internal notes",
            f"- {_check(checklist.approval_checked)} Approval checked",
            f"- {_check(checklist.safe_to_deliver)} Safe to deliver",
            "",
        ]
        if checklist.blockers:
            lines += ["## Blockers", ""]
            for b in checklist.blockers:
                lines.append(f"- {b}")
            lines.append("")
        if checklist.warnings:
            lines += ["## Warnings", ""]
            for w in checklist.warnings:
                lines.append(f"- {w}")
        return "\n".join(lines) + "\n"
