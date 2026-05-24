from __future__ import annotations

from core.state import QAFactoryState


class OpportunityFilterAgent:
    """Turns analysis into a practical apply/skip/advisory decision."""
    name = "Opportunity Filter"

    def run(self, state: QAFactoryState) -> QAFactoryState:
        action, reasons = self._decide(state)
        state.recommended_action = action
        state.skip_reasons = reasons if action.startswith("skip") else []
        state.next_action = self._next_action(action)
        state.generated_outputs["fit_decision.md"] = self._render_fit(state, reasons)
        state.generated_outputs["DECISION.md"] = self._render_decision(state, reasons)
        state.generated_outputs["NEXT_ACTIONS.md"] = self._render_next_actions(state)
        state.log(f"{self.name}: {action}")
        return state

    @staticmethod
    def _decide(state: QAFactoryState) -> tuple[str, list[str]]:
        text = state.raw_input.lower()
        reasons = []
        if state.recommended_action in {"skip_risky", "skip_low_value", "skip_not_core"}:
            reasons.append(f"CapabilityRouter recommended {state.recommended_action}")
            return state.recommended_action, reasons
        if any(x in text for x in ["valid id", "deposit", "without vpn", "crypto brokerage"]):
            return "skip_risky", ["Deposit/ID/crypto testing risk"]
        import re
        if re.search(r"\$\s*(5|10)(?!\d)", text) or "lowest rates" in text or ("entry level" in text and "10 minutes" in text):
            return "skip_low_value", ["Very low value for Senior QA positioning"]
        if state.support_level == "strong_execution" and state.fit_score >= 65:
            return "strong_apply", []
        if state.support_level == "supported_or_adjacent":
            return "apply_selectively", []
        if state.support_level == "advisory_only":
            return "advisory_only", ["Outside primary execution zone"]
        if state.fit_score < 45:
            return "skip_not_core", ["Low fit score and weak stack/domain match"]
        return "review_manually", []

    @staticmethod
    def _next_action(action: str) -> str:
        return {
            "strong_apply": "prepare_and_review_proposal",
            "apply_selectively": "prepare_narrow_scope_proposal",
            "advisory_only": "review_before_applying_or_skip",
            "skip_low_value": "skip",
            "skip_risky": "skip",
            "skip_not_core": "skip",
        }.get(action, "manual_review")

    @staticmethod
    def _render_fit(state: QAFactoryState, reasons: list[str]) -> str:
        return f"""# Fit Decision

**Recommended action:** `{state.recommended_action}`
**Fit score:** {state.fit_score}/100
**Source platform:** {state.source_platform}
**Opportunity type:** {state.opportunity_type}
**Support level:** {state.support_level}
**Commercial fit:** {state.commercial_fit}

## Reasons
{chr(10).join(f'- {r}' for r in reasons) if reasons else '- Good enough to proceed, with human review.'}

## Safe positioning angle
{state.client_context.get('safe_positioning_angle', 'Use honest senior QA positioning.')}
"""

    @staticmethod
    def _render_decision(state: QAFactoryState, reasons: list[str]) -> str:
        return f"""# Decision

**Decision:** `{state.recommended_action}`

## Why
- Platform: {state.source_platform}
- Type: {state.opportunity_type}
- Support: {state.support_level}
- Fit: {state.fit_score}/100
{chr(10).join(f'- {r}' for r in reasons) if reasons else '- No blocking reason detected.'}

## Human decision still required
AI QA Factory can recommend, but Dmytro decides whether to spend Connects/time.
"""

    @staticmethod
    def _render_next_actions(state: QAFactoryState) -> str:
        lines = ["# Next Actions", ""]
        if state.recommended_action.startswith("skip"):
            lines.append("- Skip this opportunity unless there is a strategic reason to revisit it.")
        elif state.recommended_action == "strong_apply":
            lines.extend([
                "- Review `proposal.md` and `screening_answers.md`.",
                "- Fill missing evidence from `evidence_needed.md`.",
                "- Check `commercial_strategy.md` before quoting price/rate.",
                "- Send only after human review.",
            ])
        elif state.recommended_action == "apply_selectively":
            lines.extend([
                "- Apply only with a narrow, truthful positioning angle.",
                "- Avoid claiming capabilities that are not verified.",
                "- Consider audit-first / discovery-first scope.",
            ])
        elif state.recommended_action == "advisory_only":
            lines.extend([
                "- Do not claim full execution expertise unless verified.",
                "- Either skip or position as QA strategy/advisory only.",
            ])
        else:
            lines.append("- Review manually before spending time or Connects.")
        return "\n".join(lines).strip() + "\n"
