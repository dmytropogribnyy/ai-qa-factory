from __future__ import annotations

from core.initial_analysis_engine import InitialAnalysisEngine
from core.state import QAFactoryState


class JobAnalyzerAgent:
    name = "Job Analyzer"

    def __init__(self, engine: InitialAnalysisEngine):
        self.engine = engine

    def run(self, state: QAFactoryState) -> QAFactoryState:
        analysis = self.engine.analyze(state.raw_input, state.mode)
        state.task_type = analysis["task_type"]
        state.stack_choice = analysis["stack_choice"]
        state.project_type = analysis["project_type"]
        state.requirements = analysis["requirements"]
        state.risk_flags = analysis["risk_flags"]
        state.clarifications = analysis["clarifications"]
        state.fit_score = analysis["fit_score"]
        state.detected_technologies = analysis["detected_technologies"]
        state.automation_scope = analysis["automation_scope"]
        state.prompt_profile = analysis.get("prompt_profile", "qa_automation")
        state.client_context.update(analysis["client_context"])
        state.generated_outputs["analysis.md"] = self._render_analysis(state)
        state.generated_outputs["client_questions.md"] = self._render_questions(state)
        state.generated_outputs["red_flags.md"] = self._render_risks(state)
        state.log(f"{self.name}: completed | fit={state.fit_score} | stack={state.stack_choice} | profile={state.prompt_profile}")
        return state

    @staticmethod
    def _render_analysis(state: QAFactoryState) -> str:
        return f"""# Initial Analysis Report

**Project ID:** {state.project_id}
**Project Type:** {state.project_type}
**Fit Score:** {state.fit_score}/100
**Recommended Stack:** {state.stack_choice}
**Prompt Profile:** {state.prompt_profile}

## Detected Technologies
{chr(10).join(f"- {tech}" for tech in state.detected_technologies) or "- Not specified"}

## Automation Scope
{chr(10).join(f"- {scope}" for scope in state.automation_scope) or "- Not specified"}

## Recommended First Milestone
{state.client_context.get("recommended_first_milestone", "Not specified")}

## LLM Deep Analysis
{state.client_context.get("llm_deep_analysis", "No LLM note available.")}
"""

    @staticmethod
    def _render_questions(state: QAFactoryState) -> str:
        return "# Client Questions\n\n" + "\n".join(f"- {q}" for q in state.clarifications) + "\n"

    @staticmethod
    def _render_risks(state: QAFactoryState) -> str:
        return "# Red Flags / Risks\n\n" + "\n".join(f"- {r}" for r in state.risk_flags) + "\n"
