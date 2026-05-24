from __future__ import annotations

from core.state import QAFactoryState
from tools.playwright_mcp_tool import PlaywrightMCPTool


class TestRunnerNoteAgent:
    name = "Test Runner Note"

    def run(self, state: QAFactoryState) -> QAFactoryState:
        state.generated_outputs["TEST_RUNNER_NOTE.md"] = """# Safe Test Runner

The generated Playwright scaffold is saved as files, but tests are not executed automatically.

Recommended flow from the repository root:

```bash
cd outputs/<project_id>/framework
npm install
npx playwright install
npm test
```

Or use the safe runner from the repository root:

```bash
python main.py run-tests --project-path outputs/<project_id>/framework --kind playwright
```

Do not run generated tests against production systems. Review URLs, credentials, selectors and business assertions before execution.
"""
        state.log(f"{self.name}: generated")
        return state


class PlaywrightMCPWorkflowAgent:
    name = "Playwright MCP Workflow Note"

    def run(self, state: QAFactoryState) -> QAFactoryState:
        state.generated_outputs["PLAYWRIGHT_MCP_WORKFLOW.md"] = PlaywrightMCPTool().recommended_workflow()
        state.log(f"{self.name}: generated")
        return state


class FullPipelineNoteAgent:
    name = "Full Pipeline Note"

    def run(self, state: QAFactoryState) -> QAFactoryState:
        state.generated_outputs["FULL_PIPELINE_NOTE.md"] = (
            "# Full Pipeline Note\n\n"
            "This package is for Dmytro's internal review: proposal, QA plan, pricing, scaffold/review if applicable and delivery support. "
            "Do not send raw outputs to clients without manual editing.\n"
        )
        state.log(f"{self.name}: generated")
        return state
