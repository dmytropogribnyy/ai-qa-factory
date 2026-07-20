"""ClientWorkService (v3.0.0 Milestone 2).

The operator-facing analyze-a-job entrypoint. It REUSES the existing planning pipeline
(WorkPlanningWorkflow) end to end, then reads that run's artifacts and adds a human-readable
feasibility decision + client questions + proposal draft into the SAME project workspace (no
duplicate pipeline, no second artifact hierarchy). Analysis never starts implementation: it stops at
the planning/feasibility stage for human approval.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from core.orchestration.content_safety import ArtifactSafeWriter
from core.orchestration.feasibility import FeasibilityAssessor
from core.orchestration.providers import ClockProvider, IdProvider
from core.orchestration.work_workflow import WorkPlanningResult, WorkPlanningWorkflow
from core.schemas.feasibility import NOT_RECOMMENDED, FeasibilityReport


@dataclass
class ClientWorkResult:
    project_id: str
    verdict: str
    profile: str
    workspace_dir: str
    feasibility: FeasibilityReport
    planning: WorkPlanningResult


class ClientWorkService:
    def __init__(self, clock: Optional[ClockProvider] = None, ids: Optional[IdProvider] = None,
                 output_dir: str = "outputs") -> None:
        self._clock = clock or ClockProvider()
        self._ids = ids or IdProvider()
        self._output_dir = Path(output_dir)

    def analyze(self, raw_text: str, project_id: str, source_platform: str = "unknown",
                profile_override: Optional[str] = None, fresh_only: bool = False) -> ClientWorkResult:
        """Analyze a potential client assignment (read-only planning + feasibility). Never executes."""
        planning = WorkPlanningWorkflow(self._clock, self._ids, self._output_dir).run(
            raw_text, project_id, source_platform, profile_override, fresh_only=fresh_only)
        target = Path(planning.target_dir)
        report = FeasibilityAssessor().assess(
            project_id=project_id,
            work_packet=self._read_json(target / "WORK_PACKET.json"),
            capability_plan=self._read_json(target / "CAPABILITY_PLAN.json"),
            toolchain_plan=self._read_json(target / "TOOLCHAIN_PLAN.json"),
            intake_report=self._read_json(target / "INTAKE_REPORT.json"))
        readiness = self._build_resource_readiness(target, planning.profile, raw_text, report)
        self._add_client_work_artifacts(target, report, readiness)
        return ClientWorkResult(project_id=project_id, verdict=report.verdict, profile=planning.profile,
                                workspace_dir=str(target), feasibility=report, planning=planning)

    def _build_resource_readiness(self, target: Path, profile: str, raw_text: str,
                                  report: Any) -> Dict[str, Any]:
        """Compose the per-project Resource Readiness Checklist from the persisted planning signals.
        Deterministic (no subprocess/network) so analyze stays fast and CI-safe; the Access page shows
        live operator-runtime readiness separately."""
        from types import SimpleNamespace

        from core.orchestration.resource_readiness import build_readiness
        input_map = self._read_json(target / "INPUT_MAP.json")
        sources = input_map.get("sources", []) if isinstance(input_map, dict) else []
        missing = SimpleNamespace(blocking=list(getattr(report, "unavailable_blockers", []) or []))
        return build_readiness(project_id=target.parent.name, profile=profile, raw_text=raw_text,
                               input_map_sources=sources, missing=missing, integrations=None)

    @staticmethod
    def _read_json(path: Path) -> Dict[str, Any]:
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _add_client_work_artifacts(self, target: Path, report: FeasibilityReport,
                                   readiness: Optional[Dict[str, Any]] = None) -> None:
        # Re-read the planning artifacts and republish the COMBINED set so the atomic writer never
        # drops the workflow's output when it adds the feasibility artifacts.
        combined: Dict[str, str] = {}
        for f in sorted(target.glob("*")):
            if f.is_file():
                combined[f.name] = f.read_text(encoding="utf-8")
        combined["FEASIBILITY_REPORT.json"] = json.dumps(report.to_dict(), indent=2, sort_keys=True)
        combined["FEASIBILITY_SUMMARY.md"] = self._summary_md(report)
        combined["CLIENT_QUESTIONS.md"] = self._questions_md(report)
        combined["PROPOSAL_DRAFT.md"] = self._proposal_md(report)
        if readiness is not None:
            from core.orchestration.resource_readiness import readiness_summary_text
            combined["RESOURCE_READINESS.json"] = json.dumps(readiness, indent=2, sort_keys=True)
            combined["RESOURCE_READINESS.md"] = readiness_summary_text(readiness)
        ArtifactSafeWriter(target).publish(combined)

    @staticmethod
    def _summary_md(r: FeasibilityReport) -> str:
        lines = [f"# Feasibility — {r.project_id}", "",
                 f"**Verdict: {r.verdict}**  ·  confidence {r.confidence}  ·  risk {r.risk_level}", "",
                 f"- Profile: {r.profile or '(unresolved)'}",
                 f"- Client intent: {r.client_intent}",
                 f"- Technical fit: {r.technical_fit}",
                 f"- Estimated effort: {r.estimated_effort} ({r.estimated_duration})",
                 f"- Selected capabilities: {', '.join(r.selected_capabilities) or '(none)'}",
                 f"- Selected tools: {', '.join(r.selected_tools) or '(none)'}",
                 f"- Pricing: {r.pricing_guidance}", ""]
        if r.expected_deliverables:
            lines += ["## Expected deliverables", *[f"- {d}" for d in r.expected_deliverables], ""]
        if r.unavailable_blockers:
            lines += ["## Blockers (unavailable)", *[f"- {b}" for b in r.unavailable_blockers], ""]
        if r.reasons_to_reject:
            lines += ["## Honest reasons this may not be a fit",
                      *[f"- {x}" for x in r.reasons_to_reject], ""]
        lines += ["## Validation strategy", *[f"- {v}" for v in r.validation_strategy], "",
                  "_Analysis only — no implementation has started. Approve the plan to proceed._"]
        return "\n".join(lines) + "\n"

    @staticmethod
    def _questions_md(r: FeasibilityReport) -> str:
        lines = [f"# Client Questions — {r.project_id}", ""]
        if r.client_questions:
            lines += [f"{i}. {q}" for i, q in enumerate(r.client_questions, 1)]
        else:
            lines.append("_No blocking questions; optional clarifications may still help scope._")
        return "\n".join(lines) + "\n"

    @staticmethod
    def _proposal_md(r: FeasibilityReport) -> str:
        if r.verdict == NOT_RECOMMENDED:
            return (f"# Proposal Draft — {r.project_id}\n\n_Not recommended to take as specified._\n\n"
                    "## Why\n" + "".join(f"- {x}\n" for x in r.reasons_to_reject) +
                    "\n## Possible alternative\nOffer a reduced, clearly-scoped slice that fits proven "
                    "capabilities, or request the missing access/information first.\n")
        lines = [f"# Proposal Draft — {r.project_id}", "",
                 f"**Scope.** {r.client_intent}", "",
                 "**Deliverables.**", *[f"- {d}" for d in r.expected_deliverables], "",
                 "**Assumptions.**", *[f"- {a}" for a in r.assumptions], "",
                 "**Milestones.**", *[f"- {m}" for m in r.recommended_milestones], "",
                 "**Validation & handover.**", *[f"- {v}" for v in r.validation_strategy], "",
                 f"**Effort / pricing.** {r.estimated_effort} — {r.pricing_guidance}", "",
                 "_Draft for the operator to review and edit before sending to the client._"]
        return "\n".join(lines) + "\n"
