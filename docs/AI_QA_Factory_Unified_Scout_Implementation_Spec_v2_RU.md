# AI QA Factory — Unified Scout, Client Evidence и Live E2E
Дата: 2026-07-27
Статус: готовое задание на реализацию для Клода

## 0. Режим выполнения
Это не запрос на новый план или ещё один аудит. После короткой проверки кода нужно автономно реализовать весь пакет, покрыть его тестами, провести настоящий live end-to-end прогон, исправить подтверждённые проблемы, открыть PR, дождаться CI, выполнить merge и post-merge smoke.

Останавливаться следует только при объективном owner-only blocker: отсутствующий секрет/доступ, требование опасного или необратимого действия либо существенный выбор, которого нет в этом документе. Обычные инженерные решения принимать самостоятельно в рамках требований ниже.

Не отправлять письма, формы, сообщения, заявки и заказы. Не обходить CAPTCHA, login wall, robots/rate limits или защиту сайта.

## 1. Подтверждённая исходная база
Предыдущий пакет уже завершён:

PR: https://github.com/dmytropogribnyy/ai-qa-factory/pull/51

merge commit: f691c79a34790d8e7fd043cb09f0ef62cc5c3dfc

полный локальный suite: 5576 passed, 5 skipped, 5 warnings

CI: fast, scout-smoke, browser-acceptance, windows-full, meta — green

runtime после merge сообщал актуальный main без local changes и без restart requirement

На момент подготовки задания Observer дополнительно подтвердил:

- health: healthy, версия 6.3.0, safe_by_default
- deep-readiness: green
- Chromium реально запускается
- outbound network доступен
- evidence directory outputs доступен для записи
- активных кампаний нет
- в истории 14 проанализированных доменов

выбранные ниже фиксированные live-цели в этой истории отсутствуют.

Перед новой работой повторно проверить git status, HEAD, runtime build и отсутствие активного запуска. Не переделывать уже слитые изменения PR #51. В частности, переиспользовать существующие client_evidence.py, evidence manifest/storage, screenshot/video policy и delivery-pack capabilities вместо создания параллельной системы.

## 2. Результат, который должен получить оператор
Оператор видит один автономный Scout, а не набор технических режимов.

Сценарий:

источник сайтов → единая очередь → автоматическая безопасная проверка → результат сайта → findings/evidence → публичный контакт → тезисы и draft письма → клиентский evidence ZIP

Источников сайтов три:

Find websites

Paste URLs

Upload file

Это только три способа наполнить одну очередь. После ingestion, validation, canonicalization и deduplication дальнейший pipeline одинаков.

Static, Deep, Adaptive, Balanced, page/discovery caps, browser capture и evidence policy остаются внутренними возможностями движка. Оператор не должен выбирать их перед каждым запуском.

## 3. Жёсткие границы
В этом пакете:

- упростить Overview
- сделать единый Start Scout
- сохранить все три источника
- сделать правдивыми History, Needs attention и Details
- обеспечить просмотр и скачивание evidence
- добавить публичный контакт с provenance
- добавить тезисы и draft письма
- добавить отдельный клиентский evidence ZIP

провести настоящий live E2E.

Не выполнять полный редизайн Work, More и других ещё не проверенных экранов. Разрешено только перенести уже существующие Runtime/Diagnostics с Overview в подходящее существующее место под More, не создавая новый крупный режим.

Не ломать старые campaign records, API, CLI и сохранённые данные. Если старые настройки всё ещё нужны программным клиентам, сохранить их и сделать совместимый mapping в новую UI-модель.

Не коммитить outputs/, PNG, WebM/MP4, ZIP, логи, ярлыки или другие live-артефакты.

## 4. Визуальный ориентир для Overview
Figma:

https://www.figma.com/design/Er3VxY7TsxsUBZeKGWqOIg

Figma является дополнительным визуальным ориентиром. Если MCP не откроет файл, не блокировать работу: текстовые требования ниже приоритетны и достаточны. Новую Figma-доску для Scout создавать не нужно.

## 5. Overview
Целевой порядок:

- компактные основные показатели
- Scout
- Needs your attention
- Client work

компактный System ready.

Обязательные изменения:

- поднять Scout выше Client work
- Start a Scout campaign заменить на Start Scout
- добавить вторичный переход View Scout results, если маршрут уже существует
- Active work переименовать в Client work
- нулевой Needs your attention показывать одной компактной строкой
- не повторять одинаковые пустые состояния в нескольких крупных панелях
- убрать с Overview полный Runtime и Advanced view options
- подробные Runtime/Diagnostics перенести под существующий More
- на Overview оставить только понятный System ready, а при проблеме — короткий статус и переход к деталям
- исправить обрезание правого элемента темы

проверить keyboard focus, contrast, target sizes и responsive reflow.

## 6. Единый Start Scout
### 6.1. Общая структура
Форма содержит:

- переключатель источника: Find websites / Paste URLs / Upload file
- поля только выбранного источника
- необязательный общий Maximum sites
- краткое safety-summary
- одно подтверждение safety policy, только если оно обязательно

одну одинаковую кнопку Start Scout.

Пример summary:

Read-only scan · up to 20 sites · evidence saved automatically · no forms, purchases or messages.

До старта не показывать большие пустые панели IDLE, N/A, Controls unavailable и пустую таблицу Campaigns.

### 6.2. Find websites
Показывать только:

- countries
- business types
- необязательные keywords/signals

Maximum sites.

Пустое поле не должно скрыто означать неизвестный пользователю preset. Рядом кратко сообщить, что Scout применит стандартную безопасную B2B SaaS policy.

### 6.3. Paste URLs
Показывать:

- одно многострочное поле
- распознанные URL
- дубликаты

отклонённые строки и причины.

Явно переданные безопасные публичные URL считаются pinned: их нельзя отклонить только из-за невысокого commercial-fit score.

### 6.4. Upload file
Поддержать существующие целевые форматы CSV/XLSX без отдельного режима проверки.

Перед стартом показать:

- число валидных строк
- число уникальных доменов
- дубликаты

отклонённые строки и причины.

Не показывать отдельные Coverage и Scan mode.

### 6.5. Что убрать из ежедневной формы
Сейчас	Новое поведение
Campaign preset	Внутренняя конфигурация
Conservative / Balanced / Wider	Автоматическая политика Scout
Run size	Один Maximum sites
Adaptive / Deep coverage	Внутренняя адаптивная политика
Static / Deep Capture	Автоматический pre-check и углубление
Capture screenshots	Evidence включено автоматически
Page cap / discovery cap	Внутренние safety/budget limits
Diagnostic presets	Только Diagnostics
System readiness	Автоматический preflight
## 7. Единая внутренняя политика Scout
Для каждого target:

- parse и validation
- URL canonicalization
- domain normalization
- deduplication внутри input и против истории
- SSRF/safety checks
- для discovery — commercial qualification
- для pinned URL/file — commercial score не является причиной пропуска
- быстрый static pre-check
- browser/deep escalation только при необходимости
- console/network/accessibility/performance collection
- screenshot capture
- video только для значимого безопасного multi-step поведения
- поиск публичного контакта
- создание client-friendly findings
- тезисы и draft письма только при наличии проверенных actionable findings

сохранение единого result record.

Если один сайт заблокирован, Scout сохраняет причину и продолжает очередь. CAPTCHA не обходить.

## 8. History, Needs attention и Details
### 8.1. History
Основные колонки:

Site | Result | Priority | Evidence | Contact | Analyzed | Open

Результаты:

Ready to contact

Needs review

No actionable findings

Blocked

Failed

Не использовать Analyzed / Prospect как единственный содержательный результат.

Оставить поиск, status и один раскрываемый date filter. Не дублировать presets, Last N days и date range одновременно.

### 8.2. Needs attention
Исправить и покрыть regression tests:

- повторяющиеся строки одного canonical domain
- target вида 0.1
- private/reserved targets
- смешение количества уникальных сайтов и количества blocked attempts

неясный Resolve.

Требования:

- одна текущая строка на canonical domain
- прошлые попытки доступны внутри Details как history
- malformed/private/reserved values не выглядят как нормальные сайты

unique sites и attempt events считаются отдельно.

Пример:

5 sites need review. 13 blocked attempts were recorded.

Переименовать Resolve в точное действие либо добавить пояснение, что изменится.

### 8.3. Details
Не создавать ещё один верхнеуровневый режим. На одной странице сайта должны быть ясные секции:

Findings

Evidence

Contact & outreach

Client package

Каждый finding содержит:

- короткий client-friendly title
- severity/priority
- affected URL и шаг
- expected vs actual
- практический impact
- reproduction steps
- связанные evidence IDs
- статус проверки: verified / needs review

честную confidence/limitation note при необходимости.

Каждый verified finding обязан иметь релевантное evidence. Наличие файла без фактического открытия не считается проверкой.

## 9. Evidence
### 9.1. UI
В Evidence показывать:

- thumbnails для screenshots
- тип, размер и capture time
- affected page/step
- связанные finding IDs
- Open
- Download
- playable inline video

ясную причину, если capture отсутствует или завершился ошибкой.

Использовать состояния:

Available

Not applicable

Not captured: reason

Capture failed: reason

Не использовать неопределённое пустое место или вечное pending.

### 9.2. Минимум evidence
Для каждого успешно отрендеренного сайта:

- минимум один фактически открытый screenshot общего состояния
- screenshot для каждого визуально проверенного client-facing finding
- console/network/accessibility/performance summary
- технические логи только в разумном объёме и после redaction

SHA-256 и metadata в manifest.

Для всего acceptance-прогона:

- минимум одно настоящее короткое видео
- видео должно открываться inline из Details
- видео должно скачиваться

video record должен быть связан с target и, если применимо, finding.

### 9.3. Видео
Записывать только безопасную последовательность:

- публичная навигация
- поиск
- filter/toggle
- раскрытие меню

другое read-only или полностью обратимое действие.

Не отправлять формы, не голосовать, не создавать feedback, не регистрироваться и не инициировать demo booking.

Для клиентского пакета предпочтителен MP4/H.264. Если первичный Playwright artifact — WebM, сохранить оригинал внутренне и сделать клиентскую MP4-копию, если поддерживаемая runtime-зависимость уже доступна. Если надёжное преобразование невозможно, client-report.html должен воспроизводить WebM в Chromium/Edge, а README должен содержать короткую инструкцию. Не выдавать непроверенный transcoding за успешный.

## 10. Публичный контакт и draft письма
Contact & outreach содержит:

- Public email
- source URL
- captured at
- тип источника: contact page / docs / legal / feedback page
- другие публичные каналы только как secondary data
- Talking points
- Suggested subject
- Email draft
- статус Draft — not sent

действие Copy draft.

Правила:

- email извлекается только из публичного источника
- не угадывать firstname@domain
- не использовать скрытые или leaked данные
- source URL обязателен
- если email нет: Email not found и найденная публичная contact page/form, но форму не отправлять
- draft не создаётся при No actionable findings
- draft не заявляет о дефекте сильнее, чем доказано
- draft краткий, персональный, профессиональный и основан только на verified findings
- максимум 2–3 главных тезиса, а не свалка логов

ничего автоматически не отправлять.

Важно: expected emails в разделе live E2E ниже являются только тестовыми assertions. Их нельзя заранее подставлять в production result вместо фактического извлечения.

## 11. Клиентский evidence ZIP
### 11.1. Разделить клиентский пакет и внутренний draft
Не смешивать два разных артефакта:

Download client evidence (.zip) — безопасное вложение, которое после ручной проверки можно отправить клиенту.

Copy/Export outreach draft — внутренний текст оператора; по умолчанию он не входит в клиентский ZIP.

Это защищает от случайной отправки клиенту внутренних тезисов, contact provenance, служебных заметок или данных других компаний.

### 11.2. Scope пакета
Клиентский ZIP создаётся на один canonical domain. Он не должен содержать evidence, findings, email или внутренние данные других targets той же кампании.

Campaign-level bundle можно оставить как внутренний операторский export, если он уже существует, но не называть его client-ready.

### 11.3. UI
В Client package показывать:

- статус: Not generated / Generating / Ready for review / Blocked
- generated at
- package size
- число findings/screenshots/videos
- Preview report
- Download client evidence (.zip)
- Regenerate, если source evidence изменилось

причину блокировки.

Существующее свойство approved_for_client_delivery = false сохранить как честный human-review gate. Генерация ZIP не означает автоматическое одобрение или отправку.

### 11.4. Содержимое клиентского ZIP
Рекомендуемая плоская и Windows-friendly структура:

<domain>-qa-evidence-YYYYMMDD/
00-README.html
QA-Report.html
Findings.csv
Evidence/
Screenshots/
...
Videos/
...
Technical/
accessibility-summary.json
performance-summary.json
console-summary.txt
network-summary.json
manifest.json
Требования:

- 00-README.html и QA-Report.html открываются offline двойным кликом
- все ссылки в отчёте относительные и работают после распаковки
- screenshots открываются
- video фактически воспроизводится
- Findings.csv пригоден для Excel
- technical evidence содержит redacted summaries, а не бесконтрольный raw dump
- manifest.json содержит relative path, MIME, size, SHA-256, target/run/build IDs, capture/generation timestamps и finding references
- никаких абсолютных локальных путей
- никаких API keys, cookies, auth headers, tokens, паролей или иных secrets
- никаких symlinks и path traversal
- имена файлов безопасны для Windows
- разумная глубина каталогов и длина путей

ZIP filename: <domain>-qa-evidence-<YYYYMMDD>.zip.

PDF добавлять только если в проекте уже есть надёжный проверенный converter. Не вводить новый хрупкий PDF pipeline ради этого пакета: self-contained HTML является обязательным portable deliverable.

### 11.5. Secret scan и redaction
Использовать существующий delivery-pack secret scan. Если обнаружен секрет или неразрешённый чувствительный материал:

- не выдавать пакет как готовый
- показать Blocked: secret scan failed
- указать безопасную причину без раскрытия секрета

после redaction пакет должен быть regenerated и перепроверен.

## 12. Управление старыми и тестовыми данными
### 12.1. Место и цель
Добавить компактный раздел:

More → Data management

Не размещать destructive controls на Overview и не добавлять ещё один режим в ежедневную форму Scout.

Оператор должен легко:

- увидеть, сколько места занимают runs и evidence
- отделить production data от diagnostic/acceptance/test data
- найти кампании по дате, purpose, campaign ID и domain
- архивировать старые данные
- удалить выбранные тестовые runs вместе с их зависимыми artifacts

восстановить ошибочно удалённое до окончательной очистки.

### 12.2. Явная классификация runs
Добавить или нормализовать metadata:

production

diagnostic

acceptance

manual_test

Live E2E из этого задания помечать acceptance, а не production. Это не новый пользовательский Scout mode: тег задаётся acceptance harness/API/internal launch context.

Diagnostic/acceptance/manual-test data по умолчанию не должны искажать production counters и ежедневную History. Их можно показать отдельным Show test data.

Если старые записи не имеют purpose, не угадывать и не удалять их как test data. Показывать Unclassified и требовать явного выбора.

### 12.3. Основной UX
Показывать сводку:

- production campaigns/sites
- test/diagnostic campaigns/sites
- evidence storage size
- archived

items in Trash.

Основное безопасное действие:

Review test data

После выбора filters и items сначала показать preview:

- campaign IDs
- purpose
- dates
- unique domains
- findings
- screenshots/videos/logs
- package files
- storage to reclaim
- связанные Client work/outreach records

какие canonical sites также используются production runs.

Только после preview разрешить:

Move N selected test runs to Trash

Для одного сайта/кампании должны быть также доступны точечные действия из Details/History, но они используют тот же preview и safety rules.

### 12.4. Archive, Trash и permanent delete
Archive скрывает данные из ежедневных представлений, но сохраняет их.

Move to Trash является recoverable soft delete.

Restore полностью возвращает records, relationships и evidence visibility.

Permanently delete доступно только внутри Trash после отдельного подтверждения.

Не использовать одну кнопку Clear all.

Перед permanent delete показать точные counts и объём. Подтверждение должно называть scope, например:

Permanently delete 3 acceptance runs and 184 MB of evidence?

Не принимать unresolved glob/path или широкий filesystem root как target удаления.

### 12.5. Safety и целостность
- активный run удалить нельзя
- production data не попадает в default test cleanup
- Client work и вручную одобренный client package защищены от test cleanup
- если canonical site встречается в production и test runs, удаляются только test relationships/artifacts, а production site/history/evidence сохраняются
- shared evidence удаляется только при отсутствии оставшихся references
- операция idempotent и переживает повтор после interruption
- DB/index/manifest/filesystem изменяются согласованно
- после cleanup не остаются orphan files, broken links или stale counters
- Activity получает одно понятное cleanup event без дублей
- сохраняется минимальный audit tombstone: scope, IDs, counts, deleted at и result, но без удалённого client content

никакие cleanup artifacts не попадают в Git.

### 12.6. Acceptance cleanup
После того как live E2E, persistence и ZIP acceptance полностью доказаны:

- открыть More → Data management
- отфильтровать созданные в этом задании acceptance runs
- проверить preview и доказать, что production data не выбрана
- переместить acceptance runs в Trash
- проверить обновление Overview/History/Needs attention/storage counters
- восстановить один run и доказать возврат Details/evidence/package metadata
- снова переместить его в Trash
- permanent delete выполнять только для специально созданных test/acceptance данных, если это безопасно и явно входит в acceptance

доказать отсутствие orphan evidence и сохранность всех production records.

В финальном handoff указать, какие тестовые данные оставлены в Trash, какие удалены окончательно и сколько места освобождено.

## 13. Обязательные automated tests
Добавить или обновить tests минимум для:

- единых трёх источников и общего Start Scout
- скрытия технических modes из daily UI
- совместимости legacy API/CLI/config
- pinned target semantics
- input counts: valid / unique / duplicate / rejected
- canonicalization www, scheme, trailing slash и tracking query
- rejection 0.1, localhost, loopback, private/reserved IP/domain
- одна текущая Needs-attention row на domain
- отдельные unique-domain и attempt-event counters
- evidence → finding links
- honest missing/capture-failed states
- public email provenance
- запрета guessed email
- отсутствия outreach draft без actionable finding
- draft, основанного только на verified findings
- site-scoped client pack без cross-target data
- safe ZIP names и Windows extraction
- path traversal/symlink protection
- Content-Type и Content-Disposition download endpoint
- manifest hashes
- secret-scan blocking
- persistence после restart
- purpose classification и скрытие test data из production counters по умолчанию
- cleanup preview
- защита active/production/client-linked records
- mixed production/test target cleanup без потери production history
- Archive / Trash / Restore
- idempotent interrupted cleanup
- shared evidence reference protection
- orphan detection и корректное обновление counters/Activity

keyboard/focus/responsive browser acceptance для изменённых экранов.

Модули Playwright в лёгких jobs должны импортироваться через уже исправленный pytest.importorskip("playwright") pattern, чтобы не повторить ошибку первого CI прогона PR #51.

## 14. Точные live E2E цели
Фиксированные ранее не анализировавшиеся цели:

A. Plausible Analytics
URL: https://plausible.io/

- тип: небольшой независимый B2B SaaS, web analytics
- безопасный сценарий видео: homepage → View live demo → применить один read-only filter/date control → очистить filter
- expected public email assertion: hello@plausible.io

expected source: https://plausible.io/contact

B. Userlist
URL: https://userlist.com/

- тип: B2B SaaS, email automation для SaaS-компаний
- безопасный сценарий: homepage/docs navigation без demo booking и без форм
- expected public email assertion: support@userlist.com

expected source: https://userlist.com/docs/

C. Nolt
URL: https://nolt.io/

- тип: B2B SaaS, feedback/roadmap/changelog
- безопасный запасной сценарий видео: https://feedback.nolt.io/ → search SSO или read-only filter → clear
- не голосовать и не создавать suggestion
- expected public email assertion: hello@nolt.io

expected source: https://feedback.nolt.io/ или https://nolt.io/help/privacy

Если сайт изменился, стал login-only, выставил CAPTCHA или запретил безопасный public flow, зафиксировать это честно и продолжить остальные цели. Для замены взять другой новый небольшой B2B SaaS и в отчёте явно указать причину и новый домен.

## 15. Точный live E2E сценарий
### 14.1. Preflight
Подтвердить:

- clean expected worktree
- runtime build соответствует тестируемому commit
- health green
- deep-readiness green
- Chromium real launch
- network ready
- evidence directory writable
- Dashboard и Observer смотрят на одну актуальную базу

нет активной конфликтующей кампании.

### 14.2. Find websites
Через новый UI выполнить настоящий discovery:

- countries: Canada / Switzerland или близкий EU/NA выбор
- business type: B2B SaaS
- signals: user feedback, roadmap, changelog

Maximum sites: малый bounded limit.

Цель — проверить реальное автономное discovery, а не тайно подставить URL. Предпочтительный ожидаемый кандидат — nolt.io, но exact domain нельзя hardcode в production pipeline.

Если discovery возвращает другой новый подходящий домен:

- провести его через pipeline
- в отчёте указать фактический результат

nolt.io всё равно проверить через file import ниже.

Если discovery не возвращает ни одной корректной цели, это live defect: сохранить evidence, добавить regression test и исправить минимально.

### 14.3. Paste URLs
Передать:

https://plausible.io/
Проверить preview counts и запустить тот же Scout.

### 14.4. Upload file
Создать временный CSV/XLSX через поддерживаемый UI contract со строками:

https://userlist.com/
https://nolt.io/
https://www.nolt.io/
0.1
http://localhost/
До старта UI должен показать:

- Userlist и Nolt как валидные canonical targets
- www.nolt.io как duplicate
- 0.1 как malformed/non-public target

localhost как private/reserved target.

Invalid строки не должны появиться в History как сайты.

### 14.5. Cross-source deduplication
Повторно передать https://plausible.io/pricing?utm_source=scout-e2e через другой источник.

Ожидание:

- не создаётся вторая текущая строка Plausible в History/Needs attention
- attempt/source event сохраняется в target history
- counters ясно различают один unique site и повторную попытку

система не теряет ранее сохранённое evidence.

### 14.6. Проверка каждого результата
Для каждого fixed target и фактического discovery target пройти:

Start Scout → queue/progress → result → Details → findings → evidence → contact → talking points/draft → client package

При No actionable findings:

- не выдумывать defect
- не создавать outreach draft

evidence и honest result всё равно сохраняются.

### 14.7. Реальная проверка ZIP
Для каждого сайта с доступным evidence:

Нажать Preview report.

Нажать Download client evidence (.zip) именно через UI.

Проверить HTTP response headers и безопасное filename.

Распаковать ZIP в новый пустой временный каталог стандартным Windows-compatible способом.

Открыть 00-README.html.

Открыть QA-Report.html offline.

Открыть все screenshots.

Воспроизвести каждое включённое video.

Открыть Findings.csv.

Проверить относительные ссылки.

Пересчитать SHA-256 и сравнить с manifest.

Проверить отсутствие данных других domains.

Проверить отсутствие secrets и абсолютных путей.

Нельзя считать проверкой только существование ZIP или успешный return code.

### 14.8. Persistence
После завершения:

- штатно перезапустить Dashboard/service
- повторно открыть History и Details
- доказать сохранение findings, screenshots, playable video, contact provenance, draft и package metadata
- повторно скачать и распаковать хотя бы один клиентский ZIP
- проверить Activity на отсутствие дублированных production events

подтвердить runtime build и restart truthfulness.

## 16. Исправление live-дефектов
Если E2E обнаружит проблему:

- сохранить воспроизводимое evidence
- написать failing regression test
- внести минимальное исправление
- повторить targeted test
- повторить соответствующий live-шаг

не расширять scope догадками.

Не маскировать blocked/failed состояния ручной правкой output files.

## 17. PR и завершение
Предпочтительно выполнить последовательно три небольших slice, но завершить весь пакет, а не остановиться после первого:

Unified Scout UX

Truthful Results + Contact/Outreach + Client Package

Live E2E fixes and acceptance

Можно объединить близкие изменения, если diff остаётся проверяемым. Для каждого PR:

- targeted tests
- обязательные CI jobs
- исправление CI до green
- merge

актуализация main.

В финале:

- полный suite
- CI
- merge SHA
- post-merge runtime restart
- post-merge smoke

чистое дерево.

## 18. Финальный handoff
Обязательная таблица:

Site	Source	Run/target ID	Result	Verified findings	Screenshots	Video	Public email + source	Draft	Client ZIP	ZIP unpack/playback	Blocker
Отдельно указать:

- commits, PRs и merge SHAs
- targeted test results
- полный suite
- CI
- post-merge smoke
- фактический runtime build
- evidence IDs/relative refs
- client ZIP filename, size и manifest hash
- что реально открылось и воспроизвелось
- какие public emails реально извлечены и откуда
- какие drafts созданы и почему
- где draft намеренно не создан
- что не сработало
- какие live-дефекты найдены и исправлены
- какие acceptance/test runs архивированы, перемещены в Trash или удалены
- сколько места освобождено и как проверена сохранность production data

какие объективно остались.

## 19. Definition of Done
Задача завершена только если одновременно выполнено всё:

- один понятный Scout вместо набора технических режимов
- три источника используют общий pipeline
- legacy API/CLI/data не сломаны
- Overview упрощён в согласованных границах
- invalid target 0.1 и private/reserved values не выглядят как сайты
- History/Needs attention дедуплицированы и имеют честные counters
- фиксированные live-цели реально пройдены либо имеют доказанный внешний blocker
- минимум одно реальное video открывается inline и после скачивания
- screenshots и technical summaries открываются из Details
- публичный email имеет source URL либо честно отсутствует
- talking points/draft основаны только на verified findings
- ничего не отправлено
- site-scoped client ZIP скачан через UI
- ZIP распакован, отчёт открыт offline, screenshots открыты, video воспроизведено, hashes совпали
- client ZIP не содержит внутренних draft/contact notes, secrets или данные других sites
- данные переживают restart
- test/diagnostic/acceptance data отделены от production
- старые или тестовые runs можно безопасно preview, архивировать, перемещать в Trash и восстанавливать из Dashboard
- test cleanup не удаляет production/client-linked data и не оставляет orphan evidence
- targeted tests, full suite, CI, merge и post-merge smoke подтверждены
- live artifacts не попали в Git
