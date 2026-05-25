"""WorkbenchController — orchestrates input classification and writes initial artifacts.

This is NOT a replacement for core/orchestrator.py. The orchestrator remains the
workflow execution engine. WorkbenchController is the initial classification and
artifact-writing layer (Phase 2A/2B).

Classify-only: no URL fetching, no browser execution, no credential use,
no external calls, no cleanup deletion.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional
from uuid import uuid4

from core.input_context_resolver import InputContextResolver, _redact_secrets
from core.schemas.input_map import InputMap
from core.schemas.project_blueprint import ProjectBlueprint
from core.schemas.project_status import ProjectStatus
from core.schemas.task_classification import TaskClassification
from core.schemas.work_request import WorkRequest
from core.work_request_classifier import WorkRequestClassifier


_BLOCKED_TYPES = frozenset({
    "target_url",
    "unknown_url",
    "credentials_reference",
    "api_docs_url",
    "design_url",
    "repo_url",
})

_OUTPUTS_ROOT = Path("outputs")


class WorkbenchController:
    """Coordinates input classification and writes structured artifacts.

    Does NOT replace core/orchestrator.py. The orchestrator handles workflow execution.
    WorkbenchController handles the classify-only intake phase (Phase 2A).
    """

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self._resolver = InputContextResolver()
        self._classifier = WorkRequestClassifier()
        self._outputs_root = outputs_root or _OUTPUTS_ROOT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_inputs(
        self,
        raw_inputs: List[str],
        raw_text: str = "",
        source_platform: str = "unknown",
        project_id: Optional[str] = None,
    ) -> dict:
        """Classify inputs and return a structured result dict.

        No artifacts are written. Safe for use in unit tests.
        """
        pid = project_id or str(uuid4())
        if not raw_text and raw_inputs:
            raw_text = " ".join(raw_inputs)

        # Redact secrets from raw_text before any storage or classification
        raw_text, _ = _redact_secrets(raw_text)

        input_map = self._resolver.resolve(raw_inputs, pid)
        work_request, task_classification = self._classifier.classify(
            raw_text, input_map, source_platform
        )
        project_status = self._build_initial_status(pid, task_classification)
        next_step = self._determine_next_safe_step(input_map, task_classification)

        return {
            "project_id": pid,
            "input_map": input_map,
            "work_request": work_request,
            "task_classification": task_classification,
            "project_status": project_status,
            "next_safe_step": next_step,
        }

    def build_initial_context(
        self,
        raw_inputs: List[str],
        raw_text: str = "",
        source_platform: str = "unknown",
        project_id: Optional[str] = None,
    ) -> dict:
        """Classify and write artifacts to outputs/<project_id>/00_project/.

        Returns the same result dict as analyze_inputs plus artifact paths.
        """
        result = self.analyze_inputs(raw_inputs, raw_text, source_platform, project_id)
        artifact_paths = self._write_artifacts(result)
        result["artifact_paths"] = artifact_paths
        return result

    def render_initial_artifacts(self, result: dict) -> dict:
        """Write artifacts for a pre-computed result dict. Returns artifact paths."""
        return self._write_artifacts(result)

    def get_next_safe_step(
        self,
        input_map: InputMap,
        task_classification: TaskClassification,
    ) -> str:
        return self._determine_next_safe_step(input_map, task_classification)

    # ------------------------------------------------------------------
    # Phase 2B — Blueprint API
    # ------------------------------------------------------------------

    def build_project_blueprint(
        self,
        input_map: InputMap,
        work_request: WorkRequest,
        task_classification: TaskClassification,
    ) -> ProjectBlueprint:
        """Build a ProjectBlueprint from Phase 2A context. No external calls."""
        from core.project_blueprint_builder import ProjectBlueprintBuilder
        return ProjectBlueprintBuilder().build(input_map, work_request, task_classification)

    def render_blueprint_artifacts(
        self,
        blueprint: ProjectBlueprint,
        task_type: str,
        project_id: str,
    ) -> dict:
        """Write Phase 2B planning artifacts to outputs/<project_id>/00_project/. Returns path dict."""
        from core.project_blueprint_builder import ProjectBlueprintBuilder
        out_dir = self._outputs_root / project_id / "00_project"
        return ProjectBlueprintBuilder().render_artifacts(blueprint, task_type, out_dir)

    def update_project_status_for_blueprint(
        self,
        project_id: str,
        blueprint: ProjectBlueprint,
    ) -> ProjectStatus:
        """Return a ProjectStatus reflecting Phase 2B completion."""
        n_missing = len(blueprint.missing_information)
        return ProjectStatus(
            project_id=project_id,
            phase="blueprint",
            overall_status="in_progress",
            next_action=(
                f"Review blueprint and resolve {n_missing} missing information item(s) "
                "before proceeding to Phase 2C."
            ),
            notes=(
                f"Phase 2B blueprint complete. "
                f"confidence={blueprint.confidence_level} "
                f"project_type={blueprint.project_type}"
            ),
        )

    def build_context_with_blueprint(
        self,
        raw_inputs: List[str],
        raw_text: str = "",
        source_platform: str = "unknown",
        project_id: Optional[str] = None,
    ) -> dict:
        """Phase 2A + 2B: classify inputs, write all artifacts including blueprint.

        Returns the combined result dict with keys:
          project_id, input_map, work_request, task_classification,
          project_status, next_safe_step, artifact_paths,
          blueprint, blueprint_status, blueprint_artifact_paths.
        """
        result = self.build_initial_context(raw_inputs, raw_text, source_platform, project_id)

        blueprint = self.build_project_blueprint(
            result["input_map"],
            result["work_request"],
            result["task_classification"],
        )
        blueprint_status = self.update_project_status_for_blueprint(result["project_id"], blueprint)
        blueprint_paths = self.render_blueprint_artifacts(
            blueprint,
            result["task_classification"].task_type,
            result["project_id"],
        )

        result["blueprint"] = blueprint
        result["blueprint_status"] = blueprint_status
        result["blueprint_artifact_paths"] = blueprint_paths
        result["artifact_paths"].update(blueprint_paths)

        return result

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _build_initial_status(
        self, project_id: str, classification: TaskClassification
    ) -> ProjectStatus:
        return ProjectStatus(
            project_id=project_id,
            phase="intake",
            overall_status="in_progress",
            next_action=f"Review classification ({classification.task_type}) and approve next step",
            notes=f"Phase 2A intake complete. confidence={classification.confidence}",
        )

    def _determine_next_safe_step(
        self,
        input_map: InputMap,
        classification: TaskClassification,
    ) -> str:
        blocked = [s for s in input_map.sources if s.input_type in _BLOCKED_TYPES]
        has_credentials = any(
            s.input_type == "credentials_reference" for s in input_map.sources
        )

        if has_credentials:
            return (
                "BLOCKED: Credential reference detected. "
                "No credential use permitted in Phase 2A. "
                "Review credential references and obtain explicit approval before proceeding."
            )

        if blocked:
            blocked_types = sorted({s.input_type for s in blocked})
            return (
                f"REVIEW REQUIRED: Inputs of type(s) {blocked_types} require approval "
                "before any fetch, execution, or access. "
                "Approve target URLs / external resources manually, then proceed to Phase 2B."
            )

        task_type = classification.task_type
        if task_type == "qa_automation":
            return (
                "Safe to proceed to Phase 2B: "
                "Generate project blueprint and QA strategy from classified inputs. "
                "No external execution until approved."
            )
        if task_type == "api_testing":
            return (
                "Safe to proceed to Phase 2B: "
                "Generate API test strategy. "
                "No API calls until target URL and credentials are approved."
            )
        if task_type == "proposal":
            return (
                "Safe to proceed: Generate proposal draft from brief. "
                "No external access required."
            )
        if task_type == "test_strategy":
            return (
                "Safe to proceed to Phase 2B: "
                "Generate test strategy document from classified inputs."
            )
        return (
            "Review classified inputs and task type, then decide next phase. "
            "No automatic execution without explicit approval."
        )

    # ------------------------------------------------------------------
    # Artifact writing
    # ------------------------------------------------------------------

    def _write_artifacts(self, result: dict) -> dict:
        project_id: str = result["project_id"]
        out_dir = self._outputs_root / project_id / "00_project"
        out_dir.mkdir(parents=True, exist_ok=True)

        input_map: InputMap = result["input_map"]
        work_request: WorkRequest = result["work_request"]
        classification: TaskClassification = result["task_classification"]
        status: ProjectStatus = result["project_status"]
        next_step: str = result["next_safe_step"]

        paths = {}

        # INPUT_MAP
        paths["input_map_json"] = self._write_json(
            out_dir / "INPUT_MAP.json", input_map.to_dict()
        )
        paths["input_map_md"] = self._write_text(
            out_dir / "INPUT_MAP.md",
            self._render_input_map(input_map),
        )

        # WORK_REQUEST
        paths["work_request_json"] = self._write_json(
            out_dir / "WORK_REQUEST.json", work_request.to_dict()
        )
        paths["work_request_md"] = self._write_text(
            out_dir / "WORK_REQUEST.md",
            self._render_work_request(work_request),
        )

        # TASK_CLASSIFICATION
        paths["task_classification_json"] = self._write_json(
            out_dir / "TASK_CLASSIFICATION.json", classification.to_dict()
        )
        paths["task_classification_md"] = self._write_text(
            out_dir / "TASK_CLASSIFICATION.md",
            self._render_classification(classification),
        )

        # PROJECT_STATUS
        paths["project_status_json"] = self._write_json(
            out_dir / "PROJECT_STATUS.json", status.to_dict()
        )
        paths["project_status_md"] = self._write_text(
            out_dir / "PROJECT_STATUS.md",
            self._render_project_status(status),
        )

        # NEXT_SAFE_STEP
        paths["next_safe_step_md"] = self._write_text(
            out_dir / "NEXT_SAFE_STEP.md",
            self._render_next_step(next_step, classification),
        )

        return paths

    # ------------------------------------------------------------------
    # Markdown renderers
    # ------------------------------------------------------------------

    def _render_input_map(self, im: InputMap) -> str:
        lines = [
            f"# Input Map — {im.project_id}",
            "",
            f"**Created:** {im.created_at}",
            f"**Sources:** {len(im.sources)}",
            "",
            "---",
            "",
        ]
        for i, src in enumerate(im.sources, 1):
            lines += [
                f"## Source {i}: `{src.input_type}`",
                "",
                f"- **Label:** {src.label}",
                f"- **Approved:** {src.approved}",
            ]
            if src.raw_value:
                truncated = src.raw_value[:200] + ("..." if len(src.raw_value) > 200 else "")
                lines += [f"- **Value (truncated):** {truncated}"]
            if src.classification_notes:
                lines += [f"- **Notes:** {src.classification_notes}"]
            lines.append("")
        return "\n".join(lines)

    def _render_work_request(self, wr: WorkRequest) -> str:
        lines = [
            f"# Work Request — {wr.project_id}",
            "",
            f"**Title:** {wr.request_title}",
            f"**Platform:** {wr.source_platform}",
            f"**Created:** {wr.created_at}",
            "",
            "## Summary",
            "",
            wr.request_summary or "_No summary extracted._",
            "",
        ]
        if wr.inputs:
            lines += ["## Input types", ""]
            for inp in wr.inputs:
                lines.append(f"- {inp}")
            lines.append("")
        if wr.target_urls:
            lines += ["## Target URLs (not yet approved)", ""]
            for url in wr.target_urls:
                lines.append(f"- `{url}` — blocked; requires approval")
            lines.append("")
        if wr.tags:
            lines += ["## Tags", ""]
            lines.append(", ".join(f"`{t}`" for t in wr.tags))
            lines.append("")
        return "\n".join(lines)

    def _render_classification(self, tc: TaskClassification) -> str:
        lines = [
            f"# Task Classification — {tc.project_id}",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| Task type | `{tc.task_type}` |",
            f"| Project type | `{tc.project_type}` |",
            f"| Platform | `{tc.source_platform}` |",
            f"| Confidence | {tc.confidence} |",
            f"| Classified at | {tc.classified_at} |",
            "",
            "## Notes",
            "",
            tc.notes or "_none_",
            "",
            "## Signals",
            "",
        ]
        for sig in tc.signals:
            lines.append(f"- `{sig}`")
        lines.append("")
        return "\n".join(lines)

    def _render_project_status(self, ps: ProjectStatus) -> str:
        lines = [
            f"# Project Status — {ps.project_id}",
            "",
            "| Field | Value |",
            "|---|---|",
            f"| Phase | `{ps.phase}` |",
            f"| Status | `{ps.overall_status}` |",
            f"| Updated | {ps.updated_at} |",
            "",
            "## Next action",
            "",
            ps.next_action or "_none_",
            "",
        ]
        if ps.notes:
            lines += ["## Notes", "", ps.notes, ""]
        return "\n".join(lines)

    def _render_next_step(self, next_step: str, tc: TaskClassification) -> str:
        lines = [
            "# Next Safe Step",
            "",
            f"**Task type:** `{tc.task_type}`  ",
            f"**Project type:** `{tc.project_type}`  ",
            f"**Confidence:** {tc.confidence}",
            "",
            "---",
            "",
            next_step,
            "",
            "---",
            "",
            "_Generated by WorkbenchController (Phase 2A — classify only). "
            "No execution has occurred. All URLs, credentials, and external resources "
            "require explicit approval before any access._",
            "",
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # File helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _write_json(path: Path, data: dict) -> str:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return str(path)

    @staticmethod
    def _write_text(path: Path, content: str) -> str:
        path.write_text(content, encoding="utf-8")
        return str(path)
