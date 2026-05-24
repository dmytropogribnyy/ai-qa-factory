from __future__ import annotations

from core.llm_router import LLMRouter
from core.state import QAFactoryState


class FlakinessCriticAgent:
    name = "Flakiness Critic"
    SYSTEM_PROMPT = (
        "You are a strict senior test automation reviewer. Review QA automation code and plans for flakiness, "
        "weak assertions, brittle selectors, hidden dependencies, unsafe test data, missing cleanup, and CI risks. "
        "Return prioritized fixes and concrete examples. Avoid generic advice."
    )

    def __init__(self, router: LLMRouter):
        self.router = router

    def run(self, state: QAFactoryState) -> QAFactoryState:
        snippets = []
        for filename, content in state.generated_outputs.items():
            if filename.endswith((".ts", ".js", ".py", ".java", ".md", ".yml", ".yaml")):
                snippets.append(f"### File: {filename}\n{content[:1800]}")
        joined_snippets = "\n\n".join(snippets) if snippets else "No generated files yet. Review the raw input instead."

        prompt = f"""
Raw input / code to review:
{state.raw_input}

Generated artifacts to review:
{joined_snippets}

Return a structured review with:
1. Critical issues
2. Flaky locator/wait risks
3. Missing assertions
4. Test data and isolation risks
5. API/DB/CI/reporting risks if applicable
6. Prioritized fixes with examples
7. What must be manually verified before client delivery
"""
        response = self.router.complete("review", self.SYSTEM_PROMPT, prompt, temperature=0.2, max_tokens=1600)
        state.generated_outputs["flakiness_review.md"] = response.text
        state.log(f"{self.name}: review generated with {response.model}")
        return state
