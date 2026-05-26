"""
Phase 5K — Evidence Intelligence.

Static analysis of existing evidence artifacts under outputs/<project_id>/.
Identifies coverage gaps, computes a coverage score, and generates recommendations.
Read-only: no subprocess calls, no network calls, no execution.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from core.schemas.evidence_intelligence import (
    EVIDENCE_ARTIFACT_DIR_MAP,
    EvidenceCoverageItem,
    EvidenceGap,
    EvidenceIntelligenceReport,
)

_OUTPUTS_ROOT = Path("outputs")

# Gap descriptions and recommendations per area
_GAP_INFO: Dict[str, tuple] = {
    "auth": (
        "high",
        "No dedicated auth execution artifacts found.",
        "Run run_dedicated_auth.py to capture auth evidence.",
    ),
    "api": (
        "medium",
        "No API smoke artifacts found.",
        "Run run_api_auth_smoke.py to capture API evidence.",
    ),
    "qa_report": (
        "medium",
        "No QA evidence report found.",
        "Run generate_qa_report.py to aggregate evidence.",
    ),
    "mobile": (
        "low",
        "No mobile viewport artifacts found.",
        "Run run_mobile_viewport_smoke.py for mobile evidence.",
    ),
    "visual": (
        "low",
        "No visual regression artifacts found.",
        "Run run_visual_regression.py to capture baselines.",
    ),
    "database": (
        "medium",
        "No database smoke artifacts found.",
        "Run run_db_smoke.py to validate DB connectivity.",
    ),
    "pipeline": (
        "low",
        "No E2E pipeline run artifacts found.",
        "Run run_e2e_pipeline.py to generate pipeline evidence.",
    ),
    "task_source": (
        "low",
        "No task source artifacts found.",
        "Run run_task_source_fetch.py to link requirements.",
    ),
    "intake": (
        "low",
        "No intake analysis artifacts found.",
        "Run run_intake_agent.py to classify requirements.",
    ),
    "test_oracle": (
        "low",
        "No test oracle artifacts found.",
        "Run run_test_oracle.py to generate test scenarios.",
    ),
    "google_auth": (
        "low",
        "No Google OAuth artifacts found.",
        "Run run_google_auth_smoke.py if Google auth is needed.",
    ),
    "github_auth": (
        "low",
        "No GitHub OAuth artifacts found.",
        "Run run_github_auth_smoke.py if GitHub auth is needed.",
    ),
}


class EvidenceIntelligence:
    """Static evidence gap analyzer — read-only, no execution."""

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self._outputs_root = outputs_root or _OUTPUTS_ROOT

    def analyze(
        self,
        project_id: str,
        areas_to_check: Optional[List[str]] = None,
    ) -> EvidenceIntelligenceReport:
        """Analyze artifact dirs for project_id and report coverage gaps."""
        if not project_id:
            report = EvidenceIntelligenceReport(project_id=project_id)
            report.blockers.append("project_id is required")
            return report

        project_dir = self._outputs_root / project_id
        if not project_dir.exists():
            report = EvidenceIntelligenceReport(project_id=project_id)
            report.notes.append(
                f"Project directory '{project_dir}' does not exist — no artifacts to analyze."
            )
            report.overall_coverage_score = 0.0
            return report

        check_areas = areas_to_check or list(EVIDENCE_ARTIFACT_DIR_MAP.keys())
        coverage_items: List[EvidenceCoverageItem] = []
        gaps: List[EvidenceGap] = []

        for area in check_areas:
            artifact_dir = EVIDENCE_ARTIFACT_DIR_MAP.get(area, "")
            if not artifact_dir:
                continue
            area_path = project_dir / artifact_dir
            present = area_path.exists()
            artifact_count = (
                len([f for f in area_path.iterdir() if f.is_file()])
                if present
                else 0
            )
            coverage_items.append(
                EvidenceCoverageItem(
                    area=area,
                    artifact_dir=str(area_path),
                    present=present,
                    artifact_count=artifact_count,
                )
            )
            if not present:
                gap_info = _GAP_INFO.get(area)
                if gap_info:
                    severity, description, recommendation = gap_info
                    gaps.append(
                        EvidenceGap(
                            area=area,
                            severity=severity,
                            description=description,
                            recommendation=recommendation,
                            missing_artifact_dir=str(area_path),
                        )
                    )

        present_count = sum(1 for c in coverage_items if c.present)
        total = len(coverage_items)
        score = round(present_count / total, 3) if total > 0 else 0.0

        high_count = sum(
            1 for g in gaps if g.severity in ("high", "critical")
        )

        recommendations = list(
            {g.recommendation for g in gaps if g.severity in ("high", "critical")}
        )
        recommendations += list(
            {g.recommendation for g in gaps if g.severity == "medium"}
        )

        report = EvidenceIntelligenceReport(
            project_id=project_id,
            gaps=gaps,
            coverage_items=coverage_items,
            overall_coverage_score=score,
            high_severity_gap_count=high_count,
            recommendations=recommendations,
        )

        if score == 1.0:
            report.notes.append("Full coverage — all checked artifact areas are present.")
        elif score == 0.0:
            report.notes.append(
                "No coverage found — project directory exists but no artifact directories are present."
            )

        return report

    def render_artifacts(
        self, report: EvidenceIntelligenceReport, project_id: str
    ) -> Dict[str, Path]:
        """Write artifacts to outputs/<project_id>/24_evidence_intelligence/."""
        out_dir = self._outputs_root / project_id / "24_evidence_intelligence"
        out_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(timezone.utc).isoformat()
        payload: dict = {
            "schema_version": "5K.1",
            "generated_at": ts,
            **report.to_dict(),
        }

        json_path = out_dir / "EVIDENCE_INTELLIGENCE_REPORT.json"
        json_path.write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )

        md_path = out_dir / "EVIDENCE_INTELLIGENCE_REPORT.md"
        md_path.write_text(self._render_md(report, ts), encoding="utf-8")

        return {"json": json_path, "md": md_path}

    def _render_md(self, report: EvidenceIntelligenceReport, ts: str) -> str:
        lines = [
            "# Evidence Intelligence Report",
            "",
            f"**Project:** {report.project_id}",
            f"**Generated:** {ts}",
            f"**Coverage score:** {report.overall_coverage_score:.1%}",
            f"**High-severity gaps:** {report.high_severity_gap_count}",
            "",
            "## Coverage Summary",
            "",
            "| Area | Present | Artifacts |",
            "|---|---|---|",
        ]
        for item in report.coverage_items:
            status = "YES" if item.present else "NO"
            lines.append(f"| {item.area} | {status} | {item.artifact_count} |")
        if report.gaps:
            lines += ["", "## Gaps", "", "| Area | Severity | Description |", "|---|---|---|"]
            for gap in sorted(report.gaps, key=lambda g: ("low", "medium", "high", "critical").index(g.severity), reverse=True):
                lines.append(f"| {gap.area} | {gap.severity} | {gap.description} |")
        if report.recommendations:
            lines += ["", "## Recommendations", ""]
            for r in report.recommendations:
                lines.append(f"- {r}")
        if report.notes:
            lines += ["", "## Notes", ""]
            for n in report.notes:
                lines.append(f"- {n}")
        lines += [
            "",
            "---",
            "",
            "**SAFETY:** `network_calls_made=False` | `execution_performed=False` | "
            "`safe_to_deliver=False` | `human_review_required=True`",
        ]
        return "\n".join(lines) + "\n"
