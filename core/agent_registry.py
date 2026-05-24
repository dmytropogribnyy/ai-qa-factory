from __future__ import annotations

from typing import Dict

from agents.platform_router import PlatformRouterAgent
from agents.capability_router import CapabilityRouterAgent
from agents.screening_answers import ScreeningAnswersAgent
from agents.evidence_pack import EvidencePackAgent
from agents.opportunity_filter import OpportunityFilterAgent
from agents.commercial_strategy import CommercialStrategyAgent
from agents.technical_writing_agent import TechnicalWritingAgent
from agents.test_strategy_agent import TestStrategyAgent
from agents.test_plan_writer import TestPlanWriterAgent
from agents.test_case_writer import TestCaseWriterAgent
from agents.prescreening import PreScreeningAgent
from agents.project_extension import ProjectExtensionAgent
from agents.self_health_monitor import SelfHealthMonitorAgent
from agents.execution_cockpit import ExecutionCockpitAgent
from agents.api_test_generator import APITestGeneratorAgent
from agents.db_validation_agent import DBValidationAgent
from agents.delivery_writer import DeliveryWriterAgent
from agents.dynamic_agent_factory import DynamicAgentFactory
from agents.flakiness_critic import FlakinessCriticAgent
from agents.job_analyzer import JobAnalyzerAgent
from agents.performance_agent import PerformanceAgent
from agents.notes_agents import FullPipelineNoteAgent, PlaywrightMCPWorkflowAgent, TestRunnerNoteAgent
from agents.playwright_generator import PlaywrightGeneratorAgent
from agents.pricing_advisor import PricingAdvisorAgent
from agents.proposal_writer import ProposalWriterAgent
from agents.qa_planner import QAPlannerAgent
from agents.stack_router import StackRouterAgent
from agents.ux_a11y_agent import UXA11yAgent
from core.quality_gate import QualityGate


def build_agent_registry(engine, router, quality_gate: QualityGate, persistence=None) -> Dict[str, object]:
    """Single place where executable agents are registered.

    Adding a new agent should require creating the class and adding one entry here,
    not modifying the orchestrator loop.
    """
    return {
        "platform_router": PlatformRouterAgent(),
        "capability_router": CapabilityRouterAgent(),
        "opportunity_filter": OpportunityFilterAgent(),
        "screening_answers": ScreeningAnswersAgent(),
        "evidence_pack": EvidencePackAgent(),
        "commercial_strategy": CommercialStrategyAgent(),
        "technical_writing": TechnicalWritingAgent(),
        "test_strategy": TestStrategyAgent(router),
        "test_plan_writer": TestPlanWriterAgent(router),
        "test_case_writer": TestCaseWriterAgent(router),
        "prescreening": PreScreeningAgent(),
        "project_extension": ProjectExtensionAgent(),
        "self_health_monitor": SelfHealthMonitorAgent(),
        "execution_cockpit": ExecutionCockpitAgent(),
        "job_analyzer": JobAnalyzerAgent(engine),
        "stack_router": StackRouterAgent(),
        "pricing_advisor": PricingAdvisorAgent(persistence=persistence),
        "proposal_writer": ProposalWriterAgent(router),
        "qa_planner": QAPlannerAgent(router),
        "playwright_generator": PlaywrightGeneratorAgent(router),
        "api_test_generator": APITestGeneratorAgent(),
        "db_validation_agent": DBValidationAgent(),
        "ux_a11y_agent": UXA11yAgent(),
        "performance_agent": PerformanceAgent(),
        "dynamic_agent_factory": DynamicAgentFactory(),
        "flakiness_critic": FlakinessCriticAgent(router),
        "delivery_writer": DeliveryWriterAgent(router),
        "test_runner_note": TestRunnerNoteAgent(),
        "mcp_workflow_note": PlaywrightMCPWorkflowAgent(),
        "full_pipeline_note": FullPipelineNoteAgent(),
        "mcp_guide": PlaywrightMCPWorkflowAgent(),
        "quality_gate": quality_gate,
    }
