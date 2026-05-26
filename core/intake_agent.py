"""
Phase 5K — Intake Agent.

Heuristic classifier for incoming work requests.
Raw input text is NEVER stored in any artifact — only derived metadata
(length, classification, confidence) appears in output.

Architecture note:
- Heuristic mode (Phase 5K): pure keyword matching, no LLM calls.
- LLM-enhanced mode (Phase 5L): optional orchestrator integration.
- Does NOT replace WorkbenchController (Phase 2A intake classification).
  IntakeAgent focuses on free-text requirements analysis for test planning.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

from core.schemas.intake import IntakeClassification, IntakeReport

_OUTPUTS_ROOT = Path("outputs")

# ---------------------------------------------------------------------------
# Classification rules (keyword → classification)
# ---------------------------------------------------------------------------

_CLASSIFICATION_KEYWORDS: Dict[str, List[str]] = {
    "auth_testing": [
        "login", "auth", "authentication", "password", "session",
        "logout", "signin", "sign in", "oauth", "sso", "token",
        "credentials", "jwt", "2fa", "mfa",
    ],
    "api_testing": [
        "api", "endpoint", "rest", "graphql", "http", "request",
        "response", "swagger", "openapi", "webhook", "status code",
        "json response", "xml response",
    ],
    "mobile_testing": [
        "mobile", "ios", "android", "responsive", "viewport",
        "touch", "swipe", "tablet", "smartphone", "small screen",
    ],
    "database_testing": [
        "database", "sql", "query", "table", "record", "row",
        "postgresql", "mysql", "mongodb", "migration", " db ",
        "schema", "column",
    ],
    "visual_testing": [
        "visual", "screenshot", "pixel", "regression", "baseline",
        "layout rendering", "ui diff", "appearance", "visual diff",
    ],
    "performance_testing": [
        "performance", "load test", "latency", "response time",
        "throughput", "stress test", "benchmark", "scalability",
        "concurrent users",
    ],
    "security_testing": [
        "security", "vulnerability", "xss", "injection", "csrf",
        "penetration", "owasp", "exploit", "pentest", "attack",
    ],
    "functional_testing": [
        "functional", "user story", "acceptance", "workflow",
        "scenario", "feature test", "e2e", "end-to-end",
    ],
}

_RISK_KEYWORDS: Dict[str, List[str]] = {
    "critical": [
        "payment", "checkout", "financial", "banking",
        "health record", "medical", "billing", "transaction",
    ],
    "high": [
        "auth", "login", "password", "security", "database",
        "migration", "admin", "production data",
    ],
    "low": [
        "read-only", "view only", "display", "search results",
        "static page", "public page",
    ],
}

_MODULE_RECOMMENDATIONS: Dict[str, List[str]] = {
    "auth_testing": ["browser", "google_auth", "github_auth"],
    "api_testing": ["api_smoke"],
    "mobile_testing": ["mobile_viewport"],
    "database_testing": ["db_smoke"],
    "visual_testing": ["visual_regression"],
    "performance_testing": [],  # deferred to Phase 5N
    "security_testing": [],  # deferred to Phase 5N
    "functional_testing": ["browser", "api_smoke"],
    "unknown": ["browser"],
}


class IntakeAgent:
    """Heuristic intake agent — classifies work requests without LLM calls."""

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self._outputs_root = outputs_root or _OUTPUTS_ROOT

    def analyze(self, raw_input: str, project_id: str) -> IntakeReport:
        """Classify raw_input. Raw text is never stored in artifacts."""
        if not project_id:
            report = IntakeReport(project_id=project_id)
            report.blockers.append("project_id is required")
            return report

        if not raw_input or not raw_input.strip():
            report = IntakeReport(project_id=project_id)
            report.blockers.append("raw_input is empty — nothing to analyze")
            return report

        text_lower = raw_input.lower()
        classification = self._classify(text_lower)

        report = IntakeReport(
            project_id=project_id,
            raw_input_length=len(raw_input),
            intake_mode="heuristic",
            classification=classification,
        )

        if classification.classification == "unknown":
            report.notes.append(
                "Classification is 'unknown' — consider providing more specific requirements."
            )
        if not classification.recommended_modules:
            report.notes.append(
                "No modules recommended for this classification in Phase 5K. "
                "Performance and security testing are deferred to Phase 5N."
            )

        return report

    def _classify(self, text_lower: str) -> IntakeClassification:
        scores: Dict[str, float] = {}
        matched: Dict[str, List[str]] = {}

        for cls, keywords in _CLASSIFICATION_KEYWORDS.items():
            hits = [kw for kw in keywords if kw in text_lower]
            if hits:
                scores[cls] = len(hits) / len(keywords)
                matched[cls] = hits

        risk_level = "medium"
        for level in ("critical", "high", "low"):
            if any(kw in text_lower for kw in _RISK_KEYWORDS.get(level, [])):
                risk_level = level
                break

        if not scores:
            return IntakeClassification(
                classification="unknown",
                confidence=0.0,
                risk_level=risk_level,
            )

        top_cls = max(scores, key=lambda k: scores[k])
        # Scale confidence: 1 keyword hit → ~0.1, 3 hits → ~0.6+, cap at 1.0
        confidence = min(scores[top_cls] * 3.0, 1.0)
        secondary = sorted(
            [c for c in scores if c != top_cls and scores[c] >= 0.05],
            key=lambda c: scores[c],
            reverse=True,
        )[:3]

        return IntakeClassification(
            classification=top_cls,
            confidence=round(confidence, 3),
            evidence_keywords=matched.get(top_cls, [])[:10],
            risk_level=risk_level,
            recommended_modules=list(_MODULE_RECOMMENDATIONS.get(top_cls, [])),
            secondary_classifications=secondary,
        )

    def render_artifacts(
        self, report: IntakeReport, project_id: str
    ) -> Dict[str, Path]:
        """Write artifacts to outputs/<project_id>/22_intake/."""
        out_dir = self._outputs_root / project_id / "22_intake"
        out_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(timezone.utc).isoformat()
        payload: dict = {
            "schema_version": "5K.1",
            "generated_at": ts,
            **report.to_dict(),
        }

        json_path = out_dir / "INTAKE_REPORT.json"
        json_path.write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )

        md_path = out_dir / "INTAKE_REPORT.md"
        md_path.write_text(self._render_md(report, ts), encoding="utf-8")

        return {"json": json_path, "md": md_path}

    def _render_md(self, report: IntakeReport, ts: str) -> str:
        c = report.classification
        lines = [
            "# Intake Analysis Report",
            "",
            f"**Project:** {report.project_id}",
            f"**Generated:** {ts}",
            f"**Mode:** {report.intake_mode}",
            f"**Input length:** {report.raw_input_length} chars",
            "",
            "## Classification",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| Classification | `{c.classification}` |",
            f"| Confidence | {c.confidence:.1%} |",
            f"| Risk level | `{c.risk_level}` |",
        ]
        if c.recommended_modules:
            lines.append(f"| Recommended modules | {', '.join(c.recommended_modules)} |")
        if c.secondary_classifications:
            lines.append(
                f"| Secondary classifications | {', '.join(c.secondary_classifications)} |"
            )
        if c.evidence_keywords:
            lines += ["", f"**Evidence keywords:** {', '.join(c.evidence_keywords)}"]
        if report.blockers:
            lines += ["", "## Blockers", ""]
            for b in report.blockers:
                lines.append(f"- {b}")
        if report.notes:
            lines += ["", "## Notes", ""]
            for n in report.notes:
                lines.append(f"- {n}")
        lines += [
            "",
            "---",
            "",
            "**SAFETY:** `raw_input_stored=False` | `credentials_in_output=False` | "
            "`safe_to_deliver=False` | `human_review_required=True`",
        ]
        return "\n".join(lines) + "\n"
