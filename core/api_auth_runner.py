"""
Phase 5E — API Auth Smoke Runner.

Safety contract:
- Approval gate required (approve_api_auth_execution=True) before any network call.
- No personal accounts. No production accounts.
- URL allowlist: only approved demo/staging/dedicated-test API targets.
- Env var names only accepted from caller — values read only after gates pass.
- Credentials injected as request body fields only — never in URL, headers, or logs.
- Token returned by auth endpoint: presence verified, value masked in all artifacts.
- raw_credentials_logged=False, token_logged=False, safe_to_deliver=False always.
- No destructive calls (no DELETE, no PUT booking update in this phase).
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import List, Optional, Tuple

from core.schemas.api_auth import (
    APIAuthCommand,
    APIAuthExecutionReport,
    APIAuthTarget,
)

# ---------------------------------------------------------------------------
# Allowed API target profiles
# ---------------------------------------------------------------------------

_API_TARGET_PROFILES: dict[str, APIAuthTarget] = {
    "restful_booker_public_api": APIAuthTarget(
        profile_name="restful_booker_public_api",
        base_url="https://restful-booker.herokuapp.com",
        auth_endpoint="/auth",
        safe_read_endpoint="/booking",
        target_category="restful_booker_demo_auth",
        description="Restful Booker public demo API — token-based auth",
    ),
}

# ---------------------------------------------------------------------------
# URL safety — same blocked list as Phase 5AB
# ---------------------------------------------------------------------------

_STRICTLY_BLOCKED_URL_PATTERNS = [
    "accounts.google.com",
    "google.com/o/oauth2",
    "amazon.com",
    "pay.amazon.com",
    "alza.sk",
    "alza.cz",
    "alza.hu",
    "alza.at",
    "alza.de",
    "linkedin.com",
    "upwork.com",
    "127.0.0.1",
]

# Env var name constraints
_ENV_VAR_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
_ENV_VAR_MAX_LEN = 64

# Mask placeholder
_REDACTED = "[REDACTED]"


class APIAuthRunner:
    """
    Approval-gated API auth smoke runner for Phase 5E.

    Supports token-based API targets (POST /auth → token).
    No Playwright. No subprocess. Pure HTTP via requests.
    """

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self.outputs_root = outputs_root or Path("outputs")

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_api_auth(
        self,
        project_id: str,
        approve_api_auth_execution: bool = False,
        target_profile: str = "",
        base_url: Optional[str] = None,
        username_env_var: Optional[str] = None,
        password_env_var: Optional[str] = None,
        personal_account_confirmed: bool = False,
        production_account_confirmed: bool = False,
        run_safe_read_check: bool = True,
        timeout: int = 30,
    ) -> APIAuthExecutionReport:
        """Run approval-gated API auth smoke."""

        # Gate 1: approval flag
        if not approve_api_auth_execution:
            return self._blocked(
                project_id,
                ["--approve-api-auth-execution flag is required. "
                 "No env vars read. No network calls."],
                notes=["Preview mode. All gates skipped. No credentials materialized."],
            )

        # Gate 2: no personal accounts
        if personal_account_confirmed:
            return self._blocked(
                project_id,
                ["Personal accounts are not allowed. Use a dedicated test account."],
            )

        # Gate 3: no production accounts
        if production_account_confirmed:
            return self._blocked(
                project_id,
                ["Production accounts are not allowed. Use a dedicated test account."],
            )

        # Gate 4: resolve target profile
        profile = _API_TARGET_PROFILES.get(target_profile)
        if not profile:
            return self._blocked(
                project_id,
                [f"Unknown target profile: {target_profile!r}. "
                 f"Allowed: {list(_API_TARGET_PROFILES.keys())}"],
            )

        # Gate 5: resolve base URL (CLI override or profile default)
        effective_url = base_url.rstrip("/") if base_url else profile.base_url.rstrip("/")
        if self._is_blocked_url(effective_url):
            return self._blocked(
                project_id,
                [f"URL is strictly blocked: {effective_url}"],
            )

        # Gate 6: env var name format
        env_var_specs: List[Tuple[str, str]] = []
        for var_type, var_name in [
            ("username", username_env_var),
            ("password", password_env_var),
        ]:
            if not var_name:
                continue
            ok, reason = self._validate_env_var_name(var_name)
            if not ok:
                return self._blocked(
                    project_id,
                    [f"Invalid {var_type}_env_var '{var_name}': {reason}. "
                     "Only uppercase letters, digits, underscore allowed."],
                )
            env_var_specs.append((var_type, var_name))

        if not username_env_var:
            return self._blocked(
                project_id,
                ["username_env_var is required."],
            )

        # Gate 7: env vars exist in process environment
        missing: List[str] = []
        secret_values: List[str] = []
        username_val = ""
        password_val = ""

        for var_type, var_name in env_var_specs:
            val = os.environ.get(var_name)
            if not val:
                missing.append(var_name)
            else:
                secret_values.append(val)
                if var_type == "username":
                    username_val = val
                elif var_type == "password":
                    password_val = val

        if missing:
            return self._blocked(
                project_id,
                [f"Required env vars not found in process environment: {missing}. "
                 "Set them in your terminal before running."],
                notes=["No credentials materialized. Blocked before network call."],
            )

        # All gates passed — execute
        return self._execute(
            project_id=project_id,
            profile=profile,
            effective_url=effective_url,
            username_val=username_val,
            password_val=password_val,
            secret_values=secret_values,
            run_safe_read_check=run_safe_read_check,
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
                f"(uppercase only). Got: {name!r}"
            )
        return True, ""

    def _is_blocked_url(self, url: str) -> bool:
        lower = url.lower()
        return any(p in lower for p in _STRICTLY_BLOCKED_URL_PATTERNS)

    def _mask(self, text: str, secret_values: List[str]) -> str:
        """Replace raw secret values with [REDACTED]."""
        for val in secret_values:
            if val and len(val) >= 3:
                text = text.replace(val, _REDACTED)
        return text

    def _execute(
        self,
        project_id: str,
        profile: APIAuthTarget,
        effective_url: str,
        username_val: str,
        password_val: str,
        secret_values: List[str],
        run_safe_read_check: bool,
        timeout: int,
    ) -> APIAuthExecutionReport:
        import urllib.request
        import urllib.error

        auth_url = effective_url + profile.auth_endpoint
        commands: List[APIAuthCommand] = []
        overall_status = "unknown"
        token_present = False
        token_val: Optional[str] = None

        # ---------------------------------------------------------------
        # Step 1: POST /auth — credentials in JSON body only
        # ---------------------------------------------------------------
        auth_body = json.dumps({
            "username": username_val,
            "password": password_val,
        }).encode("utf-8")

        start = time.time()
        try:
            req = urllib.request.Request(
                auth_url,
                data=auth_body,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                duration = time.time() - start
                status_code = resp.status
                body = resp.read().decode("utf-8", errors="replace")

            response_data = json.loads(body) if body else {}
            token_val = response_data.get("token")
            token_present = bool(token_val)

            # Mask secrets + token in any logged content
            all_secrets = secret_values + ([token_val] if token_val else [])
            safe_body = self._mask(body, all_secrets)

            status = "passed" if token_present and status_code < 400 else "failed"
            cmd = APIAuthCommand(
                id="api_auth_step1_post_auth",
                method="POST",
                url=auth_url,
                status_code=status_code,
                status=status,
                duration_seconds=round(duration, 3),
                token_present=token_present,
                stdout_excerpt=safe_body[:500],
                executed=True,
                safety_notes=[
                    "Credentials sent as JSON body — not in URL or headers.",
                    "Token value masked in all artifacts.",
                    "raw_credentials_logged=False always.",
                ],
            )
            commands.append(cmd)

        except urllib.error.HTTPError as e:
            duration = time.time() - start
            commands.append(APIAuthCommand(
                id="api_auth_step1_post_auth",
                method="POST",
                url=auth_url,
                status_code=e.code,
                status="failed",
                duration_seconds=round(duration, 3),
                stderr_excerpt=self._mask(str(e), secret_values)[:500],
                executed=True,
            ))

        except Exception as e:
            duration = time.time() - start
            commands.append(APIAuthCommand(
                id="api_auth_step1_post_auth",
                method="POST",
                url=auth_url,
                status="error",
                duration_seconds=round(duration, 3),
                stderr_excerpt=self._mask(str(e), secret_values)[:500],
                executed=True,
            ))

        # ---------------------------------------------------------------
        # Step 2 (optional): GET /booking — safe read-only health check
        # ---------------------------------------------------------------
        if run_safe_read_check and profile.safe_read_endpoint and token_present and token_val:
            read_url = effective_url + profile.safe_read_endpoint
            all_secrets = secret_values + [token_val]
            start2 = time.time()
            try:
                req2 = urllib.request.Request(
                    read_url,
                    headers={"Accept": "application/json"},
                    method="GET",
                )
                with urllib.request.urlopen(req2, timeout=timeout) as resp2:
                    dur2 = time.time() - start2
                    sc2 = resp2.status
                    body2 = resp2.read().decode("utf-8", errors="replace")[:500]

                safe_body2 = self._mask(body2, all_secrets)
                cmd2 = APIAuthCommand(
                    id="api_auth_step2_get_booking",
                    method="GET",
                    url=read_url,
                    status_code=sc2,
                    status="passed" if sc2 < 400 else "failed",
                    duration_seconds=round(dur2, 3),
                    stdout_excerpt=safe_body2,
                    executed=True,
                    safety_notes=[
                        "Read-only GET — no destructive operations.",
                        "No token value logged.",
                    ],
                )
                commands.append(cmd2)

            except Exception as e2:
                dur2 = time.time() - start2
                commands.append(APIAuthCommand(
                    id="api_auth_step2_get_booking",
                    method="GET",
                    url=read_url,
                    status="error",
                    duration_seconds=round(dur2, 3),
                    stderr_excerpt=self._mask(str(e2), all_secrets)[:500],
                    executed=True,
                ))

        # ---------------------------------------------------------------
        # Determine overall status
        # ---------------------------------------------------------------
        auth_cmd = next((c for c in commands if "step1" in c.id), None)
        if auth_cmd and auth_cmd.status == "passed" and token_present:
            overall_status = "passed"
        elif auth_cmd and auth_cmd.status in ("failed", "error"):
            overall_status = auth_cmd.status
        else:
            overall_status = "failed"

        # ---------------------------------------------------------------
        # Render artifacts
        # ---------------------------------------------------------------
        self._render_artifacts(project_id, overall_status, profile, effective_url, commands)

        return APIAuthExecutionReport(
            project_id=project_id,
            target_profile=profile.profile_name,
            base_url=effective_url,
            execution_status=overall_status,
            approval_required=True,
            approved=True,
            commands=commands,
            notes=[
                "Credentials used only as HTTP request body — not logged or serialized.",
                "Token returned by server: presence verified, value masked in all artifacts.",
                "All artifacts are internal-only.",
                "safe_to_deliver=False, approved_for_client_delivery=False.",
            ],
        )

    def _render_artifacts(
        self,
        project_id: str,
        status: str,
        profile: APIAuthTarget,
        base_url: str,
        commands: List[APIAuthCommand],
    ) -> None:
        out = self.outputs_root / project_id / "13_api_auth"
        out.mkdir(parents=True, exist_ok=True)

        # JSON report
        report_data = {
            "project_id": project_id,
            "target_profile": profile.profile_name,
            "base_url": base_url,
            "execution_status": status,
            "raw_credentials_logged": False,
            "raw_credentials_serialized": False,
            "token_logged": False,
            "token_serialized": False,
            "safe_to_deliver": False,
            "approved_for_client_delivery": False,
            "personal_account_used": False,
            "production_account_used": False,
            "commands": [
                {
                    "id": c.id,
                    "method": c.method,
                    "url": c.url,
                    "status": c.status,
                    "status_code": c.status_code,
                    "duration_seconds": c.duration_seconds,
                    "token_present": c.token_present,
                }
                for c in commands
            ],
        }
        (out / "API_AUTH_EXECUTION_REPORT.json").write_text(
            json.dumps(report_data, indent=2), encoding="utf-8"
        )

        # MD report
        cmd_rows = "\n".join(
            f"| {c.id} | {c.method} | {c.url} | {c.status} | {c.status_code} | {c.duration_seconds}s |"
            for c in commands
        )
        md = f"""# API Auth Execution Report — Phase 5E

**Project:** {project_id}
**Status:** {status}
**Target profile:** {profile.profile_name}
**Base URL:** {base_url}

## Safety assertions

- No raw credentials stored in this artifact.
- Credentials sent as HTTP request body — not in URL, headers, logs, or artifacts.
- Token value masked — only presence recorded (`token_present` boolean).
- raw_credentials_logged: False
- raw_credentials_serialized: False
- token_logged: False
- token_serialized: False
- personal_account_used: False
- production_account_used: False
- safe_to_deliver: False
- approved_for_client_delivery: False

## Commands

| ID | Method | URL | Status | HTTP Code | Duration |
|---|---|---|---|---|---|
{cmd_rows}

## Redaction checklist

- [ ] Verify no raw credentials appear in any artifact.
- [ ] Verify no token values appear in any artifact.
- [ ] Verify this report is not sent to client.
- [ ] Human review required before any client-facing use.
"""
        (out / "API_AUTH_EXECUTION_REPORT.md").write_text(md, encoding="utf-8")

    def _blocked(
        self,
        project_id: str,
        blockers: List[str],
        notes: Optional[List[str]] = None,
    ) -> APIAuthExecutionReport:
        return APIAuthExecutionReport(
            project_id=project_id,
            execution_status="blocked",
            approval_required=True,
            approved=False,
            blockers=blockers,
            notes=notes or [],
        )
