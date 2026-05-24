from __future__ import annotations

from core.llm_router import LLMRouter
from core.prompt_loader import PromptLoader
from core.state import QAFactoryState


class QAPlannerAgent:
    name = "QA Planner"

    SYSTEM = """You are a senior QA strategist.
Create practical, risk-based QA plans for freelance delivery.
Write in English. Be concrete and milestone-oriented. Separate manual, automation, API, DB, performance and accessibility scope.
Do not overpromise.
"""

    def __init__(self, router: LLMRouter):
        self.router = router
        self.prompts = PromptLoader()

    def run(self, state: QAFactoryState) -> QAFactoryState:
        profile_prompt = self.prompts.load("qa_plan", state.prompt_profile, fallback="default")
        response = self.router.complete(
            "plan",
            self.SYSTEM + "\n\n" + profile_prompt,
            f"""
Client request:
{state.raw_input}

Context:
- Project type: {state.project_type}
- Stack: {state.stack_choice}
- Scope: {', '.join(state.automation_scope)}
- Technologies: {', '.join(state.detected_technologies) or 'not specified'}
- Risks: {'; '.join(state.risk_flags)}
- Clarifications: {'; '.join(state.clarifications)}
- Suggested first milestone: {state.suggested_milestone or state.client_context.get('recommended_first_milestone')}
- Inline feedback: {state.client_context.get('latest_inline_feedback') if state.client_context.get('latest_inline_feedback', {}).get('agent') == 'qa_planner' else 'None'}

Return sections:
1. Scope and assumptions
2. Critical flows in priority order
3. Risk-based priorities
4. Manual exploratory checks
5. Automation candidates
6. API / DB / Performance / Accessibility notes where applicable
7. First paid milestone recommendation
8. Questions before final scoping
""",
            temperature=0.26,
            max_tokens=1600,
            context=state.to_dict(),
        )
        state.generated_outputs["qa_plan.md"] = response.text
        state.log(f"{self.name}: generated")
        return state
