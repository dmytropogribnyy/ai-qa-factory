from __future__ import annotations


class PlaywrightMCPTool:
    """Practical stub for future Playwright MCP integration.

    This intentionally does not attempt to control the browser yet. It provides a
    structured workflow that can later be replaced with actual MCP calls.
    """

    def recommended_workflow(self) -> str:
        return """# Playwright MCP / Browser Exploration Workflow

Use this before finalizing generated Playwright tests.

## Goal

Convert AI-generated placeholders into stable real-world locators and flows.

## Steps

1. Generate scaffold with `python main.py scaffold --input sample_inputs/client_brief.txt`.
2. Open the target app with Playwright MCP or `npx playwright codegen`.
3. Capture the accessibility structure of critical pages.
4. Record stable locators:
   - roles
   - labels
   - test IDs
   - visible names
5. Replace placeholder locators in generated tests.
6. Run the test suite.
7. Review flaky risks with `python main.py review --input <test-file>`.

## Commands

```bash
npx playwright codegen https://example.com
npx playwright test --headed
npx playwright test --trace on
npx playwright show-report
```

## Human approval required

Do not send generated tests to a client until selectors, auth, test data and business assertions are reviewed.
"""
