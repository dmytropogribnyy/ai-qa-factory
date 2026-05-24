from __future__ import annotations

from core.state import QAFactoryState


class UXA11yAgent:
    name = "UX/A11y Agent"

    def run(self, state: QAFactoryState) -> QAFactoryState:
        if "UX/accessibility review" not in state.automation_scope and "UI automation" not in state.automation_scope:
            return state
        state.generated_outputs["ux_a11y_checklist.md"] = """# UX / Accessibility Checklist

## Quick checks
- Main navigation is keyboard reachable.
- Important controls have accessible names.
- Form validation messages are visible and clear.
- Responsive layout works on desktop/tablet/mobile widths.
- Color contrast is acceptable for key text/buttons.
- No critical axe violations on core pages.

## Human TODO
- Compare against Figma/design links when available.
- Do not claim full WCAG compliance from smoke checks only.
"""
        state.log(f"{self.name}: generated")
        return state
