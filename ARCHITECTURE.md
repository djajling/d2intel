# System Architecture

Статус: PROPOSED. Все изменения архитектуры согласуются с владельцем через ADR. Здесь только проект; ни приложение, ни jobs не запущены.

## 1. Минимальная форма

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

## 2. Технологические решения

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

### Celery / RQ / APScheduler: не смешивать scheduler и queue

- **APScheduler:** кандидат для одного локального процесса в будущем deployment, без broker. Для исследованной 3.x ветки совместное использование job store несколькими процессами приводит к ошибкам — [FAQ](https://apscheduler.readthedocs.io/en/3.x/faq.html), [guide](https://apscheduler.readthedocs.io/en/3.x/userguide.html). Не распространять это утверждение автоматически на другую major version.
- **RQ:** простая task queue с Redis/Valkey; добавляет сервис, пока не нужен — [docs](https://python-rq.org/docs/).
- **Celery:** broker-based queue; более сложные workflows пока не оправданы — [brokers](https://docs.celeryq.dev/en/stable/getting-started/backends-and-brokers/index.html).

Рекомендация по future local worker: один владелец ingestion с checkpoint и идемпотентными обработчиками; APScheduler оценить при реализации после version pinning, без внедрения очереди заранее. В текущей среде scheduled/recurring tasks недоступны: здесь они не создаются и не запускаются; доступен только разовый исследовательский workflow. Это ограничение среды помощника, не отказ от требования автопополнения будущего локального продукта.

## 3. Контракт source adapter

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

## 4. События и конечные автоматы

Минимальный MVP: обнаружение → нормализация → пригодность forecast → прогноз → результат → оценка. Изменение состояния и запись события совершаются одной транзакцией. Пока worker один, обработка может быть последовательной; Durable outbox нужен при внешних уведомлениях/нескольких consumers, не раньше.

| Объект | Состояния | Критические случаи |
|---|---|---|
| Fixture/Match | discovered → scheduled → in_progress → completed | postponed/cancelled/forfeit/unknown; возврат к scheduled после переноса не стирает историю |
| Game | placeholder → draft → running → finished | remake/abandoned/void/corrected; повторная карта получает собственную идентичность |
| Forecast | eligible → computed → stored → served → evaluated | ineligible/abstained; failed store означает не served |
| Ingestion | pending → fetched → validated → normalized | retryable/dead-letter/quarantined; cursor не продвигается при неполной транзакции |

У событий есть aggregate_id, source_revision, event_type, occurred_at, observed_at и dedup_key. Источник может пропустить draft/start и сразу дать result: автомат не изобретает промежуточные timestamps. Late result correction создаёт новую revision и evaluation revision; старые predictions остаются неизменными.

Identity resolution: provider ID → canonical mapping; затем проверяемые сочетания league, team pair, series и времени. Fuzzy name — лишь кандидат; при неоднозначности карантин, а не уверенное объединение. Нулевой/отсутствующий provider ID не становится общей сущностью «Team 0».

## 5. Prediction API / presentation

Контракт ответа: target_type, target_id, team_a_id, team_b_id, probability_a/b или abstention, forecast_phase, computed_at, cutoff_at, evaluation_mode, model_version_id, feature_snapshot_id, prediction_snapshot_id, roster_status, freshness и evidence_refs. Нельзя выдавать значение без указания target: первая карта или серия.

Предлагаемые ресурсы: список встреч, карточка встречи, история её snapshots, карточки команд/игроков, health/data-quality. Конкретный HTTP routing — задача API-001, не реализованный endpoint. Web чтение возвращает уже сохранённый snapshot; повторный GET не обучает модель и не обращается к внешнему API. Mutating recompute — локальный управляемый workflow с уникальным idempotency key, не публичный GET.

Показ: всегда время последнего обновления, missing fields, evidence и отсутствие forecast при невалидном входе. MVP explanation — фактические feature values и, где доступно, модельные contributions, не причинные утверждения. Никакой фразы «сильнее психологически» из длительности серии.

## 6. Ошибки, безопасность, сопровождение

- Структурные логи с run_id/source_id/entity_id; без секретов и полного текста приватных данных.
- Health различает процесс жив, БД доступна, данные свежи, forecasts пригодны; HTTP 200 не означает качественные данные.
- Метрики: fetch errors, quota remaining, lag, missing IDs, quarantine share, coverage denominator, snapshot failure, calibration/drift. Порог alert — отдельное согласование после наблюдения.
- БД и UI локально по умолчанию. Публичное размещение требует отдельного security gate, auth, TLS, secret handling и rights review; здесь ничего не публикуется.
- Backup raw/canonical/model artifacts с manifest; тест восстановления входит в MVP, не только наличие backup-файла.
- Условия источников и retention могут требовать удаления. Prediction ledger immutable логически, но legal erasure имеет приоритет: сохраняются разрешённые hash/provenance tombstones и отметка неполной воспроизводимости, а не запрещённый контент.

## 7. Целевая структура репозитория (не созданный код)

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
