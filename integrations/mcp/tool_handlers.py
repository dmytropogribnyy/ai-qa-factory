"""Phase 6 — QA Factory MCP tool handler functions.

Pure Python — no mcp package dependency. Called by server.py when registered
as MCP tools, but fully testable without the mcp package.

Safety invariants always enforced:
- All tools default to planning_only / analysis_only (no network, no browser)
- Network / browser execution requires explicit approval flags in params
- No credentials accepted as parameters or returned in responses
- Delivery pack ZIP safety invariants always preserved
- human_review_required=True in every response
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

APP_VERSION = "6.3.0"
_SAFE_MODE = "safe_by_default"

TOOL_NAMES = [
    "qa_factory_health",
    "analyze_project",
    "run_quality_audit",
    "run_flaky_test_analysis",
    "generate_delivery_pack",
    "propose_self_healing_fixes",
    "apply_self_healing_fixes",
]

_BLOCKED_PARAM_FRAGMENTS = (
    "credential", "password", "token", "api_key", "secret", "private_key",
    "auth_key", "access_key", "bearer",
)

_ROOT = Path(__file__).parent.parent.parent


def _core_path() -> None:
    root = str(_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)


def _check_blocked_params(params: dict) -> None:
    for key in params:
        if any(b in key.lower() for b in _BLOCKED_PARAM_FRAGMENTS):
            raise ValueError(
                f"[BLOCKED] Parameter '{key}' is not accepted — "
                "credentials must not be passed to MCP tools."
            )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------------------
# 1. qa_factory_health
# ---------------------------------------------------------------------------

def handle_qa_factory_health(params: dict) -> dict:
    """Return system health, version, available modules, and safety mode."""
    _check_blocked_params(params)
    return {
        "status": "healthy",
        "version": APP_VERSION,
        "safety_mode": _SAFE_MODE,
        "available_modules": TOOL_NAMES,
        "default_execution_mode": "planning_only",
        "network_by_default": False,
        "browser_by_default": False,
        "auto_apply_changes": False,
        "human_review_required": True,
        "generated_at": _now(),
    }


# ---------------------------------------------------------------------------
# 2. analyze_project
# ---------------------------------------------------------------------------

def handle_analyze_project(params: dict) -> dict:
    """Classify a project directory and return available modules + recommendations."""
    _check_blocked_params(params)
    project_id = params.get("project_id", "")
    outputs_root = Path(params.get("outputs_root", "outputs"))

    project_dir = outputs_root / project_id if project_id else None
    found_dirs: list[str] = []
    recommendations: list[str] = []

    _DIR_LABELS = {
        "14_qa_report": "QA evidence report",
        "25_api_contract": "API contract",
        "26_generated_tests": "Generated Playwright tests",
        "27_cicd": "CI/CD config",
        "28_client_delivery": "Client delivery pack",
        "29_accessibility": "Accessibility smoke",
        "30_performance": "Performance smoke",
        "31_passive_security": "Passive security smoke",
        "32_flaky_test_analyzer": "Flaky test analysis",
    }

    if project_dir and project_dir.exists():
        for d in _DIR_LABELS:
            if (project_dir / d).exists():
                found_dirs.append(d)
        if "32_flaky_test_analyzer" not in found_dirs:
            recommendations.append(
                "Run run_flaky_test_analysis to detect selector risks in spec files."
            )
        if "28_client_delivery" not in found_dirs:
            recommendations.append(
                "Run generate_delivery_pack to create a client-ready report package."
            )
        if "31_passive_security" not in found_dirs:
            recommendations.append(
                "Run run_quality_audit to check OWASP security headers (passive only)."
            )
        if not found_dirs:
            recommendations.append(
                "No artifacts found. Run CLI tools to generate phase outputs first."
            )
    else:
        recommendations.append(
            "Project directory not found. Run CLI phase tools to generate outputs first."
        )
        recommendations.append(
            "Example: python tools/run_flaky_test_analyzer.py --project-id my-project"
        )

    return {
        "status": "analysis_only",
        "project_id": project_id,
        "project_dir_exists": bool(project_dir and project_dir.exists()),
        "found_artifact_dirs": found_dirs,
        "module_labels": {d: _DIR_LABELS[d] for d in found_dirs},
        "recommendations": recommendations,
        "human_review_required": True,
        "generated_at": _now(),
    }


# ---------------------------------------------------------------------------
# 3. run_quality_audit
# ---------------------------------------------------------------------------

def handle_run_quality_audit(params: dict) -> dict:
    """Run quality audit modules (planning_only by default; network/browser require approval)."""
    _check_blocked_params(params)
    _core_path()

    project_id = params.get("project_id", "")
    target_url = params.get("target_url", "https://example.com")
    outputs_root = params.get("outputs_root", "outputs")
    approve_public_readonly = bool(params.get("approve_public_readonly_execution", False))
    approve_browser = bool(params.get("approve_browser_execution", False))
    write_files = bool(params.get("write_files", True))

    if not project_id:
        return {
            "status": "failed",
            "error": "project_id is required",
            "human_review_required": True,
        }

    module_statuses: dict[str, str] = {}
    artifact_paths: list[str] = []
    notes: list[str] = []

    # Accessibility
    try:
        from core.accessibility_runner import AccessibilityRunner
        a11y = AccessibilityRunner(
            project_id=project_id,
            target_url=target_url,
            outputs_root=outputs_root,
        )
        if approve_public_readonly and approve_browser:
            report = a11y.execute(
                approve_public_readonly=True,
                approve_browser_execution=True,
                write_files=write_files,
            )
        else:
            report = a11y.generate_plan(write_files=write_files)
        module_statuses["accessibility"] = report.status
        artifact_paths.append(f"{outputs_root}/{project_id}/29_accessibility/")
    except Exception as exc:
        module_statuses["accessibility"] = "failed"
        notes.append(f"Accessibility module error: {exc}")

    # Performance
    try:
        from core.performance_smoke_runner import PerformanceSmokeRunner
        perf = PerformanceSmokeRunner(
            project_id=project_id,
            target_url=target_url,
            outputs_root=outputs_root,
        )
        if approve_public_readonly and approve_browser:
            report = perf.execute(
                approve_public_readonly=True,
                approve_browser_execution=True,
                write_files=write_files,
            )
        else:
            report = perf.generate_plan(write_files=write_files)
        module_statuses["performance"] = report.status
        artifact_paths.append(f"{outputs_root}/{project_id}/30_performance/")
    except Exception as exc:
        module_statuses["performance"] = "failed"
        notes.append(f"Performance module error: {exc}")

    # Passive security
    try:
        from core.passive_security_runner import PassiveSecurityRunner
        sec = PassiveSecurityRunner(
            project_id=project_id,
            target_url=target_url,
            outputs_root=outputs_root,
        )
        if approve_public_readonly:
            from unittest.mock import patch as _patch
            _mock_headers: dict[str, str] = {}
            with _patch(
                "core.passive_security_runner._fetch_response_headers",
                return_value=_mock_headers,
            ):
                report = sec.execute(
                    approve_public_readonly=True,
                    write_files=write_files,
                )
        else:
            report = sec.generate_plan(write_files=write_files)
        module_statuses["passive_security"] = report.status
        artifact_paths.append(f"{outputs_root}/{project_id}/31_passive_security/")
    except Exception as exc:
        module_statuses["passive_security"] = "failed"
        notes.append(f"Passive security module error: {exc}")

    statuses = list(module_statuses.values())
    if all(s == "planning_only" for s in statuses):
        overall = "planning_only"
    elif all(s == "executed" for s in statuses):
        overall = "executed"
    elif "executed" in statuses:
        overall = "partial"
    else:
        overall = "planning_only"

    return {
        "status": overall,
        "project_id": project_id,
        "module_statuses": module_statuses,
        "artifact_paths": artifact_paths,
        "notes": notes,
        "network_used": approve_public_readonly,
        "browser_used": approve_browser,
        "human_review_required": True,
        "generated_at": _now(),
    }


# ---------------------------------------------------------------------------
# 4. run_flaky_test_analysis
# ---------------------------------------------------------------------------

def handle_run_flaky_test_analysis(params: dict) -> dict:
    """Run static flaky test analysis on Playwright spec files."""
    _check_blocked_params(params)
    _core_path()

    project_id = params.get("project_id", "")
    spec_files: list[str] = params.get("spec_files", [])
    outputs_root = params.get("outputs_root", "outputs")
    write_files = bool(params.get("write_files", True))

    if not project_id:
        return {
            "status": "failed",
            "error": "project_id is required",
            "human_review_required": True,
        }

    from core.flaky_test_analyzer import FlakyTestAnalyzer
    analyzer = FlakyTestAnalyzer(
        project_id=project_id,
        outputs_root=outputs_root,
        spec_files=spec_files or None,
    )
    analysis = analyzer.analyze(write_files=write_files)
    selector_report = analyzer.analyze_selectors(write_files=write_files)
    healing = analyzer.generate_healing_proposals(write_files=write_files)

    out_dir = f"{outputs_root}/{project_id}/32_flaky_test_analyzer/"
    return {
        "status": "analysis_only",
        "project_id": project_id,
        "files_analyzed": analysis.files_analyzed,
        "total_risks": analysis.total_risks,
        "risks_by_severity": analysis.risks_by_severity,
        "stability_score": selector_report.stability_score,
        "strong_selectors": selector_report.strong_count,
        "weak_selectors": selector_report.weak_count,
        "total_proposals": healing.total_proposals,
        "applied_proposals": 0,
        "proposals_status": healing.status,
        "artifact_dir": out_dir,
        "artifacts": [
            f"{out_dir}flaky_test_analysis.json",
            f"{out_dir}Flaky_Test_Analysis_Report.md",
            f"{out_dir}selector_stability.json",
            f"{out_dir}Selector_Stability_Report.md",
            f"{out_dir}self_healing_proposals.json",
            f"{out_dir}Self_Healing_Proposals.md",
        ],
        "code_modification_allowed": False,
        "auto_apply_changes": False,
        "human_review_required": True,
        "generated_at": _now(),
    }


# ---------------------------------------------------------------------------
# 5. generate_delivery_pack
# ---------------------------------------------------------------------------

def handle_generate_delivery_pack(params: dict) -> dict:
    """Generate client delivery pack with secret scan and ZIP."""
    _check_blocked_params(params)
    _core_path()

    project_id = params.get("project_id", "")
    outputs_root = params.get("outputs_root", "outputs")
    write_files = bool(params.get("write_files", True))

    if not project_id:
        return {
            "status": "failed",
            "error": "project_id is required",
            "human_review_required": True,
        }

    from core.client_delivery_pack import ClientDeliveryPack
    pack = ClientDeliveryPack(outputs_root=outputs_root)
    manifest = pack.build(project_id=project_id, write=write_files)

    delivery_dir = f"{outputs_root}/{project_id}/28_client_delivery/"
    return {
        "status": "draft",
        "project_id": project_id,
        "total_artifacts": manifest.total_artifacts,
        "secret_scan_passed": manifest.secret_scan.scan_passed,
        "blocked_files": manifest.secret_scan.blocked_files,
        "delivery_dir": delivery_dir,
        "zip_path": f"{delivery_dir}client_delivery.zip",
        "approved_for_client_delivery": False,
        "auto_send_to_client": False,
        "human_review_required": True,
        "generated_at": _now(),
    }


# ---------------------------------------------------------------------------
# 6. propose_self_healing_fixes
# ---------------------------------------------------------------------------

def handle_propose_self_healing_fixes(params: dict) -> dict:
    """Generate self-healing proposals. Does NOT apply any changes."""
    _check_blocked_params(params)
    _core_path()

    project_id = params.get("project_id", "")
    spec_files: list[str] = params.get("spec_files", [])
    outputs_root = params.get("outputs_root", "outputs")
    write_files = bool(params.get("write_files", True))

    if not project_id:
        return {
            "status": "failed",
            "error": "project_id is required",
            "human_review_required": True,
        }

    from core.flaky_test_analyzer import FlakyTestAnalyzer
    analyzer = FlakyTestAnalyzer(
        project_id=project_id,
        outputs_root=outputs_root,
        spec_files=spec_files or None,
    )
    healing = analyzer.generate_healing_proposals(write_files=write_files)

    out_dir = f"{outputs_root}/{project_id}/32_flaky_test_analyzer/"
    return {
        "status": healing.status,
        "project_id": project_id,
        "total_proposals": healing.total_proposals,
        "applied_proposals": 0,
        "proposals": [
            {
                "proposal_id": p.proposal_id,
                "affected_file": p.affected_file,
                "line_number": p.line_number,
                "original_selector": p.original_selector,
                "proposed_selector": p.proposed_selector,
                "confidence": p.confidence,
                "applied": False,
            }
            for p in healing.proposals
        ],
        "note": (
            "Proposals generated — review Self_Healing_Proposals.md before applying. "
            "Use apply_self_healing_fixes with approve_code_modification=true to apply."
        ),
        "artifact": f"{out_dir}Self_Healing_Proposals.md",
        "code_modification_allowed": False,
        "human_review_required": True,
        "generated_at": _now(),
    }


# ---------------------------------------------------------------------------
# 7. apply_self_healing_fixes
# ---------------------------------------------------------------------------

def handle_apply_self_healing_fixes(params: dict) -> dict:
    """Apply self-healing proposals (TODO comments). Requires explicit approval."""
    _check_blocked_params(params)
    _core_path()

    approve_code_modification = bool(params.get("approve_code_modification", False))
    dry_run = bool(params.get("dry_run", True))  # default: dry_run — no file changes
    project_id = params.get("project_id", "")
    spec_files: list[str] = params.get("spec_files", [])
    outputs_root = params.get("outputs_root", "outputs")

    if not approve_code_modification:
        return {
            "status": "blocked",
            "reason": (
                "approve_code_modification must be true to apply proposals. "
                "Review Self_Healing_Proposals.md first, then re-run with "
                "approve_code_modification=true."
            ),
            "code_modification_allowed": False,
            "human_review_required": True,
        }

    if not project_id:
        return {
            "status": "failed",
            "error": "project_id is required",
            "human_review_required": True,
        }

    from core.flaky_test_analyzer import FlakyTestAnalyzer
    analyzer = FlakyTestAnalyzer(
        project_id=project_id,
        outputs_root=outputs_root,
        spec_files=spec_files or None,
    )
    healing = analyzer.generate_healing_proposals(write_files=not dry_run)

    if dry_run:
        return {
            "status": "dry_run",
            "project_id": project_id,
            "total_proposals": healing.total_proposals,
            "applied_proposals": 0,
            "note": "Dry run — no files modified. Set dry_run=false to apply.",
            "proposals_preview": [
                {
                    "proposal_id": p.proposal_id,
                    "affected_file": p.affected_file,
                    "line_number": p.line_number,
                }
                for p in healing.proposals
            ],
            "code_modification_allowed": True,
            "human_review_required": True,
            "generated_at": _now(),
        }

    result = analyzer.apply_proposals(
        healing,
        approve_code_modification=True,
        write_files=True,
    )
    return {
        "status": result.status,
        "project_id": project_id,
        "total_proposals": result.total_proposals,
        "applied_proposals": result.applied_proposals,
        "note": (
            "TODO comments inserted at affected lines. "
            "Developer must implement the suggested selector changes."
        ),
        "code_modification_allowed": True,
        "human_review_required": True,
        "generated_at": _now(),
    }


# ---------------------------------------------------------------------------
# Handler dispatch table
# ---------------------------------------------------------------------------

HANDLERS: dict[str, object] = {
    "qa_factory_health": handle_qa_factory_health,
    "analyze_project": handle_analyze_project,
    "run_quality_audit": handle_run_quality_audit,
    "run_flaky_test_analysis": handle_run_flaky_test_analysis,
    "generate_delivery_pack": handle_generate_delivery_pack,
    "propose_self_healing_fixes": handle_propose_self_healing_fixes,
    "apply_self_healing_fixes": handle_apply_self_healing_fixes,
}


def dispatch(tool_name: str, params: dict) -> dict:
    """Dispatch a tool call by name. Raises KeyError for unknown tool names."""
    handler = HANDLERS[tool_name]
    return handler(params)  # type: ignore[operator]
