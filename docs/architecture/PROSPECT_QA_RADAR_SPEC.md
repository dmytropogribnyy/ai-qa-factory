# Prospect QA Radar / Super Scout
## Product & Architecture Specification v2.0

> **Status:** Approved target architecture specification
> **Runtime status:** Partially implemented — a bounded local slice runs today; the full
> loop is not implemented.
> **Implemented today:** Phase 8.2 domain contracts; Prospect QA Scout v1.0.1 — bounded,
> read-only, local QA runtime (`python main.py scout`); Phase 8.4 — controlled discovery
> providers (deterministic fixture + file import), campaign builder/matrix with budgets,
> candidate normalization/dedup/suppression, cheap commercial triage, and bounded promotion
> into the Scout QA runtime, plus discovery dashboard views.
> **Not implemented (future-facing):** live third-party discovery at scale, browser execution
> against every candidate, company/site transactional memory database, public contact
> intelligence, disclosure manifests, automatic outreach, CAPTCHA solving, and authorized full
> E2E. These begin no earlier than Phases 8.5–8.9.
> **Source of truth for:** Prospect QA Radar / Super Scout domain architecture.
>
> This document describes the approved **target** architecture. Where it describes discovery,
> triage, scoring, or dashboards, treat it as the target; the **implemented** runtime is
> described in [SCOUT_RUNTIME_V1.md](SCOUT_RUNTIME_V1.md) and bounded by
> `docs/PHASE_CONTRACTS.md` (Phases 8.3–8.4). The phase map lives in
> `docs/PRODUCT_VISION_2026.md`. Contact intelligence, disclosure, and outreach in this spec
> are **not** implemented and remain gated to later, human-approved phases.

**Статус:** утверждённая продуктовая концепция для включения в ARK / AI QA Factory
**Дата:** 2026-07-16
**Назначение:** зафиксировать целевую архитектуру, UX, безопасность, evidence, discovery, приоритизацию, хранение и коммерческий workflow автономного QA-проспектинга.
**Главная цель:** превратить существующую AI QA Factory в самостоятельный канал поиска и квалификации клиентов, не создавая второй QA-движок и не дублируя уже построенные capabilities.

---

# 0. Executive decision

**Prospect QA Radar / Super Scout** — отдельный автономный рабочий контур внутри общей **ARK / AI QA Factory**.

Он не является:

- отдельной второй QA-системой;
- простым crawler;
- массовым scanner dump;
- спам-движком;
- pentest-платформой;
- ботом для обхода ограничений сайтов.

Он является:

```text
global discovery
→ commercial filtering
→ adaptive QA/SEO analysis
→ bounded-interactive E2E
→ evidence capture
→ independent verification
→ prospect scoring
→ contact intelligence
→ audit offer mapping
→ controlled disclosure
→ human-approved outreach
→ paid QA audit
```

## Два контура одной системы

### Контур A — Client Work Factory

```text
входящий заказ
→ intake
→ planning
→ execution
→ evidence
→ verification
→ delivery
```

### Контур B — Prospect QA Radar

```text
campaign
→ discovery
→ eligibility
→ cheap triage
→ browser QA
→ bounded interaction
→ evidence
→ verification
→ prioritization
→ contact discovery
→ outreach draft
→ human approval
```

Оба контура используют единое QA-ядро:

- Playwright/browser runners;
- API/network analysis;
- accessibility pipeline;
- Lighthouse/performance pipeline;
- technical SEO;
- passive security/privacy checks;
- evidence engine;
- findings/risk model;
- verification;
- state machine;
- approvals;
- Client Delivery Pack;
- secret/PII scanning.

---

# 1. Non-negotiable architecture principles

## 1.1 Reuse first

```text
REUSE EXISTING FACTORY CAPABILITY
→ USE TRUSTED MCP
→ USE MATURE API/TOOL
→ BUILD THIN ADAPTER
→ BUILD CUSTOM ONLY FOR UNIQUE VALUE
```

### Нельзя создавать заново

- второй browser automation framework;
- второй findings format;
- новый screenshot/video engine;
- новый accessibility scanner;
- новый performance scanner;
- новый evidence format;
- второй report generator;
- отдельный QA verifier;
- собственный универсальный crawler, если зрелый provider покрывает задачу;
- второй CRM внутри QA core.

### Собственная ценность Super Scout

Собственный код сосредоточен на:

- campaign planning;
- global discovery strategy;
- business eligibility;
- business-flow detection;
- adaptive capability planning;
- side-effect classification;
- interaction boundaries;
- evidence normalization;
- false-positive reduction;
- company identity resolution;
- contact intelligence;
- prospect prioritization;
- offer mapping;
- disclosure control;
- retention and recheck logic;
- human review;
- orchestration готовых tools/MCP и AI QA Factory.

---

# 2. Product objective

Система должна находить не максимальное количество сайтов, а максимальное количество:

```text
платёжеспособных бизнесов
× с важным digital flow
× с доказуемыми проблемами
× с подходящим публичным контактом
× с высокой вероятностью покупки QA-аудита
```

Главная бизнес-метрика:

```text
paid_audits_per_1000_discovered_targets
```

Дополнительные метрики:

- verified prospects per 1,000 targets;
- positive replies per 100 drafts;
- calls per 100 approved messages;
- paid audits per 100 contacts;
- revenue per 1,000 discovered businesses;
- cost per verified prospect;
- cost per reply;
- cost per paid client;
- gross margin;
- false-positive rate;
- evidence completeness;
- side-effect incidents.

---

# 3. Markets and target universe

## 3.1 География

| Уровень | Рынки |
|---|---|
| Tier 1 | США, Германия |
| Tier 2 | Великобритания, Австрия, Швейцария, Нидерланды, Ирландия |
| Tier 3 | Канада, Австралия, Новая Зеландия, Nordics, Бельгия |
| Local | Словакия, Чехия, Украина |
| Experimental | любые другие рынки по нишам, языкам и бюджету |

Для каждой страны хранится отдельная policy:

```text
allowed_discovery_sources
allowed_contact_sources
allowed_outreach_channels
email_allowed
linkedin_allowed
manual_review_required
follow_up_rules
retention_period
suppression_requirements
legal_review_status
```

## 3.2 Типы потенциальных клиентов

### Компании

- SaaS;
- AI products;
- ecommerce;
- marketplaces;
- booking platforms;
- hotels;
- clinics;
- restaurants;
- agencies;
- professional services;
- education;
- real estate;
- local services;
- subscription businesses.

### Малые команды и стартапы

- MVP;
- bootstrapped SaaS;
- micro-SaaS;
- founder-led products;
- недавно запущенные продукты;
- redesigned/relaunched products;
- waitlist и launch pages.

### Платёжеспособные персональные бренды

- premium consultants;
- lawyers;
- financial advisors;
- doctors;
- coaches с high-ticket offers;
- course creators;
- paid communities;
- authors/speakers;
- premium freelancers;
- independent experts;
- personal SaaS owners.

Одностраничный сайт не считается слабым автоматически. Важны:

```text
commercial capacity
website criticality
contactability
audit potential
```

---

# 4. Global Discovery & Filtering Engine

## 4.1 Многоканальный discovery

Система не зависит от одного поисковика или каталога.

Источники подключаются через adapters/MCP/API:

- search providers;
- maps/business directories;
- startup/product directories;
- marketplaces;
- agency directories;
- professional directories;
- public company databases;
- technology databases;
- public social/company profiles;
- conference and speaker pages;
- portfolio/personal sites;
- public launch announcements;
- job and hiring signals;
- public documentation/help/status pages.

## 4.2 Campaign matrix

```text
country
× region/city
× language
× industry
× business type
× business model
× commercial flow
× technology
× company size
× source
```

Примеры:

```text
USA × B2B SaaS × demo/signup
Germany × private clinic × appointment
Global × premium consultant × book-a-call
UK × ecommerce × cart/checkout
Austria × hotel × direct booking
```

## 4.3 Двухступенчатая фильтрация

### Stage 1 — eligibility

Практически бесплатные проверки:

- доступность;
- не parked domain;
- не заброшенный проект;
- активный бизнес;
- наличие коммерческого offer;
- наличие conversion action;
- язык/страна;
- duplicate/suppression;
- contact route;
- сайт принадлежит реальному бизнесу;
- отсутствие очевидного low-value/hobby signal.

### Stage 2 — commercial qualification

Проверяется:

- сайт влияет на revenue/leads;
- есть booking/cart/signup/contact;
- продукт или услуга имеет коммерческую ценность;
- компания активна;
- есть вероятность бюджета на QA;
- сайт достаточно значим и сложен;
- есть decision-maker или usable business contact;
- возможен focused/comprehensive audit;
- вероятны follow-up services.

## 4.4 Commercial Capacity Score

Сигналы:

- опубликованные цены;
- paid subscription;
- premium/high-ticket services;
- ecommerce catalog;
- booking with price;
- multiple pricing tiers;
- customer cases;
- active hiring;
- product team;
- international markets;
- multilingual/multicurrency site;
- active campaigns;
- fresh releases;
- multiple offices;
- complex funnel;
- professional design;
- integrations.

Для персональных сайтов:

- Book a consultation;
- Apply to work with me;
- premium program;
- paid course/community;
- calendar booking;
- testimonials;
- case studies;
- digital checkout;
- speaking/consulting;
- paid newsletter.

## 4.5 Negative filtering

Понижать или исключать:

- parked domains;
- hobby/student projects;
- inactive sites;
- no commercial action;
- duplicate white-label sites;
- pure aggregator without owned product;
- giant enterprise without realistic contact path;
- unsupported markets;
- previously suppressed companies;
- obvious public-sector targets without separate strategy.

Исключение должно быть объяснимым и обратимым.

## 4.6 Non-standard high-value

Специальная категория:

```text
NON_STANDARD_HIGH_VALUE
```

Сюда попадают:

- premium one-page landing;
- founder site;
- waitlist;
- launch page;
- paid webinar funnel;
- course sales page;
- premium community;
- direct-booking specialist;
- small agency landing;
- high-ticket lead funnel.

---

# 5. Site/Application Classification & Capability Planning

Перед тестированием Scout определяет:

```text
resource_type
business_type
primary_flow
secondary_flows
technology_stack
languages
markets
mobile_importance
seo_importance
authentication_requirements
interaction_boundaries
commercial_capacity
```

## 5.1 Resource types

- corporate site;
- ecommerce;
- SaaS/web app;
- booking;
- clinic;
- hotel;
- restaurant;
- marketplace;
- agency;
- personal brand;
- premium landing;
- content/media;
- startup/MVP;
- local service;
- public app area;
- authenticated app.

## 5.2 Dynamic capability plan

Для каждого сайта создаются:

```text
SITE_PROFILE.json
BUSINESS_CONTEXT.json
CAPABILITY_PLAN.json
INTERACTION_BOUNDARY.json
COVERAGE_MAP.json
```

Scout не запускает все инструменты на всех сайтах. Он выбирает релевантный набор и бюджет.

---

# 6. Adaptive analysis matrix

## 6.1 Универсальный базовый слой

Почти каждый подходящий target получает:

- availability/HTTP;
- redirects/broken assets;
- desktop/mobile rendering;
- console/network quick check;
- obvious UX defects;
- accessibility quick scan;
- performance quick scan;
- technical SEO;
- sitemap/robots/canonical;
- public contacts;
- commercial flows;
- passive security/privacy indicators.

## 6.2 Ecommerce

- product page;
- variants;
- price/currency;
- quantity;
- add/remove cart;
- subtotal;
- cart persistence;
- checkout navigation;
- mobile checkout;
- product structured data;
- product SEO;
- network failures;
- stop before order/payment.

## 6.3 Booking / hotel / clinic / restaurant

- date/time selection;
- guests;
- availability;
- timezone;
- service/room selection;
- pricing;
- mobile calendar;
- accessibility;
- validation;
- booking funnel;
- local/service SEO;
- stop before hold/reservation.

## 6.4 SaaS / web application

- pricing;
- demo;
- public signup entry;
- trial entry;
- auth UI;
- onboarding entry;
- validation;
- public APIs/network errors;
- mobile;
- accessibility;
- performance;
- marketing SEO.

Private functions require authorized access.

## 6.5 Personal brand / premium landing

- CTA;
- consultation booking;
- lead form validation;
- course/community entry;
- mobile conversion;
- trust signals;
- performance;
- technical SEO;
- structured data;
- contactability.

## 6.6 Content/media

- crawlability;
- indexability;
- canonical;
- structured data;
- pagination;
- internal links;
- performance;
- accessibility;
- localization.

---

# 7. Analysis levels and budget routing

## Level A — Cheap discovery

Без полноценного браузера:

- DNS/HTTP;
- headers;
- robots/sitemap;
- homepage HTML;
- tech detection;
- language/country;
- commercial flow presence;
- contact pages;
- deduplication;
- suppression;
- basic SEO.

## Level B — Browser triage

- homepage;
- pricing/service/product;
- contact/cart/booking entry;
- mobile/desktop screenshots;
- console;
- failed requests;
- axe quick scan;
- limited Lighthouse;
- broken navigation;
- overlays;
- responsive defects.

## Level C — Bounded interactive QA

- primary business journey;
- multiple viewports;
- search/filter/sort;
- product options;
- reversible cart;
- booking availability;
- validation;
- synthetic data;
- pre-submit E2E;
- video/trace;
- reproducibility.

## Level D — Outreach eligibility

Finding допускается только если:

- reproduced;
- evidence captured;
- sanitized;
- independently verified;
- business impact explained;
- allowed action used;
- current before send;
- suitable for our audit offer.

---

# 8. Business-flow priority

```text
BUSINESS_FLOW_FAILURE
>
CONVERSION_FRICTION
>
TRUST_ACCESSIBILITY_LOCALIZATION
>
TECHNICAL_QUALITY
>
COSMETIC
```

## P0

- cart/checkout unavailable;
- booking unavailable;
- incorrect total/price;
- main lead form broken;
- critical API failure;
- mobile funnel impossible.

## P1

- CTA blocked;
- lost user data;
- infinite loader;
- broken funnel step;
- major mobile conversion issue;
- commercially important performance failure.

## P2

- localization;
- currency/date inconsistency;
- accessibility barrier;
- important 404;
- trust/privacy inconsistency.

## P3

- performance;
- technical SEO;
- metadata;
- caching;
- structured data;
- security-header gaps.

## P4

- cosmetic;
- minor content;
- low-impact accessibility;
- minor layout inconsistency.

### Severity and outreach value are separate

```text
Severity:
CRITICAL / HIGH / MEDIUM / LOW / INFORMATIONAL

Outreach value:
STRONG_HOOK / SUPPORTING_HOOK / PAID_AUDIT_ONLY / INTERNAL_ONLY
```

---

# 9. Synthetic User & Safe E2E Simulation Engine

Scout должен уметь вводить правдоподобные синтетические данные и проходить сценарий максимально глубоко до side-effect boundary.

## 9.1 Personas

- consumer;
- business buyer;
- tourist;
- patient;
- restaurant guest;
- SaaS trial user;
- premium lead;
- international customer.

Параметры:

```text
country
locale
timezone
currency
language
name
address format
email strategy
phone strategy
company profile
```

Синтетические данные не должны принадлежать реальным людям.

## 9.2 Modes

### Validation only

Заполнение без submit.

### Reversible session

- cart;
- filters;
- variants;
- dates;
- wizard;
- session state;
- cleanup.

### Pre-submit E2E

Проход до последней безопасной точки.

### Authorized full E2E

Только со staging/test account/sandbox/written scope.

## 9.3 Blocked without authorization

- order;
- booking;
- slot hold;
- contact submission;
- account creation;
- newsletter;
- OTP/email/SMS;
- payment;
- coupon with business impact;
- upload;
- public content;
- real-user modification.

## 9.4 Cleanup

```text
remove cart items
clear session/local storage
clear synthetic form data
close context
delete temp files
record cleanup result
```

---

# 10. Access, blocks and CAPTCHA policy

## 10.1 Block-aware, not reject-by-default

```text
ACCESS LIMITED
≠
BUSINESS NOT SUITABLE
```

Отдельно оцениваются:

- commercial opportunity;
- public coverage;
- access complexity.

Статусы:

```text
FULLY_ACCESSIBLE
PARTIALLY_ACCESSIBLE
PUBLIC_PAGES_ONLY
MANUAL_REVIEW_REQUIRED
CONTACT_FIRST
AUTHORIZED_AUDIT_REQUIRED
TEMPORARILY_RATE_LIMITED
GEO_LIMITED
NO_SCAN
```

## 10.2 Block classifier

```text
NORMAL
RATE_LIMITED
ROBOTS_RESTRICTED
LOGIN_REQUIRED
CAPTCHA_PRESENT
WAF_CHALLENGE
GEO_RESTRICTED
CONSENT_REQUIRED
TEMPORARY_FAILURE
AUTOMATION_RESTRICTED
UNKNOWN_BLOCK
```

## 10.3 Allowed efficiency measures

- real Chromium;
- proper JS execution;
- one stable session per domain;
- cookies/consent;
- correct locale/timezone;
- low concurrency;
- rate limiting;
- exponential backoff;
- caching;
- URL deduplication;
- public subdomains;
- official/public endpoints;
- licensed providers;
- manual takeover for strong prospects;
- authorized test access.

## 10.4 Not included

- automatic CAPTCHA solving on third-party sites;
- stealth plugins;
- fingerprint forgery;
- residential proxy rotation for evasion;
- bypass of rate limits;
- IP rotation after blocks;
- hidden/private API exploitation;
- login/paywall/access-control bypass;
- repeated attempts after explicit prohibition.

## 10.5 CAPTCHA queue

CAPTCHA не означает reject.

```text
CAPTCHA_DETECTED
→ SESSION_PAUSED
→ COMMERCIAL SCORE CHECK
→ weak target archived
→ strong target enters CAPTCHA REVIEW QUEUE
→ session preserved
→ manual completion
→ automatic resume
```

Для authorized audits используются test keys, staging, allowlisting или QA bypass provided by client.

---

# 11. Evidence-first architecture

Главное правило:

```text
NO EVIDENCE
=
NO CLIENT FINDING
```

Lifecycle:

```text
UNVERIFIED
→ REPRODUCED
→ EVIDENCE_CAPTURED
→ SANITIZED
→ VERIFIED
→ OUTREACH_ELIGIBLE
```

## 11.1 Evidence types

- original screenshot;
- annotated screenshot;
- short video;
- Playwright trace;
- sanitized console log;
- sanitized network excerpt;
- Lighthouse report;
- axe result;
- reproduction steps;
- URL/device/viewport/locale/timestamp;
- expected vs actual;
- business impact;
- cleanup status.

## 11.2 Three evidence layers

```text
RAW
→ VERIFIED
→ CLIENT_SAFE
```

### RAW

Internal originals.

### VERIFIED

Sanitized, reproduced, linked to finding.

### CLIENT_SAFE

Minimal materials suitable for outreach or paid delivery.

## 11.3 Evidence Center

Evidence хранится не как хаотичные папки, а в UI:

```text
Company
└── Session
    ├── Finding
    │   ├── screenshot
    │   ├── video
    │   ├── trace
    │   ├── logs
    │   └── verification
    └── Coverage summary
```

Каждый artifact содержит:

```text
evidence_id
finding_id
company_id
domain
session_id
artifact_type
captured_at
page_url
viewport
browser
sanitization_status
verification_status
client_safe
storage_path
retention_until
hash
```

---

# 12. Finding normalization and cross-tool synthesis

Разные tools могут описывать одну проблему.

Пример:

```text
Lighthouse → slow LCP
Browser → CTA appears late
Mobile QA → CTA below fold
Network → 9 MB hero image
```

Normalizer объединяет их в один коммерчески понятный finding.

Каждый finding содержит:

```text
finding_id
severity
confidence
technical_confidence
business_impact
outreach_value
reproduction_steps
evidence_refs
verification_status
freshness_status
```

Scout metadata:

```text
company_id
campaign_id
audit_opportunity
contactability
client_safe_status
disclosure_level
```

---

# 13. Prospect scoring

Не использовать один непрозрачный score.

## 13.1 Independent scores

```text
technical_confidence
business_impact
evidence_quality
audit_opportunity
contactability
commercial_capacity
market_fit
website_criticality
outreach_value
public_coverage
access_complexity
remediation_fit
```

`remediation_fit` не должен снижать ценность аудита.

## 13.2 Prospect priority

Пример базовых весов:

| Фактор | Вес |
|---|---:|
| Business impact | 25% |
| Audit opportunity | 20% |
| Technical confidence | 15% |
| Evidence quality | 15% |
| Commercial capacity | 10% |
| Contactability | 10% |
| Market fit | 5% |

## 13.3 Grades

```text
A — contact first
B — strong prospect
C — review later
D — weak/insufficient evidence
REJECTED — unsuitable
```

## 13.4 Explainability

UI должен показывать:

```text
Priority A — 89/100

Why:
+ booking flow is business-critical
+ finding reproduced twice
+ video and network evidence available
+ website is primary conversion channel
+ focused booking audit fits well

Risks:
- no named decision-maker
- manual country-policy review required
```

---

# 14. Contact Intelligence

## 14.1 Contact block

```text
name
role
email
source
confidence
last_verified_at
linkedin
contact_page
public_phone
country_policy
suppression_status
```

## 14.2 Contact priority

1. Head of Product / CTO / Engineering Manager.
2. Founder/owner.
3. Digital/Ecommerce/Operations Manager.
4. QA/Engineering contact.
5. General business email.
6. Contact form.

## 14.3 Email status

```text
VERIFIED_PUBLIC
PUBLIC_UNVERIFIED
GENERIC_BUSINESS
INFERRED_NOT_ALLOWED_FOR_SEND
CONTACT_FORM_ONLY
INVALID
SUPPRESSED
```

Автоматически угаданный адрес не используется для отправки без подтверждения.

## 14.4 Provenance

Каждый контакт показывает источник:

- company contact page;
- team page;
- public LinkedIn;
- business directory;
- footer;
- public profile.

## 14.5 History

```text
first_discovered_at
last_verified_at
contacted_at
reply_status
bounce_status
do_not_contact
suppression_reason
```

---

# 15. Company Identity Resolution

Дедупликация выполняется на уровне компании, а не только домена.

```text
company_id
legal_name
brand_names[]
domains[]
subdomains[]
contacts[]
campaign_history[]
outreach_history[]
```

Пример одной компании:

```text
example.com
example.de
shop.example.com
booking-example.com
```

Это предотвращает повторный crawl и повторный outreach.

---

# 16. Evidence Disclosure Engine

Нельзя отдавать клиенту весь аудит бесплатно.

## 16.1 Outreach Teaser

- 1 primary finding;
- максимум 1 supporting finding;
- 1 annotated screenshot или 5–15 sec video;
- page/device/date;
- concise business impact;
- no root-cause details;
- no full logs;
- no full findings list;
- no remediation backlog.

## 16.2 Qualification Pack

После заинтересованного ответа:

- 2–3 findings;
- coverage summary;
- checked/not checked;
- risk overview;
- recommended audit scope;
- price/effort range;
- sample deliverables.

## 16.3 Paid Delivery

- all approved findings;
- full verified evidence;
- reproduction;
- coverage;
- risk matrix;
- recommendations;
- technical appendices;
- optional remediation assessment.

## 16.4 Disclosure levels

```text
INTERNAL_ONLY
OUTREACH_ELIGIBLE
QUALIFICATION_ELIGIBLE
PAID_DELIVERY_ONLY
```

## 16.5 Client-safe protection

- watermark;
- expiry;
- non-indexed/random URL if hosted later;
- revoke;
- access log;
- pre-send revalidation;
- no raw secrets/PII;
- no full trace/HAR in first outreach.

---

# 17. Audit Offer Engine

Для prospect система предлагает конкретный продукт.

```text
recommended_audit_offer
audit_scope
audit_depth
audit_directions
estimated_effort
deliverables
price_band
optional_remediation_possible
remediation_confidence
required_access
```

## 17.1 Core offers

- QA Discovery Session;
- Focused Funnel Audit;
- Booking Audit;
- Ecommerce Checkout Audit;
- Mobile/Responsive Audit;
- Accessibility Audit;
- Technical SEO Audit;
- Performance Audit;
- API/Integration Audit;
- Comprehensive QA Assessment;
- Continuous Regression Review;
- Combined QA + SEO Audit.

## 17.2 Primary commercial model

```text
free verified micro-finding
→ paid QA audit
→ report/risk map/recommendations
→ optional remediation proposal
→ verification/regression
```

Исправление продаётся отдельно и только после оценки stack/access/feasibility.

---

# 18. Web dashboard — mandatory MVP

Первый рабочий пилот должен иметь ясный профессиональный локальный web-интерфейс.

```text
laptop on
→ Start Radar
→ http://localhost:<port>
→ VS Code not required
```

## 18.1 Main sections

1. Overview.
2. Campaigns.
3. Live Sessions.
4. Prospects.
5. Prospect Detail.
6. Evidence Center.
7. Review Queue.
8. Storage.
9. Settings/Safety.

## 18.2 Overview

Показывает только главное:

```text
Radar status
Running now
Best opportunities
Needs attention
Today metrics
Cost
Storage
```

## 18.3 Campaign Builder

Поля:

```text
campaign name
countries
industries
keywords
business types
languages
sources
commercial threshold
analysis directions
interaction mode
daily budget
site limits
schedule
```

Advanced settings скрыты.

## 18.4 Live Sessions

- domain;
- stage;
- flow;
- current action;
- latest screenshot;
- elapsed time;
- evidence count;
- safety state;
- stop/pause.

## 18.5 Prospects table

| Company | Main finding | Grade | Audit offer | Contact | Evidence | Status |
|---|---|---:|---|---|---|---|

Фильтры:

- country;
- industry;
- grade;
- severity;
- audit type;
- evidence completeness;
- contact availability;
- campaign;
- status.

## 18.6 Prospect Detail

Tabs:

- Summary;
- Findings;
- Evidence;
- Coverage;
- Contacts;
- SEO;
- Outreach;
- History;
- Technical details.

## 18.7 Review Queue

```text
Verify findings
Review prospects
Review contacts
Approve drafts
Review CAPTCHA sessions
Review deletions
Re-run expired evidence
```

## 18.8 Progressive disclosure

Главный экран показывает бизнес-результат. Raw JSON/logs/IDs доступны только через `Technical details`.

---

# 19. Prospect lifecycle

```text
DISCOVERED
→ ELIGIBLE
→ QUICK_SCANNED
→ BROWSER_AUDITED
→ FINDING_VERIFIED
→ QUALIFIED
→ CONTACT_FOUND
→ DRAFT_READY
→ APPROVED
→ CONTACTED
→ REPLIED
→ PAID_AUDIT
→ CLOSED / ARCHIVED
```

Дополнительные:

```text
REJECTED
SUPPRESSED
DUPLICATE
NEEDS_RECHECK
EVIDENCE_EXPIRED
CONTACT_FIRST
MANUAL_REVIEW_REQUIRED
COOLDOWN
```

---

# 20. Storage & Retention Manager

## 20.1 Three project classes

1. Prospect scans.
2. Paid client projects.
3. Internal/demo projects.

## 20.2 Actions

### Archive

Hide from active work; preserve data.

### Cleanup evidence

Remove heavy artifacts but keep summary/history/suppression.

### Soft delete

Move to Trash with recovery window.

### Permanent purge

Destroy selected data after explicit confirmation.

## 20.3 Retention defaults

| State | Retention |
|---|---:|
| Failed eligibility | URL + reason only |
| Quick scan, no findings | 0–3 days |
| Weak rejected prospect | 7–14 days |
| Useful uncontacted finding | 30 days |
| Qualified prospect | 60–90 days |
| Contacted prospect | campaign policy |
| Positive reply | until commercial process ends |
| Paid audit | project-specific policy |
| PII/secrets | quarantine then redact/delete |

## 20.4 Rejected prospect cleanup

Remove first:

- video;
- traces;
- full network logs;
- duplicate screenshots;
- temp profiles;
- crawl intermediates;
- stale reports.

Keep minimal:

```text
company_id
domains
contact hashes
rejection reason
score
suppression
last_checked_at
```

Evidence removed does not mean company forgotten.

## 20.5 Deduplication and compression

- artifact hashes;
- one physical artifact referenced by multiple findings;
- screenshot compression;
- video trimming/compression;
- trace archive;
- sanitized excerpt instead of full logs;
- raw logs removed after safe copy where policy permits.

## 20.6 Disk protection

```text
free > 30 GB → normal
free < 20 GB → reduce video
free < 10 GB → pause deep browser audits + cleanup
free < 5 GB  → stop new sessions, preserve active state
```

---

# 21. Site Memory & Recheck Manager

Scout должен помнить каждый сайт и каждый finding.

```text
company_id
domains[]
first_seen_at
last_scanned_at
last_full_audit_at
last_changed_at
known_findings[]
resolved_findings[]
outreach_history
next_recheck_at
recheck_policy
suppression_status
site_fingerprint
```

## 21.1 Before any scan

Проверяется:

- already scanned;
- same company under another domain;
- suppression;
- cooldown;
- recent scan;
- site changed;
- findings active/resolved;
- contacted before.

## 21.2 Cheap change detection

- ETag;
- Last-Modified;
- HTML hash;
- DOM fingerprint;
- sitemap;
- key assets;
- metadata;
- commercial-page hash;
- screenshot perceptual hash;
- business-flow fingerprint.

Result:

```text
NO_MEANINGFUL_CHANGE
MINOR_CHANGE
MAJOR_CHANGE
BUSINESS_FLOW_CHANGED
UNKNOWN
```

## 21.3 Recheck levels

```text
L0 history check
L1 cheap change detection
L2 finding recheck
L3 targeted re-audit
L4 full re-audit
```

## 21.4 Finding lifecycle

```text
DISCOVERED
→ REPRODUCED
→ VERIFIED
→ ACTIVE
→ RESOLVED
→ REGRESSED
```

## 21.5 Pre-send revalidation

```text
DRAFT_READY
→ TARGETED_RECHECK
→ STILL_REPRODUCIBLE
→ EVIDENCE_CURRENT
→ HUMAN_APPROVAL
```

Resolved finding blocks old outreach.

## 21.6 Scan vs outreach suppression

```text
NO_OUTREACH
NO_SCAN
COOLDOWN
MONITOR_CHANGES_ONLY
```

---

# 22. Technical SEO capability

Technical SEO is an optional but integrated analysis direction.

## 22.1 Quick triage

- robots;
- sitemap;
- status/redirect;
- noindex;
- canonical;
- title/description;
- H1/headings;
- broken internal links;
- mobile;
- Lighthouse SEO;
- structured data presence;
- hreflang;
- duplicate indicators.

## 22.2 Deep Technical SEO

- crawlability;
- indexability;
- JS rendering;
- canonical conflicts;
- internal linking;
- orphan-like pages;
- duplicate metadata;
- structured data;
- Core Web Vitals;
- international versions;
- pagination;
- URL structure;
- crawl depth.

## 22.3 Search/competitor intelligence

Separate paid/optional layer requiring external datasets:

- ranking keywords;
- competitors;
- backlinks;
- traffic estimates;
- content gaps.

## 22.4 Independent scores

```text
technical_seo_confidence
seo_business_impact
seo_opportunity
search_visibility_potential
seo_evidence_quality
```

---

# 23. Local infrastructure first

## 23.1 Start stage

No domain and no traditional hosting required.

```text
local scheduler
local database
local queues
browser workers
local dashboard
```

VS Code is not required after launch.

## 23.2 One-click startup

- Start Radar shortcut/command;
- automatic service startup;
- dashboard opens;
- Stop Radar;
- graceful pause;
- state preserved after restart/sleep.

## 23.3 Local resilience

- SQLite/Postgres abstraction;
- transactional writes;
- checkpoints;
- resume queues;
- crash recovery;
- periodic backups;
- storage health;
- worker heartbeat;
- no data loss on controlled shutdown.

## 23.4 Later server mode

Only after proven value:

- VPS/container;
- scheduler;
- DB;
- workers;
- dashboard;
- private access;
- domain optional.

---

# 24. Observability and safety controls

## 24.1 Structured events

```text
session_started
site_discovered
page_opened
flow_identified
action_executed
observation_created
finding_reproduced
evidence_captured
finding_verified
cleanup_completed
lead_scored
contact_found
draft_created
session_finished
```

## 24.2 Kill switches

```text
pause_all_campaigns
pause_country
pause_provider
pause_browser_interactions
disable_cart_actions
disable_booking_actions
disable_outreach
stop_all_workers
```

## 24.3 Alerts

- P0 verified;
- A-grade prospect ready;
- draft ready;
- cost limit reached;
- disk low;
- worker stopped;
- evidence expired;
- finding invalidated;
- CAPTCHA/manual action required;
- sanitization blocked;
- safety boundary reached.

## 24.4 Versioning

Every result records:

```text
policy_version
scanner_version
tool_version
browser_version
campaign_version
scoring_version
prompt_version
evidence_schema_version
```

---

# 25. Quality gates and evaluation

## 25.1 Benchmark set

Maintain:

- known-defect sites;
- clean sites;
- controlled demo sites;
- resolved/regressed scenarios;
- different business types;
- different languages/viewports.

## 25.2 Target quality

```text
outreach precision > 90%
evidence completeness > 95%
side-effect incidents = 0
duplicate outreach = 0
stale-finding outreach = 0
```

## 25.3 Human sampling

- 100% P0/P1 outbound findings;
- 100% outreach drafts;
- sample of rejected findings;
- sample of automatic archives;
- periodic false-positive review.

---

# 26. Adaptive learning and unit economics

Система должна учиться по результатам:

```text
source
→ eligible targets
→ browser audits
→ verified findings
→ approved drafts
→ replies
→ calls
→ paid audits
→ revenue
```

## 26.1 Feedback reasons

### Reject

- false positive;
- weak company;
- no suitable contact;
- low commercial value;
- not relevant;
- duplicate;
- access too limited;
- no audit fit.

### Approve

- strong evidence;
- clear impact;
- good decision-maker;
- good offer fit;
- high payment potential.

## 26.2 Budget adaptation

- increase high-yield sources/segments;
- reduce low-yield sources;
- preserve 10–20% exploration budget;
- optimize paid conversion, not email opens.

---

# 27. Outreach and communication controls

## 27.1 No automatic send in MVP

```text
finding
→ verification
→ sanitization
→ disclosure selection
→ country policy
→ suppression check
→ pre-send revalidation
→ human approval
→ send
```

## 27.2 Outreach history

- recipient;
- channel;
- exact disclosure;
- evidence link;
- timestamp;
- reply;
- opt-out;
- bounce;
- follow-up status.

## 27.3 Responsible disclosure

Critical security/privacy issues are not used as sales pressure.

- minimize sensitive storage;
- use secure channel;
- disclose enough to protect users;
- avoid exploit details in normal outreach;
- follow responsible disclosure workflow.

---

# 28. Mandatory artifacts

## 28.1 Campaign-level

```text
PROSPECT_CAMPAIGN.json
MARKET_POLICY.json
DISCOVERY_PLAN.json
DISCOVERED_BUSINESSES.json
ELIGIBLE_TARGETS.json
BUSINESS_CONTEXT.json
SITE_PROFILE.json
INTERACTION_BOUNDARY.json
SITE_TRIAGE_PLAN.json
CAPABILITY_PLAN.json
COVERAGE_MAP.json
NORMALIZED_FINDINGS.json
LEAD_SCORECARD.json
PROSPECT_SHORTLIST.json
CONTACTS.json
OUTREACH_DRAFTS.md
DISCLOSURE_MANIFEST.json
SUPPRESSION_CHECK.json
RETENTION_PLAN.json
CAMPAIGN_SUMMARY.md
```

## 28.2 Finding-level

```text
FINDING_<id>.json
REPRODUCTION_STEPS_<id>.md
EVIDENCE_INDEX_<id>.json
SCREENSHOT_ORIGINAL_<id>.png
SCREENSHOT_ANNOTATED_<id>.png
TRACE_<id>.zip
VIDEO_<id>.webm
CONSOLE_SANITIZED_<id>.log
NETWORK_SANITIZED_<id>.json
VERIFICATION_RESULT_<id>.json
OUTREACH_EVIDENCE_SUMMARY_<id>.md
```

Не каждый finding обязан иметь все файлы. Evidence planner выбирает минимально достаточный набор.

---

# 29. Phased implementation

## Phase 8.1

- finish planning hardening;
- no crawler scope expansion.

## Phase 8.2

- prospect campaign schemas;
- market policy;
- interaction boundary;
- evidence bundle;
- business context;
- capability profiles;
- scoring contracts;
- lifecycle contracts;
- retention/recheck contracts;
- dashboard information architecture.

## Phase 8.3

- MCP discovery;
- adapters;
- trust/allowlists;
- cost/rate metadata;
- discovery/crawl providers;
- evidence capabilities;
- contact providers;
- tool provenance.

## Phase 8.4

- read-only/bounded-interactive execution;
- browser;
- DevTools;
- Lighthouse;
- axe;
- screenshots;
- traces/video;
- synthetic data;
- safe cart/booking flows;
- block detection;
- local dashboard skeleton.

## Phase 8.5

- finding normalization;
- independent verification;
- false-positive reduction;
- business impact;
- lead scoring;
- SEO opportunity;
- contactability;
- evidence center;
- shortlist;
- draft generation;
- disclosure engine.

## Phase 8.6

- campaign management;
- DB/CRM;
- company identity;
- suppression;
- rechecks;
- retention/storage;
- client-safe export/page;
- review queues;
- contacts;
- full dashboard.

## Phase 8.7

Optional controlled expansion:

- Gmail/Resend;
- follow-ups;
- CRM integrations;
- authorized write actions;
- staging/full E2E;
- optional remediation/deploy.

---

# 30. Rational MVP

Первый полезный локальный MVP включает:

1. Local web dashboard.
2. Campaign Builder.
3. Discovery and filtering.
4. Site classification.
5. Browser triage.
6. Bounded-interactive flows.
7. Synthetic validation/pre-submit E2E.
8. QA + technical SEO quick analysis.
9. Evidence Center.
10. Verification.
11. Prospect scoring with explanation.
12. Contacts.
13. Audit offer mapping.
14. Outreach teaser generation.
15. Review Queue.
16. Archive/reject/suppress/delete.
17. Retention and disk protection.
18. Site memory/rechecks.
19. Cost counters.
20. Emergency stop.

Не входят в первый MVP:

- mobile app;
- complex multi-user CRM;
- automatic email send;
- full live video for all sessions;
- multi-tenant SaaS;
- autonomous remediation;
- automated CAPTCHA solving;
- large-scale proxy infrastructure.

---

# 31. MVP acceptance criteria

MVP считается рабочим, когда пользователь может:

```text
включить ноутбук
→ запустить Radar одной командой/ярлыком
→ открыть localhost dashboard
→ создать кампанию
→ увидеть discovery funnel
→ наблюдать live sessions
→ открыть prospect
→ увидеть findings/evidence/contacts
→ понять, почему prospect приоритетен
→ увидеть рекомендуемый audit offer
→ создать outreach teaser
→ approve/archive/reject/suppress
→ очистить evidence
→ остановить и продолжить систему после перезапуска
```

Технические критерии:

- no external send without approval;
- no side-effect action outside policy;
- no client finding without evidence;
- no stale finding in outreach;
- no duplicate company outreach;
- no silent data loss;
- no uncontrolled disk growth;
- recoverable local state;
- explainable scoring;
- complete provenance.

---

# 32. Final product model

```text
максимально широкий global discovery
→ дешёвый commercial filter
→ adaptive site classification
→ QA + mobile + accessibility + performance + SEO
→ safe synthetic E2E
→ evidence capture
→ verification
→ company/contact intelligence
→ explainable prospect priority
→ audit offer mapping
→ minimal sufficient disclosure
→ human approval
→ paid QA audit
→ optional remediation
→ retention/recheck/history
```

**Super Scout должен стать коммерческим intelligence-слоем внутри ARK / AI QA Factory: он сам находит перспективные бизнесы, понимает их ключевые digital flows, запускает релевантные QA/SEO capabilities, собирает доказательства, исключает ложные и устаревшие findings, находит публичные контакты, объясняет коммерческий приоритет и готовит минимально достаточное предложение платного аудита.**
