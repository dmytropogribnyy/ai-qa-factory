"""Execution Readiness Planner — Phase 4A.

Inspects local project artifacts and generates:
- ExecutionApprovalChecklist
- ExecutionReadinessReport
- Execution boundary documentation
- Evidence collection plan

SAFETY: Never executes code, never fetches URLs, never uses credentials,
never calls external services. All approved_for_* flags remain False.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.schemas.execution_approval import (
    ExecutionApprovalChecklist,
    ExecutionApprovalRequirement,
    ExecutionReadinessReport,
)

_OUTPUTS_ROOT = Path("outputs")


class ExecutionReadinessPlanner:
    """Plans execution readiness from existing local artifacts. No execution performed."""

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self._outputs_root = outputs_root or _OUTPUTS_ROOT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def plan_readiness(
        self,
        project_id: str,
        scaffold_root: Optional[Path] = None,
    ) -> Tuple[ExecutionApprovalChecklist, ExecutionReadinessReport]:
        """Inspect local artifacts and return (checklist, readiness_report)."""
        context = self._load_context(project_id, scaffold_root)
        checklist = self._build_checklist(project_id, context)
        report = self._build_readiness_report(project_id, checklist, context)
        return checklist, report

    def render_execution_plan_artifacts(
        self,
        checklist: ExecutionApprovalChecklist,
        report: ExecutionReadinessReport,
        project_id: str,
    ) -> Dict[str, Path]:
        """Write execution plan artifacts to outputs/<project_id>/04_execution_plan/."""
        out_dir = self._outputs_root / project_id / "04_execution_plan"
        out_dir.mkdir(parents=True, exist_ok=True)

        paths: Dict[str, Path] = {}

        p = out_dir / "EXECUTION_APPROVAL_CHECKLIST.json"
        p.write_text(json.dumps(checklist.to_dict(), indent=2), encoding="utf-8")
        paths["checklist_json"] = p

        p = out_dir / "EXECUTION_APPROVAL_CHECKLIST.md"
        p.write_text(self._render_checklist_md(checklist), encoding="utf-8")
        paths["checklist_md"] = p

        p = out_dir / "EXECUTION_READINESS_REPORT.json"
        p.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        paths["readiness_json"] = p

        p = out_dir / "EXECUTION_READINESS_REPORT.md"
        p.write_text(self._render_readiness_md(report), encoding="utf-8")
        paths["readiness_md"] = p

        p = out_dir / "EVIDENCE_COLLECTION_PLAN.md"
        p.write_text(self._render_evidence_plan_md(project_id), encoding="utf-8")
        paths["evidence_plan_md"] = p

        p = out_dir / "EXECUTION_BOUNDARIES.md"
        p.write_text(self._render_boundaries_md(project_id), encoding="utf-8")
        paths["boundaries_md"] = p

        return paths

    # ------------------------------------------------------------------
    # Context loading
    # ------------------------------------------------------------------

    def _load_context(
        self,
        project_id: str,
        scaffold_root: Optional[Path],
    ) -> Dict[str, Any]:
        ctx: Dict[str, Any] = {
            "has_blueprint": False,
            "has_strategy": False,
            "has_scaffold": False,
            "has_static_validation": False,
            "has_toolchain_validation": False,
            "toolchain_passed": False,
            "static_passed": False,
            "has_blockers": False,
            "project_type": "unknown",
            "environment_type": "unknown",
            "target_url": None,
            "has_payment": False,
            "has_auth": False,
            "has_n8n": False,
            "has_api": False,
        }

        blueprint_path = self._outputs_root / project_id / "00_project" / "PROJECT_BLUEPRINT.json"
        if blueprint_path.exists():
            ctx["has_blueprint"] = True
            try:
                data = json.loads(blueprint_path.read_text(encoding="utf-8"))
                ctx["project_type"] = data.get("project_type", "unknown")
                ctx["environment_type"] = data.get("environment_type", "unknown")
                ctx["target_url"] = data.get("target_application", {}).get("url") if isinstance(data.get("target_application"), dict) else None
                ctx["has_payment"] = "ecommerce" in ctx["project_type"] or "payment" in str(data).lower()
                ctx["has_auth"] = any(k in str(data).lower() for k in ("auth", "oauth", "login"))
                ctx["has_n8n"] = "n8n" in str(data).lower() or "webhook" in str(data).lower()
                ctx["has_api"] = "api" in ctx["project_type"].lower()
            except Exception:
                pass

        strategy_path = self._outputs_root / project_id / "02_strategy" / "QA_STRATEGY.json"
        if strategy_path.exists():
            ctx["has_strategy"] = True

        sc_root = scaffold_root
        if sc_root is None:
            sc_root = self._outputs_root / project_id / "03_framework" / "playwright"

        scaffold_meta = sc_root / "FRAMEWORK_SCAFFOLD.json"
        if scaffold_meta.exists():
            ctx["has_scaffold"] = True

        static_report = sc_root / "STATIC_VALIDATION_REPORT.json"
        if static_report.exists():
            ctx["has_static_validation"] = True
            try:
                d = json.loads(static_report.read_text(encoding="utf-8"))
                ctx["static_passed"] = d.get("validation_status") == "pass"
                ctx["has_blockers"] = bool(d.get("blocker_count", 0))
            except Exception:
                pass

        toolchain_report = sc_root / "TOOLCHAIN_VALIDATION_REPORT.json"
        if toolchain_report.exists():
            ctx["has_toolchain_validation"] = True
            try:
                d = json.loads(toolchain_report.read_text(encoding="utf-8"))
                ctx["toolchain_passed"] = d.get("validation_status") == "pass"
            except Exception:
                pass

        return ctx

    # ------------------------------------------------------------------
    # Checklist / report builders
    # ------------------------------------------------------------------

    def _build_checklist(
        self, project_id: str, ctx: Dict[str, Any]
    ) -> ExecutionApprovalChecklist:
        reqs: List[ExecutionApprovalRequirement] = []

        reqs.append(ExecutionApprovalRequirement(
            id="target_url_approval",
            name="Target URL Approval",
            category="target_url",
            required=True,
            approved=False,
            rationale="The target application URL must be explicitly approved before any browser session is opened.",
            risk_level="critical",
            blocks_execution=True,
            notes=["Approval must be documented outside the system."],
        ))

        reqs.append(ExecutionApprovalRequirement(
            id="test_account_confirmation",
            name="Test Account / Credentials Confirmed",
            category="credentials",
            required=True,
            approved=False,
            rationale="Valid test credentials must be provided and confirmed before any auth flow can run.",
            risk_level="critical",
            blocks_execution=True,
            notes=["Store in .env — never commit credentials."],
        ))

        if ctx.get("has_payment"):
            reqs.append(ExecutionApprovalRequirement(
                id="payment_sandbox",
                name="Payment Sandbox Confirmed",
                category="payment_sandbox",
                required=True,
                approved=False,
                rationale="Payment tests require a confirmed sandbox environment — never run against live payment endpoints.",
                risk_level="critical",
                blocks_execution=True,
            ))

        if ctx.get("has_n8n"):
            reqs.append(ExecutionApprovalRequirement(
                id="integration_blocked",
                name="n8n / Webhook Integration Blocked",
                category="external_integrations",
                required=True,
                approved=False,
                rationale="Outbound integration calls (n8n, webhooks) are blocked by default and require explicit approval.",
                risk_level="critical",
                blocks_execution=True,
            ))

        reqs.append(ExecutionApprovalRequirement(
            id="static_validation_pass",
            name="Static Scaffold Validation Passed",
            category="evidence_collection",
            required=True,
            approved=ctx.get("static_passed", False),
            rationale="Scaffold must pass static validation before any toolchain command.",
            risk_level="high",
            blocks_execution=not ctx.get("static_passed", False),
        ))

        reqs.append(ExecutionApprovalRequirement(
            id="toolchain_validation_pass",
            name="Toolchain Validation Passed (with approval)",
            category="evidence_collection",
            required=True,
            approved=ctx.get("toolchain_passed", False),
            rationale="Toolchain commands (npm install, typecheck, playwright --list) must pass with explicit --approve-toolchain.",
            risk_level="high",
            blocks_execution=not ctx.get("toolchain_passed", False),
        ))

        return ExecutionApprovalChecklist(
            project_id=project_id,
            target_environment=ctx.get("environment_type", "unknown"),
            target_url_approved=False,
            credentials_approved=False,
            test_account_confirmed=False,
            production_readonly_approved=False,
            payment_sandbox_confirmed=False,
            destructive_actions_blocked=True,
            external_integrations_blocked=True,
            browser_execution_approved=False,
            evidence_collection_approved=False,
            requirements=reqs,
            approved_for_execution=False,
            approved_for_browser_execution=False,
            approved_for_client_delivery=False,
            notes=[
                "All approved_for_* flags are False. Human approval required for each.",
                "No execution has been performed. This is a readiness plan only.",
            ],
        )

    def _build_readiness_report(
        self,
        project_id: str,
        checklist: ExecutionApprovalChecklist,
        ctx: Dict[str, Any],
    ) -> ExecutionReadinessReport:
        blockers: List[str] = []
        warnings: List[str] = []
        required_approvals: List[str] = []
        safe_next_steps: List[str] = []

        if not ctx["has_blueprint"]:
            blockers.append("PROJECT_BLUEPRINT.json not found — run Phase 2B first.")
        if not ctx["has_strategy"]:
            warnings.append("QA_STRATEGY.json not found — run Phase 2C for full strategy.")
        if not ctx["has_scaffold"]:
            blockers.append("FRAMEWORK_SCAFFOLD.json not found — run Phase 3A first.")
        if not ctx["has_static_validation"]:
            blockers.append("STATIC_VALIDATION_REPORT.json not found — run Phase 3B first.")
        elif not ctx["static_passed"]:
            blockers.append("Static scaffold validation has blockers — resolve before proceeding.")
        if not ctx["has_toolchain_validation"]:
            warnings.append("TOOLCHAIN_VALIDATION_REPORT.json not found — run Phase 3C with --approve-toolchain.")
        elif not ctx["toolchain_passed"]:
            warnings.append("Toolchain validation did not pass — run Phase 3C with --approve-toolchain.")

        required_approvals.extend([
            "Explicit approval for target URL",
            "Test credentials confirmed in .env",
            "Test account verified with application owner",
        ])
        if ctx.get("has_payment"):
            required_approvals.append("Payment sandbox environment confirmed")
        if ctx.get("has_n8n"):
            required_approvals.append("Outbound integration calls explicitly approved")

        safe_next_steps.extend([
            "Review EXECUTION_APPROVAL_CHECKLIST.md and obtain all required approvals",
            "Confirm .env is populated with safe test credentials (never commit)",
            "Run Phase 3C (validate_toolchain.py --approve-toolchain) if not yet done",
            "Build evidence foundation (build_evidence_foundation.py)",
            "Build report drafts (build_report_drafts.py)",
        ])

        evidence_plan_ready = (
            ctx["has_blueprint"]
            and ctx["has_scaffold"]
            and ctx["has_static_validation"]
        )

        readiness_status = "not_ready"
        if not blockers:
            readiness_status = "partial" if warnings else "ready_for_review"

        return ExecutionReadinessReport(
            project_id=project_id,
            readiness_status=readiness_status,
            approved_for_execution=False,
            approved_for_browser_execution=False,
            approved_for_target_url=False,
            approved_for_credentials=False,
            approved_for_external_calls=False,
            approved_for_client_delivery=False,
            blockers=blockers,
            warnings=warnings,
            required_approvals=required_approvals,
            safe_next_steps=safe_next_steps,
            evidence_plan_ready=evidence_plan_ready,
            notes=[
                "No execution has been performed.",
                "No URL fetching has been performed.",
                "No credentials have been used.",
                "All approved_for_* flags remain False.",
            ],
        )

    # ------------------------------------------------------------------
    # Markdown renderers
    # ------------------------------------------------------------------

    def _render_checklist_md(self, checklist: ExecutionApprovalChecklist) -> str:
        lines = [
            "# Execution Approval Checklist",
            "",
            "> **DRAFT — NOT APPROVED FOR EXECUTION**  ",
            "> All approved_for_execution and approved_for_browser_execution flags are False.",
            "> Human review and explicit approval required for each item.",
            "",
            f"**Project:** `{checklist.project_id}`  ",
            f"**Target environment:** `{checklist.target_environment}`  ",
            f"**approved_for_execution:** {checklist.approved_for_execution}  ",
            f"**approved_for_browser_execution:** {checklist.approved_for_browser_execution}  ",
            f"**approved_for_client_delivery:** {checklist.approved_for_client_delivery}  ",
            "",
            "## Approval Requirements",
            "",
        ]
        for r in checklist.requirements:
            status = "[ ]" if not r.approved else "[x]"
            lines.append(f"- {status} **{r.name}** (`{r.category}`, risk={r.risk_level})")
            lines.append(f"  - {r.rationale}")
            if r.notes:
                for n in r.notes:
                    lines.append(f"  - _{n}_")
        lines += [
            "",
            "## Safety Invariants",
            "",
            "- No browser execution performed.",
            "- No target URL contacted.",
            "- No credentials used.",
            "- No external API calls.",
            "",
            "## Notes",
        ]
        for note in checklist.notes:
            lines.append(f"- {note}")
        return "\n".join(lines) + "\n"

    def _render_readiness_md(self, report: ExecutionReadinessReport) -> str:
        lines = [
            "# Execution Readiness Report",
            "",
            "> **DRAFT — NOT APPROVED FOR EXECUTION**",
            "",
            f"**Project:** `{report.project_id}`  ",
            f"**Readiness status:** `{report.readiness_status}`  ",
            f"**approved_for_execution:** {report.approved_for_execution}  ",
            f"**evidence_plan_ready:** {report.evidence_plan_ready}  ",
            "",
        ]
        if report.blockers:
            lines += ["## Blockers", ""]
            for b in report.blockers:
                lines.append(f"- {b}")
            lines.append("")
        if report.warnings:
            lines += ["## Warnings", ""]
            for w in report.warnings:
                lines.append(f"- {w}")
            lines.append("")
        lines += ["## Required Approvals", ""]
        for a in report.required_approvals:
            lines.append(f"- [ ] {a}")
        lines += ["", "## Safe Next Steps", ""]
        for s in report.safe_next_steps:
            lines.append(f"- {s}")
        lines += [
            "", "## Safety Boundary",
            "",
            "- No execution performed.",
            "- No URL fetching performed.",
            "- No credentials used.",
            "- No external calls performed.",
        ]
        return "\n".join(lines) + "\n"

    def _render_evidence_plan_md(self, project_id: str) -> str:
        return f"""# Evidence Collection Plan

> **PLANNING ONLY — No evidence collection has been performed.**

**Project:** `{project_id}`

## What Will Be Collected (After Approved Execution)

After all required approvals are obtained and execution is authorized:

| Evidence type | Source | Internal only? |
|---|---|---|
| Command logs | TOOLCHAIN_COMMAND_LOG.md | Yes |
| Scaffold metadata | FRAMEWORK_SCAFFOLD.json | Yes |
| Static validation report | STATIC_VALIDATION_REPORT.json | Yes |
| Toolchain validation report | TOOLCHAIN_VALIDATION_REPORT.json | Yes |
| Test results (future) | playwright-report/ | Yes, until reviewed |
| Screenshots (future) | test-results/ | Yes, until redacted |
| Traces (future) | test-results/ | Yes, until reviewed |

## Evidence Safety Rules

- All evidence is internal-only by default (`client_visible=False`).
- Screenshots and traces require redaction review before any client visibility.
- No raw secrets may appear in any evidence artifact.
- Evidence is never delivered to client without completing EVIDENCE_QUALITY_GATE.

## Current Evidence Status

Evidence collection plan is ready. No execution evidence exists yet.
Run `build_evidence_foundation.py` to register existing local artifacts.
"""

    def _render_boundaries_md(self, project_id: str) -> str:
        return f"""# Execution Boundaries

**Project:** `{project_id}`

> This document defines what has been done, what is blocked, and what requires approval.

## Current Phase Boundary

| Action | Status |
|---|---|
| Input classification (Phase 2A) | Complete |
| Project blueprint (Phase 2B) | Complete |
| QA strategy (Phase 2C) | Complete |
| Playwright scaffold (Phase 3A) | Complete |
| Static scaffold validation (Phase 3B) | Complete |
| Toolchain validation (Phase 3C) | Complete |
| Execution readiness planning (Phase 4A) | In progress |
| Browser test execution (Phase 4A+) | **BLOCKED** — requires approval |
| Evidence collection (Phase 4B+) | **BLOCKED** — requires execution approval |
| Client delivery (Phase 4C+) | **BLOCKED** — requires evidence review and client approval |

## What Has NOT Happened

- No browser has been opened.
- No target application has been contacted.
- No credentials have been used.
- No Playwright tests have been run.
- No external APIs have been called.
- No client delivery has been prepared.

## What Requires Approval Before Execution

1. Target URL must be explicitly approved.
2. Test credentials must be confirmed and stored in .env.
3. Test account must be verified with application owner.
4. Payment sandbox must be confirmed (if applicable).
5. All outbound integrations must remain blocked unless explicitly approved.

## Safety Invariants (Always True)

- `safe_to_execute_tests = False` — toolchain validation alone does not authorize tests.
- `browser_execution_performed = False` — no browser launched.
- `external_url_used = False` — no external URL contacted.
- `credentials_used = False` — no credentials read or injected.
"""
