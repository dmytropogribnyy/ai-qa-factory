"""Operator Dashboard application layer (v3.1).

A thin read-model + actions layer that COMPOSES the existing core services (ProjectIndex,
WorkExecutionService, ClientWorkService, ScoutService, ToolBroker). It creates no second project
store, evidence store, state machine, or database - it is the stable application-facing contract the
single dashboard (`core/scout/dashboard.py`) renders and the guarded HTTP mutations call. The UI
never parses raw JSON files or performs state transitions itself; it consumes these DTOs and posts
to guarded endpoints that call the same services the CLI uses.
"""
