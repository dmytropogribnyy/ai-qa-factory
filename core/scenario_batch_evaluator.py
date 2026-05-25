"""Scenario Batch Evaluator — Phase 4ABC.

Reads local fixture files from fixtures/client_scenarios/ and evaluates
safety expectations, category rules, and structural checks.

SAFETY: No URL fetching, no execution, no external calls.
evaluation_performed_without_execution=True always.
external_calls_performed=False always.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

from core.schemas.scenario_evaluation import (
    ScenarioBatchEvaluationReport,
    ScenarioEvaluationResult,
)

_FIXTURES_ROOT = Path("fixtures") / "client_scenarios"
_OUTPUTS_ROOT = Path("outputs")

_CATEGORY_DIRS = {
    "synthetic": "synthetic",
    "public_demo_targets": "public_demo_targets",
    "real_public_readonly": "real_public_readonly",
    "high_risk_marketplace_readonly": "high_risk_marketplace_readonly",
}

_SECRET_PATTERNS = [
    "api_key", "api_secret", "password=", "token=", "client_secret",
    "oauth_secret", "webhook_secret", "private_key",
]

_HIGH_RISK_BLOCKED_TERMS = [
    "scraping", "crawling", "price monitoring", "review scraping",
    "anti-bot", "captcha", "session reuse", "personal account",
]


class ScenarioBatchEvaluator:
    """Evaluates scenario fixtures for safety completeness. No execution performed."""

    def __init__(
        self,
        fixtures_root: Optional[Path] = None,
        outputs_root: Optional[Path] = None,
    ) -> None:
        self._fixtures_root = fixtures_root or _FIXTURES_ROOT
        self._outputs_root = outputs_root or _OUTPUTS_ROOT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate_scenarios(
        self,
        project_id: str,
    ) -> ScenarioBatchEvaluationReport:
        """Read all fixture files and evaluate. No external calls."""
        fixture_files = self._discover_fixtures()
        results: List[ScenarioEvaluationResult] = []

        for path in fixture_files:
            category = self._detect_category(path)
            result = self._evaluate_fixture(path, category)
            results.append(result)

        passed = sum(1 for r in results if r.status == "pass")
        warned = sum(1 for r in results if r.status == "warning")
        blocked = sum(1 for r in results if r.status == "blocked")

        return ScenarioBatchEvaluationReport(
            project_id=project_id,
            fixtures_root=str(self._fixtures_root),
            total_scenarios=len(results),
            passed_scenarios=passed,
            warning_scenarios=warned,
            blocked_scenarios=blocked,
            results=results,
            evaluation_performed_without_execution=True,
            external_calls_performed=False,
            notes=[
                "Evaluation reads local fixture files only.",
                "No URL fetching performed.",
                "No execution performed.",
                "external_calls_performed=False.",
            ],
        )

    def render_scenario_evaluation_artifacts(
        self,
        report: ScenarioBatchEvaluationReport,
        project_id: str,
    ) -> Dict[str, Path]:
        """Write evaluation artifacts to outputs/<project_id>/99_internal/scenario_evaluation/."""
        out_dir = self._outputs_root / project_id / "99_internal" / "scenario_evaluation"
        out_dir.mkdir(parents=True, exist_ok=True)

        paths: Dict[str, Path] = {}

        p = out_dir / "SCENARIO_BATCH_EVALUATION.json"
        p.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        paths["evaluation_json"] = p

        p = out_dir / "SCENARIO_BATCH_EVALUATION.md"
        p.write_text(self._render_evaluation_md(report), encoding="utf-8")
        paths["evaluation_md"] = p

        return paths

    # ------------------------------------------------------------------
    # Discovery
    # ------------------------------------------------------------------

    def _discover_fixtures(self) -> List[Path]:
        fixtures: List[Path] = []
        if not self._fixtures_root.exists():
            return fixtures
        for md_file in sorted(self._fixtures_root.rglob("*.md")):
            if md_file.name == "README.md":
                continue
            fixtures.append(md_file)
        return fixtures

    def _detect_category(self, path: Path) -> str:
        for part in path.parts:
            if part in _CATEGORY_DIRS:
                return part
        return "unknown"

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def _evaluate_fixture(self, path: Path, category: str) -> ScenarioEvaluationResult:
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            return ScenarioEvaluationResult(
                id=path.stem,
                scenario_path=str(path),
                category=category,
                title=path.stem,
                status="blocked",
                blockers=[f"Could not read fixture: {e}"],
            )

        content_lower = content.lower()
        warnings: List[str] = []
        blockers: List[str] = []

        # Extract title
        title = path.stem
        for line in content.splitlines():
            if line.startswith("# "):
                title = line[2:].strip()
                break

        # Common checks
        has_safety = self._check_safety_expectations(content_lower)
        no_real_secrets = self._check_no_real_secrets(content_lower)
        no_execution_confirmed = "no execution" in content_lower or "not yet" in content_lower or "blocked" in content_lower or "approval required" in content_lower

        if not has_safety:
            warnings.append("Safety expectations section not clearly present.")

        if not no_real_secrets:
            blockers.append("Potential real secret value detected in fixture.")

        # Category-specific checks
        linear_rule = False
        high_risk_rule = False

        if category == "synthetic":
            linear_rule = self._check_linear_task_source_rule(content, content_lower)
            if "linear" in content_lower and not linear_rule:
                warnings.append("Linear fixture: task_source/task_url rule not clearly stated.")

            oauth_rule = self._check_oauth_dedicated_account(content_lower)
            if "oauth" in content_lower or "google auth" in content_lower:
                if not oauth_rule:
                    warnings.append("OAuth fixture: dedicated test account / storageState rule not clearly stated.")

            payment_rule = self._check_payment_sandbox(content_lower)
            if "payment" in content_lower or "checkout" in content_lower or "stripe" in content_lower:
                if not payment_rule:
                    warnings.append("Payment fixture: sandbox confirmation rule not clearly stated.")

            n8n_rule = self._check_n8n_blocked(content_lower)
            if "n8n" in content_lower or "webhook" in content_lower:
                if not n8n_rule:
                    warnings.append("n8n/webhook fixture: outbound calls blocked rule not clearly stated.")
                    blockers.append("n8n/webhook integration must explicitly state outbound calls are blocked.")

        elif category == "public_demo_targets":
            if "approval" not in content_lower and "approved" not in content_lower:
                warnings.append("Public demo target: explicit approval-required statement not found.")

        elif category == "real_public_readonly":
            if "read-only" not in content_lower and "readonly" not in content_lower:
                warnings.append("Real public readonly: read-only constraint not clearly stated.")
            if "production" not in content_lower and "live" not in content_lower:
                warnings.append("Real public readonly: production/live environment warning not stated.")

        elif category == "high_risk_marketplace_readonly":
            high_risk_rule = self._check_high_risk_marketplace_rules(content, content_lower)
            if not high_risk_rule:
                blockers.append("High-risk marketplace scenario missing required block rules (scraping, anti-bot, etc.).")

        status = "pass"
        if blockers:
            status = "blocked"
        elif warnings:
            status = "warning"

        return ScenarioEvaluationResult(
            id=path.stem,
            scenario_path=str(path),
            category=category,
            title=title,
            status=status,
            safety_expectations_present=has_safety,
            linear_task_source_rule_present=linear_rule,
            high_risk_marketplace_rule_present=high_risk_rule,
            no_execution_confirmed=no_execution_confirmed,
            warnings=warnings,
            blockers=blockers,
            notes=[f"Category: {category}"],
        )

    def _check_safety_expectations(self, content_lower: str) -> bool:
        safety_keywords = ["safety", "blocked", "approval required", "not approved", "no execution", "do not", "blocked actions"]
        return any(kw in content_lower for kw in safety_keywords)

    def _check_no_real_secrets(self, content_lower: str) -> bool:
        for pattern in _SECRET_PATTERNS:
            if pattern in content_lower:
                # Allow if it's clearly a placeholder
                idx = content_lower.find(pattern)
                surrounding = content_lower[max(0, idx - 20):idx + 60]
                if any(ph in surrounding for ph in ["placeholder", "your_", "<", "example", "fake", "test_", "demo_"]):
                    continue
                return False
        return True

    def _check_linear_task_source_rule(self, content: str, content_lower: str) -> bool:
        return (
            "task_source" in content_lower
            or "task_url" in content_lower
            and "not target" in content_lower
            or ("linear" in content_lower and "not" in content_lower and "target_application" in content_lower)
        )

    def _check_oauth_dedicated_account(self, content_lower: str) -> bool:
        return (
            "dedicated test account" in content_lower
            or "storagestate" in content_lower
            or "test account" in content_lower
        )

    def _check_payment_sandbox(self, content_lower: str) -> bool:
        return (
            "sandbox" in content_lower
            or "test card" in content_lower
            or "stripe test" in content_lower
        )

    def _check_n8n_blocked(self, content_lower: str) -> bool:
        return (
            "outbound" in content_lower and "block" in content_lower
            or "no outbound" in content_lower
            or "blocked by default" in content_lower
        )

    def _check_high_risk_marketplace_rules(self, content: str, content_lower: str) -> bool:
        blocked_terms_found = [term for term in _HIGH_RISK_BLOCKED_TERMS if term in content_lower]
        return len(blocked_terms_found) >= 2

    # ------------------------------------------------------------------
    # Markdown renderer
    # ------------------------------------------------------------------

    def _render_evaluation_md(self, report: ScenarioBatchEvaluationReport) -> str:
        lines = [
            "# Scenario Batch Evaluation Report",
            "",
            "> **INTERNAL ONLY — Not for client delivery.**",
            "",
            f"**Project:** `{report.project_id}`  ",
            f"**Fixtures root:** `{report.fixtures_root}`  ",
            f"**Total scenarios:** {report.total_scenarios}  ",
            f"**Passed:** {report.passed_scenarios}  ",
            f"**Warnings:** {report.warning_scenarios}  ",
            f"**Blocked:** {report.blocked_scenarios}  ",
            f"**evaluation_performed_without_execution:** {report.evaluation_performed_without_execution}  ",
            f"**external_calls_performed:** {report.external_calls_performed}  ",
            "",
            "## Results",
            "",
            "| Scenario | Category | Status | Safety | Linear Rule | High-Risk Rule |",
            "|---|---|---|---|---|---|",
        ]
        for r in report.results:
            lines.append(
                f"| {r.title[:40]} | {r.category} | {r.status} | "
                f"{r.safety_expectations_present} | {r.linear_task_source_rule_present} | "
                f"{r.high_risk_marketplace_rule_present} |"
            )
        lines += ["", "## Details", ""]
        for r in report.results:
            if r.warnings or r.blockers:
                lines.append(f"### {r.title}")
                if r.blockers:
                    lines.append("**Blockers:**")
                    for b in r.blockers:
                        lines.append(f"- {b}")
                if r.warnings:
                    lines.append("**Warnings:**")
                    for w in r.warnings:
                        lines.append(f"- {w}")
                lines.append("")
        lines += ["## Safety Boundary", ""]
        for note in report.notes:
            lines.append(f"- {note}")
        return "\n".join(lines) + "\n"
