"""
Phase 5K — Test Oracle.

Heuristic test scenario generator. Given an IntakeReport (or raw text),
produces a prioritized list of TestScenarios with risk scores.

Heuristic mode (Phase 5K): template-based, no LLM calls.
LLM-enhanced mode (Phase 5L): optional orchestrator integration.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.schemas.intake import IntakeReport
from core.schemas.test_oracle import TestOracleReport, TestScenario

_OUTPUTS_ROOT = Path("outputs")

# ---------------------------------------------------------------------------
# Scenario templates: classification → [(name, priority, risk_score, tags)]
# ---------------------------------------------------------------------------

_SCENARIO_TEMPLATES: Dict[str, List[Tuple[str, int, float, List[str]]]] = {
    "auth_testing": [
        ("Login with valid credentials succeeds", 1, 0.90, ["login", "positive"]),
        ("Login rejects invalid credentials", 1, 0.95, ["login", "negative", "security"]),
        ("Session persists after successful login", 2, 0.70, ["session"]),
        ("Logout clears the session", 2, 0.80, ["logout", "security"]),
        ("Password reset flow completes successfully", 2, 0.75, ["password-reset"]),
    ],
    "api_testing": [
        ("Valid request returns expected 2xx response", 1, 0.80, ["positive", "http"]),
        ("Missing required fields returns 4xx error", 1, 0.85, ["negative", "validation"]),
        ("Response schema matches contract", 2, 0.70, ["contract", "schema"]),
        ("Unauthenticated requests to protected endpoints return 401", 1, 0.90, ["auth", "security"]),
        ("Repeated requests return consistent results", 3, 0.55, ["idempotency"]),
    ],
    "mobile_testing": [
        ("Layout renders correctly on mobile viewport", 1, 0.80, ["layout", "mobile"]),
        ("Navigation works on small screen", 1, 0.75, ["navigation", "mobile"]),
        ("Touch interactions respond correctly", 2, 0.70, ["touch", "interaction"]),
        ("Content is readable without horizontal scrolling", 2, 0.65, ["layout", "readability"]),
    ],
    "database_testing": [
        ("Target table is accessible and returns rows", 1, 0.85, ["connectivity", "read"]),
        ("Row count is within expected range", 2, 0.70, ["data-integrity"]),
        ("Required columns are present in schema", 2, 0.75, ["schema", "structure"]),
        ("Read-only query completes within timeout", 2, 0.65, ["performance"]),
    ],
    "visual_testing": [
        ("Baseline screenshots are captured successfully", 1, 0.80, ["baseline"]),
        ("No unexpected pixel differences from baseline", 1, 0.90, ["regression"]),
        ("Layout is consistent across viewport sizes", 2, 0.75, ["responsive"]),
    ],
    "performance_testing": [
        ("Response time under normal load is within SLA", 1, 0.80, ["performance", "sla"]),
        ("System handles expected concurrent users", 2, 0.75, ["load", "concurrency"]),
    ],
    "security_testing": [
        ("Input fields reject XSS payloads", 1, 0.95, ["xss", "security"]),
        ("SQL injection attempts are blocked", 1, 0.95, ["injection", "security"]),
        ("Sensitive data is not exposed in responses", 1, 0.90, ["data-exposure", "security"]),
    ],
    "functional_testing": [
        ("Core user workflow completes end-to-end", 1, 0.85, ["e2e", "workflow"]),
        ("Form validation provides appropriate feedback", 2, 0.70, ["validation", "ui"]),
        ("Navigation between views works correctly", 2, 0.65, ["navigation"]),
        ("Error states are handled gracefully", 2, 0.75, ["error-handling"]),
    ],
    "unknown": [
        ("Smoke test: application loads successfully", 1, 0.70, ["smoke"]),
        ("Core features are accessible", 2, 0.60, ["smoke", "general"]),
    ],
}

# Scenarios that are deferred to future phases — still surfaced but marked deferred
_DEFERRED_SCENARIOS: Dict[str, List[Tuple[str, str]]] = {
    "performance_testing": [
        ("Load test with 1000+ concurrent users", "Full load testing deferred to Phase 5N"),
        ("Stress test to find breaking point", "Stress testing deferred to Phase 5N"),
    ],
    "security_testing": [
        ("Automated penetration test scan", "Pen testing deferred to Phase 5N"),
        ("Dependency vulnerability scan", "Dep scanning deferred to Phase 5N"),
    ],
}

# Map classification → coverage area label
_CLASSIFICATION_TO_AREA: Dict[str, str] = {
    "auth_testing": "auth",
    "api_testing": "api",
    "mobile_testing": "mobile",
    "database_testing": "database",
    "visual_testing": "visual",
    "performance_testing": "performance",
    "security_testing": "security",
    "functional_testing": "functional",
    "unknown": "general",
}


class TestOracle:
    """Heuristic test scenario generator."""

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self._outputs_root = outputs_root or _OUTPUTS_ROOT

    def generate(
        self, intake_report: IntakeReport, project_id: str
    ) -> TestOracleReport:
        """Generate scenarios from a completed IntakeReport."""
        if not project_id:
            report = TestOracleReport(project_id=project_id)
            report.blockers.append("project_id is required")
            return report

        if intake_report.blockers:
            report = TestOracleReport(project_id=project_id)
            report.blockers.append(
                "IntakeReport has blockers — cannot generate scenarios: "
                + "; ".join(intake_report.blockers[:3])
            )
            return report

        cls = intake_report.classification.classification
        return self._generate_from_classification(cls, project_id)

    def generate_from_classification(
        self, classification: str, project_id: str
    ) -> TestOracleReport:
        """Generate scenarios directly from a classification string."""
        if not project_id:
            report = TestOracleReport(project_id=project_id)
            report.blockers.append("project_id is required")
            return report
        return self._generate_from_classification(classification, project_id)

    def _generate_from_classification(
        self, classification: str, project_id: str
    ) -> TestOracleReport:
        templates = _SCENARIO_TEMPLATES.get(
            classification, _SCENARIO_TEMPLATES["unknown"]
        )
        scenarios = [
            TestScenario(
                name=name,
                coverage_area=_CLASSIFICATION_TO_AREA.get(classification, "general"),
                priority=priority,
                risk_score=risk_score,
                tags=list(tags),
            )
            for name, priority, risk_score, tags in templates
        ]

        deferred_templates = _DEFERRED_SCENARIOS.get(classification, [])
        deferred = [
            TestScenario(
                name=name,
                coverage_area=_CLASSIFICATION_TO_AREA.get(classification, "general"),
                priority=3,
                risk_score=0.5,
                deferred=True,
                defer_reason=reason,
            )
            for name, reason in deferred_templates
        ]

        coverage_area = _CLASSIFICATION_TO_AREA.get(classification, "general")
        report = TestOracleReport(
            project_id=project_id,
            oracle_mode="heuristic",
            source_classification=classification,
            scenarios=scenarios,
            deferred_scenarios=deferred,
            total_scenarios=len(scenarios),
            coverage_areas=[coverage_area] if coverage_area != "general" else ["general"],
        )

        if deferred:
            report.notes.append(
                f"{len(deferred)} scenario(s) deferred to future phases "
                f"({', '.join(set(s.defer_reason.split(' ')[0] for s in deferred))})."
            )

        return report

    def render_artifacts(
        self, report: TestOracleReport, project_id: str
    ) -> Dict[str, Path]:
        """Write artifacts to outputs/<project_id>/23_test_oracle/."""
        out_dir = self._outputs_root / project_id / "23_test_oracle"
        out_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(timezone.utc).isoformat()
        payload: dict = {
            "schema_version": "5K.1",
            "generated_at": ts,
            **report.to_dict(),
        }

        json_path = out_dir / "TEST_ORACLE_REPORT.json"
        json_path.write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )

        md_path = out_dir / "TEST_ORACLE_REPORT.md"
        md_path.write_text(self._render_md(report, ts), encoding="utf-8")

        return {"json": json_path, "md": md_path}

    def _render_md(self, report: TestOracleReport, ts: str) -> str:
        lines = [
            "# Test Oracle Report",
            "",
            f"**Project:** {report.project_id}",
            f"**Generated:** {ts}",
            f"**Mode:** {report.oracle_mode}",
            f"**Classification:** `{report.source_classification}`",
            f"**Total scenarios:** {report.total_scenarios}",
            "",
            "## Scenarios",
            "",
            "| # | Scenario | Priority | Risk | Tags |",
            "|---|---|---|---|---|",
        ]
        for i, s in enumerate(report.scenarios, 1):
            tags = ", ".join(s.tags) if s.tags else "—"
            lines.append(
                f"| {i} | {s.name} | P{s.priority} | {s.risk_score:.0%} | {tags} |"
            )
        if report.deferred_scenarios:
            lines += [
                "",
                "## Deferred Scenarios",
                "",
                "| Scenario | Reason |",
                "|---|---|",
            ]
            for s in report.deferred_scenarios:
                lines.append(f"| {s.name} | {s.defer_reason} |")
        if report.notes:
            lines += ["", "## Notes", ""]
            for n in report.notes:
                lines.append(f"- {n}")
        lines += [
            "",
            "---",
            "",
            "**SAFETY:** `raw_input_stored=False` | `executable_without_approval=False` | "
            "`safe_to_deliver=False` | `human_review_required=True`",
        ]
        return "\n".join(lines) + "\n"
