# LangGraph v5 Note

v5.0.8 Model Routing Profiles remains registry-based rather than full LangGraph.

Why: current workflows are still mostly linear and registry-based routing is faster to operate.

When to migrate to LangGraph:

- more than 15 agents;
- conditional loops and retry decisions are common;
- real MCP/browser exploration feeds back into generation;
- per-client memory changes route decisions;
- human approval checkpoints become multi-step.

Until then, this registry structure is intentionally LangGraph-ready but simpler.
