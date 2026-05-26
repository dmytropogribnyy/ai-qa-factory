"""DedicatedAuthRunner — Phase 5AB: Approval-gated dedicated test-account auth execution.

Safety boundaries (enforced on every call):
- No execution without --approve-dedicated-auth-execution flag.
- No personal accounts. No production accounts.
- No Google OAuth (accounts.google.com strictly blocked).
- No Alza/Amazon/LinkedIn/Upwork auth.
- No raw secret values in CLI args, artifacts, or logs.
- No .env reading. No storageState reading.
- No npm install. No npx playwright install.
- Subprocess only for allowlisted Playwright auth smoke commands.
- Secrets injected into subprocess env only — never in command args.
- storageState: outputs/<project_id>/12_dedicated_auth/.auth/ — internal only.
- safe_to_deliver=False, approved_for_client_delivery=False always.

Allowed lanes: dedicated_test_account_auth_future, staging_client_app_future.
Allowed targets: staging, client_test_environment, dedicated_test_environment,
                 plus named profiles: orangehrm_demo_auth, restful_booker_demo_auth,
                 dedicated_test_account_custom_target.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

from core.schemas.runtime_secret_routing import (
    DedicatedAuthExecutionCommand,
    DedicatedAuthExecutionReport,
    DedicatedAuthSessionArtifact,
    RuntimeSecretReference,
    TestAccountIntakeRequest,
    TestAccountValidationResult,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ALLOWED_LANES = frozenset({
    "dedicated_test_account_auth_future",
    "staging_client_app_future",
})

_ALLOWED_TARGET_CATEGORIES = frozenset({
    "staging",
    "client_test_environment",
    "dedicated_test_environment",
    # Named safe profiles (non-Google, non-real-ecommerce)
    "orangehrm_demo_auth",
    "restful_booker_demo_auth",
    "dedicated_test_account_custom_target",
    # Phase 5H: public demo auth targets (known demo credentials, no personal accounts)
    "saucedemo_demo_auth",       # standard_user / secret_sauce — public demo credentials
    "practice_site_demo_auth",   # practicesoftwaretesting.com, the-internet.herokuapp.com, demoqa.com
})

# URL patterns that are always blocked regardless of credentials
_STRICTLY_BLOCKED_URL_PATTERNS = [
    "accounts.google.com",   # Google OAuth — always blocked
    "google.com/o/oauth2",   # Google OAuth endpoint
    "amazon.com",
    "alza.sk", "alza.cz", "alza.hu", "alza.at", "alza.de",
    "linkedin.com",
    "upwork.com",
    "pay.amazon.com",
    "payments.amazon.com",
]

# Safe known target URL patterns for dedicated auth
_SAFE_TARGET_PATTERNS = [
    "opensource-demo.orangehrmlive.com",  # OrangeHRM public demo
    "automationintestingpractice.com",    # Restful Booker
    "restful-booker.herokuapp.com",
    "the-internet.herokuapp.com",
    "practicesoftwaretesting.com",
    "demoqa.com",
    "staging.",
    "qa.",
    "test.",
    "dev.",
    "localhost",
    "127.0.0.1",
]

# Allowlisted Playwright command bases
_ALLOWED_COMMAND_BASES = [
    "npx playwright test tests/auth",
]

# Blocked command patterns
_BLOCKED_COMMAND_PATTERNS = [
    "npm install",
    "npm run",
    "npm test",
    "npx playwright install",
    "--headed",
    "tests/ecommerce",
    "tests/admin",
    "tests/regression",
    "tests/api",
    "curl",
    "wget",
    "git clone",
]

# Env var name constraints
_ENV_VAR_MAX_LEN = 80
_ENV_VAR_PATTERN = re.compile(r'^[A-Z][A-Z0-9_]{0,79}$')

# Secret-looking value patterns (reject if env var name matches these)
_SECRET_VALUE_PATTERNS = [
    re.compile(r'@'),                      # email address
    re.compile(r'\s'),                     # whitespace
    re.compile(r'^eyJ'),                   # JWT
    re.compile(r'^sk-'),                   # OpenAI/Anthropic key prefix
    re.compile(r'^ghp_'),                  # GitHub PAT
    re.compile(r'[^A-Z0-9_]'),            # any non-env-var char
]


# ---------------------------------------------------------------------------
# DedicatedAuthRunner
# ---------------------------------------------------------------------------

class DedicatedAuthRunner:
    """Approval-gated runner for dedicated test-account auth execution.

    Never reads .env files. Never stores raw secrets. Never creates delivery packages.
    Subprocess is called only when all approval gates pass.
    """

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self.outputs_root = outputs_root or Path("outputs")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_intake(
        self,
        project_id: str,
        target_url: Optional[str] = None,
        target_category: str = "",
        scenario_lane: str = "",
        account_provider: str = "",
        account_type: str = "",
        username_env_var: Optional[str] = None,
        password_env_var: Optional[str] = None,
        token_env_var: Optional[str] = None,
        dedicated_test_account_confirmed: bool = False,
        personal_account_confirmed: bool = False,
        production_account_confirmed: bool = False,
        staging_environment_confirmed: bool = False,
        client_scope_confirmed: bool = False,
    ) -> TestAccountValidationResult:
        """Validate a test-account intake request without reading env var values or executing."""
        intake = TestAccountIntakeRequest(
            project_id=project_id,
            target_url=target_url,
            target_category=target_category,
            scenario_lane=scenario_lane,
            account_provider=account_provider,
            account_type=account_type,
            username_env_var=username_env_var,
            password_env_var=password_env_var,
            token_env_var=token_env_var,
            dedicated_test_account_confirmed=dedicated_test_account_confirmed,
            personal_account_confirmed=personal_account_confirmed,
            production_account_confirmed=production_account_confirmed,
            staging_environment_confirmed=staging_environment_confirmed,
            client_scope_confirmed=client_scope_confirmed,
        )

        blockers: List[str] = []
        warnings: List[str] = []
        accepted: List[RuntimeSecretReference] = []
        rejected: List[RuntimeSecretReference] = []

        # Personal / production account checks
        if personal_account_confirmed:
            blockers.append("Personal accounts are never allowed.")
        if production_account_confirmed:
            blockers.append("Production accounts are never allowed.")

        # Lane check
        if scenario_lane and scenario_lane not in _ALLOWED_LANES:
            if scenario_lane == "strictly_blocked":
                blockers.append(
                    f"Lane '{scenario_lane}' is strictly blocked. "
                    "Credentials cannot make a strictly-blocked scenario executable."
                )
            else:
                blockers.append(
                    f"Lane '{scenario_lane}' is not an approved dedicated auth lane. "
                    f"Allowed: {sorted(_ALLOWED_LANES)}"
                )

        # Target category check
        if target_category and target_category not in _ALLOWED_TARGET_CATEGORIES:
            blockers.append(
                f"Target category '{target_category}' is not allowed. "
                f"Allowed: {sorted(_ALLOWED_TARGET_CATEGORIES)}"
            )

        # URL check
        if target_url and self._is_blocked_url(target_url):
            blockers.append(
                f"Target URL is strictly blocked: {target_url}. "
                "Google OAuth, Alza, Amazon, LinkedIn, Upwork are never allowed."
            )

        # Env var name validation (names only — no values read)
        for var_type, var_name in [
            ("username", username_env_var),
            ("password", password_env_var),
            ("token", token_env_var),
        ]:
            if not var_name:
                continue
            valid, reason = self._validate_env_var_name(var_name)
            ref = RuntimeSecretReference(
                id=f"ref_{var_type}",
                label=f"{var_type} reference",
                env_var_name=var_name,
                secret_type=var_type,
                source_route="runtime_env_reference",
                approved_for_runtime_use=valid and not blockers,
            )
            if valid:
                accepted.append(ref)
            else:
                rejected.append(ref)
                blockers.append(f"Invalid {var_type}_env_var '{var_name}': {reason}")

        # Must have at least username or token
        if not username_env_var and not token_env_var:
            blockers.append("Either username_env_var or token_env_var must be provided.")

        # Scope confirmation
        if not dedicated_test_account_confirmed:
            blockers.append("dedicated_test_account_confirmed must be True.")
        if not staging_environment_confirmed and not client_scope_confirmed:
            blockers.append(
                "Either staging_environment_confirmed or client_scope_confirmed must be True."
            )

        status = "blocked" if blockers else ("valid" if not warnings else "valid_with_warnings")

        return TestAccountValidationResult(
            project_id=project_id,
            status=status,
            intake_request=intake,
            accepted_secret_references=accepted,
            rejected_secret_references=rejected,
            blockers=blockers,
            warnings=warnings,
            safe_for_future_execution=not blockers,
            # approved_for_execution_now always forced False by __post_init__
            notes=[
                "No env var values were read during validation.",
                "No subprocess was called.",
                "Validation checks env var name format and lane/category constraints only.",
            ],
        )

    def run_dedicated_auth(
        self,
        project_id: str,
        approve_dedicated_auth_execution: bool = False,
        scenario_lane: str = "",
        target_category: str = "",
        target_url: Optional[str] = None,
        username_env_var: Optional[str] = None,
        password_env_var: Optional[str] = None,
        token_env_var: Optional[str] = None,
        dedicated_test_account_confirmed: bool = False,
        staging_environment_confirmed: bool = False,
        client_scope_confirmed: bool = False,
        personal_account_confirmed: bool = False,
        production_account_confirmed: bool = False,
        command_mode: str = "auth_smoke",
        scaffold_root: Optional[Path] = None,
        timeout: int = 120,
    ) -> DedicatedAuthExecutionReport:
        """Run approval-gated dedicated test-account auth execution."""

        # Gate 1: approval flag — no env lookup, no subprocess without it
        if not approve_dedicated_auth_execution:
            return self._blocked(
                project_id,
                ["--approve-dedicated-auth-execution flag is required. "
                 "No env vars read. No subprocess called."],
                notes=["Preview mode. All gates skipped. No credentials materialized."],
            )

        # Gate 2: personal / production account
        if personal_account_confirmed:
            return self._blocked(
                project_id,
                ["Personal accounts are never allowed. personal_account_confirmed must be False."],
            )
        if production_account_confirmed:
            return self._blocked(
                project_id,
                ["Production accounts are never allowed. production_account_confirmed must be False."],
            )

        # Gate 3: scenario lane
        if scenario_lane not in _ALLOWED_LANES:
            extra = (
                " Credentials cannot make a strictly-blocked scenario executable."
                if scenario_lane == "strictly_blocked" else ""
            )
            return self._blocked(
                project_id,
                [f"Scenario lane '{scenario_lane}' not allowed.{extra} "
                 f"Allowed: {sorted(_ALLOWED_LANES)}"],
                scenario_lane=scenario_lane,
            )

        # Gate 4: target category
        if target_category not in _ALLOWED_TARGET_CATEGORIES:
            return self._blocked(
                project_id,
                [f"Target category '{target_category}' not allowed. "
                 f"Allowed: {sorted(_ALLOWED_TARGET_CATEGORIES)}"],
                scenario_lane=scenario_lane,
                target_category=target_category,
            )

        # Gate 5: blocked URL
        if target_url and self._is_blocked_url(target_url):
            return self._blocked(
                project_id,
                [f"Target URL is strictly blocked: {target_url}. "
                 "Google OAuth, Alza, Amazon, LinkedIn, Upwork are never allowed."],
                scenario_lane=scenario_lane,
                target_category=target_category,
                target_url=target_url,
            )

        # Gate 6: dedicated account + scope
        if not dedicated_test_account_confirmed:
            return self._blocked(
                project_id,
                ["dedicated_test_account_confirmed must be True."],
                scenario_lane=scenario_lane,
                target_category=target_category,
            )
        if not staging_environment_confirmed and not client_scope_confirmed:
            return self._blocked(
                project_id,
                ["Either staging_environment_confirmed or client_scope_confirmed must be True."],
                scenario_lane=scenario_lane,
                target_category=target_category,
            )

        # Gate 7: env var name format (no values read yet)
        env_var_specs: List[Tuple[str, str]] = []
        for var_type, var_name in [
            ("username", username_env_var),
            ("password", password_env_var),
            ("token", token_env_var),
        ]:
            if not var_name:
                continue
            valid, reason = self._validate_env_var_name(var_name)
            if not valid:
                return self._blocked(
                    project_id,
                    [f"Invalid {var_type}_env_var '{var_name}': {reason}. "
                     "Only uppercase letters, digits, underscore allowed (e.g. QA_TEST_USERNAME)."],
                    scenario_lane=scenario_lane,
                    target_category=target_category,
                )
            env_var_specs.append((var_type, var_name))

        if not username_env_var and not token_env_var:
            return self._blocked(
                project_id,
                ["Either username_env_var or token_env_var must be provided."],
                scenario_lane=scenario_lane,
                target_category=target_category,
            )

        # Gate 8: check env vars exist in process environment (values read here, not before)
        missing: List[str] = []
        secret_values: List[str] = []
        for _, var_name in env_var_specs:
            val = os.environ.get(var_name)
            if not val:
                missing.append(var_name)
            else:
                secret_values.append(val)

        if missing:
            return self._blocked(
                project_id,
                [f"Required env vars not found in process environment: {missing}. "
                 "Set them in your terminal before running."],
                scenario_lane=scenario_lane,
                target_category=target_category,
                target_url=target_url,
                notes=["No credentials materialized. Blocked before subprocess."],
            )

        # Gate 9: scaffold
        if scaffold_root is None:
            scaffold_root = self.outputs_root / project_id / "03_framework" / "playwright"

        scaffold_ok, scaffold_blocker = self._check_scaffold(scaffold_root)
        if not scaffold_ok:
            return self._blocked(
                project_id, [scaffold_blocker],
                scenario_lane=scenario_lane,
                target_category=target_category,
                target_url=target_url,
                scaffold_root=str(scaffold_root),
                notes=["No subprocess called."],
            )

        # All gates passed — build command and run
        return self._execute(
            project_id=project_id,
            scaffold_root=scaffold_root,
            command_mode=command_mode,
            scenario_lane=scenario_lane,
            target_category=target_category,
            target_url=target_url,
            secret_values=secret_values,
            username_env_var=username_env_var,
            password_env_var=password_env_var,
            target_url_for_env=target_url,
            timeout=timeout,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _validate_env_var_name(self, name: str) -> Tuple[bool, str]:
        if not name:
            return False, "Empty name"
        if len(name) > _ENV_VAR_MAX_LEN:
            return False, f"Too long ({len(name)} chars, max {_ENV_VAR_MAX_LEN})"
        if not _ENV_VAR_PATTERN.match(name):
            return False, (
                f"Invalid format: must match [A-Z][A-Z0-9_]* "
                f"(uppercase only, no spaces or special chars). Got: {name!r}"
            )
        return True, ""

    def _is_blocked_url(self, url: str) -> bool:
        lower = url.lower()
        return any(p in lower for p in _STRICTLY_BLOCKED_URL_PATTERNS)

    def _check_scaffold(self, scaffold_root: Path) -> Tuple[bool, str]:
        if not scaffold_root.exists():
            return False, (
                f"Scaffold not found: {scaffold_root}. "
                "Run Phase 3A scaffold generation first."
            )
        if not (scaffold_root / "node_modules").exists():
            return False, (
                f"node_modules not found in {scaffold_root}. "
                "Run Phase 3C toolchain validation (npm install) first. "
                "Do not run npm install automatically."
            )
        if not (scaffold_root / "tests" / "auth").exists():
            return False, (
                f"tests/auth not found in {scaffold_root}. "
                "Create auth test files before running dedicated auth execution."
            )
        return True, ""

    def _mask(self, text: str, secrets: List[str]) -> str:
        result = text
        for s in secrets:
            if s and len(s) > 2:
                result = result.replace(s, "[REDACTED]")
        return result

    def _blocked(
        self,
        project_id: str,
        blockers: List[str],
        *,
        scenario_lane: str = "",
        target_category: str = "",
        target_url: Optional[str] = None,
        scaffold_root: str = "",
        notes: Optional[List[str]] = None,
    ) -> DedicatedAuthExecutionReport:
        return DedicatedAuthExecutionReport(
            project_id=project_id,
            scaffold_root=scaffold_root,
            execution_status="blocked",
            approval_required=True,
            approved=False,
            scenario_lane=scenario_lane,
            target_category=target_category,
            target_url=target_url,
            blockers=blockers,
            notes=notes or [],
        )

    def _execute(
        self,
        project_id: str,
        scaffold_root: Path,
        command_mode: str,
        scenario_lane: str,
        target_category: str,
        target_url: Optional[str],
        secret_values: List[str],
        username_env_var: Optional[str],
        password_env_var: Optional[str],
        target_url_for_env: Optional[str],
        timeout: int,
    ) -> DedicatedAuthExecutionReport:
        # Build allowlisted command
        cmd_str = "npx playwright test tests/auth --reporter=list"
        # On Windows, subprocess cannot resolve .cmd shims without shell=True.
        # Resolve npx to its full path so the list-form exec works cross-platform.
        npx_exe = shutil.which("npx") if sys.platform == "win32" else "npx"
        if not npx_exe:
            npx_exe = "npx"
        cmd = [npx_exe] + cmd_str.split()[1:]

        # Verify against allowlist
        if not any(cmd_str.startswith(base) for base in _ALLOWED_COMMAND_BASES):
            return self._blocked(
                project_id,
                [f"Command not in allowlist: {cmd_str}"],
                scenario_lane=scenario_lane,
                target_category=target_category,
            )

        # Prepare output dir
        auth_out = self.outputs_root / project_id / "12_dedicated_auth"
        auth_dir = auth_out / ".auth"
        auth_dir.mkdir(parents=True, exist_ok=True)
        storage_state_path = (auth_dir / "storageState.json").resolve()

        # subprocess env inherits process env (which has the secrets already)
        proc_env = os.environ.copy()

        # Map target-specific env var names to the standard names the spec reads.
        # e.g. ORANGEHRM_USERNAME → QA_TEST_USERNAME so the spec's process.env lookup works.
        if username_env_var and proc_env.get(username_env_var):
            proc_env["QA_TEST_USERNAME"] = proc_env[username_env_var]
        if password_env_var and proc_env.get(password_env_var):
            proc_env["QA_TEST_PASSWORD"] = proc_env[password_env_var]
        if target_url_for_env:
            proc_env["BASE_URL"] = target_url_for_env
        proc_env["AUTH_STORAGE_STATE_PATH"] = str(storage_state_path)

        start = time.time()
        status = "unknown"
        exit_code: Optional[int] = None
        stdout_masked = ""
        stderr_masked = ""

        try:
            result = subprocess.run(
                cmd,
                cwd=str(scaffold_root),
                env=proc_env,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            duration = time.time() - start
            exit_code = result.returncode
            stdout_masked = self._mask((result.stdout or "")[:2000], secret_values)
            stderr_masked = self._mask((result.stderr or "")[:2000], secret_values)
            status = "passed" if exit_code == 0 else "failed"

        except subprocess.TimeoutExpired:
            duration = float(timeout)
            exit_code = -1
            stderr_masked = f"Timed out after {timeout}s"
            status = "timeout"
        except Exception as exc:
            duration = time.time() - start
            exit_code = -1
            stderr_masked = type(exc).__name__
            status = "error"

        command_record = DedicatedAuthExecutionCommand(
            id="dedicated_auth_cmd_001",
            command=cmd_str,  # no raw secret values in command string
            cwd=str(scaffold_root),
            status=status,
            exit_code=exit_code,
            duration_seconds=round(duration, 2),
            stdout_excerpt=stdout_masked,
            stderr_excerpt=stderr_masked,
            executed=True,
            safety_notes=[
                "Secrets injected into subprocess env only — not in command args.",
                "stdout/stderr redacted for raw credential values.",
                "storageState path recorded by reference only — content never read.",
            ],
        )

        artifacts: List[DedicatedAuthSessionArtifact] = []
        if storage_state_path.exists():
            artifacts.append(DedicatedAuthSessionArtifact(
                id="storage_state_001",
                artifact_type="storage_state",
                path=str(storage_state_path),
                notes=[
                    "storageState is internal-only. Must not be committed.",
                    "Must not be sent to client.",
                    "approved_for_commit=False always.",
                ],
            ))

        self._write_artifacts(auth_out, project_id, command_record, artifacts, scenario_lane,
                              target_category, target_url, status)

        return DedicatedAuthExecutionReport(
            project_id=project_id,
            scaffold_root=str(scaffold_root),
            execution_status=status,
            approval_required=True,
            approved=True,
            auth_execution_performed=True,
            browser_execution_performed=True,
            storage_state_created=storage_state_path.exists(),
            credentials_used=True,
            target_url=target_url,
            scenario_lane=scenario_lane,
            target_category=target_category,
            commands=[command_record],
            session_artifacts=artifacts,
            notes=[
                "Credentials used only in subprocess environment — not logged or serialized.",
                "All artifacts are internal-only.",
                "storageState approved_for_commit=False always.",
                "safe_to_deliver=False, approved_for_client_delivery=False.",
            ],
        )

    def _write_artifacts(
        self,
        out_dir: Path,
        project_id: str,
        command: DedicatedAuthExecutionCommand,
        artifacts: List[DedicatedAuthSessionArtifact],
        scenario_lane: str,
        target_category: str,
        target_url: Optional[str],
        status: str,
    ) -> None:
        import json

        out_dir.mkdir(parents=True, exist_ok=True)

        report_data = {
            "project_id": project_id,
            "execution_status": status,
            "scenario_lane": scenario_lane,
            "target_category": target_category,
            "target_url": target_url,
            "raw_credentials_logged": False,
            "raw_credentials_serialized": False,
            "personal_account_used": False,
            "production_account_used": False,
            "safe_to_deliver": False,
            "approved_for_client_delivery": False,
            "commands": [command.to_dict()],
            "session_artifacts": [a.to_dict() for a in artifacts],
            "notes": [
                "No raw credential values are stored in this artifact.",
                "Secrets were read from process environment only.",
                "storageState path recorded by reference only.",
            ],
        }
        (out_dir / "DEDICATED_AUTH_EXECUTION_REPORT.json").write_text(
            json.dumps(report_data, indent=2), encoding="utf-8"
        )

        approval_text = f"""# Dedicated Auth Execution Approval

**Project:** {project_id}
**Status:** {status}
**Scenario lane:** {scenario_lane}
**Target category:** {target_category}
**Target URL:** {target_url or "N/A"}

## Safety assertions

- No raw credentials stored in this artifact.
- Secrets read from process environment only — not from .env, chat, or CLI args.
- storageState is internal-only and must not be committed.
- personal\\_account\\_used: False
- production\\_account\\_used: False
- safe\\_to\\_deliver: False
- approved\\_for\\_client\\_delivery: False

## Command log

**Command:** `{command.command}`
**Exit code:** {command.exit_code}
**Duration:** {command.duration_seconds}s

## stdout excerpt

```
{command.stdout_excerpt or "(empty)"}
```

## stderr excerpt

```
{command.stderr_excerpt or "(empty)"}
```

## Redaction checklist

- [ ] Verify no raw credentials appear in any artifact.
- [ ] Verify storageState is gitignored.
- [ ] Verify this report is not sent to client.
- [ ] Human review required before any client-facing use.
"""
        (out_dir / "DEDICATED_AUTH_EXECUTION_REPORT.md").write_text(
            approval_text, encoding="utf-8"
        )

        command_log = f"""# Dedicated Auth Command Log

**Project:** {project_id}
**Status:** {status}

## Commands executed

| # | Command | Status | Exit code | Duration |
|---|---|---|---|---|
| 1 | `{command.command}` | {command.status} | {command.exit_code} | {command.duration_seconds}s |

## Safety notes

{chr(10).join(f'- {n}' for n in command.safety_notes)}

## Artifacts

{chr(10).join(f'- `{a.path}` (internal_only={a.internal_only})' for a in artifacts) or '- None'}

No raw credential values appear in this log.
"""
        (out_dir / "DEDICATED_AUTH_COMMAND_LOG.md").write_text(command_log, encoding="utf-8")

        checklist = f"""# Dedicated Auth Redaction Checklist

**Project:** {project_id}

Before any use of these artifacts, complete this checklist:

- [ ] No raw credentials appear in DEDICATED_AUTH_EXECUTION_REPORT.json
- [ ] No raw credentials appear in DEDICATED_AUTH_EXECUTION_REPORT.md
- [ ] No raw credentials appear in DEDICATED_AUTH_COMMAND_LOG.md
- [ ] storageState.json is gitignored (check .gitignore)
- [ ] storageState.json content has NOT been read or included in any artifact
- [ ] This artifact directory is NOT staged for commit
- [ ] This artifact is NOT included in client delivery

Human review required. Do not skip.
"""
        (out_dir / "DEDICATED_AUTH_REDACTION_CHECKLIST.md").write_text(
            checklist, encoding="utf-8"
        )
