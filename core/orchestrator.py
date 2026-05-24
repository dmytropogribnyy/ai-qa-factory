from __future__ import annotations

import sys
import time
from pathlib import Path

from core.agent_registry import build_agent_registry
from core.config import Settings
from core.dialog import prompt_user_choice, prompt_user_text
from core.initial_analysis_engine import InitialAnalysisEngine
from core.llm_router import LLMRouter
from core.persistence import get_persistence
from core.quality_gate import QualityGate
from core.state import QAFactoryState, make_project_id
from core.structured_logger import StructuredLogger
from core.workflow_registry import WORKFLOWS
from tools.file_manager import FileManager
from tools.report_builder import ReportBuilder
from tools.test_runner import TestRunner


class QAFactoryOrchestrator:
    """Registry-based v5.0.8 orchestrator.

    Workflows describe *what* to run. Execution modes describe *how* to run it.
    This keeps the system extensible without turning it into an autonomous platform.
    """

    def __init__(self, settings: Settings):
        self.settings = settings
        self.router = LLMRouter(settings)
        self.engine = InitialAnalysisEngine(self.router)
        self.file_manager = FileManager(settings.output_dir)
        self.report_builder = ReportBuilder()
        self.test_runner = TestRunner()
        self.persistence = get_persistence(settings)
        self.quality_gate = QualityGate()
        self.structured_logger = StructuredLogger(settings.output_dir)
        self.agents = build_agent_registry(self.engine, self.router, self.quality_gate, persistence=self.persistence)

    def run(
        self,
        mode: str,
        raw_input: str,
        approve: bool = False,
        client_id: str | None = None,
        execution_mode: str = "auto",
        from_step: str | None = None,
        only: str | None = None,
        project_id_override: str | None = None,
        source_platform_override: str | None = None,
    ) -> QAFactoryState:
        project_id = project_id_override or make_project_id(raw_input, mode=mode)
        state = self._initial_or_loaded_state(project_id, mode, raw_input, client_id, from_step, only)
        state.execution_mode = execution_mode
        if source_platform_override:
            state.source_platform = source_platform_override
            state.client_context["source_platform_override"] = source_platform_override
        if approve:
            state.approval_status = "approved_by_user"
        if client_id:
            state.client_id = client_id
            state.client_context["memory"] = self.persistence.load_client(client_id)

        state.log(f"Workflow started in mode={mode}, execution_mode={execution_mode}")
        dry_run = execution_mode == "dry-run"
        if not dry_run:
            self.structured_logger.log(state.project_id, "workflow_start", mode=mode, execution_mode=execution_mode)
        state = self._run_triggered_pre_run_prompts(state, interactive=sys.stdin.isatty())
        state = self._run_workflow(state, mode, execution_mode=execution_mode, from_step=from_step, only=only, dry_run=dry_run)
        state = self._human_approval_checkpoint(state)

        if not dry_run:
            state = self._save_outputs(state)
            self.persistence.save_project(state.project_id, state.to_dict())
        else:
            state.log("Dry-run: final outputs were not written to disk")
        return state

    def _initial_or_loaded_state(
        self,
        project_id: str,
        mode: str,
        raw_input: str,
        client_id: str | None,
        from_step: str | None,
        only: str | None,
    ) -> QAFactoryState:
        if from_step or only:
            loaded = self._load_state(project_id)
            if loaded:
                loaded.raw_input = loaded.raw_input or raw_input
                loaded.mode = mode
                return loaded
        return QAFactoryState(project_id=project_id, mode=mode, raw_input=raw_input, client_id=client_id)

    def _load_state(self, project_id: str) -> QAFactoryState | None:
        data = self.persistence.load_project(project_id)
        if data:
            return QAFactoryState.from_dict(data)
        return None

    def _run_triggered_pre_run_prompts(self, state: QAFactoryState, interactive: bool) -> QAFactoryState:
        """Ask only high-value safety/scope questions before running agents.

        In non-interactive contexts we never block CI/tests; triggers are recorded as
        unanswered and surfaced in an artifact for Dmytro's manual review.
        """
        text = state.raw_input.lower()
        triggers: list[tuple[str, str, list[str], list[str]]] = [
            (
                "payment_sandbox",
                "Payment/checkout terms detected. Confirm testing will happen only in sandbox/staging with test cards and no real charges.",
                ["stripe", "checkout", "payment", "subscription", "invoice", "billing"],
                ["confirmed_sandbox", "not_confirmed", "unclear"],
            ),
            (
                "production_safety",
                "Production/live environment language detected. Confirm whether automation must avoid production and use staging/test data only.",
                ["production", "live", "live site", "real users", "real customers", "prod"],
                ["staging_only", "production_read_only", "unclear"],
            ),
            (
                "urgency_scope",
                "Urgency language detected. Clarify whether this is truly urgent or a negotiation signal, and keep the first milestone small.",
                ["asap", "urgent", "by friday", "today", "tomorrow", "immediately"],
                ["really_urgent", "probably_tactic", "unclear"],
            ),
        ]

        answers: dict[str, str] = {}
        lines = ["# Triggered Pre-run Prompts", ""]
        for key, question, keywords, choices in triggers:
            if not any(keyword in text for keyword in keywords):
                continue
            if interactive:
                answer = prompt_user_choice(question, choices, default=choices[-1])
            else:
                answer = "not_asked_non_interactive"
            answers[key] = answer
            lines.append(f"- **{key}:** {question}")
            lines.append(f"  - Answer: `{answer}`")

        if answers:
            state.triggered_prompts_answers.update(answers)
            state.client_context["triggered_prompts_answers"] = dict(state.triggered_prompts_answers)
            state.generated_outputs["triggered_pre_run_prompts.md"] = "\n".join(lines) + "\n"
            state.log(f"Triggered pre-run prompts recorded: {', '.join(answers.keys())}")
        return state

    def _run_workflow(
        self,
        state: QAFactoryState,
        mode: str,
        execution_mode: str = "auto",
        from_step: str | None = None,
        only: str | None = None,
        dry_run: bool = False,
    ) -> QAFactoryState:
        workflow = WORKFLOWS.get(mode) or WORKFLOWS["plan"]
        agents_to_run = self._select_agents(workflow, from_step=from_step, only=only)
        interactive_step = execution_mode == "step" and sys.stdin.isatty()
        if execution_mode == "step" and not interactive_step:
            state.log("Step mode requested in non-interactive terminal; running without pauses.")

        for agent_key in agents_to_run:
            if agent_key == "quality_gate" and state.approval_status != "approved_by_user":
                # Make the review note visible to QualityGate before it evaluates outputs.
                state.generated_outputs.setdefault("HUMAN_REVIEW_REQUIRED.md", self._human_review_template(state))

            agent = self.agents[agent_key]
            if interactive_step:
                decision = prompt_user_choice(f"Next agent: {agent_key}", ["continue", "skip", "quit"], default="continue")
                if decision == "skip":
                    state.log(f"Step mode: skipped {agent_key}")
                    continue
                if decision == "quit":
                    state.log(f"Step mode: stopped before {agent_key}")
                    break

            state = self._run_agent(agent_key, agent, state)

            if interactive_step:
                while True:
                    decision = prompt_user_choice(
                        f"{agent_key} completed. What next?",
                        ["continue", "redo", "skip", "quit"],
                        default="continue",
                    )
                    if decision == "continue" or decision == "skip":
                        break
                    if decision == "quit":
                        return state
                    if decision == "redo":
                        feedback = prompt_user_text("Feedback for redo", default="Regenerate with a more client-specific, concise version.")
                        state.agent_feedback.setdefault(agent_key, []).append(feedback)
                        state.client_context["latest_inline_feedback"] = {"agent": agent_key, "feedback": feedback}
                        state = self._run_agent(agent_key, agent, state)

            if not dry_run:
                self._save_snapshot(state, agent_key)

        return state

    @staticmethod
    def _select_agents(workflow: list[str], from_step: str | None = None, only: str | None = None) -> list[str]:
        if only:
            if only not in workflow:
                return [only]
            return [only]
        if from_step:
            if from_step not in workflow:
                raise ValueError(f"Agent '{from_step}' is not in this workflow: {workflow}")
            return workflow[workflow.index(from_step):]
        return workflow

    def _run_agent(self, agent_key: str, agent, state: QAFactoryState) -> QAFactoryState:
        started = time.perf_counter()
        before_keys = set(state.generated_outputs.keys())
        before_llm_calls = self.router.call_count
        if state.execution_mode != "dry-run":
            self.structured_logger.log(state.project_id, "agent_start", agent=agent_key, execution_mode=state.execution_mode)
        try:
            state = agent.run(state)
            duration_ms = round((time.perf_counter() - started) * 1000, 2)
            after_keys = set(state.generated_outputs.keys())
            llm_response = self.router.last_response if self.router.call_count > before_llm_calls else None
            if state.execution_mode != "dry-run":
                self.structured_logger.log(
                    state.project_id,
                    "agent_end",
                    agent=agent_key,
                    duration_ms=duration_ms,
                    new_outputs=sorted(after_keys - before_keys),
                    output_count=len(after_keys),
                    model_alias=getattr(llm_response, "model_alias", None),
                    model_name=getattr(llm_response, "model", None),
                    used_fallback=getattr(llm_response, "used_fallback", None),
                    tokens_prompt=getattr(llm_response, "prompt_tokens", None),
                    tokens_completion=getattr(llm_response, "completion_tokens", None),
                    tokens_total=getattr(llm_response, "total_tokens", None),
                    cost_usd=getattr(llm_response, "cost_usd", None),
                    reasoning_effort=getattr(llm_response, "reasoning_effort", None),
                )
            return state
        except Exception as exc:
            if state.execution_mode != "dry-run":
                self.structured_logger.log(state.project_id, "agent_error", agent=agent_key, error=str(exc))
            raise

    def _save_snapshot(self, state: QAFactoryState, agent_key: str) -> Path:
        snapshot_rel = f".snapshots/state_after_{agent_key}.json"
        self.file_manager.write_many(state.project_id, {snapshot_rel: state.to_json()})
        state.state_snapshots_path = str(self.settings.output_dir / state.project_id / ".snapshots")
        self.structured_logger.log(state.project_id, "snapshot_saved", agent=agent_key, path=snapshot_rel)
        return self.settings.output_dir / state.project_id / snapshot_rel

    def _human_approval_checkpoint(self, state: QAFactoryState) -> QAFactoryState:
        if state.approval_status != "approved_by_user":
            state.approval_status = "needs_human_review"
            state.next_action = "review_outputs_before_client_delivery"
            state.generated_outputs["HUMAN_REVIEW_REQUIRED.md"] = self._human_review_template(state)
        else:
            state.next_action = "ready_for_delivery_after_final_manual_check"
        return state

    @staticmethod
    def _human_review_template(state: QAFactoryState) -> str:
        return f"""# Human Review Required

Before sending anything to a client, check:

1. Business logic and assumptions.
2. Placeholder URLs, credentials, locators and selectors.
3. Auth, payment and security flows. Use sandbox/staging only.
4. Test data and environment safety.
5. Scope, tone and promises in proposal/delivery.
6. Pricing and milestone suggestion: {state.suggested_price or 'not generated'} / {state.suggested_milestone or 'not generated'}.
7. Quality gate warnings in `QUALITY_GATE_REPORT.md`.
8. Suggested specialists in `suggested_specialists.md`.

AI drafts. Senior QA decides.
"""

    def _save_outputs(self, state: QAFactoryState) -> QAFactoryState:
        state.generated_outputs["READ_ME_FIRST.md"] = self.report_builder.build_read_me_first(state)
        state.generated_outputs["SUMMARY.md"] = self.report_builder.build_summary(state)
        state.generated_outputs["state.json"] = state.to_json()
        output_path = self.file_manager.write_many(state.project_id, state.generated_outputs)
        state.log(f"Outputs saved to {output_path}")
        self.structured_logger.log(state.project_id, "outputs_saved", output_path=str(output_path))
        return state
