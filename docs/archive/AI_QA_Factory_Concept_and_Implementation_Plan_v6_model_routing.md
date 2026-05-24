# AI QA Factory — единый концепт, архитектура и план реализации

**Version:** v2.0 — Market-Calibrated Architecture Plan  
**Owner:** Dmytro Pogribnyy  
**System focus:** QA / SDET / Playwright / SaaS / AI-assisted delivery / multi-platform opportunity routing  
**Status:** Concept + architecture + implementation direction for v5.0.3+  

---

## 0. Назначение документа

Этот документ фиксирует единое видение системы **AI QA Factory**: что мы строим, зачем, какие задачи система должна решать, какие архитектурные принципы использовать, какие инструменты подключать, что делать сейчас, что оставить на будущие версии и как не превратить проект в хаотичный набор ad hoc-правок.

Документ нужен как **единая точка опоры** для дальнейшей разработки, ревью через GPT / Claude / Grok и практического использования системы в фриланс-бизнесе Dmytro Pogribnyy.

Главное изменение v2.0: система больше не описывается как “Upwork/Playwright-only tool”. Она становится **multi-platform opportunity and QA delivery system**, где Playwright остаётся strongest execution zone, но Factory умеет маршрутизировать и другие типы задач: manual QA, SaaS audit, API testing, mobile QA, Tosca advisory, Next.js QA, technical writing, documentation migration, AI automation opportunities, evaluator platforms, Fiverr/PPH gigs and direct B2B leads.

---

## 1. Краткое видение

**AI QA Factory** — это локальная, модульная, human-in-the-loop система для Senior QA / SDET / AI-assisted freelancer, которая помогает быстрее находить, фильтровать, оценивать, выигрывать и выполнять paid opportunities across multiple channels.

Система не должна заменять Senior QA. Она должна усиливать его.

Главное правило:

> **AI drafts. Senior QA decides.**

AI генерирует черновики и аналитические артефакты: opportunity analysis, fit/skip decision, proposal, screening answers, QA audit plan, bug report pack, Playwright scaffold, API notes, mobile advisory, technical writing pitch, delivery report, evidence checklist.

Финальное решение, редактирование и ответственность всегда остаются за Dmytro.

---

## 2. Бизнес-цель

Главная цель системы — помочь Dmytro быстрее выйти на устойчивый доход через несколько связанных каналов:

1. **Upwork + direct QA proposals** — основной high-ticket route.
2. **Paid QA / DevTools writing** — authority + cash + clips.
3. **B2B whitepapers / legal-tech** — high-margin writing and consulting.
4. **AI evaluator platforms** — flexible side cash, но без использования AI для выполнения evaluator tasks.
5. **Fiverr / PeoplePerHour microservices** — small wins, reviews, packaged services.
6. **Courses / templates / workshops** — later compounding assets.
7. **Direct LinkedIn / B2B outreach** — QA audit and legal-tech offers.

Система должна помогать:

1. Быстро анализировать opportunities из разных источников.
2. Фильтровать strong apply / selective apply / advisory / skip.
3. Генерировать platform-specific outputs: proposal, pitch, gig, DM, article outline, evidence checklist.
4. Готовить QA audit / test plan / bug report pack / delivery report.
5. Генерировать starter Playwright framework там, где это уместно.
6. Поддерживать technical writing and documentation migration branch.
7. Сохранять human review и не выдумывать доказательства, опыт, кейсы или credentials.
8. Снижать ручную рутину на 70–80%, оставив Dmytro senior judgment.

---

## 3. Что система должна делать

### 3.1. Opportunity intake layer

Система должна принимать:

- Upwork job description;
- Fiverr/PPH buyer request;
- LinkedIn/direct lead;
- writing platform call for pitches;
- evaluator platform opportunity;
- B2B SaaS/legal-tech lead;
- client brief;
- existing website/app URL for safe testing;
- local demo app / benchmark task.

На входе система должна определить:

- source platform;
- task domain;
- role type;
- required tools;
- commercial fit;
- support level;
- evidence required;
- risk flags;
- recommended action.

### 3.2. Upwork / sales layer

Для Upwork система должна выдавать:

- `fit_decision.md`;
- `proposal.md`;
- `screening_answers.md`;
- `commercial_strategy.md`;
- `client_questions.md`;
- `red_flags.md`;
- `evidence_needed.md`;
- `skip_reason.md` если лучше не подаваться.

Важно: многие реальные Upwork jobs содержат screening questions. Система должна отвечать на них отдельно, а не смешивать с proposal.

### 3.3. Multi-platform sales layer

Для разных платформ система должна генерировать разные output packs:

#### Upwork

```text
proposal.md
screening_answers.md
commercial_strategy.md
fit_decision.md
red_flags.md
evidence_needed.md
```

#### Fiverr / PeoplePerHour

```text
gig_title.md
gig_description.md
package_tiers.md
faq.md
buyer_requirements.md
delivery_scope.md
```

#### Writing platforms: nDash, Draft.dev, Airbyte, TestMu, DO Ripple

```text
pitch.md
article_outline.md
sample_angle.md
editor_questions.md
ai_policy_warning.md
source_checklist.md
```

#### Direct B2B / legal-tech

```text
cold_dm.md
one_page_offer.md
whitepaper_angle.md
credibility_pack.md
follow_up.md
```

#### AI evaluator platforms

```text
platform_fit.md
profile_answers.md
assessment_prep.md
ai_usage_warning.md
```

The system must not perform paid AI evaluation tasks with AI. It may only help prepare profiles, organize experience, and understand platform rules.

---

## 4. QA planning layer

Система должна принимать client brief / requirements и выдавать:

- QA audit plan;
- risk-based test plan;
- critical flows;
- manual exploratory checklist;
- automation candidates;
- API / DB / performance / accessibility notes;
- SaaS multi-tenant testing strategy;
- billing / Stripe / role / auth testing strategy;
- PWA/offline testing strategy;
- mobile release QA strategy;
- first milestone recommendation.

---

## 5. Automation layer

Default strongest execution stack:

> **Playwright + TypeScript**

Система должна генерировать:

- `package.json`;
- `playwright.config.ts`;
- `.env.example`;
- Page Objects;
- fixtures;
- UI smoke tests;
- API smoke tests;
- a11y smoke example;
- GitHub Actions workflow;
- README для клиента;
- Architecture Notes.

Важно: LLM не должен напрямую писать весь `.spec.ts` как свободный текст. Лучше использовать **deterministic scaffold + LLM notes separately**.

---

## 6. Review layer

Система должна проверять outputs на:

- flaky locators;
- hard waits;
- missing assertions;
- shared state;
- poor test data strategy;
- unsafe assumptions;
- overpromising in proposals;
- generic proposal language;
- unanswered screening questions;
- fake evidence / invented examples;
- risky security wording;
- underpricing / budget mismatch;
- unclear delivery.

---

## 7. Delivery layer

Система должна готовить:

- delivery note;
- summary of work;
- bug report pack;
- limitations;
- what requires human verification;
- next recommended step;
- possible upsell;
- Loom / screenshot / trace artifact checklist;
- client-friendly “fix these first” summary.

---

## 8. Human-readable reporting and dialog layer

### 8.1. Why this layer is critical

The system must not only produce files. It must be easy for Dmytro to understand:

- what the system decided;
- why it decided it;
- what needs human review;
- what is ready to send;
- what is blocked;
- what evidence is missing;
- what should be done next.

Therefore, every run should produce both:

1. **human-readable reports** for decision-making;
2. **machine-readable logs/state** for debugging and future automation.

### 8.2. Human-readable output pack

Each project/opportunity should produce a clear top-level pack:

```text
READ_ME_FIRST.md
SUMMARY.md
DECISION.md
NEXT_ACTIONS.md
HUMAN_REVIEW_REQUIRED.md
QUALITY_GATE_REPORT.md
```

For Upwork/opportunity mode:

```text
fit_decision.md
proposal.md
screening_answers.md
commercial_strategy.md
client_questions.md
red_flags.md
evidence_needed.md
skip_reason.md
```

For QA delivery mode:

```text
qa_plan.md
bug_report_template.md
test_strategy.md
automation_candidates.md
delivery_note.md
```

For writing mode:

```text
pitch.md
article_outline.md
documentation_plan.md
sample_rewrite.md
ai_policy_warning.md
```

### 8.3. READ_ME_FIRST.md structure

Every run should create a short human-readable control page:

```text
# Read Me First

Decision:
- strong_apply / apply_selectively / skip / advisory_only / adjacent_opportunity

Why:
- 3–5 bullet points

Main risks:
- budget
- missing evidence
- wrong stack
- risky task
- policy issue

What to review before sending:
- proposal
- screening answers
- evidence
- pricing
- claims

Next action:
- send proposal
- edit with real evidence
- skip
- ask clarification
- create audit-first offer
```

### 8.4. Dialog modes

The system should support three practical dialog interfaces.

#### A. Inline feedback in `--step` mode

After each agent, Dmytro can say:

```text
redo: make it shorter, more senior, add SaaS billing angle
```

The agent regenerates using previous output + feedback.

#### B. Triggered pre-run prompts

Before workflow starts, the system asks only when a risk trigger appears:

- Stripe / billing / payment;
- production environment;
- crypto / ID / deposit;
- mobile device requirement;
- Tosca / uncommon tool;
- NDA / client evidence requirement;
- urgent / ASAP;
- low-budget mismatch.

Example:

```text
Payment flow detected.
Question: Is this sandbox/test mode only?
```

Answers are saved to state and used by later agents.

#### C. Post-run Q&A

Command:

```bash
python main.py ask --project-id <id>
```

Purpose:

- ask why a decision was made;
- generate alternative proposal angle;
- prepare for client call;
- ask what evidence is missing;
- ask how to improve next run.

### 8.5. Technical logs

Machine-readable artifacts:

```text
state.json
.snapshots/state_after_<agent>.json
logs/factory.jsonl
```

Structured logs should contain:

- workflow start/end;
- agent start/end;
- model alias;
- model name;
- fallback usage;
- duration;
- output keys;
- tokens/cost when available.

Human-readable markdown remains primary for daily use. JSON logs are for debugging, analytics and future automation.

---

## 9. Что система НЕ должна делать сейчас

Сейчас система не должна:

- отправлять messages клиентам автоматически;
- auto-submit proposals;
- scrape Upwork aggressively;
- делать GitHub auto-push;
- выполнять произвольные shell commands;
- обещать bug-free / 100% coverage;
- работать без human review;
- притворяться экспертом в Tosca / mobile / security / compliance без реального подтверждения;
- выдумывать bug reports, Loom videos, portfolio samples, devices, credentials, published articles;
- выполнять AI evaluator paid tasks с помощью AI;
- строить универсальную QA-платформу уровня TestRail / Xray / Zephyr;
- уходить в LangGraph/RAG/Web UI до проверки пользы на реальных задачах.

---

## 10. Основной позиционирующий фокус

AI QA Factory should be broad in intelligence, but focused in honest execution.

Core principle:

> **Broad intelligence. Focused execution. Honest routing.**

### Strong execution zone

- Playwright + TypeScript;
- Web QA;
- SaaS QA audits;
- multi-tenant / billing / auth QA;
- API testing;
- manual exploratory QA;
- bug reports with Loom/Linear style;
- flaky test stabilization;
- Selenium → Playwright migration;
- AI-generated MVP testing;
- CI/CD feedback and reporting;
- technical QA writing.

### Supported / partial execution zone

- Next.js / React app QA;
- PWA/offline testing strategy;
- Stripe/billing flow testing;
- role/session/auth boundary testing;
- React Native release QA;
- Maestro mobile tests;
- UX walkthrough testing;
- technical documentation migration;
- AI workflow opportunity analysis.

### Advisory-only zone

- Tosca / Tricentis;
- Sharetribe Flex;
- deep performance/load testing;
- formal security testing;
- compliance testing;
- POS hardware;
- native mobile if no device access;
- QuickBooks/accounting integrations.

### Skip / risk zone

- crypto app tests requiring deposit/ID;
- $5 usability tasks;
- pure full-stack developer jobs outside QA positioning;
- underpriced RAG/chatbot builds;
- tasks requiring fake experience;
- anything that violates platform rules.

---

## 11. Architecture principles

### 11.1. Human-in-the-loop

Every client-facing output is a draft.

Mandatory file:

```text
HUMAN_REVIEW_REQUIRED.md
```

It must list what to verify before sending:

- business logic;
- assumptions;
- selectors;
- test data;
- credentials;
- payment/security flows;
- tone and promises;
- evidence;
- scope alignment;
- required screening keywords;
- pricing.

### 11.2. Dry-run / mock mode

The system must work without API keys.

But mock mode must not be used for real client-facing proposals.

Required guard:

```bash
python main.py upwork --input real_job.txt --require-real-llm
```

If `LLM_MODE=mock`, the system must stop and warn.

### 11.3. Deterministic scaffold + LLM notes

Framework structure must be deterministic and valid.

LLM may generate:

- architecture notes;
- recommended flows;
- locator strategy;
- risk notes;
- TODOs.

Core scaffold should remain deterministic templates.

### 11.4. Safety first

`SafeCodeExecutor` must allow only allowlisted commands.

Forbidden:

- `shell=True`;
- arbitrary command execution;
- dangerous npm scripts;
- writing outside project directory;
- path traversal.

### 11.5. Registry-based workflows

Workflow must not grow into huge `if/elif`.

Use:

```text
core/workflow_registry.py
core/agent_registry.py
```

New workflow = registry entry.  
New agent = file/class + registry entry.

### 11.6. Prompt profiles in files

Prompts must not be hardcoded only in Python.

Required structure:

```text
prompts/
  proposal/
  qa_plan/
  delivery/
  writing/
  platform/
  dynamic/
  screening/
```

Fallback chain:

```text
profile → fallback → default → empty
```

### 11.7. Persistence abstraction

v5.x should use JSON files, not a full database.

But architecture must include:

```text
core/persistence.py
JSONFilePersistence
PERSISTENCE_BACKEND=json
```

Future SQLite is acceptable if JSON becomes slow, but not needed now.

### 11.8. Platform profiles

Add:

```text
platforms/
  upwork.yaml
  fiverr.yaml
  peopleperhour.yaml
  contra.yaml
  linkedin_direct.yaml
  ndash.yaml
  draft_dev.yaml
  airbyte.yaml
  testmu.yaml
  legal_tech_direct.yaml
  evaluator_platforms.yaml
  gumroad.yaml
```

Each profile stores:

- platform name;
- allowed output packs;
- tone;
- pricing style;
- evidence requirements;
- AI policy;
- payment notes;
- risk rules;
- recommended offers.

### 11.9. Capability profiles

Add:

```text
capabilities/
  playwright_ts.yaml
  manual_exploratory_qa.yaml
  api_testing.yaml
  nextjs_qa.yaml
  saas_multi_tenant_billing_auth.yaml
  react_native_mobile_qa.yaml
  maestro.yaml
  tosca_advisory.yaml
  technical_writing.yaml
  documentation_migration.yaml
  ai_automation_adjacent.yaml
  ux_walkthrough.yaml
  security_responsible_discovery.yaml
```

Each capability profile stores:

- support level;
- keywords;
- strong signals;
- risk signals;
- allowed claims;
- forbidden claims;
- proposal angle;
- questions to ask;
- recommended outputs.

---

## 12. Core components

### 12.1. CLI entrypoint

File:

```text
main.py
```

Core commands:

```bash
python main.py upwork --input real_jobs/job_001.txt --require-real-llm
python main.py filter --input real_jobs/job_001.txt
python main.py batch-filter --input real_jobs/
python main.py scaffold --input sample_inputs/client_brief.txt
python main.py full --input sample_inputs/client_brief.txt
python main.py review --input sample_inputs/test_to_review.ts
python main.py ask --project-id <id>
python main.py capabilities
python main.py agents --input sample_inputs/client_brief.txt
python main.py run-tests --project-path outputs/<project_id>/framework
```

Execution modes:

```bash
--auto
--step
--dry-run
--from-step <agent>
--only <agent>
--allow-mock
--require-real-llm
```

### 12.2. State model

File:

```text
core/state.py
```

Must include:

- project_id;
- schema_version;
- mode;
- source_platform;
- opportunity_type;
- task_domain;
- role_type;
- raw_input;
- project_type;
- stack_choice;
- prompt_profile;
- capability_profile;
- platform_profile;
- support_level;
- fit_score;
- recommended_action;
- risk_flags;
- red_flags;
- clarifications;
- detected_technologies;
- required_tools;
- automation_scope;
- commercial_strategy;
- pricing_notes;
- evidence_required;
- missing_evidence;
- suggested_specialists;
- generated_outputs;
- approval_status;
- triggered_prompts_answers;
- execution_mode;
- state_snapshots_path;
- logs.

### 12.3. PlatformRouterAgent

Determines:

- source platform;
- platform-specific output pack;
- AI policy;
- tone;
- evidence requirements;
- pricing mode.

### 12.4. CapabilityRouterAgent

Determines:

- task domain;
- primary stack;
- support level;
- whether Dmytro can realistically apply;
- missing capabilities;
- safe positioning angle.

### 12.5. OpportunityFilterAgent

Determines:

```text
strong_apply
apply_selectively
apply_only_with_narrow_scope
audit_first
advisory_only
adjacent_opportunity
skip_low_budget
skip_not_core
skip_risky
skip_policy_risk
```

### 12.6. ScreeningAnswersAgent

Generates:

```text
screening_answers.md
```

Must handle:

- required opening keyword;
- exact client questions;
- evidence warnings;
- “do not invent” rules;
- user-provided real examples.

### 12.7. EvidencePackAgent

Generates:

```text
evidence_needed.md
```

Maintains optional structure:

```text
evidence_pack/
  bug_report_examples/
  loom_examples/
  qa_audit_samples/
  playwright_samples/
  linear_ticket_examples/
  mobile_testing_devices.md
  ai_tools_workflow.md
  documentation_samples/
  writing_clips/
```

The agent must never invent evidence.

### 12.8. CommercialStrategyAgent

This replaces the narrow idea of “PricingAdvisor”.

It does not decide final price.

It outputs:

- commercial fit;
- budget fit;
- rate pressure;
- first milestone strategy;
- safe price range;
- do-not-quote warning;
- proposal pricing angle;
- skip reason if any.

### 12.9. TechnicalWritingAgent

Supports adjacent writing opportunities:

- B2B SaaS docs;
- QA/devtools writing;
- help center migration;
- API/setup docs;
- release notes;
- technical documentation audit;
- documentation migration;
- legal-tech whitepapers.

Outputs:

```text
technical_writing_assessment.md
documentation_plan.md
sample_doc_rewrite.md
pitch.md
screening_answers.md
evidence_needed.md
```

### 12.10. QualityGate

Checks:

- generic proposal phrases;
- missing client questions;
- missing screening answers;
- missing required keyword;
- mock-mode warning;
- `waitForTimeout`;
- brittle selectors;
- hardcoded credentials;
- overclaims;
- invented evidence;
- deposit/ID risk;
- developer-only mismatch;
- low-budget mismatch;
- aggressive security language;
- missing human review note.

Output:

```text
QUALITY_GATE_REPORT.md
```

---

## 13. Agent model

### 13.1. Core agents for v5.0.3+

- `PlatformRouterAgent`
- `CapabilityRouterAgent`
- `OpportunityFilterAgent`
- `JobAnalyzerAgent`
- `StackRouterAgent`
- `ScreeningAnswersAgent`
- `EvidencePackAgent`
- `ProposalWriterAgent`
- `CommercialStrategyAgent`
- `QAPlannerAgent`
- `PlaywrightGeneratorAgent`
- `APITestGeneratorAgent`
- `FlakinessCriticAgent`
- `TechnicalWritingAgent`
- `DeliveryWriterAgent`
- `DynamicAgentFactory`
- `QualityGate`

### 13.2. Specialist / advisory agents

- `PaymentFlowSpecialist`
- `MobileTestingAdvisor`
- `ReactNativeMaestroAdvisor`
- `ToscaAdvisoryAgent`
- `NextJsQAAdvisor`
- `PwaOfflineTestingAdvisor`
- `ComplianceReviewer`
- `HealthcareReviewer`
- `SeleniumMigrationExpert`
- `AccessibilityReviewer`
- `PerformanceSmokeAdvisor`
- `SecurityChecklistAdvisor`
- `LegalTechQAReviewer`
- `DocumentationMigrationAdvisor`
- `AIWorkflowAutomationAdvisor`

---

## 14. Capability Matrix

| Area | Support level | Expected output |
|---|---:|---|
| Upwork QA proposals | Strong | proposal + screening + fit + commercial strategy |
| Web UI automation | Strong | Playwright scaffold |
| Manual exploratory QA | Strong | test plan + bug report pack |
| SaaS multi-tenant/billing/auth | Strong | risk audit plan + evidence pack |
| API testing | Good/Strong | API smoke notes + starter tests |
| Flaky regression automation | Strong | fix strategy + tests |
| Selenium → Playwright | Strong | migration plan + proposal |
| Technical QA writing | Strong adjacent | pitch + outline |
| Documentation migration | Strong adjacent | documentation plan + sample rewrite |
| Next.js / React QA | Supported | QA strategy + Playwright angle |
| PWA/offline testing | Supported | advisory checklist |
| React Native / Maestro | Conditional | mobile QA strategy + evidence required |
| UX walkthrough testing | Supported | recorded walkthrough plan |
| Tosca / Tricentis | Advisory only | opportunity analysis + caution |
| Sharetribe Flex | Advisory only | not-core warning |
| Deep performance | Advisory | k6/perf smoke plan only |
| Formal security testing | Advisory / caution | responsible discovery checklist |
| Compliance testing | Advisory | risk checklist |
| AI automation / n8n | Adjacent | opportunity analysis / pitch |
| AI evaluator platforms | Advisor only | profile prep, no task execution |
| Crypto deposit/ID testing | Skip/risk | skip reason |
| Full autonomy | Not supported | human review required |

---

## 15. Upwork Market Benchmark Pack

### 15.1. Purpose

Before real client usage, the system must be validated against representative real Upwork jobs.

Goal:

- classify opportunities correctly;
- detect strong fit vs low fit;
- generate non-generic proposals;
- answer screening questions;
- recommend safe commercial strategy;
- identify red flags;
- avoid overpromising;
- distinguish QA, writing, dev-only, mobile, advisory and skip jobs.

### 15.2. Benchmark categories

Use at least:

```text
1. AI-native exploratory QA / multi-app retail platform
2. SaaS multi-tenant onboarding + billing audit
3. Failing regression tests automation
4. React Native release QA with Maestro
5. UX/product walkthrough with recordings
6. Technical documentation migration
7. AI automation adjacent project
8. Low-value usability test
9. Crypto/deposit risky test
10. Developer-only full-stack role
11. Tosca-only automation role
12. Frontend precision UX/animation project
```

### 15.3. Benchmark scoring rubric

Each output is scored manually:

| Criterion | Score 1–5 |
|---|---:|
| Correct classification | 1–5 |
| Fit/skip decision quality | 1–5 |
| Proposal specificity | 1–5 |
| Screening answer quality | 1–5 |
| Commercial strategy realism | 1–5 |
| Risk detection | 1–5 |
| QA approach relevance | 1–5 |
| Evidence handling honesty | 1–5 |
| Tone and seniority | 1–5 |
| Edit distance before sending | 1–5 |

Target before real usage:

```text
Average score >= 4.0 across 10 representative jobs
No critical failure on mandatory keywords, invented evidence, risky/security wording, or skip decisions
```

---

## 16. Multi-platform opportunity router

AI QA Factory must not be limited to Upwork.

Supported sources from Income Map:

- Upwork and direct QA proposals;
- Fiverr / PeoplePerHour microservices;
- Contra / LinkedIn direct leads;
- Paid QA / DevTools writing platforms;
- B2B legal-tech whitepaper leads;
- AI evaluator platforms;
- Later: templates, workshops, Gumroad/Substack.

The system should classify each opportunity by:

- source platform;
- opportunity type;
- support level;
- commercial priority;
- required output pack;
- evidence required;
- AI policy / platform restrictions;
- recommended action.

Recommended actions:

```text
strong_apply
apply_selectively
create_pitch
create_gig
prepare_profile
direct_dm
save_for_later
skip_low_value
skip_risky
skip_policy_risk
```

The system must not scrape platforms aggressively or auto-submit applications. It should analyze opportunities provided manually, through saved searches, email alerts, exports, or user-provided text.

---

## 17. Technical writing branch

Technical writing is an adjacent but important capability.

Supported areas:

- QA/devtools articles;
- B2B SaaS documentation;
- help center migration;
- API/setup docs;
- release notes;
- user guides;
- troubleshooting guides;
- documentation audits;
- legal-tech / AI quality whitepapers.

TechnicalWritingAgent must not position Dmytro as a generic copywriter. It should position him as:

```text
QA/SDET + SaaS + AI-assisted technical documentation specialist
```

Allowed claims:

- AI-assisted technical documentation;
- SaaS/QA documentation clarity;
- structured docs migration;
- user-focused technical writing;
- QA/devtools writing.

Forbidden claims:

- native English copywriter unless verified;
- legal/compliance documentation expert unless scope fits actual experience;
- deep domain expert in unknown product;
- published clip if not real.

---

## 18. Practical website / app validation strategy

After text/job calibration, the system should be tested against safe websites or controlled demo apps.

### A. Local benchmark playground

Build a small local app with seeded bugs:

```text
multi-tenant data leakage
role enforcement bypass
Stripe mock checkout
PWA offline sync bug
flaky UI timing issue
timezone/date bug
checkout validation issue
API error handling bug
mobile layout issue
```

### B. Public demo apps

Use public demo/testing sites for:

- login flow;
- forms;
- tables;
- checkout demo;
- API mock;
- UI regression;
- accessibility smoke.

### C. Real sites with own credentials

Allowed only when:

```text
account belongs to Dmytro
no destructive actions
no real payments
credentials only in .env
no scraping or abuse
terms of use respected
```

---

## 19. Roadmap

### v5.0.2 Foundation — current/pre-calibration base

Already includes:

- registry architecture;
- prompt loader;
- persistence abstraction;
- structured logging;
- snapshots;
- execution modes;
- mock guard;
- QualityGate;
- triggered prompts;
- Playwright scaffold;
- basic opportunity outputs.

### v5.0.3 — Capability Router + Market Calibration

Add:

- PlatformRouterAgent;
- CapabilityRouterAgent;
- OpportunityFilterAgent;
- ScreeningAnswersAgent;
- EvidencePackAgent;
- CommercialStrategyAgent;
- TechnicalWritingAgent;
- platform profiles;
- capability profiles;
- batch-filter mode;
- benchmark scoring;
- Upwork-specific QualityGate checks.

### v5.0.4 — Practical QA Validation

Add:

- local benchmark app;
- seeded-bug playground;
- safe demo-site validation;
- sample bug reports;
- artifact pack validation;
- improved human-readable reports.

### v5.1 — Post-run Q&A and memory hardening

Add:

- full REPL `ask`;
- better project memory;
- reusable evidence pack;
- proposal history;
- successful pattern storage.

### v5.2 — Playwright MCP / visual recon

Add:

- browser snapshot workflow;
- locator extraction;
- UI structure analysis;
- generated test suggestions from actual UI;
- recon screenshots.

### v5.3 — Client/project memory

Add:

- per-client profiles;
- pricing history;
- successful patterns;
- client-specific reusable domain knowledge.

### v6.0 — UI / RAG / advanced orchestration

Only after CLI proves useful on real opportunities.

Potential additions:

- web UI;
- dashboard;
- RAG over project history;
- Telegram/Slack interface;
- LangGraph only if justified;
- GitHub integration with human approval.

---

## 20. Acceptance criteria

### 20.1. Existing functional tests

```bash
python -m pytest -q
python main.py upwork --input sample_inputs/upwork_job.txt
python main.py scaffold --input sample_inputs/client_brief.txt
python main.py full --input sample_inputs/client_brief.txt
python main.py review --input sample_inputs/test_to_review.ts
python main.py capabilities
```

### 20.2. Execution modes

```bash
python main.py full --input sample_inputs/client_brief.txt --step
python main.py full --input sample_inputs/client_brief.txt --dry-run
python main.py full --input sample_inputs/client_brief.txt --from-step proposal_writer
python main.py full --input sample_inputs/client_brief.txt --only proposal_writer
```

### 20.3. Market calibration acceptance

```bash
python main.py batch-filter --input real_jobs/
```

Expected:

- ranked shortlist;
- recommended action per job;
- skip reasons;
- commercial strategy;
- evidence requirements;
- screening questions detected.

### 20.4. Platform router acceptance

Given different inputs, system outputs correct packs:

- Upwork → proposal + screening;
- Fiverr → gig package;
- writing platform → pitch + outline;
- direct B2B → DM + one-page offer;
- evaluator → profile prep + AI policy warning.

### 20.5. Human-readable reporting acceptance

Every workflow must create:

```text
READ_ME_FIRST.md
SUMMARY.md
DECISION.md
NEXT_ACTIONS.md
HUMAN_REVIEW_REQUIRED.md
QUALITY_GATE_REPORT.md
```

### 20.6. Safety acceptance

System must not:

- invent evidence;
- claim unavailable tools/devices;
- auto-submit proposals;
- perform evaluator tasks;
- recommend risky crypto/deposit/ID jobs;
- suggest unauthorized testing;
- execute unsafe commands.

---

## 21. Practical usage workflow

### For batch opportunity filtering

1. Copy jobs into:

```text
real_jobs/
  job_001.txt
  job_002.txt
  job_003.txt
```

2. Run:

```bash
python main.py batch-filter --input real_jobs/
```

3. Review:

```text
upwork_shortlist.md
skip_reasons.md
proposal_priority_queue.md
```

### For one Upwork job

```bash
python main.py upwork --input real_jobs/job_001.txt --require-real-llm
```

Review:

```text
READ_ME_FIRST.md
fit_decision.md
proposal.md
screening_answers.md
commercial_strategy.md
evidence_needed.md
QUALITY_GATE_REPORT.md
```

### For technical writing opportunity

```bash
python main.py opportunity --platform draft_dev --input writing_jobs/job_001.txt
```

Review:

```text
pitch.md
article_outline.md
sample_angle.md
ai_policy_warning.md
```

### For Fiverr/PPH gig creation

```bash
python main.py gig --platform fiverr --offer playwright_audit
```

Review:

```text
gig_title.md
gig_description.md
package_tiers.md
faq.md
buyer_requirements.md
```

---

## 22. Strategic decision rules

Before adding a feature, ask:

1. Does this help win or deliver paid work in the next 2–4 weeks?
2. Does this improve QA/SDET/SaaS/AI-assisted positioning?
3. Does this reduce repeated manual work?
4. Does this preserve human review?
5. Can it be added modularly?
6. Does it avoid false claims and fake evidence?
7. Does it respect platform policies?

If no, postpone.

---

## 23. Final principle

The system should grow from real opportunities, not from architectural imagination.

But the architecture must allow growth from the beginning.

Core idea:

> Build a focused, powerful AI-assisted opportunity and QA operating system for one Senior SDET business — not a generic platform for everyone.

Final operating philosophy:

```text
Broad intelligence.
Focused execution.
Honest routing.
Human-readable reporting.
Senior QA decides.
```

---

## 20. Pre-screening & Execution Cockpit

### 20.1. Why this layer exists

AI QA Factory must be able to act as a practical pre-screening and execution cockpit before Dmytro spends Connects, accepts a task, runs tests, or sends anything to a client.

The system should answer five questions before execution:

1. Is this opportunity suitable for Dmytro?
2. Can Factory support it fully, partially, advisory-only, or not at all?
3. What is the approximate effort / timebox?
4. What inputs, accounts, credentials, devices, APIs or evidence are missing?
5. Which workflow should run next, and where does Dmytro need to approve?

This turns Factory from a generator into a decision-support and delivery-control system.

### 20.2. Input types

The system should support these intake types:

| Input type | Current handling | Future handling |
|---|---|---|
| Pasted job text | Fully supported | Keep as main reliable path |
| Link to job/platform | Store as reference; user should paste relevant text | URL fetch adapter may be added later |
| Screenshots | User should summarize/paste text for now | Vision/OCR adapter later via `VISION_MODEL` |
| Client brief | Supported | Expand with structured intake templates |
| Real website/app URL | Supported only as context until access/scope confirmed | Playwright MCP/recon workflow later |
| Repository/code | Supported as manual brief now | GitHub adapter later |

The system must not treat a URL or screenshot alone as enough to accept a fixed client commitment.

### 20.3. New agents

#### PreScreeningAgent

Creates:

```text
PRESCREENING_REPORT.md
```

It should include:

- system suitability;
- recommended workflow;
- rough effort/timebox;
- realistic scope;
- blockers;
- required inputs;
- approval checkpoints;
- what Factory can do;
- what Factory must not do.

#### ExecutionCockpitAgent

Creates:

```text
EXECUTION_FLOW.md
APPROVAL_CHECKPOINTS.md
SYSTEM_DIALOG_GUIDE.md
TESTING_READINESS_CHECKLIST.md
PROJECT_INTAKE_CHECKLIST.md
```

This is the human-friendly control layer for running a project step by step.

### 20.4. Suitability categories

Pre-screening should classify the opportunity into one of these categories:

```text
strong_for_prescreen_and_audit_planning
strong_for_prescreen_release_qa_and_bug_reporting
strong_for_repro_and_regression_test_planning
strong_adjacent_for_docs_pitch_and_plan
conditional_if_device_tooling_available
advisory_only_unless_real_experience_confirmed
partial_adjacent_prescreen_only_until_scope_confirmed
not_suitable_for_execution
manual_review_required
```

The output must be honest. If a task is Tosca-heavy, developer-only, risky, too low value, or requires devices/tools Dmytro does not have, Factory should say so.

### 20.5. Effort/timebox estimates

The system should provide rough effort bands, not fake precision.

Examples:

| Task type | Rough estimate |
|---|---:|
| SaaS multi-tenant billing/auth audit | Trial: 1 hour; full audit: 8–12 hours over 3–5 working days |
| AI-native exploratory QA release pass | 4–10 hours initial pass; ongoing hourly if accepted |
| One recurring bug / failing regression test | 2–5 hours starter scope |
| Technical writing sample rewrite/audit | 1–3 hours; full migration depends on volume |
| React Native release QA | 3–6 hours if tooling/devices are ready |
| Tosca implementation | No estimate unless real Tosca capability is confirmed |
| Risky deposit/ID/crypto test | Skip; do not estimate execution |

### 20.6. Human-friendly output pack

Every opportunity run should create a top-level control pack:

```text
READ_ME_FIRST.md
PRESCREENING_REPORT.md
DECISION.md
NEXT_ACTIONS.md
EXECUTION_FLOW.md
APPROVAL_CHECKPOINTS.md
SYSTEM_DIALOG_GUIDE.md
TESTING_READINESS_CHECKLIST.md
PROJECT_INTAKE_CHECKLIST.md
HUMAN_REVIEW_REQUIRED.md
QUALITY_GATE_REPORT.md
```

`READ_ME_FIRST.md` is the first file Dmytro opens. It should explain the decision, suitability, estimated effort, next action and what to review first.

### 20.7. Approval checkpoints

Factory may run semi-automatically, but these decisions are human-owned:

1. Approve spending Connects or replying to the client.
2. Approve the proposed scope and first milestone.
3. Approve real-site testing boundaries and credentials handling.
4. Approve generated proposal/screening answers before sending.
5. Approve generated tests/reports before client delivery.

Stop conditions:

- client asks for real payment/deposit/ID;
- task requires unauthorized access or exploitation;
- evidence would need to be invented;
- task is outside verified capability;
- budget/time is incompatible with strategic value.

---

## 21. Real Testing Readiness

### 21.1. Required for real LLM usage

Before using Factory for client-facing outputs:

```text
.env configured
real LLM provider key available
ARCHITECT_MODEL / FAST_MODEL / REVIEW_MODEL / CODING_MODEL set
--require-real-llm works without mock mode
```

Recommended providers:

- OpenAI-compatible model through LiteLLM;
- Anthropic/Claude through LiteLLM if configured;
- separate aliases for fast/proposal/review/coding when possible.

### 21.2. Required for real website/app testing

For actual websites/apps prepare:

```text
target URL(s)
staging/test environment if available
test accounts and roles
approved scope and boundaries
browser/device matrix
critical flows
reporting format
safe test data
credentials in .env only
```

Never put real credentials into prompts, job files, reports, or screenshots.

### 21.3. Optional tools/API by project type

| Project type | Useful tools / access |
|---|---|
| Web QA / Playwright | Node.js, Playwright browsers, staging URL, test accounts |
| API testing | Postman collection / OpenAPI / test tokens |
| SaaS billing | Stripe test mode/sandbox, test plans, invoices/roles brief |
| Linear/Jira bug reporting | Linear/Jira account/API token if direct ticket creation is desired |
| Loom/Jam reporting | Loom/Jam account, screen recording permission |
| React Native / mobile | Mac, Xcode, Android Studio, TestFlight, Google Play Internal Testing, Maestro |
| Repository analysis | GitHub access/token, branch/PR rules |
| Documentation/writing | source docs, target audience, AI policy, style guide, sample requirements |

### 21.4. Safe real-site policy

Allowed:

- testing your own accounts;
- testing client-provided test accounts;
- non-destructive checks;
- staging/sandbox flows;
- read-only production checks if explicitly approved.

Not allowed:

- unauthorized security testing;
- scraping/abuse;
- destructive actions;
- real payments unless explicitly part of a controlled test with reimbursement/approval;
- storing secrets in generated artifacts;
- testing platforms in ways that violate their rules.

### 21.5. When to start real testing

Start real testing only after:

1. v5.0.4 pre-screening artifacts are generated correctly;
2. one or two real LLM runs produce useful proposal/screening outputs;
3. test accounts/scope are clear;
4. Dmytro confirms the opportunity is worth pursuing.

Until then, use controlled benchmark tasks and safe demo apps.

---

## 22. v5.0.4 Execution Cockpit acceptance criteria

```bash
python main.py prescreen --input sample_inputs/upwork_job_saas_multitenant_billing.txt --allow-mock
python main.py upwork --input sample_inputs/upwork_job_greenhouse_ai_native_qa.txt --allow-mock
python main.py batch-filter --input sample_inputs --allow-mock
python main.py ask --project-id <project_id> --question "What should I review first?"
python -m pytest -q
```

Expected:

- `PRESCREENING_REPORT.md` created;
- `EXECUTION_FLOW.md` created;
- `APPROVAL_CHECKPOINTS.md` created;
- `SYSTEM_DIALOG_GUIDE.md` created;
- `TESTING_READINESS_CHECKLIST.md` created;
- `PROJECT_INTAKE_CHECKLIST.md` created;
- `READ_ME_FIRST.md` shows decision, suitability and estimated effort;
- no client-facing output is marked safe without human review;
- pytest passes.

---

## 24. v5.0.7 — Project Extension Packs, Self-Health and Test Design

### 24.1. Why this layer exists

AI QA Factory must be able to adapt to concrete opportunities without becoming a chaotic universal platform.

Some opportunities will require temporary or project-specific support:

- Tosca terminology and advisory questions;
- React Native / Maestro release testing;
- Sharetribe marketplace flow analysis;
- Stripe / billing-specific checks;
- multi-tenant data-isolation checks;
- technical documentation and help-center migration;
- test strategy / test plan / test case generation;
- AI automation / n8n / Make.com workflow analysis.

The system should support these cases through **extension packs**, not through uncontrolled permanent feature growth.

Core rule:

> Temporary project support is allowed. Permanent capability growth requires repeated real-world value.

---

### 24.2. Project Extension Packs

A project extension pack is a temporary, approval-based bundle that may contain:

- prompt profile;
- checklist;
- test-design template;
- domain-specific risk notes;
- advisory specialist suggestion;
- sample artifact structure;
- client questions;
- safe execution boundaries.

It must not claim that Dmytro has hands-on expertise in a tool unless that is true.

A new agent handles this:

```text
ProjectExtensionAgent
```

Output:

```text
PROJECT_EXTENSION_PLAN.md
```

The output should include:

- suggested packs;
- trigger keyword/domain;
- why the pack may be useful;
- whether approval is required;
- what can be generated;
- what must not be claimed or executed.

Examples of extension packs:

```text
tosca_advisory_pack
mobile_maestro_pack
react_native_release_pack
sharetribe_marketplace_pack
ai_automation_pack
technical_docs_pack
billing_risk_pack
tenant_isolation_pack
pwa_offline_pack
async_jobs_pack
bug_reporting_pack
test_design_pack
capability_gap_pack
```

---

### 24.3. Self-Health Monitoring

The system needs a basic self-health layer so that each run can say whether the generated output pack is internally consistent.

This is not autonomous self-healing.

The system may:

- detect missing outputs;
- detect decision/suitability conflicts;
- detect missing screening answers;
- detect missing evidence reports;
- detect unanswered safety prompts;
- detect unapproved extension packs;
- detect missing test-design artifacts where expected;
- create local placeholder reports;
- recommend which agent to re-run.

The system must not:

- auto-submit proposals;
- auto-push code;
- change client systems;
- run destructive commands;
- make payments;
- perform real security exploitation;
- invent evidence;
- silently repair client-facing artifacts without human approval.

Agent:

```text
SelfHealthMonitorAgent
```

Outputs:

```text
SELF_HEALTH_REPORT.md
SYSTEM_REPAIR_PLAN.md
```

Health statuses:

```text
healthy
review_recommended
needs_repair
```

---

### 24.4. Test Design Layer

The original `QAPlannerAgent` is useful but too broad. Real projects often require specific QA artifacts:

- test strategy;
- test plan;
- test cases;
- acceptance checklist;
- regression checklist;
- manual exploratory charters;
- automation candidates.

Therefore, v5.0.7 separates test design into dedicated agents:

```text
TestStrategyAgent      → TEST_STRATEGY.md
TestPlanWriterAgent    → TEST_PLAN.md
TestCaseWriterAgent    → TEST_CASES.md
```

These agents support:

- Upwork jobs asking for “approach to testing and improving QA”;
- documentation/testing jobs;
- client audit/discovery;
- SaaS onboarding/billing/auth testing;
- manual QA and exploratory tasks;
- conversion of requirements/Figma/briefs into practical test cases;
- preparation before automation.

They should generate drafts only. Dmytro must still review the scope, evidence, environment assumptions and client-facing wording.

---

### 24.5. New workflow

New mode:

```bash
python main.py test-design --input sample_inputs/client_brief.txt
```

Targeted regeneration:

```bash
python main.py test-design --input sample_inputs/client_brief.txt --only test_strategy
python main.py test-design --input sample_inputs/client_brief.txt --only test_plan_writer
python main.py test-design --input sample_inputs/client_brief.txt --only test_case_writer
```

This allows the system to produce or refresh specific test-design artifacts without rerunning the entire pipeline.

---

### 24.6. Human-friendly working model

The intended working style is:

```text
Opportunity / brief / task
  ↓
Pre-screening
  ↓
Capability + platform routing
  ↓
Project extension suggestions
  ↓
Human approval
  ↓
Test strategy / plan / cases / proposal / QA audit artifacts
  ↓
Self-health report
  ↓
Human review and final decision
```

The system should feel like a cockpit, not a black box.

It should always make clear:

- what it recommends;
- why it recommends it;
- what it can do;
- what it cannot do;
- what inputs are missing;
- which agent generated which artifact;
- where human approval is required;
- what should be re-run if something is weak.

---

### 24.7. Acceptance criteria for v5.0.7

```bash
python -m pytest -q
python main.py test-design --input sample_inputs/test_design_brief.txt --allow-mock
python main.py prescreen --input sample_inputs/upwork_job_saas_multitenant_billing.txt --allow-mock
python main.py full --input sample_inputs/client_brief.txt --allow-mock
```

Expected:

- tests pass;
- `PROJECT_EXTENSION_PLAN.md` created when project-specific packs are relevant;
- `SELF_HEALTH_REPORT.md` created;
- `SYSTEM_REPAIR_PLAN.md` created;
- `TEST_STRATEGY.md` created in test-design/full/plan workflows where appropriate;
- `TEST_PLAN.md` created in test-design/full/plan workflows where appropriate;
- `TEST_CASES.md` created in test-design/full/plan workflows where appropriate;
- no auto-submit / auto-push / destructive self-healing;
- all client-facing outputs remain drafts.

---

### 24.8. Practical boundary

v5.0.7 adds adaptability and safety, not full autonomy.

It is acceptable for the system to say:

```text
This project needs a temporary extension pack.
This capability is advisory only.
This task requires real evidence from Dmytro.
This workflow needs human approval before continuing.
This output pack is missing a required artifact.
Re-run only the TestCaseWriterAgent.
```

It is not acceptable for the system to silently claim unsupported expertise, auto-submit applications, execute risky real-site actions, or repair client-facing artifacts without approval.

Core principle remains:

> AI drafts. Senior QA decides.


---

## 24. v5.0.7 Code & Documentation Sync — Operating Model Lock

### 24.1. Purpose

v5.0.7 is a synchronization release. It does not change the fundamental architecture. It locks the current operating model into both code and documentation so that future work does not drift into random feature additions.

The current model is:

```text
pre-screen first
→ human-readable decision pack
→ approval checkpoints
→ selected workflow / agents
→ self-health report
→ repair plan if needed
→ final human review
```

The system must remain understandable from markdown outputs, not only from `state.json` or logs.

### 24.2. Pre-screening as the default entry point

For any uncertain job, platform task, direct lead, website request, screenshot-derived task, or client brief, the first command should be:

```bash
python main.py prescreen --input real_jobs/job_001.txt --source-platform upwork --allow-mock
```

The goal is to answer:

- Is this opportunity suitable for Dmytro?
- Is it suitable for Factory execution, partial support, advisory-only, or skip?
- What can realistically be done?
- What is the rough timebox or first milestone?
- Which inputs/access are missing?
- Which workflow should run next?
- Where does Dmytro need to approve before continuing?

### 24.3. Human-readable control pack

Every normal workflow should prioritize human-readable files:

```text
READ_ME_FIRST.md
PRESCREENING_REPORT.md
DECISION.md
NEXT_ACTIONS.md
APPROVAL_CHECKPOINTS.md
PROJECT_INTAKE_CHECKLIST.md
TESTING_READINESS_CHECKLIST.md
SELF_HEALTH_REPORT.md
SYSTEM_REPAIR_PLAN.md
QUALITY_GATE_REPORT.md
```

`READ_ME_FIRST.md` is the primary cockpit. If it does not clearly explain the decision and next step, the workflow is not yet human-friendly enough.

### 24.4. Approval checkpoints

Factory can run semi-automatically, but the following decisions remain human-owned:

- whether to spend Connects or reply;
- whether the scope and first milestone are acceptable;
- whether the proposal makes honest claims;
- whether evidence is real and available;
- whether real-site testing is allowed;
- how credentials are handled;
- whether final client-facing text can be sent;
- whether final delivery artifacts can be shared.

### 24.5. Real testing readiness

Before real website/app testing, the user must prepare:

- target URL;
- explicit testing permission or own account/test account;
- staging/test environment if possible;
- test users/roles;
- critical flows;
- browser/device matrix;
- reporting format;
- test data;
- payment sandbox if billing is involved;
- API docs/tokens if API testing is involved;
- timebox and delivery expectation.

Current reliable intake mode is text/brief-first. URLs and screenshots may be included as context, but URL-only and screenshot-only autonomous analysis are future adapters, not current production assumptions.

Future adapters:

```text
URLIntakeAdapter
ScreenshotIntakeAdapter
PlaywrightReconAgent
VisionReviewAgent
```

### 24.6. Self-health monitoring and safe repair

Self-health monitoring is a safe diagnostic layer, not an autonomous self-fixing system.

Allowed:

- detect missing outputs;
- detect inconsistent state;
- detect missing evidence;
- detect unanswered screening questions;
- detect missing test-design artifacts;
- suggest repair commands or next steps.

Not allowed:

- auto-submit proposals;
- auto-push code;
- modify client systems;
- run unauthorized tests;
- invent evidence;
- silently change client-facing claims.

### 24.7. Project-specific extension packs

The system must allow temporary/project-specific extension packs without turning every edge case into a permanent core module.

Examples:

```text
tosca_advisory_pack
mobile_maestro_pack
react_native_release_pack
sharetribe_marketplace_pack
ai_automation_pack
technical_docs_pack
billing_risk_pack
tenant_isolation_pack
pwa_offline_pack
bug_reporting_pack
test_design_pack
capability_gap_pack
```

These packs can suggest agents, prompts, checklists, risk notes and missing evidence. They should be activated only when useful for the project.

### 24.8. Current real-test sequence

Recommended sequence before real usage:

```bash
python main.py system-health
python main.py batch-filter --input real_jobs/ --allow-mock
python main.py prescreen --input real_jobs/job_001.txt --source-platform upwork --allow-mock
python main.py upwork --input real_jobs/job_001.txt --source-platform upwork --require-real-llm
```

Only after this should the system be evaluated for real client-facing use.

### 24.9. What remains intentionally later

The following are intentionally later-stage items:

- real URL/browser recon;
- screenshot-only intake;
- vision-based app review;
- full Playwright MCP workflow;
- UI dashboard;
- LangGraph/RAG;
- autonomous self-healing;
- auto-submission to platforms.

The next bottleneck is not architecture. The next bottleneck is real LLM output quality and market calibration on representative opportunities.


---

## 25. v5.0.8 Model Routing Profiles — Role-Based LLM Configuration

AI QA Factory does not use one model for every task. The system uses an LLM Router with role-based aliases so each type of work can be sent to the most appropriate model.

### 25.1. Role aliases

| Alias | Purpose | Recommended premium model |
|---|---|---|
| `architect` | pre-screening, opportunity routing, capability decisions, test strategy, complex reasoning | `gpt-5.5` |
| `coding` | Playwright scaffold notes, implementation planning, generated test architecture | `anthropic/claude-sonnet-4-6` |
| `review` | Quality Gate, self-health, deep review, difficult risk analysis | `anthropic/claude-opus-4-7` |
| `fast` | proposals, summaries, delivery notes, fast documentation drafts | `anthropic/claude-sonnet-4-6` |
| `vision` | future screenshot and visual recon workflows | `gpt-5.5` |
| `fallback` | backup model if the primary route fails | `gpt-5.4-mini` |

### 25.2. Recommended profile

The preferred real-testing profile is:

```env
LLM_MODE=real
MODEL_PROFILE=premium_hybrid
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

This profile maps roles to models as follows:

```env
ARCHITECT_MODEL=gpt-5.5
CODING_MODEL=anthropic/claude-sonnet-4-6
REVIEW_MODEL=anthropic/claude-opus-4-7
FAST_MODEL=anthropic/claude-sonnet-4-6
VISION_MODEL=gpt-5.5
FALLBACK_MODEL=gpt-5.4-mini
```

### 25.3. Effort settings

Each role may have an effort level:

```env
ARCHITECT_EFFORT=high
CODING_EFFORT=medium
REVIEW_EFFORT=xhigh
FAST_EFFORT=low
VISION_EFFORT=high
FALLBACK_EFFORT=low
```

The system should log model alias, model name, fallback status, token usage, cost if available, and reasoning/adaptive effort for each LLM-backed agent call.

### 25.4. Alternate profiles

The codebase supports multiple model profiles:

- `mock` — safe local mode, no paid API calls.
- `premium_hybrid` — GPT-5.5 + Claude Sonnet 4.6 + Claude Opus 4.7.
- `openai_only` — useful when only OpenAI API key is configured.
- `anthropic_only` — useful when only Anthropic API key is configured.
- `budget` — lower-cost calibration and batch filtering.

### 25.5. Safety rule

The system must never require a single expensive model for all tasks. Expensive/deep models are reserved for reasoning and review. Fast or cheaper models handle proposals, summaries, routine drafts and fallback.

If a provider rejects optional effort parameters, the router should retry the same model without optional parameters before falling back.

