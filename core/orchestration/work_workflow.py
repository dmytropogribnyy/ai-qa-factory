"""WorkPlanningWorkflow — Phase 8.1 (planning-only orchestrator).

Ties the deterministic components into a single planning-only run and publishes the
artifact set atomically. Performs NO LLM calls, NO network, NO subprocess, NO browser,
NO MCP calls. Produces a plan for human review; never executes it.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List

from core.schemas.work_packet import WorkPacket
from core.schemas.work_run_state import WorkRunState
from core.orchestration.providers import ClockProvider, IdProvider
from core.orchestration.universal_intake import UniversalWorkIntake
from core.orchestration.profile_selector import UniversalProfileSelector
from core.orchestration.requirement_extractor import RequirementExtractor
from core.orchestration.missing_information_analyzer import MissingInformationAnalyzer
from core.orchestration.capability_registry import CapabilityRegistry
from core.orchestration.capability_planner import CapabilityPlanner
from core.orchestration.toolchain_composer import ToolchainComposer
from core.orchestration.work_state_manager import WorkStateManager
from core.orchestration.mcp_snapshot import build_configured_servers_snapshot
from core.orchestration.content_safety import ArtifactSafeWriter

_ARK_DIR = "40_ark_work"


class WorkPlanningError(Exception):
    """Raised when planning cannot proceed safely (e.g. project-id collision)."""


@dataclass
class WorkPlanningResult:
    project_id: str
    profile: str
    final_status: str
    target_dir: str
    artifacts: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    secrets_redacted: bool = False
    missing_information_count: int = 0
    approvals_required_count: int = 0
    planning_only: bool = True


def _dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True)


def input_fingerprint(redacted_text: str, source_platform: str, profile_override: str | None) -> str:
    """Deterministic digest of the REDACTED, normalised input + platform + profile override.

    Computed only from already-redacted text (never raw input), so it cannot expose secrets.
    Line endings and trailing whitespace are normalised so cosmetic edits don't change identity.
    """
    norm = (redacted_text or "").replace("\r\n", "\n").replace("\r", "\n")
    norm = "\n".join(line.rstrip() for line in norm.split("\n")).strip()
    payload = f"{norm}\x00{source_platform or ''}\x00{profile_override or ''}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class WorkPlanningWorkflow:
    """Deterministic, planning-only universal work entrypoint."""

    def __init__(
        self,
        clock: ClockProvider,
        ids: IdProvider,
        output_dir: Path,
        registry: CapabilityRegistry | None = None,
    ) -> None:
        self._clock = clock
        self._ids = ids
        self._output_dir = Path(output_dir)
        self._registry = (registry or CapabilityRegistry()).load()
        self._state_mgr = WorkStateManager(clock)

    def run(
        self, raw_text: str, project_id: str, source_platform: str = "unknown",
        profile_override: str | None = None, fresh_only: bool = False,
    ) -> WorkPlanningResult:
        now = self._clock.now_iso()

        # 1. Run state (RECEIVED)
        state = WorkRunState(project_id=project_id, status="RECEIVED", owner_agent="cli")
        state.run_idempotency_key = self._ids.new_id()
        state.updated_at = now

        # 2. Intake (deterministic, redacted, no LLM/network)
        intake = UniversalWorkIntake(self._clock, self._ids).run(
            raw_text, project_id, source_platform
        )
        self._state_mgr.transition(state, "INTAKE_COMPLETE", "intake complete", "cli")

        # 2b. Deterministic fingerprint of the redacted input (identity of this work run)
        fingerprint = input_fingerprint(intake.redacted_text, source_platform, profile_override)

        # 3. Profile inference
        selection = UniversalProfileSelector().select(
            intake.redacted_text, signals=intake.task_classification.signals,
            override=profile_override,
        )
        profile = selection.selected_profile

        # 4. Requirements
        requirements = RequirementExtractor(self._clock, self._ids).extract(
            intake.redacted_text, profile, source_ref="WORK_REQUEST.json"
        )

        # 5. Missing information
        missing = MissingInformationAnalyzer().analyze(
            profile, intake.work_request, intake.input_map
        )
        intake.work_request.missing_information = list(missing.blocking)

        # 6. Capability + toolchain plans (only meaningful when profile resolved)
        cap_plan = CapabilityPlanner(self._registry).plan(
            project_id, "WORK_PACKET.json", profile
        )
        cap_plan.id = self._ids.new_id()
        cap_plan.created_at = now
        toolchain = ToolchainComposer().compose(cap_plan)
        toolchain.id = self._ids.new_id()
        toolchain.created_at = now

        # 7. WorkPacket
        packet = WorkPacket(
            id=self._ids.new_id(),
            project_id=project_id,
            title=intake.work_request.request_title,
            summary=intake.work_request.request_summary,
            source_platform=source_platform,
            source_ref="INPUT_MAP.json",
            work_request_ref=intake.work_request.id,
            input_fingerprint=fingerprint,
            requirements=requirements,
            capability_profile=profile,
            detected_capabilities=list(cap_plan.required_capabilities),
            missing_information=list(missing.blocking),
            capability_plan_ref="CAPABILITY_PLAN.json",
            toolchain_plan_ref="TOOLCHAIN_PLAN.json",
            run_state_ref="WORK_RUN_STATE.json",
            created_at=now,
        )

        # 8. State: PLANNED then WAITING_* per outcome
        self._state_mgr.transition(state, "PLANNED", "planning complete", "cli")
        approvals = sorted(set(cap_plan.approvals_required) | set(toolchain.approvals_required))
        if missing.has_blocking:
            self._state_mgr.transition(
                state, "WAITING_FOR_INFORMATION", "blocking information missing", "cli"
            )
        elif approvals:
            self._state_mgr.transition(
                state, "WAITING_FOR_APPROVAL", "approvals required before execution", "cli"
            )
        # else: remain PLANNED (human plan review)

        # 9. MCP configured snapshot (config-level; no discovery)
        snapshot = build_configured_servers_snapshot(self._registry, self._clock)

        # 10. Assemble artifacts (deterministic serialization)
        artifacts = self._render_artifacts(
            intake, selection, requirements, missing, packet, state,
            cap_plan, toolchain, snapshot, approvals,
        )

        # 11. Overwrite guard + atomic publish
        target = self._output_dir / project_id / _ARK_DIR
        self._guard_overwrite(target, project_id, fresh_only, fingerprint)
        ArtifactSafeWriter(target).publish(artifacts)

        return WorkPlanningResult(
            project_id=project_id,
            profile=profile,
            final_status=state.status,
            target_dir=str(target),
            artifacts=sorted(artifacts.keys()),
            warnings=selection.warnings,
            secrets_redacted=intake.secrets_redacted,
            missing_information_count=len(missing.blocking),
            approvals_required_count=len(approvals),
        )

    # ------------------------------------------------------------------
    def _guard_overwrite(
        self, target: Path, project_id: str, fresh_only: bool, current_fingerprint: str
    ) -> None:
        if not target.exists():
            return
        # A generated id must never collide with an existing project directory.
        if fresh_only:
            raise WorkPlanningError(
                f"{target} already exists; refusing to overwrite a generated-id run "
                "(re-run to get a new id, or pass an explicit --project-id to resume)"
            )
        existing = target / "WORK_PACKET.json"
        if existing.exists():
            try:
                data = json.loads(existing.read_text(encoding="utf-8"))
            except Exception:
                return
            if data.get("project_id") and data["project_id"] != project_id:
                raise WorkPlanningError(
                    f"{target} holds a different project ({data['project_id']}); "
                    "use a new --project-id"
                )
            # Explicit id may resume/regenerate ONLY the same logical work request.
            prior_fp = data.get("input_fingerprint", "")
            if prior_fp and current_fingerprint and prior_fp != current_fingerprint:
                raise WorkPlanningError(
                    f"project id '{project_id}' already holds a different work request "
                    "(input fingerprint mismatch); choose a new --project-id"
                )

    def _render_artifacts(
        self, intake, selection, requirements, missing, packet, state,
        cap_plan, toolchain, snapshot, approvals,
    ) -> Dict[str, str]:
        intake_report = {
            "profile_selection": selection.to_dict(),
            "secrets_redacted": intake.secrets_redacted,
            "missing_information": missing.to_dict(),
            "source_platform": packet.source_platform,
        }
        return {
            "INPUT_MAP.json": _dumps(intake.input_map.to_dict()),
            "WORK_REQUEST.json": _dumps(intake.work_request.to_dict()),
            "TASK_CLASSIFICATION.json": _dumps(intake.task_classification.to_dict()),
            "INTAKE_REPORT.json": _dumps(intake_report),
            "WORK_PACKET.json": _dumps(packet.to_dict()),
            "WORK_RUN_STATE.json": _dumps(state.to_dict()),
            "CAPABILITY_PLAN.json": _dumps(cap_plan.to_dict()),
            "TOOLCHAIN_PLAN.json": _dumps(toolchain.to_dict()),
            "MCP_CONFIGURED_SERVERS_SNAPSHOT.json": _dumps(snapshot),
            "WORK_SUMMARY.md": self._summary_md(packet, selection, state, missing, approvals),
            "AGENT_TASKS.md": self._agent_tasks_md(cap_plan, toolchain),
            "APPROVALS_REQUIRED.md": self._approvals_md(approvals, missing),
            "NEXT_ACTION.md": self._next_action_md(state, missing, approvals, selection),
        }

    @staticmethod
    def _summary_md(packet, selection, state, missing, approvals) -> str:
        lines = [
            "# Work Summary (planning-only)", "",
            f"- Project: {packet.project_id}",
            f"- Profile: {packet.capability_profile or '(unresolved)'} "
            f"(source: {selection.selection_source}, confidence: {selection.confidence})",
            f"- Title: {packet.title}",
            f"- Run state: {state.status}",
            f"- Requirements extracted: {len(packet.requirements)}",
            f"- Blocking info missing: {len(missing.blocking)}",
            f"- Approvals required: {len(approvals)}", "",
            "_Phase 8.1 planning-only. No MCP tool was invoked; nothing was executed._",
        ]
        if selection.warnings:
            lines += ["", "## Warnings", *[f"- {w}" for w in selection.warnings]]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _agent_tasks_md(cap_plan, toolchain) -> str:
        lines = ["# Agent Tasks (proposed, not executed)", ""]
        for step in toolchain.steps:
            lines.append(
                f"- `{step.capability}` — backend: {step.backend or '(none)'}; "
                f"status: {step.resolution_status}; "
                f"approval: {'yes' if step.requires_approval else 'no'}"
            )
        lines += ["", "_MCP steps stay unresolved until Phase 8.3 discovery._"]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _approvals_md(approvals, missing) -> str:
        lines = ["# Approvals Required (unresolved)", ""]
        if approvals:
            for a in approvals:
                lines.append(f"- {a} — execution blocked until approved")
        else:
            lines.append("- None identified at planning time.")
        if missing.approval_needed:
            lines += ["", "## Profile-specific approvals", *[f"- {a}" for a in missing.approval_needed]]
        lines += ["", "_No approval is granted or persisted in Phase 8.1._"]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _next_action_md(state, missing, approvals, selection) -> str:
        lines = ["# Next Action", ""]
        if state.status == "WAITING_FOR_INFORMATION":
            lines.append("Provide the missing blocking information:")
            lines += [f"- {b}" for b in missing.blocking]
        elif state.status == "WAITING_FOR_APPROVAL":
            lines.append("Human approval required before any execution:")
            lines += [f"- {a}" for a in approvals]
        else:
            lines.append("Planning complete. Human review of the plan is the next step.")
        if missing.clarification:
            lines += ["", "## Optional clarifications", *[f"- {c}" for c in missing.clarification]]
        return "\n".join(lines) + "\n"
