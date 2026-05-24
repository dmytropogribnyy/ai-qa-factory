from __future__ import annotations

from core.state import QAFactoryState


class DBValidationAgent:
    name = "DB Validation Agent"

    def run(self, state: QAFactoryState) -> QAFactoryState:
        if "DB validation" not in state.automation_scope:
            return state
        state.generated_outputs["db_validation_plan.md"] = """# DB Validation Plan

## Use only read-only access unless the client explicitly provides a safe test DB.

Recommended checks:
- Validate critical UI actions create/update expected DB records.
- Check status transitions and timestamps.
- Verify no duplicate records for idempotent actions.
- Compare API response values against DB where useful.
- Keep SQL queries documented and non-destructive.

Human TODO:
- Confirm DB engine and credentials.
- Confirm test data reset strategy.
"""
        state.log(f"{self.name}: generated")
        return state
