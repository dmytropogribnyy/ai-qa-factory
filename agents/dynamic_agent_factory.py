from __future__ import annotations

from core.state import QAFactoryState


class DynamicAgentFactory:
    """v5-light: specialist suggestions, not runtime code generation yet."""

    name = "Dynamic Agent Factory"

    SPECIALISTS = {
        "payment": ("Payment Flow Specialist", "Review Stripe/checkout/subscription flows in sandbox only."),
        "stripe": ("Payment Flow Specialist", "Review Stripe/checkout/subscription flows in sandbox only."),
        "healthcare": ("Healthcare Risk Specialist", "Check privacy, data handling and regulated workflow assumptions."),
        "hipaa": ("Healthcare Risk Specialist", "Check privacy, data handling and regulated workflow assumptions."),
        "mobile": ("Mobile QA Specialist", "Clarify device/OS matrix; keep automation advisory unless scoped."),
        "android": ("Mobile QA Specialist", "Clarify device/OS matrix; keep automation advisory unless scoped."),
        "ios": ("Mobile QA Specialist", "Clarify device/OS matrix; keep automation advisory unless scoped."),
        "performance": ("Performance Smoke Specialist", "Clarify load model, metrics, environment and k6 smoke scope."),
        "load": ("Performance Smoke Specialist", "Clarify load model, metrics, environment and k6 smoke scope."),
        "figma": ("UX/A11y Reviewer", "Compare key screens to design and check accessibility risks."),
        "accessibility": ("UX/A11y Reviewer", "Check axe smoke and manual accessibility heuristics."),
        "tosca": ("Tosca Advisory Specialist", "Provide test design and migration advisory, not full Tosca automation."),
    }

    def run(self, state: QAFactoryState) -> QAFactoryState:
        text = state.raw_input.lower()
        suggestions: list[tuple[str, str]] = []
        seen = set()
        for key, specialist in self.SPECIALISTS.items():
            if key in text and specialist[0] not in seen:
                suggestions.append(specialist)
                seen.add(specialist[0])
        state.suggested_specialists = [s[0] for s in suggestions]
        if not suggestions:
            content = "# Suggested Specialists\n\n- None required beyond the core QA workflow.\n"
        else:
            lines = ["# Suggested Specialists", ""]
            for name, note in suggestions:
                lines.append(f"- **{name}** — {note}")
            lines.append("\nThese are review prompts for Dmytro, not autonomous agents yet.\n")
            content = "\n".join(lines)
        state.generated_outputs["suggested_specialists.md"] = content
        state.log(f"{self.name}: {len(suggestions)} suggestions")
        return state
