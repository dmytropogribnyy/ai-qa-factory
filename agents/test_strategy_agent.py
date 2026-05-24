from __future__ import annotations

from core.llm_router import LLMRouter
from core.state import QAFactoryState


class TestStrategyAgent:
    """Creates a senior-level test strategy for accepted or shortlisted work.

    This is deliberately broader than Playwright. It can cover manual QA,
    API, SaaS, mobile, advisory-only stacks, technical-writing validation,
    and mixed QA delivery, while clearly marking what requires human approval.
    """

    __test__ = False
    name = "Test Strategy"

    SYSTEM = """You are a senior QA strategist creating practical freelance test strategies.
Write in English. Be concrete, risk-based and client-ready, but keep it as a draft.
Do not overpromise. Do not invent access, tooling, devices or evidence.
Separate what the Factory can do now from what Dmytro must approve or provide.
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
Input / opportunity:
{state.raw_input}

Detected context:
- Source platform: {state.source_platform}
- Opportunity type: {state.opportunity_type}
- Support level: {state.support_level}
- Recommended action: {state.recommended_action}
- System suitability: {state.system_suitability}
- Stack choice: {state.stack_choice}
- Technologies: {', '.join(state.detected_technologies) or 'not specified'}
- Risk flags: {'; '.join(state.risk_flags)}
- Required inputs: {'; '.join(state.required_inputs)}
- Evidence required: {'; '.join(state.evidence_required)}

Return a practical TEST_STRATEGY.md with these sections:
1. Strategy summary
2. Quality goals
3. Scope and non-scope
4. Risk-based priorities
5. Test levels / types: exploratory, functional, API, automation, data, mobile, performance, accessibility as applicable
6. Environment and access requirements
7. Reporting cadence and artifacts
8. Approval checkpoints
9. Exit criteria
10. What must not be claimed or executed without approval
""",
            temperature=0.23,
            max_tokens=1700,
            context=state.to_dict(),
        )
        state.generated_outputs["TEST_STRATEGY.md"] = response.text.strip() + "\n"
        self._record(state, "TEST_STRATEGY.md")
        state.log(f"{self.name}: generated")
        return state

    @staticmethod
    def _should_generate(state: QAFactoryState) -> bool:
        if state.recommended_action.startswith("skip"):
            return False
        if state.mode in {"plan", "audit", "full", "prescreen", "job", "upwork", "test-design"}:
            return True
        return any(term in state.raw_input.lower() for term in ["test strategy", "test plan", "test cases", "qa strategy", "acceptance"])

    @staticmethod
    def _record(state: QAFactoryState, artifact: str) -> None:
        if artifact not in state.test_design_artifacts:
            state.test_design_artifacts.append(artifact)
        if artifact not in state.output_pack:
            state.output_pack.append(artifact)
