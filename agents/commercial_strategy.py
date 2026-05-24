from __future__ import annotations

import re
from core.state import QAFactoryState


class CommercialStrategyAgent:
    """Turns pricing into a negotiation/filtering strategy, not a final price."""
    name = "Commercial Strategy"

    def run(self, state: QAFactoryState) -> QAFactoryState:
        strategy = self._strategy(state)
        state.commercial_fit = strategy["commercial_fit"]
        state.suggested_price = strategy["safe_price_range"]
        state.suggested_milestone = strategy["first_milestone_strategy"]
        state.generated_outputs["commercial_strategy.md"] = self._render(strategy)
        # Backward-compatible filename for old workflows/tests/users.
        state.generated_outputs.setdefault("pricing_and_milestone.md", state.generated_outputs["commercial_strategy.md"])
        state.log(f"{self.name}: {state.commercial_fit} / {state.suggested_price}")
        return state

    @staticmethod
    def _money_signals(text: str) -> dict:
        hourly = re.findall(r"\$(\d+(?:\.\d+)?)\s*-\s*\$?(\d+(?:\.\d+)?)\s*hourly", text, flags=re.I)
        fixed = re.findall(r"\$(\d+(?:\.\d+)?)\s*fixed", text, flags=re.I)
        return {"hourly_ranges": hourly, "fixed_prices": fixed}

    @classmethod
    def _strategy(cls, state: QAFactoryState) -> dict:
        text = state.raw_input.lower()
        money = cls._money_signals(state.raw_input)
        action = state.recommended_action
        commercial_fit = "medium"
        rate_pressure = "unknown"
        safe_price_range = state.suggested_price or "$50/hr or discovery milestone"
        first_milestone = state.suggested_milestone or "Small fixed-scope discovery / QA audit before full commitment"
        do_not_quote = "Do not quote full implementation before access to app/repo/brief."

        if state.opportunity_type == "saas_multi_tenant_billing_auth_audit":
            commercial_fit = "high"
            safe_price_range = "$300–$500 fixed audit or $50/hr depending on scope"
            first_milestone = "1–2 hour trial or fixed 5–10 hour SaaS risk audit: tenant isolation, billing, roles, auth/session."
        elif state.opportunity_type == "ai_native_exploratory_qa":
            commercial_fit = "high_fit_rate_sensitive"
            safe_price_range = "$40–$50/hr target; do not anchor to low posted range if expert bids are accepted"
            first_milestone = "First release QA pass: exploratory testing + Linear/Loom bug reports + 2–3 Playwright flows."
        elif state.opportunity_type == "flaky_regression_automation":
            commercial_fit = "medium_high_if_rate_acceptable"
            safe_price_range = "$75–$250 starter task or $40–$50/hr"
            first_milestone = "Reproduce recurring bug and add failing regression test around it."
        elif state.opportunity_type == "technical_writing":
            commercial_fit = "adjacent_good"
            safe_price_range = "$200–$650/article or project-specific fixed quote"
            first_milestone = "Documentation audit + one sample rewrite/outline before full migration."
        elif state.recommended_action.startswith("skip"):
            commercial_fit = "low_or_risky"
            safe_price_range = "Do not quote unless strategic exception"
            first_milestone = "Skip or reply only if there is a clear non-risky paid scope."

        if "$7" in text or "$10" in text or "$15" in text or "$5" in text:
            rate_pressure = "high"
        elif "$50" in text or "$80" in text or "$120" in text:
            rate_pressure = "acceptable_or_high"
        else:
            rate_pressure = "unknown"

        return {
            "commercial_fit": commercial_fit,
            "budget_fit": "review_budget_against_target_rate",
            "rate_pressure": rate_pressure,
            "recommended_action": state.recommended_action,
            "first_milestone_strategy": first_milestone,
            "safe_price_range": safe_price_range,
            "do_not_quote_warning": do_not_quote,
            "proposal_pricing_angle": cls._pricing_angle(state),
            "detected_money_signals": money,
        }

    @staticmethod
    def _pricing_angle(state: QAFactoryState) -> str:
        if state.recommended_action.startswith("skip"):
            return "No pricing angle recommended; skip or avoid spending Connects."
        if state.opportunity_type == "technical_writing":
            return "Position as a scoped documentation improvement/migration, not generic copywriting."
        return "Lead with a low-risk first milestone, then estimate full scope after access/brief review."

    @staticmethod
    def _render(strategy: dict) -> str:
        lines = ["# Commercial Strategy", "", "Pricing is advisory. Final terms are agreed with the client.", ""]
        for key, value in strategy.items():
            lines.append(f"## {key}")
            if isinstance(value, dict):
                for k, v in value.items():
                    lines.append(f"- **{k}:** {v}")
            else:
                lines.append(str(value))
            lines.append("")
        return "\n".join(lines).strip() + "\n"
