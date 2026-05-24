from __future__ import annotations

from core.llm_router import LLMRouter
from core.state import QAFactoryState


class TestPlanWriterAgent:
    """Generates a concrete execution-oriented test plan."""

    __test__ = False
    name = "Test Plan Writer"

    SYSTEM = """You are a senior QA lead writing a practical test plan.
Keep it concise, operational and easy to execute. The plan is a draft for human review.
Do not invent credentials, links, devices, tools, project access or client approval.
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
Client request / project brief:
{state.raw_input}

Context:
- Opportunity type: {state.opportunity_type}
- Recommended action: {state.recommended_action}
- Support level: {state.support_level}
- Stack: {state.stack_choice}
- Critical scope: {', '.join(state.automation_scope)}
- Risks: {'; '.join(state.risk_flags)}
- Required inputs: {'; '.join(state.required_inputs)}

Return TEST_PLAN.md with:
1. Objective
2. Assumptions
3. In-scope areas
4. Out-of-scope areas
5. Test environments and data needed
6. Test areas / modules
7. Priority flows
8. Execution order
9. Defect reporting format
10. Daily/weekly delivery rhythm
11. Open questions before execution
""",
            temperature=0.22,
            max_tokens=1600,
            context=state.to_dict(),
        )
        state.generated_outputs["TEST_PLAN.md"] = response.text.strip() + "\n"
        self._record(state, "TEST_PLAN.md")
        state.log(f"{self.name}: generated")
        return state

    @staticmethod
    def _should_generate(state: QAFactoryState) -> bool:
        if state.recommended_action.startswith("skip"):
            return False
        if state.mode in {"plan", "audit", "full", "prescreen", "job", "upwork", "test-design"}:
            return True
        text = state.raw_input.lower()
        return any(term in text for term in ["test plan", "test cases", "qa plan", "acceptance", "regression"])

    @staticmethod
    def _record(state: QAFactoryState, artifact: str) -> None:
        if artifact not in state.test_design_artifacts:
            state.test_design_artifacts.append(artifact)
        if artifact not in state.output_pack:
            state.output_pack.append(artifact)
