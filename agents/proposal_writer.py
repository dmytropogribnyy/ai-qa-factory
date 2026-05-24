from __future__ import annotations

from core.llm_router import LLMRouter
from core.prompt_loader import PromptLoader
from core.state import QAFactoryState


class ProposalWriterAgent:
    name = "Proposal Writer"

    BASE_SYSTEM = """You are a senior QA automation freelancer writing Upwork proposals.
Write in English. Be concise, specific and client-focused.
Avoid generic phrases like "I'm excited", "I believe", "Dear sir".
Focus on a low-risk first step, concrete QA value, and 1-2 smart questions.
Never claim guaranteed results or invent experience details.
"""

    def __init__(self, router: LLMRouter):
        self.router = router
        self.prompts = PromptLoader()

    def run(self, state: QAFactoryState) -> QAFactoryState:
        profile_prompt = self.prompts.load("proposal", state.prompt_profile, fallback="qa_automation")
        context = state.to_dict()
        response = self.router.complete(
            task_type="proposal",
            system_prompt=self.BASE_SYSTEM + "\n\n" + profile_prompt,
            user_prompt=f"""
Client / Upwork job:
{state.raw_input}

Detected context:
- Project type: {state.project_type}
- Stack: {state.stack_choice}
- Fit score: {state.fit_score}/100
- Proposal angle: {state.client_context.get('proposal_angle')}
- Suggested price: {state.suggested_price}
- Suggested first milestone: {state.suggested_milestone or state.client_context.get('recommended_first_milestone')}
- Risks: {'; '.join(state.risk_flags)}
- Questions to ask: {'; '.join(state.clarifications[:5])}
- Mandatory keywords: {', '.join(state.mandatory_keywords) or 'None'}
- Recommended action: {state.recommended_action}
- Support level: {state.support_level}

Inline feedback from Dmytro, if any:
{state.client_context.get('latest_inline_feedback') if state.client_context.get('latest_inline_feedback', {}).get('agent') == 'proposal_writer' else 'None'}

Write a 120-170 word Upwork proposal.
If mandatory opening keywords are present in context, start exactly with the required keyword and then continue naturally.
Structure:
1. First sentence shows you understand the client's problem.
2. One paragraph with relevant approach and stack.
3. Low-risk first step.
4. 1-2 specific questions.
""",
            temperature=0.22,
            max_tokens=950,
            context=context,
        )
        proposal = response.text.strip()
        if state.mandatory_keywords and proposal and not proposal.lower().startswith(state.mandatory_keywords[0].lower()):
            proposal = f"{state.mandatory_keywords[0]}\n\n{proposal}"
        state.generated_outputs["proposal.md"] = proposal
        state.log(f"{self.name}: generated using {response.model}, profile={state.prompt_profile}")
        return state
