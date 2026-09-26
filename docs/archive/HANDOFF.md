# Dota Esports Intelligence Platform — Handoff Package (архив)

> **Историческая копия от 2026-09-18, не актуальное состояние проекта.** Не выполнять назначения и не восстанавливать статусы из этого файла. Начать с [AGENTS.md](AGENTS.md) и [HANDOFF_PROMPT.md](HANDOFF_PROMPT.md). Ниже сохранён исходный пакет для истории; реализованное ядро и действующие решения описаны в отдельных документах репозитория.

**Что это:** полная передача проекта другому AI-агенту (или разработчику). Это архитектурный пакет и план, **не код**.
**Дата исследования источников:** 2026-09-16 (Asia/Singapore, часы инструмента). Консолидировано: 2026-09-18.
**Статус:** все архитектурные решения и ADR — **PROPOSED**. Владелец (solo-founder) ещё **не утвердил** ни цель прогноза, ни стек, ни gates.
**Ограничения проекта (подтверждены владельцем):** только **бесплатные** источники данных; **личный исследовательский** инструмент.
**Рабочий язык с владельцем:** русский.

---

## 0. Как читать этот файл

- Это консолидированная копия 12 корневых документов и 5 ADR в одном файле, для удобной передачи.
- Разделы **Part 1 … Part 13** — исходные документы (названия сохранены). Внутренние относительные ссылки вида `X.md` переписаны в текст с указанием имени файла: разрешать их внутри одного файла невозможно, оригиналы лежат в `dota-intelligence/`.
- Канонический вид пакета — каталог `dota-intelligence/` (и архив `dota-intelligence-plan.zip`).
- Все задачи в бэклоге имеют статус `Planned`/`Proposed`. **Ни одна задача не выполнена и не выполняется.**

## 1. Задача для принимающего агента

Продолжить проект строго в логике исходного ТЗ: сначала **PRD-001** (согласование цели/первой карты/гейтов/правил cutoff с владельцем), затем последовательно первые 10 задач. Не выдавать владельцу 50 задач сразу: определять CURRENT EPIC → CURRENT TASK → WHY IT MATTERS → DEPENDENCIES → NEXT ACTION и вести последовательно.

**Текущая точка (после передачи):**

- CURRENT EPIC: `EPIC 00 — Product specification`
- CURRENT TASK: `PRD-001` (P0, Proposed)
- WHY IT MATTERS: без утверждённой цели прогноза, scope и измеримых gates нельзя ни собирать данные, ни обучать модель — иначе все дальнейшие метрики несопоставимы.
- DEPENDENCIES: нет.
- NEXT ACTION: владелец утверждает или правит предложения из Part 1 (PRODUCT.md); только после этого — `SRC-001`.
- Далее: **STOP и ожидание команды владельца.** Автоматически реализовывать задачи нельзя.

## 2. Что категорически нельзя

1. Начинать писать код по этому пакету без явной команды владельца.
2. Объявлять ретроспективную реконструкцию «настоящим прогнозом» или backdated live-прогнозом.
3. Использовать данные с `available_at > cutoff`; подставлять фактический состав целевого матча и финальную статистику в pre-match признаки.
4. Обещать точность, калибровку, прибыльность, SLA или свежесть — ни один бесплатный источник не даёт гарантий; метрик проекта пока не существует.
5. Строить critical path на непроверенном источнике (PandaScore исключён до письменного разрешения провайдера; upcoming через Liquipedia — только после access/rights/coverage gate).
6. Скрапить HTML в обход ToS, обходить авторизацию, выдумывать credentials.
7. Автоматически размещать ставки: market-модуль — **ANALYSIS only**.
8. Молча менять архитектуру: обнаружена проблема → STOP → объяснение → альтернативы → решение владельца (+ ADR).

## 3. Контекст: что уже решено владельцем

- Бюджет: только бесплатные источники (платные данные не в critical path).
- Аудитория: личный исследовательский инструмент, без публичной перепродажи данных и прогнозов.
- Стиль работы: «минимально необходимая сложность при максимальной проверяемости результата»; MVP → измерение → улучшение → следующий слой.
- LLM — для неструктурированных данных, объяснений и экспертного слоя; математический предиктор — отдельные модели.

---


## Part 1 — Product Vision и определение MVP

Статус: **PROPOSED — на согласование владельцу**. Это проектирование, не реализованный продукт. Дата пакета: 2026-09-16, Asia/Singapore. Бюджет источников: только бесплатные; аудитория: личный исследовательский инструмент. Бесплатные API не означают бесплатное вычисление, хранение и сопровождение: первый deployment предполагается на имеющемся компьютере, без обещания облачного free tier.

### 1. Видение

Dota Esports Intelligence Platform — воспроизводимая система сбора и интерпретации информации о профессиональной Dota 2. Центральный продукт — вероятность конкретного исхода с зафиксированными входными данными, временем доступности, версией модели и последующей проверкой результата. Не «LLM, угадывающая победителя», не обещание заработка.

Ценность для владельца: открыть встречу, увидеть доступные на тот момент сведения, прогноз и ограничения, затем проверить, насколько такие вероятности соответствовали исходам. TEAM / PLAYER / DRAFT / GAME / MARKET — предметные измерения; EXPERT OPINION и TOURNAMENT CONTEXT — отдельные объяснимые источники сигналов.

**Основной differentiator:** собственная история «что было известно → что предсказано → что произошло», в том числе по составам, драфтам и экспертным утверждениям. Более сложная модель и больше графиков сами по себе не создают преимущества.

### 2. Архитектурный анализ: что необходимо изменить в исходном порядке

| Напряжение в исходном плане | Предлагаемое решение | Почему |
|---|---|---|
| OpenDota-only и автоматические будущие встречи | OpenDota для истории; отдельный проверяемый schedule adapter | В рассмотренной документации нет upcoming-календаря; подробнее SOURCES.md |
| «Match», «Series», «Game» пересекаются | Явно разделить scheduled fixture, серию и карту | Нельзя сравнивать вероятность карты с коэффициентом серии |
| Snapshots появляются лишь в MVP 2 | Минимальные снимки и model version — с прототипа | Без них нельзя доказать отсутствие backdating и воспроизвести прогноз |
| Хочется CatBoost сразу, но нужен baseline | Prior → Logistic Regression → CatBoost challenger | Champion выбирается измерением; CatBoost не обязан победить |
| Точные составы до матча | Известный/объявленный/предположенный состав + происхождение и давность | Фактическую пятёрку часто узнаём позже; её подстановка в историю создаёт утечку |
| LLM-объяснения уже в MVP | Сначала шаблонные evidence-backed объяснения | Не требует платного API и не генерирует статистику |
| Автоматизация только в конце | Простое автопополнение и оценка исходов — в полном MVP; богатый event engine позже | Это часть определения автоматизированного продукта |
| Live и heatmaps выглядят как очередные API-поля | Отдельные access/rights/data-parity gates | Наличие endpoint не доказывает покрытие профессиональных игр |

Это предложения, а не принятые за владельца решения. Изменение оформляется ADR до реализации.

### 3. Единица прогноза

**Рекомендуемый MVP target:** P(Team A выигрывает первую карту Series | карта будет сыграна), до начала её драфта. Team A закрепляется при создании fixture по канонической идентичности, а не меняется вместе с Radiant/Dire. Вторая вероятность = 1 − первая только для бинарного спортивного исхода сыгранной карты.

Почему первая карта: не нужны будущие драфты, вероятность достижения следующих карт и модель зависимости карт в серии. Предматчевый прогноз всей BO3/BO5 — другой target; он добавляется в MVP 2. Если владелец выбирает series win с первого дня, потребуется пересмотреть PRD-001, dataset и первые задачи, а не переименовать карту в серию.

Время cutoff — время решения на реально полученном состоянии, пока источник подтверждает pre-draft. Если статус сомнителен или драфт уже мог начаться, система воздерживается. Исторический proxy cutoff и доступность расписания явно маркируются как реконструкция, не как наблюдавшийся прогноз. Forfeit, walkover, отмена и void — отдельные статусы, не игровые победы для обучения.

### 4. Этапы и рабочий результат

| Этап | Что пользователь получает | Что не считается выполненным |
|---|---|---|
| Прототип: первые 10 задач, часть MVP | Реальная историческая первая карта → as-of Team/Player features → prior/LR → immutable prediction → локальная страница с пометкой retrospective_reconstructed | Нет заявления, что прогноз сделан тогда; нет полноценного upcoming-продукта |
| MVP | Автообнаружение будущих встреч в утверждённом scope; первая карта; известный roster/fallback; recent form, player form, historical hero pool, patch; LR и CatBoost comparison; calibration; FastAPI; простой UI; оценка результатов | Не live, не драфтовая модель, не ставки, не публичный SaaS |
| MVP 2 | Драфт-снимки, synergy, tournament context, более глубокий patch analysis; отдельная series probability | Не требуется neural ensemble |
| MVP 3 | Права на корпус → извлечение экспертных мнений → ссылки/таймкоды → track record и проверяемые сигналы | Нет гарантии автоматической транскрипции чужих стримов |
| Future A: исходный MVP 4 | Разрешённый live feed, отдельная live-модель, trajectory | Только после доказанного pro-live access и train/serve parity |
| Future B: исходный MVP 5 | Heatmaps и проверенные spatial features | Не имитация траекторий из итоговой статистики |
| Future C: исходный MVP 6 | Законные timestamped odds, margin, edge, out-of-sample market backtest | ANALYSIS only; отсутствие данных = no-go, не синтетическая прибыль |
| Future D: исходный MVP 7 | LLM analyst с evidence, настраиваемые уведомления, расширенная событийность | Никакого самостоятельного размещения ставок |

GNN, embeddings, temporal transformers, online learning, RL и knowledge graph — только гипотезы после качественного baseline; отдельной обязанности реализовать каждый подход нет.

### 5. Scope первого полноценного MVP

В PRD-001 владелец фиксирует набор профессиональных турниров/лиг и период проверки до просмотра результатов модели. Scope обнаруживается по правилам источника, а не ручным созданием каждого матча. Не обещается покрытие всей мировой сцены. На первой странице показываются:

- Team A / Team B; турнир, стадия при наличии, формат серии и **target: первая карта**;
- вероятности либо «недостаточно данных»;
- фактическое время расчёта, cutoff, возраст данных, модель и режим оценки;
- известный на cutoff состав со статусом confirmed/announced/inferred/unknown;
- recent form, player form, patch, historical hero pool — только доступные сведения;
- объяснение с внутренними evidence IDs; отсутствие данных не заменяется выдумкой;
- история прогнозов и результат после завершения.

Player/Team/Tournament полноценные страницы — MVP 2, но минимальные идентичности и статистика для карточки матча обязательны в MVP. Публичные аккаунты, подписки, биллинг, коммерческая перепродажа данных — вне scope.

### 6. Gates: предлагаемые критерии, не достигнутые показатели

| Gate | Проверка | Решение при провале |
|---|---|---|
| История и права | Доступны реальные исторические game1, provenance и допустимый способ хранения; измерены пропуски | Нет пригодной истории — STOP до INF-001 |
| Upcoming | API-доступ легален, timestamps и identity пригодны; не HTML scraping | История есть, upcoming нет — завершить только ретроспективный прототип |
| Temporal integrity | Критических нарушений cutoff = 0; неоднозначных identity среди оцениваемых записей = 0 | Любая утечка блокирует качество-прогнозы |
| Operational MVP | Покрытие пригодным pre-draft прогнозом ≥90% на заранее зафиксированных 30 последовательных eligible game1 fixtures; все пропуски входят в знаменатель | Сузить/изменить scope только новым решением и новым окном, не удалять неудобные записи |
| Freshness | Измерены source publish lag, ingestion lag и data age; предельный возраст каждого поля утверждён в SRC-001; stale случаи дают отказ/обозначенный fallback | Нет численного SLO, подкреплённого наблюдениями, — gate не завершён |
| Model | Prior/LR/CatBoost проверены одним протоколом; champion выбран на tuning, calibrator отдельно; frozen test оценивается один раз; precision/минимальный эффект утверждены заранее | Недостаточная выборка — insufficient evidence; нет полезного выигрыша — baseline/research, не усложнение |
| Reliability | Повторный запуск не меняет старые снимки; crash recovery, результат и коррекция не теряются; backup восстановлен | Доработка существующего этапа |

30 fixtures — **операционная проверка**, не достаточная выборка для статистического доказательства качества модели или прибыльности. Размер frozen test выбирается по требуемой точности оценки и зависимости наблюдений; универсальной магической численности нет. Model gate использует доверительные интервалы парных разностей log loss/Brier и reliability diagram, а не одну accuracy. Конкретные SLO и ML-пороги ещё не утверждены — это результат PRD-001/SRC-001, не скрытое допущение.

Метрики coverage считаются относительно замороженного списка eligible fixtures внешнего контрольного источника/аудита, а не только того, что наш pipeline нашёл. Отдельно: discovery coverage, entity mapping coverage, feature availability, served prediction coverage и abstention rate.

### 7. Reuse / build / defer

- **Переиспользовать:** библиотеки БД/API/ML; справочники OpenDota после проверки лицензий; точечные MIT-компоненты amarcu после кодаудита; готовый replay parser вместо собственного протокола.
- **Написать самостоятельно:** каноническую модель, temporal identity/roster resolution, feature contracts, as-of evaluator, snapshot ledger, own calibration/backtest protocol, экспертные claims с evidence и outcome resolution.
- **Не форкать платформу целиком:** deployment-зависимости чужих проектов не равны потребностям solo-founder.
- **Отложить:** live, spatial, market, expert ingestion до gates; Redis, microservices, Kafka, Kubernetes, ClickHouse, GPU и neural stack до измеренного bottleneck.

Источники и сравнение шести reference-проектов: SOURCES.md (SOURCES.md). Полная декомпозиция: BACKLOG.md (BACKLOG.md). Следующая точка решения: FIRST_10_TASKS.md (FIRST_10_TASKS.md), PRD-001. После выдачи этого пакета — ожидание команды, без реализации.

---


## Part 2 — System Architecture

Статус: PROPOSED. Все изменения архитектуры согласуются с владельцем через ADR. Здесь только проект; ни приложение, ни jobs не запущены.

### 1. Минимальная форма

**Модульный Python-монолит + одна PostgreSQL + локальный каталог артефактов.** Один кодовый репозиторий; API и ingestion worker имеют разные жизненные циклы, но используют одни контракты и БД. Отдельный offline train/evaluate entrypoint не равен отдельному сервису. Никаких брокеров и распределённого exactly-once.

```text
OpenDota history       Liquipedia API (conditional access gate)
       |                              |
       +-------- source adapters -----+
                        |
          raw capture + source metadata
                        |
           validation / quarantine
                        |
         normalization + identity versions
                        |
                 PostgreSQL
          raw / canonical / evidence
                        |
               as-of feature builder
                        |
           FeatureSnapshot + ModelVersion
                        |
           prediction service + calibrator
                        |
         immutable PredictionSnapshot ledger
                        |
             FastAPI + simple local UI
                        |
          result resolution / evaluation
```

Future добавляет экспертные, live и market adapters, но они не пишут напрямую в модели. Все проходят availability/provenance/rights contract. Domain event из изменения нормализованного состояния не требует Kafka.

### 2. Технологические решения

| Компонент | Предложение для MVP | Обоснование / условие усложнения |
|---|---|---|
| Язык | Python | Одна среда для ingestion, ML и API |
| БД | PostgreSQL, typed relational canonical + JSONB raw/snapshots | FK, unique, транзакции; JSONB не заменяет модель сущностей |
| Доступ к БД | SQLAlchemy + Alembic как кандидаты | Единые migrations; окончательные совместимые версии фиксируются в INF-001 |
| API / validation | FastAPI + явные schema contracts | Read-only API отделён от вычисления/получения данных |
| DataFrame | pandas | Один engine; Polars вводить лишь после профилирования памяти/времени |
| ML | scikit-learn prior/LR; CatBoost CPU challenger | Не требует GPU; sklearn для независимой оценки и calibration |
| Neural | PyTorch — отложить | Только если temporal/spatial эксперимент выигрывает у tabular baseline |
| UI | Server-rendered templates в FastAPI | Минимум toolchains для личного инструмента; React/Next.js — осознанная замена при сложном live UI |
| Background | Сначала sync-once contract; будущий отдельный локальный worker | Не помещать ingestion в HTTP request или каждый web worker |
| Broker/cache | Нет Redis | PostgreSQL checkpoint/state + файловые артефакты; Redis/RQ после измеренного queue bottleneck |
| Packaging | Git, pinned dependencies, Docker Compose local | API/worker/DB логически изолированы, но deployment простой |
| Model artifacts | Каталог + checksum/manifest в БД | Не нужен отдельный MLflow/feature-store сервис на старте |

Основания: [PostgreSQL constraints](https://www.postgresql.org/docs/current/ddl-constraints.html), [range types](https://www.postgresql.org/docs/current/rangetypes.html), [FastAPI Docker](https://fastapi.tiangolo.com/deployment/docker/), [CatBoost categorical features](https://catboost.ai/docs/en/features/categorical-features), [pandas as-of merge](https://pandas.pydata.org/docs/reference/api/pandas.merge_asof.html). Документация online/stable, может измениться; точные версии сейчас не выбираются.

#### Celery / RQ / APScheduler: не смешивать scheduler и queue

- **APScheduler:** кандидат для одного локального процесса в будущем deployment, без broker. Для исследованной 3.x ветки совместное использование job store несколькими процессами приводит к ошибкам — [FAQ](https://apscheduler.readthedocs.io/en/3.x/faq.html), [guide](https://apscheduler.readthedocs.io/en/3.x/userguide.html). Не распространять это утверждение автоматически на другую major version.
- **RQ:** простая task queue с Redis/Valkey; добавляет сервис, пока не нужен — [docs](https://python-rq.org/docs/).
- **Celery:** broker-based queue; более сложные workflows пока не оправданы — [brokers](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/index.html).

Рекомендация по future local worker: один владелец ingestion с checkpoint и идемпотентными обработчиками; APScheduler оценить при реализации после version pinning, без внедрения очереди заранее. В текущей среде scheduled/recurring tasks недоступны: здесь они не создаются и не запускаются; доступен только разовый исследовательский workflow. Это ограничение среды помощника, не отказ от требования автопополнения будущего локального продукта.

### 3. Контракт source adapter

Каждый adapter объявляет source_id, schema_version, capabilities, auth_mode, terms_reference, allowed_purposes, quota_policy, cursor semantics и timezone. Способен вернуть batch записей вместе с provider IDs, сырым payload, временем наблюдения, source publication time при наличии, retrieval status, next_cursor и completeness flags.

**Не универсальный сверхфреймворк:** достаточно небольшого интерфейса `fetch → validate → normalize`. Специфичные поля источника сохраняются в raw; canonical consumers ничего не знают об endpoint-именах. Пустой ответ не равен «матч отменён» и не равен успеху полного охвата.

Обязательные механизмы:

1. bounded timeout; retry с exponential backoff/jitter для transient failures, `Retry-After` при наличии; auth/permission errors — остановка, а не бесконечный retry;
2. общий quota budget по источнику для всех endpoint, журнал headers и cache; не провоцировать 429 намеренно;
3. raw hash + request metadata; секреты, cookies и API-ключи в raw/log не сохраняются;
4. pagination cursor + overlap window для поздних исправлений; watermark только после commit;
5. natural-key uniqueness и transactional upsert canonical revision; ingestion delivery at-least-once, обработка идемпотентная;
6. карантин повреждённых строк, отдельная data-quality причина, schema drift contract tests;
7. source outage → marked stale/fallback/abstain; никакого тихого переключения на семантически другой набор данных.

Raw payload можно дедуплицировать по hash, но повторные fetch observations и их времена сохраняются отдельно: одинаковое содержимое на разных retrievals — не одинаковое событие получения.

### 4. События и конечные автоматы

Минимальный MVP: обнаружение → нормализация → пригодность forecast → прогноз → результат → оценка. Изменение состояния и запись события совершаются одной транзакцией. Пока worker один, обработка может быть последовательной; Durable outbox нужен при внешних уведомлениях/нескольких consumers, не раньше.

| Объект | Состояния | Критические случаи |
|---|---|---|
| Fixture/Match | discovered → scheduled → in_progress → completed | postponed/cancelled/forfeit/unknown; возврат к scheduled после переноса не стирает историю |
| Game | placeholder → draft → running → finished | remake/abandoned/void/corrected; повторная карта получает собственную идентичность |
| Forecast | eligible → computed → stored → served → evaluated | ineligible/abstained; failed store означает не served |
| Ingestion | pending → fetched → validated → normalized | retryable/dead-letter/quarantined; cursor не продвигается при неполной транзакции |

У событий есть aggregate_id, source_revision, event_type, occurred_at, observed_at и dedup_key. Источник может пропустить draft/start и сразу дать result: автомат не изобретает промежуточные timestamps. Late result correction создаёт новую revision и evaluation revision; старые predictions остаются неизменными.

Identity resolution: provider ID → canonical mapping; затем проверяемые сочетания league, team pair, series и времени. Fuzzy name — лишь кандидат; при неоднозначности карантин, а не уверенное объединение. Нулевой/отсутствующий provider ID не становится общей сущностью «Team 0».

### 5. Prediction API / presentation

Контракт ответа: target_type, target_id, team_a_id, team_b_id, probability_a/b или abstention, forecast_phase, computed_at, cutoff_at, evaluation_mode, model_version_id, feature_snapshot_id, prediction_snapshot_id, roster_status, freshness и evidence_refs. Нельзя выдавать значение без указания target: первая карта или серия.

Предлагаемые ресурсы: список встреч, карточка встречи, история её snapshots, карточки команд/игроков, health/data-quality. Конкретный HTTP routing — задача API-001, не реализованный endpoint. Web чтение возвращает уже сохранённый snapshot; повторный GET не обучает модель и не обращается к внешнему API. Mutating recompute — локальный управляемый workflow с уникальным idempotency key, не публичный GET.

Показ: всегда время последнего обновления, missing fields, evidence и отсутствие forecast при невалидном входе. MVP explanation — фактические feature values и, где доступно, модельные contributions, не причинные утверждения. Никакой фразы «сильнее психологически» из длительности серии.

### 6. Ошибки, безопасность, сопровождение

- Структурные логи с run_id/source_id/entity_id; без секретов и полного текста приватных данных.
- Health различает процесс жив, БД доступна, данные свежи, forecasts пригодны; HTTP 200 не означает качественные данные.
- Метрики: fetch errors, quota remaining, lag, missing IDs, quarantine share, coverage denominator, snapshot failure, calibration/drift. Порог alert — отдельное согласование после наблюдения.
- БД и UI локально по умолчанию. Публичное размещение требует отдельного security gate, auth, TLS, secret handling и rights review; здесь ничего не публикуется.
- Backup raw/canonical/model artifacts с manifest; тест восстановления входит в MVP, не только наличие backup-файла.
- Условия источников и retention могут требовать удаления. Prediction ledger immutable логически, но legal erasure имеет приоритет: сохраняются разрешённые hash/provenance tombstones и отметка неполной воспроизводимости, а не запрещённый контент.

### 7. Целевая структура репозитория (не созданный код)

```text
dota-intelligence/
  README.md  PRODUCT.md  ARCHITECTURE.md  DATA_MODEL.md
  FEATURES.md  ML.md  EXPERT_ENGINE.md  LIVE.md  BACKTEST.md
  SOURCES.md  BACKLOG.md  FIRST_10_TASKS.md
  docker-compose.yml                 # будущий файл INF-001
  src/
    ingestion/ normalization/ features/ models/ prediction/
    experts/ live/ market/ backtest/ api/
  tests/
  frontend/                          # позднее, если выбран React
  scripts/                           # будущие одноразовые entrypoints
  docs/adr/
```

Сейчас в пакете только документы. Не создавать пустые сервисы и абстракции Future заранее. Границы модулей — возможность замены источников и контроля leakage, не микросервисы.

---


## Part 3 — Data Architecture и Data Model

Статус: PROPOSED; концептуальная/логическая схема, не SQL migrations. Физически MVP реализует только используемое ядро; остальные сущности — эволюционный контракт.

### 1. Слои хранения

1. **Raw:** неизменяемый payload источника + отдельные retrieval observations, hash и rights policy. Нужен для replay нормализации и расследования.
2. **Canonical:** типизированные реляционные сущности, PK/FK, ограничения идентичности и версий. JSONB только для расширяемых payload, не вместо FK.
3. **Derived:** измерения, as-of feature snapshots, модели, predictions/evaluations. Derived можно пересчитать новой версией, опубликованный snapshot — не перезаписать.
4. **Artifacts:** model binary, dataset manifest, крупные replay/spatial файлы локально; БД содержит URI относительно разрешённого storage root, checksum, format/version/rights. Массовые позиции не загружать в JSONB одного матча.

Все времена — UTC `timestamptz`, исходная timezone и original timestamp сохраняются. Неизвестное время — NULL + причина, не фиктивная полночь. Счётчики provider IDs хранить без потери точности; наружу большие внешние IDs допустимо сериализовать строками. Служебные IDs — UUID; внешний ID уникален только внутри источника и типа сущности.

### 2. Бивременность и фактическая доступность

| Поле | Значение |
|---|---|
| event_time / valid_from, valid_to | Когда событие произошло / факт действовал в игровом мире |
| source_published_at | Когда источник заявил о публикации; NULL, если неизвестно |
| observed_at | Когда наш collector фактически получил эту версию |
| ingested_at | Когда версия записана в БД |
| available_at | Когда версия после необходимой обработки стала доступна prediction pipeline; не раньше observed_at/ingested_at и готовности зависимостей |
| system_from, system_to | Интервал знания о версии в нашей системе; новая коррекция закрывает старую системную версию |
| cutoff_at | Граница информации конкретного forecast, а не время будущего события |

Для strict prospective forecast все используемые версии имеют `available_at <= cutoff_at`; публикации с явно будущим source_published_at требуют карантина/разбора clock skew. У historical reconstructed dataset нет права выставлять observed_at в прошлое. Он хранит фактическое retrieval now и отдельный `assumed_available_at` + lag_policy_version. Оценка режима реконструкции всегда отделена от реального point-in-time replay.

Обнаруженный сейчас старый трансфер не становится известным модели вчера. Прошлый roster «последние пять сыгравших» — inference из прошлых матчей, а не confirmed roster. Справочники/patch assignments также версионируются: сегодняшняя исправленная таблица не заменяет прошлую без отметки.

### 3. Семантика соревнований

```text
Tournament 1 ── N TournamentStage 1 ── N Match
                                           | 0..1
                                         Series 1 ── N Game
Team 1 ── N Roster 1 ── N RosterMembership N ── 1 Player
Game 1 ── N GameParticipant N ── 1 Player
Game 1 ── N DraftAction / GameEvent / PlayerPerformance
Prediction 1 ── N PredictionSnapshot N ── 1 FeatureSnapshot
PredictionSnapshot N ── 1 ModelVersion
PredictionSnapshot 1 ── N PredictionEvaluation
```

**Match:** запланированная встреча, не отдельная карта; именно здесь доступны upcoming и TBD до появления игровых IDs. **Series:** соревновательное BO-исполнение fixture, связанное с одним Match; создаётся, когда известен формат/исполнение, может существовать до карт. **Game:** карта, `map_number`; provider `match_id` обычно отображается сюда, а не на наш Match. Series без сопоставленного fixture хранится как orphan с причиной; не плодить искусственные расписания.

В MVP прогнозируем game1 placeholder при условии сыгранной карты. Несыгранные будущие карты не создаются как завершённые наблюдения. Номер первой карты нельзя угадывать по первой найденной записи при неполной серии; такие строки исключаются с явной причиной. `attempt_number` позволяет хранить remake той же карты; result rules выбирают counting attempt.

### 4. Справочник сущностей: поля и ограничения

Обозначения стадий: **M** — ядро MVP, **2** — MVP 2, **3** — MVP 3, **F** — Future. PK = `id`, если не указано иначе; versioned-объекты дополнительно имеют temporal envelope из §2 и provenance.

#### Источники и нормализация

| Сущность | Стадия | Основные поля / связи / ограничения |
|---|---|---|
| DataSource | M | name, adapter_version, capabilities, terms_url, terms_checked_at, allowed_purposes, retention_policy; API-token вне БД |
| IngestionRun | M | source_id FK, started_at, finished_at, status, cursor_before/after, error_summary, quota_headers |
| RawPayload | M | source_id, endpoint_kind, content_hash, payload_json, schema_version; unique(source_id, content_hash); hash включает каноническое представление |
| SourceObservation | M | run_id, raw_payload_id, provider_entity_id/type, request_fingerprint, observed_at, source_published_at; разные retrievals не дедуплицируются только по payload |
| EntityMapping | M | source_id, entity_type, external_id, canonical_id, mapping_version, status, evidence_id; unique active(source,type,external_id); type-aware FK через typed mapping tables либо registry |
| EvidenceRecord | M | observation_id, field_path/span, entity_revision_id, transformation_version, rights_policy; внутренний первоисточник объяснения |
| QuarantineRecord | M | observation_id, reason_code, details, resolved_by, resolution_revision; неоднозначные данные не входят в eval |
| ProcessingCheckpoint | M | source_id, job_kind, cursor, revision, committed_at; unique(source,job_kind) |
| DomainEvent / OutboxDelivery | 2/F | aggregate_id/type, revision, type, observed_at, payload, dedup_key; Delivery consumer/status/attempts; unique(consumer,event_id) |

#### Соревнования и идентичность

| Сущность | Стадия | Основные поля / связи / ограничения |
|---|---|---|
| Tournament | M | name, organizer_source, provider_league mappings, start/end, tier_evidence; названия не PK |
| TournamentStage | M/2 | tournament_id, name, stage_type, order, format_rules_version; group/bracket/round сведения позднее |
| Match | M | stage_id nullable, tournament_id, scheduled_start, status, time_precision, best_of nullable, schedule_revision; нельзя требовать известные команды для TBD |
| MatchParticipant | M | match_id, slot A/B, team_id nullable, seed/context; unique(match,slot); две известные команды не одинаковы |
| Series | M | match_id unique nullable, best_of, score_a/b, status, result_revision_id; BO2/draw не обрабатывать бинарно без отдельного контракта |
| Game | M | series_id nullable, map_number nullable, attempt_number, status, patch_id nullable, draft_start/start/end, winner_team_id nullable, result_type; unique(series,map_number,attempt) при известных полях |
| GameTeam | M | game_id, team_id, side nullable, slot; unique(game,slot), unique(game,side) при известной стороне |
| Team | M | canonical_name, identity_status, created_at; организация ≠ roster, переименование ≠ новая сущность автоматически |
| TeamAlias | M | team_id, alias, provider, validity, evidence; только для candidate resolution |
| Player | M | account_id nullable, canonical_name, identity_status; Steam/account mapping отдельно, никакого merging по nickname |
| PlayerAlias | M | player_id, alias, validity, evidence |
| Roster | M | team_id, roster_type announced/registered/inferred/actual, scope_tournament_id nullable, version, valid/system intervals, evidence_id |
| RosterMembership | M | roster_id, player_id, role nullable, is_standin nullable, valid interval, evidence; unique(roster,player,valid_from); противоречивые свидетельства разрешаются явно |
| GameParticipant | M | game_id, player_id, team_id, hero_id nullable, slot, role nullable, roster_evidence; unique(game,player), unique(game,slot); actual состав — результат наблюдения этой карты |
| Hero | M | stable_game_id unique, name versions, active_from; deprecated/unknown IDs поддерживаются |
| Patch | M | version_label, effective_from/to, announced_at, type major/minor/hotfix, evidence; actual game patch имеет приоритет над выводом из даты |
| PatchChange | 2 | patch_id, entity_type/id, field, before/after nullable, change_text, source/span; интерпретация meta отделена от release-note факта |
| ResultRevision | M | target_type/id, result_type, winner_id nullable, score, observed/available time, supersedes_id, evidence; sporting outcome, forfeit, void, cancelled раздельно |

#### Игровые и производные данные

| Сущность | Стадия | Основные поля / связи / ограничения |
|---|---|---|
| Draft | 2 | game_id, revision, completeness, observed_at, available_at, format_rules_version |
| DraftAction | 2 | draft_id, sequence, action pick/ban, team_id, hero_id, event_time, observation_id; unique(draft,sequence); порядок источника проверять |
| GameEvent | F | game_id, source_event_key, sequence, game_time, type, actor/target nullable, position nullable, payload, available_at; unique(source,game,key) |
| PlayerPerformance | M/F | game_participant_id, metric_schema_version, final K/D/A/GPM/XPM/duration; более глубокие metrics nullable + missing_reason + raw provenance; final нельзя читать как target pre-match feature |
| PlayerSynergy | 2 | unordered player-set key, role_assignment_version, context patch/roster/window, cutoff, n_games, weighted statistics, effective_n; triple не перечислять до достаточного покрытия |
| TeamStyle | 2/F | team_id, window, patch, cutoff, metric_definition_version, observables, effective_n, coverage; Team DNA — профиль значений, не мистический score |
| PlayerStyle | 2/F | player_id, role_context, тот же контракт метрик/окон; пространственные поля только при позиции |
| PositionSample | F | game_id, player_id, game_time, x/y, map_version, visibility_scope, sample_interval, observation; policy для gaps/teleports |
| SpatialArtifact | F | game_id/scope, artifact_uri/hash, map_transform_version, coordinate_frame, sample_coverage |
| Heatmap | F | artifact_id, subject, type movement/farm/death/teamfight/ward/objective, grid/binning/smoothing versions, normalization, time_window, patch_id, visibility_scope |

`PlayerPerformance` — сырые измерения сыгранной карты; `PlayerStyle`/`TeamStyle` — рассчитанные профили; `FeatureSnapshot` — именно те значения, которые вошли в конкретное решение. Не смешивать их в одной mutable таблице current_stats.

#### Forecast и воспроизводимость

| Сущность | Стадия | Основные поля / связи / ограничения |
|---|---|---|
| FeatureDefinition | M | name, version, formula, source requirements, windows, availability policy, units, missing policy |
| DatasetVersion | M | manifest_uri/hash, source revision set, temporal_mode, split_manifest, excluded records/reasons, label policy, feature_schema_version |
| ModelVersion | M | algorithm, artifact/hash, code_commit, dependency_lock_hash, dataset_id, training_cutoff, hyperparams, seed, feature_schema_version, calibration_version_id nullable, evaluated_report_id, promotion status |
| CalibrationVersion | M | method, artifact/hash, base_model_id, calibration dataset interval, schema, metrics; base-model relation FK без обязательного циклического insert |
| FeatureSnapshot | M | target_type/id, cutoff_at, evaluation_mode, values_json, missing/coverage_json, evidence_refs, feature_schema_version, content_hash, assumed_availability_policy nullable |
| Prediction | M | immutable target request: target_type, target_id, team_a_id, team_b_id, horizon/phase contract; unique stable request key |
| PredictionSnapshot | M | prediction_id, computed_at, cutoff_at, snapshot_seq, model_version_id, feature_snapshot_id, p_a/p_b nullable, abstention_reason, draft_revision_id nullable, roster_state_json, expert_state_json, market_state_json, state_hash, trigger_event_id, idempotency_key unique |
| SnapshotEvidence | M | snapshot_id, evidence_id, role source/feature/attribution; фиксированные revision refs, не ссылки на mutable latest |
| PredictionEvaluation | M | snapshot_id, result_revision_id, metric_definition_version, y nullable, log_loss/brier nullable, exclusion_reason, evaluated_at; unique(snapshot,result_revision,metric_version) |
| Backtest | F | model_version(s), dataset_id, market_dataset_id, strategy_version, config/hash, cutoff_policy, date range, metrics/report artifact, mode reconstructed/observed; подробнее BACKTEST.md |

Target FK не оставлять бесконтрольным polymorphic integer: в реализации выбрать nullable typed FKs с XOR-check (game_id или series_id), а `target_type` проверить CHECK. Все служебные arbitrary JSON source refs валидируются и имеют typed FK через evidence joins.

#### Experts и Market

| Сущность | Стадия | Основные поля / связи / ограничения |
|---|---|---|
| Expert | 3 | name, aliases, claimed role, verified_source_accounts; Nix/RAMZES/Solo/NS — кандидаты, не автоматически подтверждённые handles |
| MediaAsset | 3 | source_url/provider_id, author, publication_time, retrieved_at, rights_status, consent_reference, permitted_retention |
| TranscriptSegment | 3 | media_id, speaker_id nullable, start/end offset, text/hash, ASR_version nullable, language, speaker_confidence |
| ExpertOpinion | 3 | expert_id nullable, segment_id, entity_type/id, topic, original_claim, normalized_claim, sentiment, extraction_confidence, explicit_probability nullable, horizon, patch_id nullable, context, available_at, extraction_version, review_status |
| ClaimEvaluation | 3 | opinion_id, evaluation_rule_version, target_id, resolution_time, outcome, disputed/void, evidence; непроверяемая opinion не получает выдуманный score |
| ExpertSignalSnapshot | 3 | cutoff, topic, opinions/evaluations versions, method, weights, uncertainty, dependency clusters |
| CommunitySignal | F | source/entity/topic, timestamp, sentiment, volume, unique-author estimate nullable, bot/dedup policy, availability; не экспертный факт |
| Market | F | provider/bookmaker, target_type/id, market_type, map_number/line, currency, settlement_rules_version; разных рынков не объединять по team name |
| MarketSnapshot | F | market_id, source_quote_time, observed/available_at, status open/suspended/closed, odds_format, raw_payload_id, quote_group_id |
| MarketSelectionQuote | F | snapshot_id, selection_id/team_id, decimal_odds, raw_implied_probability, no_vig_probability nullable, normalization_method, liquidity/limit nullable; обе стороны одной временной группы |
| ModelMarketComparison | F | prediction_snapshot_id, market_snapshot_id, selection_id, p_model, p_market, edge, estimated_EV, validity_reason, decision_at; не изменяет model probability |
| SimulatedBet / Settlement | F | backtest_id, quote_id, selection, stake, accepted_time_assumption, bankroll_lock, result_revision, pnl/commission/void policy; ANALYSIS only, никаких ордеров |

### 5. Invariants и индексы

- FK на team/player/game/evidence/model обязательны в оценённых records; unresolved data остаются в quarantine/raw.
- Probability либо две конечные величины в [0,1] с суммой 1 в пределах заранее зафиксированной численной tolerance, либо abstention с NULL; не NaN.
- Для данного inference idempotency key повтор возвращает тот же snapshot, но новый input revision создаёт новый ключ. Probability не является частью ключа дедупликации.
- `computed_at` не выдаётся за исторический cutoff. Model artifact обучен без будущих labels относительно training cutoff; строгий serving запрещает модель, появившуюся после реального решения.
- Append-only права на snapshots; административная коррекция через supersedes/revocation event. Results могут уточняться без переписывания predictions.
- Индексы: provider lookup; game(series,map); game end/time; performance(player,game); roster(team,valid interval,system interval); snapshot(prediction,computed_at); observation(source,observed_at); source failure queue.
- Не создавать unique(team,player) для всей истории членства — игрок может вернуться. Non-overlap применяется к утверждённой непротиворечивой projection, не ко всем конкурирующим свидетельствам.
- Retention и privacy-source deletion согласуются отдельно; воспроизводимость хранит версию удалённого evidence с redacted/tombstone, а не незаконную копию.

Основания технических ограничений: [PostgreSQL constraints](https://www.postgresql.org/docs/current/ddl-constraints.html), [range types](https://www.postgresql.org/docs/current/rangetypes.html). Связанные документы: FEATURES.md, ML.md, EXPERT_ENGINE.md, LIVE.md, BACKTEST.md.

---


## Part 4 — Feature Engine

Статус: PROPOSED. Формулы ниже — предлагаемые определения продукта, не измеренные результаты. Все параметры фиксируются в FeatureDefinition и выбираются только на training/tuning данных.

### 1. Единый контракт

Каждый признак: name/version, subject_id, unit, numerator/denominator, source fields, window, cutoff, patch/role context, recency policy, min sample policy, missing reason, evidence refs. Никаких безымянных «aggression=82». Неизвестное ≠ 0. Сырые значения, availability mask, n и effective sample size передаются вместе.

Окна из запроса: lifetime; последние 365/90/30 дней; последние 20/10 завершённых карт; current patch; current tournament; current roster. В MVP сначала lifetime-prior, last20/last10 и current patch с shrinkage; остальные расширяются общим механизмом, не отдельными pipelines. Lifetime = вся доступная история источника, не вся карьера, если coverage не доказано. Окна заканчиваются до cutoff, по времени доступного результата, не start_time ещё не завершившейся игры.

Для допустимой прошлой игры i:

- вес w_i = exp(−ln(2)·age_i/H) · ρ(patch_i, patch_target);
- H > 0 — half-life, ρ ∈ [0,1] — политика patch-distance; текущий patch получает 1, неизвестный — отдельный mask/политика, а не автоматически «старый»;
- weighted mean = Σw_i x_i / Σw_i;
- n_eff = (Σw_i)² / Σw_i²;
- сглаженный winrate = (Σw_i y_i + αμ) / (Σw_i + α), где μ — prior из допустимого training-прошлого, α ≥ 0 фиксируется train/tuning.

Изменение патча не требует механического обнуления всей истории: сравниваем recency-only и patch-weighted подходы. Официальный patch ID игры предпочтительнее календарного вывода. Today's meta winrates запрещены в старых cutoff.

### 2. Минимум MVP

| Признак | Определение | Ограничение |
|---|---|---|
| Team recent form | smoothed weighted wins / games, last10/20; дифференциал A−B | strength of opposition пока отдельный Elo challenger, не скрытый коэффициент |
| Player form | те же past wins и historical K/D/A/GPM/XPM по prior-known roster | неизвестный состав → availability-aware fallback; actual target participants не подставлять |
| KDA | (kills+assists)/max(1,deaths) для описания, рядом K/D/A отдельно | ratio при 0 deaths условен; не «навык» |
| Death rate | deaths / played_minutes | duration > 0, короткие/аномальные карты по отдельной eligibility policy |
| Kill participation | (kills+assists)/team_kills | если team_kills=0 → missing/defined mask; не делить на 1 без обозначения |
| Hero pool | распределение прошлых picks игрока/команды, entropy = −Σ p_h ln p_h, distinct heroes, sample size | показатель breadth зависит от объёма; никакого target draft до драфта |
| Hero proficiency | smoothed past winrate/performance на герое, role/patch context | редкий герой → prior + low coverage, не уверенный «контрпик» |
| Roster continuity | overlap доли prior-known игроков с прошлой known пятёркой + games together | overlap не подтверждает отсутствие стендина |
| Patch context | patch ID evidence + age + same-patch n_eff | новый patch → cold-start warning |

Player form агрегируется по ролям, когда роль была известна, иначе mask. Не называть среднее GPM пятёрки рейтингом игроков: сравнение carry/support без role context искажает смысл. Основная первая модель может использовать только надёжное подмножество; UI поясняет, что остальные сведения ещё не влияют на вероятность.

### 3. Team DNA и Player Style: MVP 2 и далее

**Team DNA** — вектор observable statistics с единицами и coverage, не один произвольный балл. Стандартизация относительно прошлого patch/role cohort обучается на train, не на всём датасете.

| Название | Операциональное определение | Что требуется |
|---|---|---|
| Early strength | средняя доля/разность net worth или gold advantage на фиксированном game time | per-time ряды; games surviving до этого времени; отдельно сообщать survival selection |
| Mid/late strength | аналогично на заранее выбранных временных landmarks | нельзя сравнивать only-long-game cohort с общей выборкой без оговорки |
| Comeback rate | P(win | в заранее заданное время deficit ≤ −d) | d/time обучаются либо задаются до test; сообщать denominator |
| Throw rate | P(loss | advantage ≥ d в том же зафиксированном окне) | не психологический термин; не искать максимум по всему будущему матча для live feature |
| Objective participation | доля team objective events с атрибутированным участием игрока | определить участие через damage/position/time-window; final last hit — не полное участие |
| Roshan behavior | first-Roshan timing, count и доля контролируемых Roshan в доступной истории | kill attribution и unknown rights/visibility |
| Farm dependency | доля team net-worth/farm, получаемая игроком в фиксированных окнах | описывает распределение ресурсов, не причинную необходимость farm |
| Aggression proxy | hero-damage/active-minute + fights entered/active-minute как отдельные компоненты | нельзя сворачивать в score без обученной и проверенной методики |
| Farm efficiency proxy | Δgold / время в заранее размеченных farm zones | реальные позиции + earnings; покупки/пассивный gold требуют разделения |
| Map activity | distance/time и unique occupied cells/time | положение наблюдаемое, gaps/teleports отфильтрованы |
| Rotation frequency | число смен lane/region с минимальным dwell time / observed minutes | versioned region map и фиксированный dwell threshold |
| Teamfight positioning | распределение расстояния до teamfight centroid в событиях fights | clustering radius/time, роли, позиции; это proxy, не качество механики |
| Lane performance | net-worth/XP differential lane counterparts в выбранный landmark | role/lane matching с confidence и отсутствием counterpart |
| Hero flexibility | распределение ролей на герое / entropy conditional role | роли не должны восстанавливаться по финальной статистике целевой игры |

«Mechanical impact» не включается: пока нет отдельного проверенного observable определения, это недопустимый субъективный score.

### 4. Synergy

Для пары/тройки/пятёрки: sorted player IDs как set key, роли и roster version отдельно. Games/wins/losses together, duration, early advantage, fight/objective statistics и sample counts. На старте ограничиться парами и полной пятёркой; triples — только после анализа разреженности.

Сыгранность ≠ winrate сильных игроков. Synergy residual предлагается как среднее `actual_y − expected_y` относительно честного out-of-fold player/team baseline на прошлых совместных играх, со shrinkage к 0. Baseline не знает результат оцениваемой игры. Сначала описательные counts, затем residual ablation; не присваивать causal трактовку.

Stable/new roster, stand-in, role swap — evidence-backed categorical states. `stand-in=true` только по источнику или явно маркированной inference policy; низкий games-together сам по себе не доказательство стендина.

### 5. Draft и турнир

MVP 2: picks/bans/order, known roles, past player-hero proficiency, hero-pair synergy/counter counts with shrinkage, pick/ban frequencies по прошлому patch. Sparse hero combinations требуют регуляризации. Draft archetype — классификация наблюдаемого состава с versioned rule/model, а не экспертный факт.

На каждом значимом draft revision — новая availability-aware FeatureSnapshot и PredictionSnapshot; historical draft без времени публикации не превращается в настоящий pre-draft snapshot. Каждая стадия draft — отдельный contract/модель либо модель, обученная на том же pattern missingness. Не подавать неполный драфт в модель, обученную только на финальных picks.

Tournament context: format/stage/bracket/elimination, already played maps, opponent IDs, elapsed rest = cutoff − previous_known_game_end, schedule density в lookback, recent series duration. Если отдых выводится из scheduled end, пометить estimated. Никаких психологических объяснений из defeat streak.

### 6. Проверка ценности

Один feature group за раз: baseline → добавление → парные time-block OOS сравнения log loss/Brier/calibration → cost/coverage → решение. Group ablation для Team/Player/Patch/Draft/Synergy/Expert/Spatial/Market. Доступность группы оценивается на тех же матчах; улучшение только на удобном subset не считать выигрышем полного продукта.

Feature service общий для training и serving; nearest as-of join может брать будущее, поэтому только backward + cutoff + entity/version matching. Техническая справка: [pandas merge_asof](https://pandas.pydata.org/docs/reference/api/pandas.merge_asof.html).

---


## Part 5 — ML Architecture

Статус: PROPOSED. Модели не обучены; метрик проекта ещё нет. Заявления reference-репозиториев не считаются нашими результатами.

### 1. Target и прогноз

MVP: бинарный outcome первой сыгранной карты Series, Team A/B зафиксированы canonical identity, прогноз до draft. Не вероятность победы серии. Forfeit/void/no-contest не имеют обычного label. Если неизвестно, действительно ли карта первая, sample quarantined/excluded с причиной.

Первая тренировочная таблица содержит одну строку на eligible game1 и фиксированный cutoff; map2+ не подмешиваются молча. Истории всех прошлых карт разрешены для Team/Player form при соблюдении cutoff. Для будущих series/live целей создаются отдельные training cohorts, метрики и target contracts.

Side-neutral вход: дифференциалы A−B, known side только если она действительно известна на cutoff. Для симметрии тестируем P(A,B)=1−P(B,A). При необходимости применяем symmetrization `(f(A,B)+1−f(B,A))/2`, затем калибруем/проверяем итоговую процедуру; нельзя после calibration незаметно изменить probability. Минимальный LR на антисимметричных features с подходящим intercept contract упрощает проверку.

### 2. Порядок моделей

1. Constant prior и симметричный нейтральный baseline; при canonical A/B полезен именно контроль 0.5, а не идентичность алфавитного порядка.
2. Logistic Regression на небольшом Team/Player prior-form + availability features; Elo — дополнительный challenger/признак, только обновляемый после доступного результата.
3. CatBoost CPU — challenger полного MVP. Обучить и сравнить, но **не делать обязательным победителем**. Если LR лучше/надёжнее, он остаётся champion.
4. XGBoost/LightGBM — только дополнительное экспериментальное сравнение, не обязательная лестница из всех библиотек.
5. Neural/ensemble — после установленного gain, достаточного датасета и приемлемого сопровождения.

CatBoost обработка категориальных признаков не решает temporal leakage автоматически. Team/player IDs могут запоминать эпохи; нужны cold-team/roster/patch cohorts и ablation. Описание метода: [categorical features](https://catboost.ai/docs/en/features/categorical-features).

### 3. Два режима истории

**retrospective_reconstructed:** история скачана сейчас; в прошлом доступны лишь event times/предположения о lag. Future outcomes target исключены, но факт исторической доступности источника не доказан. Сохраняются actual observed_at и отдельная assumed_available_at с policy. Этот режим помогает отладить модель, не доказывает честную прибыль или реальный прошлый forecast.

**prospective_observed / observed_replay:** данные реально накоплены нашей системой; available_at для всех зависимостей ≤ cutoff. Прогноз сохранён до фактического начала draft, результат приходит позже. Это основа честного shadow validation.

Не объединять метрики этих режимов в одну цифру. Ретроспективный prediction computed_at = сейчас; UI не backdate. Для live replay per-minute состояния reconstructed и фактические наблюдения также различаются.

### 4. Temporal validation

```text
прошлое ----------------------------------------------------> будущее
[train] [tuning / rolling folds] [calibration] [frozen test]
 fit     choose features/model     fit map       report once
```

- Границы по calendar time и группам Series, не случайные строки. Все snapshots одной карты/серии в одной оценочной группе. Серия, пересекающая boundary, purge либо целиком позднее по заранее выбранной политике.
- Train labels должны уже быть доступны к training cutoff; поздно завершившиеся/исправленные серии не просачиваются.
- Scaling, imputation, encoders, feature selection и feature priors fit только train каждого fold. Hyperparameters и champion выбираются только tuning.
- Calibration block позже training/tuning, не используется для fit основной модели. Выбор метода calibration — внутри tuning, не по final test. Base-model затем не переобучать незаметно после calibration.
- Untouched test вскрывается один раз для gate, не для выбора winner. Провал → статус провал/insufficient evidence; новые изменения требуют будущего test window, а не повторного «untouched».
- Split/group manifest хранит record IDs, boundaries, exclusions, feature schema и code hash. Нерегулярные игры требуют собственного calendar/group splitter: стандартный [TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html) не обеспечивает grouping и документирует equally-spaced допущение для сравнимых интервалов.
- Tournament holdout/cold-team test — дополнительный stress test, не замена temporal evaluation. Совпадение команды в train/test не само по себе leakage: важно, какая информация была известна.

### 5. Обязательные leakage-тесты

1. Добавление будущих матчей/коррекций/трансферов не меняет ранее построенный strict snapshot.
2. Target final KDA/GPM/outcome/duration/actual roster не доступны pre-match feature query.
3. При неизвестном roster обучающий пример получает тот же fallback/mask, что serving; не использовать фактическую пятёрку целевой карты как будто известную заранее.
4. Текущий hero winrate/patch dictionary/expert evaluation не подставляются в старые cutoffs.
5. Feature hash повторяем; не используются latest-views без version/as-of filter.
6. Model artifact не обучен на test; обучение/cалибровка/feature extraction time manifests согласованы.
7. Live sequence не содержит future timestep, padding по финальной duration, terminal outcome или статистики события после cutoff.
8. Same series snapshots не оказываются в разных splits. Mean score считается с равным весом игр/зафиксированных horizons, а не количеством кадров.
9. Finite probability, unknown category/hero/patch, team swap, cold roster, missing source, cancelled game дают определённый результат/abstention.

### 6. Метрики и calibration

Для n допустимых независимых target instances: y_i ∈ {0,1}, p_i = P(A wins).

- **Brier** = (1/n) Σ(p_i−y_i)²; фиксируем бинарную шкалу [0,1].
- **Log loss** = −(1/n) Σ[y_i ln p_i + (1−y_i) ln(1−p_i)]; численный clipping ε фиксируется в metric version и не скрывает экстремальные raw p.
- **ECE** = Σ_b (n_b/n)·|mean(p)_b−mean(y)_b|; binning policy фиксируется, показываются n_b и uncertainty.
- Reliability diagram + histogram forecast probabilities; accuracy/AUC — вторичные.

Brier и log loss оценивают вероятностное качество в целом, не только calibration; меньше Brier не обязательно означает лучше reliability. ECE зависит от binning/sample size и не должен быть единственным gate. Основание: [scikit-learn calibration guide](https://scikit-learn.org/stable/modules/calibration.html), [Brier](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.brier_score_loss.html), [log loss](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.log_loss.html).

Начальный calibrator: identity vs sigmoid на отдельном block; isotonic — только при достаточной выборке и OOS advantage. Не использовать случайную CV по умолчанию. Храним uncalibrated и calibrated outputs в evaluation report; production snapshot хранит реально показанную вероятность и calibration version.

Сравнение моделей: paired per-game loss difference, confidence intervals block bootstrap по сериям/времени с sensitivity по турнирам. Порог meaningful gain, confidence level, test precision и minimum coverage фиксируются до test в PRD-001. Недостаточно данных → insufficient evidence, не «модель не хуже» по отсутствию значимости. 30 operational fixtures из PRODUCT.md не заменяют statistical test.

Отчёт по cohorts: patch, league tier из evidence, roster certainty, time horizon, missingness, cold starts; counts и исключения обязательны. Метрики на отобранных прогнозах сопровождаются abstention/coverage.

### 7. Model registry и serving

ModelVersion: artifact checksum, algorithm, hyperparameters, training interval, dataset/split manifest, dependency lock, feature schema, seed, calibrator, promotion decision. На CPU возможны малые численные отличия — tolerance фиксируется тестом, не обещается bitwise identity любой среды.

Champion заморожен до следующего offline evaluation; новые данные не запускают автоматическое обучение/промо в MVP. Drift monitoring сообщает об изменении patch/feature distributions и quality; решение retrain/rollback принимается владельцем. Откат возвращает предыдущую связку model+features+calibrator, не только binary.

### 8. Live и ensemble — Future

Live tabular baseline по доступным minute/state features и отдельной calibration по horizons либо time-aware calibrator. Не сравнивать last-minute accuracy с pre-match accuracy. Temporal model лишь после train/serve parity и OOS выигрыша с одинаковыми срезами.

Ensemble: Team/Player/Draft/Patch/Tournament/Live/Expert outputs генерируются out-of-fold временно; meta-model видит только OOF predictions при fit. Stacking на in-sample вероятностях запрещён. Statistical/model/expert/community сигналы сохраняются раздельно. Final ensemble probability калибруется как отдельная модель.

Добавление экспертов/рынка не может менять саму формулировку «независимая модель vs рынок»: если market входит в features, это отдельный market-aware model и он не выдаётся за независимый edge estimate.

---


## Part 6 — Expert Architecture

Статус: PROPOSED, MVP 3. Это самостоятельный слой свидетельств, не замена статистической модели.

### 1. Разделить четыре вида информации

- **Observed data:** игровые факты, подтверждённые источником.
- **Model signal:** расчёт на определённом feature snapshot.
- **Expert opinion:** утверждение конкретного человека с контекстом и датой.
- **Community signal:** измерение дискуссии; не факт и не экспертный консенсус.

Nix, RAMZES, Solo, NS и другие pro players/coaches/analysts/casters — кандидаты в Expert registry. Имена не означают найденные официальные каналы, разрешение на использование или качество мнений. Verified accounts и право на корпус проверяются отдельной задачей.

### 2. Права прежде автоматизации

Первый корпус: предоставленные владельцем/экспертом либо явно разрешённые текстовые интервью/транскрипты. Сохранять author/source, право обработки, допустимые цитаты, retention и attribution. Публично просматриваемый ролик не означает право скачать, транскрибировать и хранить его целиком.

[YouTube captions.download](https://developers.google.com/youtube/v3/docs/captions/download) требует надлежащей авторизации; API metadata не является универсальным API чужих транскриптов. [Twitch API guide](https://dev.twitch.tv/docs/api/guide/) описывает metadata/access/quotas, а не автоматическое предоставление прав на контент. Условия и найденные ограничения — SOURCES.md. Если бесплатного правомерного корпуса нет — gate no-go; не обходить доступ и не обещать извлечение всех стримов.

LLM/ASR adapters: локальный вариант при достаточных ресурсах или уже доступный разрешённый бесплатный endpoint. Выбор лицензии, требований к памяти и качества — отдельный benchmark. Платный API не закладывается. «Локально» не означает нулевую стоимость CPU/GPU и сопровождения.

### 3. Pipeline

```text
MediaAsset + rights policy
          ↓
разрешённый Transcript / ASR
          ↓
speaker attribution + segmentation
          ↓
LLM extraction в строгую schema
          ↓
entity linking / temporal checks / validation
          ↓
review / quarantine
          ↓
ExpertOpinion → проверяемый claim → ClaimEvaluation
```

Начать с текстового корпуса без speaker diarization, затем добавить ASR. Повторный extraction одного segment/version имеет dedup key; изменение prompt/model создаёт новую revision, не переписывает прошлое мнение.

#### Поля opinion

expert_id (nullable при неизвестном speaker), segment_id, original_claim, normalized_claim, entity_type/id, topic, sentiment, extraction_confidence, explicit_probability (только явно произнесённая), source_url, publication_time, segment_start/end, observed_at, available_at, patch_id (nullable), match/series context, horizon, conditions, extraction_version, review_status, evidence span/hash.

`extraction_confidence` оценивает уверенность извлечения/атрибуции, **не** вероятность истинности и не доверие эксперту. Число из LLM по умолчанию не калибровано: либо заменить review status, либо проверить на размеченном корпусе. «Команда выглядит лучше» не превращается в 0.7 win probability. Чужая цитата, сарказм, условное предсказание и пересказ отделяются от собственного утверждения speaker.

Темы: player skill, current form, hero pool/strength, draft, team strength/weakness, meta, patch, strategy, lane, teamfight, synergy, roster, tournament, match prediction. Multi-label разрешён; неизвестная тема — other/uncertain, а не насильственная классификация.

### 4. QA извлечения

Размеченный вручную небольшой корпус с редкими/отрицательными случаями, отдельные train/development/test по источнику и времени. Проверки: precision/recall обнаружения opinion, topic F1, entity-link accuracy, speaker attribution, faithful claim rate, точность time offsets, доля unsupported extractions и duplicate rate. Порог допуска фиксируется до просмотра held-out корпуса.

LLM не имеет доступа к записывающим инструментам/секретам и не исполняет инструкции внутри транскрипта. Только bounded input → schema output; отклонение malformed JSON и hallucinated entity IDs. Утверждения без точного source span не публикуются.

### 5. Track record

Claim score допустим лишь если до события определены target, horizon, settlement rule и проверяемый outcome. ClaimEvaluation хранит result evidence, unresolved/disputed/void и версию правила. Постфактум выбирать удобную интерпретацию нельзя.

- Explicit probabilistic claims: Brier/log loss на сопоставимых бинарных событиях, counts, uncertainty; сравнение с baseline той же темы/горизонта.
- Categorical predictions: accuracy и coverage, не выдумывать исходную probability. Не смешивать с probabilistic score.
- Качественные утверждения: unscored либо заранее согласованный observable criterion; «талантливый» не получает автоматическое true/false.
- Разрезы topic/patch/role/horizon только с sample size, shrinkage и широкими интервалами при редкости. Не назначать «рейтинг доверия 9/10».

Оценка эксперта, использованная в cutoff t, включает только resolved claims, доступные до t. Результат сегодняшнего прогноза эксперта не влияет на его вчерашний вес. Пересказы одного источника кластеризуются: десять копий не десять независимых мнений.

### 6. Consensus и ML

Первый consensus — доли/число независимых мнений по теме, freshness и coverage, не вероятность исхода. Если есть численные probabilistic forecasts на одном target, исследовать recency-weighted aggregation со shrinkage. Performance weights либо прозрачны и фиксированы заранее, либо обучены на past OOF claims; не подгонять на исходах той же серии.

Экспертный слой сначала **только отдельная панель**. Интеграция в модель — после достаточного корпуса, temporal availability test, ablation и OOS gain. Сохранять ExpertSignalSnapshot с точными claim/evaluation versions; не подавать сегодняшние резюме стримеров в исторические forecasts.

### 7. LLM analyst — позже

На вход: только структурированные evidence-backed profiles, model output/attributions, cutoff, evidence IDs и обозначенные мнения. На выход: explanation claims с `evidence_refs`, типом data/model/opinion и confidence/limitations. Версионировать prompt, schema, generation engine и исходный bundle.

Генератор не пересчитывает probability и не придумывает statistics. Validator сверяет числа/units/entities/source refs; unsupported claim отклоняется. Fallback — шаблонное объяснение. Feature attribution не является доказательством причинности.

### 8. Community — Future

Twitch chat, YouTube comments, Reddit, Telegram и social media только после отдельного rights/access gate. Aggregate sentiment/volume с source/time/topic/entity и dedup/bot-policy. Не сохранять лишние персональные данные. API-доступ, получение удалённых публикаций и легальность хранения не предполагаются автоматически.

---


## Part 7 — Live Architecture и Heatmap Engine

Статус: PROPOSED, Future после MVP 3. Ни один live feed не подключён; sample публичных лобби не доказывает доступ к профессиональным матчам.

### 1. Gate доступа

Проверить bounded пробами: нужные профессиональные турниры действительно присутствуют; game/team/player IDs сопоставляются; поля доступны без скрытого платного контракта; известны source/game/observation clocks; права допускают использование; историческая и live схемы совместимы.

Кандидаты:
- OpenDota `/live`: только те поля и coverage, которые реально получены; observed `delay` не универсальный SLA.
- STRATZ / Valve: только после token/method/schema проверки.
- Локальный GSI: нужен разрешённый spectator/локальный клиент, доступность данных зависит от режима. Это не unattended серверный глобальный канал всех турниров.
- Replay parser: готовый OSS parser после license/compatibility проверки; replay после игры не заменяет живой поток.

Источник: SOURCES.md (SOURCES.md), U5/U6/U12/U13. No-go live не блокирует работающий pre-match продукт. Не использовать закрытые backstage feeds или игровые преимущества участнику: инструмент для анализа профессиональной сцены, не чит.

### 2. State pipeline

```text
Live adapter → raw observation → reorder/dedup/validate
       → canonical GameState revision
       → as-of live FeatureSnapshot
       → live model + calibrator
       → PredictionSnapshot → trajectory UI
```

State содержит game_id, game_time, source_time, observed_at, available_at, sequence/revision, heroes/draft, score, gold/XP/net worth/objectives/items/positions **только при наличии**, visibility_scope, missing mask и staleness. Нет позиции — нет fabricated map control.

Late/out-of-order observation не перезаписывает показанный snapshot. Обновление current-state projection допускается новой revision; replay trajectory хранит, что действительно было показано. События start/end могут отсутствовать: не синтезировать уверенные времена. Pause/reconnect/remake проверяются отдельно.

Latency измерять по компонентам: source lag, transport lag, processing/inference lag, UI lag. `game_time` не wall clock; broadcaster delay и provider timestamp не обязаны совпадать. Без правдивого source timestamp полную end-to-end задержку назвать нельзя.

### 3. Live model

Первая модель — tabular baseline на времени и реально доступных состояниях: относительные gold/XP/net worth, kills, towers, Roshan, draft/known heroes. Базовый comparator time+gold, затем дополнительные группы. Items/positions вводятся только при historical/live parity.

- Training использует replay reconstruction ровно доступного к t состояния, не final scoreboard, final duration, future objective counts.
- Валидируем по calendar/series, все snapshots игры в одном split.
- Отчёт по заранее выбранным horizons и равновесным per-game весам. Длинные игры не получают автоматический больший вес из-за большего числа кадров.
- Terminal state не включать в оценку «полезности live предсказания»: знать победителя после разрушения Ancient не прогноз.
- Missingness при serving должна совпадать с training policy; zero-fill отсутствующих towers/Roshan может разрушить смысл — fallback/abstain.
- Temporal model (LSTM/transformer) лишь после baseline, с causal mask и контролем padding. Новые heroes/patches не ломают embedding lookup.

На update значимого state/draft — snapshot; frequency и debounce выбираются по реальному quota/latency budget, не обещаются заранее. Дедуп одинаковых входов не мешает хранить observation times.

### 4. Heatmaps как измерения

Начать с доступных event-derived heatmaps (deaths/wards/objectives), затем movement/farm/teamfight при достаточной позиции. Пользовательский rollout heatmaps идёт после live gate; разрешённый offline replay research может быть независимым. Heatmap не является live map vision.

Для каждой карты: map version, coordinate transform, Radiant/Dire orientation, bounds, region polygons, game-time window, sampling policy, visibility scope и missing fraction. Сырые координаты сохраняются отдельно от transformed grid. Изменение геометрии патча требует новой map_version; нельзя накладывать несопоставимые территории.

| Heatmap | Что считается | Нельзя подменять |
|---|---|---|
| Movement | время присутствия игрока в клетке / наблюдаемое время | частоту нерегулярных sample вместо времени |
| Farm | события получения farm/creep kills или локализованный gold, policy явная | всю occupancy в лесу за «farm» |
| Death | count/observed exposure по месту смерти | вероятность смерти из голого количества без exposure |
| Teamfight | кластеризованные боевые события/позиции в fight windows | все kills за полноценные teamfights без правила |
| Ward-related | позиции/время активности wards и обнаруженные destroy events | полную vision coverage без terrain/visibility модели |
| Objective | события/присутствие возле конкретных objectives | причинный objective pressure из статичного расстояния |

### 5. Численные spatial features

Предлагаемые формальные proxies, параметры версионируются:

- **presence_control(R):** наблюдаемые player-seconds команды в регионе R / суммарные наблюдаемые player-seconds обеих команд в R; это присутствие, не полная информация о контроле/vision.
- **rotation_frequency:** число переходов между region labels с минимальным dwell / observed_minutes.
- **farm_area:** площадь grid cells с подтверждёнными farm events в окне; зависит от grid resolution, сохранять её.
- **enemy_jungle_presence:** player-seconds в enemy-jungle polygons / все observed player-seconds команды.
- **objective_pressure:** время игроков в радиусе objective, делённое на observed exposure; радиус/длительность фиксированы; рядом damage/event features отдельно.
- **average_rotation_distance:** сумма валидных расстояний переходов / число завершённых rotations; teleports отдельно, long missing gaps не интерполировать как прогулку.
- **death_hotspots:** spatial death intensity count/exposure по клеткам, с minimum exposure и uncertainty.
- **teamfight_position:** распределение расстояния игрока до centroid собственного состава/событий в fight, роль и момент зафиксированы.

SpatialArtifact/Heatmap хранит raw input manifest, transform/binning/smoothing versions, payload hash, window и cutoff. Сглаживание для UI не должно незаметно менять ML feature. Объём raw positions оценивается пилотом до решения о parquet/partitioning; ClickHouse не нужен по умолчанию.

### 6. Тесты и остановка

Fixtures: нет позиции; перепутанная ориентация; новый patch/map; пропуск sample; out-of-order; pause; повторное событие; game ended correction; неизвестный hero; неполный draft. Golden trajectory проверяет отсутствие будущих полей. Spatial transform проверяется контрольными точками и coverage mask.

Если pro-live отсутствует или права неясны — остановить live, сохранить pre-match. Если реплеи не доступны — не обещать исторические movement heatmaps. Если spatial ablation не улучшает OOS качество, оставить визуализацию исследовательской, не объявлять ML advantage.

---


## Part 8 — Market Architecture и Backtest Engine

Статус: PROPOSED, Future, **ANALYSIS ONLY**. Источник бесплатных исторических timestamped odds не подтверждён. Реальных ставок, прибыли проекта и результатов backtest нет.

### 1. Два разных backtest

- **Prediction evaluation** входит уже в MVP: насколько вероятности соответствуют исходам, независимо от рынка.
- **Market backtest** появляется только после model gate и правомерного odds dataset: могли ли решения на доступных котировках дать результат после маржи/комиссии/ограничений.

Accuracy, calibration, prediction quality, edge и profitability — разные свойства. Положительный edge модели не доказывает прибыльность.

### 2. Source/access gate

Требования к market dataset: provider, bookmaker/venue, target game/series, market/selection, quote timestamp, actual observation timestamp, открытость/приостановка, обе стороны одной котировки, тип odds, settlement rules, исправления, разрешённое использование/хранение. Для live также synchronization/latency и доступность выполнения по цене.

Сначала оценить разрешённый бесплатный API либо предоставленный владельцем законный CSV с реальными данными. CSV — интерфейс импорта, **не существующий датасет и не предложение подставить demo**. Без источника — no-go market layer. Не собирать HTML в обход ToS; не регистрировать платные услуги. PandaScore stats free исключён до письменного подтверждения допустимости betting-related анализа — даже личный ANALYSIS не снимает ограничений (SOURCES.md).

### 3. Pipeline и разделение источников

```text
правомерные odds → raw quote → validation/market mapping
  → MarketSnapshot + selections
  → as-of join с независимым PredictionSnapshot
  → ModelMarketComparison → simulation → audit report
```

Bookmaker != market. Game winner != series winner. Map handicap/series total не сравниваются с бинарной game1 model. Разные BO/void rules/валюты/selection definitions не объединяются. Не строить «лучшую пару коэффициентов» из разных bookmakers и объявлять её маржой одного рынка.

### 4. Вероятности, маржа, edge

Для одного полного взаимоисключающего binary рынка с decimal odds o_A,o_B > 1:

- q_A = 1/o_A; q_B = 1/o_B — raw implied probabilities.
- overround = q_A + q_B − 1.
- простая пропорциональная no-vig оценка: p_market,A = q_A/(q_A+q_B); p_market,B аналогично.
- edge_A = p_model,A − p_market,A, в долях либо процентных пунктах, unit всегда указан.
- ожидаемый net return на единицу stake при отсутствии комиссий: EV_A = p_model,A·o_A − 1.

No-vig — оценка распределения маржи, не наблюдаемая «истинная вероятность рынка». Проверить sensitivity к методам de-vig позже. При неполной котировке/несогласованных timestamp честного paired no-vig нет — NULL+reason, не нормализация случайных сторон. Underround/аномалии помечаются, не автоматически «арбитраж».

Для комиссии c только с выигрыша одиночной ставки: EV = p·(o−1)·(1−c) − (1−p). Это лишь конкретная commission convention; биржевое net-market settlement моделируется отдельным rule, не этой формулой по умолчанию.

Положительный edge против no-vig не равен положительному EV по доступным odds после маржи. Модель может ошибаться; uncertainty/confidence не превращается в универсальную вероятность «ставка верна».

Справочные формулы: [implied probability](https://help.smarkets.com/hc/en-gb/articles/214058369-How-to-calculate-implied-probability-in-betting), [margins](https://help.smarkets.com/hc/en-gb/articles/214180145-How-to-calculate-betting-margins), [expected value](https://help.smarkets.com/hc/en-gb/articles/214554985-How-to-calculate-expected-value-in-betting). Это справка по математике, не одобрение доступа к данным или обещание доходности.

### 5. Исполнитель исторической симуляции

Конфигурация: date range, eligible tournaments, target/market, model version, prediction mode, minimum edge, maximum odds, minimum data-quality/uncertainty requirement, stake strategy, bankroll, maximum simultaneous exposure, fees, latency/slippage, settlement rules и closing-line definition. Каждый параметр versioned.

События обрабатываются по доступности, а не по знаниям из конца периода:

1. Подгрузить только model/feature/quote versions, доступные на decision time.
2. Проверить рынок, статус, свежесть, pre-draft target и допустимость quote. Для честного model-vs-market сравнения forecast cutoff не позже decision, quote available_at не позже decision; older forecasts помечены age.
3. Применить заранее замороженную стратегию; не брать несколько почти одинаковых snapshots одной позиции как независимые bets без стратегии увеличения позиции.
4. Зарезервировать stake из free bankroll; незавершённые одновременные события блокируют капитал. Не тратить будущий выигрыш до settlement.
5. Outcome resolver учитывает void/forfeit/remake/перенос/правила bookmaker. Corrections сохраняются revision, а не стирают аудит.
6. Сохранить decision, rejected reason, quote, model snapshot, stake и settlement. Никаких API ордеров.

Первый stake baseline — заранее фиксированный flat stake с капитал-ограничением. Kelly/оптимизация ставки не нужны для доказательства прогнозного сигнала; добавлять только как sensitivity после калибровки, без обещаний дохода. Minimum confidence — определённая заранее data-quality или interval-width policy, не само значение p и не LLM confidence.

### 6. Метрики с точными определениями

Пусть s_i — stake, π_i — net settled P&L, N — число не-void settled decisions (void count показывается отдельно).

- bets/wins/losses/void/pending/rejected — раздельно; win rate = wins/(wins+losses), не включая void.
- profit = Σπ_i после комиссий и расходов модели исполнения.
- turnover = Σs_i по settled non-void bets; ROI = profit/turnover. При 0 turnover → undefined.
- profit factor = Σmax(π_i,0) / |Σmin(π_i,0)|; при отсутствии убытков → undefined/infinite с count, не доказанная устойчивость.
- Equity E_t = initial bankroll + cumulative settled P&L; free cash и reserved stakes показываются отдельно. Peak H_t = max_{u≤t} E_u; max drawdown absolute = max_t(H_t−E_t); relative = max_t((H_t−E_t)/H_t) при H_t>0. Mark-to-market equity — другой режим, не смешивать.
- **CLV odds ratio** = o_taken/o_close − 1 для той же selection/market/settlement и принятой closing timestamp definition. Positive означает более высокий взятый decimal odds, не гарантирует прибыль.
- **CLV probability delta**, если нужна: p_close,no-vig − p_taken,no-vig; другая единица/смысл, хранить отдельно. Нет законной closing line — CLV = NULL с coverage, не substitute by result.
- Brier/log loss/calibration для всех пригодных forecasts и отдельно выбранных bets; показывать selection bias и размер обеих выборок.

Confidence intervals: блоки по времени/series/tournament, sensitivity к зависимым рынкам и correlated bets. Резкое различие ROI одного турнира и остальных — риск нестабильности, не сигнал подгонять фильтр.

### 7. Out-of-sample и gate

Strategy tuning только внутри старого training/tuning market периода; следующий test заморожен. Model selection, calibration, edge threshold и stake strategy не выбираются по итоговому ROI test. Закрывающая линия используется для диагностики после, не как доступная ранее feature. Одна удачная история недостаточна.

Раздельные режимы:
- reconstructed историческая симуляция с предположением о доступности/исполнении;
- observed shadow decisions с реально накопленными timestamped snapshots;
- actual execution здесь отсутствует и не заявляется.

Нет timestamps, market matching, условий исполнения или достаточного sample → «невозможно подтвердить», не «прибыльно». Market module может остаться исследовательским навсегда; автоматизация ставок не входит ни в текущую задачу, ни в этот план.

### 8. Тесты

Golden cases: бинарная выплата/проигрыш/void, комиссия, несогласованные стороны, stale quote, wrong map/series, suspend, missing close, repeated snapshot, concurrent bets, empty denominator, model trained after decision, late correction, timezone/DST, floating precision. Stake/money хранить в фиксированной денежной точности по currency policy; raw odds сохранять без преждевременного округления.

---


## Part 9 — Исследование источников и reference-проектов

**Тип документа:** архитектурное исследование источников (НЕ продуктовый код, НЕ рыночная математика, НЕ общая архитектура).
**Проект:** solo-founder, личный исследовательский инструмент, только бесплатные источники (подтверждено пользователем).
**Дата пакета исследования:** **2026-09-16 (Asia/Singapore)** — по данным основного агента (`get_time`). Это **дата пакета**, а не «согласованное время снимка»: исследование выполнялось в текущей сессии, разные страницы/эндпоинты читались в разные моменты сессии. Системное время среды исполнения (`date` в песочнице) — это время OCRuntime, а не источник истины; оно здесь не используется как дата исследования.
**Метод:** `web_search` + `web_fetch` (браузер недоступен). Часть данных получена **вызовами эндпоинтов через `web_fetch`**, а не «сырым» HTTP-клиентом. Оговорка: `web_fetch` может **кэшировать или нормализовать** ответ (свой User-Agent, нет контроля над заголовками), поэтому такие вызовы помечены как `ЭНДПОИНТ(proxy)` и **НЕ являются подтверждением свежего HTTP 200**: raw-заголовки (`Date`, `Age`, `Cache-Control`, `X-RateLimit-*`, `Retry-After`) не проверялись, нагрузочных тестов и замеров квот не проводилось. Тела ответов, которые удалось прочитать, приводятся как есть (с указанием, что это ответ прокси).
Прямой HTTP/curl из песочницы заблокирован: попытка `urllib` к `api.opendota.com`, `api.stratz.com`, `api.pandascore.co`, `dota.haglund.dev` вернула **HTTP 403 Forbidden** (egress-прокси песочницы). Поэтому «проба эндпоинта» = вызов через инструмент `web_fetch` (`ЭНДПОИНТ(proxy)`), а `DOCS` = прочитана документация, живого запроса не было.

**Легенда статуса проверки:**
- `DOCS` — подтверждено официальной документацией/страницей (документация прочитана, но не проверена живым запросом).
- `ЭНДПОИНТ(proxy)` — получен ответ эндпоинта **через `web_fetch`** (см. оговорку выше; raw-заголовки не проверялись).
- `КЛЮЧ` — требуется ключ/токен/регистрация (подтверждено ответом API или docs).
- `РЕПО` — подтверждено чтением README/листинга/метаданных GitHub-репозитория (**без аудита содержимого файлов**).
- `НЕИЗВ.` — не удалось подтвердить, нужен spike.

---

### 1. TL;DR (что реально есть бесплатно)

1. **Ядро бесплатного исторического слоя — OpenDota.** Ключ не требуется: «You can use the API without a key» ([docs.opendota.com](https://docs.opendota.com/)); заявленный free tier: 3000 вызовов/день, 60 вызовов/мин ([opendota.com/api-keys](https://www.opendota.com/api-keys)). `ЭНДПОИНТ(proxy)`: `GET /api/proMatches` и `GET /api/live` вернули читаемый JSON через `web_fetch` (не подтверждение свежего 200 — см. оговорку в шапке). **Покрытие/глубина истории требуют аудита** (см. §7 U3, U13).
2. **STRATZ — кандидат #2, но нужен токен.** API заявлен как бесплатный, GraphQL, токен выдаётся автоматически после входа через Steam («Default Token»); без токена данные не получить — по docs: «To get started with the STRATZ API, you will need a token» ([stratz.com/api](https://stratz.com/api)). Прямой запрос из песочницы не прошёл (egress 403), т.е. поведение «без токена» **не проверено живьём**.
3. **Календаря будущих матчей в рассмотренной документации OpenDota/Valve нет.** В списке эндпоинтов OpenDota (`docs.opendota.com`) нет «upcoming/schedule» ([docs.opendota.com](https://docs.opendota.com/)); `ЭНДПОИНТ(proxy)` `/api/proMatches` вернул только **завершённые** матчи (верхний `start_time=1789324066` ≈ 2026-09-14). Это утверждение об **обзоре рассмотренных docs**, а не о невозможности такого API в принципе.
4. **Upcoming auto-discovery:** основной бесплатный путь — **Liquipedia** (MediaWiki API, 1 req/2s) + производные проекты (напр. [beeequeue/dota-matches-api](https://github.com/beeequeue/dota-matches-api), кэш 3 ч). **PandaScore free исключён из initial critical path** (см. п. 4a и §3.5) до письменного подтверждения прав.
   **4a. PandaScore и «betting-related» — отдельно.** Free-план описан как «Schedules, Results & Context Data» (0 €, 1000 req/ч, без карты), но stats-планы «only available to customers with **non betting-related usage**», а betting-клиентам они запрещены ([pandascore.co/pricing](https://www.pandascore.co/pricing)). Исходная цель проекта содержит market/edge/backtest, поэтому **нельзя по умолчанию считать использование не-betting’овым**: даже «личный analysis» может квалифицироваться как betting-related. Решение: **не включать PandaScore в initial critical path без письменного разрешения провайдера**.
5. **Pre-match rosters** (отдельно от результатов) — в основном Liquipedia (ростеры/трансферы, CC-BY-SA 3.0, обязательна атрибуция) и PandaScore pre-match (под тем же условием, п. 4a); у OpenDota есть производный список `/proPlayers` c `team_id` (стареющий, без «кто реально играет» — стендинов).
6. **Live game-state:** `GET /api/live` (OpenDota) в `ЭНДПОИНТ(proxy)` отдал идущие игры с `game_time`, `radiant_lead`, `radiant_score/dire_score`, `series_id`, `team_id_*`, `players[] {account_id, hero_id}` и `delay: 120`. **Важно:** `league_id: 0` в обеих попавших в выборку играх → **про-лобби (pro-live) не проверены**; поле `delay=120` наблюдалось **только в этом sample** и не является универсальной/гарантированной задержкой. Локальный GSI покрывает только свой/спектируемый клиент.
7. **Reference-проекты найдены оба.** `amarcu/dota-predictor` — заявлена лицензия **MIT** (файл `LICENSE` присутствует). `NUKI1223/dota-predictor` — **явной лицензии в репозитории не обнаружено** → **не копировать код до получения разрешения/уточнения лицензии** (это осторожная позиция, а не юридическая квалификация). Полный код-аудит не проводился: проверены README, структура файлов и метаданные (§6).
8. **SLA нет ни у одного рассмотренного бесплатного источника.** Liquipedia прямо оставляет за собой право изменить/приостановить API «at any time, without notice» ([api-terms-of-use](https://liquipedia.net/api-terms-of-use)); Valve указывает, что может изменить или прекратить доступ ([dev/apiterms](https://steamcommunity.com/dev/apiterms)).

---

### 2. Матрица возможностей источников (главная сводная таблица)

| Источник | Данные | Интерфейс | Бесплатность/цена (подтверждено) | Лимиты | Cadence / freshness | История | Качество | Legal/ToS | Критичность | Статус проверки |
|---|---|---|---|---|---|---|---|---|---|---|
| **OpenDota** | Матчи (raw+parsed), игроки, команды, лиги, герои, `/live`, `/proMatches`, `/parsedMatches`, `/explorer` (SQL), `/scenarios` | REST + OpenAPI (версия API в docs: `31.1.0`) | Free: без ключа. Premium $0.01/100 calls, $0.0001/call | Заявлено: free **3000/день, 60/мин**; Premium: unlimited, 3000/мин (фактические квоты не измерялись) | Pro-матчи появляются после окончания; в `ЭНДПОИНТ(proxy)` верхний завершённый матч был от ~3 суток ранее — это может быть лагом индексации **или** отсутствием матчей в окне | Глубина истории не аудирована: доступна через `/explorer`, но покрытие/полнота не проверены | Парсинг реплеев даёт расширенные поля; **community-проект, качество по полям не аудировано** | Публичных ToS не найдено в обзоре; ключ Premium требует платёжного метода; 404/429/500 не тарифицируются | **Критичный #1** (историческая база) | DOCS + ЭНДПОИНТ(proxy) |
| **STRATZ** | GraphQL: матчи, игроки, команды, лиги, герои, battle-pass, leaderboards + кастомная аналитика (заявлен Clarity 2 parser) | GraphQL (`api.stratz.com/graphql`, GraphiQL) | Заявлено «available for free» ([stratz.com/api](https://stratz.com/api)) | Default token (после Steam-логина): таблица показывает значения порядка 20 / 250 / 2 000 / 10 000 (per Second/Minute/Hour/Day — **рендер таблицы неоднозначен, см. §7 U1**) | Cadence не документирован | Глубина не аудирована; вендор заявляет «every public match» | Используется Dota2ProTracker/Twitch-расширением (заявление вендора); поля не аудированы | Требует `User-Agent: STRATZ_API`; запрещены читерство/скрипты; Individual/Multi токены — по заявке + referral-трафик | **Критичный #2** (кандидат на дополнение OpenDota) | DOCS + КЛЮЧ |
| **Valve / Steam Web API** | Dota 2 интерфейс `IDOTA2Match_570` (`GetMatchHistory`, `GetMatchHistoryBySequenceNum`, `GetTopLiveGame`, `GetTeamInfoByTeamID` и др.) | REST (`api.steampowered.com`), JSON/XML/VDF | Заявлено «Valve makes the Steam Web API available free» ([dev/apiterms](https://steamcommunity.com/dev/apiterms)) | **100 000 вызовов/день на ключ** (там же) | Не документировано в прочитанном объёме; методы матчей исторически критикуются сообществом | Не проверено; ожидается исторический доступ через sequence-num, но **требует живого теста** | Детализации матчей/ростеров в прочитанных материалах не хватает | Ключ персональный, обязателен; запрет «unfair competitive advantage»; запрет выдавать данные как данные Valve | **Средний кандидат** (live/team info) | DOCS + КЛЮЧ |
| **Liquipedia** | Расписания (upcoming/ongoing), результаты, ростеры, трансферы, турниры | MediaWiki API (free) + LiquipediaDB API (по заявке) | MediaWiki API — free; LiquipediaDB — по одобренной заявке | MediaWiki: **1 req/2s**, `action=parse` **1 req/30s**; LiquipediaDB: **60 req/1 час** | Ведётся сообществом вручную → от минут до дней; значимая доля `TBD` | 150k+ турниров / 3M+ матчей — маркетинговое заявление [liquipedia.net/api](https://liquipedia.net/api) (не проверено) | Структура для расписаний/ростеров есть; **требует парсинга шаблонов, API-доступ не тестировался** | CC-BY-SA 3.0 → **обязательна атрибуция**; автоматический доступ к HTML-страницам запрещён (только API); API может быть отключён без предупреждения | **Высокий кандидат** для upcoming + roster | DOCS (API-эндпоинты не тестировались; см. §3.4) |
| **PandaScore** | Заявлено: Static, Calendar (future+past), Pre-match (турниры/команды/игроки); подробные post-match stats и live — платно | REST (`api.pandascore.co`) | Free-план «Schedules, Results & Context Data» = **0 €**, без карты | **1000 req/час** на free | Не документировано | Заявлено: Historical — от 400 €/видеоигра/мес (платно) | Провайдер промышленного уровня; состав free-плана по полям **не проверен построчно** | Stats-планы **только для non-betting usage**; betting-клиентам запрещены → для проекта с market/edge/backtest требует письменного разрешения | **Исключён из initial critical path** (§3.5) | DOCS + КЛЮЧ (`ЭНДПОИНТ(proxy)`: `{"error":"Token is missing"}`) |
| **Локальный Dota 2 GSI** | Game state своего/спектируемого клиента (net worth, XP, LH, kills, heroes) | HTTP POST с клиента на localhost (`.cfg`) | Бесплатно (часть клиента) | Локально, без квот | Реальное время, но требует запущенного клиента | Нет (только live) | Потенциально точный для live; набор полей зависит от `.cfg` (не проверялся живьём) | Только для клиента пользователя; не серверный источник | **Средний** (live-слой личного инструмента) | DOCS (вторично) + РЕПО |
| **Twitch Helix** | Стримы, категории, VOD, зрители (для экспертного контекста/CCV) | REST + EventSub | Free (docs) | Token-bucket; в docs пример заголовка `Ratelimit-Limit: 800` (**пример, не универсальная квота**) | Реальное время | VOD/архив — по правилам хранения платформы | Не оценивалось для наших задач | Twitch Developer ToS; контрактный запрет зависимости от строк/URL ответов | **Низкий-средний** (контекст) | DOCS |
| **YouTube Data API v3** | Видео, каналы, live, комментарии; транскрипты — только для видео, которое вы вправе редактировать | REST | Free quota | Точные значения квот в прочитанной таблице **противоречивы** (units vs calls/day) → не приводим числа: см. [quota calculator](https://developers.google.com/youtube/v3/determine_quota_cost) и §7 U14 | Пост-факт (VOD) | Архив | Годится для метаданных; **скачивание чужих транскриптов через API недоступно** ([captions.download](https://developers.google.com/youtube/v3/docs/captions/download)) | YouTube API ToS (хранение/редистрибуция ограничены) | **Низкий-средний** | DOCS |
| **datdota** | Про-статистика (player/team/hero/league, draft, win expectancy) | Веб-платформа (публичный API не подтверждён) | НЕИЗВ. (на входе — экран принятия ToS) | НЕИЗВ. | НЕИЗВ. | Заявлена про-история; глубина не проверена | Контент ведёт известный статистик сообщества; качество полей не проверялось | ToS платформы (текст не читался) | **Опциональный** | НЕИЗВ. |
| **Dota2ProTracker** | Hero build/статистика, pro-матчи | Веб | Не подтверждено | — | — | — | — | — | **Низкий** (reference UI) | НЕИЗВ. (третьестороннее утверждение об отсутствии публичного API) |
| **beeequeue/dota-matches-api** | Upcoming-расписание Dota 2 (из Liquipedia) | REST: `GET /v1/matches` | Открытый код/сервис (лицензию репозитория не читал) | Кэш 3 ч после первого фетча | Обновление раз в ~3 ч (по кэшу) | Только upcoming | Простое; зависит от Liquipedia | Зависит от условий Liquipedia (в репо есть коммит с сообщением «properly adhere to liquipedia terms»); **сервис, судя по README, разбирает HTML-страницу — риск ToS-конфликта, требует проверки** | **Средний** (референс-паттерн для upcoming) | РЕПО |

---

### 3. Детальные карточки источников

#### 3.1 OpenDota (`api.opendota.com`)

**Что даёт.** «The OpenDota API provides Dota 2 related data including advanced match data extracted from match replays» — это ключевое отличие: OpenDota **парсит реплеи**, поэтому поверх базового match JSON есть per-minute ряды (`gold_t`, `xp_t`, `lh_t`), `kills_log`, `objectives`, `teamfights`, `draft_timings`, `picks_bans`, `radiant_gold_adv`/`radiant_xp_adv` ([docs.opendota.com](https://docs.opendota.com/)). Полный список эндпоинтов (docs, версия API `31.1.0`): `matches`, `players` (+ `/recentMatches`, `/matches`, `/heroes`, `/peers`, `/pros`, `/totals`, `/counts`, `/histograms`, `/wardmap`, `/wordcloud`, `/ratings`, `/rankings`, POST `/refresh`), `/topPlayers`, `/proPlayers`, `/proMatches`, `/publicMatches`, `/parsedMatches`, `/explorer`, `/metadata`, `/distributions`, `/search`, `/rankings`, `/benchmarks`, `/health`, `/request/{jobId}`, POST `/request/{match_id}`, `/heroes` (+подэндпоинты), `/heroStats`, `/leagues` (+подэндпоинты), `/teams` (+подэндпоинты), `/records/{field}`, `/live`, `/scenarios/*`, `/schema`, `/constants` ([docs.opendota.com](https://docs.opendota.com/)).
Дополнительно: OpenAPI-спецификация скачивается с `https://api.opendota.com/api` (ссылка «Download OpenAPI specification» на docs-странице); справочники ID — в репозитории [odota/dotaconstants](https://github.com/odota/dotaconstants).

**Интерфейс.** REST/JSON. Ключ передаётся параметром `api_key`; без ключа тоже работает.

**Цена / бесплатность — подтверждено.** На текущей странице ключей: `Free Tier — Price: Free; Key Required? No; Call Limit: 3000 per day; Rate Limit: 60 calls per minute; Support: community via Discord`; `Premium Tier — $0.01 per 100 calls; Unlimited; 3000 calls per minute; priority support`; биллинг `$0.0001 per call, rounded up to the nearest cent`; «Responses with status codes 404, 429 or 500 aren't billed»; получение Premium-ключа требует привязанного платёжного метода ([opendota.com/api-keys](https://www.opendota.com/api-keys)).

**Лимиты.** Free 3000/день + 60/мин (там же). **Историческая нестыковка (важно):** в блоге OpenDota от **2018-04-17** описаны другие цифры — «a Free Tier of 50,000 API calls per month», «no API key required» ([blog.opendota.com/2018/04/17/changes-to-the-api/](https://blog.opendota.com/2018/04/17/changes-to-the-api/)). Третьесторонний источник (Reddit, 2024) утверждает 2000 вызовов/день без ключа ([reddit](https://www.reddit.com/r/DotA2/comments/1dhpv35/opendota_api_returning_empty_response_all_of_a/)). **Вывод:** исторические цифры менялись; ориентироваться нужно на актуальную страницу `/api-keys`, а фактические квоты проверять эмпирически (spike). Для бесплатного ключа на docs: «registering for a key allows increased rate limits and usage» ([docs.opendota.com](https://docs.opendota.com/)).

**Пробы эндпоинтов (без ключа, через `web_fetch` → `ЭНДПОИНТ(proxy)`; raw-заголовки не проверялись):**
- `GET https://api.opendota.com/api/proMatches` → читаемый JSON-массив завершённых матчей (тело ответа получено). Пример записи: `{"match_id":8997682537,"duration":1975,"start_time":1789324066,"radiant_name":"YBN Club","dire_name":"Stray Club","leagueid":20159,"league_name":"WINLINE Star Series Season 4","series_id":1141801,"series_type":1,"radiant_score":42,"dire_score":15,"radiant_win":true,"version":22}`. Верхний `start_time` в выборке ≈ 2026-09-14. **Будущих `start_time` в выборке нет** — согласуется с отсутствием calendar-эндпоинта в рассмотренных docs. Оговорка: это одна выборка через прокси, а не проверка полноты фида.
- `GET https://api.opendota.com/api/live` → читаемый JSON-массив идущих игр. Поля: `activate_time`, `deactivate_time`, `server_steam_id`, `lobby_id`, `league_id`, `lobby_type`, `game_time`, `delay`, `spectators`, `game_mode`, `average_mmr`, `match_id`, `series_id`, `team_name_radiant/dire`, `team_logo_*`, `team_id_radiant/dire`, `sort_score`, `last_update_time`, `radiant_lead`, `radiant_score`, `dire_score`, `players[] {account_id, hero_id, team_slot, team}`, `building_state`, `is_player_draft`, `is_watch_eligible`. **Обе игры в sample были паблик-лобби** (`league_id: 0`, `team_id_*: 0`, пустые `team_name_*`) → **pro-live (турнирные лобби) этим sample НЕ проверен**; нельзя утверждать, что для про-лобби `team_name_*`/`team_id_*` заполняются (в docs гарантий нет — это гипотеза для spike). Поле `delay` в sample равнялось `120`, но это **единственное наблюдение**, а не универсальная задержка.

**Cadence / freshness vs отсутствие SLA.** OpenDota — community-проект (open source, Discord-поддержка, `/health`). Формального SLA и документированной гарантии свежести в рассмотренных материалах нет. Каденс зависит от парсинга реплеев; в пробе `/live` поле `last_update_time` было близко к моменту запроса, а `/proMatches` отдал завершённые матчи с верхним `start_time` ~3 суток ранее — но это одна выборка, и причина (лаг индексации vs отсутствие матчей в окне) **не установлена**. Нужен отдельный замер cadence (U10, U13).

**Качество.** Парсинг реплеев даёт расширенные поля (`gold_t`, `xp_t`, `lh_t`, `kills_log`, `objectives`, `teamfights`, `draft_timings`, `picks_bans`), т.е. потенциально сильный источник для фич. Но: parsed-поля есть только у распарсенных матчей (`/parsedMatches`), `replay_url` доступен не всегда, «raw» матчи содержат лишь базовые поля. **Полнота и корректность полей по про-матчам не аудированы** — это задача аудита (U13), а не установленный факт.

**Legal/ToS.** Публичных ToS-страниц у OpenDota в рамках обзора не найдено (на сайте — Discord и страница ключей; из условий биллинга: 404/429/500 не тарифицируются). **Не утверждаю**, что производные данные автоматически наследуют Steam Web API ToS: лицензионная цепочка Valve → OpenDota → наш инструмент требует отдельной проверки прав (U8). Ключ с Premium требует **платёжный метод** → в бесплатном сценарии ключ не обязателен, но лимит ниже.

**Критичность:** #1 как кандидат на историческую базу (матчи, драфты, таймсерии, про-контекст) и как один из проверенных на доступность live-эндпоинтов (без утверждения «единственный» и без подтверждённого pro-live).

---

#### 3.2 STRATZ (`api.stratz.com` / `stratz.com/api`)

**Что даёт.** GraphQL вместо REST. По официальной странице: «The STRATZ API is the most comprehensive resource for Dota 2 statistics in the world, and it's available for free. We've transitioned from REST to GraphQL…». Источник данных: «Using SkadiStats's Clarity 2 parser for replay data access, along with our array of inhouse parsers and analytics tools». Среди потребителей заявлены Dota2ProTracker, Twitch-расширение Dota 2 Tracker, Overwolf DotaPlus draft assistant ([stratz.com/api](https://stratz.com/api)). Схема/песочница — `https://api.stratz.com/graphiql` ([stratz.com/api](https://stratz.com/api)).

**Интерфейс / авторизация.** Обязательны: (а) токен, (б) заголовок `User-Agent: STRATZ_API` (там же). Default Token выдаётся автоматически при входе через Steam. Individual/Multi токены — по заявке; Individual требует «Required Monthly Referrals» = 1000, Multi = 5000, и заявка рассматривается «case-by-case» с периодическими аудитами referral-трафика, иначе токен деактивируется ([stratz.com/api](https://stratz.com/api)).
**Эндпоинт-тест:** прямой запрос к `api.stratz.com/graphql` без токена из песочницы → 403 (egress-блок), поэтому проверить поведение «без токена» не удалось. **Статус: КЛЮЧ (подтверждено, что токен обязателен по docs: «To get started with the STRATZ API, you will need a token»).**

**Цена.** Бесплатно для Default/Individual (с referral-обязательствами для Individual/Multi). Платного тарифа на странице API нет — вместо цены «referral traffic back to STRATZ».

**Лимиты.** Таблица токенов на странице API (колонки: Calls / Second, Minute, Hour, Day). Значения, как отрендерилась таблица: Default → 20 / 250 / 2 000 / 10 000; Individual → 20 / 250 / 4 000 / 20 000; Multi → 20 / 20 / 50 / 100 **per user**. **Рендер таблицы неоднозначен** (значения нарушают арифметику бакетов), поэтому это **не следует закладывать в архитектуру как факт** — см. §7 (блокирующее неизвестное).

**Cadence/freshness.** Не документирован. STRATZ заявляет хранение/парсинг «every public match» ([stratz.com](https://stratz.com/)) — но без SLA.
**История.** В Medium-посте **2021-11-20**: «The STRATZ API handles over 13 million requests every day» ([stratz.medium.com](https://stratz.medium.com/stratz-api-major-update-5557335dbdfd)); переход на GraphQL анонсирован **2019-11-30** ([medium.com/stratz](https://medium.com/stratz/dota-7-23-graphql-631ea1d5f173)). Обе страницы — старые, цифры не проверяемы сейчас.

**Качество.** По заявлениям вендора — «most comprehensive resource… in the world» + кастомная аналитика (draft-данные, win-rate разбивки, R.O.S.H.); **независимой проверки полей не делалось**. **Legal/ToS:** запрет использования данных для illegal purposes, для читерства/скриптов/хакинга, нарушения Steam Subscriber Agreement или «damaging the integrity of Dota 2 and/or esports»; STRATZ может менять условия («We may add to and change the terms of our API usage over time») ([stratz.com/api](https://stratz.com/api)).
**Критичность:** #2 — потенциальная замена/дополнение OpenDota, особенно для draft/live, но чуть выше барьер (Steam-логин + токен + referral-риск для больших токенов).

---

#### 3.3 Valve / Steam (официальный слой)

**Что даёт.** Steam Web API: `ISteamNews`, `ISteamUserStats`, `ISteamUser` и per-game интерфейсы; для Dota 2 — `IDOTA2Match_570` (список методов см. в неофициальном зеркале документации: `GetMatchHistory`, `GetMatchHistoryBySequenceNum`, `GetTopLiveGame`, `GetTopLiveEventGame`, `GetTeamInfoByTeamID`: [steamwebapi.azurewebsites.net](https://steamwebapi.azurewebsites.net/); примеры вызовов: [ribasco/async-gamequery-lib](https://ribasco.github.io/async-gamequery-lib/examples/webapi_dota2_example.html); обёртки: [EthanWadsworth/valve-steam-web-api](https://github.com/EthanWadsworth/valve-steam-web-api)). Официальная страница Valve перечисляет только общеигровые интерфейсы и отправляет за ключом: [steamcommunity.com/dev](https://steamcommunity.com/dev).

**Интерфейс / ключ.** `http://api.steampowered.com/<interface>/<method>/v<version>/?key=<api key>&format=json|xml|vdf`. В документации Valve заявлено: «All use of the Steam Web API requires the use of an API Key» ([steamcommunity.com/dev](https://steamcommunity.com/dev)); форма ключа — `https://steamcommunity.com/dev/apikey`.
**Не обобщаю это утверждение:** это формулировка docs для Web API в целом, а **состав публичных/защищённых методов и фактическое поведение отдельных эндпоинтов** (в т.ч. Dota-методов) нужно проверять покомпонентно (U5) — какие-то Steam-эндпоинты/страницы могут быть доступны без ключа, и это нельзя исключать без пробы. Для **рассматриваемых защищённых Dota-методов** наличие ключа предполагается. Есть OpenID-провайдер Steam (`https://steamcommunity.com/openid`) для аутентификации.

**Цена / лимиты — подтверждено.** «Valve makes the Steam Web API available free» и жёсткий лимит: **«You are limited to one hundred thousand (100,000) calls to the Steam Web API per day»** ([steamcommunity.com/dev/apiterms](https://steamcommunity.com/dev/apiterms)).
**ToS-особенности (важно для архитектуры):** лицензия персональная и привязана к приложению, ключ нельзя передавать третьим лицам; запрещено подавать данные так, будто приложение аффилировано с Valve/Steam; **«You agree that you will not create or assist third parties in any way to create any technology or functionality that may give a user an unfair competitive advantage when playing multiplayer versions of any Steam game»**; Valve может изменить или прекратить API/доступ; ToU **не датированы** — страница помечена «Last updated July 2010» ([steamcommunity.com/dev/apiterms](https://steamcommunity.com/dev/apiterms)).

**Критичность:** средняя. Потенциально полезно для live/team-info методов, но детализации матчей/ростеров в прочитанных материалах не хватает, а `GetMatchHistory` исторически критикуется сообществом ([reddit 2022](https://www.reddit.com/r/DotA2/comments/vndwu6/steam_api_the_problematic_getmatchhistory_method/)) — это мнение сообщества, не официальное заявление Valve. Заявление о «смене формата про-сцены» здесь **снято**: без проверенного источника на него нельзя опираться (это влияет на U5 и требует отдельной проверки).

**Dota 2 Game State Integration.** Официальная документация — Valve Wiki: [Dota 2 Game State Integration](https://developer.valvesoftware.com/wiki/Dota_2_Game_State_Integration) и [Dota_2_Workshop_Tools/Dota_2_Game_State_Integration](https://developer.valvesoftware.com/wiki/Dota_2_Workshop_Tools/Dota_2_Game_State_Integration) (обе ссылки указаны в README reference-проекта [amarcu/dota-predictor](https://github.com/amarcu/dota-predictor)). **В этой сессии: страница Valve Wiki закрыта анти-бот защитой Anubis** («Making sure you're not a bot! … This website is running Anubis version 1.23.1»), т.е. документация недоступна для автоматического чтения — статус `DOCS` только через вторичные источники. GSI работает **только локально** (клиент POST-ит state на ваш HTTP-эндпоинт), поэтому для личного инструмента это live-слой «спектейт свой матч», а не серверный источник данных по чужим матчам.

---

#### 3.4 Liquipedia (`liquipedia.net`)

**Что даёт.** Расписания (Upcoming/ongoing), завершённые матчи, ростеры и трансферы, турниры. Страница upcoming — [liquipedia.net/dota2/Liquipedia:Upcoming_and_ongoing_matches](https://liquipedia.net/dota2/Liquipedia:Upcoming_and_ongoing_matches).
**Наблюдение в этой сессии (разовое, не воспроизводимое):** страница была **однократно прочитана через `web_fetch`** — это было разовое чтение HTML-страницы, а **не** «ручная проверка через браузер». В снимке видны: дата/время (EDT), команды (часто `TBD`), формат `(Bo3)`/`(Bo5)`, лига/турнир со ссылкой, `+ Add details`. По ToS Liquipedia автоматический доступ к таким HTML-страницам запрещён, поэтому **этот способ больше не используется**: программно допустим только MediaWiki API / LiquipediaDB API. API-эндпоинты Liquipedia в этой сессии **не тестировались** (статус в матрице — `DOCS`, не `tested`).

**Интерфейсы.**
- **MediaWiki API** — бесплатный, для wiki-контента.
- **LiquipediaDB API** — структурированные данные (matches/rosters и т.п.), доступ **по одобренной заявке**, документация открывается после логина в LiquipediaDB Dashboard ([api-terms-of-use](https://liquipedia.net/api-terms-of-use)).
- Прямой скрапинг HTML-страниц **запрещён**: «Automated access to non-API endpoints (ie, generated HTML pages) is not permitted» (там же).

**Лимиты — подтверждено.** MediaWiki API: **не более 1 HTTP-запроса / 2 секунды**; `action=parse` — **не более 1 запроса / 30 секунд**; обязателен кастомный `User-Agent` с контактом (generic вроде `Python-requests` блокируются); обязательна поддержка gzip; нужно переиспользовать HTTP-клиент; LiquipediaDB API: **не более 60 запросов / 1 час**, ключи не передавать третьим лицам ([api-terms-of-use](https://liquipedia.net/api-terms-of-use)). Историческая (2015) формулировка тех же правил — на TL.net: [tl.net/forum/hidden/491339](https://tl.net/forum/hidden/491339-liquipedia-api-usage-guidelines); актуальная страница-указатель: [liquipedia.net/commons/Liquipedia:API_Usage_Guidelines](https://liquipedia.net/commons/Liquipedia:API_Usage_Guidelines) (обновлена 2025-02-07).

**Cadence/freshness vs отсутствие SLA.** Данные ведёт сообщество вручную → задержка от минут до дней; в про-сценах расписание часто заполняется заранее, но состав/время могут меняться, значительная доля `TBD`. Прямое предупреждение: Liquipedia может «modify, suspend or terminate operation of or access to the Liquipedia API … at any time, without notice» ([api-terms-of-use](https://liquipedia.net/api-terms-of-use)).

**Legal/ToS — критично.** Контент под **CC-BY-SA 3.0**, требуется атрибуция Liquipedia как источника (там же). Это означает: при отображении расписаний/ростеров нужно явно атрибутировать и учитывать share-alike для производных текстов. Библиотека-референс: [c00kie17/liquipediapy](https://github.com/c00kie17/liquipediapy) (в README прямо предупреждает о строгом соблюдении лимитов, иначе бан).
**Критичность:** **высокая** — по итогам обзора это основной **бесплатный публичный** кандидат на **upcoming** и **объявленные ростеры** (единственность не утверждается: PandaScore формально тоже может это отдавать, но исключён по ToS-условию, §3.5).

---

#### 3.5 PandaScore (`pandascore.co`)

**Что даёт (free).** Free-план на официальной странице цен назван «**Schedules, Results & Context Data**», 0 € за видеоигру в месяц, и перечисляет: **STATIC DATA** (чемпионы/предметы/базовая инфо), **CALENDAR** («Future and past match schedule»), **PRE-MATCH DATA** («Information on tournaments, team and players»), лимит **1K REQUESTS PER HOUR**; «No credit card is required to sign up» ([pandascore.co/pricing](https://www.pandascore.co/pricing)). Платные уровни: Historical & Post-Match — **от 400 €/видеоигра/мес** («post-match results and detailed per-game data», computed statistics, 10K req/h); Live Basic/Real-time — **от 1000 €**; Live Pro — «Contact us» (там же).
**Важное уточнение:** название free-плана включает «Results», а описания листинга ограничиваются static/calendar/pre-match. **Наличие или отсутствие базовых результатов/счётов во free-плане по прочитанной странице однозначно не устанавливается** — поэтому здесь **не утверждается**, что free «пустой». Утверждать можно только то, что **подробные post-match данные и вычисленные статистики отнесены к платному уровню** (от 400 €), а live отнесён к платным уровням. Статус: `НЕИЗВ.` → уточнить в U8/U15.

**Интерфейс.** REST; есть отдельный референс «List Dota 2 matches» / «Get upcoming Dota 2 matches»: [developers.pandascore.co/reference/get_dota2_matches](https://developers.pandascore.co/reference/get_dota2_matches).
**Проба эндпоинта (`ЭНДПОИНТ(proxy)`, через `web_fetch`):** `GET https://api.pandascore.co/dota2/matches/upcoming` → тело ответа **`{"error":"Token is missing"}`** (raw-заголовки не проверялись). Подтверждает: даже для free-плана нужен API-токен (регистрация аккаунта).

**Ограничение «betting-related» — блокирующее для этого проекта.** «These stats plans are only available to customers with **non betting-related usage**» и «customers with a betting-related usage are not permitted to use the stats plans» ([pandascore.co/pricing](https://www.pandascore.co/pricing)).
Исходная цель проекта включает **market/edge/backtest**, поэтому:
- нельзя по умолчанию считать использование «не-betting’овым»: даже «личный analysis» может квалифицироваться как betting-related (граница не определена публично);
- **вывод: PandaScore исключается из initial critical path**; включать его можно только после **письменного разрешения/подтверждения** от провайдера (или после юридической квалификации, что сценарий не является betting-related).
Также: «The "live" pricing only indicates stream-synced data» — live отнесён к платным уровням. Cadence/SLA не документированы; free-план может измениться.

**Критичность:** понижена до **«кандидат на будущее»** (потенциально ценен для upcoming + rosters, но не входит в initial critical path из-за ToS-условия).

#### 3.6 Прочие источники (проверено точечно)

| Источник | Что это | Что известно (подтверждено) | Статус | Годится для |
|---|---|---|---|---|
| [datdota.com](https://datdota.com/) | Про-статистика Dota 2 (player/team/hero/league, draft analysis, win expectancy) | На входе — обязательный экран принятия ToS: «I agree to the Terms of Service … I confirm that I am at least 16 years of age. Accept and Continue» ([datdota.com](https://datdota.com/)); страница [datdota.com/about](https://datdota.com/about) существует | `НЕИЗВ.` (публичный API не подтверждён; партнёрский/закрытый доступ возможен) | Возможный экспертный reference по про-статистике; не закладывать как источник без spike |
| [dota2protracker.com](https://dota2protracker.com/) | High-MMR/pro hero-статистика и билды | Третьесторонний обзор утверждает: «Dota2ProTracker does not publish an official public developer API or documented API endpoints for third-party use» ([parse.bot](https://parse.bot/marketplace/88cc8d49-9a24-4a20-b021-0bef5a8b1815/dota2protracker-com-api)) — **источник третьесторонний, низкая надёжность**; сам STRATZ заявляет Dota2ProTracker как потребителя своего API ([stratz.com/api](https://stratz.com/api)) | `НЕИЗВ.` | Только как UI-reference; данные, скорее всего, достижимы через STRATZ |
| [beeequeue/dota-matches-api](https://github.com/beeequeue/dota-matches-api) | Открытый REST-API: upcoming-расписание из Liquipedia | README: «fetches, caches and formats the current upcoming match schedule from Liquipedia… caches matches for 3 hours»; `GET /v1/matches`; Base URL `https://dota.haglund.dev`; поля матча: `id`, `hash`, `teams[2]`, `matchType`, `startsAt`, `leagueName`, `leagueUrl`, `streamUrl`; стек: TypeScript + Cloudflare Workers + D1(SQLite) + Cache; 14 звёзд, 493 коммита, последний коммит 2026-07-30; в истории коммитов есть «properly adhere to liquipedia terms» | `РЕПО` (сервис не вызывался) | **Готовый reference-паттерн** для upcoming: брать из Liquipedia + кэшировать; но 3 ч кэш = грубая свежесть |
| [liquipediapy](https://github.com/c00kie17/liquipediapy) | Python-клиент Liquipedia | README предупреждает о строгом соблюдении rate limits (иначе IP-бан) | `РЕПО` | Библиотека-помощник для MediaWiki API |
| [dota2.balldontlie.io](https://dota2.balldontlie.io/) | Третьесторонний «Dota 2 API» (pro matches, tournaments, teams, players, heroes) | «An API key is required» | `НЕИЗВ.` (цена/лимиты/качество не подтверждены) | Не закладывать |
| [citoapi.com/dota-2-api](https://citoapi.com/dota-2-api/) | Коммерческий Dota 2 esports API (upcoming, teams, rosters, live) | Заявляет endpoints; цена/лимиты не подтверждены, в обзорах фигурируют платные тарифы | `НЕИЗВ.` | Не бесплатный кандидат |
| [Imprint Esports](https://www.reddit.com/r/DotA2/comments/1sbd58b/were_imprint_esports_the_dota_2_data_platform/) | Новая Dota 2 data-платформа | Пост-анонс на Reddit про «access for our Dota 2 data platform» | `НЕИЗВ.` | Наблюдать; не закладывать |
| Valve Wiki (GSI) | Официальная документация GSI | В этой сессии страница закрыта Anubis-антиботом (см. §3.3) | `DOCS (вторично)` | Live-слой локально |

#### 3.6a Replay-парсеры (OSS) — быстро подтверждённые ориентиры

Если понадобится **свой** парсинг реплеев (вместо/помимо OpenDota), есть открытые парсеры. Проверялось по листингам GitHub (README/карточки репозиториев), без клонирования и запуска:

| Проект | Что это | Лицензия (по листингу GitHub) |
|---|---|---|
| [skadistats/clarity](https://github.com/skadistats/clarity) | «Clarity» — Java-парсер реплеев Dota 2 (заявлен в STRATZ как основа парсинга) | **BSD-3-Clause** (указано на карточке репозитория) |
| [odota/parser](https://github.com/odota/parser) | Replay parse server, генерирующий логи из реплеев (парсер OpenDota) | На карточке лицензия не отображалась → **проверить `LICENSE` в репозитории** |
| [odota/core](https://github.com/odota/core) | Ядро/бэкенд OpenDota (включая API) | **MIT** (указано в листинге организации odota) |
| [odota/web](https://github.com/odota/web) | Веб-UI OpenDota | **MIT** (указано в листинге организации odota) |

Практический вывод: переиспользуемый OSS-парсер реплеев существует и лицензирован пермиссивно в части подтверждённых проектов, но перед использованием нужно **проверить файл лицензии каждого конкретного репозитория** и совместимость (и не забыть U6 — доступность самих `.dem` файлов).

#### 3.7 Twitch / YouTube / публичные интервью (для «экспертных мнений»)

**Назначение в проекте:** это **не источник фактов о матчах**, а (а) контекст (кто стримит/смотрит, CCV), (б) канал для качественной оценки (интервью, разборы, аналитика), (в) материал для проверки «почему»-гипотез. Использовать как фичи для модели — рискованно и юридически тонко.

**Автоматизируемость экспертного слоя — уточнение.** Ранее сформулированный вывод «только ручной слой» **снят**: экспертный слой **автоматизируем**, если соблюдаются права/согласие и используются собственные транскрипты:
- свои транскрипты (запись/расшифровка с согласия спикера, или собственный контент) — автоматизация допустима;
- публичные интервью/подкасты — автоматизация только при наличии прав/лицензии на контент и при соблюдении правил платформы;
- агрегация метаданных (кто стримил, когда, какие видео) — автоматизируема в пределах лимитов и ToS платформ.
Ограничитель не «техническая невозможность», а **права и условия платформ**.

- **Twitch Helix (docs: [dev.twitch.tv/docs/api/guide](https://dev.twitch.tv/docs/api/guide)).** Token-bucket rate limiting; в docs приведён **пример** заголовков `Ratelimit-Limit: 800` (это иллюстрация, а не универсальная квота); при превышении — 429; заголовки `Ratelimit-Limit/Remaining/Reset`; отдельные бакеты для app access и user access токенов. Данные: стримы, категории, VOD, клипы. Доступ бесплатный (docs), но **Twitch ToS** ограничивает хранение/использование данных; приложение не должно зависеть от форматов строк и URL из ответов (там же).
- **YouTube Data API v3 (docs: [Quota Calculator](https://developers.google.com/youtube/v3/determine_quota_cost)).** В прочитанной таблице квот значения **противоречивы** (в разных местах страницы фигурируют и «units», и «calls/day» для `search.list`/`videos.insert`), поэтому **конкретные числа здесь не приводятся** — они помечены как `НЕИЗВ.` и вынесены в §7 (U14). Достоверно: квота проекта ограничена, часть методов дороже других, есть отдельные бакеты для `search.list`/`videos.insert`, сброс квоты — в полночь PT (там же).
- **Транскрипты через API — недоступны для чужих видео (подтверждено).** `captions.download`: «This method requires the user to have permission to edit the video»; требуются scopes `youtube.force-ssl` или `youtubepartner`; стоимость вызова 200 units; при недостатке прав — `403 forbidden` ([captions/download](https://developers.google.com/youtube/v3/docs/captions/download), страница от 2026-09-15). Следствие: **метаданные видео не дают права на скачивание транскрипта**; для чужих интервью автоматический транскрипт через API невозможен — только собственные транскрипты/права.
- **Публичные интервью / документалистика как экспертный контент.** Пример официального качественного источника — серия Valve **True Sight** ([TI 2018 Finals](https://www.youtube.com/watch?v=Bv4CqIxqTMA), [TI 2019 Finals](https://www.youtube.com/watch?v=ceQ2XFS1tUo)): даёт «почему»-контекст по драфтам и решениям команд. Это **видео с авторским правом** — допустимо цитирование со ссылкой и датой, но не переиспользование. Готового API «мнений»/«аналитики» не существует, однако это ограничение правовое, а не принципиально техническое.
- **Вывод по экспертизе:** слой может быть автоматизирован при правах/согласии и собственных транскриптах; базовый (всегда доступный) уровень — метаданные Twitch/YouTube в пределах их ToS + курируемый список источников с цитатами и датами.

---

### 4. Upcoming auto-discovery (автообнаружение будущих матчей) — отдельный разбор

**Наблюдение: в рассмотренной документации OpenDota и Valve нет эндпоинта «список будущих матчей».** Это утверждение об **обзоре docs**, а не о невозможности такого API.
- В перечне эндпоинтов OpenDota (`docs.opendota.com`, API `31.1.0`) нет ни `upcoming`, ни `schedule`; есть только `proMatches`, `publicMatches`, `parsedMatches`, `live`, `leagues` ([docs.opendota.com](https://docs.opendota.com/)).
- `ЭНДПОИНТ(proxy)`: `/api/proMatches` вернул только завершённые матчи, у верхней записи `start_time` ≈ 2026-09-14 — будущих `start_time` в выборке нет.
- `/api/live` даёт идущие игры (`deactivate_time: 0`), не будущие.
- Valve: в рассмотренных зеркалах видны исторические и live методы (`GetMatchHistory`, `GetMatchHistoryBySequenceNum`, `GetTopLiveGame`, `GetTopLiveEventGame`); метода «расписание», по **рассмотренным** зеркалам, не найдено ([steamwebapi.azurewebsites.net](https://steamwebapi.azurewebsites.net/)). Полнота списка не гарантируется (зеркало неофициальное).

**Что потенциально работает для upcoming (нужна проверка API-доступом):**
1. **Liquipedia** — страница [Upcoming and ongoing matches](https://liquipedia.net/dota2/Liquipedia:Upcoming_and_ongoing_matches). Снимок страницы в этой сессии (разовое чтение через `web_fetch`, см. §3.4) показывает матчи, время, Bo3/Bo5, лигу и `TBD` по командам. Программно допустим только MediaWiki API (1 req/2s; `action=parse` 1/30s) или LiquipediaDB API (60 req/ч, по заявке) — **API-доступ в этой сессии не тестировался**, статус `DOCS`. Автоматический разбор HTML запрещён ([api-terms-of-use](https://liquipedia.net/api-terms-of-use)).
2. **PandaScore** — Calendar «Future and past match schedule» + Pre-match есть в описании free-плана (1000 req/ч, без карты), референс-эндпоинт «Get upcoming Dota 2 matches» ([developers.pandascore.co](https://developers.pandascore.co/reference/get_dota2_matches)); проба без токена → `{"error":"Token is missing"}`. **Но**: stats-планы — только для non-betting usage, а цель проекта включает market/edge/backtest → **исключён из initial critical path** до письменного разрешения (§3.5).
3. **Community-мост (референс-паттерн)** — [beeequeue/dota-matches-api](https://github.com/beeequeue/dota-matches-api): по README фетчит Liquipedia-страницу, кэширует на 3 часа, отдаёт `GET /v1/matches` с `startsAt`, `teams`, `leagueName`, `streamUrl`. Оговорки: зависимость от одного сопровождающего, 3-часовая свежесть и **вероятный ToS-конфликт** (разбор HTML-страницы Liquipedia) → использовать как паттерн, а не как готовую зависимость.
4. **Возможный STRATZ-путь** — STRATZ показывает лиги/серии на сайте; наличие предстоящих серий в GraphQL **не подтверждено** документацией → `НЕИЗВ.` (§7 U2, проба с Default Token).

**Ключевая архитектурная рекомендация:** upcoming — **отдельный пайплайн** от завершённых матчей, со своим источником, кэшем (для расписаний 3 ч — ориентир, не факт) и обязательным **резолвингом команд** (страницы Liquipedia ↔ `team_id` OpenDota/Valve). **Game-level идентификатор не доступен на этапе upcoming** — он появляется, когда становится доступен game-level источник (live-эндпоинт или parsed/исторический слой). При этом нельзя утверждать, что ID появляется «только после игры»: live-эндпоинт может отдавать game-level ID уже во время матча — это отдельная гипотеза к проверке (U12). Поэтому связка «upcoming-запись → матч» на этапе планирования делается по командам+времени+лиге, а не по ID.

---

### 5. Pre-match rosters (составы до матча) — отдельный разбор

**Определение, которое важно зафиксировать:** «pre-match roster» бывает двух разных типов, и они смешиваются в большинстве обсуждений:
- **(A) Объявленный состав (registered/announced roster)** — кого организация заявила на турнир.
- **(B) Фактический состав на конкретный матч (с учётом стендинов)** — кто реально играет. **В рамках этого обзора бесплатного источника, который это гарантирует, не найдено** (формулировка «не найдено в обзоре», а не «не существует»).

| Источник | Тип A (объявленный) | Тип B (фактический, стендины) | Как получать | Ограничения |
|---|---|---|---|---|
| Liquipedia | Да (ростеры команд + трансферы) | Косвенно: смены состава фиксируются как трансферы/`TBD`, но не «кто вышел на эту карту» | MediaWiki API / LiquipediaDB API | 1 req/2s; CC-BY-SA 3.0 атрибуция; ручные правки → лаг |
| PandaScore (free pre-match) | Да — teams, players (по описанию free-плана) | Нет данных (подробный post/live отнесены к платным уровням) | REST + токен | Stats-планы только для non-betting usage → **исключён из critical path**, §3.5 |
| OpenDota `/proPlayers` | Частично: список про-игроков с `team_id`, `team_name`, `is_pro`, `last_login` ([docs.opendota.com](https://docs.opendota.com/)) | Нет | REST, без ключа | Производный от Valve-списка, исторически стареет; не учитывает стендинов; в docs нет гарантий частоты обновления |
| STRATZ (players/teams, GraphQL) | Вероятно да | НЕИЗВ. | Требуется токен | Маппинг и наличие upcoming-ростеров не подтверждены |
| Valve `GetTeamInfoByTeamID` | Инфо о команде | Нет | REST + ключ | Не документированный источник актуальных ростеров |
| NUKI1223/dota-predictor (reference) | — | Опосредованно: **в README заявлены** фичи «составы игроков из `player_matches`: личный винрейт пятёрки, сыгранность, детектор стендинов» (код/данные не проверялись) | — | Это **реконструкция** состава по истории матчей, а не «объявленный ростер» |

**Практический вывод:** бесплатный pre-match roster = **Liquipedia (тип A) + эвристика по `player_matches`/`proPlayers` (тип B)**, при этом тип B — это отдельная эвристика (стендин-детектор), а не готовые данные. Требование «точно знать, кто играет» **нельзя обещать на рассмотренных бесплатных источниках** (граница «гарантий» зависит от ещё не проведённых проб, U7).

---

### 6. Reference-проекты: точное сравнение `NUKI1223/dota-predictor` и `amarcu/dota-predictor`

Оба проекта **найдены** (не «предположительно существуют»): [github.com/NUKI1223/dota-predictor](https://github.com/NUKI1223/dota-predictor) и [github.com/amarcu/dota-predictor](https://github.com/amarcu/dota-predictor).

**Что именно было проверено (границы достоверности):** прочитаны **README**, **листинг файлов/папок** и метаданные репозитория (звёзды/форки/дата последнего коммита/наличие `LICENSE`). **Полный код-аудит НЕ проводился**: содержимое файлов не читалось, код не запускался, данные не скачивались. Поэтому ниже разделены три категории:
- `Наблюдаемо` — факт из README/листинга/метаданных;
- `Заявлено (self-reported)` — цифры и свойства, которые авторы декларируют в README;
- `Риск к проверке` — гипотеза о возможной проблеме (в т.ч. leakage), которую нужно подтвердить чтением кода/данных, а не установленный дефект.

#### 6.1 Сводная таблица

| Критерий | NUKI1223/dota-predictor | amarcu/dota-predictor |
|---|---|---|
| Точный URL | `https://github.com/NUKI1223/dota-predictor` (проверено) | `https://github.com/amarcu/dota-predictor` (проверено) |
| Лицензия | `Наблюдаемо`: явной лицензии **не обнаружено** — в корне нет `LICENSE` (в листинге `src/dota_predictor/`, `tests/`, `.gitignore`, `README.md`, `pyproject.toml`). **Это не юридический вывод:** отсутствие файла лицензии означает лишь неопределённость. Осторожная позиция проекта: **не копировать код до уточнения/получения разрешения от автора** | `Наблюдаемо`: лицензия **MIT заявлена** (`LICENSE` в корне; в README «MIT — see LICENSE»). Условия — по тексту `LICENSE` |
| Активность / зрелость | `Наблюдаемо`: 15 коммитов, 1 ветка, 0 тегов, 0 звёзд, 0 форков; последний коммит **2026-07-19** («Add EWC 2026 grand final case study to README») | `Наблюдаемо`: 8 коммитов, 1 ветка, 0 тегов, **1 звезда**, 0 форков; последний коммит **2026-08-26** (merge PR #2 «fix/demo-hero-embedding»); в README заявлен статус `Development Status :: 3 - Alpha`, «published as a single release commit in March 2026» |
| Задача | Предсказание вероятности победы в **профессиональных** матчах Dota 2 (pre-match + live + in-game), превью матчей | Предсказание вероятности победы Radiant **по минутам** игры (per-minute win probability), live-дашборд |
| Модели (`Заявлено` в README) | Elo + форма (v0, logistic regression) → CatBoost с draft-фичами (v1) → калибровка Platt/isotonic + ECE (v2) → **in-game CatBoost по графикам золота** (v7.1) | **2-слойный LSTM (128 hidden)** по 20 per-minute фичам + обучаемые hero-эмбеддинги (146×32), 244 866 параметров; один линейный per-minute голова |
| Live / in-game | `live.py` — трекер идущих про-матчей через **OpenDota `/live`**: предматчевая вероятность карты + текущее преимущество по золоту, сравнение с линией (`--odds`) | `scripts/live_predict.py` — живой терминальный дашборд через **Dota 2 GSI** (локальный HTTP-эндпоинт), обрабатывает spectator (`team2`/`team3`) и playing (`allplayers`) payloads |
| Draft | Да: `picks_bans`, bag-of-heroes, hero winrates с затуханием (half-life 90 дней), баны (v1, v5.1) | Только косвенно: hero embeddings по 10 пикам; драфт-логика/баны как фичи отсутствуют |
| Данные | `Заявлено (README)`: OpenDota REST + bulk через `/explorer` SQL (`--history-days 730` ≈ 54k матчей), фильтр тира лиги (`premium,professional`), внешний odds-CSV | `Заявлено (README)`: OpenDota `/proMatches` (default) или `/parsedMatches` → `/matches/{id}` через `aiohttp` c ограничением конкурентности и rate-limit (30 req/min без ключа, 3000/min с ключом), SQLite с дедупликацией по match_id. Пути файлов видны в листинге: `scripts/fetch_data.py`, `scripts/process_data.py` |
| Фичи | Elo, форма, draft/hero winrates, мета патча, форма на турнире («вторая по важности фича после Elo»), баны, составы (`player_matches`: личный винрейт пятёрки, сыгранность, детектор стендинов — стало «важнейшей фичей») | 20 per-minute: economy (8), kills (3), towers (3), barracks (3), roshan (3); zero-pad до 60 минут + маска валидности; hero IDs эмбеддинги |
| Заявленные метрики (`self-reported` в README; **воспроизводимость не проверялась**) | Лучший **log loss 0.6465** (с Platt) на v6; in-game: log loss **0.49** vs 0.55 эвристика vs 0.66 pre-match, accuracy **75%** (заявлено 163k поминутных срезов / 24.7k матчей) | В README про чекпойнт: epoch 46, **val loss 0.563**, **accuracy на последней минуте 94.11%** (train 94.19%); Brier/ECE не закоммичены |
| Валидация (`по README`; код не читался) | `Заявлено`: **временной сплит** (train — прошлое, test — будущее). Но метрики живут только в README → воспроизводимость не подтверждена | `Заявлено`: **случайный 80/20 сплит с фиксированным seed** (не временной); артефакты оценки уходят в git-ignored `experiments/` |
| Риски к проверке (leakage/correctness) — **гипотезы, а не подтверждённые дефекты** (код не читался) | (1) по README hero-winrate/форма считаются «по всем матчам», а обучение — по выбранным тирам: проверить, что каждая фича привязана по времени к матчу (иначе — утечка из будущего); (2) «форма на турнире до матча» заявлена leak-free — проверить в `src/dota_predictor/features/`; (3) личный винрейт игроков из `player_matches` — проверить наличие time-gate; (4) `--odds-csv` — проверить, не попадает ли закрывающая линия в признаки (пост-факт); (5) внешний LLM-слой превью — проверить, что его инструменты не читают «будущие» данные; (6) кейс-стади турнира в README — **не валидация** (нет неизменяемых таймстемпов прогнозов); (7) `tests/` в репозитории есть, но покрытие пайплайна не проверялось | (1) **случайный, а не временной сплит** (по README): матчи одного периода/патча/турнира могут попадать и в train, и в val → проверить влияние на метрики; (2) **94.11% на последней минуте** — близко к тривиальному (победитель почти определён), baseline-сравнения в репозитории не заявлено; (3) изотоник-калибраторы фитируются на том же случайном val-сплите — проверить; (4) чекпойнт не хранит датасет обучения (воспроизводимость под вопросом); (5) hero-эмбеддинги ограничены ID ≤145 → новые герои потенциально ломают инференс; (6) live-режим получает **подмножество** фич (нет towers/barracks/roshan) → возможен train/serve skew |
| Внешние платные зависимости | `Заявлено`: модуль `llm/` (по README) требует внешнего **платного LLM-API-ключа** → вне ограничения «только бесплатное» | По README платных зависимостей нет; опционально — публичный market-data API без credentials и библиотека ордеров (методы ордеров в коде есть, но скрипты их не вызывают) |
| Reuse vs reference | **Только reference:** явная лицензия не подтверждена → **не копировать код до разрешения автора**. Концепции к изучению: тир-фильтр лиг, bulk `/explorer`, калибровка + ECE, ban-фичи, roster-фичи, `/live`-трекер, in-game модель по золоту | **Кандидат на переиспользование под MIT** (условия — по тексту `LICENSE`). Наибольшая ценность: OpenDota-клиент с rate-limit и SQLite-дедупом, построение фич с маской, GSI-сервер + дашборд, метрики/evaluation-утилиты. Не переносить: методологию валидации (случайный сплит) |

#### 6.2 Что взять из каждого (архитектурный вердикт)

- Из **NUKI1223** — *методологию*: временной сплит, калибровку (Platt/isotonic + ECE), разделение pre-match и in-game слоёв, тир-фильтр лиг, использование `/explorer` для массовой истории, идею стендин-детектора по `player_matches`. **Не тащить код** (лицензия не подтверждена) и **не тащить внешний платный LLM-слой** (вне ограничения «только бесплатное» и потенциальный источник утечек).
- Из **amarcu** — *кандидаты на переиспользование* (**только после code- и license-аудита**, MIT заявлена): OpenDota-клиент с ограничением конкурентности и SQLite-кэшем, конструктор per-minute фич с маской, GSI-интеграцию с обработкой spectator-пейлоадов, оффлайн-предсказание с «обнулением будущего» (anti-leak на инференсе). **Не переносить**: случайный сплит, отсутствие baseline, отключённую калибровку, замороженный словарь героев.
- **Обязательная оговорка ко всем рекомендациям «взять/переиспользовать»:** это **кандидаты после аудита кода и лицензии**, а **не подтверждённая живая функциональность**. Ни один репозиторий не запускался, зависимости не проверялись, работоспособность под реальными лимитами источников (U1–U3, U5, U12–U13) не подтверждена.
- Оба проекта — **personal side projects**, не production-системы; по доступным материалам (README/листинг/метаданные) воспроизводимость их метрик **не подтверждается**. Использовать как **источники идей и заготовок**, а не как валидированную основу.

#### 6.3 Единая матрица: 6 кандидатов × 8 измерений

Легенда: **✓** — подтверждено docs/листингом; **~** — частично/с оговорками; **?** — не проверено (spike); **✗** — не покрывает / запрещено. Для репозиториев «✓» означает «заявлено в README и видно в структуре», а не «проверено запуском».

| Кандидат | Historical (матчи/статистика) | Upcoming (календарь) | Roster (объявленный) | Draft (пики/баны) | Live | Expert-контекст (стримы/интервью) | Market validation (сверка модель↔рынок) | Лицензия / ToS-условия |
|---|---|---|---|---|---|---|---|---|
| **OpenDota** | ✓ (REST, `/matches`, `/proMatches`, `/parsedMatches`; глубина — `?` U13) | ✗ в рассмотренных docs | ~ (`/proPlayers`, `/teams`; стареет, тип A) | ✓ (`picks_bans`, `draft_timings`) | ~ (`/live`; pro-live **не проверен**, задержка не гарантирована) | ✗ | ✗ (коэффициентов нет) | Публичных ToS в обзоре не найдено; цепочка прав Valve→OpenDota `?` (U8) |
| **STRATZ** | ~ (GraphQL; поля не аудированы) | ? (U2) | ? | ✓ (заявляет draft-аналитику) | ~ (нужен токен) | ✗ | ✗ | Free с referral-условиями для больших токенов; запрет читерства/скриптов |
| **PandaScore** | ~ (платные уровни: post-match/historical от 400 €) | ~ (есть в описании free, но **исключён** до письменного разрешения) | ~ (pre-match teams/players) | ? | ✗ (только платные уровни) | ✗ | ✗ (odds — отдельный продукт) | **Только non-betting usage**; проект с market/edge/backtest → требуется письменное разрешение (U8) |
| **Liquipedia** | ✓ (результаты/турниры; API-доступ `DOCS`, не тестирован) | ✓ структурно (расписания; `TBD`; API-доступ `?`) | ✓ (ростеры, трансферы) | ✗ (драфты как данные — нет) | ✗ | ~ (интервью/разборы есть как контент) | ✗ | CC-BY-SA 3.0 (атрибуция); HTML-доступ запрещён; API может быть отключён без предупреждения |
| **NUKI1223/dota-predictor** | ~ (пайплайн по README: `/explorer`, 730 дней) | ✗ | ~ (эвристика по `player_matches`, тип B; заявлено) | ✓ (по README: `picks_bans`, bag-of-heroes, баны) | ~ (`live.py` через OpenDota `/live`) | ~ (внешний LLM-слой превью — платный) | ~ (сверка с odds-CSV и «симуляция флэт-ставок» — **заявлено**, не воспроизведено) | Явной лицензии нет → **не копировать** код до разрешения |
| **amarcu/dota-predictor** | ~ (пайплайн по README: parsed-матчи, SQLite) | ✗ | ✗ | ~ (только hero-эмбеддинги, без банов) | ✓ (GSI, локальный) | ✗ | ~ (рыночные данные подключены для отображения рядом с моделью, не для валидации) | **MIT заявлена** (`LICENSE`); условия — по тексту лицензии |

**Практический смысл матрицы:** ни один кандидат не закрывает все измерения. Бесплатный «скелет» = **OpenDota (historical + draft + частично live) ⊕ Liquipedia (upcoming + контрактный roster)**, при полном отсутствии бесплатного «market validation»-источника: коэффициенты/рыночные данные придётся брать вне этого набора и отдельно проверять их правомерность (U8), а сверку «модель ↔ рынок» считать необеспеченной.

---

### 7. Блокирующие неизвестные (требуют spike перед обещаниями)

| # | Неизвестное | Почему блокирует | Минимальный spike |
|---|---|---|---|
| U1 | Точные rate-limit бакеты STRATZ Default Token (таблица на странице рендерится неоднозначно: 20/250/2000/10000 vs арифметика бакетов) | От этого зависит, можно ли строить ingestion на STRATZ | Войти через Steam, взять Default Token и провести **bounded, quota-compliant пробы**: по 1–2 запроса в каждом окне (сек/мин/час/сутки), фиксируя доступные заголовки (`X-RateLimit-*`, `Retry-After`). **Квоту не исчерпывать и 429 намеренно не провоцировать** |
| U2 | Есть ли в STRATZ GraphQL **upcoming/fixtures** (предстоящие серии) и **pre-match rosters** | Если да — upcoming можно закрыть без PandaScore/Liquipedia-обвязки | Introspection/тестовые запросы к схеме под токеном |
| U3 | Реальные бесплатные квоты OpenDota (3000/день по текущей странице vs 50 000/мес по блогу 2018 vs 2000/день по третьестороннему источнику) + отдельные ли лимиты у `/explorer` SQL | Определяет объём истории, которую можно тянуть бесплатно и за сколько дней | Bounded-пробы в течение 24 ч: несколько запросов с фиксацией заголовков + 1–2 запроса к `/explorer`; **не выбирать дневную/минутную квоту целиком** |
| U4 | LiquipediaDB API: одобряют ли доступ для личного инструмента, бесплатно ли, и покрывает ли структура (matches/rosters) нужные поля | Альтернатива — только MediaWiki API с парсингом шаблонов | Подать заявку (не платить, не обходить) и/или сделать парсер MediaWiki-шаблонов на 1 req/2s |
| U5 | Живы ли в 2026 дотa-методы Valve (`GetMatchHistory`, `GetLiveLeagueGames`/`GetTopLiveGame`, `GetTeamInfoByTeamID`) и что именно возвращают | Valve-слой может быть частично мёртв → влияет на резервный источник | Получить Steam-ключ и вызвать каждый метод, зафиксировать фактические ответы |
| U6 | Окно доступности реплеев: `replay_url`+`replay_salt` OpenDota и срок жизни ссылок Valve CDN | Определяет, возможен ли **свой** парсинг реплеев бесплатно (важно для in-game слоя) | Скачать 1–2 реплея сразу после матча и через 3/7/14 дней |
| U7 | Существует ли **бесплатный** источник «фактический состав на матч» со стендинами (тип B) | Влияет на честность обещаний по ростер-фичам | Ручная сверка Liquipedia ↔ `player_matches` на 5–10 матчах |
| U8 | Юридическая интерпретация: PandaScore free non-betting ToS (полный текст) и **квалификация нашего сценария** (market/edge/backtest — вероятно betting-related), объём share-alike CC-BY-SA 3.0, граница Steam ToU «unfair competitive advantage», а также **правомерность источников рыночных данных/коэффициентов** | Может запретить часть сценариев (особенно betting-adjacent и «помощь игроку во время матча») | Прочитать полные ToS по ссылкам §8 без регистрации; при сомнении — не строить сценарий и не включать источник в critical path |
| U9 | STRATZ referral-обязательства для Individual Token (1000/мес) и риск деактивации при их невыполнении | Инструмент без публичного трафика не сможет апгрейдить токен | Проверка условий по docs; планировать дизайн на Default Token |
| U10 | Отсутствие SLA у **всех** free-источников: частота отказов/пустых ответов (напр. известная проблема «empty response» у OpenDota), поведение при деградации | Нужна стратегия fallback и собственный health-monitoring | Недельный сбор `/health` и ошибок по каждому источнику |
| U11 | Правила хранения данных Twitch/YouTube (retention) для метаданных стримов/видео; права на транскрипты и цитаты | Может запретить локальное накопление истории CCV/VOD-метаданных и автоматизацию экспертного слоя | Прочитать Twitch ToS и YouTube API ToS; для транскриптов — только свои/лицензированные (см. §3.7) |
| U12 | **Pro-live: coverage / freshness / field parity.** В sample `/live` были только паблик-лобби (`league_id: 0`, `team_id_*: 0`), поэтому неизвестно: заполняются ли для турнирных лобби `league_id`/`series_id`/`team_*`; какова реальная задержка (`delay`) и частота обновления (`last_update_time`); совпадает ли набор полей live с историческим слоем; отдаёт ли live game-level ID во время матча | Пока не проверено — live **нельзя** ставить в critical path и нельзя обещать pro-live-покрытие/задержку | Во время известного турнирного матча сделать 3–5 сэмплов `/live`, зафиксировать `league_id`/`series_id`/`team_*`/`delay`/`last_update_time`/`match_id`, затем сверить с `/proMatches` после матча |
| U13 | **Историческая глубина/полнота:** реальный охват (доля про-матчей, глубина по годам), **идентификация карты в серии (map1/map2 и т.п.)**, покрытие parsed-полей (`/parsedMatches` vs raw), консистентность `leagueid`/`series_id`, доля доступных `replay_url` | Без аудита нельзя обещать «полный» исторический охват, корректное разбиение по картам серии и глубину in-game слоя | Выборка матчей за разные периоды: доля parsed, доля с `series_id`/картой, сверка map1-идентификации с внешним расписанием (Liquipedia), % доступных `replay_url` — bounded, quota-compliant пробы |
| U14 | Точные значения квоты YouTube Data API v3: в прочитанной таблице числа **противоречивы** (units vs calls/day для `search.list`/`videos.insert`) | От этого зависит планирование экспертного слоя | Сверить актуальную страницу [Quota Calculator](https://developers.google.com/youtube/v3/determine_quota_cost) и консоль квот; до этого числа считать `НЕИЗВ.` |
| U15 | Состав free-плана PandaScore по полям: входят ли **базовые результаты/счёты**, или «Results» в названии плана — маркетинговая формулировка, а данные только платные | Влияет на то, закрывает ли PandaScore хоть что-то бесплатно | Уточнить в официальных материалах/поддержке; **не регистрироваться без решения по U8** |

---

### 8. Короткий вывод для архитектуры

**Что можно обещать БЕСПЛАТНО по итогам обзора (с оговорками):**
1. **Исторический слой** — OpenDota без ключа (пробы через `web_fetch` отвечали читаемым JSON): матчи, драфты (`picks_bans`, `draft_timings`), таймсерии (у parsed-матчей), лиги/команды/герои. **Глубина и полнота истории требуют аудита** (U3, U13) — обещать конкретный «полный» охват нельзя.
2. **Live-состояние идущих игр** — **не входит в initial critical path, а отнесено к future conditional** (см. итоговую ставку ниже). Что наблюдалось в пробе `/live`: `game_time`, `radiant_lead`, счёт, `players[].account_id/hero_id`, `series_id`, `team_id_*`. Оговорки: **pro-live не проверен** (в выборке только `league_id: 0`), `delay` наблюдался один раз = 120 с и **не является гарантией**, field parity с историческим слоем не проверена (U12). Локальный **GSI** — отдельный опциональный путь для «своего» спектейта.
3. **Календарь будущих матчей** — основной путь: **Liquipedia** (MediaWiki API; API-доступ ещё не тестирован) + производные проекты как паттерн. **PandaScore в critical path не входит** (§3.5). OpenDota/Valve в рассмотренной документации этого не дают.
4. **Объявленные ростеры (тип A)** — Liquipedia (обязательна атрибуция CC-BY-SA 3.0).
5. **Контекст/экспертиза** — метаданные Twitch/YouTube в пределах их квот и ToS; слой **автоматизируем при правах/согласии и собственных транскриптах**; скачивание чужих транскриптов через API недоступно (§3.7).
6. **Reference-заготовки** — `amarcu/dota-predictor` заявлен под MIT (условия по `LICENSE`); `NUKI1223/dota-predictor` — только источник идей (лицензия не подтверждена).

**Что требует обязательного SPIKE до любых обещаний:**
- Предсказательная ценность pre-match модели (временная валидация + baseline) — **нельзя** обещать точность/калибровку, опираясь на README reference-проектов.
- Upcoming-покрытие: полнота, частота `TBD`, лаг, доступность через API (а не HTML) и разрешение конфликтов между источниками.
- Квоты и их фактическая достаточность: OpenDota (U3), STRATZ (U1), `/explorer`-лимиты — только bounded, quota-compliant пробами.
- Наличие у STRATZ upcoming/rosters (U2) и рабочие ли Valve-методы (U5).
- Свой парсинг реплеев (U6) + выбор OSS-парсера (§3.6a) — от этого зависит глубина in-game слоя без платных провайдеров.
- Roster тип B (фактический состав/стендины) — **нельзя обещать на рассмотренных бесплатных источниках**; максимум — эвристика по `player_matches`.
- Юридический статус: квалификация использования как betting-related (U8) и правомерность источников рыночных данных.

**Что НЕЛЬЗЯ обещать бесплатно:** SLA/гарантированную свежесть (нет ни у одного рассмотренного источника); гарантированную задержку/покрытие live по чужим матчам; гарантированные составы на матч; подробные post-match данные уровня платных тарифов провайдеров; «market validation» (источника рыночных данных в бесплатном наборе нет); воспроизводимость метрик чужих репозиториев как доказательство качества.

**Итоговая ставка для соло-фаундера (initial critical path):** **в initial critical path входит только OpenDota HISTORY** (исторический слой: матчи, драфты, таймсерии) — как primary, с оговоркой обязательного аудита глубины/полноты (U13). **Live — future conditional, а не primary live:** pro-live покрытие/свежесть/паритет полей не проверены (U12), поэтому live-слой можно обещать только после отдельных проб. Далее: **Liquipedia как отдельный upcoming/roster-контур**, **STRATZ как вторичный после получения токена**, Valve-слой и GSI — опциональные дополнения. **PandaScore — вне critical path** до письменного подтверждения. Обязательны: собственный кэш, rate-limiters под каждый источник, атрибуция (Liquipedia), разделение «проверенные факты» / «заявлено» / «эвристики» в UI и деградация без SLA.

---

### Приложение A. Индекс использованных URL (читались в этой сессии; API-эндпоинты, кроме отмеченных проб `ЭНДПОИНТ(proxy)`, не тестировались)

Документация/цены: [docs.opendota.com](https://docs.opendota.com/) · [opendota.com/api-keys](https://www.opendota.com/api-keys) · [blog.opendota.com (2018-04-17)](https://blog.opendota.com/2018/04/17/changes-to-the-api/) · [github.com/odota/dotaconstants](https://github.com/odota/dotaconstants) · [stratz.com/api](https://stratz.com/api) · [stratz.com/knowledge-base/API](https://stratz.com/knowledge-base/API) · [api.stratz.com/graphiql](https://api.stratz.com/graphiql) · [stratz.medium.com (2021-11-20)](https://stratz.medium.com/stratz-api-major-update-5557335dbdfd) · [medium.com/stratz (2019-11-30)](https://medium.com/stratz/dota-7-23-graphql-631ea1d5f173) · [stratz.com](https://stratz.com/) · [steamcommunity.com/dev](https://steamcommunity.com/dev) · [steamcommunity.com/dev/apiterms](https://steamcommunity.com/dev/apiterms) · [steamcommunity.com/dev/apikey](https://steamcommunity.com/dev/apikey) · [liquipedia.net/api-terms-of-use](https://liquipedia.net/api-terms-of-use) · [liquipedia.net/api](https://liquipedia.net/api) · [liquipedia.net/dota2/Liquipedia:Upcoming_and_ongoing_matches](https://liquipedia.net/dota2/Liquipedia:Upcoming_and_ongoing_matches) · [liquipedia.net/commons/Liquipedia:API_Usage_Guidelines](https://liquipedia.net/commons/Liquipedia:API_Usage_Guidelines) · [tl.net API guidelines (2015)](https://tl.net/forum/hidden/491339-liquipedia-api-usage-guidelines) · [pandascore.co/pricing](https://www.pandascore.co/pricing) · [developers.pandascore.co — Dota 2 matches](https://developers.pandascore.co/reference/get_dota2_matches) · [dev.twitch.tv/docs/api/guide](https://dev.twitch.tv/docs/api/guide) · [developers.google.com/youtube/v3/determine_quota_cost](https://developers.google.com/youtube/v3/determine_quota_cost) · [developer.valvesoftware.com/wiki/Dota_2_Game_State_Integration](https://developer.valvesoftware.com/wiki/Dota_2_Game_State_Integration) · [steamwebapi.azurewebsites.net (неофиц. зеркало)](https://steamwebapi.azurewebsites.net/) · [YouTube captions.download](https://developers.google.com/youtube/v3/docs/captions/download)

Репозитории/проекты: [NUKI1223/dota-predictor](https://github.com/NUKI1223/dota-predictor) · [amarcu/dota-predictor](https://github.com/amarcu/dota-predictor) · [beeequeue/dota-matches-api](https://github.com/beeequeue/dota-matches-api) · [c00kie17/liquipediapy](https://github.com/c00kie17/liquipediapy) · [EthanWadsworth/valve-steam-web-api](https://github.com/EthanWadsworth/valve-steam-web-api) · [ribasco/async-gamequery-lib](https://ribasco.github.io/async-gamequery-lib/examples/webapi_dota2_example.html) · [arXiv:2106.01782](https://arxiv.org/abs/2106.01782)

Replay-парсеры (OSS, §3.6a): [skadistats/clarity](https://github.com/skadistats/clarity) · [odota/parser](https://github.com/odota/parser) · [odota/core](https://github.com/odota/core) · [odota/web](https://github.com/odota/web)

Прочее/третьестороннее (низкая надёжность, помечено в тексте): [reddit — live API для Dota 2](https://www.reddit.com/r/DotA2/comments/1ntva37/live_api_for_dota_2_matches/) · [reddit — OpenDota empty responses](https://www.reddit.com/r/DotA2/comments/1dhpv35/opendota_api_returning_empty_response_all_of_a/) · [reddit — Steam GetMatchHistory](https://www.reddit.com/r/DotA2/comments/vndwu6/steam_api_the_problematic_getmatchhistory_method/) · [reddit — Noxville AMA](https://www.reddit.com/r/DotA2/comments/533hjx/hey_im_noxville_i_do_dota_related_statistics_ama/) · [datdota.com](https://datdota.com/) · [datdota.com/about](https://datdota.com/about) · [dota2.balldontlie.io](https://dota2.balldontlie.io/) · [citoapi.com/dota-2-api](https://citoapi.com/dota-2-api/) · [parse.bot — Dota2ProTracker (третьестороннее)](https://parse.bot/marketplace/88cc8d49-9a24-4a20-b021-0bef5a8b1815/dota2protracker-com-api) · [True Sight TI2018](https://www.youtube.com/watch?v=Bv4CqIxqTMA) · [True Sight TI2019](https://www.youtube.com/watch?v=ceQ2XFS1tUo)

---


## Part 10 — Первые 10 задач

**Тип документа:** краткий навигационный документ. **Полные карточки задач находятся только в `BACKLOG.md`** — здесь они не дублируются.
**Проект:** Dota Esports Intelligence Platform, solo-founder, только бесплатные источники, личный инструмент.
**Статус:** все 10 задач — `Planned`/`Proposed`. **Ни одна не выполнена и не выполняется.** Документ не является разрешением на исполнение.
**Основание:** `SOURCES.md`, `BACKLOG.md`.
**Смысл первых 10:** они дают **вертикальный РЕТРОСПЕКТИВНЫЙ прототип** (raw → нормализация → фичи as-of → baseline LR → immutable snapshot → простой локальный UI на реальной held-out исторической game1). Это **НЕ полноценный pre-match MVP**.

---

### 1. Список первых 10 задач (ID идентичны `BACKLOG.md`)

| № | TASK ID | TITLE | EPIC | PRIORITY | STATUS | DEPENDENCIES |
|---|---|---|---|---|---|---|
| 1 | `PRD-001` | Согласовать цель / первую карту / гейты / правила cutoff | 00 — Product specification | P0 | Proposed | — |
| 2 | `SRC-001` | Документированный bounded read-only audit: OpenDota history + Liquipedia legal/access/upcoming requirements; никакие credentials не выдумываются | 02 — Data ingestion | P0 | Proposed | `PRD-001` |
| 3 | `INF-001` | Воспроизводимый локальный скелет репозитория + smoke test (не фактическое выполнение здесь) | 01 — Repository and infrastructure | P0 | Planned | `PRD-001`, `SRC-001` |
| 4 | `DB-001` | Минимальная ядровая temporal-схема + snapshots / migrations / constraints | 03 — Database | P0 | Planned | `INF-001` |
| 5 | `ING-001` | OpenDota клиент + raw capture: sync-once, pagination, retry, quota, idempotence | 02 — Data ingestion | P0 | Planned | `SRC-001`, `DB-001` |
| 6 | `DATA-001` | Нормализация исторических games / team / player / series, map index, participant stats, evidence roster versions, patch; карантин неоднозначного map1 | 03 — Database | P0 | Planned | `ING-001` |
| 7 | `FEAT-001` | Минимальный prior-form датасет as-of для map1, **включая минимальные Team- и Player-prior-form**; coverage masks; режимы event vs observed | 05 — Team intelligence | P1 | Planned | `DATA-001` |
| 8 | `ML-001` | Prior + Logistic Regression baseline: temporal group split, frozen heldout, Brier/logloss; research only, **CatBoost ещё нет** | 10 — Baseline ML | P1 | Planned | `FEAT-001` |
| 9 | `API-001` | Prediction service: immutable snapshots + API + шаблонное evidence; enforcement меток historical vs real future; цель — только game1 | 12 — Prediction API | P1 | Planned | `ML-001`, `DB-001` |
| 10 | `UI-001` | Простая локальная страница матча на реальной held-out исторической game1; явно ретроспектива (не «живой» прогноз); provenance / модель / версия / причины | 13 — Frontend MVP | P1 | Planned | `API-001` |

**Порядок исполнения — строго по списку** (он уже топологически отсортирован: каждая задача зависит только от предыдущих).

**Что вертикальный срез доказывает, а что нет:**
- Доказывает: пайплайн способен пройти путь от сырых исторических данных до неизменяемого предсказания и показать его с провенансом, не нарушая временную семантику.
- **НЕ доказывает:** готовность к реальному pre-match прогнозу. Полноценный MVP требует легального upcoming-адаптера, свежести ростера, hero pool из истории, patch weighting + missing masks, CatBoost challenger (**обучен и сравнён**; победа над LR не обязательна), calibration freeze, оценки исходов (`EVAL-001`), **фактически работающего** автоматического обнаружения/ingestion в будущем локальном deployment (`ING-008`) и операционных/ML-гейтов (`MON-001`) (см. `BACKLOG.md`, §1 п.11 и Приложение A).

---

### 2. Текущий статус и точка решения

- **Текущий эпик:** `EPIC 00 — Product specification`.
- **Текущая задача:** `PRD-001` (статус `Proposed`, приоритет `P0`).
- **Требуемое решение владельца:** утвердить продуктовую спецификацию v0 — цель (победа Team A на первой карте предстоящей Series, conditional game played, before draft), определение первой карты, правила cutoff/временной семантики, перечень гейтов с **проектными** порогами и владельцами, список non-goals, а также **рассмотреть предложенные контракты §1 `BACKLOG.md`** (все они `PROPOSED`: альтернативы не отклоняются, изменение — через ADR + вердикт owner).
- **Следующее действие после утверждения:** перейти к задаче `SRC-001` (bounded read-only audit источников) — только **после явного одобрения** владельцем.
- **Далее: STOP.** До этого одобрения никакие задачи, включая `SRC-001` и последующие, не начинаются. Ничего не запускается, не конфигурируется и не выполняется.

---

### 3. Блокер: если источник окажется no-go

Логика блокировки соответствует гейту **G-SRC** (итог `SRC-001`). Вердикт **разделён на два независимых случая** — отказ по истории и отказ по upcoming — и приводит к разным последствиям.

**Случай A — не сработала ИСТОРИЯ (OpenDota history недоступна/непригодна).**
- **Точка остановки: STOP до `INF-001`.** Строить репозиторий, БД и пайплайн без пригодных исторических данных бессмысленно.
- **Что тогда:** фиксируется отсутствие базы; `INF-001` и все последующие задачи **не начинаются**.
- **Запрещено:** подменять источник нелегальным/непроверенным путём, HTML-scraping, выдумывание credentials, заполнение пробелов синтетикой под видом данных.

**Случай B — история работает, но не сработал UPCOMING (легального бесплатного пути нет).**
- **Точка остановки:** полноценный pre-match MVP **не объявляется**; работа фиксируется на **ретроспективном прототипе** (первые 10 задач), который сохраняет ценность как исследовательский инструмент.
- **Условие:** Liquipedia API недоступен/непригоден по покрытию или правам; PandaScore остаётся исключённым до письменного разрешения; STRATZ без подтверждённых upcoming/rosters.
- **Запрещено:** обход ToS, HTML-scraping, использование исключённых источников в critical path, обещания точности/прибыльности.

**Общее для обоих случаев:**
- **Кто принимает вердикт:** владелец (owner), вручную. Автоматического прохождения гейта не существует.
- **Что фиксируется в артефактах:** какой именно случай реализовался, причина, список проверенных путей, статус «проверено/заявлено/неизвестно», явная формулировка «данных нет», если их нет.
- **Что дальше:** только по отдельному решению владельца — остаться в ретроспективном контуре или пересмотреть scope. Никаких обходных путей не предлагается и не реализуется автоматически.

---

### 4. Границы этого документа

- Нет кода, нет инструкций по запуску cron/recurring-задач, нет создания/конфигурирования автоматизации.
- Нет оценок сроков разработки и нет выдуманных метрик.
- Нет утверждений, что что-либо уже сделано.
- Полные карточки (GOAL / CONTEXT / INPUT / OUTPUT / ACCEPTANCE CRITERIA / TESTS / FILES EXPECTED TO CHANGE / RISKS / DEFINITION OF DONE) — **только в `BACKLOG.md`**.
- Приоритет не выводится из стадии: в `FUTURE` есть как `P2` (необходимые проверки/реализация: live, heatmaps, market, backtest, LLM, automation, deployment), так и `P3` (**только** спекулятивные направления: `SYN-004`, `DRAFT-005`).

---


## Part 11 — Полный backlog (EPIC 00–22)

**Тип документа:** полный рабочий бэклог (продуктовая и техническая декомпозиция). Это **не код** и **не план исполнения в текущей сессии**. Ни одна задача здесь не запускается, не конфигурируется и не выполняется.
**Проект:** личный исследовательский инструмент одного основателя, только бесплатные источники.
**Статус документа:** Proposed / Planned. **Ни одна задача не объявлена выполненной.**
**Основание:** `SOURCES.md` (архитектурное исследование источников, дата пакета исследования 2026-09-16). Все ссылки на источники, лимиты и неизвестные (U1–U15) берутся из `SOURCES.md` и здесь не переизобретаются.
**Связанный документ:** `FIRST_10_TASKS.md` (первые ровно 10 задач; ID совпадают с этим файлом, полные карточки — только здесь).

---

### 0. Как читать бэклог

- **Epic** — крупная область (00–22), 23 эпика.
- **Task** — небольшая самостоятельная единица работы с полным набором полей.
- **Стадии** (поле `STAGE` внутри карточки): `MVP-FIRST10` → `MVP` → `MVP2` → `MVP3` → `FUTURE`.
- **Приоритет** (`P0`–`P3`) — **внутри активной стадии**. Запрещено брать `P2`/`P3` раньше незакрытых `P0`/`P1` и `P3` раньше незакрытых `P2`. Приоритет **не** определяется стадией: в стадии `FUTURE` есть и `P2` (необходимые проверки/реализация), и `P3` (спекулятивные направления).
- **Зависимости** — только на **существующие** ID из этого файла, только ациклические, покрывают необходимые данные/модели.
- **Гейты (gates)** — это тоже задачи; вердикт всегда даёт **владелец (owner)** вручную. Автоматической реализации гейтов не существует.
- **FILES EXPECTED TO CHANGE** может перечислять **будущие/планируемые** пути (инфраструктура, обучение моделей, нормализация и т.п.). Упоминание файла **не означает, что он уже существует**.

#### Легенда статусов

| Статус | Значение |
|---|---|
| `Proposed` | предложено; ни решения, ни работы, ни артефактов |
| `Planned` | запланировано к реализации; работы не начаты |

Оба статуса означают «не сделано». Никаких `Done` в документе нет.

#### Легенда приоритетов

| Приоритет | Значение |
|---|---|
| `P0` | критический фундамент: без него нет ни прототипа, ни платформы |
| `P1` | обязательная часть MVP (полноценный pre-match MVP после первого прототипа) |
| `P2` | развитие и **необходимые** проверки/реализация: MVP2/MVP3, а также Future-компоненты, которые нужны для своей стадии (live, heatmaps, market, backtest, LLM, automation, deployment) |
| `P3` | **только спекулятивные** направления, не требующиеся для ближайших стадий (например, GNN/RL-подходы, representation learning) |

---

### 1. Предлагаемые контракты для согласования (PROPOSED)

**Статус: все пункты ниже — `PROPOSED`.** Владелец их **не утверждал**. Это предложения для согласованности между задачами, а **не** замороженные догмы:

- **альтернативы не отклоняются**; задача не отклоняется только из-за расхождения с черновиком;
- любое изменение контракта оформляется как **ADR** (контекст → решение → последствия → рассмотренные альтернативы) и требует **вердикта owner**;
- до утверждения действует принцип «предложение по умолчанию», а не запрет;
- принятие/правка/отклонение по каждому пункту входит в `PRD-001` и `PRD-004`.

1. **Форма (PROPOSED):** Python modular monolith. PostgreSQL: **raw и snapshot — JSONB**; **canonical — типизированные реляционные таблицы** (`typed columns`, FK, PK, индексы); JSONB допустим только для raw, snapshot и variable payload **внутри** типизированной схемы. API — FastAPI. Аналитика — pandas. ML — sklearn (prior + Logistic Regression), затем **CatBoost challenger на CPU** (не раньше, чем после baseline; challenger не обязан побеждать — см. §2 G-MODEL). Docker **локально**.
2. **Явные «нет»:** без Redis, без Celery, без Kafka, без Kubernetes, без feature store.
3. **Frontend:** MVP — простые **server-rendered templates**. React — **опционально Future**.
4. **Automation runtime:** в текущем чате недоступна. Формулируются только **архитектурные требования** к будущему локальному worker. **Не создавать, не конфигурировать и не инструктировать запуск cron/recurring-задач здесь.**
5. **Источники:** primary — **OpenDota history**. Upcoming — **Liquipedia API** и **ТОЛЬКО условно**, после gate «legal/access + coverage spike». **HTML-scraping запрещён.** STRATZ — опциональная альтернатива с токеном. **PandaScore исключён** до письменного одобрения провайдера, потому что проект содержит betting-related market-анализ (даже если он приватный). Если легального бесплатного upcoming нет — **STOP на ретроспективном прототипе**; полноценный MVP не объявляется завершённым.
6. **Цель предсказания MVP:** победа **Team A на ПЕРВОЙ КАРТЕ** предстоящей Series, при условии что игра состоялась (conditional game played), **до драфта**; это **НЕ series win**. Team A — стабильный канонический ID, сторона неизвестна. Семантика: Match = запланированная встреча (фикстура), Series = competitive BO-исполнение (опционально 1:1 с Match), Game = карта (placeholder до появления provider ID). Вероятность серии — отдельная задача MVP2. Всегда поддерживаются метки forfeit/void/unknown (без спортивной метки).
7. **Снимки сразу:** минимальные **immutable** `Prediction` / `PredictionSnapshot` + `FeatureSnapshot` + `ModelVersion` — уже с первого прототипа, а не с MVP2. Историческая оценка обязана называться `retrospective_reconstructed`, а не «predicted then». Строгое `observed_at <= cutoff` возможно только для проспективно архивированной истории.
8. **Временная семантика:** различать `event_time`, `source_published_at`, `observed_at`, `available_at`, `ingested_at`. Финальная статистика матча и наблюдаемый фактический ростер-цели **запрещены** до матча. Используется **prior known roster** с uncertain/fallback. Обучающие availability-маски имитируют условия инференса.
9. **Историческое ядро:** нормализованные `Team` / `Player` / `GameParticipant` / `PlayerPerformance`, минимальные `Tournament` / `Stage`, `Patch`, `RosterMembership` **по свидетельствам, не перезаписываемый текущим состоянием**, `EntityMapping` провайдерских ID с карантином при неоднозначности.
10. **ML-дисциплина:** все baseline-трансформации фитятся **только на train**. Temporal train → tuning → calibration → untouched test по сериям, с purge на пересечении серий. Широкое обучение «все игры» допустимо только как отчёт о gap для map1-cohort; рекомендация MVP — обучение **только на map1**. Снимки сохраняются на инференсе; объяснения — **шаблонные evidence, не LLM**.
11. **Полный MVP после first-10 требует:** легальный upcoming-адаптер; свежесть/качество ростера; hero pool из исторических карт (не из целевого драфта); patch weighting + missing masks; CatBoost challenger **обучен и сравнён** с LR (победа не обязательна); calibration freeze; операционные и ML-гейты покрытия пайплайна/данных; **фактически работающее** автоматическое обнаружение и ingestion в будущем локальном deployment (`ING-008`) — **дизайн в чате не заменяет реализацию**. Ничего не запускается и не конфигурируется здесь. У гейтов есть **проектные** пороги (см. §2) и **вердикт owner**, а не обещание прибыльности.
12. **Экспертный слой (MVP3):** сначала **права/согласие** — собственные или предоставленные транскрипты; затем LLM-извлечение в JSON с evidence/span/time и оценкой; никакого «доверия эксперту по умолчанию»; confidence извлечения ≠ вероятность исхода; признак не включается в модель без ablation. Каналы Nix, RAMZES, Solo, NS — **кандидаты-сущности, а не проверенные хендлы**.
13. **Live / heatmaps:** access & replay suitability spikes обязательны до реализации. Нельзя обещать `/live` про-поля на основе только публичной выборки. GSI требует авторизованного **локального spectator-клиента**, а не серверного глобального фида. Нужны legal permissions + payload historical parity.
14. **Market — только ANALYSIS.** Наличие бесплатных исторических timestamped odds неизвестно; используется правомерный CSV, предоставленный пользователем (нельзя фабриковать данные); commission/margin/de-vig; фактическое decision time и executability; CLV на **matched market**; bankroll/settlement/малые выборки. **Автоматические ордера запрещены.**

---

### 2. Стадии и гейты верхнего уровня

| Стадия | Содержание | Покрывается эпиками |
|---|---|---|
| `MVP-FIRST10` | вертикальный **ретроспективный** прототип: raw → нормализация → фичи as-of → baseline LR → immutable snapshot → простой локальный UI на реальной held-out исторической game1 | 00, 01, 02, 03, 05, 10, 12, 13 |
| `MVP` | полноценный pre-match MVP: legal upcoming, свежесть ростера, hero pool, patch weighting, CatBoost challenger, calibration freeze, операционные/ML-гейты | 00, 01, 02, 03, 05, 08, 09, 10, 11, 12, 13, 21 |
| `MVP2` | draft/synergy/tournament/deeper patch, player intelligence, series probability | 04, 06, 07, 08, 09, 10, 12, 13 |
| `MVP3` | expert intelligence (права → extraction → evaluation) | 14 |
| `FUTURE` | live → heatmaps → market/backtest → LLM + notifications | 15, 16, 17, 18, 19, 20, 21, 22 |

**Приоритет не выводится из стадии:** внутри `FUTURE` есть и `P2` (необходимые проверки и реализация для своей стадии), и `P3` (только спекулятивные исследования, например GNN/RL). Категорическое «весь Future = P3» **не применяется**.

**Порядок внутри Future (rollout):** live → heatmaps → market/backtest → LLM + notifications. Research-часть heatmaps независима, но rollout heatmap-слоя — **после** `G-LIVE`.

**Верхнеуровневые гейты (решение owner, не автоматика):**

- **G-SRC** — итог `SRC-001` (раздельно история и upcoming):
  - **история недоступна/непригодна → STOP до `INF-001`** (нет смысла строить репозиторий и пайплайн без данных);
  - **upcoming недоступен при работающей истории → только ретроспективный прототип** (`MVP-FIRST10`), полноценный MVP не объявляется.
- **G-UPCOMING** — итог `ING-004`: легальный доступ + покрытие + пригодность Liquipedia API. Только при прохождении — продолжение к полному MVP.
- **G-ROSTER** — итог `TEAM-002`: признаётся ли качество/свежесть ростера достаточной (тип A + эвристика).
- **G-MODEL** — итоги `ML-002` + `EVAL-001` + `CAL-002/003`: CatBoost challenger **обучен и сравнён** с LR, но **не обязан побеждать** для MVP (champion'ом может остаться LR). Выбор/промо модели — **на tuning folds**; калибровка — отдельный шаг; **untouched test — только итоговый гейт**, он не используется для подбора победителя.
- **G-OPS** — итог `MON-001` + `ING-008`: операционные и ML-гейты покрытия пройдены, включая **фактически работающее** автоматическое обнаружение/ingestion в будущем локальном deployment.
- **G-LIVE** / **G-HM** / **G-MARKET** — итоги spikes `LIVE-001`, `HM-001`, `MKT-001`: доступ, право, паритет payload. Research-часть heatmaps независима, но **rollout heatmap-слоя (`HM-003`) — после `G-LIVE`**. До прохождения соответствующего гейта реализации нет.

**Проектные пороги гейтов (это определения, а не достигнутые значения):**

- **Purity:** critical temporal/purity violations = **0**;
- **Mapping:** unmapped evaluation records = **0** в eval-когорте;
- **Coverage (полный MVP):** доля покрытия **>= 90%** на **фиксированном заранее** знаменателе — **30 последовательных real eligible game1 fixtures**; gaps репортятся раздельно **по источнику** и **по модели**;
- **Статистика:** на 30 наблюдениях **никаких заявлений о значимости**; frozen test считается достаточным только если достигает **выбранной заранее в PRD точности**; неопределённость — **grouped bootstrap по сериям/времени**; если выборка слишком мала — вердикт **insufficient evidence**.

Ни один из этих порогов **не считается достигнутым**; никакие фактические метрики не заявляются.

---

### 3. Общий Definition of Done

#### 3.1 Общий DoD для coding-задач

Задача считается завершённой (в момент, когда её вообще разрешено выполнять), только если:

1. Код в репозитории, запускается **локально/Docker-appropriate** воспроизводимо (без «магии окружения»), зависимости зафиксированы, обязательных облачных/внешних зависимостей нет.
2. Все входные данные, параметры и версии артефактов записаны в run manifest; повтор запуска даёт тот же результат (или явно документировано, почему нет).
3. **Логирование:** ключевые шаги и решения логируются **структурно, с провенансом** (вход, версия артефакта, cutoff), без секретов.
4. Автотесты задачи проходят; добавлены тесты на границы/ошибки, а не только happy path. **No regressions:** ранее существовавшие тесты остаются зелёными.
5. Прогон на реальном (не синтетическом) срезе данных выполнен и результат приложен; синтетика помечена как синтетика. **Исключение:** для **чистых UI- и unit-задач** достаточно фикстур/записанных данных — реальный прогон внешнего API от них не требуется.
6. Нет нарушений предложенных контрактов (§1) либо расхождение оформлено ADR с вердиктом owner; отсутствуют запрещённые компоненты (Redis/Celery/Kafka/K8s/feature store) и HTML-scraping.
7. Временная семантика соблюдена: ни один признак в момент cutoff не использует данные с `available_at > cutoff`; финальные статистики и фактический целевой ростер не читаются до матча; critical purity violations = 0.
8. Обновлена документация задачи (что сделано, где лежит, как повторить) без выдуманных метрик и без обещаний прибыльности/точности.
9. Явно указано, что результат **не** является доказательством продакшн-качества, если это так.

#### 3.2 Общий DoD для research-задач (spike/audit/design)

1. Явно разделены три категории: **проверено** (наблюдаемо/воспроизводимо), **заявлено вендором** (self-reported), **неизвестно** (требует повторного spike).
2. Все пробы **bounded и quota-compliant**: не исчерпывать суточные/минутные квоты, не провоцировать 429 намеренно, не обходить ToS.
3. Указаны точные условия доступа (ключ/токен/лицензия/атрибуция) и юридические ограничения, включая share-alike и запрет HTML-доступа, где применимо.
4. Сформулирован **go/no-go вердикт-кандидат** с метрикой и указанием, кто его утверждает (owner).
5. Если данных нет — прямо написано «данных нет», без заполнения дырок догадками.
6. Результат оформлен как воспроизводимый отчёт-артефакт с датой и методом (браузер/инструмент/эндпоинт), а не как устное утверждение.

#### 3.3 Task-specific DoD

Каждая карточка имеет **собственный** `DEFINITION OF DONE`. Общий DoD (§3.1/§3.2) применяется **дополнительно** и не заменяет task-specific.

---

### 4. Сводка по эпикам

| Epic | Название | Стадия | Задач | Приоритеты |
|---|---|---|---|---|
| 00 | Product specification | MVP-FIRST10 / MVP | 4 | P0×1, P1×3 |
| 01 | Repository and infrastructure | MVP | 5 | P0×1, P1×3, P2×1 |
| 02 | Data ingestion | MVP-FIRST10 / MVP / FUTURE | 9 | P0×2, P1×5, P2×2 |
| 03 | Database | MVP-FIRST10 / MVP | 6 | P0×2, P1×2, P2×2 |
| 04 | Tournament intelligence | MVP2 | 3 | P2×3 |
| 05 | Team intelligence | MVP-FIRST10 / MVP / MVP2 | 4 | P1×3, P2×1 |
| 06 | Player intelligence | MVP2 | 2 | P2×2 |
| 07 | Player synergy | MVP2 / FUTURE | 4 | P2×3, P3×1 |
| 08 | Patch intelligence | MVP / MVP2 | 3 | P1×2, P2×1 |
| 09 | Draft intelligence | MVP / MVP2 / FUTURE | 5 | P1×1, P2×3, P3×1 |
| 10 | Baseline ML | MVP-FIRST10 / MVP / MVP2 | 5 | P1×3, P2×2 |
| 11 | Calibration | MVP | 3 | P1×3 |
| 12 | Prediction API | MVP / MVP2 | 5 | P1×4, P2×1 |
| 13 | Frontend MVP | MVP / MVP2 | 3 | P1×2, P2×1 |
| 14 | Expert intelligence | MVP3 | 5 | P2×5 |
| 15 | Heatmaps | FUTURE | 3 | P2×3 |
| 16 | Live engine | FUTURE | 3 | P2×3 |
| 17 | Market intelligence | FUTURE | 4 | P2×4 |
| 18 | Backtesting | FUTURE | 3 | P2×3 |
| 19 | LLM analyst | FUTURE | 3 | P2×3 |
| 20 | Automation | MVP2 / FUTURE | 3 | P2×3 |
| 21 | Monitoring | MVP / MVP2 / FUTURE | 3 | P1×1, P2×2 |
| 22 | Production deployment | FUTURE | 2 | P2×2 |

**Итого задач: 90.** Разбивка по приоритетам: **P0 = 6, P1 = 32, P2 = 50, P3 = 2.**

`P3` — **только** спекулятивные направления: `SYN-004`, `DRAFT-005`. Все необходимые проверки и реализация Future-компонентов (live, heatmaps, market, backtest, LLM, automation, deployment) отнесены к `P2`.

Разбивка по стадиям: `MVP-FIRST10` = 10 задач; `MVP` без first-10 = 28 задач (`MVP` всего = 38); `MVP2` = 22 задачи; `MVP3` = 5 задач (`EXP-001..005`); `FUTURE` = 25 задач (смесь `P2` и `P3`). Проверка: 10 + 28 + 22 + 5 + 25 = 90.

---

---

### EPIC 00 — Product specification

#### PRD-001 — Согласование цели, первой карты, гейтов и правил cutoff
- **EPIC:** 00 — Product specification
- **STAGE:** MVP-FIRST10
- **PRIORITY:** P0
- **STATUS:** Proposed
- **GOAL:** Зафиксировать в одном согласованном документе: цель предсказания, что именно считается «первой картой», правила cutoff/временной семантики и перечень гейтов.
- **CONTEXT:** Без однозначной цели рискуют разойтись все последующие эпики. Цель — победа Team A на первой карте предстоящей Series (conditional game played, before draft), НЕ series win. Team A — стабильный канонический ID, сторона неизвестна.
- **INPUT:** `SOURCES.md`; §1 этого бэклога; неформальная цель проекта от владельца.
- **OUTPUT:** Согласованный product-spec v0: цель, определение Match/Series/Game, определение map1, cutoff-правила, список гейтов (G-SRC/G-UPCOMING/G-ROSTER/G-MODEL/G-OPS/G-LIVE/G-HM/G-MARKET), список non-goals, предварительное одобрение owner.
- **DEPENDENCIES:** —
- **ACCEPTANCE CRITERIA:** (1) Цель сформулирована так, что «series win» и «map1» не смешиваются. (2) Явно записано: forfeit/void/unknown не получают спортивной метки. (3) Для каждого гейта указаны метрика и владелец вердикта. (4) Есть раздел non-goals (без Redis/Celery/Kafka/K8s/feature store, без HTML-scraping, без автоторговли). (5) Владелец подтвердил документ. (6) **Контракты §1 рассмотрены** по каждому пункту: принят / правка через ADR / отклонён — статус `PROPOSED` не остаётся молча «замороженным». (7) Определены **выбранная заранее точность** frozen test и проектные пороги (`coverage >= 90%` на 30 последовательных real eligible game1 fixtures, purity critical violations = 0, unmapped evaluation records = 0).
- **TESTS:** Ревью владельцем; проверка на противоречия с §1; контрольный вопрос «что именно предсказываем и в какой момент» имеет один ответ.
- **FILES EXPECTED TO CHANGE:** `docs/PRD.md` (создаётся), `README.md`.
- **RISKS:** Размывание цели до «предсказываем победу»; скрытое включение series win; отсутствие одобрения owner → блокировка всего MVP.
- **DEFINITION OF DONE (task-specific):** Документ существует, содержит явные разделы «Цель», «Определения», «Cutoff», «Гейты», «Non-goals»; все гейты имеют владельца-owner и метрику; owner явно подтвердил версию (дата/подпись в документе). Код не пишется.

#### PRD-002 — Спецификация цели предсказания и разметки
- **EPIC:** 00 — Product specification
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Proposed
- **GOAL:** Формально описать разметку целевой переменной и всех негативных исходов.
- **CONTEXT:** Нужны однозначные правила: conditional game played, forfeit, void, unknown, rematch, technical loss, отсутствие provider ID карты.
- **INPUT:** `PRD-001`; `SOURCES.md` §4 (Match/Series/Game, отсутствие upcoming ID).
- **OUTPUT:** Спека разметки: таблица «исход → метка», правила исключения серий, правило placeholder-ID до появления provider ID, правила для BO1/BO2/BO3.
- **DEPENDENCIES:** PRD-001
- **ACCEPTANCE CRITERIA:** (1) Для каждого возможного исхода есть решение: метка, exclusion, причина. (2) BO1/BO2/BO3 обработаны. (3) Описано, что происходит, если карта не сыграна. (4) Спека применима без интерпретаций при разметке.
- **TESTS:** Ревью owner; прогон спеки на 5–10 синтетических примерах исходов (как чек-лист, не как код).
- **FILES EXPECTED TO CHANGE:** `docs/PRD_LABELS.md`, `docs/PRD.md`.
- **RISKS:** Скрытая утечка через «known result»; разные стадии считают разметку по-разному.
- **DEFINITION OF DONE (task-specific):** Таблица «исход → метка/исключение» полная и непротиворечивая; содержит правило conditional game played и правило для forfeit/void/unknown; одобрена owner.

#### PRD-003 — Спецификация временной семантики и снимков
- **EPIC:** 00 — Product specification
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Proposed
- **GOAL:** Определить пять временных полей и правила снимков/immutability/маркировки ретроспективы.
- **CONTEXT:** Различать `event_time`, `source_published_at`, `observed_at`, `available_at`, `ingested_at`; историческая оценка обязана называться `retrospective_reconstructed`.
- **INPUT:** `PRD-001`; §1 (п.7–8).
- **OUTPUT:** Спека временной семантики: определения полей, правило cutoff, правила snapshot-immutability, словарь меток (`retrospective_reconstructed`, `prospective_archived`), правила train availability masks.
- **DEPENDENCIES:** PRD-001
- **ACCEPTANCE CRITERIA:** (1) Пять полей определены и не дублируют друг друга. (2) Явно: строгое `observed_at <= cutoff` достижимо только для проспективно архивированной истории. (3) Запрет финальных статистик и фактического целевого ростера до матча зафиксирован. (4) Метки не позволяют назвать ретроспективу «тогдашним прогнозом».
- **TESTS:** Ревью; проверка на примерах: (а) raw пришёл позже события, (б) опубликовано позже, чем стало доступно, (в) снапшот построен сегодня на матч прошлого года.
- **FILES EXPECTED TO CHANGE:** `docs/PRD_TEMPORAL.md`, `docs/PRD.md`.
- **RISKS:** Неверная трактовка `available_at` vs `ingested_at` → скрытая утечка в фичах.
- **DEFINITION OF DONE (task-specific):** Спека покрывает все пять полей, cutoff-правило, immutability снимков и словарь меток; приведены разобранные примеры; одобрена owner.

#### PRD-004 — Реестр scope/non-goals, гейтов и legal-регистр
- **EPIC:** 00 — Product specification
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Proposed
- **GOAL:** Свести в один реестр границы проекта, гейты с метриками/владельцами и юридические ограничения источников.
- **CONTEXT:** Гейты — это задачи с вердиктом owner, а не автоматические проверки. Legal-регистр фиксирует: CC-BY-SA 3.0 атрибуция Liquipedia, запрет HTML-доступа, non-betting условие PandaScore, неопределённый статус odds.
- **INPUT:** `PRD-001`, `PRD-002`, `PRD-003`; `SOURCES.md` §3, §7 (U8, U11, U15).
- **OUTPUT:** `docs/GATES_REGISTRY.md` (гейт → проектный порог → owner → решение), `docs/LEGAL_REGISTER.md` (источник → лицензия → ограничение → статус проверки) и `docs/adr/` (журнал ADR по предложенным контрактам §1).
- **DEPENDENCIES:** PRD-001, PRD-002, PRD-003
- **ACCEPTANCE CRITERIA:** (1) Все гейты из §2 перечислены с проектным порогом и владельцем. (2) Ни один гейт не помечен как «проходит автоматически». (3) Legal-регистр явно отделяет «проверено» / «заявлено» / «неизвестно». (4) PandaScore отмечен как исключённый до письменного разрешения. (5) Атрибуция Liquipedia обязательна и зафиксирована. (6) Пороги — проектные определения (coverage >= 90% на 30 fixtures, purity violations = 0, unmapped = 0, запрет significance-заявлений на 30), а не заявленные достижения. (7) ADR-журнал фиксирует, какие предложенные контракты §1 приняты/изменены/отклонены.
- **TESTS:** Ревью owner; кросс-проверка, что каждое ограничение из `SOURCES.md` §7 (U8/U11/U15) попало хотя бы в одну строку реестра.
- **FILES EXPECTED TO CHANGE:** `docs/GATES_REGISTRY.md`, `docs/LEGAL_REGISTER.md`.
- **RISKS:** Гейт без владельца; «неявное» разрешение спорного источника.
- **DEFINITION OF DONE (task-specific):** Оба реестра существуют и заполнены; каждый гейт имеет метрику и владельца; спорные источники помечены статусом; owner подтвердил.

---

### EPIC 01 — Repository and infrastructure

#### INF-001 — Локальный воспроизводимый скелет репозитория + smoke test
- **EPIC:** 01 — Repository and infrastructure
- **STAGE:** MVP-FIRST10
- **PRIORITY:** P0
- **STATUS:** Planned
- **GOAL:** Создать структуру репозитория и минимальный воспроизводимый smoke test. **В текущей сессии не выполняется** — только планирование и спецификация структуры.
- **CONTEXT:** Нужен предсказуемый каркас modular monolith под FastAPI/pandas/sklearn/Postgres JSONB/Docker local, без запрещённых компонентов.
- **INPUT:** `PRD-001`, `SRC-001`; §1.
- **OUTPUT:** Спека структуры каталогов, список зависимостей, определение smoke test (поднимается локально и делает один тривиальный проход), инструкция воспроизведения.
- **DEPENDENCIES:** PRD-001, SRC-001
- **ACCEPTANCE CRITERIA:** (1) Структура покрывает ingestion/storage/features/models/api/frontend/docs. (2) Smoke test описан так, что его результат однозначен (прошёл/не прошёл). (3) В зависимостях нет Redis/Celery/Kafka/K8s/feature store. (4) Указан способ воспроизведения на чистой машине.
- **TESTS:** План smoke test; чек-лист «нет запрещённых зависимостей».
- **FILES EXPECTED TO CHANGE:** `README.md`, `pyproject.toml`/`requirements`, `docs/REPO_LAYOUT.md`, `.gitignore`.
- **RISKS:** Разрастание скелета в преждевременный «фреймворк»; скрытые внешние зависимости.
- **DEFINITION OF DONE (task-specific):** Существует документ структуры и определённый smoke test; явный список зависимостей без запрещённых; инструкция воспроизведения проверена на бумаге (пошагово исполнима). Никакого запуска в этой сессии.

#### INF-002 — Пакетирование, пиннинг окружения, конфиг и секреты
- **EPIC:** 01 — Repository and infrastructure
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Зафиксировать окружение и правила работы с конфигом/секретами (ключи не выдумываются и не коммитятся).
- **CONTEXT:** Источники требуют токенов/ключей (STRATZ, Valve, Liquipedia UA). Секреты не должны попадать в репозиторий.
- **INPUT:** `INF-001`, `SRC-001`.
- **OUTPUT:** Пиннинг версий, схема конфиг-файла, правила для секретов (локальный env-файл вне git), список требуемых токенов с указанием источника.
- **DEPENDENCIES:** INF-001
- **ACCEPTANCE CRITERIA:** (1) Версии зафиксированы. (2) Схема конфига не содержит несуществующих ключей и помечает «ключ не предоставлен» как валидное состояние. (3) Секреты не в git. (4) Нет «выдуманных» credentials.
- **TESTS:** Проверка, что приложение описано как стартующее без секретов в деградированном режиме (в режиме спецификации).
- **FILES EXPECTED TO CHANGE:** `pyproject.toml`, `.env.example`, `docs/CONFIG.md`.
- **RISKS:** Случайный коммит секрета; несовместимые версии.
- **DEFINITION OF DONE (task-specific):** Окружение запинено, схема конфига описана, правила секретов зафиксированы, `.env.example` содержит только имена переменных без значений.

#### INF-003 — Structured logging, run manifest и реестр артефактов
- **EPIC:** 01 — Repository and infrastructure
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Обеспечить провенанс: каждый запуск пишет manifest, каждый артефакт (датасет/модель/снимок) регистрируется.
- **CONTEXT:** Без провенанса ретроспективные прогоны неотличимы от проспективных, а метрики невоспроизводимы.
- **INPUT:** `INF-001`, `PRD-003`.
- **OUTPUT:** Спека log-структуры, полей run manifest (входные данные, версии, cutoff, seed, код-версия) и реестра артефактов.
- **DEPENDENCIES:** INF-001
- **ACCEPTANCE CRITERIA:** (1) Manifest содержит cutoff и хэш/версию входных данных. (2) Артефакт без записи в реестре считается невалидным. (3) Логи структурированы и не содержат секретов. (4) Метка `retrospective_reconstructed` пишется автоматически по cutoff.
- **TESTS:** Чек-лист полей manifest; пример восстановления прогона по manifest (в описании).
- **FILES EXPECTED TO CHANGE:** `docs/RUN_MANIFEST.md`, `src/.../logging.py`, `src/.../artifacts.py`.
- **RISKS:** Manifest без cutoff → невозможность доказать отсутствие утечки.
- **DEFINITION OF DONE (task-specific):** Спека manifest/логов/реестра полная, поля cutoff и версии обязательны, зафиксирован запрет секретов в логах.

#### INF-004 — Docker local + локальные quality gates
- **EPIC:** 01 — Repository and infrastructure
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Локальный запуск через Docker (app + Postgres) и единые локальные проверки качества (lint/type/test).
- **CONTEXT:** Docker только локально; никакой оркестрации/K8s. CI-инфраструктура не создаётся, проверки запускаются локально.
- **INPUT:** `INF-001`, `INF-002`.
- **OUTPUT:** Описание compose-состава (app + db), команды единого quality gate, политика «зелёный локальный gate перед мержем».
- **DEPENDENCIES:** INF-001, INF-002
- **ACCEPTANCE CRITERIA:** (1) Compose содержит только app и db. (2) Quality gate одной командой запускает lint+type+test. (3) Нет зависимостей от внешней CI. (4) Запрещённые компоненты отсутствуют.
- **TESTS:** Чек-лист compose-состава; проверка, что gate определены детерминированно.
- **FILES EXPECTED TO CHANGE:** `docker-compose.yml`, `Makefile`/`scripts/`, `docs/DEV_WORKFLOW.md`.
- **RISKS:** Незаметное «протекание» прод-инфраструктуры в локальный стек.
- **DEFINITION OF DONE (task-specific):** Описан локальный стек app+db и единый quality gate; подтверждено отсутствие CI-зависимостей и запрещённых компонентов.

#### INF-005 — Backup/restore локальной БД и retention-политика
- **EPIC:** 01 — Repository and infrastructure
- **STAGE:** MVP2
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Описать резервное копирование/восстановление локальной БД и сроки хранения raw/снапшотов.
- **CONTEXT:** Raw-данные могут быть недоступны повторно (U6/U10); снапшоты immutable и должны храниться долго.
- **INPUT:** `INF-004`, `DB-001`.
- **OUTPUT:** Процедура backup/restore, политика retention по классам данных (raw / canonical / snapshots / модели), проверка восстановления.
- **DEPENDENCIES:** INF-004, DB-001
- **ACCEPTANCE CRITERIA:** (1) Процедура restore воспроизводима. (2) Immutable-снапшоты не удаляются политикой. (3) Политика явно различает классы данных. (4) Указано, что делается при недоступности источника.
- **TESTS:** Плановая проверка восстановления на копии (описание, не запуск).
- **FILES EXPECTED TO CHANGE:** `docs/BACKUP_RETENTION.md`, `scripts/backup_*`.
- **RISKS:** Потеря raw при перезаписи; удаление снапшотов, нужных для аудита.
- **DEFINITION OF DONE (task-specific):** Документ содержит процедуры backup и restore, политику retention по классам и явный запрет удаления immutable-снапшотов.

---

### EPIC 02 — Data ingestion

#### SRC-001 — Документированный bounded read-only audit: OpenDota history + Liquipedia legal/access/upcoming
- **EPIC:** 02 — Data ingestion
- **STAGE:** MVP-FIRST10
- **PRIORITY:** P0
- **STATUS:** Proposed
- **GOAL:** Провести ограниченный read-only аудит: глубина/полнота истории OpenDota, фактические квоты, и легальность/доступность/покрытие Liquipedia для upcoming.
- **CONTEXT:** Это гейт G-SRC. Без него нельзя обещать upstream/upcoming. Прямой HTTP из песочницы заблокирован — метод фиксируется как в `SOURCES.md`. Credentials не выдумываются.
- **INPUT:** `SOURCES.md` (§3.1, §3.4, §4, §7 U3/U4/U10/U13); `PRD-001`.
- **OUTPUT:** Отчёт аудита с bounded-пробами (несколько запросов в окне, без исчерпания квот), оценкой покрытия истории, условиями Liquipedia API (rate limit, User-Agent, `action=parse`), go/no-go вердикт-кандидат по G-SRC.
- **DEPENDENCIES:** PRD-001
- **ACCEPTANCE CRITERIA:** (1) Пробы bounded и quota-compliant, 429 не провоцируется. (2) Разделены «проверено/заявлено/неизвестно». (3) Вердикт по **истории** и по **upcoming** разделён: **история недоступна/непригодна → STOP до `INF-001`**; **upcoming недоступен при работающей истории → только ретроспективный прототип** (полноценный MVP не объявляется). (4) Никакие credentials не выдуманы и не запрашиваются обходными путями. (5) Есть вердикт-кандидат с проектной метрикой и владельцем.
- **TESTS:** Повторяемость отчёта по указанному методу; чек-лист «ни один запрос не исчерпывает квоту».
- **FILES EXPECTED TO CHANGE:** `docs/SRC_AUDIT.md`, `docs/GATES_REGISTRY.md` (обновление записи G-SRC).
- **RISKS:** Единственная выборка выдаётся за «полное покрытие»; ToS-нарушение при попытке доступа к HTML; бан IP.
- **DEFINITION OF DONE (task-specific):** Отчёт содержит разделы «метод», «bounded-пробы», «покрытие/глубина», «legal/access Liquipedia», «вердикт-кандидат G-SRC»; все утверждения помечены статусом; вердикт направлен owner на решение.

#### ING-001 — OpenDota клиент + raw capture (pagination, retry, quota, idempotence)
- **EPIC:** 02 — Data ingestion
- **STAGE:** MVP-FIRST10
- **PRIORITY:** P0
- **STATUS:** Planned
- **GOAL:** Минимальный клиент OpenDota, сохраняющий сырые ответы без потерь и дублей.
- **CONTEXT:** primary-источник истории. Нужны sync-once, пагинация, ограниченный retry, учёт квот, идемпотентность записи raw.
- **INPUT:** `SRC-001`, `DB-001`.
- **OUTPUT:** Клиент + raw-capture слой: пагинация, retry с backoff, счётчик квоты, ключ идемпотентности, запись raw как есть (JSONB) с метаданными (`ingested_at`, эндпоинт, параметры).
- **DEPENDENCIES:** SRC-001, DB-001
- **ACCEPTANCE CRITERIA:** (1) Повторный запуск на тех же параметрах не создаёт дублей. (2) Retry ограничен, при 429/5xx поведение определено. (3) Счётчик квоты не позволяет исчерпать суточный лимит. (4) Raw сохраняется без нормализации и без потерь. (5) Работа возможна без ключа; при наличии ключа — учитывается.
- **TESTS:** Повторный прогон → идентичный набор записей; тест на 429/5xx; тест пагинации на границах; тест квоты.
- **FILES EXPECTED TO CHANGE:** `src/ingestion/opendota_client.py`, `src/ingestion/raw_capture.py`, `tests/ingestion/...`.
- **RISKS:** Дубли raw → двойной учёт; исчерпание квоты; тихая потеря страниц.
- **DEFINITION OF DONE (task-specific):** Клиент воспроизводимо тянет ограниченную выборку, raw сохраняется один раз, есть счётчик квоты и определённое поведение при 429/5xx, тесты на идемпотентность и пагинацию проходят.

#### ING-002 — Backfill-оркестрация и discovery серий/лиг (bounded)
- **EPIC:** 02 — Data ingestion
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Оркестрация ограниченного backfill: выбор окна, обход лиг/серий, чекпойнты, докрутка после сбоя.
- **CONTEXT:** История тянется по частям; нужны чекпойнты и явное окно, иначе прогон невоспроизводим. Сам по себе backfill не закрывает требование полного MVP: гейт полного MVP требует **фактически работающего** автоматического обнаружения/ingestion в будущем локальном deployment (см. `ING-008`).
- **INPUT:** `ING-001`.
- **OUTPUT:** Планировщик backfill (окно по дате/лиге), чекпойнты, повторный запуск с продолжением, отчёт покрытия окна.
- **DEPENDENCIES:** ING-001
- **ACCEPTANCE CRITERIA:** (1) Окно задаётся явно и попадает в manifest. (2) Сбой не приводит к повторной загрузке уже загруженного. (3) Есть отчёт «загружено/пропущено/ошибок». (4) Объём ограничен квотой.
- **TESTS:** Прерывание на середине → продолжение без дублей; проверка отчёта покрытия.
- **FILES EXPECTED TO CHANGE:** `src/ingestion/backfill.py`, `tests/ingestion/test_backfill.py`.
- **RISKS:** Неограниченный backfill → исчерпание квоты; неверное окно → смещение выборки.
- **DEFINITION OF DONE (task-specific):** Backfill воспроизводим, возобновляем, ограничен квотой, с отчётом покрытия и записью окна в manifest.

#### ING-003 — Raw store writer: идемпотентный upsert и карантин
- **EPIC:** 02 — Data ingestion
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Единый слой записи raw в JSONB с версионированием, дедупликацией и карантином неоднозначных записей.
- **CONTEXT:** Некоторые записи неоднозначны (например, невозможно определить map1). Их нельзя молча нормализовать.
- **INPUT:** `ING-001`, `DB-001`.
- **OUTPUT:** Модуль записи raw: ключ идемпотентности, версии, карантин-таблица с причиной и ссылкой на raw.
- **DEPENDENCIES:** ING-001, DB-001
- **ACCEPTANCE CRITERIA:** (1) Upsert идемпотентен. (2) Неоднозначная запись попадает в карантин с причиной, а не в canonical. (3) Raw не перезаписывается при повторной загрузке. (4) Карантин имеет статус и владельца решения.
- **TESTS:** Тест дубля; тест карантина (неоднозначный map1); тест неизменности raw.
- **FILES EXPECTED TO CHANGE:** `src/ingestion/raw_store.py`, `tests/ingestion/test_raw_store.py`.
- **RISKS:** Молчаливая нормализация неоднозначных данных; потеря версии raw.
- **DEFINITION OF DONE (task-specific):** Запись идемпотентна, карантин работает и не течёт в canonical, raw неизменяем, тесты проходят.

#### ING-004 — Liquipedia MediaWiki adapter для upcoming (условный гейт G-UPCOMING)
- **EPIC:** 02 — Data ingestion
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Реализовать upcoming-адаптер через **MediaWiki API** (не HTML) только если gate `SRC-001` подтвердил легальность, доступ и покрытие.
- **CONTEXT:** Это обязательное условие полного MVP. HTML-scraping запрещён. Нужны кастомный User-Agent с контактом, gzip, reuse клиента, лимиты 1 req/2s и `action=parse` 1/30s.
- **INPUT:** `SRC-001`, `ING-003`; `SOURCES.md` §3.4/§4.
- **OUTPUT:** Адаптер расписаний (upcoming/ongoing): команды, время, формат Bo3/Bo5, лига, доля `TBD`; кэш и атрибуция Liquipedia; отчёт покрытия и лага.
- **DEPENDENCIES:** SRC-001, ING-003
- **ACCEPTANCE CRITERIA:** (1) Только API, без HTML. (2) Лимиты соблюдены. (3) Атрибуция CC-BY-SA 3.0 присутствует в артефактах. (4) Явно отражена доля `TBD` и нестабильность расписания. (5) Если gate не пройден — адаптер не реализуется, фиксируется STOP.
- **TESTS:** Проверка лимитера; тест атрибуции; тест поведения при `TBD`; bounded-проба покрытия.
- **FILES EXPECTED TO CHANGE:** `src/ingestion/liquipedia_client.py`, `src/ingestion/upcoming.py`, `tests/ingestion/test_liquipedia.py`.
- **RISKS:** ToS-нарушение через парсинг шаблонов «на грани»; блокировка IP; ложный вывод о покрытии.
- **DEFINITION OF DONE (task-specific):** Адаптер работает через API с соблюдением лимитов и атрибуции, есть отчёт покрытия/лага/TBD, gate G-UPCOMING оформлен как решение owner.

#### ING-005 — STRATZ adapter (опциональный токен, после spike)
- **EPIC:** 02 — Data ingestion
- **STAGE:** FUTURE
- **PRIORITY:** P2
- **STATUS:** Proposed
- **GOAL:** Описать и, при наличии токена и прошедшем spike, подключить STRATZ GraphQL как вторичный источник.
- **CONTEXT:** Токен обязателен; бакеты rate limit в документации рендерятся неоднозначно (U1), наличие upcoming/rosters не подтверждено (U2).
- **INPUT:** `SRC-001`, `ING-003`.
- **OUTPUT:** Отчёт spike (доступность полей, фактические бакеты, наличие upcoming/rosters) и, при успехе, адаптер с token-aware лимитером и обязательным `User-Agent: STRATZ_API`.
- **DEPENDENCIES:** SRC-001, ING-003
- **ACCEPTANCE CRITERIA:** (1) Spike bounded, без исчерпания квот. (2) Неоднозначность бакетов разрешена фактами, а не догадками. (3) Адаптер не является обязательным для MVP. (4) Зафиксировано, закрывает ли STRATZ upcoming/rosters.
- **TESTS:** Bounded-пробы по окнам сек/мин/час; проверка обязательных заголовков.
- **FILES EXPECTED TO CHANGE:** `docs/STRATZ_SPIKE.md`, `src/ingestion/stratz_client.py`.
- **RISKS:** Блокировка/деактивация токена; ложная зависимость от непроверенной схемы.
- **DEFINITION OF DONE (task-specific):** Отчёт spike содержит разделённые «проверено/заявлено/неизвестно» и явный вердикт о пригодности; адаптер либо реализован, либо обоснованно отложен.

#### ING-006 — Rate-limit/quota accounting и деградация/fallback
- **EPIC:** 02 — Data ingestion
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Единый учёт квот по источникам и предсказуемое поведение при деградации (пустые ответы, 429, 5xx).
- **CONTEXT:** SLA нет ни у одного бесплатного источника (U10); известна проблема «empty response».
- **INPUT:** `ING-001`.
- **OUTPUT:** Лимитеры по источникам, учёт расходования, стратегия повторной попытки/отложенной догрузки, фиксация деградации в метриках.
- **DEPENDENCIES:** ING-001
- **ACCEPTANCE CRITERIA:** (1) У каждого источника свой лимитер. (2) Пустой ответ не трактуется как «данных нет» без повторной проверки. (3) 429/5xx обрабатываются без потери чекпойнта. (4) Расход квоты виден в отчёте.
- **TESTS:** Тест на пустой ответ; тест на 429; тест сохранения чекпойнта при сбое.
- **FILES EXPECTED TO CHANGE:** `src/ingestion/limits.py`, `tests/ingestion/test_limits.py`.
- **RISKS:** Тихая деградация → ложный «полный» датасет.
- **DEFINITION OF DONE (task-specific):** Лимитеры и учёт работают по источникам, деградация фиксируется и не маскируется под отсутствие данных, тесты проходят.

#### ING-007 — Spike доступности реплеев (окно жизни ссылок)
- **EPIC:** 02 — Data ingestion
- **STAGE:** FUTURE
- **PRIORITY:** P2
- **STATUS:** Proposed
- **GOAL:** Оценить, доступны ли реплеи бесплатно и как долго живут ссылки (`replay_url`/`replay_salt`, CDN Valve).
- **CONTEXT:** От этого зависит, возможен ли собственный парсинг для in-game слоя без платных провайдеров (U6).
- **INPUT:** `ING-001`.
- **OUTPUT:** Отчёт: доступность реплеев, окно жизни ссылок (проверки на 0/3/7/14 день), легальность, вердикт о собственном парсинге.
- **DEPENDENCIES:** ING-001
- **ACCEPTANCE CRITERIA:** (1) Проверки на нескольких возрастных точках. (2) Разделены «проверено/неизвестно». (3) Указано, нужен ли OSS-парсер и совместимость лицензий. (4) Сформулирован вердикт-кандидат.
- **TESTS:** Повторяемость проверок по датам.
- **FILES EXPECTED TO CHANGE:** `docs/REPLAY_SPIKE.md`.
- **RISKS:** Единственная удачная проверка выдана за гарантию; игнорирование лицензий OSS-парсеров.
- **DEFINITION OF DONE (task-specific):** Отчёт содержит возрастные точки проверки, лицензионные выводы и вердикт о возможности собственного парсинга.

#### ING-008 — Контракт идемпотентности/восстановления worker + e2e-критерии автопоиска
- **EPIC:** 02 — Data ingestion
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Зафиксировать контракт идемпотентности/восстановления будущего локального worker и e2e-приёмочные критерии автоматического обнаружения матчей/расписания.
- **CONTEXT:** **Дизайн в чате не означает, что реализация локального MVP не нужна.** Полноценный MVP-гейт (`G-OPS`) требует, чтобы автопоиск/ingestion **фактически работали** в будущем локальном deployment. Здесь ничего не запускается и не конфигурируется; cron/recurring-задачи не создаются и не инструктируются.
- **INPUT:** `ING-002`, `ING-003`, `ING-006`.
- **OUTPUT:** Контракт (ключи идемпотентности, чекпойнты, правила восстановления после сбоя, поведение при повторном запуске, порядок обработки пропусков) + e2e-приёмочные критерии автопоиска (что именно считается «работает») + требования к наблюдаемости.
- **DEPENDENCIES:** ING-002, ING-003, ING-006
- **ACCEPTANCE CRITERIA:** (1) Контракт полный и проверяемый. (2) E2e-критерии дают бинарный вердикт. (3) Явно зафиксировано, что работоспособность подтверждается **в будущем локальном deployment**, а не в текущем чате. (4) Никаких инструкций по запуску cron/recurring и никаких внешних отправок. (5) Проектный порог: purity violations = 0 (нет дублей/потерь при повторном запуске).
- **TESTS:** План e2e-проверки (описание); чек-лист «нет инструкций по запуску»; сценарии сбоя/повтора.
- **FILES EXPECTED TO CHANGE:** `docs/WORKER_CONTRACT.md`, `docs/OPS_GATES.md`.
- **RISKS:** Дизайн принят за реализацию; необнаруженные сбои повторного запуска; скрытое создание автоматизации.
- **DEFINITION OF DONE (task-specific):** Контракт и e2e-критерии зафиксированы; вердикт по работоспособности возможен только после фактической работы в будущем локальном deployment; никаких задач/запусков здесь не создано.

---

### EPIC 03 — Database

#### DB-001 — Минимальная ядровая temporal-схема + snapshots/migrations/constraints
- **EPIC:** 03 — Database
- **STAGE:** MVP-FIRST10
- **PRIORITY:** P0
- **STATUS:** Planned
- **GOAL:** Создать минимальную схему с temporal-полями, таблицами снимков и обязательными constraint'ами; **canonical — типизированные реляционные таблицы**, JSONB — только для raw/snapshot/variable payload.
- **CONTEXT:** Схема сразу должна поддерживать `raw`, `canonical`, `snapshot` и пять временных полей; миграции — с первого дня. JSONB на canonical-слое **не** используется для основных полей.
- **INPUT:** `INF-001`, `PRD-003`.
- **OUTPUT:** Миграции: raw-таблица (JSONB), canonical — **типизированные таблицы с PK/FK/индексами** (без JSONB на ключевых полях), snapshot-таблицы (JSONB payload), `Prediction`, `PredictionSnapshot`, `FeatureSnapshot`, `ModelVersion`; constraints на временной порядок и уникальность.
- **DEPENDENCIES:** INF-001
- **ACCEPTANCE CRITERIA:** (1) Все пять временных полей присутствуют. (2) Снимки имеют запрет на update/delete. (3) Миграции обратимо/воспроизводимо применяются локально. (4) Нет запрещённых компонентов (например, внешнего feature store). (5) Есть constraint, запрещающий противоречивый порядок временных полей. (6) Canonical-поля типизированы и покрыты FK/индексами; JSONB встречается только в raw/snapshot/variable payload.
- **TESTS:** Тест применения миграций с нуля; тест нарушения constraint'а; тест попытки изменения снимка.
- **FILES EXPECTED TO CHANGE:** `migrations/0001_*.sql`, `docs/SCHEMA.md`.
- **RISKS:** Схема без temporal-ограничений → скрытая утечка; ранняя иммyтабельность вредит отладке, если нет отмены миграции.
- **DEFINITION OF DONE (task-specific):** Миграции применяются на пустой БД, constraints на временной порядок и неизменность снимков работают, схема задокументирована.

#### DATA-001 — Нормализация исторического ядра + карантин неоднозначного map1
- **EPIC:** 03 — Database
- **STAGE:** MVP-FIRST10
- **PRIORITY:** P0
- **STATUS:** Planned
- **GOAL:** Нормализовать исторические игры/команды/игроков/серии, построить map index и participant stats, с карантином неоднозначного map1.
- **CONTEXT:** Нужен стабильный map index и разделение серий/карт; всё с провенансом на raw и сохранением свидетельств ростера.
- **INPUT:** `ING-001`.
- **OUTPUT:** Нормализованные `Team`, `Player`, `GameParticipant`, `PlayerPerformance`, минимальные `Tournament`/`Stage`, `Patch`, evidence-based `RosterMembership`, `EntityMapping` — **типизированные реляционные таблицы с PK/FK/индексами** (JSONB только для variable payload); отдельная очередь карантина для map1-неоднозначных записей.
- **DEPENDENCIES:** ING-001
- **ACCEPTANCE CRITERIA:** (1) Каждая canonical-запись связана с raw. (2) Ростер хранится как свидетельство с датами, не как «текущий состав». (3) Неоднозначный map1 идёт в карантин, а не в датасет. (4) Повторная нормализация идемпотентна. (5) Финальные статистики помечены отдельно от pre-match данных. (6) Canonical-поля типизированы, а не свалены в один JSONB-документ.
- **TESTS:** Тест идемпотентной нормализации; тест карантина map1; тест связности raw↔canonical; тест «нет перезаписи ростеров».
- **FILES EXPECTED TO CHANGE:** `src/normalize/*.py`, `migrations/0002_*.sql`, `tests/normalize/*`.
- **RISKS:** Смешение игр разных форматов в один «map1»; перезапись ростеров текущим состоянием; потеря связи с raw.
- **DEFINITION OF DONE (task-specific):** Историческое ядро нормализовано на реальном срезе, у каждой записи есть raw-источник, ростеры evidence-based, неоднозначный map1 в карантине, тесты проходят.

#### DB-002 — Каноническая модель сущностей: EntityMapping и ambiguity quarantine
- **EPIC:** 03 — Database
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Достроить канонические сущности и межисточниковый маппинг с карантином неоднозначностей.
- **CONTEXT:** Команды/игроки приходят из разных источников с разными ID; без канонического ID нельзя связать upstream с историей.
- **INPUT:** `DB-001`, `DATA-001`.
- **OUTPUT:** `EntityMapping` (provider → canonical), правила разрешения конфликтов, карантин при неоднозначном матчинге.
- **DEPENDENCIES:** DB-001, DATA-001
- **ACCEPTANCE CRITERIA:** (1) У каждой сущности есть стабильный канонический ID. (2) Неоднозначный матчинг не разрешается автоматически. (3) Маппинг версионируем. (4) Team A определяется по каноническому ID, а не по имени.
- **TESTS:** Тест неоднозначного матчинга → карантин; тест стабильности канонического ID при повторной загрузке.
- **FILES EXPECTED TO CHANGE:** `src/normalize/entity_mapping.py`, `migrations/0003_*.sql`.
- **RISKS:** «Схлопывание» разных команд в одну; дрейф канонического ID между прогонами.
- **DEFINITION OF DONE (task-specific):** Каноническая модель и маппинг работают, неоднозначности уходят в карантин, канонический ID стабилен и версионируется.

#### DB-003 — Integrity/constraint тест-сьют и проверки отсутствия досрочных полей
- **EPIC:** 03 — Database
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Автоматически проверять целостность данных и отсутствие «будущих» полей в pre-match слое.
- **CONTEXT:** Основной риск — утечка финальной статистики/фактического ростера до матча.
- **INPUT:** `DB-002`, `DATA-001`.
- **OUTPUT:** Сьют проверок: FK/уникальность, временной порядок, отсутствие финальных статистик в pre-match представлении, отсутствие фактического целевого ростера, согласованность снимков.
- **DEPENDENCIES:** DB-002, DATA-001
- **ACCEPTANCE CRITERIA:** (1) Проверки ловят намеренно внедрённую утечку. (2) Проверки воспроизводимы на реальном датасете. (3) Есть отчёт «пройдено/провалено» по каждой проверке. (4) Проверки не зависят от внешней инфраструктуры. (5) **Проектный порог:** critical temporal/purity violations = **0**; (6) **unmapped evaluation records = 0** в eval-когорте. Оба порога — определения (не достигнутые значения).
- **TESTS:** Позитивные (данные корректны) и негативные (искусственная утечка) сценарии.
- **FILES EXPECTED TO CHANGE:** `tests/integrity/*`, `docs/DATA_INTEGRITY.md`.
- **RISKS:** Проверки, которые «всегда зелёные»; пропуск утечки через агрегаты.
- **DEFINITION OF DONE (task-specific):** Сьют ловит искусственную утечку и проходит на валидных данных, отчёт по проверкам формируется.

#### DB-004 — Индексы, партиционирование и query playbook
- **EPIC:** 03 — Database
- **STAGE:** MVP2
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Обеспечить приемлемую производительность при росте истории без введения запрещённых компонентов.
- **CONTEXT:** История может расти до больших объёмов; нужны индексы/партиционирование по времени и лигам, а также типовые запросы.
- **INPUT:** `DB-003`.
- **OUTPUT:** Индексы, стратегия партиционирования, playbook типовых запросов (по серии, по команде, по окну времени, по cutoff).
- **DEPENDENCIES:** DB-003
- **ACCEPTANCE CRITERIA:** (1) Типовые запросы укладываются в заранее заданный локальный бюджет времени. (2) Партиционирование не ломает immutability снимков. (3) Playbook воспроизводим. (4) Замеры приложены.
- **TESTS:** Прогон типовых запросов на росте данных; проверка планов выполнения.
- **FILES EXPECTED TO CHANGE:** `migrations/0004_*.sql`, `docs/QUERY_PLAYBOOK.md`.
- **RISKS:** Преждевременная оптимизация; партиционирование, усложняющее миграции.
- **DEFINITION OF DONE (task-specific):** Индексы/партиционирование задокументированы с замерами, типовые запросы укладываются в бюджет, immutability не нарушена.

#### DB-005 — Append-only enforcement иммутабельности снимков
- **EPIC:** 03 — Database
- **STAGE:** MVP2
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Технически гарантировать, что `PredictionSnapshot`, `FeatureSnapshot`, `ModelVersion` неизменяемы.
- **CONTEXT:** Без этого нельзя доказывать, что ретроспективный снапшот не подправлен задним числом.
- **INPUT:** `DB-001`, `DB-003`.
- **OUTPUT:** Механизм append-only, тесты на запрет update/delete, процедура «исправление = новый снапшот».
- **DEPENDENCIES:** DB-001, DB-003
- **ACCEPTANCE CRITERIA:** (1) Изменение существующего снапшота невозможно. (2) Исправление возможно только новым снапшотом со ссылкой на предыдущий. (3) Связь «снапшот → модель/фичи/данные» сохраняется. (4) Есть отчёт об инцидентах нарушения.
- **TESTS:** Негативный тест update/delete; тест создания корректирующего снапшота.
- **FILES EXPECTED TO CHANGE:** `migrations/0005_*.sql`, `tests/db/test_immutability.py`.
- **RISKS:** Обход иммутабельности через прямой SQL; потеря цепочки версий.
- **DEFINITION OF DONE (task-specific):** Изменение/удаление снапшота технически невозможно, корректировка выполняется новым снапшотом, негативные тесты проходят.

---

### EPIC 04 — Tournament intelligence

#### TOUR-001 — Обогащение модели турниров/стадий и tier-классификация
- **EPIC:** 04 — Tournament intelligence
- **STAGE:** MVP2
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Дополнить сущности турниров/стадий и ввести tier-классификацию лиг.
- **CONTEXT:** Важность стадии и уровень лиги влияют на предсказание; нужен явный tier, а не неявный фильтр.
- **INPUT:** `DB-002`, `DATA-001`.
- **OUTPUT:** Обогащённые `Tournament`/`Stage` (формат, регион, tier) и правила назначения tier с указанием источника сигнала.
- **DEPENDENCIES:** DB-002, DATA-001
- **ACCEPTANCE CRITERIA:** (1) Tier назначается по явному правилу, воспроизводимо. (2) Стадии различают групповую/плейофф. (3) Нет неявного смешивания уровней лиг. (4) Пропуски помечены как unknown.
- **TESTS:** Тест воспроизводимости tier; тест обработки неизвестной лиги.
- **FILES EXPECTED TO CHANGE:** `src/normalize/tournaments.py`, `migrations/0006_*.sql`, `docs/TOURNAMENTS.md`.
- **RISKS:** Tier-ошибки → смещение оценки силы команд.
- **DEFINITION OF DONE (task-specific):** Турниры/стадии обогащены, tier назначается воспроизводимо с трактовкой unknown, документация обновлена.

#### TOUR-002 — Tournament-context признаки as-of (важность стадии, формат, регион)
- **EPIC:** 04 — Tournament intelligence
- **STAGE:** MVP2
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Построить tournament-context признаки строго as-of.
- **CONTEXT:** Контекст турнира доступен заранее, но только в той части, что опубликована до cutoff.
- **INPUT:** `TOUR-001`, `FEAT-001`.
- **OUTPUT:** Признаки: важность стадии, формат (BO), регион, длительность серии, «свежий приезд/переезд» при наличии; с масками доступности.
- **DEPENDENCIES:** TOUR-001, FEAT-001
- **ACCEPTANCE CRITERIA:** (1) Все признаки имеют `available_at <= cutoff`. (2) Формат (BO) фиксируется до матча. (3) Неизвестные значения дают маску, а не выдуманное число. (4) Признаки воспроизводимы по серии.
- **TESTS:** Тест cutoff на границе; тест масок; тест воспроизводимости.
- **FILES EXPECTED TO CHANGE:** `src/features/tournament_context.py`, `tests/features/test_tournament_context.py`.
- **RISKS:** Использование пост-факт информации о стадии (например, итогового состава плейофф).
- **DEFINITION OF DONE (task-specific):** Признаки строятся as-of, маски покрывают неизвестные значения, тесты cutoff/маски/воспроизводимости проходят.

#### TOUR-003 — Форма команды внутри турнира (as-of)
- **EPIC:** 04 — Tournament intelligence
- **STAGE:** MVP2
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Вычислить форму команды внутри конкретного турнира до матча.
- **CONTEXT:** Это потенциально сильный контекст, но обязательно leak-free: учитываются только сыгранные до cutoff матчи того же турнира.
- **INPUT:** `TOUR-002`, `FEAT-001`.
- **OUTPUT:** Признаки формы внутри турнира (сыгранные матчи, результат, карта, счёт) с окнами и масками малых выборок.
- **DEPENDENCIES:** TOUR-002, FEAT-001
- **ACCEPTANCE CRITERIA:** (1) Используются только матчи с `event_time < cutoff`. (2) Малые выборки маскируются. (3) Граница турнира определяется по каноническому ID. (4) Есть отчёт о покрытии (доля матчей без истории в турнире).
- **TESTS:** Тест на невозможность использования матчей после cutoff; тест малых выборок.
- **FILES EXPECTED TO CHANGE:** `src/features/in_tournament_form.py`, `tests/features/test_in_tournament_form.py`.
- **RISKS:** Утечка из будущих матчей того же турнира; путаница турниров.
- **DEFINITION OF DONE (task-specific):** Форма внутри турнира строится только из матчей до cutoff, малые выборки маскируются, есть отчёт покрытия.

---

### EPIC 05 — Team intelligence

#### FEAT-001 — Минимальный prior-form датасет as-of для map1
- **EPIC:** 05 — Team intelligence
- **STAGE:** MVP-FIRST10
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Собрать минимальный датасет признаков «форма/приоры» на момент до матча для первой карты — **включая минимальные Team- и Player-prior-form**, необходимые для baseline прототипа.
- **CONTEXT:** Нужны coverage masks и различение режимов event vs observed (что было известно до cutoff против того, что наблюдалось позже). **В first10 минимальный player prior-form входит сюда**; расширенные player-агрегаты (EPIC 06) — уже MVP2-надстройка, а не предусловие первого прототипа.
- **INPUT:** `DATA-001`.
- **OUTPUT:** Таблица примеров (серия/карта) с признаками prior-form, масками доступности, режимом (`event_asof` / `observed_mode_only_study`) и target-меткой map1.
- **DEPENDENCIES:** DATA-001
- **ACCEPTANCE CRITERIA:** (1) Каждый признак имеет cutoff. (2) Маски доступности явные. (3) `observed_mode_only_study` не попадает в обучение/оценку MVP. (4) Целевая метка — map1, не series. (5) Только train-fitted трансформации (никакого фита на всём датасете).
- **TESTS:** Тест на отсутствие данных после cutoff; тест масок; тест единственности примера на серию.
- **FILES EXPECTED TO CHANGE:** `src/features/prior_form.py`, `docs/FEATURE_DATASET.md`, `tests/features/test_prior_form.py`.
- **RISKS:** Утечка через агрегаты, посчитанные на всём датасете; смешение режимов; несколько примеров на серию.
- **DEFINITION OF DONE (task-specific):** Датасет строится as-of на реальных данных, маски и режимы явные, все трансформации fit только на train, один пример на серию, тесты проходят.

#### TEAM-001 — Team strength/rating (Elo-like) as-of, fit train-only
- **EPIC:** 05 — Team intelligence
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Построить рейтинг силы команд, доступный на cutoff и не «подглядывающий» в будущее.
- **CONTEXT:** Рейтинг должен обновляться строго по сыгранным матчам; параметры фитятся только на train.
- **INPUT:** `FEAT-001`.
- **OUTPUT:** Рейтинг-модуль с версионированием, значения рейтинга на cutoff для каждой серии, описание инициализации/обновления/HFA.
- **DEPENDENCIES:** FEAT-001
- **ACCEPTANCE CRITERIA:** (1) Рейтинг на cutoff не зависит от будущих матчей. (2) Параметры fit только на train. (3) Версия рейтинга попадает в `ModelVersion`/manifest. (4) Есть отчёт о покрытии команд.
- **TESTS:** Тест «пересчёт на усечённой истории даёт то же значение»; тест покрытия.
- **FILES EXPECTED TO CHANGE:** `src/features/team_rating.py`, `tests/features/test_team_rating.py`.
- **RISKS:** Скрытая утечка через инициализацию на всей истории; дрейф версии рейтинга.
- **DEFINITION OF DONE (task-specific):** Рейтинг воспроизводим, ограничен прошлым, версия учитывается в артефактах, покрытие отчитано, тест на усечённой истории проходит.

#### TEAM-002 — Свежесть/качество ростера и признаки неопределённости/стендинов (prior known roster)
- **EPIC:** 05 — Team intelligence
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Построить признаки на основе **prior known roster** с явной неопределённостью и fallback; оценить качество/свежесть.
- **CONTEXT:** Фактический состав на матч на бесплатных источниках не гарантируется (тип B). Нельзя использовать наблюдаемый целевой ростер. Гейт G-ROSTER.
- **INPUT:** `FEAT-001`, `DB-002`.
- **OUTPUT:** Признаки: давность последнего свидетельства о ростере, число изменений за окно, вероятность стендина (эвристика), fallback при отсутствии данных; отчёт качества (покрытие/свежесть).
- **DEPENDENCIES:** FEAT-001, DB-002
- **ACCEPTANCE CRITERIA:** (1) Используется только prior known roster. (2) Есть fallback и явная метка uncertain. (3) Свежесть/покрытие отчитаны. (4) G-ROSTER оформлен как решение owner. (5) Нет чтения фактического состава матча-цели.
- **TESTS:** Тест отсутствия данных → fallback; тест «целевой ростер не читается»; отчёт покрытия.
- **FILES EXPECTED TO CHANGE:** `src/features/roster.py`, `docs/ROSTER_QUALITY.md`, `tests/features/test_roster.py`.
- **RISKS:** Ложная уверенность в составе; скрытая утечка через post-match состав; эвристика стендина без валидации.
- **DEFINITION OF DONE (task-specific):** Признаки строятся только на prior known roster, есть fallback и uncertain-метки, отчёт свежести/качества приложен, gate G-ROSTER оформлен.

#### TEAM-003 — Team pace/economy/objective агрегаты as-of
- **EPIC:** 05 — Team intelligence
- **STAGE:** MVP2
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Добавить командные агрегаты темпа/экономики/объективов, доступные до матча.
- **CONTEXT:** Агрегаты считаются по историческим картам с cut-off и учитывают патч-контекст.
- **INPUT:** `FEAT-001`.
- **OUTPUT:** Признаки: длительность, темп, gold/xp advantage-паттерны, объективы; с масками и окнами.
- **DEPENDENCIES:** FEAT-001
- **ACCEPTANCE CRITERIA:** (1) Все значения as-of. (2) Малые выборки маскируются. (3) Есть версия агрегата в manifest. (4) Нет двойного счёта одного матча в нескольких окнах.
- **TESTS:** Тест cutoff; тест малых выборок; тест дедупликации вклада матча.
- **FILES EXPECTED TO CHANGE:** `src/features/team_aggregates.py`, `tests/features/test_team_aggregates.py`.
- **RISKS:** Двойной учёт матчей; утечка через агрегаты, посчитанные на полном датасете.
- **DEFINITION OF DONE (task-specific):** Агрегаты as-of, маски и версия учтены, дубли исключены, тесты проходят.

---

### EPIC 06 — Player intelligence

#### PLAY-001 — Player performance агрегаты as-of (masked)
- **EPIC:** 06 — Player intelligence
- **STAGE:** MVP2
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Построить **расширенные (MVP2-надстройка)** агрегаты индивидуальной производительности игроков as-of. Минимальный player prior-form уже покрыт `FEAT-001` в first10 и здесь не дублируется.
- **CONTEXT:** Индивидуальные метрики считаются по историческим картам, строго до cutoff, с масок малых выборок. Это **расширение** поверх минимума из `FEAT-001`, а не его замена.
- **INPUT:** `DATA-001`, `DB-002`.
- **OUTPUT:** Агрегаты по игроку (роль, участие, KDA/экономика/объективы) с окнами, масками и версией.
- **DEPENDENCIES:** DATA-001, DB-002
- **ACCEPTANCE CRITERIA:** (1) Только данные до cutoff. (2) Роль различается или помечается unknown. (3) Малые выборки маскируются. (4) Агрегаты воспроизводимы по игроку/окну.
- **TESTS:** Тест cutoff; тест роли unknown; тест малых выборок.
- **FILES EXPECTED TO CHANGE:** `src/features/player_aggregates.py`, `tests/features/test_player_aggregates.py`.
- **RISKS:** Смешение ролей; утечка через агрегаты на полном датасете.
- **DEFINITION OF DONE (task-specific):** Агрегаты строятся as-of, роли и малые выборки обрабатываются явно, тесты проходят.

#### PLAY-002 — Player-hero performance as-of (ограничения пула)
- **EPIC:** 06 — Player intelligence
- **STAGE:** MVP2
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Построить player-hero статистику с учётом ограничений пула и неопределённости.
- **CONTEXT:** Пул героев конкретного игрока может быть неизвестен до драфта; факты берутся из исторических карт, а не из целевого драфта.
- **INPUT:** `PLAY-001`.
- **OUTPUT:** Таблица player-hero с окнами/масками, признак «уверенности пула», правило fallback при неизвестном пуле.
- **DEPENDENCIES:** PLAY-001
- **ACCEPTANCE CRITERIA:** (1) Никакие герои из целевого драфта не используются как вход. (2) Пул-признаки имеют маску уверенности. (3) Учитывается патч-контекст (в связке с PATCH). (4) Воспроизводимо по игроку/герою.
- **TESTS:** Тест «целевой драфт не читается»; тест маски уверенности.
- **FILES EXPECTED TO CHANGE:** `src/features/player_hero.py`, `tests/features/test_player_hero.py`.
- **RISKS:** Скрытая утечка через целевой драфт; разреженность данных → ложная уверенность.
- **DEFINITION OF DONE (task-specific):** Player-hero признаки строятся из истории, целевой драфт не читается, маска уверенности присутствует, тесты проходят.

---

### EPIC 07 — Player synergy

#### SYN-001 — Co-play synergy матрица as-of
- **EPIC:** 07 — Player synergy
- **STAGE:** MVP2
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Измерить «сыгранность» составов на основе совместного участия в матчах до cutoff.
- **CONTEXT:** Сыгранность вычисляется по prior known roster; целевой фактический состав недоступен.
- **INPUT:** `PLAY-001`, `DB-002`.
- **OUTPUT:** Матрица совместного участия/результата для пар/пятёрок с окнами и масками.
- **DEPENDENCIES:** PLAY-001, DB-002
- **ACCEPTANCE CRITERIA:** (1) Учитываются только матчи до cutoff. (2) Малые выборки маскируются. (3) Стендины помечаются uncertain и не «затирают» историю пятёрки. (4) Воспроизводимо по составу.
- **TESTS:** Тест cutoff; тест малых выборок; тест обработки стендина.
- **FILES EXPECTED TO CHANGE:** `src/features/synergy.py`, `tests/features/test_synergy.py`.
- **RISKS:** Ложная сыгранность из смешанных периодов; утечка из будущих матчей.
- **DEFINITION OF DONE (task-specific):** Матрица сыгранности строится as-of, малые выборки и стендины обрабатываются явно, тесты проходят.

#### SYN-002 — Признаки комбинаций составов + availability masks
- **EPIC:** 07 — Player synergy
- **STAGE:** MVP2
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Превратить матрицы сыгранности в признаки модели с масками доступности.
- **CONTEXT:** Признаки должны вести себя одинаково в train и inference (маски имитируют условия инференса).
- **INPUT:** `SYN-001`, `TEAM-002`.
- **OUTPUT:** Набор признаков комбинаций (минимальная/средняя сыгранность, стабильность пятёрки) + маски.
- **DEPENDENCIES:** SYN-001, TEAM-002
- **ACCEPTANCE CRITERIA:** (1) Признаки определены при неизвестном составе (через fallback). (2) Маски совпадают по смыслу в train и inference. (3) Нет признаков, требующих фактического состава матча-цели. (4) Версия признаков попадает в manifest.
- **TESTS:** Тест идентичности масок train/inference; тест fallback при неизвестном составе.
- **FILES EXPECTED TO CHANGE:** `src/features/synergy_features.py`, `tests/features/test_synergy_features.py`.
- **RISKS:** Train/serve skew; скрытое требование недоступного состава.
- **DEFINITION OF DONE (task-specific):** Признаки строятся при неизвестном составе с fallback, маски совпадают между train и inference, тесты проходят.

#### SYN-003 — Harness для ablation synergy-признаков
- **EPIC:** 07 — Player synergy
- **STAGE:** MVP2
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Измерить вклад synergy-признаков через ablation на неизменном протоколе оценки.
- **CONTEXT:** Признак без ablation не признаётся; сравнение должно быть на одинаковых сплитах/метриках.
- **INPUT:** `SYN-002`, `ML-001`.
- **OUTPUT:** Ablation-прогоны (с synergy / без synergy), отчёт по метрикам и доверительным интервалам, решение о включении.
- **DEPENDENCIES:** SYN-002, ML-001
- **ACCEPTANCE CRITERIA:** (1) Единый протокол и сплиты для обоих вариантов. (2) Отчёт содержит метрики и неопределённость. (3) Нет заявлений о значимости без статистики. (4) Решение о включении фиксируется явно.
- **TESTS:** Тест воспроизводимости ablation; тест одинаковости сплитов.
- **FILES EXPECTED TO CHANGE:** `src/eval/ablation.py`, `docs/ABLATION_SYNERGY.md`.
- **RISKS:** Сравнение на разных сплитах → ложный вывод; переоценка малых эффектов.
- **DEFINITION OF DONE (task-specific):** Ablation выполнен на едином протоколе, метрики и неопределённость отчитаны, решение о включении зафиксировано.

#### SYN-004 — Спекулятивное исследование: graph/representation learning для связности составов
- **EPIC:** 07 — Player synergy
- **STAGE:** FUTURE
- **PRIORITY:** P3
- **STATUS:** Proposed
- **GOAL:** Исследовать (без обязательства внедрения) графовые/representation-learning подходы к связности игроков как **спекулятивное** направление.
- **CONTEXT:** `P3` — только спекулятивные направления. Эта задача не требуется для MVP/MVP2/MVP3 и не должна блокировать или подменять `SYN-002`/`SYN-003`.
- **INPUT:** `SYN-002`, `ML-002`.
- **OUTPUT:** Исследовательская записка + минимальный экспериментальный протокол (сравнение с уже принятым synergy-подходом на том же протоколе), при отрицательном результате — явный отказ.
- **DEPENDENCIES:** SYN-002, ML-002
- **ACCEPTANCE CRITERIA:** (1) Сравнение на том же протоколе/сплитах. (2) Неопределённость отчитана. (3) Отсутствуют заявления о превосходстве без статистики. (4) Явно указано, что направление не требуется для текущих стадий. (5) Никакого влияния на прод-модель без отдельного решения owner.
- **TESTS:** Тест воспроизводимости протокола; чек-лист «нет влияния на прод».
- **FILES EXPECTED TO CHANGE:** `docs/RESEARCH_GRAPH_SYNERGY.md`, `research/` (планируемые пути).
- **RISKS:** Спекулятивное направление «просачивается» в прод-путь; переоценка на малой выборке.
- **DEFINITION OF DONE (task-specific):** Записка и протокол существуют, сравнение оформлено на едином протоколе, при отсутствии эффекта зафиксирован отказ; влияния на прод-модель нет.

---

### EPIC 08 — Patch intelligence

#### PATCH-001 — Patch timeline и маппинг patch→дата
- **EPIC:** 08 — Patch intelligence
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Построить таймлайн патчей и корректно отнести каждый матч к патчу.
- **CONTEXT:** Базовый patch timeline необходим уже для patch weighting полного MVP; более глубокий анализ hero balance остаётся в MVP2.
- **INPUT:** `DB-002`, `DATA-001`.
- **OUTPUT:** Таблица патчей с датами и связь матч→патч, включая неоднозначные случаи (стык патчей).
- **DEPENDENCIES:** DB-002, DATA-001
- **ACCEPTANCE CRITERIA:** (1) Каждый матч имеет патч или явную метку unknown. (2) Стыки патчей обрабатываются консервативно. (3) Маппинг воспроизводим. (4) Неизвестные патчи не додумываются.
- **TESTS:** Тест на матч на стыке патчей; тест unknown.
- **FILES EXPECTED TO CHANGE:** `src/normalize/patch.py`, `migrations/0007_*.sql`, `docs/PATCH.md`.
- **RISKS:** Неверный патч → смещение меты; додумывание даты патча.
- **DEFINITION OF DONE (task-specific):** Таймлайн патчей и маппинг матч→патч построены с обработкой стыков и unknown, тесты проходят.

#### PATCH-002 — Patch weighting и missing masks
- **EPIC:** 08 — Patch intelligence
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Ввести взвешивание исторических примеров по патчам и маски отсутствия данных.
- **CONTEXT:** Требование полного MVP: patch weighting + missing masks; веса не должны зависеть от целевого матча.
- **INPUT:** `FEAT-001`, `PATCH-001`.
- **OUTPUT:** Весовая функция (затухание по патч-расстоянию), правила масок, версия весов в manifest.
- **DEPENDENCIES:** FEAT-001, PATCH-001
- **ACCEPTANCE CRITERIA:** (1) Веса фитятся только на train. (2) Маски отличают «нет данных» от «нулевого значения». (3) Вес не использует информацию из целевого матча. (4) Есть отчёт распределения весов.
- **TESTS:** Тест fit-only-train; тест различения masking vs zero; тест воспроизводимости весов.
- **FILES EXPECTED TO CHANGE:** `src/features/patch_weight.py`, `tests/features/test_patch_weight.py`.
- **RISKS:** Утечка через веса, посчитанные на всём датасете; маски, превращающиеся в нули.
- **DEFINITION OF DONE (task-specific):** Веса и маски реализованы, веса fit только на train, маски отличают отсутствие от нуля, отчёт распределения приложен.

#### PATCH-003 — Сдвиги hero balance/winrate по патчам
- **EPIC:** 08 — Patch intelligence
- **STAGE:** MVP2
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Измерить, как меняются витрейты героев между патчами (as-of).
- **CONTEXT:** Нужен сигнал о мете без утечки: используются только матчи предыдущих патчей.
- **INPUT:** `PATCH-001`, `PLAY-002`.
- **OUTPUT:** Таблица hero×patch (winrate/пики), правила малых выборок, отчёт стабильности.
- **DEPENDENCIES:** PATCH-001, PLAY-002
- **ACCEPTANCE CRITERIA:** (1) Только данные до cutoff. (2) Малые выборки маскируются. (3) Изменения фиксируются как наблюдения, а не как каузальные утверждения. (4) Воспроизводимо.
- **TESTS:** Тест cutoff; тест малых выборок.
- **FILES EXPECTED TO CHANGE:** `src/features/patch_hero_shift.py`, `tests/features/test_patch_hero_shift.py`.
- **RISKS:** Причинно-следственные заявления без оснований; шум на малых патчах.
- **DEFINITION OF DONE (task-specific):** Таблица hero×patch строится as-of, малые выборки маскируются, формулировки некаузальные, тесты проходят.

---

### EPIC 09 — Draft intelligence

#### DRAFT-001 — Извлечение draft-данных и hero pool из исторических карт
- **EPIC:** 09 — Draft intelligence
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Извлечь `picks_bans`/`draft_timings` и построить hero pool **из исторических карт**, а не из целевого драфта.
- **CONTEXT:** Требование полного MVP; целевой драфт недоступен до матча и не может быть входом.
- **INPUT:** `DATA-001`, `DB-002`.
- **OUTPUT:** Нормализованные picks/bans с порядком и таймингами; hero pool на cutoff по игроку/команде.
- **DEPENDENCIES:** DATA-001, DB-002
- **ACCEPTANCE CRITERIA:** (1) Draft-данные связаны с картой и серией. (2) Hero pool строится только из истории. (3) Целевой драфт явно не читается. (4) Неоднозначные draft-записи уходят в карантин.
- **TESTS:** Тест «целевой драфт не читается»; тест карантина неоднозначных пиков; тест покрытия draft-данных.
- **FILES EXPECTED TO CHANGE:** `src/normalize/draft.py`, `src/features/hero_pool.py`, `tests/normalize/test_draft.py`.
- **RISKS:** Утечка через целевой драфт; отсутствие draft у части матчей → смещение.
- **DEFINITION OF DONE (task-specific):** Draft-данные и hero pool построены из истории, целевой драфт не используется, покрытие и карантин отчитаны, тесты проходят.

#### DRAFT-002 — Draft-признаки (synergy/counter, hero winrate с затуханием)
- **EPIC:** 09 — Draft intelligence
- **STAGE:** MVP2
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Построить признаки драфта: синергии/контрпики и взвешенные витрейты героев.
- **CONTEXT:** Признаки должны быть as-of и учитывать патч; затухание задаётся явно.
- **INPUT:** `DRAFT-001`, `PATCH-001`.
- **OUTPUT:** Набор draft-признаков (bag-of-heroes, синергии, контрпики, взвешенные винрейты) с окнами и масками.
- **DEPENDENCIES:** DRAFT-001, PATCH-001
- **ACCEPTANCE CRITERIA:** (1) Все признаки as-of. (2) Затухание параметризовано и попадает в manifest. (3) Неизвестные взаимодействия дают маску. (4) Признаки устойчивы к появлению новых героев (не «замороженный словарь»).
- **TESTS:** Тест cutoff; тест нового героя; тест маски неизвестного взаимодействия.
- **FILES EXPECTED TO CHANGE:** `src/features/draft_features.py`, `tests/features/test_draft_features.py`.
- **RISKS:** Замороженный словарь героев ломает инференс; утечка через винрейты, посчитанные на всём датасете.
- **DEFINITION OF DONE (task-specific):** Draft-признаки строятся as-of с параметрами затухания в manifest, маски и новые герои обрабатываются, тесты проходят.

#### DRAFT-003 — Draft-strength baseline модель
- **EPIC:** 09 — Draft intelligence
- **STAGE:** MVP2
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Обучить модель «силы драфта» как отдельный слой и сравнить с общей моделью.
- **CONTEXT:** Нужен изолированный вклад драфта, а не смешение с формой.
- **INPUT:** `DRAFT-002`, `ML-001`.
- **OUTPUT:** Draft-only модель с метриками на том же протоколе сплитов и отчёт сравнения.
- **DEPENDENCIES:** DRAFT-002, ML-001
- **ACCEPTANCE CRITERIA:** (1) Единый протокол оценки. (2) Метрики (Brier/logloss) отчитаны. (3) Нет заявлений о превосходстве без сравнения. (4) Версия модели зарегистрирована.
- **TESTS:** Тест воспроизводимости обучения; тест одинаковости сплитов.
- **FILES EXPECTED TO CHANGE:** `src/models/draft_model.py`, `docs/DRAFT_MODEL.md`.
- **RISKS:** Несравнимые сплиты; переобучение на малых выборках драфтов.
- **DEFINITION OF DONE (task-specific):** Draft-only модель обучена, метрики на едином протоколе отчитаны, версия зарегистрирована, сравнение оформлено.

#### DRAFT-004 — Интеграция draft в предсказание и объяснение
- **EPIC:** 09 — Draft intelligence
- **STAGE:** MVP2
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Включить draft-признаки в основную модель и в шаблонное объяснение.
- **CONTEXT:** Интеграция только после ablation; объяснение — шаблонное evidence, не LLM.
- **INPUT:** `DRAFT-003`, `API-002`.
- **OUTPUT:** Обновлённая модель с draft-признаками, ablation-отчёт, шаблонные пункты объяснения по драфту.
- **DEPENDENCIES:** DRAFT-003, API-002
- **ACCEPTANCE CRITERIA:** (1) Включение подтверждено ablation. (2) Объяснение ссылается на конкретные evidence-поля снапшота. (3) Нет LLM-генерации в объяснении. (4) Версия модели и фич зафиксированы.
- **TESTS:** Тест наличия ablation; тест «объяснение ссылается на существующие поля»; тест неизменности снапшота.
- **FILES EXPECTED TO CHANGE:** `src/models/main_model.py`, `src/api/explanations.py`.
- **RISKS:** Включение драфта без ablation; галлюцинации в объяснении (недопустимы — только шаблоны).
- **DEFINITION OF DONE (task-specific):** Draft-признаки включены с подтверждающим ablation, объяснения шаблонные и ссылаются на реальные поля снапшота, версии зафиксированы.

#### DRAFT-005 — Спекулятивное исследование: RL/GNN-подход к драфту
- **EPIC:** 09 — Draft intelligence
- **STAGE:** FUTURE
- **PRIORITY:** P3
- **STATUS:** Proposed
- **GOAL:** Исследовать (без обязательства внедрения) RL/GNN-подходы к моделированию драфта как **спекулятивное** направление.
- **CONTEXT:** `P3` — только спекулятивные направления. Задача не требуется для MVP/MVP2 и не подменяет `DRAFT-002..004`.
- **INPUT:** `DRAFT-003`, `ML-002`.
- **OUTPUT:** Исследовательская записка + экспериментальный протокол сравнения с принятым draft-baseline; при отсутствии эффекта — явный отказ.
- **DEPENDENCIES:** DRAFT-003, ML-002
- **ACCEPTANCE CRITERIA:** (1) Единый протокол/сплиты с baseline. (2) Неопределённость отчитана. (3) Нет заявлений о превосходстве без статистики. (4) Явно: направление не требуется для текущих стадий. (5) Никакого прод-влияния без решения owner.
- **TESTS:** Тест воспроизводимости; чек-лист «нет прод-влияния».
- **FILES EXPECTED TO CHANGE:** `docs/RESEARCH_DRAFT_RL.md`, `research/` (планируемые пути).
- **RISKS:** Спекулятивный результат трактуется как готовое решение; вычислительные затраты без пользы.
- **DEFINITION OF DONE (task-specific):** Записка и протокол существуют, сравнение с baseline оформлено, при отсутствии эффекта зафиксирован отказ; прод-влияния нет.

---

### EPIC 10 — Baseline ML

#### ML-001 — Prior + Logistic Regression baseline: temporal group split, frozen heldout, Brier/logloss
- **EPIC:** 10 — Baseline ML
- **STAGE:** MVP-FIRST10
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Построить baseline (prior + LR) с корректным временным групповым сплитом и замороженным heldout.
- **CONTEXT:** Research-only на этом шаге: **CatBoost пока не используется**. Сплит по сериям с purge на пересечении.
- **INPUT:** `FEAT-001`.
- **OUTPUT:** Baseline-модель, замороженный heldout, метрики Brier/logloss, отчёт по протоколу; версия модели.
- **DEPENDENCIES:** FEAT-001
- **ACCEPTANCE CRITERIA:** (1) Сплит временной и групповой по сериям. (2) Purge исключает пересечение серий. (3) Heldout заморожен и не используется для подбора. (4) Трансформации fit только на train. (5) Отчитаны Brier и logloss относительно prior. (6) Обучение только на map1-когорте (или явно помечено иначе).
- **TESTS:** Тест отсутствия пересечения серий между сплитами; тест «heldout не читается при обучении»; тест метрик.
- **FILES EXPECTED TO CHANGE:** `src/models/baseline_lr.py`, `src/eval/split.py`, `docs/BASELINE.md`, `tests/models/test_baseline.py`.
- **RISKS:** Случайный сплит (как в reference-проектах) → завышенные метрики; утечка при препроцессинге; отсутствие baseline-сравнения.
- **DEFINITION OF DONE (task-specific):** Baseline обучен на temporal group split с purge, heldout заморожен, Brier/logloss отчитаны против prior, есть отчёт о протоколе и версия модели.

#### ML-002 — CatBoost challenger (CPU) в сравнении с LR
- **EPIC:** 10 — Baseline ML
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Обучить CatBoost challenger на CPU и **сравнить** с LR на том же протоколе. **Победа над LR не требуется для MVP.**
- **CONTEXT:** Challenger допустим только после baseline; CPU-only. **Выбор/промо модели делается на tuning folds**, калибровка — отдельный шаг (`CAL-002/003`), а **untouched test используется только как итоговый гейт и не участвует в подборе победителя**. Champion'ом по итогам гейта может остаться LR.
- **INPUT:** `ML-001`, `PATCH-002`, `TEAM-002`.
- **OUTPUT:** Challenger-модель, отчёт сравнения метрик на tuning folds (с неопределённостью), решение о промо (возможно «оставить LR»), версия модели, регистрация в реестре артефактов.
- **DEPENDENCIES:** ML-001, PATCH-002, TEAM-002
- **ACCEPTANCE CRITERIA:** (1) Тот же протокол сплитов; untouched test не используется для выбора. (2) CPU-обучение. (3) Сравнение с LR с неопределённостью (grouped bootstrap по сериям/времени). (4) **Нет требования, чтобы challenger победил**; допускается решение «champion остаётся LR». (5) Роль untouched test — только итоговый гейт. (6) G-MODEL оформлен как решение owner.
- **TESTS:** Тест одинаковости сплитов; тест «untouched test не читается при выборе»; тест воспроизводимости обучения.
- **FILES EXPECTED TO CHANGE:** `src/models/catboost_challenger.py`, `docs/CHALLENGER.md`.
- **RISKS:** Подбор победителя на test (загрязнение финального гейта); разные сплиты → ложное превосходство; неявная смена метрики.
- **DEFINITION OF DONE (task-specific):** Challenger обучен на CPU, сравнение с LR оформлено на tuning folds с неопределённостью, зафиксировано решение о промо (в т.ч. допустимо «LR») и роль untouched test как итогового гейта; версия зарегистрирована, вердикт G-MODEL направлен owner.

#### ML-003 — Ablation/importance и availability masks, имитирующие инференс
- **EPIC:** 10 — Baseline ML
- **STAGE:** MVP2
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Провести ablation признаков и проверить, что обучающие маски имитируют условия инференса.
- **CONTEXT:** Признак без ablation не признаётся; маски train/inference должны совпадать по смыслу.
- **INPUT:** `ML-002`.
- **OUTPUT:** Отчёт ablation/importance по группам признаков, отчёт о соответствии масок train/inference, решения о включении.
- **DEPENDENCIES:** ML-002
- **ACCEPTANCE CRITERIA:** (1) Единый протокол для всех ablation. (2) Маски train/inference сопоставлены явно. (3) Решения по каждому признаку зафиксированы. (4) Нет «важности без метрики».
- **TESTS:** Тест идентичности семантики масок; тест воспроизводимости ablation.
- **FILES EXPECTED TO CHANGE:** `src/eval/ablation.py`, `docs/ABLATION.md`.
- **RISKS:** Train/serve skew; выводы по важности без контроля утечки.
- **DEFINITION OF DONE (task-specific):** Ablation выполнен по группам, соответствие масок train/inference подтверждено, решения по признакам зафиксированы.

#### ML-004 — Отчёт map1-когорта vs all-games gap
- **EPIC:** 10 — Baseline ML
- **STAGE:** MVP2
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Сравнить обучение только на map1 и на всех играх, зафиксировать gap и рекомендацию.
- **CONTEXT:** Широкое обучение допустимо только как отчёт о gap; рекомендация MVP — обучение только на map1.
- **INPUT:** `ML-001`, `DATA-001`.
- **OUTPUT:** Отчёт с метриками обеих стратегий на map1-когорте и явной рекомендацией.
- **DEPENDENCIES:** ML-001, DATA-001
- **ACCEPTANCE CRITERIA:** (1) Оценка обеих стратегий на одном map1-когорте. (2) Gap отчитан с неопределённостью. (3) Рекомендация сформулирована однозначно. (4) Нет подмены целевой метрики серией.
- **TESTS:** Тест единого когорта оценки; тест отсутствия утечки между стратегиями.
- **FILES EXPECTED TO CHANGE:** `docs/MAP1_VS_ALLGAMES.md`, `src/eval/cohort_report.py`.
- **RISKS:** Сравнение на разных когортах → ложный вывод; неявное использование series-метки.
- **DEFINITION OF DONE (task-specific):** Отчёт содержит метрики обеих стратегий на одном map1-когорте, gap с неопределённостью и явную рекомендацию.

#### EVAL-001 — Оценка исходов на frozen test: grouped bootstrap, insufficient-evidence rule
- **EPIC:** 10 — Baseline ML
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Дать итоговую оценку исходов модели на frozen untouched test **до** метрик-гейта, с корректной неопределённостью и правилом «недостаточно доказательств».
- **CONTEXT:** Оценка исходов должна предшествовать метрикс-гейту: без неё гейт `MON-001` не имеет основания. На малых выборках (в т.ч. 30 наблюдений) **нельзя** заявлять значимость. Frozen test считается достаточным только если достигает точности, **заранее выбранной в PRD**.
- **INPUT:** `ML-002`, `CAL-002`.
- **OUTPUT:** Отчёт оценки исходов: метрики (Brier/logloss/ECE), **grouped bootstrap по сериям и по времени**, интервалы, вердикт `sufficient` / `insufficient evidence`, явная ссылка на выбранную в PRD точность.
- **DEPENDENCIES:** ML-002, CAL-002
- **ACCEPTANCE CRITERIA:** (1) Оценка выполняется на frozen untouched test только один раз как итоговый гейт. (2) Bootstrap группируется по сериям и по времени, а не по отдельным картам. (3) На 30 наблюдениях **нет заявлений о статистической значимости**. (4) Если точность/объём ниже порога — вердикт `insufficient evidence`, а не «успех». (5) Никакие фактические метрики заранее не объявляются достигнутыми.
- **TESTS:** Тест группировки bootstrap; тест «insufficient evidence на малой выборке»; чек-лист отсутствия significance-заявлений.
- **FILES EXPECTED TO CHANGE:** `src/eval/outcomes.py`, `docs/OUTCOME_EVAL.md`.
- **RISKS:** Значимость на малой выборке; многократное использование frozen test; ложный «sufficient» вердикт.
- **DEFINITION OF DONE (task-specific):** Отчёт оценки исходов содержит метрики с grouped bootstrap по сериям/времени, явный вердикт `sufficient`/`insufficient evidence` и ссылку на выбранную в PRD точность; significance-заявления отсутствуют.

---

### EPIC 11 — Calibration

#### CAL-001 — Пайплайн калибровки: train → tuning → calibration → untouched test по сериям, purge
- **EPIC:** 11 — Calibration
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Реализовать строгий четырёхчастный протокол оценки по сериям с purge.
- **CONTEXT:** Калибровка не должна фититься на том же наборе, что и выбор модели; untouched test трогается один раз.
- **INPUT:** `ML-001`.
- **OUTPUT:** Разбиение на четыре части по сериям с purge, правила доступа к каждой части, отчёт о границах разбиения.
- **DEPENDENCIES:** ML-001
- **ACCEPTANCE CRITERIA:** (1) Четыре части не пересекаются по сериям. (2) Purge исключает протечку между частями. (3) Untouched test используется только для финальной оценки. (4) Границы разбиения попадают в manifest.
- **TESTS:** Тест отсутствия пересечения; тест «test не читается на этапах обучения/калибровки».
- **FILES EXPECTED TO CHANGE:** `src/eval/split.py`, `docs/CALIBRATION_PROTOCOL.md`.
- **RISKS:** Скрытое пересечение серий; многократное использование test → переоценка.
- **DEFINITION OF DONE (task-specific):** Протокол из четырёх непересекающихся частей с purge реализован, правила доступа соблюдаются, границы зафиксированы в manifest.

#### CAL-002 — Калибровка Platt/isotonic + ECE/Brier/logloss
- **EPIC:** 11 — Calibration
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Откалибровать вероятности и измерить качество калибровки.
- **CONTEXT:** Изотоник/Platt фитятся только на калибровочной части; **выбор метода калибровки — на tuning/calibration-фолдах, untouched test — только итоговый гейт**. Калибровка — отдельный шаг и не участвует в выборе победителя между LR и CatBoost.
- **INPUT:** `CAL-001`.
- **OUTPUT:** Калибраторы (Platt/isotonic), отчёт ECE/Brier/logloss до и после, выбор метода с обоснованием.
- **DEPENDENCIES:** CAL-001
- **ACCEPTANCE CRITERIA:** (1) Калибраторы фитятся только на calibration-части. (2) Метрики отчитаны до/после. (3) Выбор метода обоснован на tuning/calibration-фолдах, а не «по умолчанию» и не на test. (4) Нет заявлений о качестве без итогового untouched test; на малых выборках — без significance-заявлений. (5) Калибровка не используется для выбора champion'а между LR и CatBoost.
- **TESTS:** Тест «калибратор не видит test»; тест воспроизводимости калибровки.
- **FILES EXPECTED TO CHANGE:** `src/models/calibration.py`, `docs/CALIBRATION.md`.
- **RISKS:** Фитинг калибратора на val/test; ECE на малой выборке без интервалов.
- **DEFINITION OF DONE (task-specific):** Калибраторы обучены только на calibration-части, метрики до/после отчитаны на untouched test, выбор метода обоснован.

#### CAL-003 — Calibration freeze и версионирование
- **EPIC:** 11 — Calibration
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Заморозить калибровку и связать её версию с моделью и снимками.
- **CONTEXT:** «Calibration freeze» — требование полного MVP; версия калибровки должна быть в каждом снапшоте.
- **INPUT:** `CAL-002`.
- **OUTPUT:** Замороженный калибратор с версией, правило «изменение = новая версия», связь снапшот→калибровка, gate G-MODEL.
- **DEPENDENCIES:** CAL-002
- **ACCEPTANCE CRITERIA:** (1) Заморозка зафиксирована неизменяемым артефактом. (2) Каждый снапшот ссылается на конкретную версию калибровки. (3) Изменение калибровки невозможно без новой версии. (4) G-MODEL оформлен как решение owner.
- **TESTS:** Тест «снапшот без версии калибровки отклоняется»; негативный тест перезаписи.
- **FILES EXPECTED TO CHANGE:** `src/models/calibration.py`, `migrations/0008_*.sql`, `docs/GATES_REGISTRY.md`.
- **RISKS:** Тихая подмена калибратора; снапшоты без ссылки на версию.
- **DEFINITION OF DONE (task-specific):** Калибровка заморожена с версией, снапшоты ссылаются на версию, подмена без новой версии невозможна, вердикт G-MODEL оформлен.

---

### EPIC 12 — Prediction API

#### API-001 — Prediction service: immutable snapshots + API + шаблонное evidence (только game1)
- **EPIC:** 12 — Prediction API
- **STAGE:** MVP-FIRST10
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Сервис предсказания, который пишет immutable `Prediction`/`PredictionSnapshot`, отдаёт API и шаблонное evidence; цель — только game1.
- **CONTEXT:** Снимки обязательны с первого прототипа. Историческая оценка маркируется `retrospective_reconstructed`.
- **INPUT:** `ML-001`, `DB-001`.
- **OUTPUT:** FastAPI-эндпоинт предсказания, запись снапшота, шаблонное evidence, явная метка retrospective/prospective, отказ на не-game1 целях.
- **DEPENDENCIES:** ML-001, DB-001
- **ACCEPTANCE CRITERIA:** (1) На каждый вызов создаётся неизменяемый снапшот. (2) Цель ограничена game1; series-цель отклоняется. (3) Снапшот содержит модель/версию/фичи/cutoff. (4) Ретроспективная оценка помечена `retrospective_reconstructed`. (5) Нет LLM в объяснении. (6) Проектный порог: critical purity violations = 0 (ни один снапшот не содержит данных с `available_at > cutoff`).
- **TESTS:** Тест immutability снапшота; тест отказа на series-цель; тест обязательных полей; тест метки retrospective.
- **FILES EXPECTED TO CHANGE:** `src/api/predict.py`, `src/api/snapshots.py`, `tests/api/test_predict.py`.
- **RISKS:** Снапшот без cutoff/версии; выдача ретроспективы за «прогноз тогда»; расширение цели до серии.
- **DEFINITION OF DONE (task-specific):** Сервис принимает только game1-цель, пишет полный immutable-снапшот, возвращает шаблонное evidence, корректно маркирует ретроспективу; тесты проходят.

#### API-002 — FeatureSnapshot builder на инференсе (persist)
- **EPIC:** 12 — Prediction API
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** На каждом инференсе строить и сохранять `FeatureSnapshot` с точными входами модели.
- **CONTEXT:** Без сохранения фич нельзя объяснить предсказание и воспроизвести его.
- **INPUT:** `API-001`, `DATA-001`.
- **OUTPUT:** Модуль сборки `FeatureSnapshot` (значения, маски, cutoff, версия фич) с записью в immutable-хранилище.
- **DEPENDENCIES:** API-001, DATA-001
- **ACCEPTANCE CRITERIA:** (1) Снапшот фич записывается на каждом инференсе. (2) Значения совпадают с теми, что видит модель. (3) Cutoff и версия фич сохранены. (4) Маски доступности сохранены отдельно от значений.
- **TESTS:** Тест «фичи модели = фичи снапшота»; тест наличия масок и cutoff.
- **FILES EXPECTED TO CHANGE:** `src/api/feature_snapshot.py`, `tests/api/test_feature_snapshot.py`.
- **RISKS:** Расхождение фич сервинга и снапшота; потеря масок.
- **DEFINITION OF DONE (task-specific):** FeatureSnapshot сохраняется на каждом инференсе и точно совпадает с входами модели, включая маски и cutoff; тесты проходят.

#### API-003 — Генерация шаблонного evidence (не LLM)
- **EPIC:** 12 — Prediction API
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Формировать объяснения из шаблонов, привязанных к evidence снапшота.
- **CONTEXT:** Объяснения — шаблонные evidence, LLM не используется.
- **INPUT:** `API-001`.
- **OUTPUT:** Шаблонный генератор объяснений (например, вклад рейтинга/формы/ростера/патча), каждое утверждение ссылается на поле снапшота.
- **DEPENDENCIES:** API-001
- **ACCEPTANCE CRITERIA:** (1) Каждый пункт объяснения ссылается на существующее поле снапшота. (2) Нет генерации свободным текстом. (3) Отсутствуют утверждения о причинности/прибыльности. (4) Формулировки различают uncertain-данные.
- **TESTS:** Тест «ссылка на несуществующее поле отклоняется»; тест отсутствия запрещённых формулировок.
- **FILES EXPECTED TO CHANGE:** `src/api/explanations.py`, `docs/EXPLANATIONS.md`.
- **RISKS:** «Псевдо-объяснения» без опоры на данные; скрытое обещание точности.
- **DEFINITION OF DONE (task-specific):** Все пункты объяснения трассируются к полям снапшота, шаблоны детерминированы, запрещённые формулировки отсутствуют.

#### API-004 — Enforcement ретроспективы/проспективы и контракт API
- **EPIC:** 12 — Prediction API
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Технически различать ретроспективную и проспективную оценку и зафиксировать контракт API.
- **CONTEXT:** Ретроспектива обязана называться `retrospective_reconstructed`; проспективная возможна только при проспективно архивированной истории.
- **INPUT:** `API-001`, `PRD-003`.
- **OUTPUT:** Правила маркировки, схема контракта API (версии, поля, ошибки), отказ при невозможности доказать проспективность.
- **DEPENDENCIES:** API-001, PRD-003
- **ACCEPTANCE CRITERIA:** (1) Невозможно выставить метку prospective без архива. (2) Контракт версионируется. (3) Ошибки описаны детерминированно. (4) Совместимость контракта с шаблонным evidence сохранена.
- **TESTS:** Негативный тест «prospective без архива»; тест версии контракта; тест схемы ошибок.
- **FILES EXPECTED TO CHANGE:** `src/api/contract.py`, `docs/API_CONTRACT.md`, `tests/api/test_contract.py`.
- **RISKS:** Ретроспектива, выданная за реальный прогноз; ломающие изменения контракта.
- **DEFINITION OF DONE (task-specific):** Enforcement работает (prospective невозможен без архива), контракт версионирован и описан, негативные тесты проходят.

#### API-005 — Вероятность серии (отдельная задача MVP2)
- **EPIC:** 12 — Prediction API
- **STAGE:** MVP2
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Добавить отдельный вывод вероятности победы в серии, не смешивая с map1.
- **CONTEXT:** Series win — отдельная сущность, появляется только в MVP2 и не подменяет map1-цель.
- **INPUT:** `API-001`, `CAL-003`.
- **OUTPUT:** Отдельный эндпоинт/поле series-вероятности с собственной версией модели и явной пометкой отличия от map1.
- **DEPENDENCIES:** API-001, CAL-003
- **ACCEPTANCE CRITERIA:** (1) Series-вероятность не подменяет map1-ответ. (2) Имеет собственную версию модели. (3) Метрики отчитаны отдельно. (4) Снапшот series-предсказания также immutable.
- **TESTS:** Тест несмешения целей; тест immutability series-снапшота.
- **FILES EXPECTED TO CHANGE:** `src/api/series_predict.py`, `docs/SERIES_MODEL.md`.
- **RISKS:** Смешение map1/series; перенос метрик с одной цели на другую.
- **DEFINITION OF DONE (task-specific):** Series-вероятность выдаётся отдельно, с собственной версией модели и immutable-снапшотом, метрики отчитаны раздельно.

---

### EPIC 13 — Frontend MVP

#### UI-001 — Простая локальная страница матча на реальной held-out исторической game1
- **EPIC:** 13 — Frontend MVP
- **STAGE:** MVP-FIRST10
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Показать предсказание на реальном held-out историческом матче, явно как ретроспективу.
- **CONTEXT:** Страница не должна выглядеть как «живой прогноз»; необходима явная маркировка.
- **INPUT:** `API-001`.
- **OUTPUT:** Server-rendered страница: команды, предсказание game1, метка `retrospective_reconstructed`, провенанс (источник, дата), версия модели.
- **DEPENDENCIES:** API-001
- **ACCEPTANCE CRITERIA:** (1) Метка ретроспективы видна явно. (2) Провенанс и версия модели отображены. (3) Нет элементов, имитирующих live. (4) Страница работает локально.
- **TESTS:** Рендер-тест; проверка наличия метки и провенанса; проверка отсутствия live-элементов.
- **FILES EXPECTED TO CHANGE:** `src/web/templates/match.html`, `src/web/views.py`, `tests/web/test_match_page.py`.
- **RISKS:** UI, вводящий в заблуждение (ретроспектива как прогноз); отсутствие провенанса.
- **DEFINITION OF DONE (task-specific):** Страница отображает предсказание на реальном held-out матче с явной ретроспективной меткой, провенансом и версией модели, рендер-тесты проходят.

#### UI-002 — Server-rendered список/деталь матчей + provenance
- **EPIC:** 13 — Frontend MVP
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Дать простой навигационный интерфейс: список предсказанных матчей и деталь с провенансом.
- **CONTEXT:** Только server-rendered шаблоны, без React; provenance обязателен.
- **INPUT:** `UI-001`, `API-003`.
- **OUTPUT:** Список (фильтры по турниру/дате/метке) и детальная страница с evidence и ссылками на снапшот.
- **DEPENDENCIES:** UI-001, API-003
- **ACCEPTANCE CRITERIA:** (1) Список отделяет ретроспективу от проспективы. (2) Деталь ссылается на конкретный снапшот/версию. (3) Нет React и клиентских фреймворков. (4) Источник/дата данных видны.
- **TESTS:** Рендер-тесты списка/детали; тест фильтра по метке.
- **FILES EXPECTED TO CHANGE:** `src/web/templates/*.html`, `src/web/views.py`, `tests/web/*`.
- **RISKS:** Потеря провенанса в списке; смешение меток.
- **DEFINITION OF DONE (task-specific):** Список и деталь работают на серверных шаблонах, отделяют ретроспективу от проспективы, ведут к конкретному снапшоту; тесты проходят.

#### UI-003 — Маркировка ретроспективы/проспективы, атрибуция Liquipedia и панель модели
- **EPIC:** 13 — Frontend MVP
- **STAGE:** MVP2
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Усилить честность UI: явные метки статуса, атрибуция источников, панель модели/версии/причин.
- **CONTEXT:** Атрибуция Liquipedia (CC-BY-SA 3.0) обязательна; панель модели должна ссылаться на шаблонное evidence.
- **INPUT:** `UI-002`, `PRD-004`.
- **OUTPUT:** Блок статуса (retrospective/prospective/unknown), блок атрибуции источников, панель модели с версиями и причинами.
- **DEPENDENCIES:** UI-002, PRD-004
- **ACCEPTANCE CRITERIA:** (1) Атрибуция Liquipedia присутствует везде, где используются её данные. (2) Панель модели не содержит LLM-текста. (3) Статус данных явен. (4) Неизвестные значения визуально помечены.
- **TESTS:** Тест наличия атрибуции; тест статус-блока; тест «нет LLM-контента».
- **FILES EXPECTED TO CHANGE:** `src/web/templates/*.html`, `docs/UI_ATTRIBUTION.md`.
- **RISKS:** Нарушение CC-BY-SA; вводящая в заблуждение подача неопределённости.
- **DEFINITION OF DONE (task-specific):** Метки статуса, атрибуция Liquipedia и панель модели реализованы, LLM-контент отсутствует, тесты проходят.

---

### EPIC 14 — Expert intelligence

#### EXP-001 — Rights-cleared intake транскриптов и реестр источников
- **EPIC:** 14 — Expert intelligence
- **STAGE:** MVP3
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Настроить приём только правомерных транскриптов (собственные/предоставленные) и реестр источников.
- **CONTEXT:** Сначала права/согласие, потом всё остальное. Каналы Nix, RAMZES, Solo, NS — кандидаты-сущности, не проверенные хендлы.
- **INPUT:** `PRD-004`.
- **OUTPUT:** Реестр источников (правообладатель, основание, дата, срок), процедура приёма транскрипта, правила отказа при отсутствии прав.
- **DEPENDENCIES:** PRD-004
- **ACCEPTANCE CRITERIA:** (1) Каждый источник имеет подтверждённое основание (собственный/предоставленный/лицензия). (2) Кандидаты-каналы не трактуются как проверенные личности. (3) Нет приёма чужих транскриптов через API без прав. (4) Отказ фиксируется явно.
- **TESTS:** Чек-лист оснований; тест отказа при отсутствии прав.
- **FILES EXPECTED TO CHANGE:** `docs/EXPERT_SOURCES.md`, `src/experts/intake.py`.
- **RISKS:** Юридическое нарушение при использовании чужих транскриптов; «деанонимизация» кандидатов-каналов без оснований.
- **DEFINITION OF DONE (task-specific):** Реестр источников заполнен с основаниями, процедура приёма работает только для правомерных данных, правила отказа зафиксированы.

#### EXP-002 — LLM-извлечение в JSON с evidence/span/time и confidence
- **EPIC:** 14 — Expert intelligence
- **STAGE:** MVP3
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Извлекать из транскриптов структурированные утверждения с доказательствами (цитата/span/время).
- **CONTEXT:** Confidence извлечения ≠ вероятность исхода. Каждое утверждение обязано иметь evidence-span и таймстемп.
- **INPUT:** `EXP-001`.
- **OUTPUT:** Схема JSON-утверждения (тип, объект, evidence-span, время, confidence), извлекатель, правила валидации.
- **DEPENDENCIES:** EXP-001
- **ACCEPTANCE CRITERIA:** (1) У каждого утверждения есть evidence-span и время. (2) Confidence отделён от вероятности исхода. (3) Утверждение без evidence отклоняется. (4) Извлечение детерминировано по версии промпта/модели.
- **TESTS:** Тест «утверждение без span отклоняется»; тест детерминированности по версии.
- **FILES EXPECTED TO CHANGE:** `src/experts/extract.py`, `docs/EXPERT_SCHEMA.md`.
- **RISKS:** Галлюцинированные утверждения; путаница confidence и вероятности.
- **DEFINITION OF DONE (task-specific):** Схема и извлекатель работают, каждое утверждение имеет evidence-span/время, confidence не трактуется как вероятность, тесты проходят.

#### EXP-003 — Evaluation harness для экспертного извлечения
- **EPIC:** 14 — Expert intelligence
- **STAGE:** MVP3
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Измерить качество извлечения на размеченной выборке.
- **CONTEXT:** Без оценки извлечение нельзя использовать; эталонная разметка создаётся вручную.
- **INPUT:** `EXP-002`.
- **OUTPUT:** Метрики precision/recall по типам утверждений, отчёт ошибок, версии промпта/модели.
- **DEPENDENCIES:** EXP-002
- **ACCEPTANCE CRITERIA:** (1) Есть вручную размеченный эталон. (2) Метрики разделены по типам. (3) Ошибки категоризированы. (4) Версии извлечения в отчёте.
- **TESTS:** Тест воспроизводимости оценки; тест фиксированного эталона.
- **FILES EXPECTED TO CHANGE:** `src/experts/eval.py`, `docs/EXPERT_EVAL.md`.
- **RISKS:** Оценка на «удобной» выборке; неуказание версии модели.
- **DEFINITION OF DONE (task-specific):** Эталон размечен вручную, метрики по типам отчитаны, ошибки категоризированы, версии зафиксированы.

#### EXP-004 — Ablation экспертных признаков (без ablation — без включения)
- **EPIC:** 14 — Expert intelligence
- **STAGE:** MVP3
- **PRIORITY:** P2
- **STATUS:** Proposed
- **GOAL:** Проверить, даёт ли экспертный сигнал вклад, и только затем рассматривать включение в модель.
- **CONTEXT:** Признак не включается в модель без ablation; источники-кандидаты не получают доверия по умолчанию. Задача входит в **MVP3-контур экспертов** (если экспертный слой запрошен), а не в Future.
- **INPUT:** `EXP-003`, `ML-003`.
- **OUTPUT:** Ablation-отчёт по экспертным признакам на едином протоколе и явное решение о включении/невключении.
- **DEPENDENCIES:** EXP-003, ML-003
- **ACCEPTANCE CRITERIA:** (1) Единый протокол/сплиты с базовой моделью. (2) Метрики с неопределённостью. (3) Решение о включении обосновано. (4) Отсутствует «доверие эксперту» как аргумент.
- **TESTS:** Тест одинаковости сплитов; тест воспроизводимости ablation.
- **FILES EXPECTED TO CHANGE:** `docs/ABLATION_EXPERTS.md`, `src/experts/ablation.py`.
- **RISKS:** Смешивание экспертных и обычных признаков; переоценка на малой выборке.
- **DEFINITION OF DONE (task-specific):** Ablation на едином протоколе выполнен, метрики с неопределённостью отчитаны, решение о включении зафиксировано.

#### EXP-005 — Track record эксперта: сопоставление утверждений с исходами (MVP3)
- **EPIC:** 14 — Expert intelligence
- **STAGE:** MVP3
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Оценить, насколько утверждения конкретного эксперта/канала соотносятся с фактическими исходами, **до** любого доверия к нему.
- **CONTEXT:** Входит в **requested MVP3** (не Future), потому что без оценки track record экспертное свидетельство использовать нельзя. Confidence извлечения ≠ вероятность исхода; track record — отдельная величина со своей неопределённостью.
- **INPUT:** `EXP-003`, `DATA-001`.
- **OUTPUT:** Отчёт track record: набор утверждений с датами, сопоставление с исходами, размер выборки, ограничения, явная пометка малых выборок.
- **DEPENDENCIES:** EXP-003, DATA-001
- **ACCEPTANCE CRITERIA:** (1) Каждое утверждение имеет дату и evidence-span. (2) Исходы берутся строго после даты утверждения (никакого look-ahead). (3) Track record отделён от confidence извлечения. (4) На малых выборках — без significance-заявлений, возможен вердикт `insufficient evidence`. (5) Кандидаты-каналы (Nix, RAMZES, Solo, NS) не объявляются проверенными личностями.
- **TESTS:** Тест отсутствия look-ahead; тест малой выборки; чек-лист «канал ≠ проверенная личность».
- **FILES EXPECTED TO CHANGE:** `src/experts/track_record.py`, `docs/EXPERT_TRACK_RECORD.md`.
- **RISKS:** Look-ahead в сопоставлении; перенос авторитета канала на достоверность; выводы на малых выборках.
- **DEFINITION OF DONE (task-specific):** Отчёт track record существует, сопоставления без look-ahead, малые выборки помечены (`insufficient evidence` где применимо), кандидаты-каналы не приравнены к проверенным личностям.

---

### EPIC 15 — Heatmaps

#### HM-001 — Spike: доступ и пригодность реплеев (legal + payload parity)
- **EPIC:** 15 — Heatmaps
- **STAGE:** FUTURE
- **PRIORITY:** P2
- **STATUS:** Proposed
- **GOAL:** До реализации проверить доступность позиционных данных и их сопоставимость между эпохами.
- **CONTEXT:** Требуется legal permissions + payload historical parity; нельзя обещать heatmaps без проверки. **Research-часть heatmaps независима** от live-гейта; зависимость возникает только на rollout (см. `HM-003`).
- **INPUT:** `SRC-001`.
- **OUTPUT:** Отчёт: какие позиционные данные доступны, паритет полей по периодам, юридические условия, вердикт-кандидат G-HM.
- **DEPENDENCIES:** SRC-001
- **ACCEPTANCE CRITERIA:** (1) Проверены легальность и доступ. (2) Паритет payload проверен на разных периодах. (3) Разделены «проверено/неизвестно». (4) Вердикт направлен owner.
- **TESTS:** Повторяемость проверок; кросс-проверка полей по периодам.
- **FILES EXPECTED TO CHANGE:** `docs/HEATMAP_SPIKE.md`.
- **RISKS:** Данные для «своего» клиента принимаются за данные по чужим матчам; нет паритета → ложная аналитика.
- **DEFINITION OF DONE (task-specific):** Отчёт содержит доступность, легальность, паритет payload по периодам и вердикт-кандидат G-HM.

#### HM-002 — Дизайн извлечения позиционных данных и валидация
- **EPIC:** 15 — Heatmaps
- **STAGE:** FUTURE
- **PRIORITY:** P2
- **STATUS:** Proposed
- **GOAL:** Спроектировать извлечение позиционных рядов и правила валидации перед реализацией.
- **CONTEXT:** Только после прохождения G-HM; схема должна сохранять провенанс и учитывать неполноту.
- **INPUT:** `HM-001`, `DATA-001`.
- **OUTPUT:** Дизайн-документ: схема позиционных данных, частота, обработка пропусков, правила валидации и артефакты.
- **DEPENDENCIES:** HM-001, DATA-001
- **ACCEPTANCE CRITERIA:** (1) Дизайн не зависит от недоступных полей. (2) Пропуски обрабатываются явно. (3) Есть правило «сначала валидация, потом рендер». (4) Указан провенанс источника.
- **TESTS:** Ревью дизайна; чек-лист покрытия пропусков.
- **FILES EXPECTED TO CHANGE:** `docs/HEATMAP_DESIGN.md`.
- **RISKS:** Преждевременная реализация на неполных данных; визуализация, вводящая в заблуждение.
- **DEFINITION OF DONE (task-specific):** Дизайн покрывает схему, частоту, пропуски, валидацию и провенанс, не опираясь на недоступные поля.

#### HM-003 — Реализация heatmap-слоя (rollout только после G-LIVE)
- **EPIC:** 15 — Heatmaps
- **STAGE:** FUTURE
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Реализовать heatmap-слой по утверждённому дизайну, начиная rollout **только после прохождения `G-LIVE`**.
- **CONTEXT:** Research (`HM-001`, `HM-002`) независим, но **rollout heatmaps идёт после live-гейта** в порядке `live → heatmaps`. До прохождения гейта реализации нет; зависимость семантическая, а не «по номеру».
- **INPUT:** `HM-002`, `LIVE-001`.
- **OUTPUT:** Рабочий heatmap-слой с провенансом, валидацией и явной пометкой неполноты данных.
- **DEPENDENCIES:** HM-002, LIVE-001
- **ACCEPTANCE CRITERIA:** (1) Реализация соответствует дизайну `HM-002`. (2) Rollout не начинается до вердикта owner по `G-LIVE`. (3) Провенанс и пропуски видимы. (4) Нет визуализаций, вводящих в заблуждение (неполнота помечена). (5) Логирование структурное, локальная воспроизводимость.
- **TESTS:** Тест соответствия дизайну; чек-лист «гейт пройден»; тест видимости пропусков.
- **FILES EXPECTED TO CHANGE:** `src/heatmaps/*`, `src/web/templates/heatmap.html`, `docs/HEATMAPS.md`.
- **RISKS:** Rollout в обход гейта; неполные данные подаются как полные.
- **DEFINITION OF DONE (task-specific):** Heatmap-слой реализован по дизайну, rollout начат только после прохождения `G-LIVE`, провенанс и пропуски видимы, тесты проходят.

---

### EPIC 16 — Live engine

#### LIVE-001 — Spike доступа к live (/live pro coverage; GSI авторизованный локальный spectator)
- **EPIC:** 16 — Live engine
- **STAGE:** FUTURE
- **PRIORITY:** P2
- **STATUS:** Proposed
- **GOAL:** Проверить, что именно даёт live на бесплатных путях, и на каких условиях.
- **CONTEXT:** Нельзя обещать `/live` про-поля на основе только публичной выборки; GSI требует авторизованного локального spectator-клиента, а не серверного глобального фида.
- **INPUT:** `SRC-001`, `ING-001`.
- **OUTPUT:** Отчёт: наличие/заполненность про-полей, наблюдаемая задержка как наблюдение (не гарантия), требования к локальному GSI, legal, вердикт G-LIVE.
- **DEPENDENCIES:** SRC-001, ING-001
- **ACCEPTANCE CRITERIA:** (1) Про-live проверен отдельно от публичной выборки. (2) Задержка указана как наблюдение, а не как контракт. (3) Явно: GSI — локальный, авторизованный. (4) Вердикт направлен owner.
- **TESTS:** Bounded-пробы; кросс-проверка заполненности полей.
- **FILES EXPECTED TO CHANGE:** `docs/LIVE_SPIKE.md`, `docs/GATES_REGISTRY.md`.
- **RISKS:** Обещание полей по публичной выборке; попытка использовать GSI как глобальный фид.
- **DEFINITION OF DONE (task-specific):** Отчёт отделяет проверенное от неизвестного, фиксирует требования GSI и правило «задержка = наблюдение», вердикт G-LIVE оформлен.

#### LIVE-002 — Live feature parity и обработка train/serve skew
- **EPIC:** 16 — Live engine
- **STAGE:** FUTURE
- **PRIORITY:** P2
- **STATUS:** Proposed
- **GOAL:** Обеспечить сопоставимость live-признаков с обучающими и явно измерить skew.
- **CONTEXT:** Известный риск reference-проектов — live-режим получает подмножество фич.
- **INPUT:** `LIVE-001`, `FEAT-001`.
- **OUTPUT:** Таблица соответствия полей train/live, отчёт skew, правила недоступных признаков (маска/отказ).
- **DEPENDENCIES:** LIVE-001, FEAT-001
- **ACCEPTANCE CRITERIA:** (1) Каждый обучающий признак сопоставлен с live-источником или помечен недоступным. (2) Skew измерен и отчитан. (3) Недоступные признаки дают маску/отказ, а не подстановку. (4) Нет скрытой замены полей.
- **TESTS:** Тест сопоставления полей; тест недоступного признака.
- **FILES EXPECTED TO CHANGE:** `docs/LIVE_PARITY.md`, `src/features/live_parity.py`.
- **RISKS:** Train/serve skew → деградация live-качества; подстановка суррогатов без пометки.
- **DEFINITION OF DONE (task-specific):** Таблица соответствия полей и отчёт skew приложены, недоступные признаки обрабатываются маской/отказом.

#### LIVE-003 — Локальный live inference loop (без серверного глобального фида)
- **EPIC:** 16 — Live engine
- **STAGE:** FUTURE
- **PRIORITY:** P2
- **STATUS:** Proposed
- **GOAL:** Реализовать локальный цикл инференса на live-данных с сохранением immutable-снапшотов.
- **CONTEXT:** Только локально и только на авторизованном источнике; снапшоты обязательны, как и в pre-match.
- **INPUT:** `LIVE-002`, `API-002`.
- **OUTPUT:** Локальный цикл: приём live-состояния → фичи → предсказание → снапшот; маркировка live-предсказаний.
- **DEPENDENCIES:** LIVE-002, API-002
- **ACCEPTANCE CRITERIA:** (1) Работает только локально/авторизованно. (2) Каждое live-предсказание сохраняется как immutable-снапшот. (3) Метка отличает live от pre-match и ретроспективы. (4) Нет зависимости от серверного глобального фида.
- **TESTS:** Тест маркировки; тест immutability live-снапшота; тест отказа при отсутствии авторизации.
- **FILES EXPECTED TO CHANGE:** `src/live/loop.py`, `docs/LIVE_ENGINE.md`.
- **RISKS:** Смешение live и pre-match предсказаний; выход за пределы легального доступа.
- **DEFINITION OF DONE (task-specific):** Локальный цикл сохраняет immutable live-снапшоты с явной меткой, работает только на авторизованном локальном источнике, тесты проходят.

---

### EPIC 17 — Market intelligence

#### MKT-001 — Правомерный intake timestamped odds CSV (user-provided) и схема
- **EPIC:** 17 — Market intelligence
- **STAGE:** FUTURE
- **PRIORITY:** P2
- **STATUS:** Proposed
- **GOAL:** Определить схему и порядок приёма odds только из правомерного, предоставленного пользователем CSV.
- **CONTEXT:** Наличие бесплатных исторических timestamped odds неизвестно; **фабриковать данные запрещено**. Гейт G-MARKET.
- **INPUT:** `PRD-004`.
- **OUTPUT:** Схема odds (время снимка, рынок, выбор, линия, источник, номер снимка), процедура приёма, правила отклонения синтетики, вердикт-кандидат G-MARKET.
- **DEPENDENCIES:** PRD-004
- **ACCEPTANCE CRITERIA:** (1) Данные только user-provided и правомерные. (2) Каждая строка имеет фактическое время снимка. (3) Синтетические/выдуманные данные отклоняются. (4) Явно зафиксирован запрет автоторговли. (5) Вердикт направлен owner.
- **TESTS:** Тест отклонения без времени; тест отклонения синтетики; чек-лист источника.
- **FILES EXPECTED TO CHANGE:** `docs/MARKET_SCHEMA.md`, `src/market/intake.py`.
- **RISKS:** Фабрикация данных; использование закрывающей линии до decision time.
- **DEFINITION OF DONE (task-specific):** Схема и процедура приёма работают только с правомерным CSV с реальным временем снимка, синтетика отклоняется, вердикт G-MARKET оформлен.

#### MKT-002 — Commission/margin и de-vig
- **EPIC:** 17 — Market intelligence
- **STAGE:** FUTURE
- **PRIORITY:** P2
- **STATUS:** Proposed
- **GOAL:** Корректно считать маржу/комиссию и де-виговать линии.
- **CONTEXT:** Без de-vig сравнение модели с рынком некорректно; комиссия влияет на executability.
- **INPUT:** `MKT-001`.
- **OUTPUT:** Модуль расчёта margin/de-vig с версионированием, отчёт по рынкам, обработка неполных/несогласованных линий.
- **DEPENDENCIES:** MKT-001
- **ACCEPTANCE CRITERIA:** (1) De-vig метод явно указан и версионирован. (2) Комиссия учитывается отдельно от линии. (3) Несогласованные линии помечаются, а не «поправляются» молча. (4) Результаты воспроизводимы.
- **TESTS:** Тест на синтетическом примере с известной маржой; тест несогласованных линий.
- **FILES EXPECTED TO CHANGE:** `src/market/devig.py`, `docs/MARKET_MATH.md`.
- **RISKS:** Неверная трактовка маржи; двойной учёт комиссии.
- **DEFINITION OF DONE (task-specific):** Расчёт margin/de-vig воспроизводим и версионирован, комиссия учитывается отдельно, несогласованные линии помечаются.

#### MKT-003 — Фактическое decision time, executability и CLV на matched market
- **EPIC:** 17 — Market intelligence
- **STAGE:** FUTURE
- **PRIORITY:** P2
- **STATUS:** Proposed
- **GOAL:** Оценивать линию в момент принятия решения с учётом исполнимости и считать CLV на сопоставленном рынке.
- **CONTEXT:** Решение принимается до матча; закрывающая линия не может быть входом. CLV считается только на matched market.
- **INPUT:** `MKT-002`, `API-001`.
- **OUTPUT:** Модуль сопоставления рынка, расчёт decision-time линии, executability (лимиты/доступность), CLV-отчёт.
- **DEPENDENCIES:** MKT-002, API-001
- **ACCEPTANCE CRITERIA:** (1) Decision time фиксируется явно. (2) Закрывающая линия не используется как вход. (3) CLV считается только на matched market. (4) Нет обещаний прибыльности.
- **TESTS:** Тест «closing line не вход»; тест unmatched market → отказ/пометка.
- **FILES EXPECTED TO CHANGE:** `src/market/clv.py`, `docs/CLV.md`.
- **RISKS:** Look-ahead по закрывающей линии; сравнение разных рынков.
- **DEFINITION OF DONE (task-specific):** Decision-time линия, executability и CLV на matched market реализованы, closing line не используется как вход, формулировки без обещаний прибыли.

#### MKT-004 — Bankroll/settlement и анализ малых выборок
- **EPIC:** 17 — Market intelligence
- **STAGE:** FUTURE
- **PRIORITY:** P2
- **STATUS:** Proposed
- **GOAL:** Описать анализ банкролла/расчётов с честной оценкой неопределённости малых выборок.
- **CONTEXT:** Малые выборки легко дают ложную уверенность; отчёт должен это подчёркивать.
- **INPUT:** `MKT-003`.
- **OUTPUT:** Отчёт: схема расчётов, оценка неопределённости, чувствительность к комиссии/лимитам, явные ограничения.
- **DEPENDENCIES:** MKT-003
- **ACCEPTANCE CRITERIA:** (1) Неопределённость малых выборок показана явно. (2) Результаты не подаются как «стратегия». (3) Автоторговля отсутствует. (4) Комиссия/лимиты включены в анализ.
- **TESTS:** Тест на малой выборке (демонстрация широкой неопределённости); чек-лист «нет автоордеров».
- **FILES EXPECTED TO CHANGE:** `docs/BANKROLL_ANALYSIS.md`.
- **RISKS:** Ложная уверенность; скрытое превращение анализа в рекомендации по ставкам.
- **DEFINITION OF DONE (task-specific):** Отчёт содержит схему расчётов, явную неопределённость малых выборок и ограничения, автоторговля отсутствует.

---

### EPIC 18 — Backtesting

#### BT-001 — Harness ретроспективного бэктеста на реконструированной истории
- **EPIC:** 18 — Backtesting
- **STAGE:** FUTURE
- **PRIORITY:** P2
- **STATUS:** Proposed
- **GOAL:** Дать честный бэктест на ретроспективно реконструированных примерах с явной маркировкой.
- **CONTEXT:** Реконструкция обязана называться `retrospective_reconstructed`; нельзя выдавать её за реальные прогнозы.
- **INPUT:** `API-001`, `CAL-003`.
- **OUTPUT:** Harness: проход по времени, метрики, отчёт с явной меткой метода, версии моделей/фич по шагам.
- **DEPENDENCIES:** API-001, CAL-003
- **ACCEPTANCE CRITERIA:** (1) Все результаты помечены как ретроспективная реконструкция. (2) Метрики считаются по шагам времени. (3) Версии моделей/калибровки зафиксированы по шагам. (4) Нет утверждений о проспективной валидности.
- **TESTS:** Тест маркировки; тест фиксации версий по шагам; тест отсутствия пересечения серий.
- **FILES EXPECTED TO CHANGE:** `src/backtest/harness.py`, `docs/BACKTEST.md`.
- **RISKS:** Ретроспектива, поданная как реальный прогноз; скрытая утечка при реконструкции.
- **DEFINITION OF DONE (task-specific):** Harness воспроизводим, все результаты помечены как ретроспективная реконструкция, версии по шагам зафиксированы, тесты проходят.

#### BT-002 — Рыночный бэктест с комиссией/лимитами на matched market
- **EPIC:** 18 — Backtesting
- **STAGE:** FUTURE
- **PRIORITY:** P2
- **STATUS:** Proposed
- **GOAL:** Оценить гипотетическое сопоставление модели и рынка с явными издержками.
- **CONTEXT:** Только после MKT; без обещаний прибыльности; автоторговля запрещена.
- **INPUT:** `BT-001`, `MKT-003`.
- **OUTPUT:** Отчёт бэктеста с комиссией/лимитами, чувствительностью и явными ограничениями.
- **DEPENDENCIES:** BT-001, MKT-003
- **ACCEPTANCE CRITERIA:** (1) Издержки учтены явно. (2) Есть анализ чувствительности. (3) Нет рекомендаций по ставкам и автоордеров. (4) Ограничения перечислены.
- **TESTS:** Тест включения издержек; чек-лист «нет автоторговли».
- **FILES EXPECTED TO CHANGE:** `src/backtest/market_backtest.py`, `docs/MARKET_BACKTEST.md`.
- **RISKS:** Игнорирование ликвидности; публикация «стратегии» вместо анализа.
- **DEFINITION OF DONE (task-specific):** Бэктест учитывает комиссию/лимиты и чувствительность, ограничения перечислены, автоторговля отсутствует.

#### BT-003 — Отчёт robustness и малых выборок
- **EPIC:** 18 — Backtesting
- **STAGE:** FUTURE
- **PRIORITY:** P2
- **STATUS:** Proposed
- **GOAL:** Проверить устойчивость результатов к изменениям протокола и объёму выборки.
- **CONTEXT:** Малые выборки и множественные сравнения легко создают ложные «успехи».
- **INPUT:** `BT-001`.
- **OUTPUT:** Отчёт robustness: чувствительность к сплитам/окнам/гиперпараметрам, оценка неопределённости, список ограничений.
- **DEPENDENCIES:** BT-001
- **ACCEPTANCE CRITERIA:** (1) Есть несколько вариантов протокола. (2) Неопределённость показана. (3) Отмечены множественные сравнения. (4) Нет выводов о прибыльности.
- **TESTS:** Тест воспроизводимости вариантов; чек-лист формулировок.
- **FILES EXPECTED TO CHANGE:** `docs/BACKTEST_ROBUSTNESS.md`.
- **RISKS:** Cherry-picking лучшего варианта; выводы из малых выборок.
- **DEFINITION OF DONE (task-specific):** Отчёт содержит варианты протокола, неопределённость и явные ограничения; выводы о прибыльности отсутствуют.

---

### EPIC 19 — LLM analyst

#### LLM-001 — Дизайн LLM-аналитика: evidence-grounded, без фабрикации, в рамках бесплатного/локального
- **EPIC:** 19 — LLM analyst
- **STAGE:** FUTURE
- **PRIORITY:** P2
- **STATUS:** Proposed
- **GOAL:** Спроектировать аналитика, который работает только от evidence снапшота и не выдумывает данные, в бесплатном/локальном бюджете.
- **CONTEXT:** Reference-проекты используют платный LLM — вне ограничения «только бесплатное». LLM не заменяет численное предсказание.
- **INPUT:** `API-003`.
- **OUTPUT:** Дизайн: роль аналитика, жёсткая привязка к evidence, запреты, лимиты стоимости, границы (не изменяет предсказание).
- **DEPENDENCIES:** API-003
- **ACCEPTANCE CRITERIA:** (1) Каждый вывод должен трассироваться к evidence. (2) Фабрикация данных явно запрещена. (3) Бюджет/локальность учтены. (4) Аналитик не изменяет числа модели.
- **TESTS:** Ревью дизайна; чек-лист запретов; тест бюджета.
- **FILES EXPECTED TO CHANGE:** `docs/LLM_ANALYST_DESIGN.md`.
- **RISKS:** Галлюцинации; скрытый платный API; подмена численного прогноза текстом.
- **DEFINITION OF DONE (task-specific):** Дизайн задаёт привязку к evidence, запрещает фабрикацию и подмену чисел, содержит лимиты стоимости; одобрен owner.

#### LLM-002 — Retrieval снапшотов/фич/evidence и контракт промпта
- **EPIC:** 19 — LLM analyst
- **STAGE:** FUTURE
- **PRIORITY:** P2
- **STATUS:** Proposed
- **GOAL:** Дать аналитику доступ ровно к тем данным, что в снапшоте, и зафиксировать контракт промпта.
- **CONTEXT:** Retrieval ограничен снапшотом; экспертное извлечение подключается с evidence-span.
- **INPUT:** `LLM-001`, `API-002`, `EXP-002`.
- **OUTPUT:** Модуль retrieval (снапшот/фичи/evidence/экспертные утверждения), версионированный контракт промпта.
- **DEPENDENCIES:** LLM-001, API-002, EXP-002
- **ACCEPTANCE CRITERIA:** (1) Нет доступа к данным вне снапшота. (2) Контракт промпта версионирован. (3) Экспертные утверждения передаются с evidence-span и confidence. (4) Retrieval детерминирован.
- **TESTS:** Тест «нет доступа вне снапшота»; тест версии промпта; тест детерминированности retrieval.
- **FILES EXPECTED TO CHANGE:** `src/llm/retrieval.py`, `docs/LLM_PROMPT.md`.
- **RISKS:** Retrieval, тянущий финальные статистики; передача экспертного мнения как факта.
- **DEFINITION OF DONE (task-specific):** Retrieval ограничен снапшотом, контракт промпта версионирован, экспертные данные передаются со span/confidence, тесты проходят.

#### LLM-003 — Оценка и guardrails вывода аналитика
- **EPIC:** 19 — LLM analyst
- **STAGE:** FUTURE
- **PRIORITY:** P2
- **STATUS:** Proposed
- **GOAL:** Проверять вывод аналитика на трассируемость, отсутствие фабрикации и запрещённых формулировок.
- **CONTEXT:** Guardrails обязательны: любой неподкреплённый вывод отбрасывается.
- **INPUT:** `LLM-002`.
- **OUTPUT:** Guardrail-набор (трассируемость утверждений к evidence, запрет числовых выдумок, запрет обещаний прибыли/точности), отчёт прогонов и отказов.
- **DEPENDENCIES:** LLM-002
- **ACCEPTANCE CRITERIA:** (1) Утверждение без evidence отбрасывается. (2) Выдуманные числа блокируются. (3) Запрещённые формулировки блокируются. (4) Есть отчёт отказов.
- **TESTS:** Негативные тесты (фабрикация, неподкреплённое утверждение, обещание прибыли).
- **FILES EXPECTED TO CHANGE:** `src/llm/guardrails.py`, `docs/LLM_GUARDRAILS.md`.
- **RISKS:** Пропуск галлюцинации; ложное блокирование корректного вывода.
- **DEFINITION OF DONE (task-specific):** Guardrails блокируют неподкреплённые утверждения и выдуманные числа, отчёт отказов формируется, негативные тесты проходят.

---

### EPIC 20 — Automation

#### AUTO-001 — Архитектурные требования к будущему локальному worker
- **EPIC:** 20 — Automation
- **STAGE:** MVP2
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Описать требования к будущему локальному worker как **документ**, без создания и без запуска.
- **CONTEXT:** Automation runtime в текущем чате недоступна: только требования к будущему локальному worker. **Не создавать/не конфигурировать/не инструктировать запуск cron/recurring-задач здесь.** При этом **дизайн не заменяет реализацию**: полноценный MVP-гейт требует, чтобы автоматическое обнаружение/ingestion **фактически работали** в будущем локальном deployment (`ING-008`).
- **INPUT:** `INF-001`, `ING-003`.
- **OUTPUT:** Документ требований: идемпотентность, чекпойнты, лимиты, наблюдаемость, поведение при сбое, границы (никаких внешних отправок).
- **DEPENDENCIES:** INF-001, ING-003
- **ACCEPTANCE CRITERIA:** (1) Документ описывает требования, а не исполнение. (2) Явно запрещены автоматические внешние действия. (3) Описаны идемпотентность и восстановление после сбоя. (4) Никакие задачи здесь не создаются и не запускаются.
- **TESTS:** Ревью документа; кросс-проверка «нет инструкций по запуску».
- **FILES EXPECTED TO CHANGE:** `docs/AUTOMATION_REQUIREMENTS.md`.
- **RISKS:** Незаметное превращение требований в фактически работающую автоматизацию; внешние отправки.
- **DEFINITION OF DONE (task-specific):** Документ требований существует, содержит идемпотентность/чекпойнты/лимиты/наблюдаемость, не содержит инструкций по запуску и внешних действий.

#### AUTO-002 — Дизайн расписания ingestion, идемпотентности и backfill
- **EPIC:** 20 — Automation
- **STAGE:** FUTURE
- **PRIORITY:** P2
- **STATUS:** Proposed
- **GOAL:** Спроектировать, как будущий локальный worker будет рекуррентно тянуть данные, без реализации.
- **CONTEXT:** Только дизайн. Опирается на чекпойнты и лимиты источников.
- **INPUT:** `AUTO-001`, `ING-002`, `ING-008`.
- **OUTPUT:** Дизайн: каденс по источникам, окна, поведение при деградации, правила повторного запуска, метрики.
- **DEPENDENCIES:** AUTO-001, ING-002, ING-008
- **ACCEPTANCE CRITERIA:** (1) Дизайн учитывает лимиты каждого источника. (2) Описано поведение при пустых ответах/429. (3) Повторный запуск безопасен. (4) Никаких cron-задач не создаётся.
- **TESTS:** Ревью дизайна; чек-лист лимитов.
- **FILES EXPECTED TO CHANGE:** `docs/AUTOMATION_INGEST_DESIGN.md`.
- **RISKS:** Каденс, исчерпывающий квоты; небезопасный повторный запуск.
- **DEFINITION OF DONE (task-specific):** Дизайн описывает каденс, окна, деградацию и безопасный повторный запуск с учётом лимитов; задач не создаётся.

#### AUTO-003 — Дизайн нотификаций (Future, без внешних отправок)
- **EPIC:** 20 — Automation
- **STAGE:** FUTURE
- **PRIORITY:** P2
- **STATUS:** Proposed
- **GOAL:** Описать, как в будущем формировать внутренние уведомления о завершении пайплайнов/гейтов.
- **CONTEXT:** Только внутренние уведомления; внешние отправки (email/messenger) не выполняются и не настраиваются здесь.
- **INPUT:** `AUTO-001`, `API-001`.
- **OUTPUT:** Дизайн: типы событий, содержание, частота, правила подавления шума, границы.
- **DEPENDENCIES:** AUTO-001, API-001
- **ACCEPTANCE CRITERIA:** (1) Только внутренние уведомления. (2) Внешние отправки явно исключены. (3) Есть правила подавления шума. (4) Ничего не отправляется в этой работе.
- **TESTS:** Ревью дизайна; чек-лист «нет внешних каналов».
- **FILES EXPECTED TO CHANGE:** `docs/NOTIFICATIONS_DESIGN.md`.
- **RISKS:** Случайная внешняя отправка; шум, маскирующий важные сбои.
- **DEFINITION OF DONE (task-specific):** Дизайн описывает события и подавление шума, внешние каналы исключены, ничего не отправляется.

---

### EPIC 21 — Monitoring

#### MON-001 — Операционные и ML-гейты покрытия пайплайна/данных
- **EPIC:** 21 — Monitoring
- **STAGE:** MVP
- **PRIORITY:** P1
- **STATUS:** Planned
- **GOAL:** Формализовать гейты покрытия данных и пайплайна с **проектными** порогами и решением owner (G-OPS).
- **CONTEXT:** Требование полного MVP: operational/data coverage + ML gates. Оценка исходов (`EVAL-001`) должна быть выполнена **до** этого гейта. Автоматически гейты не «проходят»; пороги — определения, а не достигнутые значения.
- **INPUT:** `EVAL-001`, `API-001`, `DATA-001`, `ING-008`.
- **OUTPUT:** Набор метрик покрытия (доля серий с map1, доля матчей с драфтом, покрытие ростера, пропуски фич) на **фиксированном заранее** знаменателе — **30 последовательных real eligible game1 fixtures**; gaps раздельно **по источнику** и **по модели**; отчёт и вердикт-кандидат G-OPS.
- **DEPENDENCIES:** EVAL-001, API-001, DATA-001, ING-008
- **ACCEPTANCE CRITERIA:** (1) Каждая метрика определена и воспроизводима. (2) Пороги заданы **до** просмотра результата и не меняются после. (3) Проектные пороги: coverage **>= 90%** на знаменателе 30 реальных подходящих game1 fixtures; purity critical violations = **0**; unmapped evaluation records = **0**. (4) Gaps репортятся раздельно по источнику и по модели. (5) На 30 наблюдениях **никаких заявлений о значимости**. (6) Гейт требует явного решения owner; при недостаточном объёме — вердикт `insufficient evidence`.
- **TESTS:** Тест воспроизводимости метрик; тест «порог не меняется после прогона»; чек-лист отсутствия significance-заявлений.
- **FILES EXPECTED TO CHANGE:** `src/monitoring/coverage.py`, `docs/OPS_GATES.md`, `docs/GATES_REGISTRY.md`.
- **RISKS:** Подгонка порогов под результат; «автоматически зелёный» гейт.
- **DEFINITION OF DONE (task-specific):** Метрики и пороги зафиксированы заранее, отчёт с фактическими значениями приложен, вердикт G-OPS направлен owner.

#### MON-002 — Мониторинг здоровья источников и деградации
- **EPIC:** 21 — Monitoring
- **STAGE:** MVP2
- **PRIORITY:** P2
- **STATUS:** Planned
- **GOAL:** Отслеживать доступность/качество источников и фиксировать деградацию.
- **CONTEXT:** SLA нет ни у одного бесплатного источника; нужен собственный health-контур.
- **INPUT:** `ING-006`, `MON-001`.
- **OUTPUT:** Метрики (доля ошибок/пустых, задержка обновления, расход квот), отчёт деградации, правила эскалации владельцу.
- **DEPENDENCIES:** ING-006, MON-001
- **ACCEPTANCE CRITERIA:** (1) Метрики по каждому источнику. (2) Деградация не маскируется под «нет данных». (3) Есть отчёт за окно. (4) Эскалация — только внутренняя.
- **TESTS:** Тест на пустых ответах/429; тест отчёта.
- **FILES EXPECTED TO CHANGE:** `src/monitoring/source_health.py`, `docs/SOURCE_HEALTH.md`.
- **RISKS:** Тихий отказ источника; ложная тревога.
- **DEFINITION OF DONE (task-specific):** Метрики по источникам собираются, деградация фиксируется отдельно от отсутствия данных, отчёт формируется.

#### MON-003 — Research: мониторинг дрейфа модели/данных
- **EPIC:** 21 — Monitoring
- **STAGE:** FUTURE
- **PRIORITY:** P2
- **STATUS:** Proposed
- **GOAL:** Исследовать, как отслеживать дрейф признаков/качества без ложных выводов.
- **CONTEXT:** Дрейф меты и патчей — реальный риск; нужен план, а не преждевременная реализация.
- **INPUT:** `MON-001`, `CAL-003`.
- **OUTPUT:** Дизайн метрик дрейфа (распределения признаков, калибровка по времени), пороги, ограничения малых выборок.
- **DEPENDENCIES:** MON-001, CAL-003
- **ACCEPTANCE CRITERIA:** (1) Метрики привязаны к времени и cutoff. (2) Учтена множественность сравнений. (3) Нет автоматических «переобучений» без решения owner. (4) Ограничения описаны.
- **TESTS:** Ревью дизайна; чек-лист cutoff.
- **FILES EXPECTED TO CHANGE:** `docs/DRIFT_MONITORING.md`.
- **RISKS:** Ложные срабатывания; автоматические изменения модели.
- **DEFINITION OF DONE (task-specific):** Дизайн описывает метрики дрейфа с учётом времени, множественности и ограничений; автоматических изменений модели не предусмотрено.

---

### EPIC 22 — Production deployment

#### DEP-001 — Воспроизводимость, backup/restore и DR локально
- **EPIC:** 22 — Production deployment
- **STAGE:** FUTURE
- **PRIORITY:** P2
- **STATUS:** Proposed
- **GOAL:** Описать воспроизводимое развёртывание локально и восстановление после сбоя.
- **CONTEXT:** Только локальный контур, без K8s; immutable-снапшоты должны переживать восстановление.
- **INPUT:** `DB-004`, `INF-005`.
- **OUTPUT:** Инструкция развёртывания с нуля, процедура восстановления, проверка целостности снапшотов после restore.
- **DEPENDENCIES:** DB-004, INF-005
- **ACCEPTANCE CRITERIA:** (1) Развёртывание с нуля воспроизводимо. (2) Восстановление проверено на копии. (3) Снапшоты остаются неизменными после restore. (4) Нет K8s/облачных зависимостей.
- **TESTS:** Плановое восстановление на копии; проверка целостности снапшотов.
- **FILES EXPECTED TO CHANGE:** `docs/DEPLOY_LOCAL.md`, `docs/DR_PLAN.md`.
- **RISKS:** Невоспроизводимое развёртывание; порча снапшотов при восстановлении.
- **DEFINITION OF DONE (task-specific):** Инструкция развёртывания и DR-план существуют, восстановление проверено на копии, целостность снапшотов подтверждена.

#### DEP-002 — Локальное deployment hardening и процесс версий/changelog
- **EPIC:** 22 — Production deployment
- **STAGE:** FUTURE
- **PRIORITY:** P2
- **STATUS:** Proposed
- **GOAL:** Ужесточить локальное развёртывание и описать процесс версий/изменений.
- **CONTEXT:** Без версионирования артефактов невозможно связать снапшоты с релизами.
- **INPUT:** `DEP-001`, `INF-004`, `AUTO-001`.
- **OUTPUT:** Правила конфигурации/секретов в локальном контуре, схема версий артефактов и моделей, процесс changelog, чек-лист релиза.
- **DEPENDENCIES:** DEP-001, INF-004, AUTO-001
- **ACCEPTANCE CRITERIA:** (1) Версии артефактов/моделей согласованы со снапшотами. (2) Секреты не попадают в образы/репозиторий. (3) Changelog ведётся по правилу. (4) Чек-лист релиза исполним вручную.
- **TESTS:** Ревью чек-листа; тест связности «снапшот → версия модели».
- **FILES EXPECTED TO CHANGE:** `docs/RELEASE_PROCESS.md`, `CHANGELOG.md`, `docs/DEPLOY_LOCAL.md`.
- **RISKS:** Снапшоты без привязки к версии; утечка секретов.
- **DEFINITION OF DONE (task-specific):** Правила версионирования и релиза описаны, снапшоты связаны с версиями, секреты исключены, changelog ведётся.

---

### Приложение A. Порядок исполнения и вертикальный срез

**Первый вертикальный прототип (`MVP-FIRST10`)** — ровно 10 задач, строго в порядке зависимостей:

1. `PRD-001` → 2. `SRC-001` → 3. `INF-001` → 4. `DB-001` → 5. `ING-001` → 6. `DATA-001` → 7. `FEAT-001` → 8. `ML-001` → 9. `API-001` → 10. `UI-001`.

В `FEAT-001` входит **минимальный Team- и Player-prior-form**; расширенные player-агрегаты (EPIC 06) — уже MVP2-надстройка.

Этот срез даёт **ретроспективный** прототип, а **не** полноценный pre-match MVP. Полноценный MVP требует дополнительно (минимум): `ING-004` (при прохождении G-UPCOMING), `ING-008`, `TEAM-002`, `DRAFT-001`, `PATCH-002`, `ML-002`, `EVAL-001`, `CAL-001..003`, `API-002..004`, `UI-002`, `MON-001`.

**Правило порядка:** внутри стадии сначала закрываются `P0`, затем `P1`, затем `P2`, и только потом `P3`. Ни одна задача `P3` не берётся раньше незакрытых `P0`/`P1`/`P2`. `P3` — только спекулятивные исследования (`SYN-004`, `DRAFT-005`).

**Правило гейтов:** каждый гейт (`G-SRC`, `G-UPCOMING`, `G-ROSTER`, `G-MODEL`, `G-OPS`, `G-LIVE`, `G-HM`, `G-MARKET`) — это задача с **проектными** порогами и **ручным** вердиктом owner. Автоматической реализации гейтов не существует. Семантика отказа `G-SRC` различает два случая: **история недоступна → STOP до `INF-001`**; **upcoming недоступен при работающей истории → только ретроспективный прототип**. Rollout heatmaps (`HM-003`) — **после `G-LIVE`**, хотя research (`HM-001`, `HM-002`) независим.

**Чего в этом бэклоге нет:** кода, инструкций по запуску cron/recurring-задач, обещаний прибыльности/точности, оценки сроков, автоматических внешних отправок, HTML-scraping, использования исключённых/непроверенных источников в critical path.

---


## Part 12 — Навигация пакета (README)

**Статус: предложения для согласования. Кода приложения нет; ничего не запущено, не развёрнуто и не опубликовано.**

Условия владельца: solo-founder, только бесплатные источники данных, личный исследовательский инструмент. Дата пакета: 2026-09-16 (Asia/Singapore; часы инструмента). Условия API и сведения репозиториев — срез исследования, не гарантия будущей доступности.

### Начать здесь

1. Product Vision, границы и gates (PRODUCT.md) — что строим и что считается работающим результатом.
2. Первые 10 задач (FIRST_10_TASKS.md) — ближайший последовательный маршрут.
3. Полный backlog (BACKLOG.md) — все EPIC 00–22, полные карточки, зависимости, критерии и DoD.
4. Источники и reference-проекты (SOURCES.md) — OpenDota, STRATZ, Valve/Steam, Liquipedia, PandaScore, replay/expert источники, NUKI1223/dota-predictor и amarcu/dota-predictor; verified/docs/unknown различаются.

### Архитектура

| Документ | Содержание |
|---|---|
| ARCHITECTURE.md (ARCHITECTURE.md) | Модульный монолит, stack, ingestion, событийность, API/UI, эксплуатация, будущая структура repo |
| DATA_MODEL.md (DATA_MODEL.md) | Все запрошенные сущности, дополнительные evidence/identity/time сущности, cardinalities, FK/uniqueness, snapshots |
| FEATURES.md (FEATURES.md) | Team/Player/Patch/Draft/Tournament/Synergy и формальные определения style metrics |
| ML.md (ML.md) | Baseline/challenger, temporal splits, leakage, calibration, evaluation и ensemble gates |
| EXPERT_ENGINE.md (EXPERT_ENGINE.md) | Права, transcripts, extraction, экспертные claims, track record, consensus, LLM analyst |
| LIVE.md (LIVE.md) | Live access, state/time parity, trajectory, heatmaps и spatial features |
| BACKTEST.md (BACKTEST.md) | Market architecture, no-vig/edge/EV, simulator, ROI/CLV/drawdown, ANALYSIS-only ограничения |

### Предлагаемые ADR

- ADR-001: database (docs/adr/ADR-001-database.md)
- ADR-002: initial data provider (docs/adr/ADR-002-initial-data-provider.md)
- ADR-003: ML baseline (docs/adr/ADR-003-ml-baseline.md)
- ADR-004: temporal validation (docs/adr/ADR-004-temporal-validation.md)
- ADR-005: prediction snapshots (docs/adr/ADR-005-prediction-snapshots.md)

Все ADR — Proposed. Владелец ещё не одобрял ни target первой карты, ни stack, ни gates. Внутренние task IDs ссылаются на BACKLOG.md; пути FILES EXPECTED TO CHANGE — будущие файлы, не утверждение, что код уже создан.

### Главные выводы

- Первый вертикальный срез — **ретроспективный** прототип на реальных game1, не выдуманный исторический live forecast.
- Полный MVP требует проверенного бесплатного upcoming-источника, фактически работающего локального автоматического ingestion, known-roster/fallback и честной prospective оценки.
- OpenDota history — основной кандидат; Liquipedia API upcoming — условный до access/rights/coverage gate; PandaScore не включён без разрешения для сценария с market-анализом.
- Prediction/Feature snapshots и temporal lineage нужны сразу; CatBoost — challenger, не обязательный победитель LR.
- Live/heatmaps/expert/market доступны только по своим gates; отсутствие данных нельзя заменить уверенными обещаниями.

### Рабочий протокол AI coding assistant

Выбрать одну задачу → прочитать архитектуру/связанный код → объяснить план → написать тесты → реализовать → запустить тесты → review → обновить документацию → commit в согласованном репозитории. Архитектурная проблема: STOP → объяснение → альтернативы → решение владельца. Никакие шаги реализации не выполняются по этому документу автоматически.

**CURRENT EPIC:** EPIC 00 — Product specification. **CURRENT TASK:** PRD-001. **WHY IT MATTERS:** зафиксировать target первой карты, scope и измеримые gates до сбора и обучения. **DEPENDENCIES:** нет. **NEXT ACTION:** решение владельца по предложениям PRODUCT.md; затем SRC-001 только по команде.

В этой среде scheduled/recurring tasks недоступны. Пакет описывает требования будущего локального продукта, не создаёт автоматизации помощника.

---


## Part 12b — ADR (Architecture Decision Records)


### ADR-001 — Database

**Статус:** Proposed, не утверждён владельцем.

**Контекст:** один разработчик, бесплатные источники, нужны provenance, temporal joins, идемпотентность и неизменяемая история.

**Предложение:** одна PostgreSQL; canonical — typed tables/PK/FK; raw и snapshots — JSONB; крупные replay/model artifacts — локальные файлы с checksum/manifest. Никаких Redis/ClickHouse/feature-store сервисов в MVP.

**Альтернативы:** SQLite проще для throwaway research, но переход к общим API/worker транзакциям потребует миграции; отдельное object storage — после измерения объёма. Не создавать распределённое хранилище заранее.

**Последствия:** нужны migrations и backup/restore test; реляционные связи не растворяются в JSON. Append-only snapshots и temporal revisions реализуются явно, не появляются автоматически из выбора БД.

**Основания:** [constraints](https://www.postgresql.org/docs/current/ddl-constraints.html), [range types](https://www.postgresql.org/docs/current/rangetypes.html).

**Условия пересмотра:** измеренный размер/latency превышают ресурсы одиночной БД, подтверждён отдельный workload. Связанные документы: DATA_MODEL.md, ARCHITECTURE.md. Принятие — PRD-001/PRD-004, реализация — DB-001.

---


### ADR-002 — Initial data provider

**Статус:** Proposed; operational доступ не подтверждён этим ADR.

**Контекст:** OpenDota historical API не является upcoming-календарём; проект ограничен бесплатными источниками и содержит будущий market-анализ.

**Предложение:** OpenDota — primary historical candidate после bounded coverage/rights audit. Liquipedia API — conditional upcoming/announced-roster candidate, только разрешённый API, без HTML scraping. STRATZ — optional secondary после token/schema проверки. PandaScore — вне critical path до письменного подтверждения допустимости сценария с market/edge/backtest.

**Альтернативы:** использовать только исторический OpenDota для первого прототипа; поменять источник, если бесплатный schedule gate не пройден. Community bridge не обход ToS и не независимый первоисточник.

**Последствия:** нужен EntityMapping, quarantine неоднозначных team/fixture matches, отдельный freshness/coverage отчёт. Upcoming no-go при working history оставляет ретроспективный прототип, но не закрывает полноценный MVP. History no-go блокирует INF-001.

**Основания:** SOURCES.md, U1–U15; [OpenDota docs](https://docs.opendota.com/), [Liquipedia ToS](https://liquipedia.net/api-terms-of-use), [PandaScore pricing/use restrictions](https://www.pandascore.co/pricing).

**Условия принятия:** SRC-001 фиксирует реальные данные/headers/coverage, права хранения и доступ; владелец принимает gate. Изменение провайдера не меняет canonical model без отдельного ADR.

---


### ADR-003 — ML baseline

**Статус:** Proposed.

**Контекст:** нужна проверяемая вероятность, а не число моделей. Мало данных и неизвестная полнота roster/patch history.

**Предложение:** первая карта, pre-draft target; constant prior → Logistic Regression → CatBoost CPU challenger. Champion выбирается на temporal tuning folds, не на final test; LR допустим как итог MVP. Calibration и metrics из ML.md обязательны до quality claim. LLM не математический предиктор.

**Альтернативы:** сразу neural/ensemble либо обязательная цепочка всех boosting libraries — откладываются из-за стоимости оценки и сопровождения. Series-win target с первого дня возможен только после отдельного решения владельца и изменения dataset/validation.

**Последствия:** нужны cohort map1, cold-start/fallback, outcome policy, feature availability masks, model/data/code manifests. CatBoost implementation не доказывает superiority.

**Основания:** [calibration](https://scikit-learn.org/stable/modules/calibration.html), [categorical features](https://catboost.ai/docs/en/features/categorical-features).

**Условия принятия:** PRD-001 утверждает target и критерии полезности; ML-001 baseline, ML-002 challenger. Пересмотр — доказанный OOS gain нового подхода на сопоставимых данных.

---


### ADR-004 — Temporal validation

**Статус:** Proposed, обязательное условие честной оценки после принятия.

**Предложение:** отдельно хранить event/source-publication/observed/ingested/available times. Strict feature <= cutoff по фактической доступности. Историю, полученную сейчас, считать retrospective_reconstructed с отдельной assumed-availability policy, без backdating observed_at.

**Split:** calendar/series train → tuning → calibration → untouched test; crossing series purge; все transforms внутри train fold; model selection до test; calibration не на train. Final test используется один раз. Поздние outcomes/roster corrections не переписывают прошлые feature snapshots.

**Альтернативы:** random split и latest-views проще, но не соответствуют будущему serving и не принимаются как доказательство качества.

**Последствия:** потребуется больше audit metadata и честный статус insufficient evidence на малой выборке. Отсутствие leakage в коде не доказывает historical availability, если источник её не архивировал.

**Основания:** [TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html), [calibration guide](https://scikit-learn.org/stable/modules/calibration.html). Group/calendar splitter проектируется отдельно.

**Приёмка:** tests из ML.md, критерии PRD-001, проверка DATA-001/FEAT-001/ML-001. Любая критическая утечка блокирует переход этапа.

---


### ADR-005 — Prediction snapshots

**Статус:** Proposed.

**Контекст:** без evidence и model version невозможно доказать, что вероятность действительно была рассчитана на указанных данных до события. Поэтому перенос snapshots целиком в MVP 2 неприемлем для проверяемого прототипа.

**Предложение:** immutable Prediction как target contract; append-only PredictionSnapshot с cutoff/computed time, model version, FeatureSnapshot, roster/draft/expert/market state refs, режимом historical/prospective, probability/abstention и idempotency key. Минимум сразу, расширенные draft/live states позднее.

**Альтернативы:** mutable current_probability проще, но не воспроизводим. Полное event-sourcing всего приложения — лишняя сложность; достаточно версий критических фактов и prediction ledger.

**Последствия:** API читает только committed snapshots; повторный request не создаёт дубль; новый input revision — новый snapshot. Result correction создаёт новую PredictionEvaluation, старое предсказание не меняется. Юридически обязательное удаление evidence отмечается tombstone и потерей полной воспроизводимости.

**Приёмка:** DB-001 ограничения, API-001 запись/чтение, повторный расчёт, snapshot hash, evidence FK, отсутствие backdating. Gate не означает, что forecast полезен: качество проверяется отдельно ML.md.

---


## Part 13 — Исходное ТЗ: конспект требований

Зафиксированные владельцем требования, к которым обязан привязываться принимающий агент (полное ТЗ — 61 раздел, здесь только операционно значимое).

### 13.1 Роль и принципы

Solo-founder + AI-ассистент, который выступает как CTO / PM / ML Architect / Data Engineer / Backend / ML Engineer / AI Engineer / DevOps / QA / аналитик. Решения принимаются **совместно** с владельцем. Архитектура не создаётся ради архитектуры. Работа маленькими задачами, каждая с работающим результатом; нельзя переходить к следующему крупному этапу, пока предыдущий не проверен.

### 13.2 Продуктовые измерения

TEAM · PLAYER · DRAFT · GAME · MARKET — основные; EXPERT OPINION · TOURNAMENT CONTEXT — дополнительные. Все они сходятся в feature engine, затем pre-match/live, ensemble, calibration, prediction + analysis, UI.

### 13.3 Основные сущности ТЗ

Tournament, TournamentStage, Series, Match, Game, Team, Roster, Player, Hero, Patch, Draft, GameEvent, PlayerPerformance, PlayerSynergy, TeamStyle, PlayerStyle, Expert, ExpertOpinion, Prediction, PredictionSnapshot, MarketSnapshot, Heatmap, FeatureSnapshot, ModelVersion, Backtest. Список открыт: пакет добавляет доказательные сущности (EvidenceRecord, EntityMapping, RosterMembership, ResultRevision, ClaimEvaluation, CommunitySignal, PositionSample, IngestionRun и др.) — см. Part 3.

### 13.4 Источники, которые требовалось исследовать

OpenDota, STRATZ, Valve/Steam, Liquipedia, PandaScore, другие esports API, replay/game-state источники, Twitch, YouTube, публичные интервью, аналитические материалы. Для каждого: что получаем, API, стоимость, лимиты, частота обновления, историческая глубина, качество, юридические/ToS ограничения, критичность. Нельзя строить критичную архитектуру на непроверенном источнике; источник должен быть заменяемым. Результат — Part 9.

### 13.5 Требования к data ingestion

Pipeline SOURCE → INGESTION → RAW → VALIDATION → NORMALIZATION → DATABASE → FEATURES. Обязательно: новые турниры/матчи, обновление статусов, составы, игроки, драфт, патч, game data, повтор неудачных запросов, обработка rate limits, логирование ошибок, отсутствие дублей, отслеживание времени последнего обновления, обнаружение изменений. Все процессы **идемпотентны**.

### 13.6 Automatic event engine (требование автоматизации)

Система сама понимает: новый турнир → стадии → матчи → изменение состава → начало матча → драфт → game → end game → final result. Ручное создание матча не требуется. Пример из ТЗ: 09:00 обнаружен турнир → 09:02 серия → 09:03 Team A vs Team B → 09:04 ростер → 09:05 прогноз → 14:00 старт → 14:01 live-движок → 16:00 конец → 16:01 оценка прогноза. В пакете это требование зафиксировано как контракт и e2e-критерии будущего локального worker (`ING-008`, `G-OPS`), а не как уже работающая автоматизация.

### 13.7 Player / Team / Synergy / Patch / Draft / Tournament intelligence

Игрок — центральная сущность: профиль не только lifetime, но и окна 365/90/30 дней, 20/10 игр, текущий патч/турнир/ростер; признаки winrate, KDA, GPM/XPM, kill participation, death rate, damage, tower/Roshan/teamfight participation, lane performance, farm efficiency, map activity, objective participation, hero pool/specialization/flexibility, performance by patch/role/teammates/opponents. **Субъективные оценки запрещены:** у каждого показателя (aggression, map pressure, mechanical impact) должно быть математическое происхождение и формальное определение — см. Part 4. Аналогично Team DNA, Player Style, synergy (пары/тройки/пятёрка, стабильность/стендины/role swap), patch intelligence с recency weighting, draft intelligence со снапшотами после каждого изменения драфта, tournament context через измеримые признаки, а не психологию.

### 13.8 Heatmap engine

Минимум: movement, farm, death, teamfight, ward-related, objective. Heatmap — не только UI, а потенциальный источник ML-признаков: map_control, rotation_frequency, farm_area, enemy_jungle_presence, objective_pressure, death_hotspots, average_rotation_distance, teamfight_position. См. Part 7 (LIVE.md).

### 13.9 Expert / community слой

Pipeline: VIDEO/STREAM/INTERVIEW → TRANSCRIPT → SEGMENTATION → LLM EXTRACTION → STRUCTURED OPINION. Хранить не только sentiment, но исходное утверждение, источник, timestamp, контекст. Мнение эксперта не превращать в факт. Темы: player skill, current form, hero pool/strength, draft, team strength/weakness, meta, patch, strategy, lane, teamfight, synergy, roster, tournament, match prediction. Track record: prediction/opinion → будущее событие → фактический исход; разрезы по теме/патчу/роли/горизонту. **Произвольные «рейтинги доверия» запрещены** — только прозрачная методика. Consensus остаётся отдельным сигналом: statistical / model / expert / community не смешивать без объяснимости происхождения. Community sentiment — не объективная истина; хранить source, timestamp, topic, entity, sentiment, volume.

### 13.10 ML-требования

Не начинать с LLM. Порядок: Logistic Regression → XGBoost/LightGBM → CatBoost → neural → ensemble; для live — CatBoost/XGBoost baseline → LSTM/temporal → ensemble. Pre-match: P(Team A wins)/P(Team B wins) с обязательным хранением model version. Live: снапшоты прогноза во времени (траектория). Ensemble: meta-model получает outputs Team/Player/Draft/Patch/Tournament/Live/Expert; веса обучаемые или обоснованные. Calibration: Brier, Log Loss, ECE, calibration curve, reliability diagram — ориентироваться не только на accuracy. **Data leakage — критический пункт:** никакой информации после момента prediction; temporal split или rolling-window. PredictionSnapshot обязан хранить prediction_id, match_id, timestamp, model_version, probability, features_snapshot, draft_state, roster_state, expert_state, market_state.

### 13.11 Market / edge / backtest / betting

Market подключается **после** доказанной работоспособности прогнозной системы. Для каждого снапшота: timestamp, bookmaker/market, selection, odds, implied_probability, model_probability; учитывать маржу. Edge = model_probability − market_probability, но положительный edge **не** доказывает прибыльность: проверять ROI, drawdown, CLV, Brier, Log Loss, calibration, sample size. Backtest engine: date range, market, min edge, max odds, min confidence, model version, stake strategy → bets, wins, losses, win rate, profit, ROI, max drawdown, CLV, profit factor, calibration; без подгонки под один период, с out-of-sample. Betting module на первом этапе — **только ANALYSIS**, автоматическое размещение ставок не делать.

### 13.12 LLM analyst, страницы, уведомления

LLM получает структурированные данные (model outputs, профили, драфт, патч, контекст, мнения, heatmap-признаки, live state) и генерирует объяснение «почему модель оценивает Team A выше» с **ссылкой на источник данных внутри системы**; LLM не должна придумывать статистику. Страницы: Match (probabilities, draft, player/team intelligence, expert opinions, heatmaps, объяснение, market, prediction history, live graph), Player, Team, Tournament. Notification engine: новое событие/матч/ростер/драфт/изменение прогноза/расхождение с рынком/оценка прогноза — с настраиваемостью.

### 13.13 Стек, репозиторий, документация, backlog

Ориентир по стеку: Python, PostgreSQL, FastAPI, Pandas/Polars, CatBoost, PyTorch, Redis при необходимости, Docker, Git, React/Next.js; для фоновых задач — Celery/RQ/APScheduler **после** оценки требований; Kafka/Kubernetes/ClickHouse «ради модности» запрещены. Структура репозитория из ТЗ (src/ingestion, normalization, features, models, prediction, experts, live, market, backtest, api; tests; frontend; scripts; docs/adr) — в пакете уточнена с пометкой «будущие пути». Документы: PRODUCT, ARCHITECTURE, DATA_MODEL, ML, EXPERT_ENGINE, LIVE, BACKTEST, BACKLOG + ADR (database, initial data provider, ML baseline, temporal validation, prediction snapshots). Эпики 00–22 — как в ТЗ; формат задачи: TASK ID, TITLE, EPIC, PRIORITY, STATUS, GOAL, CONTEXT, INPUT, OUTPUT, DEPENDENCIES, ACCEPTANCE CRITERIA, TESTS, FILES EXPECTED TO CHANGE, RISKS, DEFINITION OF DONE.

### 13.14 Workflow AI-ассистента и DoD

Workflow: select task → read architecture → read related code → explain plan → write tests → implement → run tests → review → update documentation → commit. Не просить AI «сделай весь проект». Definition of Done: код работает, тесты проходят, логирование есть, документация обновлена, нет регрессий, локальное окружение работает, acceptance criteria выполнены.

### 13.15 MVP-этапы по ТЗ и их отображение в пакете

ТЗ: MVP (OpenDota → PostgreSQL → автоматический ingestion → team/player features → CatBoost → pre-match prediction → FastAPI → простой web UI), MVP 2 (draft, synergy, tournament context, patch intelligence, snapshots), MVP 3 (expert intelligence + LLM extraction + история), MVP 4 (live + trajectory), MVP 5 (heatmaps), MVP 6 (market + edge + backtest), MVP 7 (LLM analyst + alerts + полностью автоматический event-driven pipeline). Отображение и границы — Part 1 (PRODUCT.md); ключевое отличие: минимальные snapshots и temporal-версии перенесены в первый прототип, а CatBoost — challenger, не обязательный победитель LR.

### 13.16 Приоритеты, KPI, риски

P0 критично → P1 нужно для MVP → P2 важно → P3 nice-to-have; P3 не делать при незакрытых P0/P1. KPI — не количество функций/строк и не accuracy, а data coverage, data freshness, calibration, log loss, Brier, out-of-sample performance, backtest stability, model drift (+ ROI, CLV, max drawdown, sample size для market). Риски к постоянному отслеживанию: API unavailable, bad data, duplicates, data leakage, overfitting, concept drift, patch/roster changes, малые выборки, expert bias, LLM hallucination, качество market-данных, legal/ToS. Главный ML-принцип: accuracy ≠ calibration ≠ prediction quality ≠ market edge ≠ profitability. Направления после baseline (GNN, embeddings, temporal transformers, online learning, RL, spatial, knowledge graph, RAG, multimodal) — только после качественного baseline.

### 13.17 Путь развития и что делать, когда владелец спрашивает «что дальше»

Отвечать структурой CURRENT EPIC / CURRENT TASK / WHY IT MATTERS / DEPENDENCIES / NEXT ACTION, вести последовательно, дробить большие задачи, говорить прямо, если задача не нужна для MVP. Новую фичу оценивать по impact, complexity, data requirements, ML value, product value, maintenance cost — но решение оставлять владельцу.

---

## Приложение — состав пакета


- `PRODUCT.md` — Part 1 — Product Vision и определение MVP
- `ARCHITECTURE.md` — Part 2 — System Architecture
- `DATA_MODEL.md` — Part 3 — Data Architecture и Data Model
- `FEATURES.md` — Part 4 — Feature Engine
- `ML.md` — Part 5 — ML Architecture
- `EXPERT_ENGINE.md` — Part 6 — Expert Architecture
- `LIVE.md` — Part 7 — Live Architecture и Heatmap Engine
- `BACKTEST.md` — Part 8 — Market Architecture и Backtest Engine
- `SOURCES.md` — Part 9 — Исследование источников и reference-проектов
- `FIRST_10_TASKS.md` — Part 10 — Первые 10 задач
- `BACKLOG.md` — Part 11 — Полный backlog (EPIC 00–22)
- `README.md` — Part 12 — Навигация пакета (README)
- `docs/adr/ADR-001-database.md` — ADR-001 — Database
- `docs/adr/ADR-002-initial-data-provider.md` — ADR-002 — Initial data provider
- `docs/adr/ADR-003-ml-baseline.md` — ADR-003 — ML baseline
- `docs/adr/ADR-004-temporal-validation.md` — ADR-004 — Temporal validation
- `docs/adr/ADR-005-prediction-snapshots.md` — ADR-005 — Prediction snapshots
