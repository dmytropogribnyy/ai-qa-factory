"""
Phase 5J — E2E Pipeline Runner.

Architecture note — this class occupies a distinct layer and does NOT replace:
- core/orchestrator.py (QAFactoryOrchestrator) — AI/LLM workflow engine with agent
  registry, state management, and LLM routing.
- core/workbench_controller.py (WorkbenchController) — intake classification and
  artifact writing (Phase 2A/2B).
- core/evidence_manager.py (EvidenceManager) — evidence artifact registration (4B).

E2EPipelineRunner is a subprocess orchestration layer: it calls each Phase 5x
CLI runner in the correct sequence and aggregates their results.

Orchestrates existing Phase runners in a fixed, safe order:
  task_source → browser → api_smoke → google_auth → github_auth
  → mobile_viewport → visual_regression → db_smoke → qa_report

Each module is run as a subprocess via its existing CLI tool.
Modules that are not enabled are skipped. Modules whose CLI tool
does not exist are marked blocked.

SAFETY:
- Requires --approve-pipeline-execution for any actual execution.
- Each module's own safety gates remain fully in effect.
- Raw secrets never accepted via CLI flags.
- safe_to_deliver=False always on PipelineRunReport.
- human_review_required=True always.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.schemas.pipeline import (
    PIPELINE_MODULE_ARTIFACT_DIRS,
    PIPELINE_MODULE_CLI_TOOLS,
    PIPELINE_MODULE_STATUSES,  # noqa: F401
    PIPELINE_MODULES,
    PIPELINE_OVERALL_STATUSES,  # noqa: F401
    PipelineModuleConfig,
    PipelineModuleResult,
    PipelineRunPlan,
    PipelineRunReport,
)

_OUTPUTS_ROOT = Path("outputs")
_EXCERPT_LIMIT = 2000

# Execution order is fixed — cannot be reordered via config
_EXECUTION_ORDER = list(PIPELINE_MODULES)


class E2EPipelineRunner:
    """Orchestrates enabled Phase runners in a fixed safe order."""

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self._outputs_root = outputs_root or _OUTPUTS_ROOT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def plan(
        self,
        project_id: str,
        enabled_modules: List[str],
        module_config: Optional[PipelineModuleConfig] = None,
        approve_pipeline_execution: bool = False,
    ) -> PipelineRunPlan:
        """Build an execution plan — no subprocess is called."""
        blockers: List[str] = []
        notes: List[str] = []
        blocked_modules: List[str] = []
        planned_commands: List[str] = []

        if not project_id:
            blockers.append("project_id is required")

        # Validate module names
        for mod in enabled_modules:
            if mod not in PIPELINE_MODULES:
                blockers.append(
                    f"Unknown module '{mod}'. Valid: {', '.join(PIPELINE_MODULES)}"
                )

        if not enabled_modules:
            blockers.append("No modules enabled. Use --enable-<module> flags.")

        if not approve_pipeline_execution:
            blockers.append(
                "Pipeline execution not approved. Add --approve-pipeline-execution."
            )

        # Check CLI tools exist
        for mod in enabled_modules:
            if mod not in PIPELINE_MODULES:
                continue
            cli_tool = PIPELINE_MODULE_CLI_TOOLS.get(mod, "")
            cli_path = Path(cli_tool) if cli_tool else None
            if cli_path and not cli_path.exists():
                blocked_modules.append(mod)
                notes.append(
                    f"Module '{mod}': CLI tool '{cli_tool}' not found — will be skipped."
                )
            else:
                planned_commands.append(
                    f"python {cli_tool} --project-id {project_id} [module-args]"
                )

        # Execution order: only the enabled modules, in fixed order
        execution_order = [m for m in _EXECUTION_ORDER if m in enabled_modules and m not in blocked_modules]

        return PipelineRunPlan(
            project_id=project_id,
            enabled_modules=list(enabled_modules),
            blocked_modules=blocked_modules,
            execution_order=execution_order,
            planned_commands=planned_commands,
            approval_required=True,
            blockers=blockers,
            notes=notes,
        )

    def run(
        self,
        project_id: str,
        enabled_modules: List[str],
        module_config: Optional[PipelineModuleConfig] = None,
        approve_pipeline_execution: bool = False,
        timeout_per_module: int = 300,
    ) -> PipelineRunReport:
        """Run all enabled modules in order; aggregate into PipelineRunReport."""
        report = PipelineRunReport(
            project_id=project_id,
            enabled_modules=list(enabled_modules),
        )

        if not approve_pipeline_execution:
            report.overall_status = "blocked"
            report.blockers.append(
                "Pipeline execution not approved. Add --approve-pipeline-execution."
            )
            return report

        if not project_id:
            report.overall_status = "blocked"
            report.blockers.append("project_id is required")
            return report

        # Validate module names
        unknown = [m for m in enabled_modules if m not in PIPELINE_MODULES]
        if unknown:
            report.overall_status = "blocked"
            report.blockers.append(
                f"Unknown modules: {', '.join(unknown)}"
            )
            return report

        cfg = module_config or PipelineModuleConfig()
        execution_order = [m for m in _EXECUTION_ORDER if m in enabled_modules]
        report.execution_order = execution_order

        pipeline_start = time.time()

        for module_name in execution_order:
            result = self._run_module(
                module_name=module_name,
                project_id=project_id,
                cfg=cfg,
                timeout=timeout_per_module,
            )
            report.module_results.append(result)
            if result.status == "complete":
                report.modules_complete += 1
            elif result.status == "failed":
                report.modules_failed += 1
            elif result.status == "blocked":
                report.modules_blocked += 1
            elif result.status == "skipped":
                report.modules_skipped += 1

        report.total_duration_seconds = round(time.time() - pipeline_start, 2)

        # Overall status
        if report.modules_blocked > 0 and report.modules_complete == 0:
            report.overall_status = "blocked"
        elif report.modules_failed > 0 and report.modules_complete == 0:
            report.overall_status = "failed"
        elif report.modules_failed > 0 or report.modules_blocked > 0:
            report.overall_status = "partial"
        elif report.modules_complete > 0:
            report.overall_status = "complete"
        else:
            report.overall_status = "failed"

        # Set final report path if qa_report was enabled
        qa_artifact_dir = (
            self._outputs_root / project_id / PIPELINE_MODULE_ARTIFACT_DIRS["qa_report"]
        )
        qa_json = qa_artifact_dir / "QA_EVIDENCE_REPORT.json"
        if qa_json.exists():
            report.final_report_path = str(qa_json)

        return report

    def render_artifacts(
        self, report: PipelineRunReport, project_id: str
    ) -> Dict[str, Path]:
        """Write pipeline artifacts to outputs/<project_id>/20_e2e_pipeline/."""
        out_dir = self._outputs_root / project_id / "20_e2e_pipeline"
        out_dir.mkdir(parents=True, exist_ok=True)

        ts = datetime.now(timezone.utc).isoformat()
        payload: Dict[str, Any] = {
            "schema_version": "5J.1",
            "generated_at": ts,
            **report.to_dict(),
        }

        json_path = out_dir / "PIPELINE_RUN_REPORT.json"
        json_path.write_text(
            json.dumps(payload, indent=2, default=str), encoding="utf-8"
        )

        md_path = out_dir / "PIPELINE_RUN_REPORT.md"
        md_path.write_text(self._render_md(report, ts), encoding="utf-8")

        checklist_path = out_dir / "PIPELINE_SAFETY_CHECKLIST.md"
        checklist_path.write_text(self._render_checklist(report), encoding="utf-8")

        return {
            "json": json_path,
            "md": md_path,
            "checklist": checklist_path,
        }

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _run_module(
        self,
        module_name: str,
        project_id: str,
        cfg: PipelineModuleConfig,
        timeout: int,
    ) -> PipelineModuleResult:
        """Run one module as a subprocess; return PipelineModuleResult."""
        cli_tool = PIPELINE_MODULE_CLI_TOOLS.get(module_name, "")
        artifact_dir = PIPELINE_MODULE_ARTIFACT_DIRS.get(module_name, "")
        result = PipelineModuleResult(
            module_name=module_name,
            cli_tool=cli_tool,
            artifact_dir=str(self._outputs_root / project_id / artifact_dir),
        )

        # Check CLI tool exists
        cli_path = Path(cli_tool) if cli_tool else None
        if not cli_path or not cli_path.exists():
            result.status = "skipped"
            result.notes.append(f"CLI tool '{cli_tool}' not found — module skipped.")
            return result

        # Build command
        cmd = self._build_command(module_name, project_id, cfg, cli_tool)
        if not cmd:
            result.status = "blocked"
            result.blockers.append(
                f"Module '{module_name}' missing required config. Check PipelineModuleConfig."
            )
            return result

        start = time.time()
        try:
            proc = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**os.environ},
            )
            result.duration_seconds = round(time.time() - start, 2)
            result.exit_code = proc.returncode
            combined = (proc.stdout + proc.stderr)[:_EXCERPT_LIMIT]
            result.stdout_excerpt = combined
            if proc.returncode == 0:
                result.status = "complete"
            else:
                result.status = "failed"
                result.blockers.append(
                    f"Exit code {proc.returncode}. Excerpt: {combined[:400]}"
                )
        except subprocess.TimeoutExpired:
            result.duration_seconds = round(time.time() - start, 2)
            result.status = "failed"
            result.blockers.append(f"Timeout after {timeout}s")
        except Exception as exc:  # noqa: BLE001
            result.duration_seconds = round(time.time() - start, 2)
            result.status = "failed"
            result.blockers.append(f"Subprocess error: {exc}")

        return result

    def _build_command(
        self,
        module_name: str,
        project_id: str,
        cfg: PipelineModuleConfig,
        cli_tool: str,
    ) -> Optional[List[str]]:
        """Build subprocess command for a given module."""
        py = sys.executable
        base = [py, cli_tool, "--project-id", project_id]

        if module_name == "task_source":
            if not cfg.task_source_provider or not cfg.task_source_token_env_var:
                return None
            return base + [
                "--provider", cfg.task_source_provider,
                "--token-env-var", cfg.task_source_token_env_var,
                "--task-source-project-id", cfg.task_source_project_id or project_id,
                "--approve-task-source-fetch",
            ]

        if module_name == "browser":
            if not cfg.browser_target_url or not cfg.browser_category:
                return None
            cmd = base + [
                "--target-url", cfg.browser_target_url,
                "--target-category", cfg.browser_category,
            ]
            if cfg.browser_approve:
                cmd.append("--approve-browser-execution")
            return cmd

        if module_name == "api_smoke":
            if not cfg.api_target_url:
                return None
            cmd = base + ["--target-url", cfg.api_target_url]
            if cfg.api_profile:
                cmd += ["--target-profile", cfg.api_profile]
            if cfg.api_approve:
                cmd.append("--approve-api-smoke")
            return cmd

        if module_name == "google_auth":
            cmd = base + [
                "--auth-mode", cfg.google_auth_mode,
                "--decide",
            ]
            if cfg.google_storage_state_path:
                cmd += ["--storage-state-path", cfg.google_storage_state_path]
            if cfg.google_approve:
                cmd.append("--approve-google-test-account")
            if cfg.google_dedicated_test_account_confirmed:
                cmd.append("--dedicated-test-account-confirmed")
            return cmd

        if module_name == "github_auth":
            cmd = base + [
                "--auth-mode", cfg.github_auth_mode,
                "--decide",
            ]
            if cfg.github_storage_state_path:
                cmd += ["--storage-state-path", cfg.github_storage_state_path]
            if cfg.github_approve:
                cmd.append("--approve-github-test-account")
            if cfg.github_dedicated_test_account_confirmed:
                cmd.append("--dedicated-test-account-confirmed")
            return cmd

        if module_name == "mobile_viewport":
            if not cfg.mobile_device:
                return None
            cmd = base + ["--device", cfg.mobile_device]
            if cfg.mobile_target_url:
                cmd += ["--target-url", cfg.mobile_target_url]
            if cfg.mobile_readonly_profile:
                cmd += ["--readonly-profile", cfg.mobile_readonly_profile]
            if cfg.mobile_approve:
                cmd.append("--approve-mobile-execution")
            return cmd

        if module_name == "visual_regression":
            if not cfg.visual_target_url:
                return None
            cmd = base + [
                "--target-url", cfg.visual_target_url,
                "--mode", cfg.visual_mode,
            ]
            if cfg.visual_device:
                cmd += ["--device", cfg.visual_device]
            if cfg.visual_approve:
                cmd.append("--approve-visual-regression")
            return cmd

        if module_name == "db_smoke":
            if not cfg.db_provider or not cfg.db_url_env_var:
                return None
            cmd = base + [
                "--provider", cfg.db_provider,
                "--db-url-env-var", cfg.db_url_env_var,
            ]
            if cfg.db_table:
                cmd += ["--table", cfg.db_table]
            if cfg.db_approve:
                cmd.append("--approve-db-smoke")
            return cmd

        if module_name == "qa_report":
            source_ids = cfg.qa_report_source_project_ids or [project_id]
            cmd = base[:]
            for sid in source_ids:
                cmd += ["--source-project-id", sid]
            return cmd

        return None

    def _render_md(self, report: PipelineRunReport, ts: str) -> str:
        lines = [
            "# E2E Pipeline Run Report",
            "",
            f"**Project:** {report.project_id}",
            f"**Status:** {report.overall_status}",
            f"**Generated:** {ts}",
            f"**Duration:** {report.total_duration_seconds}s",
            "",
            "## Module Summary",
            "",
            "| Module | Status | Duration | Blockers |",
            "|---|---|---|---|",
        ]
        for r in report.module_results:
            b = "; ".join(r.blockers[:2]) if r.blockers else "—"
            lines.append(f"| {r.module_name} | {r.status} | {r.duration_seconds}s | {b} |")
        lines += [
            "",
            f"**Complete:** {report.modules_complete} | "
            f"**Failed:** {report.modules_failed} | "
            f"**Blocked:** {report.modules_blocked} | "
            f"**Skipped:** {report.modules_skipped}",
        ]
        if report.blockers:
            lines += ["", "## Pipeline Blockers", ""]
            for b in report.blockers:
                lines.append(f"- {b}")
        lines += [
            "",
            "---",
            "",
            "**SAFETY:** `raw_secrets_allowed=False` | `production_write_allowed=False` | "
            "`client_delivery_allowed=False` | `human_review_required=True`",
        ]
        return "\n".join(lines) + "\n"

    def _render_checklist(self, report: PipelineRunReport) -> str:
        return (
            "# Pipeline Safety Checklist\n\n"
            f"**Project:** {report.project_id}\n\n"
            "- [ ] All module results reviewed by a human\n"
            "- [ ] No raw secrets in any module artifact\n"
            "- [ ] No production writes confirmed\n"
            "- [ ] Screenshots/videos do not contain PII\n"
            "- [ ] All blockers resolved or acknowledged\n"
            "- [ ] Human approval obtained before client delivery\n"
            "\n"
            "**Hardcoded safety invariants:**\n"
            "- `raw_secrets_allowed=False`\n"
            "- `production_write_allowed=False`\n"
            "- `client_delivery_allowed=False`\n"
            "- `human_review_required=True`\n"
        )
