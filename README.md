# Guided QA Automation Workbench

> **AI drafts. Senior QA decides.**

A local, AI-assisted QA automation platform for real client projects.  
Built for Dmytro Pogribnyy — SDET / QA Automation Lead.

---

## What this is

**AI QA Factory is evolving into a Guided QA Automation Workbench** for real client QA automation work.

Conceptually similar in flow to Lovable, Make, or n8n — but specialized for QA automation consulting:

```
Understand → Classify Inputs → Build Project Blueprint
    → Plan Strategically → Plan Tactically → Select Tools
    → Ask Approval → Execute Safely → Collect Evidence → Report Clearly
```

The workbench accepts a brief, client task, or job post; classifies the context; builds a QA strategy and test automation plan; generates a Playwright TypeScript scaffold; and stops — waiting for your review before anything touches a real environment or goes to a client.

**It is not a full autopilot.** It uses human approval gates at every risky step.

---

## What it supports

**Inputs (current and planned):**
- Text briefs and job posts
- Task URLs (Jira, Linear, Notion tickets)
- Target application URLs (classified, not fetched automatically)
- Screenshots (via vision model — planned)
- Uploaded archives and repos (planned)
- API documentation (OpenAPI, Postman — planned)

**Project types:**
- Web SaaS (multi-tenant, auth, billing)
- E-commerce (checkout, cart, payment flows)
- API backends (REST, GraphQL)
- AI-generated applications
- Admin panels
- Auth-heavy applications
- Mixed UI + API
- Unknown / to be classified

**Outputs:**
- Project Blueprint (source of truth)
- Strategic QA plan
- Tactical test plan and test cases
- Playwright TypeScript scaffold (full npm project)
- API test suite
- Evidence pack
- Internal summary report
- Client-facing delivery report (gated behind explicit approval)

---

## Safety model

| Action | Behaviour |
|---|---|
| Analyze text input | Automatic |
| Generate strategy / scaffold | Automatic |
| Run local validation (compile, lint, dry-run) | Automatic |
| Run tests against staging URL | **Requires approval** |
| Run tests against production | **Requires explicit read-only approval** |
| Test payment / auth / security flows | **Requires approval + sandbox confirmation** |
| Send client-facing report | **Requires final approval** |

External and staging execution is blocked by default. `--approve` flag unlocks it per run.  
See [`docs/APPROVAL_MODEL.md`](docs/APPROVAL_MODEL.md) and [`docs/SAFETY_RULES.md`](docs/SAFETY_RULES.md).

---

## Quick start

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS/Linux
pip install -r requirements.txt
copy .env.example .env
python -m pytest -q             # 3351 tests, mock mode, no API keys needed
python main.py system-health
python tools/docs_audit.py      # verify documentation is current
python tools/classify_inputs.py --input "Need Playwright tests for SaaS dashboard" --no-write
```

---

## Current commands

```bash
# System
python main.py system-health
python main.py capabilities
python main.py agents

# Opportunity evaluation
python main.py prescreen --input brief.txt
python main.py filter   --input brief.txt
python main.py upwork   --input brief.txt --source-platform upwork --require-real-llm
python main.py batch-filter --input real_jobs/

# QA delivery
python main.py test-design --input brief.txt --require-real-llm
python main.py scaffold    --input brief.txt --require-real-llm
python main.py plan        --input brief.txt --require-real-llm
python main.py audit       --input brief.txt --require-real-llm
python main.py full        --input brief.txt --require-real-llm
python main.py review      --input tests/smoke.spec.ts
python main.py delivery    --input brief.txt --require-real-llm

# Execution control
python main.py full --input brief.txt --step
python main.py full --input brief.txt --dry-run
python main.py full --input brief.txt --only proposal_writer
python main.py full --input brief.txt --from-step proposal_writer
python main.py run-tests --project-path outputs/<id>/framework --kind playwright
python main.py ask --project-id <id> --question "Why apply_selectively?"

# Workbench tools (Phase 3A+)
python tools/build_strategy.py --project-id <id>          # Phase 2C: QA strategy
python tools/docs_audit.py                                 # docs freshness check
python tools/agent_readiness_audit.py                      # agent readiness check

# Controlled execution tools (Phase 4D+)
python tools/run_browser_demo.py --project-id <id> --approve-demo-execution
python tools/inspect_credentials.py --project-id <id>     # Phase 4E: credential safety
python tools/run_demo_auth.py --project-id <id> \
    --approve-demo-auth-execution --auth-profile saucedemo_demo_auth

# Scenario execution matrix (Phase 4G)
python tools/build_execution_matrix.py --project-id <id>
python tools/build_execution_matrix.py --project-id <id> \
    --decide-url https://www.saucedemo.com --scenario-type no_auth_smoke

# AI Intelligence Core (Phase 5K)
python tools/run_intake_agent.py --project-id <id> \
    --input-text "We need to test the login API and session management"
python tools/run_test_oracle.py --project-id <id> --classification api_testing
python tools/run_evidence_intelligence.py --project-id <id>

# E2E Pipeline (Phase 5J)
python tools/run_e2e_pipeline.py --project-id <id>          # plan mode
python tools/run_e2e_pipeline.py --project-id <id> \
    --enable-api-smoke --approve-pipeline-execution         # execute
python tools/run_db_smoke.py --project-id <id> \
    --provider postgresql --db-url-env-var STAGING_DB_URL \
    --table users --approve-db-smoke
```

Full command reference with planned future commands: [`docs/COMMANDS.md`](docs/COMMANDS.md)

---

## Configuration

```env
LLM_MODE=real
MODEL_PROFILE=premium_hybrid
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

Role routing in `premium_hybrid`:

| Role | Model | Used for |
|---|---|---|
| `architect` | `gpt-5.5` | Strategy, capability routing, prescreening |
| `coding` | `claude-sonnet-4-6` | Scaffold, test implementation |
| `review` | `claude-opus-4-7` | Quality gate, self-health, deep review |
| `fast` | `claude-sonnet-4-6` | Proposals, summaries, delivery notes |
| `vision` | `gpt-5.5` | Screenshot / visual input (planned) |
| `fallback` | `gpt-5.4-mini` | Backup |

---

## Tooling decisions

- **Orchestrator:** Registry-based (current default). LangGraph is optional future backend — not mandatory now.
- **Automation framework:** Playwright + TypeScript is the primary target.
- **Reporting:** Markdown + JSONL locally. Allure is an optional future adapter.
- **Observability:** Local JSONL logs. LangSmith is optional — not mandatory now.
- **Playwright MCP:** Not a mandatory runtime dependency.
- **Playwright codegen / trace viewer:** Useful helpers, not managed by the workbench.

See [`docs/TOOLING_DECISIONS.md`](docs/TOOLING_DECISIONS.md) for rationale.

---

## Tests

```bash
.venv\Scripts\python.exe -m pytest -q   # always mock mode — no API keys consumed
```

Expected: **2893 passed** (all phases through 6.1 — schema foundations, classification, blueprint, strategy, scaffold validation, toolchain, execution readiness, evidence, reporting, delivery preview, scenario evaluation, browser execution, credential safety, demo auth execution, scenario execution matrix, task source integration, API smoke, Google/GitHub OAuth, mobile viewport, visual regression, E2E pipeline runner, DB smoke, AI intelligence core, desktop browser execution CLI, API contract importer, CI/CD builder, client delivery pack, golden delivery, accessibility smoke, performance smoke, passive security, quality audit delivery workflow, flaky test analyzer, MCP server adapter, MCP demo workflow validation, one-command client audit workflow)

---

## Docs

| Document | Purpose |
|---|---|
| [`docs/VISION.md`](docs/VISION.md) | Product vision and roadmap |
| [`docs/RUNBOOK.md`](docs/RUNBOOK.md) | Daily operating guide |
| [`docs/COMMANDS.md`](docs/COMMANDS.md) | Full command reference (implemented + planned) |
| [`docs/APPROVAL_MODEL.md`](docs/APPROVAL_MODEL.md) | Risk levels, approval gates, what runs automatically |
| [`docs/SAFETY_RULES.md`](docs/SAFETY_RULES.md) | Hard rules — what never runs automatically |
| [`docs/TOOLING_DECISIONS.md`](docs/TOOLING_DECISIONS.md) | Orchestrator, LangGraph, Playwright, Allure, LangSmith decisions |
| [`docs/SCHEMA_FOUNDATION.md`](docs/SCHEMA_FOUNDATION.md) | `core/schemas/` layer — 50+ domain models |
| [`docs/PROJECT_TYPES.md`](docs/PROJECT_TYPES.md) | Supported project types with risks and test focus |
| [`docs/DOCUMENTATION_GOVERNANCE.md`](docs/DOCUMENTATION_GOVERNANCE.md) | How to keep docs accurate as the project evolves |
| [`docs/DOCS_MANIFEST.md`](docs/DOCS_MANIFEST.md) | Registry of all documentation files and their status |
| [`docs/PHASE_CONTRACTS.md`](docs/PHASE_CONTRACTS.md) | Phase boundaries — what is implemented vs planned |
| [`docs/ARTIFACT_CONTRACTS.md`](docs/ARTIFACT_CONTRACTS.md) | Artifact paths, ownership, and delivery rules |
| [`docs/AGENT_CONTRACT.md`](docs/AGENT_CONTRACT.md) | Agent operating rules and safety obligations |
| [`docs/AGENT_HANDOFF_TEMPLATE.md`](docs/AGENT_HANDOFF_TEMPLATE.md) | Final phase report template |
| [`docs/architecture/PROSPECT_QA_RADAR_SPEC.md`](docs/architecture/PROSPECT_QA_RADAR_SPEC.md) | Prospect QA Radar / Super Scout — **approved future-facing architecture; no runtime yet**, integration starts with Phase 8.2 contracts |

---

## Changelog highlights

<!-- sync-anchor: v5.0.8 model routing profiles — kept for internal test compatibility -->
### v8.1.0 — ARK planning-only work entrypoint (current)

- New command `python main.py work` (planning-only): turns a brief into a reviewable plan.
  **No LLM in the core path, no MCP calls, no network, no browser, no execution.**
- Deterministic pipeline (`core/orchestration/`): redact → classify → infer profile →
  extract requirements → analyse missing info → plan capabilities → compose toolchain →
  enforced state machine → content-scanned atomic artifact publication.
- Universal `UniversalProfileSelector` (8 profiles; unknown work stays unresolved, never
  silently QA). MCP-backed steps stay unresolved candidates (`tool_name=""`,
  `availability_verified=false`) until Phase 8.3 discovery.
- Real content secret scanning before an atomic publish (the legacy scanner only checked
  filenames); artifacts confined to `outputs/<project_id>/40_ark_work/`.
- Additive schema fields (resolution status, candidate/discovery, `factory_process_launch_unverified`,
  `ProfileSelection`); `WorkStateManager` enforces transitions + `state_version`.
- 3635 tests total (72 new Phase 8.1 tests). Still no live MCP client / discovery.

### v8.0.0 — ARK universal orchestration foundation

- **Planning/schema foundation only — no runtime MCP client yet.** No `main.py work` command
  is available; existing QA workflows remain unchanged.
- ARK layer builds additively on the mature QA Factory core (see `docs/PRODUCT_VISION_2026.md`,
  `docs/UNIVERSAL_WORK_FACTORY.md`, `docs/REUSE_MAP_PHASE8.md`).
- New additive schemas: `WorkPacket`, `Requirement`, `Capability`/`CapabilityProfile`,
  `CapabilityPlan`, `MCPServerDescriptor`/`MCPToolDescriptor`, `ToolchainPlan`/`SelectedMCPTool`/
  `ToolExecutionPolicy`/`ExecutionBudget`, `WorkRunState`, `WorkDeliveryManifest`, `EvidenceClaim`,
  capability-gap schemas. `ClientDeliveryManifest` and `ToolSelection` unchanged.
- Reference-only MCP manifest `config/mcp_servers.yaml` (all servers `enabled: false`, no
  `@latest`, env-var auth references only) + atomic capability registry + 8 capability profiles.
- MCP consumption is **planned, not implemented**: no live discovery, no MCP invocation, no
  browser/network execution, no external writes, no server install/enable.
- 3563 tests total (44 new Phase 8.0 tests).

### v7.4.0 — Auth Demo Workflow

- Phase 7R: `core/auth_demo_workflow.py` — `AuthDemoScenario`, `AuthDemoResult` (safety invariants via `__post_init__`), `AuthDemoWorkflow` orchestrating 7A→7B→7C→7D in planning-only mode
- Phase 7R: `tools/run_auth_demo_workflow.py` — CLI with blocked-flag guard; no real credentials or storageState required
- Phase 7R: Generates 5 artifact subdirs + `33_client_audit/client_report.md` with Authentication Coverage (Executed/Planned/Skipped/Blocked sections)
- Phase 7R: 4 hardcoded blocked safety cases in every run: personal account, production account, raw CLI password, CAPTCHA bypass
- Phase 7R: `approved_for_client_delivery=False`, `human_review_required=True` always enforced
- Phase 7R: AGENT_CONTRACT.md updated with 7D and 7R agent rules
- Phase 7R: 84 new tests; 3519 total

### v7.3.0 — Email/Password Auth Runner

- Phase 7D: `core/schemas/email_password.py` — `EmailPasswordRunStatus` (5 states), `EmailPasswordModeReadiness` (3 states), `EmailPasswordInputs`, `EmailPasswordPlan`, `EmailPasswordRunResult` — all with 7 safety invariants via `__post_init__`
- Phase 7D: `core/email_password_runner.py` — `EmailPasswordRunner`: check_env_vars (presence only), build_plan, run (Node.js smoke), render_artifacts, format_auth_coverage_section
- Phase 7D: `tools/run_email_password_smoke.py` — CLI with blocked-flag guard; `--approve-execution` required for actual smoke; raw secrets never accepted via CLI
- Phase 7D: Credential flow: Python passes env var NAMES via `EP_USERNAME_ENV_VAR`/`EP_PASSWORD_ENV_VAR`; Node reads values — Python never touches credential values
- Phase 7D: Supported target: `orangehrm_demo` (OrangeHRM open-source demo)
- Phase 7D: Output artifacts: `outputs/<project>/37_email_password_auth/` — `email_password_plan.json`, `email_password_report.json`, `email_password_summary.md`
- Phase 7D: 84 new tests; 3435 total

### v7.2.0 — Google OAuth StorageState Runner

- Phase 7C: `core/schemas/google_oauth.py` — `GoogleOAuthMode` (6 values), `GoogleOAuthModeReadiness` (3 states), `GoogleOAuthRunStatus` (5 states), `GoogleOAuthInputs`, `GoogleOAuthPlan`, `GoogleOAuthRunResult` — all with 8–9 safety invariants via `__post_init__`
- Phase 7C: `core/google_oauth_runner.py` — `GoogleOAuthRunner`: classify_mode, build_plan, run (storageState reuse), render_artifacts, format_auth_coverage_section
- Phase 7C: `tools/run_google_oauth_smoke.py` — CLI with blocked-flag guard; 1 executable mode + 5 planning-only; `--approve-execution` required for actual smoke
- Phase 7C: Output artifacts: `outputs/<project>/16_google_oauth/` — `google_oauth_plan.json`, `google_oauth_report.json`, `google_oauth_summary.md`
- Phase 7C: URL allowlist — 6 Google HTTPS prefixes; captcha/recaptcha/challenge/anti-bot URLs always blocked
- Phase 7C: `next_runner: "google_oauth_runner"` from Phase 7B is now implemented
- Phase 7C: 106 new tests; 3351 total

### v7.1.0 — Auth Strategy Selector

- Phase 7B: `core/schemas/auth_strategy.py` — `DecisionStatus` (5 states), `AuthStrategyDecision` with 8 safety invariants via `__post_init__`
- Phase 7B: `core/auth_strategy_selector.py` — `AuthStrategySelector`: picks best method from 7A plan using 15-method priority order
- Phase 7B: `tools/select_auth_strategy.py` — CLI with two modes: `--plan-file` (load 7A JSON) or inline (run planner + select)
- Phase 7B: Output artifacts: `outputs/<project>/35_auth_strategy/auth_strategy_decision.json` + `auth_strategy_summary.md`
- Phase 7B: `safe_to_execute=True` only when `decision_status == ready_for_execution`; `next_runner` names the runner for Phase 7C+
- Phase 7B: `AuthCapabilityPlan.from_dict()` added for JSON deserialization
- Phase 7B: 83 new tests; 3245 total

### v7.0.0 — Auth Capability Planner

- Phase 7A: `core/schemas/auth_capability.py` — `AuthMethodType` (15 methods), `AuthReadiness` (7 states), `AuthMethodCapability`, `AuthCapabilityInputs`, `AuthCapabilityPlan`
- Phase 7A: `core/auth_capability_planner.py` — `AuthCapabilityPlanner`: classifies all 15 auth methods, writes planning artifacts
- Phase 7A: `tools/plan_auth_capability.py` — CLI with blocked-flag guard, env-var-name-only pattern, ASCII readiness markers
- Phase 7A: Output artifacts: `outputs/<project>/34_auth_capability/auth_capability_plan.json` + `auth_capability_summary.md`
- Phase 7A: Safety invariants enforced by `__post_init__` — `personal_account_allowed`, `captcha_bypass_allowed`, `auth_bypass_allowed` always `False`; `human_review_required` always `True`
- Phase 7A: Blocked CLI flags exit 1 before argparse: `--password`, `--secret`, `--token`, `--cookie`, `--totp-seed`, `--access-token`, `--bearer`, `--client-secret`, `--api-key`
- Phase 7A: 88 new tests; 3162 total

### v6.7.0 — Client Delivery Report v1

- Phase 6.3: `core/reporting/client_delivery_report.py` — professional client-facing QA audit report generator
- Phase 6.3: `client_report.md` — 12-section report with Executive Summary, Risk Matrix, Key Findings, Recommended Actions
- Phase 6.3: Human-readable language (not system log); severity-based action language; skipped modules explained
- Phase 6.3: Always DRAFT + `approved_for_client_delivery = False` — report is never auto-approved
- Phase 6.3: Path to `client_report.md` printed at end of `run_client_audit.py` write run
- Phase 6.3: 83 new tests; 3074 total

### v6.6.0 — Structured Finding Schema + Risk Matrix

- Phase 6.2: `core/schemas/finding.py` — typed `Finding` dataclass with `Severity`, `FindingCategory`, `FindingStatus`, `Confidence` enums
- Phase 6.2: `core/risk/risk_matrix.py` — `RiskMatrix` + `risk_score()` (deterministic scoring and sorting)
- Phase 6.2: `core/risk/finding_adapters.py` — adapters: `findings_from_api_contract()`, `findings_from_secret_scan()`
- Phase 6.2: `ClientAuditResult` extended with `structured_findings`, `total_findings`, `risk_summary` (backward-compat `findings: int` preserved)
- Phase 6.2: `run_report.json` includes full structured findings + risk matrix summary
- Phase 6.2: `summary.md` includes `## Risk Matrix` section with top risks and recommended actions
- Phase 6.2: 98 new tests; 2991 total

### v6.5.0 — One-Command Client Audit Workflow

- Phase 6.1: `tools/run_client_audit.py` — single entrypoint for a full client QA audit
- Phase 6.1: `core/client_audit_workflow.py` — thin orchestrator over existing modules
- Phase 6.1: `core/schemas/client_audit.py` — `ClientAuditMode`, `ClientAuditInputs`, `ClientAuditResult` with `__post_init__` safety invariants
- Phase 6.1: 4 workflow modes: `safe_audit`, `api_only`, `frontend_readonly`, `delivery_only`
- Phase 6.1: Preflight plan printed before any module runs (detected inputs, enabled/skipped/blocked)
- Phase 6.1: Output dir `33_client_audit/` with plan JSON, preflight MD, run report JSON, summary MD
- Phase 6.1: 106 new tests; 2893 total
- Blocked: `--auto-approve-all`, `--skip-human-review`, `--force-deliver`

### v6.4.0 — MCP Demo Workflow Validation

- Phase 6-R: `tools/run_mcp_demo_workflow.py` — 7-step demo runner validates full QA Factory flow
- Phase 6-R: Flow: health → analyze → quality_audit → flaky_analysis → proposals → delivery_pack → blocked_apply
- Phase 6-R: `--no-write` dry run; `--json-output` full JSON results; blocked flags exit 1
- Phase 6-R: 49 new end-to-end tests; 2787 total
- Phase 6-R: ASCII-only output (Windows cp1252 safe)

### v6.3.0 — QA Factory as MCP Server

- Phase 6: `integrations/mcp/` — thin adapter layer over existing core modules
- Phase 6: 7 MCP tools: `qa_factory_health`, `analyze_project`, `run_quality_audit`, `run_flaky_test_analysis`, `generate_delivery_pack`, `propose_self_healing_fixes`, `apply_self_healing_fixes`
- Phase 6: `tool_handlers.py` — pure Python, testable without mcp package
- Phase 6: `server.py` — MCP stdio server (requires: `pip install mcp`)
- Phase 6: `tools/run_mcp_server.py` — CLI with `--list-tools`, `--demo-health`, `--version`
- Phase 6: All tools default to planning_only/analysis_only; no credentials accepted; `human_review_required=True` in every response
- Phase 6: 95 new tests; 2738 total
- Blocked: `--approve-delivery`, `--skip-review`, `--auto-start-browser`, `--credentials`

### v6.2.0 — Flaky Test Analyzer + Self-Healing Proposals

- Phase 5O: `FlakyTestAnalyzer` — static analysis of Playwright spec files (no network, no browser)
- Phase 5O: `analyze()` — detects hard waits, fragile selectors, non-web-first assertions, dynamic classes
- Phase 5O: `analyze_selectors()` — stability score 0–100 (strong=getByRole/Label/TestId, weak=nth/xpath/generated-class)
- Phase 5O: `generate_healing_proposals()` — proposals only, `applied=False` by default
- Phase 5O: `apply_proposals()` — TODO comment insertion, requires `--approve-code-modification`
- Phase 5O: 3 new schemas (`FlakyTestAnalysisReport`, `SelectorStabilityReport`, `SelfHealingReport`) + 3 sub-schemas
- Phase 5O: Client Delivery Pack reads dir 32, flaky analysis row in QA report table
- Phase 5O: Demo fixtures (`stable_test.spec.ts`, `flaky_test.spec.ts`) in `fixtures/demo_quality_audit/playwright_specs/`
- Phase 5O: 75 new tests; 2643 total
- Blocked: `--auto-fix`, `--skip-human-review`, `--approve-delivery`, `--force-apply`

### v6.1.0 — Quality Audit Delivery Workflow

- Phase 5N-R: `demo_quality_audit` fixture set (29_accessibility + 30_performance + 31_passive_security)
- Phase 5N-R: `planning_only` fixtures (accessibility + performance) + `executed` fixture (passive security: 3/5 OWASP headers)
- Phase 5N-R: 96 golden tests — fixture integrity, planning_only mode, approved execution, delivery pack 5N integration, ZIP safety, content quality
- Phase 5N-R: QA report table correctly distinguishes `planning_only` vs `executed` per module
- Phase 5N-R: Evidence Index references 29/30/31 artifact dirs with execution status

### v6.0.0 — Accessibility + Performance + Passive Security

- Phase 5N: `AccessibilityRunner` — axe-core Playwright skeleton + approved execution path (WCAG 2.1 AA)
- Phase 5N: `PerformanceSmokeRunner` — Core Web Vitals CDP skeleton + approved execution (LCP/FCP/TTFB)
- Phase 5N: `PassiveSecurityRunner` — OWASP header skeleton + real passive HEAD request (approved)
- Phase 5N: 3 new schemas (`AccessibilityReport`, `PerformanceSmokeReport`, `PassiveSecurityReport`)
- Phase 5N: Hybrid mode — `planning_only` (default) vs `executed`; delivery pack distinguishes both
- Phase 5N: Client Delivery Pack updated — shows "Generated checks only; execution requires approval" for planning_only
- Phase 5N: 174 new tests (58 each); 2472 total
- All safety invariants double-enforced in `__post_init__` + injection-proof via `from_dict`

### v5.9.0 — Client Delivery Pack

- Phase 5P: `ClientDeliveryPack` — aggregate all phase outputs into a client-ready delivery package
- Phase 5P: `SecretScanner` — pre-delivery scan blocks storageState, .env, credentials, cookies, tokens
- Phase 5P: 9 delivery artifacts: QA_Report.md/html, Bug_Report, Test_Cases.csv, Risk_Matrix, Recommendations, Evidence_Index, Delivery_Checklist, manifest + ZIP
- Phase 5P: `approved_for_client_delivery=False` hardcoded — manual sign-off always required
- Phase 5P: CLI `create_client_delivery_pack.py` with blocked `--approve`, `--auto-send`, `--skip-secret-scan` flags
- Phase 5P: 108 new tests; 2226 total
- All safety invariants double-enforced in `__post_init__` + injection-proof via `from_dict`

### v5.8.0 — Demo Workflow Hardening

- Phase 5M-R: 4 realistic fixture specs (`petstore_openapi.json`, `sample_openapi.yaml`, `risky_api_openapi.json`, `postman_sample.json`)
- Phase 5M-R: 51 end-to-end demo workflow tests (`tests/test_phase5mr_demo_workflow.py`)
- Phase 5M-R: DELETE method always `blocked_by_default` (path-independent fix)
- Phase 5M-R: PyYAML ImportError gives clear install instructions
- Phase 5M-R: CI/CD content hardening verified programmatically (no secrets/deploy/git-push/PR-create)
- Phase 5M-R: 51 new tests; 2118 total

### v5.7.0 — API Contract Importer + CI/CD Builder

- Phase 5M: `APIContractImporter` — parse OpenAPI JSON/YAML and Postman collections into classified endpoint reports
- Phase 5M: `APITestGenerator` — generate Playwright API smoke + schema test skeletons (safe_readonly only; planning artifact, not auto-executable)
- Phase 5M: `CICDBuilder` — generate GitHub Actions + GitLab CI workflows for Playwright smoke (planning artifact, manual copy required)
- Phase 5M: Safety classification per endpoint: `safe_readonly / requires_approval / blocked_by_default`
- Phase 5M: 3 CLI tools (`import_api_contract.py`, `generate_api_tests.py`, `build_cicd_config.py`)
- Phase 5M: 3 artifact dirs (`25_api_contract/`, `26_generated_tests/`, `27_cicd/`)
- Phase 5M: 101 new tests; 2067 total
- All safety invariants double-enforced in `__post_init__` + `from_dict` across all new schemas

### v5.6.0 — Desktop Browser Execution CLI + Advanced Smoke Suite

- Phase 5L: `tools/run_browser_execution.py` — approval-gated desktop Playwright smoke CLI
- Phase 5L: Dual-approval model for ecommerce targets (Amazon, Alza): both `--approve-demo-execution` AND `--approve-public-readonly-execution` required
- Phase 5L: 4 advanced smoke spec files (desktop + mobile, Amazon + Alza) with dual-viewport `test.skip()` guards
- Phase 5L: Hardcoded site URLs in spec files to prevent cross-site BASE_URL contamination
- Phase 5L: Playwright scaffold with `screenshot/video/trace: retain-on-failure`, HTML reporter
- Phase 5L: 35 new tests in `tests/test_phase5l_browser_execution_cli.py`
- Phase 5L: `tsconfig.json` fixed — `noEmit: true`, `rootDir: "."`, `lib: ["ES2020", "DOM"]` (resolves 9 VS Code TS errors)
- Phase 5K: `IntakeAgent` — heuristic work-request classifier; raw input never stored
- Phase 5K: `TestOracle` — prioritized scenario generator; planning artifact, not executable
- Phase 5K: `EvidenceIntelligence` — read-only artifact gap analyzer; no network/subprocess
- Phase 5K: risk level detection bug fixed — keywords checked before `if not scores:` early return
- Phase 5J-R: `stop_on_first_failure` pipeline mode; demo pipeline CLI (`run_demo_pipeline.py`)
- Phase 5J: `E2EPipelineRunner` + `DBSmokeRunner`; 9-module fixed execution order
- Phase 5I: mobile viewport emulation, visual regression, GitHub OAuth
- Phase 5H: multi-target expansion, task source integration, Google Auth modes
- All safety invariants double-enforced in `__post_init__` + `from_dict`
- 1966 tests passing (1931 Python + 35 Phase 5L)

### v5.2.0 — Controlled Execution + Scenario Matrix

- Phase 3A: `core/framework_scaffold_builder.py` — Playwright TypeScript scaffold generator
- Phase 3B: `core/scaffold_validator.py`, client scenario fixtures (`fixtures/client_scenarios/`) — scaffold validation and scenario library
- Phase 3C: `core/toolchain_validator.py` — local toolchain validation (tsc, eslint, npx playwright)
- Phase 4A: `core/schemas/execution_approval.py` — execution readiness checklist (approval-gated)
- Phase 4B: `core/schemas/evidence.py` — evidence foundation with redaction and quality gates
- Phase 4C: `core/schemas/reporting.py`, `core/schemas/delivery_preview.py` — report drafts, delivery preview, safety checklists
- Phase 4ABC: `core/schemas/scenario_evaluation.py` — scenario batch evaluation, 4 synthetic + 8 real-world scenarios
- Phase 4D: `core/browser_demo_runner.py`, `tools/run_browser_demo.py` — approval-gated browser demo execution (SauceDemo only)
- Phase 4E: `core/credential_safety_inspector.py`, `tools/inspect_credentials.py` — credential safety inspection with hardcoded guards
- Phase 4F: `core/demo_auth_runner.py`, `tools/run_demo_auth.py` — approval-gated demo auth execution (SauceDemo only, public credentials)
- Phase 4G: `core/scenario_execution_matrix.py`, `tools/build_execution_matrix.py` — scenario execution matrix, 9 canonical lanes, dedicated test account planning
- All safety invariants double-enforced in `__post_init__` + `from_dict` — bypass-proof
- 1335 tests passing

### v5.1.0 — Guided QA Automation Workbench

- Product direction: evolving from opportunity router to full QA automation workbench
- `core/version.py`: `APP_VERSION`, `STATE_SCHEMA_VERSION`, `RELEASE_LABEL`
- New docs: VISION, COMMANDS, APPROVAL_MODEL, TOOLING_DECISIONS, SAFETY_RULES, PROJECT_TYPES
- Phase 1B: 35 schema modules in `core/schemas/` — domain models, auth/credential, mobile, integration, documentation governance
- Phase 1B-DOCS: `tools/docs_audit.py`, `DOCUMENTATION_GOVERNANCE.md`, `DOCS_MANIFEST.md`
- Phase 2A: `core/input_context_resolver.py`, `core/work_request_classifier.py` — input classification, secret redaction
- Phase 2B: `core/project_blueprint_builder.py` — project blueprint from classified inputs (8 project types)
- Phase 2B-AGENT: `docs/AGENT_CONTRACT.md`, `docs/PHASE_CONTRACTS.md`, `docs/ARTIFACT_CONTRACTS.md`, `docs/AGENT_HANDOFF_TEMPLATE.md`, `tools/agent_readiness_audit.py`
- Phase 2C: `core/qa_strategy_planner.py`, `core/schemas/qa_strategy.py`, `tools/build_strategy.py` — QA strategy planner, 8 artifact types in `02_strategy/`
- Pre-screen first: opportunity evaluation workflows fully supported and preserved

### v5.0.9 — Validation hardened

Patches: api_testing routing (P1), mobile risk flag (P2), SaaS billing check (P3), test-design mode (P4).

### v5.0.8 — Model routing additions

Role-based model routing profiles: architect / coding / review / fast / vision / fallback.  
`system-health`, `--project-id`, `--source-platform` added.
