"""Credential Safety Inspector — Phase 4E.

Scans local safe text artifacts for credential references, unsafe patterns,
sandbox classification, and produces the credential safety policy/report.

SAFETY:
- Never reads .env, .env.local, .auth/*.json, or storageState files.
- Never uses, stores, or logs credentials.
- Never executes login or auth flows.
- Never calls external APIs.
- Scanning is static text analysis of safe local files only.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from core.schemas.credential_safety import (
    AuthExecutionApproval,
    CredentialPolicy,
    CredentialReference,
    CredentialSafetyReport,
    SandboxProfileClassification,
    StorageStatePolicy,
)

_OUTPUTS_ROOT = Path("outputs")

# ---------------------------------------------------------------------------
# Forbidden file patterns — never read these
# ---------------------------------------------------------------------------

_FORBIDDEN_FILE_PATTERNS = [
    ".env",
    ".env.local",
    ".env.production",
    ".env.staging",
    ".env.test",
    ".auth",
    "storageState",
    "storage_state",
    "node_modules",
    ".venv",
    "__pycache__",
    "test-results",
    "playwright-report",
]

# ---------------------------------------------------------------------------
# Secret-like patterns to flag in scanned text
# ---------------------------------------------------------------------------

_SECRET_PATTERNS: List[Tuple[str, str]] = [
    (r"password\s*=\s*\S+", "password assignment"),
    (r"api[_-]?key\s*=\s*\S+", "API key assignment"),
    (r"token\s*=\s*\S+", "token assignment"),
    (r"\bbearer\s+[a-zA-Z0-9._-]{10,}", "bearer token"),
    (r"\bsk-[a-zA-Z0-9]{20,}", "OpenAI-style secret key"),
    (r"\bsk-ant-[a-zA-Z0-9]{20,}", "Anthropic secret key"),
    (r"\bxoxb-[0-9]+-[0-9]+-[a-zA-Z0-9]+", "Slack bot token"),
    (r"\bghp_[a-zA-Z0-9]{30,}", "GitHub PAT"),
    (r"eyJ[a-zA-Z0-9_-]{20,}\.eyJ[a-zA-Z0-9_-]{20,}", "JWT-like string"),
    (r"sessionid\s*=\s*\S+", "session ID"),
    (r"cookie\s*=\s*\S+", "cookie value"),
    (r"client[_-]?secret\s*=\s*\S+", "client secret"),
    (r"oauth[_-]?secret\s*=\s*\S+", "OAuth secret"),
    (r"refresh[_-]?token\s*=\s*\S+", "refresh token"),
    (r"access[_-]?token\s*=\s*\S+", "access token"),
]

# ---------------------------------------------------------------------------
# Allowed placeholder values — these are safe in synthetic fixtures
# ---------------------------------------------------------------------------

_ALLOWED_PLACEHOLDERS = {
    "FakeSecret123",
    "TEST_USERNAME",
    "TEST_PASSWORD",
    "BASE_URL",
    "API_BASE_URL",
    "PLACEHOLDER",
    "EXAMPLE",
    "your-api-key-here",
    "your-token-here",
    "changeme",
    "example.com",
    "test@example.com",
    "user@example.com",
}

# ---------------------------------------------------------------------------
# Sandbox classification rules
# ---------------------------------------------------------------------------

_SANDBOX_RULES: List[Dict[str, Any]] = [
    {
        "keywords": ["amazon pay sandbox", "amazon pay test"],
        "provider": "Amazon",
        "profile_type": "payment_sandbox",
        "classification": "future_sandbox_integration",
        "official_sandbox": True,
        "production_retail_account": False,
        "payment_sandbox": True,
        "requires_merchant_setup": True,
        "requires_dedicated_test_account": True,
        "allowed_in_future_phase": True,
        "blocked_in_current_phase": True,
        "notes": [
            "Amazon Pay Sandbox is an official sandbox for payment testing.",
            "Requires merchant setup and dedicated sandbox buyer account.",
            "Blocked in Phase 4E — allowed only in a future explicit sandbox phase.",
            "Amazon.com retail/marketplace account remains always blocked.",
        ],
    },
    {
        "keywords": ["amazon.com", "amazon retail", "amazon marketplace", "amazon account"],
        "provider": "Amazon",
        "profile_type": "production_retail",
        "classification": "blocked_production_retail",
        "official_sandbox": False,
        "production_retail_account": True,
        "payment_sandbox": False,
        "requires_merchant_setup": False,
        "requires_dedicated_test_account": False,
        "allowed_in_future_phase": False,
        "blocked_in_current_phase": True,
        "notes": [
            "Amazon.com retail/marketplace account is a production account.",
            "Always blocked as an execution target regardless of approval.",
            "Do not use personal Amazon accounts for QA automation.",
        ],
    },
    {
        "keywords": ["alza production", "alza account", "alza retail", "alza.sk account"],
        "provider": "Alza",
        "profile_type": "production_ecommerce",
        "classification": "blocked_production_ecommerce",
        "official_sandbox": False,
        "production_retail_account": True,
        "payment_sandbox": False,
        "requires_merchant_setup": False,
        "requires_dedicated_test_account": True,
        "allowed_in_future_phase": True,
        "blocked_in_current_phase": True,
        "notes": [
            "Alza.sk production/retail account is blocked in current phase.",
            "Requires client-provided staging/test account and explicit scope approval.",
            "Do not use personal Alza accounts for QA automation.",
            "Future auth/checkout testing requires official client test account only.",
        ],
    },
    {
        "keywords": ["alza staging", "alza test account", "alza sandbox"],
        "provider": "Alza",
        "profile_type": "staging_test_account",
        "classification": "future_sandbox_integration",
        "official_sandbox": False,
        "production_retail_account": False,
        "payment_sandbox": False,
        "requires_merchant_setup": False,
        "requires_dedicated_test_account": True,
        "allowed_in_future_phase": True,
        "blocked_in_current_phase": True,
        "notes": [
            "Alza staging/test account is a future candidate for auth execution.",
            "Requires explicit client approval and dedicated test account.",
            "Blocked in Phase 4E — allowed only with explicit phase + client scope.",
        ],
    },
    {
        "keywords": ["linear token", "linear api", "linear account", "linear.app"],
        "provider": "Linear",
        "profile_type": "task_source_integration",
        "classification": "blocked_task_source",
        "official_sandbox": False,
        "production_retail_account": False,
        "payment_sandbox": False,
        "requires_merchant_setup": False,
        "requires_dedicated_test_account": False,
        "allowed_in_future_phase": False,
        "blocked_in_current_phase": True,
        "notes": [
            "Linear API tokens/accounts are task-source integrations, not test targets.",
            "Blocked as execution targets in all current and planned phases.",
            "Linear/Jira/ClickUp are requirement sources only.",
        ],
    },
    {
        "keywords": ["google account", "google oauth", "gmail account", "oauth personal"],
        "provider": "Google",
        "profile_type": "personal_oauth",
        "classification": "blocked_personal_account",
        "official_sandbox": False,
        "production_retail_account": False,
        "payment_sandbox": False,
        "requires_merchant_setup": False,
        "requires_dedicated_test_account": True,
        "allowed_in_future_phase": False,
        "blocked_in_current_phase": True,
        "notes": [
            "Personal Google/OAuth accounts are blocked for QA automation.",
            "Use dedicated test accounts only — never personal/client accounts.",
        ],
    },
    {
        "keywords": ["saucedemo", "saucedemo.com"],
        "provider": "SauceDemo",
        "profile_type": "public_demo",
        "classification": "public_demo",
        "official_sandbox": True,
        "production_retail_account": False,
        "payment_sandbox": False,
        "requires_merchant_setup": False,
        "requires_dedicated_test_account": False,
        "allowed_in_future_phase": True,
        "blocked_in_current_phase": True,  # All auth execution blocked in Phase 4E
        "notes": [
            "SauceDemo is a public practice e-commerce site with known demo credentials.",
            "Demo credentials (standard_user/secret_sauce) are public — not a secret.",
            "Allowed in Phase 4D with --approve-demo-execution.",
            "Blocked in Phase 4E credential safety context — auth execution requires future approval.",
        ],
    },
    {
        "keywords": ["dedicated staging", "dedicated test account", "test account staging"],
        "provider": "generic",
        "profile_type": "dedicated_staging",
        "classification": "future_sandbox_integration",
        "official_sandbox": False,
        "production_retail_account": False,
        "payment_sandbox": False,
        "requires_merchant_setup": False,
        "requires_dedicated_test_account": True,
        "allowed_in_future_phase": True,
        "blocked_in_current_phase": True,
        "notes": [
            "Dedicated staging/test accounts are the correct approach for future auth execution.",
            "Still blocked in Phase 4E — requires explicit future phase approval.",
            "Client must provide test account credentials via secure channel at execution time.",
        ],
    },
]


class CredentialSafetyInspector:
    """Scans local safe text artifacts and produces credential safety assessments.

    Never reads .env, .auth, storageState, or secret vault files.
    Never uses, stores, or executes credentials.
    """

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self._outputs_root = outputs_root or _OUTPUTS_ROOT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def inspect_credentials(
        self,
        project_id: str,
        include_fixtures: bool = False,
        include_scaffold: bool = False,
        strict: bool = False,
    ) -> CredentialSafetyReport:
        """Inspect local safe artifacts. Returns CredentialSafetyReport."""
        detected: List[CredentialReference] = []
        blockers: List[str] = []
        warnings: List[str] = []

        # Scan scaffold if requested
        if include_scaffold:
            scaffold_root = self._outputs_root / project_id / "03_framework" / "playwright"
            if scaffold_root.exists():
                scaffold_issues = self._scan_directory(
                    scaffold_root,
                    context="scaffold",
                    allow_fake_fixture=False,
                )
                detected.extend(scaffold_issues["detected"])
                blockers.extend(scaffold_issues["blockers"])
                warnings.extend(scaffold_issues["warnings"])

        # Scan fixtures if requested
        if include_fixtures:
            fixtures_root = Path("fixtures") / "client_scenarios"
            if fixtures_root.exists():
                fixture_issues = self._scan_directory(
                    fixtures_root,
                    context="fixture",
                    allow_fake_fixture=True,
                )
                detected.extend(fixture_issues["detected"])
                blockers.extend(fixture_issues["blockers"])
                warnings.extend(fixture_issues["warnings"])

        # Scan project docs under outputs/<project_id>/00_project/
        project_docs = self._outputs_root / project_id / "00_project"
        if project_docs.exists():
            doc_issues = self._scan_directory(
                project_docs,
                context="project_docs",
                allow_fake_fixture=False,
            )
            detected.extend(doc_issues["detected"])
            blockers.extend(doc_issues["blockers"])
            warnings.extend(doc_issues["warnings"])

        # Check gitignore for required patterns
        gitignore_warnings = self._check_gitignore()
        warnings.extend(gitignore_warnings)

        sandbox_profiles = self.classify_sandbox_profiles([])

        status = "pass" if not blockers else "blocked"
        report = CredentialSafetyReport(
            project_id=project_id,
            status=status,
            credentials_detected=detected,
            test_accounts=[],
            sandbox_profiles=sandbox_profiles,
            blockers=blockers,
            warnings=warnings,
            safe_for_storage_state=False,
            notes=[
                "No real credentials were used or read during this inspection.",
                "No login or auth execution was performed.",
                "Inspection is static text analysis of safe local files only.",
                "safe_for_auth_execution=False (always in Phase 4E).",
                "safe_for_client_visibility=False (always in Phase 4E).",
                "storageState approved_for_commit=False (always).",
            ],
        )
        return report

    def build_credential_policy(self, project_id: str) -> CredentialPolicy:
        """Build the default credential safety policy for a project."""
        return CredentialPolicy(
            project_id=project_id,
            notes=[
                "Real credentials are forbidden in Phase 4E.",
                "Personal and production accounts are forbidden.",
                "Auth execution requires a future explicit phase approval.",
                "storageState must never be committed to the repository.",
            ],
        )

    def build_storage_state_policy(self, project_id: str) -> StorageStatePolicy:
        """Build the storageState policy for a project."""
        return StorageStatePolicy(
            project_id=project_id,
            notes=[
                "storageState files must never be committed to the repository.",
                "storageState is internal-only — requires explicit future phase approval.",
                "Ensure .auth/ and storageState*.json are in .gitignore.",
                "If storageState is found committed: treat as a secret leak — rotate credentials.",
            ],
        )

    def build_auth_execution_approval(self, project_id: str) -> AuthExecutionApproval:
        """Build a blocked (draft) auth execution approval record."""
        return AuthExecutionApproval(
            project_id=project_id,
            approved=False,
            approval_source=None,
            approval_scope="none — auth execution not approved in Phase 4E",
            provider="not_determined",
            target_environment="not_determined",
            dedicated_test_account_confirmed=False,
            storage_state_allowed=False,
            evidence_internal_only=True,
            blockers=[
                "Auth execution requires explicit future phase approval.",
                "Dedicated test account must be confirmed before approval.",
                "Real credentials are forbidden in Phase 4E.",
                "Personal and production accounts are forbidden.",
            ],
            notes=[
                "This is a draft approval record — not an active approval.",
                "No login or auth execution was performed.",
                "Future phases may enable auth execution with dedicated test accounts.",
            ],
        )

    def classify_sandbox_profiles(
        self, labels: List[str]
    ) -> List[SandboxProfileClassification]:
        """Classify a list of sandbox/profile labels."""
        results: List[SandboxProfileClassification] = []
        for label in labels:
            result = self.classify_single_sandbox(label)
            results.append(result)
        return results

    def classify_single_sandbox(self, label: str) -> SandboxProfileClassification:
        """Classify a single sandbox profile label string."""
        label_lower = label.lower().strip()
        for rule in _SANDBOX_RULES:
            for kw in rule["keywords"]:
                if kw in label_lower:
                    return SandboxProfileClassification(
                        id=f"sandbox_{label_lower[:30].replace(' ', '_')}",
                        provider=rule["provider"],
                        profile_type=rule["profile_type"],
                        classification=rule["classification"],
                        official_sandbox=rule["official_sandbox"],
                        production_retail_account=rule["production_retail_account"],
                        payment_sandbox=rule["payment_sandbox"],
                        requires_merchant_setup=rule["requires_merchant_setup"],
                        requires_dedicated_test_account=rule["requires_dedicated_test_account"],
                        allowed_in_future_phase=rule["allowed_in_future_phase"],
                        blocked_in_current_phase=True,
                        notes=list(rule["notes"]) + [f"Input label: '{label}'"],
                    )
        return SandboxProfileClassification(
            id=f"sandbox_{label_lower[:30].replace(' ', '_')}",
            provider="unknown",
            profile_type="unknown",
            classification="unknown",
            blocked_in_current_phase=True,
            notes=[f"Could not classify label: '{label}'. Blocked by default."],
        )

    def classify_amazon_reference(self, description: str) -> SandboxProfileClassification:
        """Classify an Amazon reference — distinguishes retail from Pay Sandbox."""
        desc_lower = description.lower()
        if "pay sandbox" in desc_lower or "pay test" in desc_lower:
            return self.classify_single_sandbox("amazon pay sandbox")
        return self.classify_single_sandbox("amazon.com")

    def classify_alza_reference(self, description: str) -> SandboxProfileClassification:
        """Classify an Alza reference — distinguishes production from staging."""
        desc_lower = description.lower()
        if "staging" in desc_lower or "test account" in desc_lower or "sandbox" in desc_lower:
            return self.classify_single_sandbox("alza staging")
        return self.classify_single_sandbox("alza production")

    def scan_text_for_secret_patterns(
        self,
        text: str,
        context: str = "unknown",
        allow_fake_fixture: bool = False,
    ) -> List[CredentialReference]:
        """Scan text for secret-like patterns. Returns list of flagged references."""
        found: List[CredentialReference] = []
        lines = text.split("\n")
        for i, line in enumerate(lines, 1):
            line_stripped = line.strip()
            # Skip comment lines
            if line_stripped.startswith("#") or line_stripped.startswith("//"):
                continue
            # Check allowed placeholders
            if allow_fake_fixture:
                if any(ph.lower() in line_stripped.lower() for ph in _ALLOWED_PLACEHOLDERS):
                    continue
            for pattern, label in _SECRET_PATTERNS:
                if re.search(pattern, line_stripped, re.IGNORECASE):
                    # Skip if it's a known placeholder
                    if any(ph.lower() in line_stripped.lower() for ph in _ALLOWED_PLACEHOLDERS):
                        continue
                    found.append(CredentialReference(
                        id=f"cred_{context}_{i:04d}",
                        label=label,
                        credential_type="unknown",
                        source_type="unknown",
                        source_location=f"{context}:line {i}",
                        required=False,
                        provided=True,
                        approved_for_use=False,
                        safe_to_store=False,
                        safe_to_log=False,
                        redaction_required=True,
                        notes=[
                            f"Pattern matched: {label}",
                            f"Context: {context}, line {i}",
                            "This value requires redaction before any client-visible use.",
                        ],
                    ))
        return found

    # ------------------------------------------------------------------
    # Artifact rendering
    # ------------------------------------------------------------------

    def render_credential_safety_artifacts(
        self,
        policy: CredentialPolicy,
        report: CredentialSafetyReport,
        storage_policy: StorageStatePolicy,
        auth_approval: AuthExecutionApproval,
        project_id: str,
    ) -> Dict[str, Path]:
        """Write credential safety artifacts to outputs/<project_id>/08_credentials/."""
        out_dir = self._outputs_root / project_id / "08_credentials"
        out_dir.mkdir(parents=True, exist_ok=True)
        paths: Dict[str, Path] = {}

        import json as _json

        p = out_dir / "CREDENTIAL_POLICY.json"
        p.write_text(_json.dumps(policy.to_dict(), indent=2), encoding="utf-8")
        paths["policy_json"] = p

        p = out_dir / "CREDENTIAL_POLICY.md"
        p.write_text(self._render_policy_md(policy), encoding="utf-8")
        paths["policy_md"] = p

        p = out_dir / "CREDENTIAL_SAFETY_REPORT.json"
        p.write_text(_json.dumps(report.to_dict(), indent=2), encoding="utf-8")
        paths["report_json"] = p

        p = out_dir / "CREDENTIAL_SAFETY_REPORT.md"
        p.write_text(self._render_report_md(report), encoding="utf-8")
        paths["report_md"] = p

        p = out_dir / "STORAGE_STATE_POLICY.json"
        p.write_text(_json.dumps(storage_policy.to_dict(), indent=2), encoding="utf-8")
        paths["storage_json"] = p

        p = out_dir / "STORAGE_STATE_POLICY.md"
        p.write_text(self._render_storage_md(storage_policy), encoding="utf-8")
        paths["storage_md"] = p

        p = out_dir / "AUTH_EXECUTION_APPROVAL_DRAFT.json"
        p.write_text(_json.dumps(auth_approval.to_dict(), indent=2), encoding="utf-8")
        paths["auth_approval_json"] = p

        p = out_dir / "AUTH_EXECUTION_APPROVAL_DRAFT.md"
        p.write_text(self._render_auth_approval_md(auth_approval), encoding="utf-8")
        paths["auth_approval_md"] = p

        # Sandbox classification
        sandbox_data = {
            "project_id": project_id,
            "sandbox_profiles": [s.to_dict() for s in report.sandbox_profiles],
        }
        p = out_dir / "SANDBOX_PROFILE_CLASSIFICATION.json"
        p.write_text(_json.dumps(sandbox_data, indent=2), encoding="utf-8")
        paths["sandbox_json"] = p

        p = out_dir / "SANDBOX_PROFILE_CLASSIFICATION.md"
        p.write_text(self._render_sandbox_md(report.sandbox_profiles, project_id), encoding="utf-8")
        paths["sandbox_md"] = p

        p = out_dir / "CREDENTIAL_REDACTION_CHECKLIST.md"
        p.write_text(self._render_redaction_checklist(report, project_id), encoding="utf-8")
        paths["redaction_checklist"] = p

        return paths

    # ------------------------------------------------------------------
    # Internal scanning helpers
    # ------------------------------------------------------------------

    def _is_forbidden_path(self, path: Path) -> bool:
        """Return True if this path must never be read."""
        path_str = str(path).replace("\\", "/")
        name = path.name
        for pattern in _FORBIDDEN_FILE_PATTERNS:
            if pattern in path_str or pattern in name:
                return True
        return False

    def _scan_directory(
        self,
        directory: Path,
        context: str,
        allow_fake_fixture: bool,
    ) -> Dict[str, Any]:
        """Scan a safe directory for secret patterns. Skips forbidden paths."""
        detected: List[CredentialReference] = []
        blockers: List[str] = []
        warnings: List[str] = []

        safe_extensions = {".md", ".json", ".txt", ".yaml", ".yml", ".example", ".ts", ".js", ".py"}
        for fpath in directory.rglob("*"):
            if not fpath.is_file():
                continue
            if self._is_forbidden_path(fpath):
                continue
            if fpath.suffix.lower() not in safe_extensions:
                continue
            try:
                text = fpath.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            file_context = f"{context}/{fpath.name}"
            found = self.scan_text_for_secret_patterns(
                text, context=file_context, allow_fake_fixture=allow_fake_fixture
            )
            for ref in found:
                detected.append(ref)
                if allow_fake_fixture:
                    warnings.append(
                        f"Possible credential pattern in fixture {fpath.name} — verify it is a safe placeholder."
                    )
                else:
                    blockers.append(
                        f"Credential-like pattern detected in {fpath.name} — redaction required."
                    )

        return {"detected": detected, "blockers": blockers, "warnings": warnings}

    def _check_gitignore(self) -> List[str]:
        """Check .gitignore for required credential-safety patterns."""
        warnings: List[str] = []
        required_patterns = [".env", ".auth", "storageState"]
        gitignore = Path(".gitignore")
        if not gitignore.exists():
            warnings.append(".gitignore not found — ensure .env, .auth, storageState are excluded.")
            return warnings
        content = gitignore.read_text(encoding="utf-8")
        for pattern in required_patterns:
            if pattern not in content:
                warnings.append(
                    f"'{pattern}' not found in .gitignore — add it to prevent accidental secret commits."
                )
        return warnings

    # ------------------------------------------------------------------
    # Markdown rendering
    # ------------------------------------------------------------------

    def _render_policy_md(self, policy: CredentialPolicy) -> str:
        lines = [
            "# Credential Safety Policy",
            "",
            "> **Phase 4E — Credential and Test-Account Safety Layer**  ",
            "> No real credentials were used. No login was performed.",
            "",
            f"**Project:** `{policy.project_id}`",
            "",
            "## Safety Defaults",
            "",
            "| Flag | Value |",
            "|------|-------|",
            f"| allow_real_credentials | `{policy.allow_real_credentials}` |",
            f"| allow_personal_accounts | `{policy.allow_personal_accounts}` |",
            f"| allow_production_accounts | `{policy.allow_production_accounts}` |",
            f"| allow_repo_storage | `{policy.allow_repo_storage}` |",
            f"| allow_logging | `{policy.allow_logging}` |",
            f"| allow_client_visible_credentials | `{policy.allow_client_visible_credentials}` |",
            f"| allow_storage_state | `{policy.allow_storage_state}` |",
            f"| require_dedicated_test_account | `{policy.require_dedicated_test_account}` |",
            f"| require_explicit_auth_approval | `{policy.require_explicit_auth_approval}` |",
            f"| require_redaction | `{policy.require_redaction}` |",
            "",
            "## Notes",
            "",
        ]
        for n in policy.notes:
            lines.append(f"- {n}")
        return "\n".join(lines) + "\n"

    def _render_report_md(self, report: CredentialSafetyReport) -> str:
        lines = [
            "# Credential Safety Report",
            "",
            "> **No real credentials were used.**  ",
            "> **No login was performed.**  ",
            "> **No real .env or .auth files were read.**",
            "",
            f"**Project:** `{report.project_id}`",
            f"**Status:** `{report.status}`",
            "",
            "## Safety Flags",
            "",
            "| Flag | Value |",
            "|------|-------|",
            f"| safe_for_auth_execution | `{report.safe_for_auth_execution}` |",
            f"| safe_for_storage_state | `{report.safe_for_storage_state}` |",
            f"| safe_for_client_visibility | `{report.safe_for_client_visibility}` |",
        ]
        if report.blockers:
            lines.extend(["", "## Blockers", ""])
            for b in report.blockers:
                lines.append(f"- {b}")
        if report.warnings:
            lines.extend(["", "## Warnings", ""])
            for w in report.warnings:
                lines.append(f"- {w}")
        lines.extend(["", "## Credentials Detected", ""])
        if report.credentials_detected:
            for c in report.credentials_detected:
                lines.append(f"- [{c.label}] at `{c.source_location}` — redaction_required={c.redaction_required}")
        else:
            lines.append("- None detected.")
        lines.extend(["", "## Notes", ""])
        for n in report.notes:
            lines.append(f"- {n}")
        return "\n".join(lines) + "\n"

    def _render_storage_md(self, policy: StorageStatePolicy) -> str:
        lines = [
            "# storageState Policy",
            "",
            "> **storageState files must never be committed.**  ",
            "> **Internal-only. Requires explicit future phase approval.**",
            "",
            f"**Project:** `{policy.project_id}`",
            f"**storage_state_allowed:** `{policy.storage_state_allowed}`",
            f"**approved_for_commit:** `{policy.approved_for_commit}`",
            f"**internal_only:** `{policy.internal_only}`",
            f"**client_visible:** `{policy.client_visible}`",
            f"**gitignored_required:** `{policy.gitignored_required}`",
            "",
            "## Notes",
            "",
        ]
        for n in policy.notes:
            lines.append(f"- {n}")
        return "\n".join(lines) + "\n"

    def _render_auth_approval_md(self, approval: AuthExecutionApproval) -> str:
        lines = [
            "# Auth Execution Approval — DRAFT",
            "",
            "> **This is a DRAFT record. Auth execution is NOT approved in Phase 4E.**  ",
            "> **No login was performed. No real credentials were used.**",
            "",
            f"**Project:** `{approval.project_id}`",
            f"**approved:** `{approval.approved}`",
            f"**approval_scope:** {approval.approval_scope}",
            "",
            "## Blockers",
            "",
        ]
        for b in approval.blockers:
            lines.append(f"- {b}")
        lines.extend(["", "## Notes", ""])
        for n in approval.notes:
            lines.append(f"- {n}")
        return "\n".join(lines) + "\n"

    def _render_sandbox_md(
        self,
        profiles: List[SandboxProfileClassification],
        project_id: str,
    ) -> str:
        lines = [
            "# Sandbox Profile Classification",
            "",
            f"**Project:** `{project_id}`",
            "",
            "## Key Distinctions",
            "",
            "- **Amazon.com retail account** → `blocked_production_retail` — always blocked.",
            "- **Amazon Pay Sandbox** → `future_sandbox_integration` — blocked in current phase; requires merchant setup.",
            "- **Alza.sk production account** → `blocked_production_ecommerce` — blocked unless client staging/test access.",
            "- **SauceDemo** → `public_demo` — allowed in Phase 4D with --approve-demo-execution.",
            "- **Dedicated staging/test account** → `future_sandbox_integration` — blocked in Phase 4E.",
            "",
            "## Classified Profiles",
            "",
        ]
        if profiles:
            for p in profiles:
                lines.extend([
                    f"### {p.provider} — {p.profile_type}",
                    f"- classification: `{p.classification}`",
                    f"- blocked_in_current_phase: `{p.blocked_in_current_phase}`",
                    f"- allowed_in_future_phase: `{p.allowed_in_future_phase}`",
                    "",
                ])
        else:
            lines.append("No profiles classified in this run.")
        return "\n".join(lines) + "\n"

    def _render_redaction_checklist(
        self,
        report: CredentialSafetyReport,
        project_id: str,
    ) -> str:
        lines = [
            "# Credential Redaction Checklist",
            "",
            f"**Project:** `{project_id}`",
            "",
            "> Review before any client-visible artifact is shared.",
            "",
            "## Required Actions",
            "",
            "- [ ] Verify no real passwords appear in any artifact.",
            "- [ ] Verify no API keys or tokens appear in any artifact.",
            "- [ ] Verify no OAuth secrets or client secrets appear in any artifact.",
            "- [ ] Verify no session cookies or access tokens appear in any artifact.",
            "- [ ] Verify storageState files are not committed to the repository.",
            "- [ ] Verify .env files are in .gitignore and not committed.",
            "- [ ] Verify .auth/ directory is in .gitignore and not committed.",
            "- [ ] Verify no personal account credentials appear anywhere.",
            "- [ ] Verify no production account credentials appear anywhere.",
            "",
            "## Credential Patterns Detected",
            "",
        ]
        if report.credentials_detected:
            for c in report.credentials_detected:
                lines.append(f"- [ ] `{c.label}` at `{c.source_location}` — REDACT before client view")
        else:
            lines.append("- No credential patterns detected in scanned files.")
        lines.extend([
            "",
            "## Safety Boundary",
            "",
            "- No real credentials were used in this inspection.",
            "- No login was performed.",
            "- No .env or .auth files were read.",
            "- All evidence is internal-only.",
            "- safe_for_client_visibility=False until redaction checklist is completed by a human.",
        ])
        return "\n".join(lines) + "\n"
