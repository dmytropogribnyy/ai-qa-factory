from __future__ import annotations

from core.llm_router import LLMRouter
from core.state import QAFactoryState


class TestCaseWriterAgent:
    """Creates human-readable test cases/checklists from a job post or brief."""

    __test__ = False
    name = "Test Case Writer"

    SYSTEM = """You are a senior QA analyst writing clear, executable test cases.
Write in English. Prefer practical, human-readable tables/checklists.
Include expected results and notes on data/environment. Keep all cases as drafts.
Never invent live credentials, user data, payments, personal data or privileged access.
"""

    def __init__(self, router: LLMRouter):
        self.router = router

    def run(self, state: QAFactoryState) -> QAFactoryState:
        if not self._should_generate(state):
            return state
        response = self.router.complete(
            "plan",
            self.SYSTEM,
            f"""
Input / project brief:
{state.raw_input}

Context:
- Opportunity type: {state.opportunity_type}
- Stack: {state.stack_choice}
- Scope: {', '.join(state.automation_scope)}
- Technologies: {', '.join(state.detected_technologies) or 'not specified'}
- Risks: {'; '.join(state.risk_flags)}
- Required inputs: {'; '.join(state.required_inputs)}

Create TEST_CASES.md with:
1. Smoke checklist
2. Critical functional test cases in table format: ID, priority, area, precondition, steps, expected result, notes
3. Negative / edge cases
4. API or data validation cases if applicable
5. Automation candidates
6. Manual-only exploratory charters
7. Missing information that blocks finalization
Limit to a useful starter set, not an exhaustive fantasy suite.
""",
            temperature=0.22,
            max_tokens=1800,
            context=state.to_dict(),
        )
        state.generated_outputs["TEST_CASES.md"] = response.text.strip() + "\n"
        self._record(state, "TEST_CASES.md")
        state.log(f"{self.name}: generated")
        return state

    @staticmethod
    def _should_generate(state: QAFactoryState) -> bool:
        if state.recommended_action.startswith("skip"):
            return False
        text = state.raw_input.lower()
        if state.mode in {"plan", "audit", "full", "test-design"}:
            return True
        return any(term in text for term in ["test cases", "test case", "acceptance criteria", "regression", "checklist", "qa cases"])

    @staticmethod
    def _record(state: QAFactoryState, artifact: str) -> None:
        if artifact not in state.test_design_artifacts:
            state.test_design_artifacts.append(artifact)
        if artifact not in state.output_pack:
            state.output_pack.append(artifact)
