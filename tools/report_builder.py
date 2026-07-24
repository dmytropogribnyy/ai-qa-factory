from __future__ import annotations

from core.state import QAFactoryState
from core.version import APP_VERSION


class ReportBuilder:
    def build_read_me_first(self, state: QAFactoryState) -> str:
        return f"""# Read Me First

**Decision:** `{state.recommended_action}`  
**Next action:** `{state.next_action}`  
**Source platform:** {state.source_platform}  
**Opportunity type:** {state.opportunity_type}  
**Support level:** {state.support_level}  
**Fit score:** {state.fit_score}/100  
**Commercial fit:** {state.commercial_fit}
**Health status:** `{state.health_status}`
**Test design artifacts:** {", ".join(state.test_design_artifacts) if state.test_design_artifacts else "Not generated"}
**System suitability:** `{state.system_suitability}`
**Estimated effort:** {state.estimated_effort or "Not estimated"}

## What to open first
1. `DECISION.md`
2. `screening_answers.md` if the job has screening questions
3. `proposal.md` or platform-specific output pack
4. `TEST_STRATEGY.md`, `TEST_PLAN.md`, `TEST_CASES.md` if generated
5. `PRESCREENING_REPORT.md`
6. `EXECUTION_FLOW.md`
6. `commercial_strategy.md`
7. `evidence_needed.md`
8. `APPROVAL_CHECKPOINTS.md`
9. `QUALITY_GATE_REPORT.md`
10. `HUMAN_REVIEW_REQUIRED.md`

## Main warning
This is an AI-assisted draft pack. Do not send any client-facing text before manual review.

## Pre-screening
- **System suitability:** `{state.system_suitability}`
- **Estimated effort:** {state.estimated_effort or 'Not estimated'}
- **Recommended workflow:** {state.recommended_workflow or 'Not generated'}


## Safe positioning angle
{state.client_context.get('safe_positioning_angle', 'Use honest senior QA positioning; do not overclaim beyond verified experience.')}
"""

    def build_summary(self, state: QAFactoryState) -> str:
        lines = [
            f"# AI QA Factory v{APP_VERSION} — Summary",
            "",
            f"**Project ID:** `{state.project_id}`",
            f"**Mode:** {state.mode}",
            f"**Source Platform:** {state.source_platform}",
            f"**Opportunity Type:** {state.opportunity_type}",
            f"**Support Level:** {state.support_level}",
            f"**Recommended Action:** `{state.recommended_action}`",
            f"**Commercial Fit:** {state.commercial_fit}",
            f"**Project Type:** {state.project_type}",
            f"**Recommended Stack:** {state.stack_choice}",
            f"**Prompt Profile:** {state.prompt_profile}",
            f"**Fit Score:** {state.fit_score}/100",
            f"**Suggested Price / Range:** {state.suggested_price or 'Not generated'}",
            f"**Suggested Milestone:** {state.suggested_milestone or state.client_context.get('recommended_first_milestone', 'Not generated')}",
            f"**Approval Status:** {state.approval_status}",
            "",
            "## Output Pack",
            *([f"- {item}" for item in state.output_pack] or ["- Default output pack"]),
            "",
            "## Automation / Work Scope",
            *[f"- {s}" for s in state.automation_scope],
            "",
            "## Risk Flags",
            *[f"- {r}" for r in state.risk_flags],
            "",
            "## Pre-screening",
            f"- System suitability: `{state.system_suitability}`",
            f"- Estimated effort: {state.estimated_effort or 'Not estimated'}",
            f"- Recommended workflow: {state.recommended_workflow or 'Not generated'}",
            "",
            "## Required Inputs",
            *([f"- {i}" for i in state.required_inputs] or ["- No extra inputs detected"]),
            "",
            "## Evidence Required",
            *([f"- {e}" for e in state.evidence_required] or ["- No special evidence detected"]),
            "",
            "## Screening Questions",
            *([f"- {q}" for q in state.screening_questions] or ["- None detected"]),
            "",
            "## Mandatory Keywords",
            *([f"- {kw}" for kw in state.mandatory_keywords] or ["- None detected"]),
            "",
            "## Clarifying Questions",
            *[f"- {q}" for q in state.clarifications],
            "",
            "## Suggested Specialists",
            *([f"- {s}" for s in state.suggested_specialists] or ["- None suggested"]),
            "",
            "## Test Design Artifacts",
            *([f"- {a}" for a in state.test_design_artifacts] or ["- None generated"]),
            "",
            "## Project Extensions / Health",
            *([f"- {e}" for e in state.project_extensions] or ["- No project-specific extension packs suggested"]),
            f"- Health status: `{state.health_status}`",
            "",
            "## Quality Gates",
        ]
        if state.quality_gate_results:
            for name, result in state.quality_gate_results.items():
                status = "PASS" if result.get("passed") else result.get("severity", "WARN").upper()
                lines.append(f"- **{name}:** {status}")
        else:
            lines.append("- Not run")
        lines += [
            "",
            "## Human Checklist Before Client Delivery",
            "- Decision and recommended action make sense",
            "- Required screening keywords are handled correctly",
            "- Screening answers do not invent evidence",
            "- Proposal tone is specific and senior, not generic",
            "- Pricing/commercial strategy is safe",
            "- Credentials, URLs and test data are not leaked",
            "- Payment/security flows are sandbox/staging only",
            "- Final manual verification completed",
        ]
        return "\n".join(lines) + "\n"
