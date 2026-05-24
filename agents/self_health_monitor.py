from __future__ import annotations

from core.state import QAFactoryState


class SelfHealthMonitorAgent:
    """Human-readable self-health checks for the Factory run.

    This is not autonomous self-healing. It performs safe consistency checks,
    creates a repair plan, and can add missing human-readable placeholders.
    """

    name = "Self Health Monitor"

    REQUIRED_HUMAN_OUTPUTS = [
        "READ_ME_FIRST.md",  # final output, may be created after this agent
        "DECISION.md",
        "NEXT_ACTIONS.md",
        "SUMMARY.md",       # final output, may be created after this agent
        "HUMAN_REVIEW_REQUIRED.md",  # may be created before QualityGate/final save
        "QUALITY_GATE_REPORT.md",    # created by quality_gate after this agent in some workflows
    ]

    def run(self, state: QAFactoryState) -> QAFactoryState:
        findings: list[dict] = []
        safe_fixes: list[str] = []

        if not state.recommended_action or state.recommended_action == "review_manually":
            findings.append(self._finding("decision_unclear", "warning", "Recommended action is missing or generic; manual review needed."))
        if state.fit_score < 25 and state.recommended_action not in {"skip_risky", "skip_low_value", "skip_not_core"}:
            findings.append(self._finding("low_fit_not_skipped", "warning", "Low fit score but action is not a skip decision."))
        if state.mandatory_keywords and "screening_answers.md" not in state.generated_outputs:
            findings.append(self._finding("missing_screening_answers", "error", "Mandatory keyword/questions detected but screening_answers.md is missing."))
        if state.evidence_required and "evidence_needed.md" not in state.generated_outputs:
            findings.append(self._finding("missing_evidence_report", "error", "Evidence is required but evidence_needed.md is missing."))
        if state.system_suitability in {"not_suitable", "advisory_only"} and state.recommended_action == "strong_apply":
            findings.append(self._finding("suitability_action_conflict", "error", "System suitability conflicts with strong_apply."))
        if state.triggered_prompts_answers:
            unanswered = [k for k, v in state.triggered_prompts_answers.items() if str(v).startswith("not_asked") or v == "unclear"]
            if unanswered:
                findings.append(self._finding("unanswered_triggered_prompts", "warning", f"Triggered safety prompts need review: {', '.join(unanswered)}"))
        if state.project_extension_requests:
            findings.append(self._finding("extension_approval_needed", "info", "Project-specific extension packs were suggested and need approval before use."))
        if state.mode in {"plan", "audit", "full", "test-design"} and not state.test_design_artifacts:
            findings.append(self._finding("missing_test_design_artifacts", "warning", "Test design workflow ran but no test strategy/plan/cases artifacts were generated."))

        # Safe, non-invasive auto-fixes: add missing human-readable placeholders if earlier agents did not create them.
        if "DECISION.md" not in state.generated_outputs:
            state.generated_outputs["DECISION.md"] = self._decision_placeholder(state)
            safe_fixes.append("Created missing DECISION.md placeholder.")
        if "NEXT_ACTIONS.md" not in state.generated_outputs:
            state.generated_outputs["NEXT_ACTIONS.md"] = self._next_actions_placeholder(state)
            safe_fixes.append("Created missing NEXT_ACTIONS.md placeholder.")

        status = "healthy"
        if any(f["severity"] == "error" for f in findings):
            status = "needs_repair"
        elif findings:
            status = "review_recommended"

        state.health_status = status
        state.health_findings = findings
        state.safe_auto_fixes = safe_fixes
        state.generated_outputs["SELF_HEALTH_REPORT.md"] = self._health_report(state, findings, safe_fixes)
        state.generated_outputs["SYSTEM_REPAIR_PLAN.md"] = self._repair_plan(state, findings)
        state.log(f"{self.name}: status={status}, findings={len(findings)}, safe_fixes={len(safe_fixes)}")
        return state

    @staticmethod
    def _finding(code: str, severity: str, message: str) -> dict:
        return {"code": code, "severity": severity, "message": message}

    @staticmethod
    def _decision_placeholder(state: QAFactoryState) -> str:
        return f"""# Decision

**Recommended action:** `{state.recommended_action}`  
**Fit score:** {state.fit_score}/100  
**System suitability:** `{state.system_suitability}`  
**Support level:** `{state.support_level}`

Review this decision before spending Connects, replying to a client, or starting delivery.
"""

    @staticmethod
    def _next_actions_placeholder(state: QAFactoryState) -> str:
        return f"""# Next Actions

1. Open `READ_ME_FIRST.md` and `DECISION.md`.
2. Check `PRESCREENING_REPORT.md` and `PROJECT_EXTENSION_PLAN.md` if present.
3. Review `screening_answers.md`, `evidence_needed.md`, and `commercial_strategy.md`.
4. Approve or reject the recommended workflow: `{state.recommended_workflow or state.mode}`.
5. Do not send or execute anything client-facing until `HUMAN_REVIEW_REQUIRED.md` is cleared manually.
"""

    @staticmethod
    def _health_report(state: QAFactoryState, findings: list[dict], safe_fixes: list[str]) -> str:
        lines = [
            "# Self Health Report",
            "",
            f"**Health status:** `{state.health_status}`",
            f"**Project ID:** `{state.project_id}`",
            f"**Mode:** `{state.mode}`",
            "",
            "## Findings",
        ]
        if findings:
            for finding in findings:
                lines.append(f"- **{finding['severity'].upper()}** `{finding['code']}` — {finding['message']}")
        else:
            lines.append("- No blocking consistency issues detected.")
        lines += ["", "## Safe auto-fixes applied"]
        if safe_fixes:
            for fix in safe_fixes:
                lines.append(f"- {fix}")
        else:
            lines.append("- None.")
        lines += [
            "",
            "## Boundary",
            "This monitor may create missing local reports and highlight inconsistencies. It must not auto-submit, auto-push, run destructive commands, make payments, or change client systems.",
        ]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _repair_plan(state: QAFactoryState, findings: list[dict]) -> str:
        lines = ["# System Repair Plan", ""]
        if not findings:
            lines.append("No repair actions required beyond normal human review.")
        else:
            lines.append("## Recommended repairs")
            for finding in findings:
                code = finding["code"]
                if code == "missing_screening_answers":
                    action = "Run or fix ScreeningAnswersAgent before proposal generation."
                elif code == "missing_evidence_report":
                    action = "Run or fix EvidencePackAgent; request real evidence from Dmytro."
                elif code == "suitability_action_conflict":
                    action = "Review OpportunityFilterAgent and PreScreeningAgent decision rules."
                elif code == "extension_approval_needed":
                    action = "Approve/reject suggested project extension packs before continuing."
                elif code == "unanswered_triggered_prompts":
                    action = "Answer triggered safety prompts manually before client-facing execution."
                elif code == "missing_test_design_artifacts":
                    action = "Run `python main.py test-design --input <brief> --only test_strategy/test_plan_writer/test_case_writer` or review why the job was classified as skip."
                else:
                    action = "Manual review required."
                lines.append(f"- `{code}`: {action}")
        lines += [
            "",
            "## Allowed auto-fix scope",
            "- Create missing local markdown reports.",
            "- Re-run selected agents with `--only` after user approval.",
            "- Update local prompt/profile files only after explicit user approval.",
            "",
            "## Not allowed",
            "- No auto-submission to platforms.",
            "- No GitHub auto-push.",
            "- No destructive tests on real systems.",
            "- No invented evidence or claims.",
        ]
        return "\n".join(lines) + "\n"
