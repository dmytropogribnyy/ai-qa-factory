from __future__ import annotations

from core.state import QAFactoryState

class APITestGeneratorAgent:
    name = "API Test Generator"

    def run(self, state: QAFactoryState) -> QAFactoryState:
        if "API testing" not in state.automation_scope and state.stack_choice != "api-first-with-playwright-request":
            return state
        state.generated_outputs["api_testing_notes.md"] = """# API Testing Notes

Recommended first API checks:

- Health/status endpoint
- Authentication token flow
- Critical create/read/update paths
- Negative cases for invalid payloads
- Contract/schema checks if OpenAPI is available

Use Playwright `request` for lightweight API checks in the same repository.
"""
        state.log(f"{self.name}: API testing notes generated")
        return state
