"""Delivery Preview Builder — Phase 4C.

Inspects local artifacts and builds:
- DeliveryPackagePreview (manifest of what would go into future delivery)
- DeliverySafetyChecklist

SAFETY: No zip/package creation. approved_for_delivery=False. safe_to_package=False.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional, Tuple

from core.schemas.delivery_preview import (
    DeliveryPackagePreview,
    DeliveryPreviewItem,
    DeliverySafetyChecklist,
)

_OUTPUTS_ROOT = Path("outputs")

_ALWAYS_EXCLUDED = {
    "99_internal",
    ".env",
    "node_modules",
    "test-results",
    "__pycache__",
}


class DeliveryPreviewBuilder:
    """Builds delivery preview manifest. No packages, no zips, no approval."""

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self._outputs_root = outputs_root or _OUTPUTS_ROOT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_delivery_preview(
        self,
        project_id: str,
        scaffold_root: Optional[Path] = None,
    ) -> Tuple[DeliveryPackagePreview, DeliverySafetyChecklist]:
        """Inspect local artifacts and return (preview, safety_checklist)."""
        ctx = self._inspect_artifacts(project_id, scaffold_root)
        preview = self._build_preview(project_id, ctx)
        checklist = self._build_safety_checklist(project_id, ctx)
        return preview, checklist

    def render_delivery_preview_artifacts(
        self,
        preview: DeliveryPackagePreview,
        checklist: DeliverySafetyChecklist,
        project_id: str,
    ) -> Dict[str, Path]:
        """Write preview artifacts to outputs/<project_id>/06_client_draft/."""
        out_dir = self._outputs_root / project_id / "06_client_draft"
        out_dir.mkdir(parents=True, exist_ok=True)

        paths: Dict[str, Path] = {}

        p = out_dir / "DELIVERY_PACKAGE_PREVIEW.json"
        p.write_text(json.dumps(preview.to_dict(), indent=2), encoding="utf-8")
        paths["preview_json"] = p

        p = out_dir / "DELIVERY_PACKAGE_PREVIEW.md"
        p.write_text(self._render_preview_md(preview), encoding="utf-8")
        paths["preview_md"] = p

        p = out_dir / "DELIVERY_SAFETY_CHECKLIST.json"
        p.write_text(json.dumps(checklist.to_dict(), indent=2), encoding="utf-8")
        paths["safety_json"] = p

        p = out_dir / "DELIVERY_SAFETY_CHECKLIST.md"
        p.write_text(self._render_safety_md(checklist), encoding="utf-8")
        paths["safety_md"] = p

        return paths

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def _inspect_artifacts(self, project_id: str, scaffold_root: Optional[Path]) -> Dict:
        ctx: Dict = {
            "include_items": [],
            "exclude_items": [],
            "has_no_secrets": True,
            "has_scaffold": False,
        }

        base = self._outputs_root / project_id
        sc_root = scaffold_root or (base / "03_framework" / "playwright")

        def _candidate(path: Path, title: str, artifact_type: str, reason: str) -> DeliveryPreviewItem:
            return DeliveryPreviewItem(
                id=f"item_{len(ctx['include_items']) + len(ctx['exclude_items']) + 1:03d}",
                path=str(path),
                title=title,
                artifact_type=artifact_type,
                include_in_preview=True,
                client_visible=False,
                requires_redaction=True,
                approved_for_delivery=False,
                reason=reason,
            )

        def _exclude(path: Path, title: str, artifact_type: str, reason: str) -> DeliveryPreviewItem:
            return DeliveryPreviewItem(
                id=f"excl_{len(ctx['exclude_items']) + 1:03d}",
                path=str(path),
                title=title,
                artifact_type=artifact_type,
                include_in_preview=False,
                client_visible=False,
                requires_redaction=True,
                approved_for_delivery=False,
                reason=reason,
            )

        # Candidates for inclusion
        draft_dir = base / "06_client_draft"
        for filename, title, art_type in [
            ("CLIENT_REPORT_DRAFT.md", "Client Report Draft", "client_report"),
            ("DELIVERY_NOTE_DRAFT.md", "Delivery Note Draft", "delivery_note"),
            ("EVIDENCE_MANIFEST.md", "Evidence Manifest", "evidence_manifest"),
        ]:
            p = draft_dir / filename
            ctx["include_items"].append(
                _candidate(p, title, art_type, "Draft candidate for client delivery after review.")
            )

        for filename, title, art_type in [
            ("FRAMEWORK_SCAFFOLD.md", "Scaffold Overview", "scaffold_metadata"),
            ("HOW_TO_RUN.md", "How To Run Guide", "how_to_run"),
            ("docs/TEST_STRATEGY.md", "Test Strategy", "strategy_doc"),
        ]:
            p = sc_root / filename
            if p.exists():
                ctx["has_scaffold"] = True
                ctx["include_items"].append(
                    _candidate(p, title, art_type, "Scaffold artifact — requires review before delivery.")
                )

        # Always excluded
        for path_str, title, reason in [
            ("99_internal/", "Internal notes directory", "Internal content — never client-facing."),
            (".env", "Environment secrets file", "Contains credentials — never included."),
            ("node_modules/", "Node modules", "Build artifact — excluded by default."),
            ("test-results/", "Test results directory", "No execution performed; excluded."),
            ("TOOLCHAIN_COMMAND_LOG.md", "Toolchain command log", "Raw logs require redaction before delivery."),
        ]:
            ctx["exclude_items"].append(
                _exclude(sc_root / path_str, title, "internal", reason)
            )

        return ctx

    def _build_preview(self, project_id: str, ctx: Dict) -> DeliveryPackagePreview:
        return DeliveryPackagePreview(
            project_id=project_id,
            preview_status="draft",
            package_name=f"{project_id}-delivery-preview",
            package_created=False,
            zip_created=False,
            approved_for_delivery=False,
            items=ctx["include_items"],
            excluded_items=ctx["exclude_items"],
            blockers=[
                "approved_for_delivery=False — human approval required before packaging.",
                "No execution evidence exists — tests have not been run.",
                "Redaction review required for all included items.",
            ],
            warnings=["All items are draft candidates only — not approved for delivery."],
            notes=[
                "Preview only. No zip or package has been created.",
                "No files have been copied or archived.",
            ],
        )

    def _build_safety_checklist(
        self, project_id: str, ctx: Dict
    ) -> DeliverySafetyChecklist:
        return DeliverySafetyChecklist(
            project_id=project_id,
            no_secrets=ctx.get("has_no_secrets", False),
            redaction_complete=False,
            client_approval_present=False,
            evidence_reviewed=False,
            reports_reviewed=False,
            internal_notes_removed=False,
            approved_for_delivery=False,
            safe_to_package=False,
            blockers=[
                "safe_to_package=False — delivery safety checklist not complete.",
                "Redaction not confirmed.",
                "Human approval not present.",
                "No execution evidence — tests have not been run.",
            ],
            warnings=["All artifact candidates require human review before any delivery."],
            notes=["Complete this checklist before creating any delivery package."],
        )

    # ------------------------------------------------------------------
    # Markdown renderers
    # ------------------------------------------------------------------

    def _render_preview_md(self, preview: DeliveryPackagePreview) -> str:
        lines = [
            "# Delivery Package Preview",
            "",
            "> **PREVIEW ONLY — No package has been created.**  ",
            "> approved_for_delivery=False. No zip or archive exists.",
            "",
            f"**Project:** `{preview.project_id}`  ",
            f"**Package name:** `{preview.package_name}`  ",
            f"**package_created:** {preview.package_created}  ",
            f"**zip_created:** {preview.zip_created}  ",
            f"**approved_for_delivery:** {preview.approved_for_delivery}  ",
            "",
            "## Candidate Items (Pending Review)",
            "",
            "| # | Title | Type | Approved? |",
            "|---|---|---|---|",
        ]
        for item in preview.items:
            lines.append(f"| {item.id} | {item.title} | {item.artifact_type} | {item.approved_for_delivery} |")
        lines += [
            "",
            "## Excluded Items",
            "",
            "| # | Title | Reason |",
            "|---|---|---|",
        ]
        for item in preview.excluded_items:
            lines.append(f"| {item.id} | {item.title} | {item.reason} |")
        lines += ["", "## Blockers", ""]
        for b in preview.blockers:
            lines.append(f"- {b}")
        lines += ["", "## Notes", ""]
        for n in preview.notes:
            lines.append(f"- {n}")
        return "\n".join(lines) + "\n"

    def _render_safety_md(self, checklist: DeliverySafetyChecklist) -> str:
        def _check(v: bool) -> str:
            return "✓" if v else "✗"

        lines = [
            "# Delivery Safety Checklist",
            "",
            f"**Project:** `{checklist.project_id}`  ",
            f"**safe_to_package:** {checklist.safe_to_package}  ",
            f"**approved_for_delivery:** {checklist.approved_for_delivery}  ",
            "",
            "## Checks",
            "",
            f"- {_check(checklist.no_secrets)} No secrets in artifacts",
            f"- {_check(checklist.redaction_complete)} Redaction complete",
            f"- {_check(checklist.client_approval_present)} Client approval present",
            f"- {_check(checklist.evidence_reviewed)} Evidence reviewed",
            f"- {_check(checklist.reports_reviewed)} Reports reviewed",
            f"- {_check(checklist.internal_notes_removed)} Internal notes removed",
            f"- {_check(checklist.approved_for_delivery)} Approved for delivery",
            f"- {_check(checklist.safe_to_package)} Safe to package",
            "",
        ]
        if checklist.blockers:
            lines += ["## Blockers", ""]
            for b in checklist.blockers:
                lines.append(f"- {b}")
        return "\n".join(lines) + "\n"
