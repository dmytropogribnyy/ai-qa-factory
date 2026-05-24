from __future__ import annotations

from core.state import QAFactoryState

class StackRouterAgent:
    name = "Stack Router"

    def run(self, state: QAFactoryState) -> QAFactoryState:
        rationale = {
            "playwright-ts": "Default high-value stack for modern web SaaS automation.",
            "api-first-with-playwright-request": "API-heavy scope; use Playwright request layer plus optional UI smoke checks.",
            "selenium-java-fallback": "Legacy/enterprise Selenium Java requirement detected.",
            "cypress-fallback": "Client mentions Cypress specifically; keep Playwright as advisory alternative.",
            "mobile-maestro-advisory": "Mobile scope detected; start with test strategy and Maestro/Appium advisory.",
            "tosca-advisory": "Tosca detected; provide test design/advisory rather than full autonomous generation.",
        }.get(state.stack_choice, "Stack selected by initial analyzer.")
        state.generated_outputs["stack_decision.md"] = f"# Stack Decision\n\n**Selected:** `{state.stack_choice}`\n\n**Reason:** {rationale}\n"
        state.log(f"{self.name}: {state.stack_choice}")
        return state
