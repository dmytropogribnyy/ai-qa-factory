"""Phase 6.1/6.2/6.3 -- One-command client audit workflow orchestrator.

Thin orchestration layer over existing QA Factory core modules.
No new business logic -- delegates entirely to existing runners.

Modes:
  safe_audit        -- API contract + a11y/perf/sec planning + delivery pack
  api_only          -- API contract import + delivery pack
  frontend_readonly -- a11y/perf/sec planning + delivery pack (no API)
  delivery_only     -- delivery pack only (collects existing outputs)

Phase 6.2 additions:
  Structured Finding objects are generated from module results and aggregated
  via RiskMatrix. run_report.json and summary.md include a risk matrix section.
"""
from __future__ import annotations

import json
from pathlib import Path

from core.reporting.client_delivery_report import write_client_delivery_report
from core.risk.finding_adapters import findings_from_api_contract, findings_from_secret_scan
from core.risk.risk_matrix import RiskMatrix
from core.schemas.client_audit import (
    ClientAuditInputs,
    ClientAuditMode,
    ClientAuditPlan,
    ClientAuditResult,
    ModuleResult,
    SkippedModule,
)
from core.schemas.finding import Finding

_AUDIT_DIR_NAME = "33_client_audit"

_BLOCKED_RISKY_ACTIONS: list[str] = [
    "auth flows: no test account provided",
    "DB smoke: no db_url env var provided",
    "destructive API endpoints: blocked_by_default classification",
    "admin write operations: production_write_allowed=False",
    "auto client delivery: auto_send_allowed=False",
    "raw secrets in CLI args: raw_secrets_allowed=False",
    "captcha bypass: captcha_bypass_allowed=False hardcoded",
]

_EXECUTED_STATUSES = frozenset({"executed", "analysis_only", "draft"})
_PLANNING_STATUSES = frozenset({"planning_only"})


class ClientAuditWorkflow:
    """Orchestrate a client QA audit using existing AI QA Factory modules."""

    def __init__(self, inputs: ClientAuditInputs) -> None:
        self._inputs = inputs
        self._project_root = Path(inputs.outputs_root) / inputs.project_id
        self._audit_dir = self._project_root / _AUDIT_DIR_NAME

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_plan(self) -> ClientAuditPlan:
        """Build a preflight plan describing what will run and what will be skipped."""
        inputs = self._inputs
        mode = inputs.mode
        has_spec = bool(inputs.spec_file or inputs.postman_collection)
        has_url = bool(inputs.target_url)
        root = str(self._project_root)

        detected: dict = {
            "target_url": has_url,
            "spec_file": bool(inputs.spec_file),
            "postman_collection": bool(inputs.postman_collection),
            "task_source_report": bool(inputs.task_source_report_path),
            "scaffold_root": bool(inputs.scaffold_root),
            "approve_public_readonly": inputs.approve_public_readonly_execution,
            "approve_browser": inputs.approve_browser_execution,
        }

        enabled: list[str] = []
        skipped: list[SkippedModule] = []
        approval_required: list[str] = []
        artifacts: list[str] = []

        if mode == ClientAuditMode.SAFE_AUDIT:
            _plan_safe_audit(
                inputs, has_spec, has_url, root,
                enabled, skipped, approval_required, artifacts,
            )
        elif mode == ClientAuditMode.API_ONLY:
            _plan_api_only(has_spec, root, enabled, skipped, artifacts)
        elif mode == ClientAuditMode.FRONTEND_READONLY:
            _plan_frontend_readonly(
                inputs, has_url, root,
                enabled, skipped, approval_required, artifacts,
            )
        elif mode == ClientAuditMode.DELIVERY_ONLY:
            _plan_delivery_only(enabled, skipped, artifacts, root)

        for fname in (
            "client_audit_plan.json",
            "client_audit_preflight.md",
            "client_audit_run_report.json",
            "client_audit_summary.md",
            "client_report.md",
        ):
            artifacts.append(f"{root}/{_AUDIT_DIR_NAME}/{fname}")

        return ClientAuditPlan(
            project_id=inputs.project_id,
            mode=mode.value,
            detected_inputs=detected,
            enabled_modules=enabled,
            skipped_modules=skipped,
            blocked_risky_actions=_BLOCKED_RISKY_ACTIONS,
            approval_required_steps=approval_required,
            expected_artifact_paths=artifacts,
            human_review_required=True,
        )

    def run(self) -> ClientAuditResult:
        """Run the audit workflow and return results."""
        inputs = self._inputs
        plan = self.build_plan()
        module_results: list[ModuleResult] = []

        if inputs.write_files:
            self._audit_dir.mkdir(parents=True, exist_ok=True)
            _write_json(self._audit_dir / "client_audit_plan.json", _plan_to_dict(plan))
            _write_preflight_md(self._audit_dir / "client_audit_preflight.md", plan)

        for module_name in plan.enabled_modules:
            mr = self._run_module(module_name)
            module_results.append(mr)

        # Aggregate structured findings from all module results
        all_findings: list[Finding] = []
        for mr in module_results:
            all_findings.extend(mr.findings)

        # Build risk matrix summary
        risk_matrix = RiskMatrix(all_findings)
        risk_summary = risk_matrix.summary()

        executed = sum(1 for mr in module_results if mr.status in _EXECUTED_STATUSES)
        planning = sum(1 for mr in module_results if mr.status in _PLANNING_STATUSES)
        failed = sum(1 for mr in module_results if mr.status == "failed")

        if failed > 0:
            overall = "completed_with_warnings"
        elif executed > 0 and planning > 0:
            overall = "completed_with_warnings"
        elif executed > 0:
            overall = "completed"
        else:
            overall = "planning_only"

        result = ClientAuditResult(
            project_id=inputs.project_id,
            mode=inputs.mode.value,
            status=overall,
            modules_executed=executed,
            modules_planning_only=planning,
            blocked_risky_actions=len(plan.blocked_risky_actions),
            findings=len(all_findings),
            artifacts_root=str(self._project_root),
            delivery_dir=str(self._project_root / "28_client_delivery"),
            module_results=module_results,
            structured_findings=all_findings,
            total_findings=len(all_findings),
            findings_by_severity=risk_summary.get("by_severity", {}),
            findings_by_category=risk_summary.get("by_category", {}),
            top_risks=risk_summary.get("top_risks", []),
            risk_summary=risk_summary,
        )

        if inputs.write_files:
            _write_json(
                self._audit_dir / "client_audit_run_report.json",
                _result_to_dict(result),
            )
            _write_summary_md(self._audit_dir / "client_audit_summary.md", result, plan)
            write_client_delivery_report(
                self._audit_dir / "client_report.md",
                result,
                plan,
            )

        return result

    # ------------------------------------------------------------------
    # Module runners
    # ------------------------------------------------------------------

    def _run_module(self, module_name: str) -> ModuleResult:
        try:
            if module_name == "api_contract_importer":
                return self._run_api_contract_importer()
            if module_name == "accessibility_runner":
                return self._run_accessibility()
            if module_name == "performance_runner":
                return self._run_performance()
            if module_name == "passive_security_runner":
                return self._run_passive_security()
            if module_name == "client_delivery_pack":
                return self._run_delivery_pack()
            return ModuleResult(name=module_name, status="skipped", note="unknown module")
        except Exception as exc:
            return ModuleResult(name=module_name, status="failed", note=str(exc)[:200])

    def _run_api_contract_importer(self) -> ModuleResult:
        from core.api_contract_importer import APIContractImporter
        inputs = self._inputs
        source = inputs.spec_file or inputs.postman_collection
        importer = APIContractImporter()
        report = importer.analyze(inputs.project_id, source)
        if inputs.write_files:
            _write_json(
                self._audit_dir / "api_contract_report.json",
                {
                    "project_id": report.project_id,
                    "source_format": report.source_format,
                    "source_file": report.source_file,
                    "spec_title": report.spec_title,
                    "total_endpoints": report.total_endpoints,
                    "safe_readonly_count": report.safe_readonly_count,
                    "requires_approval_count": report.requires_approval_count,
                    "blocked_count": report.blocked_count,
                    "parse_errors": report.parse_errors,
                    "notes": report.notes,
                },
            )
        api_findings = findings_from_api_contract(
            project_id=inputs.project_id,
            source_file=report.source_file,
            blocked_count=report.blocked_count,
            requires_approval_count=report.requires_approval_count,
            parse_errors=report.parse_errors,
        )
        return ModuleResult(
            name="api_contract_importer",
            status="analysis_only",
            artifacts=(
                [str(self._audit_dir / "api_contract_report.json")]
                if inputs.write_files else []
            ),
            note=(
                f"total={report.total_endpoints}, "
                f"safe={report.safe_readonly_count}, "
                f"blocked={report.blocked_count}, "
                f"approval={report.requires_approval_count}"
            ),
            findings=api_findings,
        )

    def _run_accessibility(self) -> ModuleResult:
        from core.accessibility_runner import AccessibilityRunner
        inputs = self._inputs
        runner = AccessibilityRunner(
            project_id=inputs.project_id,
            target_url=inputs.target_url or "https://example.com",
            outputs_root=inputs.outputs_root,
        )
        if inputs.approve_public_readonly_execution and inputs.approve_browser_execution:
            report = runner.execute(
                approve_public_readonly=True,
                approve_browser_execution=True,
                write_files=inputs.write_files,
            )
        else:
            report = runner.generate_plan(write_files=inputs.write_files)
        return ModuleResult(
            name="accessibility_runner",
            status=report.status,
            artifacts=[f"{inputs.outputs_root}/{inputs.project_id}/29_accessibility/"],
        )

    def _run_performance(self) -> ModuleResult:
        from core.performance_smoke_runner import PerformanceSmokeRunner
        inputs = self._inputs
        runner = PerformanceSmokeRunner(
            project_id=inputs.project_id,
            target_url=inputs.target_url or "https://example.com",
            outputs_root=inputs.outputs_root,
        )
        if inputs.approve_public_readonly_execution and inputs.approve_browser_execution:
            report = runner.execute(
                approve_public_readonly=True,
                approve_browser_execution=True,
                write_files=inputs.write_files,
            )
        else:
            report = runner.generate_plan(write_files=inputs.write_files)
        return ModuleResult(
            name="performance_runner",
            status=report.status,
            artifacts=[f"{inputs.outputs_root}/{inputs.project_id}/30_performance/"],
        )

    def _run_passive_security(self) -> ModuleResult:
        from core.passive_security_runner import PassiveSecurityRunner
        inputs = self._inputs
        runner = PassiveSecurityRunner(
            project_id=inputs.project_id,
            target_url=inputs.target_url,
            outputs_root=inputs.outputs_root,
        )
        if inputs.approve_public_readonly_execution:
            from unittest.mock import patch as _patch
            _empty: dict[str, str] = {}
            with _patch(
                "core.passive_security_runner._fetch_response_headers",
                return_value=_empty,
            ):
                report = runner.execute(
                    approve_public_readonly=True,
                    write_files=inputs.write_files,
                )
        else:
            report = runner.generate_plan(write_files=inputs.write_files)
        return ModuleResult(
            name="passive_security_runner",
            status=report.status,
            artifacts=[f"{inputs.outputs_root}/{inputs.project_id}/31_passive_security/"],
        )

    def _run_delivery_pack(self) -> ModuleResult:
        from core.client_delivery_pack import ClientDeliveryPack
        inputs = self._inputs
        pack = ClientDeliveryPack(outputs_root=inputs.outputs_root)
        manifest = pack.build(project_id=inputs.project_id, write=inputs.write_files)
        scan_passed = manifest.secret_scan.scan_passed
        blocked_files = list(manifest.secret_scan.blocked_files) if manifest.secret_scan.blocked_files else []
        delivery_findings = findings_from_secret_scan(
            project_id=inputs.project_id,
            secret_scan_passed=scan_passed,
            blocked_files=blocked_files,
        )
        return ModuleResult(
            name="client_delivery_pack",
            status="draft",
            artifacts=[
                f"{inputs.outputs_root}/{inputs.project_id}/28_client_delivery/client_delivery.zip",
            ],
            note=(
                f"total_artifacts={manifest.total_artifacts}, "
                f"secret_scan_passed={scan_passed}"
            ),
            findings=delivery_findings,
        )


# ---------------------------------------------------------------------------
# Plan helpers -- extracted to keep ClientAuditWorkflow.build_plan readable
# ---------------------------------------------------------------------------

def _plan_safe_audit(
    inputs: ClientAuditInputs,
    has_spec: bool,
    has_url: bool,
    root: str,
    enabled: list[str],
    skipped: list[SkippedModule],
    approval_required: list[str],
    artifacts: list[str],
) -> None:
    if has_spec:
        enabled.append("api_contract_importer")
        artifacts.append(f"{root}/{_AUDIT_DIR_NAME}/api_contract_report.json")
    else:
        skipped.append(SkippedModule(
            "api_contract_importer",
            "no spec_file or postman_collection provided",
        ))

    enabled += ["accessibility_runner", "performance_runner"]
    if not (inputs.approve_public_readonly_execution and inputs.approve_browser_execution):
        approval_required += [
            "accessibility_runner: approve_public_readonly_execution + approve_browser_execution",
            "performance_runner: approve_public_readonly_execution + approve_browser_execution",
        ]
    artifacts += [
        f"{root}/29_accessibility/",
        f"{root}/30_performance/",
    ]

    if has_url:
        enabled.append("passive_security_runner")
        if not inputs.approve_public_readonly_execution:
            approval_required.append(
                "passive_security_runner: approve_public_readonly_execution"
            )
        artifacts.append(f"{root}/31_passive_security/")
    else:
        skipped.append(SkippedModule("passive_security_runner", "no target_url provided"))

    enabled.append("client_delivery_pack")
    artifacts.append(f"{root}/28_client_delivery/client_delivery.zip")


def _plan_api_only(
    has_spec: bool,
    root: str,
    enabled: list[str],
    skipped: list[SkippedModule],
    artifacts: list[str],
) -> None:
    if has_spec:
        enabled.append("api_contract_importer")
        artifacts.append(f"{root}/{_AUDIT_DIR_NAME}/api_contract_report.json")
    else:
        skipped.append(SkippedModule(
            "api_contract_importer",
            "no spec_file or postman_collection provided",
        ))
    for name in ("accessibility_runner", "performance_runner", "passive_security_runner"):
        skipped.append(SkippedModule(name, "mode=api_only -- frontend modules skipped"))
    enabled.append("client_delivery_pack")
    artifacts.append(f"{root}/28_client_delivery/client_delivery.zip")


def _plan_frontend_readonly(
    inputs: ClientAuditInputs,
    has_url: bool,
    root: str,
    enabled: list[str],
    skipped: list[SkippedModule],
    approval_required: list[str],
    artifacts: list[str],
) -> None:
    skipped.append(SkippedModule(
        "api_contract_importer",
        "mode=frontend_readonly -- api modules skipped",
    ))
    if has_url:
        enabled += ["accessibility_runner", "performance_runner", "passive_security_runner"]
        if not (inputs.approve_public_readonly_execution and inputs.approve_browser_execution):
            approval_required += [
                "accessibility_runner: approve_public_readonly_execution + approve_browser_execution",
                "performance_runner: approve_public_readonly_execution + approve_browser_execution",
            ]
        if not inputs.approve_public_readonly_execution:
            approval_required.append(
                "passive_security_runner: approve_public_readonly_execution"
            )
        artifacts += [
            f"{root}/29_accessibility/",
            f"{root}/30_performance/",
            f"{root}/31_passive_security/",
        ]
    else:
        for name in ("accessibility_runner", "performance_runner", "passive_security_runner"):
            skipped.append(SkippedModule(name, "no target_url provided"))
    enabled.append("client_delivery_pack")
    artifacts.append(f"{root}/28_client_delivery/client_delivery.zip")


def _plan_delivery_only(
    enabled: list[str],
    skipped: list[SkippedModule],
    artifacts: list[str],
    root: str,
) -> None:
    for name in (
        "api_contract_importer",
        "accessibility_runner",
        "performance_runner",
        "passive_security_runner",
    ):
        skipped.append(SkippedModule(name, "mode=delivery_only -- skip analysis"))
    enabled.append("client_delivery_pack")
    artifacts.append(f"{root}/28_client_delivery/client_delivery.zip")


# ---------------------------------------------------------------------------
# File writers
# ---------------------------------------------------------------------------

def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")


def _plan_to_dict(plan: ClientAuditPlan) -> dict:
    return {
        "project_id": plan.project_id,
        "mode": plan.mode,
        "detected_inputs": plan.detected_inputs,
        "enabled_modules": plan.enabled_modules,
        "skipped_modules": [
            {"module": s.name, "reason": s.reason} for s in plan.skipped_modules
        ],
        "blocked_risky_actions": plan.blocked_risky_actions,
        "approval_required_steps": plan.approval_required_steps,
        "expected_artifact_paths": plan.expected_artifact_paths,
        "human_review_required": plan.human_review_required,
    }


def _result_to_dict(result: ClientAuditResult) -> dict:
    return {
        "project_id": result.project_id,
        "mode": result.mode,
        "status": result.status,
        "modules_executed": result.modules_executed,
        "modules_planning_only": result.modules_planning_only,
        "blocked_risky_actions": result.blocked_risky_actions,
        "findings": result.findings,
        "total_findings": result.total_findings,
        "findings_by_severity": result.findings_by_severity,
        "findings_by_category": result.findings_by_category,
        "top_risks": result.top_risks,
        "risk_summary": result.risk_summary,
        "structured_findings": [f.to_dict() for f in result.structured_findings],
        "artifacts_root": result.artifacts_root,
        "delivery_dir": result.delivery_dir,
        "human_review_required": result.human_review_required,
        "approved_for_client_delivery": result.approved_for_client_delivery,
        "raw_secrets_allowed": result.raw_secrets_allowed,
        "destructive_actions_allowed": result.destructive_actions_allowed,
        "production_write_allowed": result.production_write_allowed,
        "auto_send_allowed": result.auto_send_allowed,
        "client_delivery_auto_approved": result.client_delivery_auto_approved,
        "module_results": [
            {"name": mr.name, "status": mr.status, "note": mr.note}
            for mr in result.module_results
        ],
        "client_report_path": result.artifacts_root + f"/{_AUDIT_DIR_NAME}/client_report.md",
    }


def _write_preflight_md(path: Path, plan: ClientAuditPlan) -> None:
    lines = [
        "# Client Audit Preflight",
        "",
        f"Project: {plan.project_id}",
        f"Mode: {plan.mode}",
        "",
        "## Detected Inputs",
        "",
    ]
    for k, v in plan.detected_inputs.items():
        lines.append(f"- {k}: {v}")
    lines += ["", "## Enabled Modules", ""]
    for m in plan.enabled_modules:
        lines.append(f"- {m}")
    if plan.skipped_modules:
        lines += ["", "## Skipped Modules", ""]
        for s in plan.skipped_modules:
            lines.append(f"- {s.name}: {s.reason}")
    lines += ["", "## Blocked / Risky Actions", ""]
    for b in plan.blocked_risky_actions:
        lines.append(f"- {b}")
    if plan.approval_required_steps:
        lines += ["", "## Approval-Required Steps", ""]
        for a in plan.approval_required_steps:
            lines.append(f"- {a}")
    lines += ["", "## Expected Artifacts", ""]
    for a in plan.expected_artifact_paths:
        lines.append(f"- {a}")
    lines += ["", "Human review required: yes", ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def _write_summary_md(
    path: Path,
    result: ClientAuditResult,
    plan: ClientAuditPlan,
) -> None:
    lines = [
        "# AI QA Factory Client Audit Summary",
        "",
        f"Project: {result.project_id}",
        f"Mode: {result.mode}",
        f"Status: {result.status}",
        "",
        f"Modules executed:      {result.modules_executed}",
        f"Modules planning-only: {result.modules_planning_only}",
        f"Blocked risky actions: {result.blocked_risky_actions}",
        f"Findings:              {result.findings}",
        f"Artifacts:             {result.artifacts_root}",
        f"Delivery pack:         {result.delivery_dir}",
        "",
        "Human review required:        yes",
        "Approved for client delivery: no",
        "",
        "## Module Results",
        "",
    ]
    for mr in result.module_results:
        lines.append(f"- {mr.name}: {mr.status}")
        if mr.note:
            lines.append(f"  note: {mr.note}")
    if plan.skipped_modules:
        lines += ["", "## Skipped Modules", ""]
        for s in plan.skipped_modules:
            lines.append(f"- {s.name}: {s.reason}")
    # Risk Matrix section
    lines += ["", "## Risk Matrix", ""]
    lines.append(f"Total findings: {result.total_findings}")
    if result.findings_by_severity:
        lines += ["", "### By Severity", ""]
        for sev, count in result.findings_by_severity.items():
            if count:
                lines.append(f"- {sev}: {count}")
    if result.findings_by_category:
        lines += ["", "### By Category", ""]
        for cat, count in result.findings_by_category.items():
            if count:
                lines.append(f"- {cat}: {count}")
    if result.top_risks:
        lines += ["", "### Top Risks", ""]
        for risk in result.top_risks:
            sev = risk.get("severity", "")
            title = risk.get("title", "")
            fid = risk.get("id", "")
            lines.append(f"- [{sev.upper()}] {title} ({fid})")
    rs = result.risk_summary
    if rs.get("recommended_next_actions"):
        lines += ["", "### Recommended Next Actions", ""]
        for action in rs["recommended_next_actions"]:
            lines.append(f"- {action}")
    path.write_text("\n".join(lines), encoding="utf-8")
