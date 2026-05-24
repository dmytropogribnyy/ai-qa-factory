# Playwright MCP Practical Guide

This version does not perform real MCP automation yet. Use this workflow manually with VS Code/Cursor/Playwright MCP.

## Workflow

1. Open the client staging URL with Playwright MCP / browser tooling.
2. Capture accessibility snapshot for key pages.
3. Identify stable role/name/test-id locators.
4. Replace placeholder locators in generated scaffold.
5. Run a small smoke suite locally.
6. Review trace/screenshots before delivery.

## Locator priority

1. `getByRole()` with accessible name.
2. `getByLabel()` for forms.
3. `getByTestId()` if app has stable test IDs.
4. CSS only if semantic locators are not available.
5. XPath only as last resort.

## Do not

- Do not generate large suites before validating selectors.
- Do not rely on screenshots only.
- Do not run against production payment flows.
