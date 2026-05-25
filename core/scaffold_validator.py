"""ScaffoldValidator — static file inspection of generated Playwright scaffolds.

Phase 3B: Safe Local Scaffold Validation Planning and Static Checks.

SAFETY INVARIANTS (never violated):
- No npm / npx execution
- No TypeScript compilation
- No Playwright execution
- No browser launch
- No URL fetching
- No credential use
- No external calls
- No subprocess of any kind
- execution_performed, npm_performed, npx_performed, browser_performed,
  external_calls_performed remain False always
- safe_to_execute_tests remains False always
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import List, Optional, Tuple

from core.schemas.scaffold_validation import (
    ScaffoldValidationCheck,
    ScaffoldValidationReport,
    ToolchainValidationPlan,
)

_OUTPUTS_ROOT = Path("outputs")

REQUIRED_FILES = [
    "package.json",
    "playwright.config.ts",
    ".env.example",
    "tsconfig.json",
    "README.md",
    "tests/smoke/smoke.spec.ts",
    "pages/BasePage.ts",
    "fixtures/test-fixtures.ts",
    "utils/env.ts",
]

EXECUTABLE_EXTENSIONS = {".ts", ".js", ".json"}

EXTERNAL_URL_RE = re.compile(
    r"https?://(?!localhost\b|127\.0\.0\.1\b|example\.com\b|process\.env)[a-zA-Z0-9\-.]+"
)

SECRET_PATTERNS: List[Tuple[str, str]] = [
    (r"\bsk-[A-Za-z0-9]{20,}\b", "OpenAI/Stripe-style API key"),
    (r"\bsk-ant-[A-Za-z0-9\-]{20,}\b", "Anthropic API key"),
    (r"\beyJ[A-Za-z0-9_\-]{30,}", "JWT token"),
    (r"\bBearer\s+[A-Za-z0-9\-._~+/]{20,}\b", "Bearer token"),
    (r'(?i)password\s*=\s*["\']?(?!process\.env)[A-Za-z0-9!@#$%^&*]{8,}', "Hardcoded password"),
]

LITERAL_SECRET_TRIGGERS = ["FakeSecret123", "REPLACE_ME_SECRET"]

_COMPILED_SECRET_PATTERNS = [(re.compile(p), label) for p, label in SECRET_PATTERNS]


class ScaffoldValidator:
    """Statically inspects a generated Playwright scaffold.

    Never executes npm, npx, TypeScript, Playwright, browsers, or any subprocess.
    All methods return plain data — no side effects beyond writing artifact files.
    """

    def __init__(self, outputs_root: Optional[Path] = None) -> None:
        self._outputs_root = outputs_root or _OUTPUTS_ROOT

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def validate_scaffold(
        self,
        scaffold_root: Path,
        project_id: Optional[str] = None,
    ) -> ScaffoldValidationReport:
        """Run all static checks on scaffold_root. Returns a ScaffoldValidationReport.

        execution_performed, npm_performed, npx_performed, browser_performed,
        external_calls_performed, and safe_to_execute_tests are ALWAYS False.
        """
        pid = project_id or scaffold_root.name
        report = ScaffoldValidationReport(
            project_id=pid,
            scaffold_root=str(scaffold_root),
            execution_performed=False,
            npm_performed=False,
            npx_performed=False,
            browser_performed=False,
            external_calls_performed=False,
            safe_to_execute_tests=False,
        )

        check_id = [0]

        def next_id() -> str:
            check_id[0] += 1
            return f"CHK-{check_id[0]:03d}"

        report.checks.extend(self._check_structure(scaffold_root, next_id))
        report.checks.extend(self._check_metadata(scaffold_root, next_id))
        report.checks.extend(self._check_package_json(scaffold_root, next_id))
        report.checks.extend(self._check_playwright_config(scaffold_root, next_id))
        report.checks.extend(self._check_env_example(scaffold_root, next_id))
        report.checks.extend(self._check_test_placeholders(scaffold_root, next_id))
        report.checks.extend(self._check_docs(scaffold_root, next_id))
        report.checks.extend(self._check_secrets(scaffold_root, next_id))
        report.checks.extend(self._check_urls(scaffold_root, next_id))
        report.checks.extend(self._check_repository_boundary(scaffold_root, next_id))

        blockers = [c for c in report.checks if c.status == "fail" and c.blocks_next_phase]
        warnings = [c for c in report.checks if c.status in ("fail", "warning") and not c.blocks_next_phase]

        report.blockers = [f"[{c.id}] {c.name}: {c.message}" for c in blockers]
        report.warnings = [f"[{c.id}] {c.name}: {c.message}" for c in warnings]

        if blockers:
            report.validation_status = "fail"
            report.safe_to_proceed_to_toolchain_validation = False
        elif warnings:
            report.validation_status = "warning"
            report.safe_to_proceed_to_toolchain_validation = True
        else:
            report.validation_status = "pass"
            report.safe_to_proceed_to_toolchain_validation = True

        report.notes.append(
            f"Static validation complete. {len(report.checks)} checks run. "
            f"{len(blockers)} blocker(s), {len(warnings)} warning(s). "
            "No code executed."
        )

        return report

    def build_toolchain_validation_plan(
        self,
        scaffold_root: Path,
        project_id: Optional[str] = None,
    ) -> ToolchainValidationPlan:
        """Build a ToolchainValidationPlan describing what commands WOULD be run with approval.

        Does not execute anything. approval_required is always True.
        """
        pid = project_id or scaffold_root.name
        plan = ToolchainValidationPlan(
            project_id=pid,
            scaffold_root=str(scaffold_root),
            proposed_commands=[
                "npm install  # requires network access and explicit approval",
                "npx playwright install chromium  # downloads browser binary, requires approval",
                "npx tsc --noEmit  # type-check only, no test execution",
                "npx playwright test --list  # list tests only, no execution",
            ],
            approval_required=True,
            network_access_required=True,
            browser_execution_required=False,
            safe_without_approval=False,
        )
        plan.notes.append(
            "All commands above require explicit human approval before execution. "
            "Static validation (Phase 3B) does not run any of these."
        )
        return plan

    def render_validation_artifacts(
        self,
        report: ScaffoldValidationReport,
        plan: ToolchainValidationPlan,
        out_dir: Path,
    ) -> dict:
        """Write validation artifacts to out_dir. Returns dict of artifact paths."""
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = {}

        paths["validation_report_json"] = self._write_json(
            out_dir / "STATIC_VALIDATION_REPORT.json",
            report.to_dict(),
        )
        paths["validation_report_md"] = self._write_text(
            out_dir / "STATIC_VALIDATION_REPORT.md",
            self._render_validation_md(report),
        )
        paths["validation_plan_md"] = self._write_text(
            out_dir / "VALIDATION_PLAN.md",
            self._render_validation_plan(report, plan),
        )
        paths["local_checklist_md"] = self._write_text(
            out_dir / "LOCAL_VALIDATION_CHECKLIST.md",
            self._render_local_checklist(report),
        )
        paths["toolchain_plan_md"] = self._write_text(
            out_dir / "TOOLCHAIN_VALIDATION_PLAN.md",
            self._render_toolchain_plan(plan),
        )

        return paths

    # ------------------------------------------------------------------
    # Check methods
    # ------------------------------------------------------------------

    def _check_structure(self, root: Path, next_id) -> List[ScaffoldValidationCheck]:
        checks = []
        for rel in REQUIRED_FILES:
            cid = next_id()
            target = root / rel
            if target.exists():
                checks.append(ScaffoldValidationCheck(
                    id=cid,
                    name=f"Required file present: {rel}",
                    category="structure",
                    status="pass",
                    severity="info",
                    file_path=rel,
                    message=f"File exists: {rel}",
                ))
            else:
                checks.append(ScaffoldValidationCheck(
                    id=cid,
                    name=f"Required file missing: {rel}",
                    category="structure",
                    status="fail",
                    severity="high",
                    file_path=rel,
                    message=f"Required file not found: {rel}",
                    recommendation=f"Regenerate scaffold to ensure {rel} is generated.",
                    blocks_next_phase=True,
                ))
        return checks

    def _check_metadata(self, root: Path, next_id) -> List[ScaffoldValidationCheck]:
        checks = []
        meta_path = root / "FRAMEWORK_SCAFFOLD.json"
        cid = next_id()
        if not meta_path.exists():
            checks.append(ScaffoldValidationCheck(
                id=cid,
                name="Scaffold metadata present",
                category="metadata",
                status="fail",
                severity="high",
                file_path="FRAMEWORK_SCAFFOLD.json",
                message="FRAMEWORK_SCAFFOLD.json not found.",
                recommendation="Run render_scaffold_artifacts to generate metadata.",
                blocks_next_phase=True,
            ))
            return checks

        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as exc:
            checks.append(ScaffoldValidationCheck(
                id=cid,
                name="Scaffold metadata readable",
                category="metadata",
                status="fail",
                severity="high",
                file_path="FRAMEWORK_SCAFFOLD.json",
                message=f"Cannot parse FRAMEWORK_SCAFFOLD.json: {exc}",
                blocks_next_phase=True,
            ))
            return checks

        checks.append(ScaffoldValidationCheck(
            id=cid,
            name="Scaffold metadata present",
            category="metadata",
            status="pass",
            severity="info",
            file_path="FRAMEWORK_SCAFFOLD.json",
            message="FRAMEWORK_SCAFFOLD.json found and readable.",
        ))

        # execution_allowed must be False
        cid2 = next_id()
        if data.get("execution_allowed", True) is not False:
            checks.append(ScaffoldValidationCheck(
                id=cid2,
                name="execution_allowed is False",
                category="metadata",
                status="fail",
                severity="critical",
                file_path="FRAMEWORK_SCAFFOLD.json",
                message="execution_allowed is not False in scaffold metadata.",
                recommendation="Regenerate scaffold — execution_allowed must remain False.",
                blocks_next_phase=True,
            ))
        else:
            checks.append(ScaffoldValidationCheck(
                id=cid2,
                name="execution_allowed is False",
                category="metadata",
                status="pass",
                severity="info",
                file_path="FRAMEWORK_SCAFFOLD.json",
                message="execution_allowed=False confirmed.",
            ))

        # client_visible must be False
        cid3 = next_id()
        if data.get("client_visible", True) is not False:
            checks.append(ScaffoldValidationCheck(
                id=cid3,
                name="client_visible is False",
                category="metadata",
                status="fail",
                severity="high",
                file_path="FRAMEWORK_SCAFFOLD.json",
                message="client_visible is not False in scaffold metadata.",
                recommendation="Set client_visible=False before any delivery.",
                blocks_next_phase=True,
            ))
        else:
            checks.append(ScaffoldValidationCheck(
                id=cid3,
                name="client_visible is False",
                category="metadata",
                status="pass",
                severity="info",
                file_path="FRAMEWORK_SCAFFOLD.json",
                message="client_visible=False confirmed.",
            ))

        # requires_review must be True
        cid4 = next_id()
        if data.get("requires_review", False) is not True:
            checks.append(ScaffoldValidationCheck(
                id=cid4,
                name="requires_review is True",
                category="metadata",
                status="fail",
                severity="high",
                file_path="FRAMEWORK_SCAFFOLD.json",
                message="requires_review is not True in scaffold metadata.",
                recommendation="Set requires_review=True — scaffold has not been reviewed.",
                blocks_next_phase=True,
            ))
        else:
            checks.append(ScaffoldValidationCheck(
                id=cid4,
                name="requires_review is True",
                category="metadata",
                status="pass",
                severity="info",
                file_path="FRAMEWORK_SCAFFOLD.json",
                message="requires_review=True confirmed.",
            ))

        return checks

    def _check_package_json(self, root: Path, next_id) -> List[ScaffoldValidationCheck]:
        checks = []
        pkg_path = root / "package.json"
        cid = next_id()
        if not pkg_path.exists():
            checks.append(ScaffoldValidationCheck(
                id=cid,
                name="package.json parseable",
                category="package_json",
                status="skipped",
                severity="info",
                file_path="package.json",
                message="package.json not found — skipping package.json checks.",
            ))
            return checks

        try:
            pkg = json.loads(pkg_path.read_text(encoding="utf-8"))
        except Exception as exc:
            checks.append(ScaffoldValidationCheck(
                id=cid,
                name="package.json parseable",
                category="package_json",
                status="fail",
                severity="high",
                file_path="package.json",
                message=f"Cannot parse package.json: {exc}",
                blocks_next_phase=True,
            ))
            return checks

        checks.append(ScaffoldValidationCheck(
            id=cid,
            name="package.json parseable",
            category="package_json",
            status="pass",
            severity="info",
            file_path="package.json",
            message="package.json is valid JSON.",
        ))

        # Dangerous lifecycle hooks
        scripts = pkg.get("scripts", {})
        dangerous_hooks = [h for h in ("preinstall", "postinstall", "install") if h in scripts]
        cid2 = next_id()
        if dangerous_hooks:
            checks.append(ScaffoldValidationCheck(
                id=cid2,
                name="No dangerous npm lifecycle hooks",
                category="package_json",
                status="fail",
                severity="critical",
                file_path="package.json",
                message=f"Dangerous lifecycle script(s) found: {dangerous_hooks}. These execute on npm install.",
                recommendation="Remove preinstall/postinstall/install hooks before approving npm install.",
                blocks_next_phase=True,
            ))
        else:
            checks.append(ScaffoldValidationCheck(
                id=cid2,
                name="No dangerous npm lifecycle hooks",
                category="package_json",
                status="pass",
                severity="info",
                file_path="package.json",
                message="No preinstall/postinstall/install hooks found.",
            ))

        # playwright present in deps
        all_deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
        cid3 = next_id()
        if "@playwright/test" in all_deps:
            checks.append(ScaffoldValidationCheck(
                id=cid3,
                name="@playwright/test declared",
                category="package_json",
                status="pass",
                severity="info",
                file_path="package.json",
                message=f"@playwright/test={all_deps['@playwright/test']} declared.",
            ))
        else:
            checks.append(ScaffoldValidationCheck(
                id=cid3,
                name="@playwright/test declared",
                category="package_json",
                status="warning",
                severity="medium",
                file_path="package.json",
                message="@playwright/test not found in dependencies.",
                recommendation="Add @playwright/test to devDependencies.",
            ))

        return checks

    def _check_playwright_config(self, root: Path, next_id) -> List[ScaffoldValidationCheck]:
        checks = []
        cfg_path = root / "playwright.config.ts"
        cid = next_id()
        if not cfg_path.exists():
            checks.append(ScaffoldValidationCheck(
                id=cid,
                name="playwright.config.ts present",
                category="config",
                status="skipped",
                severity="info",
                file_path="playwright.config.ts",
                message="playwright.config.ts not found — skipping config checks.",
            ))
            return checks

        content = cfg_path.read_text(encoding="utf-8")
        checks.append(ScaffoldValidationCheck(
            id=cid,
            name="playwright.config.ts present",
            category="config",
            status="pass",
            severity="info",
            file_path="playwright.config.ts",
            message="playwright.config.ts found.",
        ))

        # BASE_URL uses process.env
        cid2 = next_id()
        if "process.env.BASE_URL" in content or "process.env" in content:
            checks.append(ScaffoldValidationCheck(
                id=cid2,
                name="baseURL uses process.env",
                category="config",
                status="pass",
                severity="info",
                file_path="playwright.config.ts",
                message="process.env reference found in config — no hardcoded URL.",
            ))
        else:
            checks.append(ScaffoldValidationCheck(
                id=cid2,
                name="baseURL uses process.env",
                category="config",
                status="warning",
                severity="medium",
                file_path="playwright.config.ts",
                message="No process.env reference in playwright.config.ts.",
                recommendation="Ensure baseURL is set via process.env.BASE_URL.",
            ))

        return checks

    def _check_env_example(self, root: Path, next_id) -> List[ScaffoldValidationCheck]:
        checks = []
        env_path = root / ".env.example"
        cid = next_id()
        if not env_path.exists():
            checks.append(ScaffoldValidationCheck(
                id=cid,
                name=".env.example present",
                category="env",
                status="skipped",
                severity="info",
                file_path=".env.example",
                message=".env.example not found — skipping env checks.",
            ))
            return checks

        content = env_path.read_text(encoding="utf-8")
        checks.append(ScaffoldValidationCheck(
            id=cid,
            name=".env.example present",
            category="env",
            status="pass",
            severity="info",
            file_path=".env.example",
            message=".env.example found.",
        ))

        # Must not contain real credentials (only placeholders)
        cid2 = next_id()
        has_real_secret = any(trigger in content for trigger in LITERAL_SECRET_TRIGGERS)
        for pat, _ in _COMPILED_SECRET_PATTERNS:
            if has_real_secret:
                break
            # Allow process.env.* lines and PLACEHOLDER values — only flag concrete secrets
            for line in content.splitlines():
                if "process.env" in line or "PLACEHOLDER" in line.upper():
                    continue
                if pat.search(line):
                    has_real_secret = True
                    break

        if has_real_secret:
            checks.append(ScaffoldValidationCheck(
                id=cid2,
                name=".env.example contains no real secrets",
                category="env",
                status="fail",
                severity="critical",
                file_path=".env.example",
                message="Possible real secret detected in .env.example.",
                recommendation="Replace all real values with placeholder comments.",
                blocks_next_phase=True,
            ))
        else:
            checks.append(ScaffoldValidationCheck(
                id=cid2,
                name=".env.example contains no real secrets",
                category="env",
                status="pass",
                severity="info",
                file_path=".env.example",
                message=".env.example uses placeholder values only.",
            ))

        # .env must not exist (only .env.example)
        cid3 = next_id()
        if (root / ".env").exists():
            checks.append(ScaffoldValidationCheck(
                id=cid3,
                name="No .env file in scaffold",
                category="env",
                status="fail",
                severity="critical",
                file_path=".env",
                message=".env file found inside scaffold root — must not be committed.",
                recommendation="Delete .env file and add it to .gitignore.",
                blocks_next_phase=True,
            ))
        else:
            checks.append(ScaffoldValidationCheck(
                id=cid3,
                name="No .env file in scaffold",
                category="env",
                status="pass",
                severity="info",
                file_path=".env",
                message=".env file not present (only .env.example).",
            ))

        return checks

    def _check_test_placeholders(self, root: Path, next_id) -> List[ScaffoldValidationCheck]:
        checks = []
        tests_dir = root / "tests"
        cid = next_id()
        if not tests_dir.exists():
            checks.append(ScaffoldValidationCheck(
                id=cid,
                name="tests/ directory present",
                category="tests",
                status="fail",
                severity="high",
                file_path="tests/",
                message="tests/ directory not found.",
                recommendation="Regenerate scaffold.",
                blocks_next_phase=True,
            ))
            return checks

        checks.append(ScaffoldValidationCheck(
            id=cid,
            name="tests/ directory present",
            category="tests",
            status="pass",
            severity="info",
            file_path="tests/",
            message="tests/ directory found.",
        ))

        # Auth spec skips if TEST_USERNAME not set
        auth_spec = tests_dir / "auth" / "auth-placeholder.spec.ts"
        if auth_spec.exists():
            cid2 = next_id()
            content = auth_spec.read_text(encoding="utf-8")
            if "TEST_USERNAME" in content or "test.skip" in content or "test.describe.configure" in content:
                checks.append(ScaffoldValidationCheck(
                    id=cid2,
                    name="auth.spec.ts has skip guard",
                    category="tests",
                    status="pass",
                    severity="info",
                    file_path="tests/auth.spec.ts",
                    message="auth.spec.ts has skip guard for TEST_USERNAME.",
                ))
            else:
                checks.append(ScaffoldValidationCheck(
                    id=cid2,
                    name="auth.spec.ts has skip guard",
                    category="tests",
                    status="warning",
                    severity="medium",
                    file_path="tests/auth.spec.ts",
                    message="auth.spec.ts may not have TEST_USERNAME skip guard.",
                    recommendation="Ensure auth spec skips when TEST_USERNAME is not set.",
                ))

        # API spec skips if API_BASE_URL not set
        api_spec = tests_dir / "api" / "api-placeholder.spec.ts"
        if api_spec.exists():
            cid3 = next_id()
            content = api_spec.read_text(encoding="utf-8")
            if "API_BASE_URL" in content or "test.skip" in content:
                checks.append(ScaffoldValidationCheck(
                    id=cid3,
                    name="api.spec.ts has skip guard",
                    category="tests",
                    status="pass",
                    severity="info",
                    file_path="tests/api.spec.ts",
                    message="api.spec.ts has skip guard for API_BASE_URL.",
                ))
            else:
                checks.append(ScaffoldValidationCheck(
                    id=cid3,
                    name="api.spec.ts has skip guard",
                    category="tests",
                    status="warning",
                    severity="medium",
                    file_path="tests/api.spec.ts",
                    message="api.spec.ts may not have API_BASE_URL skip guard.",
                    recommendation="Ensure api spec skips when API_BASE_URL is not set.",
                ))

        # Checkout spec — must use test.skip(true)
        checkout_spec = tests_dir / "ecommerce" / "checkout-placeholder.spec.ts"
        if checkout_spec.exists():
            cid4 = next_id()
            content = checkout_spec.read_text(encoding="utf-8")
            if "test.skip(true" in content:
                checks.append(ScaffoldValidationCheck(
                    id=cid4,
                    name="checkout.spec.ts unconditionally skipped",
                    category="tests",
                    status="pass",
                    severity="info",
                    file_path="tests/checkout.spec.ts",
                    message="checkout.spec.ts uses test.skip(true).",
                ))
            else:
                checks.append(ScaffoldValidationCheck(
                    id=cid4,
                    name="checkout.spec.ts unconditionally skipped",
                    category="tests",
                    status="warning",
                    severity="medium",
                    file_path="tests/checkout.spec.ts",
                    message="checkout.spec.ts does not use test.skip(true).",
                    recommendation="Add test.skip(true, 'Requires approval') at top of checkout spec.",
                ))

        return checks

    def _check_docs(self, root: Path, next_id) -> List[ScaffoldValidationCheck]:
        checks = []
        readme_path = root / "README.md"
        cid = next_id()
        if not readme_path.exists():
            checks.append(ScaffoldValidationCheck(
                id=cid,
                name="README.md present",
                category="docs",
                status="fail",
                severity="medium",
                file_path="README.md",
                message="README.md not found in scaffold root.",
                recommendation="Add README.md documenting setup, env vars, and test structure.",
            ))
        else:
            content = readme_path.read_text(encoding="utf-8")
            has_env_section = "BASE_URL" in content or ".env" in content or "Environment" in content
            if has_env_section:
                checks.append(ScaffoldValidationCheck(
                    id=cid,
                    name="README.md present with env guidance",
                    category="docs",
                    status="pass",
                    severity="info",
                    file_path="README.md",
                    message="README.md present and documents environment variables.",
                ))
            else:
                checks.append(ScaffoldValidationCheck(
                    id=cid,
                    name="README.md present with env guidance",
                    category="docs",
                    status="warning",
                    severity="low",
                    file_path="README.md",
                    message="README.md found but may not document environment variables.",
                    recommendation="Add a section documenting required env vars and .env.example usage.",
                ))
        return checks

    def _check_secrets(self, root: Path, next_id) -> List[ScaffoldValidationCheck]:
        checks = []
        found_secrets: List[Tuple[str, str, str]] = []

        for path in root.rglob("*"):
            if path.suffix not in EXECUTABLE_EXTENSIONS:
                continue
            if not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            rel = str(path.relative_to(root)).replace("\\", "/")

            for trigger in LITERAL_SECRET_TRIGGERS:
                if trigger in content:
                    found_secrets.append((rel, "Literal secret trigger", trigger))

            for pat, label in _COMPILED_SECRET_PATTERNS:
                match = pat.search(content)
                if match:
                    # Skip process.env lines
                    matched_text = match.group(0)
                    line = next(
                        (ln for ln in content.splitlines() if matched_text in ln), ""
                    )
                    if "process.env" not in line and "${" not in line:
                        found_secrets.append((rel, label, matched_text[:40]))

        cid = next_id()
        if found_secrets:
            details = "; ".join(f"{f} [{label}]" for f, label, _ in found_secrets[:5])
            checks.append(ScaffoldValidationCheck(
                id=cid,
                name="No secrets in scaffold files",
                category="secrets",
                status="fail",
                severity="critical",
                message=f"Possible secret(s) detected: {details}",
                recommendation="Remove all hardcoded secrets. Use process.env.* placeholders only.",
                blocks_next_phase=True,
            ))
        else:
            checks.append(ScaffoldValidationCheck(
                id=cid,
                name="No secrets in scaffold files",
                category="secrets",
                status="pass",
                severity="info",
                message="No secret patterns found in scaffold files.",
            ))
        return checks

    def _check_urls(self, root: Path, next_id) -> List[ScaffoldValidationCheck]:
        checks = []
        found_urls: List[Tuple[str, str]] = []

        for path in root.rglob("*"):
            if path.suffix not in EXECUTABLE_EXTENSIONS:
                continue
            if not path.is_file():
                continue
            try:
                content = path.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue

            rel = str(path.relative_to(root)).replace("\\", "/")
            for match in EXTERNAL_URL_RE.finditer(content):
                url = match.group(0)
                line = next(
                    (ln for ln in content.splitlines() if url in ln), ""
                )
                # Skip lines that look like comments or process.env fallbacks
                stripped = line.strip()
                if stripped.startswith("//") or stripped.startswith("*") or "process.env" in line:
                    continue
                found_urls.append((rel, url[:80]))

        cid = next_id()
        if found_urls:
            details = "; ".join(f"{f}: {u}" for f, u in found_urls[:5])
            checks.append(ScaffoldValidationCheck(
                id=cid,
                name="No hardcoded external URLs",
                category="urls",
                status="fail",
                severity="high",
                message=f"External URL(s) found in scaffold code: {details}",
                recommendation="Replace hardcoded URLs with process.env.BASE_URL or similar.",
                blocks_next_phase=True,
            ))
        else:
            checks.append(ScaffoldValidationCheck(
                id=cid,
                name="No hardcoded external URLs",
                category="urls",
                status="pass",
                severity="info",
                message="No hardcoded external URLs found in scaffold code.",
            ))
        return checks

    def _check_repository_boundary(self, root: Path, next_id) -> List[ScaffoldValidationCheck]:
        checks = []
        cid = next_id()
        root_resolved = root.resolve()
        outputs_resolved = self._outputs_root.resolve()

        try:
            root_resolved.relative_to(outputs_resolved)
            inside_outputs = True
        except ValueError:
            inside_outputs = False

        if inside_outputs:
            checks.append(ScaffoldValidationCheck(
                id=cid,
                name="Scaffold inside outputs/",
                category="repository_boundary",
                status="pass",
                severity="info",
                file_path=str(root),
                message="Scaffold root is inside outputs/ — correct boundary.",
            ))
        else:
            checks.append(ScaffoldValidationCheck(
                id=cid,
                name="Scaffold inside outputs/",
                category="repository_boundary",
                status="fail",
                severity="high",
                file_path=str(root),
                message=f"Scaffold root {root} is outside outputs/ directory.",
                recommendation="Move scaffold to outputs/<project_id>/03_framework/playwright/.",
                blocks_next_phase=True,
            ))

        # No .git directory inside scaffold
        cid2 = next_id()
        git_dir = root / ".git"
        if git_dir.exists():
            checks.append(ScaffoldValidationCheck(
                id=cid2,
                name="No .git inside scaffold",
                category="repository_boundary",
                status="fail",
                severity="critical",
                file_path=".git",
                message=".git directory found inside scaffold root.",
                recommendation="Remove .git from scaffold — scaffold must not be a separate git repo.",
                blocks_next_phase=True,
            ))
        else:
            checks.append(ScaffoldValidationCheck(
                id=cid2,
                name="No .git inside scaffold",
                category="repository_boundary",
                status="pass",
                severity="info",
                file_path=".git",
                message="No .git directory inside scaffold.",
            ))

        return checks

    # ------------------------------------------------------------------
    # Artifact renderers
    # ------------------------------------------------------------------

    def _render_validation_md(self, report: ScaffoldValidationReport) -> str:
        status_icon = {"pass": "PASS", "fail": "FAIL", "warning": "WARN", "unknown": "???"}
        icon = status_icon.get(report.validation_status, report.validation_status.upper())
        lines = [
            f"# Static Validation Report [{icon}]",
            "",
            f"**Project:** {report.project_id}",
            f"**Scaffold root:** {report.scaffold_root}",
            f"**Status:** {report.validation_status}",
            f"**Safe to proceed to toolchain validation:** {report.safe_to_proceed_to_toolchain_validation}",
            f"**Safe to execute tests:** {report.safe_to_execute_tests}",
            f"**Created:** {report.created_at}",
            "",
            "---",
            "",
            "## Safety Invariants",
            "",
            f"- execution_performed: {report.execution_performed}",
            f"- npm_performed: {report.npm_performed}",
            f"- npx_performed: {report.npx_performed}",
            f"- browser_performed: {report.browser_performed}",
            f"- external_calls_performed: {report.external_calls_performed}",
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

        lines += ["## All Checks", "", "| ID | Name | Category | Status | Severity | Blocks |", "|----|------|----------|--------|----------|--------|"]
        for c in report.checks:
            lines.append(
                f"| {c.id} | {c.name} | {c.category} | {c.status} | {c.severity} | {c.blocks_next_phase} |"
            )

        if report.notes:
            lines += ["", "## Notes", ""]
            for n in report.notes:
                lines.append(f"- {n}")

        return "\n".join(lines) + "\n"

    def _render_validation_plan(
        self, report: ScaffoldValidationReport, plan: ToolchainValidationPlan
    ) -> str:
        lines = [
            "# Validation Plan",
            "",
            f"**Project:** {report.project_id}",
            f"**Static validation status:** {report.validation_status}",
            "",
            "## Phase 3B: Static Checks (Completed)",
            "",
            f"Static analysis ran {len(report.checks)} checks with no code execution.",
            "",
            "## Phase 3C: Toolchain Validation (Requires Approval)",
            "",
            "The following commands are proposed but NOT yet executed.",
            "**All require explicit human approval before running.**",
            "",
        ]
        for cmd in plan.proposed_commands:
            lines.append(f"- `{cmd}`")
        lines += [
            "",
            f"- approval_required: {plan.approval_required}",
            f"- network_access_required: {plan.network_access_required}",
            f"- browser_execution_required: {plan.browser_execution_required}",
            f"- safe_without_approval: {plan.safe_without_approval}",
        ]
        return "\n".join(lines) + "\n"

    def _render_local_checklist(self, report: ScaffoldValidationReport) -> str:
        lines = [
            "# Local Validation Checklist",
            "",
            f"**Project:** {report.project_id}",
            f"**Static validation status:** {report.validation_status}",
            "",
            "## Before Running Any Commands Locally",
            "",
        ]

        check_items = [
            "Review STATIC_VALIDATION_REPORT.md — resolve all blockers first",
            "Review scaffold files manually in outputs/<project_id>/03_framework/playwright/",
            "Copy .env.example to .env and fill in real values (do NOT commit .env)",
            "Obtain explicit approval to run: npm install",
            "Obtain explicit approval to run: npx playwright install",
            "Run: npm install (after approval)",
            "Run: npx tsc --noEmit (type-check only, no test execution)",
            "Run: npx playwright test --list (list tests, no execution)",
            "Run: npx playwright test (only after full review and approval)",
        ]
        for item in check_items:
            lines.append(f"- [ ] {item}")

        lines += [
            "",
            "## Static Validation Blockers (Must Resolve First)",
            "",
        ]
        if report.blockers:
            for b in report.blockers:
                lines.append(f"- [ ] BLOCKER: {b}")
        else:
            lines.append("- No blockers. Static validation passed.")

        return "\n".join(lines) + "\n"

    def _render_toolchain_plan(self, plan: ToolchainValidationPlan) -> str:
        lines = [
            "# Toolchain Validation Plan",
            "",
            f"**Project:** {plan.project_id}",
            f"**approval_required:** {plan.approval_required}",
            f"**network_access_required:** {plan.network_access_required}",
            f"**browser_execution_required:** {plan.browser_execution_required}",
            f"**safe_without_approval:** {plan.safe_without_approval}",
            "",
            "## Proposed Commands (NOT YET EXECUTED)",
            "",
            "> All commands below require explicit human approval before execution.",
            "",
        ]
        for cmd in plan.proposed_commands:
            lines.append(f"```\n{cmd}\n```")

        if plan.notes:
            lines += ["", "## Notes", ""]
            for n in plan.notes:
                lines.append(f"- {n}")

        return "\n".join(lines) + "\n"

    # ------------------------------------------------------------------
    # I/O helpers
    # ------------------------------------------------------------------

    def _write_json(self, path: Path, data: dict) -> str:
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def _write_text(self, path: Path, content: str) -> str:
        path.write_text(content, encoding="utf-8")
        return str(path)
