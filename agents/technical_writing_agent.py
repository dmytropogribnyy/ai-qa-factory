from __future__ import annotations

from core.state import QAFactoryState


class TechnicalWritingAgent:
    """Adjacent branch for SaaS/QA/docs writing opportunities."""
    name = "Technical Writing"

    def run(self, state: QAFactoryState) -> QAFactoryState:
        if state.opportunity_type != "technical_writing" and "technical_writing" not in state.prompt_profile:
            return state
        state.generated_outputs["documentation_plan.md"] = self._documentation_plan(state)
        state.generated_outputs["sample_doc_rewrite.md"] = self._sample_rewrite_note(state)
        state.log(f"{self.name}: generated documentation planning artifacts")
        return state

    @staticmethod
    def _documentation_plan(state: QAFactoryState) -> str:
        return f"""# Documentation Plan

**Opportunity type:** {state.opportunity_type}
**Support level:** {state.support_level}

## Recommended scope
- Audit current documentation/source material.
- Identify user roles, core workflows and missing docs.
- Create or migrate articles with clear structure: purpose, prerequisites, steps, expected result, troubleshooting.
- Keep AI assistance human-led and compliant with the platform/client AI policy.

## Questions for client/editor
- What source material exists today?
- Is this migration, rewrite, net-new documentation, or all three?
- Who is the primary reader: developer, admin, end user, buyer, support team?
- What style guide and CMS/help-center workflow should be followed?

## Positioning
{state.client_context.get('safe_positioning_angle', 'SaaS/QA technical documentation with clear structure and user-focused accuracy.')}
"""

    @staticmethod
    def _sample_rewrite_note(state: QAFactoryState) -> str:
        return """# Sample Doc Rewrite — Placeholder

Do not generate fake client documentation samples.

Before applying, prepare one real or self-authored sample such as:

- a README/setup guide cleanup;
- a QA audit summary rewritten for a product team;
- a help-center style article;
- a Playwright/CI troubleshooting guide.

Use this sample as proof of clarity, structure and technical accuracy.
"""
