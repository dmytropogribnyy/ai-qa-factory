"""MCP + IDE integration audit (Final Phase II).

A manifest entry is NOT a working integration. This package validates the references-only MCP
manifest (disabled by default), classifies each integration honestly, and enforces fail-closed
rules on MCP tools/output. Agent-only servers are never available to the standalone Factory
process. No live MCP call, paid session, repository/ticket write, message send, or financial
operation is performed here or required by CI.
"""
