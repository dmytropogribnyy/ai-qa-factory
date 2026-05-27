"""
Phase 7R — Auth Demo Workflow.

Orchestrates Phase 7A/7B/7C/7D runners to produce a complete
authentication coverage demonstration using a controlled demo project.

No real credentials or storageState required — all scenarios run in
planning-only or blocked mode to show the full auth workbench story.

Safety contract:
- approved_for_client_delivery is always False.
- human_review_required is always True.
- No credential values are written to any artifact.
- Blocked safety cases are documented, never circumvented.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from core.auth_capability_planner import AuthCapabilityPlanner
from core.auth_strategy_selector import AuthStrategySelector
from core.email_password_runner import EmailPasswordRunner
from core.google_oauth_runner import GoogleOAuthRunner
from core.schemas.auth_capability import AuthCapabilityInputs
from core.schemas.email_password import (
    ORANGEHRM_DEFAULT_LOGIN_URL,
    ORANGEHRM_DEFAULT_SUCCESS_URL,
    EmailPasswordInputs,
)
from core.schemas.google_oauth import GoogleOAuthInputs

DEMO_PROJECT_ID = "demo-auth-workflow"


@dataclass
class AuthDemoScenario:
    """A single auth scenario result in the demo workflow."""

    name: str
    phase: str
    category: str  # "executed" | "planned" | "skipped" | "blocked"
    status: str
    description: str
    auth_coverage_summary: str = ""
    artifact_dir: str = ""


@dataclass
class AuthDemoResult:
    """Complete result from the Phase 7R auth demo workflow."""

    project_id: str
    scenarios: List[AuthDemoScenario]
    capability_plan_path: str = ""
    strategy_decision_path: str = ""
    google_oauth_report_path: str = ""
    email_password_report_path: str = ""
    client_report_path: str = ""

    # Safety invariants — always reset by __post_init__
    approved_for_client_delivery: bool = False
    human_review_required: bool = True

    def __post_init__(self) -> None:
        self.approved_for_client_delivery = False
        self.human_review_required = True

    def to_dict(self) -> dict:
        return {
            "project_id": self.project_id,
            "scenarios": [
                {
                    "name": s.name,
                    "phase": s.phase,
                    "category": s.category,
                    "status": s.status,
                    "description": s.description,
                    "auth_coverage_summary": s.auth_coverage_summary,
                    "artifact_dir": s.artifact_dir,
                }
                for s in self.scenarios
            ],
            "capability_plan_path": self.capability_plan_path,
            "strategy_decision_path": self.strategy_decision_path,
            "google_oauth_report_path": self.google_oauth_report_path,
            "email_password_report_path": self.email_password_report_path,
            "client_report_path": self.client_report_path,
            "approved_for_client_delivery": self.approved_for_client_delivery,
            "human_review_required": self.human_review_required,
        }


# ---------------------------------------------------------------------------
# Blocked safety cases — documented explicitly in every demo run
# ---------------------------------------------------------------------------
_BLOCKED_SAFETY_CASES = [
    (
        "personal_account_blocked",
        "Personal account login always blocked (personal_account_allowed=False hardcoded in all schemas)",
    ),
    (
        "production_account_blocked",
        "Production account login always blocked (production_account_allowed=False hardcoded in all schemas)",
    ),
    (
        "raw_password_cli_blocked",
        "Raw password/token/cookie via CLI always blocked (--password/--secret/--token/--cookie "
        "exit 1 before argparse in 7C and 7D CLIs)",
    ),
    (
        "captcha_bypass_blocked",
        "CAPTCHA bypass always blocked (captcha_bypass_allowed=False hardcoded; URLs with "
        "'captcha'/'recaptcha'/'anti-bot' blocked by _is_allowed_url())",
    ),
]


class AuthDemoWorkflow:
    """Phase 7R — orchestrate full auth demo across Phases 7A/7B/7C/7D."""

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self.outputs_root = outputs_root or Path("outputs")

    def run(self, project_id: str = DEMO_PROJECT_ID) -> AuthDemoResult:
        """
        Run the full auth demo workflow.

        Produces planning-only and blocked results for all auth scenarios.
        No real credentials or storageState required.
        """
        scenarios: list[AuthDemoScenario] = []

        # ----------------------------------------------------------------
        # Phase 7A — Auth Capability Planner
        # ----------------------------------------------------------------
        cap_inputs = AuthCapabilityInputs(
            project_id=project_id,
            target_url="https://accounts.google.com",
            has_google_account=True,
            has_dedicated_test_account=True,
            password_env_var="ORANGEHRM_PASSWORD",
            outputs_root=str(self.outputs_root),
            write_files=True,
        )
        planner = AuthCapabilityPlanner(cap_inputs)
        cap_plan = planner.run()
        cap_plan_path = str(
            self.outputs_root / project_id / "34_auth_capability" / "auth_capability_plan.json"
        )
        scenarios.append(
            AuthDemoScenario(
                name="auth_capability_plan",
                phase="7A",
                category="planned",
                status="planning_only",
                description=(
                    "Auth capability plan generated: 15 methods classified. "
                    "email_password and google_oauth identified as candidates."
                ),
                artifact_dir=str(self.outputs_root / project_id / "34_auth_capability"),
            )
        )

        # ----------------------------------------------------------------
        # Phase 7B — Auth Strategy Selector
        # ----------------------------------------------------------------
        selector = AuthStrategySelector(
            plan=cap_plan,
            outputs_root=str(self.outputs_root),
            write_files=True,
        )
        decision = selector.run()
        strategy_path = str(
            self.outputs_root
            / project_id
            / "35_auth_strategy"
            / "auth_strategy_decision.json"
        )
        scenarios.append(
            AuthDemoScenario(
                name="auth_strategy_decision",
                phase="7B",
                category="planned",
                status=decision.decision_status.value,
                description=(
                    f"Strategy selected: '{decision.selected_method or 'none'}'. "
                    f"Reason: {decision.reason}"
                ),
                artifact_dir=str(self.outputs_root / project_id / "35_auth_strategy"),
            )
        )

        # ----------------------------------------------------------------
        # Phase 7C — Google OAuth (storageState missing → skipped)
        # ----------------------------------------------------------------
        oauth_runner = GoogleOAuthRunner(outputs_root=self.outputs_root)
        oauth_inputs = GoogleOAuthInputs(
            project_id=project_id,
            target_url="https://accounts.google.com",
            storage_state_path="",  # deliberately absent for demo
            account_email_label="(demo — no storageState captured)",
            dedicated_test_account_confirmed=True,
            google_test_account_confirmed=True,
            approve_execution=False,
        )
        oauth_plan = oauth_runner.build_plan(oauth_inputs)
        oauth_result = oauth_runner.run(oauth_inputs)
        oauth_artifacts = oauth_runner.render_artifacts(oauth_plan, oauth_result, project_id)
        oauth_report_path = oauth_artifacts.get("google_oauth_report_json", "")

        scenarios.append(
            AuthDemoScenario(
                name="google_oauth_storagestate_missing",
                phase="7C",
                category="skipped",
                status=oauth_result.status.value,
                description=(
                    "Google OAuth storageState reuse: skipped — storageState file not captured. "
                    "Run capture_google.cjs in the Playwright scaffold to capture a session."
                ),
                auth_coverage_summary=oauth_result.auth_coverage_summary,
                artifact_dir=str(self.outputs_root / project_id / "16_google_oauth"),
            )
        )

        # ----------------------------------------------------------------
        # Phase 7D — Email/Password (env vars / approval status → skipped or blocked)
        # ----------------------------------------------------------------
        ep_runner = EmailPasswordRunner(outputs_root=self.outputs_root)
        ep_inputs = EmailPasswordInputs(
            project_id=project_id,
            target_name="orangehrm_demo",
            login_url=ORANGEHRM_DEFAULT_LOGIN_URL,
            success_url=ORANGEHRM_DEFAULT_SUCCESS_URL,
            username_env_var="ORANGEHRM_USERNAME",
            password_env_var="ORANGEHRM_PASSWORD",
            account_label="(demo — dedicated test account)",
            dedicated_test_account_confirmed=True,
            approve_execution=False,
        )
        ep_plan = ep_runner.build_plan(ep_inputs)
        ep_result = ep_runner.run(ep_inputs)
        ep_artifacts = ep_runner.render_artifacts(ep_plan, ep_result, project_id)
        ep_report_path = ep_artifacts.get("email_password_report_json", "")

        u_set, p_set = ep_runner.check_env_vars(ep_inputs)
        if not (u_set and p_set):
            ep_category = "skipped"
            ep_desc = (
                "Email/password (OrangeHRM demo): skipped — "
                "ORANGEHRM_USERNAME and/or ORANGEHRM_PASSWORD env vars not set. "
                "Set them at OS level and re-run with --approve-execution."
            )
        else:
            ep_category = "blocked"
            ep_desc = (
                "Email/password (OrangeHRM demo): blocked — "
                "env vars set but --approve-execution flag not passed."
            )

        scenarios.append(
            AuthDemoScenario(
                name="email_password_orangehrm",
                phase="7D",
                category=ep_category,
                status=ep_result.status.value,
                description=ep_desc,
                auth_coverage_summary=ep_result.auth_coverage_summary,
                artifact_dir=str(self.outputs_root / project_id / "37_email_password_auth"),
            )
        )

        # ----------------------------------------------------------------
        # Blocked safety cases — documented, never circumvented
        # ----------------------------------------------------------------
        for name, description in _BLOCKED_SAFETY_CASES:
            scenarios.append(
                AuthDemoScenario(
                    name=name,
                    phase="safety",
                    category="blocked",
                    status="blocked",
                    description=description,
                    auth_coverage_summary=f"Safety invariant: {name}",
                )
            )

        # ----------------------------------------------------------------
        # Client report
        # ----------------------------------------------------------------
        client_report_path = self._render_client_report(
            project_id=project_id,
            scenarios=scenarios,
            cap_plan_path=cap_plan_path,
            strategy_path=strategy_path,
        )

        return AuthDemoResult(
            project_id=project_id,
            scenarios=scenarios,
            capability_plan_path=cap_plan_path,
            strategy_decision_path=strategy_path,
            google_oauth_report_path=oauth_report_path,
            email_password_report_path=ep_report_path,
            client_report_path=str(client_report_path),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _render_client_report(
        self,
        project_id: str,
        scenarios: list[AuthDemoScenario],
        cap_plan_path: str,
        strategy_path: str,
    ) -> Path:
        out_dir = self.outputs_root / project_id / "33_client_audit"
        out_dir.mkdir(parents=True, exist_ok=True)

        executed = [s for s in scenarios if s.category == "executed"]
        planned = [s for s in scenarios if s.category == "planned"]
        skipped = [s for s in scenarios if s.category == "skipped"]
        blocked = [s for s in scenarios if s.category == "blocked"]

        lines = [
            f"# Client Report — {project_id}",
            "",
            "**Status:** Draft",
            "**approved_for_client_delivery:** False",
            "**human_review_required:** True",
            "",
            "---",
            "",
            "## Authentication Coverage",
            "",
        ]

        # Executed
        lines.append("### Executed Auth Flows")
        lines.append("")
        if executed:
            for s in executed:
                lines.append(f"- **{s.name}** (Phase {s.phase}): {s.description}")
                if s.auth_coverage_summary:
                    lines.append(f"  - Coverage: {s.auth_coverage_summary}")
        else:
            lines.append(
                "_(none — demo mode: no real credentials or storageState provided)_"
            )
        lines.append("")

        # Planned
        if planned:
            lines.append("### Planned Auth Flows")
            lines.append("")
            for s in planned:
                lines.append(f"- **{s.name}** (Phase {s.phase}): {s.description}")
            lines.append("")

        # Skipped
        if skipped:
            lines.append("### Skipped Auth Flows")
            lines.append("")
            for s in skipped:
                lines.append(f"- **{s.name}** (Phase {s.phase}): {s.description}")
                if s.auth_coverage_summary:
                    lines.append(f"  - Coverage: {s.auth_coverage_summary}")
            lines.append("")

        # Blocked
        if blocked:
            lines.append("### Blocked Auth Flows")
            lines.append("")
            for s in blocked:
                lines.append(f"- **{s.name}** (Phase {s.phase}): {s.description}")
            lines.append("")

        lines += [
            "---",
            "",
            "## Evidence References",
            "",
            f"- Auth capability plan: `{cap_plan_path}`",
            f"- Auth strategy decision: `{strategy_path}`",
            "",
            "---",
            "",
            "## Safety Boundary",
            "",
            "| Flag | Value |",
            "|---|---|",
            "| `approved_for_client_delivery` | `False` |",
            "| `human_review_required` | `True` |",
            "| `raw_secrets_allowed` | `False` |",
            "| `personal_account_allowed` | `False` |",
            "| `production_account_allowed` | `False` |",
            "| `captcha_bypass_allowed` | `False` |",
            "| `credential_logging_allowed` | `False` |",
            "",
            "_This report is a draft. Human review required before any client delivery._",
        ]

        report_path = out_dir / "client_report.md"
        report_path.write_text("\n".join(lines), encoding="utf-8")
        return report_path
