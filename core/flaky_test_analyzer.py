"""Phase 5O — Flaky test analyzer + self-healing proposal generator.

Default mode: static analysis of Playwright spec files (no network, no browser, no file writes).
Approved apply mode: apply self-healing proposals to spec files (requires --approve-code-modification).

Safety invariants always enforced:
- read_only=True in all reports
- auto_apply_changes=False by default
- code_modification_allowed=False (only overridable by explicit approval flag)
- human_review_required=True
"""
from __future__ import annotations

import re
import json
from datetime import datetime, timezone
from pathlib import Path

from core.schemas.flaky_test_analysis import (
    FlakinessRisk,
    FlakyTestAnalysisReport,
    SelectorFinding,
    SelectorStabilityReport,
    SelfHealingProposal,
    SelfHealingReport,
)

# ---------------------------------------------------------------------------
# Flakiness detection rules
# ---------------------------------------------------------------------------

_FLAKINESS_RULES: list[dict] = [
    {
        "pattern": re.compile(r"\bwaitForTimeout\s*\("),
        "category": "hard_wait",
        "severity": "high",
        "description": "waitForTimeout() is a hard wait — pauses for a fixed duration regardless of page state.",
        "recommendation": "Replace with: await expect(locator).toBeVisible() or await expect(locator).toBeEnabled()",
        "confidence": "high",
    },
    {
        "pattern": re.compile(r"\bpage\.wait\s*\("),
        "category": "hard_wait",
        "severity": "high",
        "description": "page.wait() is a fixed-duration pause — unreliable in variable environments.",
        "recommendation": "Use Playwright web-first assertions instead of fixed waits.",
        "confidence": "high",
    },
    {
        "pattern": re.compile(r"\.nth\s*\(\s*\d"),
        "category": "fragile_selector",
        "severity": "high",
        "description": ".nth() selector depends on element order — breaks when page structure changes.",
        "recommendation": "Use getByRole(), getByLabel(), or getByTestId() to target elements uniquely.",
        "confidence": "high",
    },
    {
        "pattern": re.compile(r">> nth="),
        "category": "fragile_selector",
        "severity": "high",
        "description": "Playwright nth combinator — fragile to DOM changes.",
        "recommendation": "Use specific semantic locators (getByRole, getByLabel) instead of positional nth.",
        "confidence": "high",
    },
    {
        "pattern": re.compile(r"xpath\s*=\s*//|locator\s*\(\s*['\"]xpath="),
        "category": "fragile_selector",
        "severity": "high",
        "description": "XPath selector detected — brittle and hard to maintain across UI changes.",
        "recommendation": "Replace with Playwright semantic locators: getByRole, getByLabel, getByTestId.",
        "confidence": "high",
    },
    {
        "pattern": re.compile(r"\bwaitForSelector\s*\("),
        "category": "non_web_first_assertion",
        "severity": "medium",
        "description": "waitForSelector() is not a web-first assertion — prefer expect() matchers.",
        "recommendation": "Replace with: await expect(page.locator('...')).toBeVisible()",
        "confidence": "high",
    },
    {
        "pattern": re.compile(r"locator\s*\(\s*['\"]\.[\w-]*\d{3,}[\w-]*['\"]"),
        "category": "dynamic_selector",
        "severity": "medium",
        "description": "CSS class with numeric suffix detected — likely auto-generated class name.",
        "recommendation": "Add a data-testid attribute and use getByTestId() for stability.",
        "confidence": "medium",
    },
    {
        "pattern": re.compile(r"\bpage\.goto\s*\([^)]*\)\s*;"),
        "category": "network_dependent",
        "severity": "low",
        "description": "page.goto() without waitUntil option may cause race conditions on slow networks.",
        "recommendation": "Add: { waitUntil: 'domcontentloaded' } to page.goto() options.",
        "confidence": "medium",
    },
    {
        "pattern": re.compile(r"\bsleep\s*\(|setTimeout\s*\(.*\d{3,}"),
        "category": "hard_wait",
        "severity": "medium",
        "description": "Fixed sleep/timeout detected — introduces non-deterministic test timing.",
        "recommendation": "Replace with event-driven wait: await expect(locator).toBeVisible()",
        "confidence": "medium",
    },
]

# ---------------------------------------------------------------------------
# Selector stability rules
# ---------------------------------------------------------------------------

_STRONG_SELECTOR_RULES: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"\bgetByRole\s*\("), "getByRole", "Semantic ARIA role — stable across refactoring."),
    (re.compile(r"\bgetByLabel\s*\("), "getByLabel", "Form label locator — accessible and stable."),
    (re.compile(r"\bgetByTestId\s*\("), "getByTestId", "data-testid locator — explicit test contract."),
    (re.compile(r"\bgetByText\s*\("), "getByText", "Text content locator — stable when text is intentional."),
    (re.compile(r"\[data-testid="), "data-testid attr", "Explicit test identifier — strong by convention."),
    (re.compile(r"\[aria-label="), "aria-label attr", "ARIA label selector — accessible and stable."),
    (re.compile(r"\bgetByPlaceholder\s*\("), "getByPlaceholder", "Placeholder text locator — stable for form inputs."),
]

_WEAK_SELECTOR_RULES: list[tuple[re.Pattern, str, str]] = [
    (re.compile(r"\.nth\s*\(\s*\d"), "nth()", "nth() depends on element order — fragile."),
    (re.compile(r">> nth="), ">> nth=", "nth combinator — fragile to DOM structure changes."),
    (re.compile(r"xpath\s*=\s*//|locator\s*\(\s*['\"]xpath="), "xpath", "XPath — brittle across UI changes."),
    (re.compile(r"locator\s*\(\s*['\"]\.[\w-]*\d{3,}[\w-]*['\"]"), "generated-class", "Likely auto-generated class name."),
    (re.compile(r"locator\s*\(\s*['\"][^'\"]*\s+>\s+[^'\"]*\s+>\s+[^'\"]*['\"]"), "deep-css", "Deep CSS chain (3+ levels) — fragile to DOM refactoring."),
]

# ---------------------------------------------------------------------------
# Healing proposal templates
# ---------------------------------------------------------------------------

_HEALING_TEMPLATES = {
    "nth()": ("Replace .nth(N) with a unique role/label/testid locator.", "medium"),
    ">> nth=": ("Replace >> nth= with a unique role/label/testid locator.", "medium"),
    "xpath": ("Replace XPath with: page.getByRole('...') or page.getByLabel('...')", "high"),
    "generated-class": ("Add data-testid attribute; use page.getByTestId('...')", "medium"),
    "deep-css": ("Simplify CSS chain; use semantic locator targeting the specific element.", "low"),
}


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------

class FlakyTestAnalyzer:
    """Static analyzer for Playwright spec files — detects flakiness, classifies selectors, generates healing proposals."""

    def __init__(
        self,
        project_id: str,
        outputs_root: str = "outputs",
        spec_files: list[str] | None = None,
    ) -> None:
        self.project_id = project_id
        self.outputs_root = Path(outputs_root)
        self._spec_file_paths: list[Path] = [Path(f) for f in spec_files] if spec_files else []
        self._out_dir = self.outputs_root / project_id / "32_flaky_test_analyzer"

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze(self, write_files: bool = True) -> FlakyTestAnalysisReport:
        """Static flakiness analysis of all configured spec files. No network or file writes to specs."""
        files = self._spec_file_paths or self._discover_spec_files()
        all_risks: list[FlakinessRisk] = []
        files_analyzed: list[str] = []

        for spec in files:
            if not spec.exists():
                continue
            content = spec.read_text(encoding="utf-8")
            files_analyzed.append(spec.name)
            all_risks.extend(self._analyze_file(spec, content))

        by_severity: dict[str, int] = {}
        for r in all_risks:
            by_severity[r.severity] = by_severity.get(r.severity, 0) + 1

        report = FlakyTestAnalysisReport(
            project_id=self.project_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            files_analyzed=files_analyzed,
            risks=all_risks,
            total_risks=len(all_risks),
            risks_by_severity=by_severity,
            status="complete" if files_analyzed else "analysis_only",
            notes=[
                f"Analyzed {len(files_analyzed)} spec file(s).",
                f"Found {len(all_risks)} flakiness risk(s).",
                "Static analysis only — no tests were executed.",
                "Human review required before remediation.",
            ],
        )

        if write_files:
            self._out_dir.mkdir(parents=True, exist_ok=True)
            (self._out_dir / "flaky_test_analysis.json").write_text(
                json.dumps(report.to_dict(), indent=2, default=str), encoding="utf-8"
            )
            (self._out_dir / "Flaky_Test_Analysis_Report.md").write_text(
                self._render_analysis_md(report), encoding="utf-8"
            )

        return report

    def analyze_selectors(self, write_files: bool = True) -> SelectorStabilityReport:
        """Classify all selectors in configured spec files by stability level."""
        files = self._spec_file_paths or self._discover_spec_files()
        findings: list[SelectorFinding] = []
        files_analyzed: list[str] = []

        for spec in files:
            if not spec.exists():
                continue
            content = spec.read_text(encoding="utf-8")
            files_analyzed.append(spec.name)
            findings.extend(self._classify_selectors(spec, content))

        strong = sum(1 for f in findings if f.stability_level == "strong")
        medium = sum(1 for f in findings if f.stability_level == "medium")
        weak = sum(1 for f in findings if f.stability_level == "weak")
        total = strong + medium + weak
        score = round((strong / total * 100) if total > 0 else 0.0, 1)

        report = SelectorStabilityReport(
            project_id=self.project_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            files_analyzed=files_analyzed,
            findings=findings,
            strong_count=strong,
            medium_count=medium,
            weak_count=weak,
            stability_score=score,
            notes=[
                f"Analyzed {len(files_analyzed)} spec file(s).",
                f"Selector stability score: {score}/100.",
                f"Strong: {strong} | Medium: {medium} | Weak: {weak}.",
                "Human review required before any selector changes.",
            ],
        )

        if write_files:
            self._out_dir.mkdir(parents=True, exist_ok=True)
            (self._out_dir / "selector_stability.json").write_text(
                json.dumps(report.to_dict(), indent=2, default=str), encoding="utf-8"
            )
            (self._out_dir / "Selector_Stability_Report.md").write_text(
                self._render_selector_md(report), encoding="utf-8"
            )

        return report

    def generate_healing_proposals(self, write_files: bool = True) -> SelfHealingReport:
        """Generate self-healing proposals for weak selectors. Does NOT apply changes."""
        selector_report = self.analyze_selectors(write_files=write_files)
        proposals: list[SelfHealingProposal] = []

        for i, finding in enumerate(selector_report.findings):
            if finding.stability_level != "weak":
                continue
            template = _HEALING_TEMPLATES.get(finding.locator_type)
            if not template:
                continue
            proposed_text, confidence = template
            proposals.append(
                SelfHealingProposal(
                    proposal_id=f"HEAL-{i + 1:03d}",
                    original_selector=finding.selector_text,
                    proposed_selector=f"// TODO: {proposed_text}",
                    rationale=finding.recommendation,
                    affected_file=finding.affected_file,
                    line_number=finding.line_number,
                    confidence=confidence,
                    applied=False,
                )
            )

        report = SelfHealingReport(
            project_id=self.project_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            proposals=proposals,
            total_proposals=len(proposals),
            applied_proposals=0,
            status="proposal_generated" if proposals else "analysis_only",
            notes=[
                f"{len(proposals)} healing proposal(s) generated.",
                "Proposals NOT applied — review before applying.",
                "To apply: use --apply-proposals --approve-code-modification flags.",
                "Human review required before any code changes.",
            ],
        )

        if write_files:
            self._out_dir.mkdir(parents=True, exist_ok=True)
            (self._out_dir / "self_healing_proposals.json").write_text(
                json.dumps(report.to_dict(), indent=2, default=str), encoding="utf-8"
            )
            (self._out_dir / "Self_Healing_Proposals.md").write_text(
                self._render_healing_md(report), encoding="utf-8"
            )

        return report

    def apply_proposals(
        self,
        report: SelfHealingReport,
        approve_code_modification: bool = False,
        write_files: bool = True,
    ) -> SelfHealingReport:
        """Apply healing proposals to spec files. Requires explicit --approve-code-modification."""
        if not approve_code_modification:
            raise ValueError(
                "Applying proposals requires --approve-code-modification flag. "
                "Review proposals in Self_Healing_Proposals.md before applying."
            )
        # Proposals contain TODO comments — applying them writes the comment into the file
        # which prompts the developer to make the actual change.
        applied_count = 0
        updated_proposals: list[SelfHealingProposal] = []

        for proposal in report.proposals:
            spec_path = self.outputs_root / proposal.affected_file
            if not spec_path.exists():
                updated_proposals.append(proposal)
                continue
            content = spec_path.read_text(encoding="utf-8")
            lines = content.splitlines(keepends=True)
            if 0 < proposal.line_number <= len(lines):
                line_idx = proposal.line_number - 1
                comment = f"  // HEAL-{proposal.proposal_id}: {proposal.proposed_selector}\n"
                lines.insert(line_idx, comment)
                if write_files:
                    spec_path.write_text("".join(lines), encoding="utf-8")
                proposal = SelfHealingProposal(
                    proposal_id=proposal.proposal_id,
                    original_selector=proposal.original_selector,
                    proposed_selector=proposal.proposed_selector,
                    rationale=proposal.rationale,
                    affected_file=proposal.affected_file,
                    line_number=proposal.line_number,
                    confidence=proposal.confidence,
                    applied=True,
                )
                applied_count += 1
            updated_proposals.append(proposal)

        status = "patch_applied" if applied_count == len(report.proposals) else "partial"
        return SelfHealingReport(
            project_id=self.project_id,
            generated_at=datetime.now(timezone.utc).isoformat(),
            proposals=updated_proposals,
            total_proposals=len(updated_proposals),
            applied_proposals=applied_count,
            status=status,
            notes=[
                f"{applied_count}/{len(updated_proposals)} proposal(s) applied.",
                "Each applied proposal inserts a TODO comment at the affected line.",
                "Developer must implement the suggested locator change.",
                "Human review required after applying proposals.",
            ],
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _discover_spec_files(self) -> list[Path]:
        if not self.outputs_root.exists():
            return []
        return sorted(self.outputs_root.rglob("*.spec.ts"))[:20]

    def _analyze_file(self, spec: Path, content: str) -> list[FlakinessRisk]:
        risks: list[FlakinessRisk] = []
        lines = content.splitlines()
        current_test = ""
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            # Track current test name
            m = re.search(r"test\s*\(\s*['\"](.+?)['\"]", line)
            if m:
                current_test = m.group(1)
            for rule in _FLAKINESS_RULES:
                if rule["pattern"].search(line):
                    risks.append(
                        FlakinessRisk(
                            risk_category=rule["category"],
                            severity=rule["severity"],
                            affected_file=spec.name,
                            test_name=current_test,
                            line_number=i,
                            matched_pattern=rule["pattern"].pattern,
                            description=rule["description"],
                            recommendation=rule["recommendation"],
                            confidence_level=rule["confidence"],
                        )
                    )
        return risks

    def _classify_selectors(self, spec: Path, content: str) -> list[SelectorFinding]:
        findings: list[SelectorFinding] = []
        lines = content.splitlines()
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith("//") or stripped.startswith("*"):
                continue
            for pattern, locator_type, recommendation in _STRONG_SELECTOR_RULES:
                if pattern.search(line):
                    findings.append(
                        SelectorFinding(
                            selector_text=line.strip()[:80],
                            stability_level="strong",
                            locator_type=locator_type,
                            affected_file=spec.name,
                            line_number=i,
                            recommendation=recommendation,
                        )
                    )
                    break
            else:
                for pattern, locator_type, recommendation in _WEAK_SELECTOR_RULES:
                    if pattern.search(line):
                        findings.append(
                            SelectorFinding(
                                selector_text=line.strip()[:80],
                                stability_level="weak",
                                locator_type=locator_type,
                                affected_file=spec.name,
                                line_number=i,
                                recommendation=recommendation,
                            )
                        )
                        break
        return findings

    def _render_analysis_md(self, report: FlakyTestAnalysisReport) -> str:
        sev_summary = " | ".join(
            f"{s}: {report.risks_by_severity.get(s, 0)}" for s in ("high", "medium", "low")
        )
        lines = [
            f"# Flaky Test Analysis Report — {report.project_id}",
            "",
            f"**Status:** {report.status}",
            f"**Generated:** {report.generated_at}",
            f"**Files analyzed:** {len(report.files_analyzed)}",
            f"**Total risks:** {report.total_risks}  ({sev_summary})",
            "",
            "## Risks",
            "",
            "| Severity | Category | File | Line | Description |",
            "|----------|----------|------|------|-------------|",
        ]
        for r in report.risks:
            lines.append(f"| {r.severity} | {r.risk_category} | {r.affected_file} | {r.line_number} | {r.description[:60]} |")
        lines += [
            "",
            "## Recommendations",
            "",
        ]
        seen = set()
        for r in report.risks:
            if r.recommendation not in seen:
                lines.append(f"- [{r.severity}] {r.recommendation}")
                seen.add(r.recommendation)
        lines += [
            "",
            "> **Static analysis only** — no code changes were made.",
            "> Human review required before remediation.",
        ]
        return "\n".join(lines) + "\n"

    def _render_selector_md(self, report: SelectorStabilityReport) -> str:
        lines = [
            f"# Selector Stability Report — {report.project_id}",
            "",
            f"**Stability score:** {report.stability_score}/100",
            f"**Generated:** {report.generated_at}",
            f"**Strong:** {report.strong_count} | **Medium:** {report.medium_count} | **Weak:** {report.weak_count}",
            "",
            "## Findings",
            "",
            "| Level | Type | File | Line | Selector |",
            "|-------|------|------|------|----------|",
        ]
        for f in report.findings:
            lines.append(
                f"| {f.stability_level} | {f.locator_type} | {f.affected_file} | {f.line_number} | {f.selector_text[:50]} |"
            )
        lines += [
            "",
            "> Human review required before any selector changes.",
        ]
        return "\n".join(lines) + "\n"

    def _render_healing_md(self, report: SelfHealingReport) -> str:
        lines = [
            f"# Self-Healing Proposals — {report.project_id}",
            "",
            f"**Status:** {report.status}",
            f"**Total proposals:** {report.total_proposals}",
            f"**Applied:** {report.applied_proposals}",
            f"**Generated:** {report.generated_at}",
            "",
            "> **Proposals only** — no code was modified.",
            "> To apply: use `--apply-proposals --approve-code-modification` flags.",
            "> Human review required before applying any proposal.",
            "",
            "## Proposals",
            "",
        ]
        for p in report.proposals:
            lines += [
                f"### {p.proposal_id} — {p.affected_file}:{p.line_number}",
                "",
                f"**Confidence:** {p.confidence}",
                f"**Original:** `{p.original_selector}`",
                f"**Proposed:** {p.proposed_selector}",
                f"**Rationale:** {p.rationale}",
                f"**Applied:** {p.applied}",
                "",
            ]
        return "\n".join(lines)
