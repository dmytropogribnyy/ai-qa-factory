from __future__ import annotations

from core.llm_router import LLMRouter
from core.state import QAFactoryState


class DeliveryWriterAgent:
    name = "Delivery Writer"
    SYSTEM_PROMPT = (
        "You write concise client delivery notes for QA automation work. Be clear, professional, "
        "and explicit about what was done, what remains, what requires client confirmation, and the next milestone."
    )

    def __init__(self, router: LLMRouter):
        self.router = router

    def run(self, state: QAFactoryState) -> QAFactoryState:
        prompt = f"""
Create a client-ready delivery note for this QA project.

Input:
{state.raw_input}

Context:
- Project type: {state.project_type}
- Stack: {state.stack_choice}
- Scope: {', '.join(state.automation_scope)}
- Risks: {'; '.join(state.risk_flags)}
- Outputs available: {', '.join(state.generated_outputs.keys())}

Include:
1. Completed work
2. Key findings / risks
3. How to run or use deliverables
4. Items requiring client confirmation
5. Suggested next milestone
6. Clear note that final business validation remains with the product owner/client
"""
        response = self.router.complete("delivery", self.SYSTEM_PROMPT, prompt, max_tokens=1200)
        state.generated_outputs["delivery_note.md"] = response.text
        state.log(f"{self.name}: delivery note generated")
        return state
