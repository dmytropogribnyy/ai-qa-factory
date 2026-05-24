from __future__ import annotations

ROUTING_CORE = ["platform_router", "job_analyzer", "capability_router", "stack_router", "pricing_advisor", "opportunity_filter", "screening_answers", "evidence_pack", "commercial_strategy", "prescreening", "project_extension", "execution_cockpit"]
TEST_DESIGN_CORE = ["qa_planner", "test_strategy", "test_plan_writer", "test_case_writer"]

WORKFLOWS: dict[str, list[str]] = {
    "prescreen": ROUTING_CORE + ["self_health_monitor", "quality_gate"],
    "filter": ROUTING_CORE + ["self_health_monitor", "quality_gate"],
    "job": ROUTING_CORE + ["proposal_writer", "technical_writing"] + TEST_DESIGN_CORE + ["dynamic_agent_factory", "self_health_monitor", "quality_gate"],
    "upwork": ROUTING_CORE + ["proposal_writer", "technical_writing"] + TEST_DESIGN_CORE[:2] + ["dynamic_agent_factory", "full_pipeline_note", "self_health_monitor", "quality_gate"],
    "audit": ROUTING_CORE + TEST_DESIGN_CORE + ["dynamic_agent_factory", "self_health_monitor", "quality_gate"],
    "plan": ["platform_router", "job_analyzer", "capability_router", "stack_router"] + TEST_DESIGN_CORE + ["dynamic_agent_factory", "self_health_monitor", "quality_gate"],
    "scaffold": ["platform_router", "job_analyzer", "capability_router", "stack_router", "qa_planner", "playwright_generator", "api_test_generator", "db_validation_agent", "ux_a11y_agent", "performance_agent", "dynamic_agent_factory", "flakiness_critic", "test_runner_note", "mcp_workflow_note", "self_health_monitor", "quality_gate"],
    "full": ROUTING_CORE + ["proposal_writer", "technical_writing"] + TEST_DESIGN_CORE + ["playwright_generator", "api_test_generator", "db_validation_agent", "ux_a11y_agent", "performance_agent", "dynamic_agent_factory", "flakiness_critic", "delivery_writer", "test_runner_note", "mcp_workflow_note", "full_pipeline_note", "self_health_monitor", "quality_gate"],
    "delivery": ["platform_router", "job_analyzer", "capability_router", "stack_router", "qa_planner", "test_strategy", "delivery_writer", "self_health_monitor", "quality_gate"],
    "test-design": ROUTING_CORE + TEST_DESIGN_CORE + ["self_health_monitor", "quality_gate"],
    "review": ["flakiness_critic", "self_health_monitor", "quality_gate"],
    "mcp-guide": ["mcp_guide"],
}
