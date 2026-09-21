# SCHEMA — физическая схема БД (DB-001)

**Статус:** реализовано в миграциях `0001` (ядро) и `0002` (ingestion cursor/quarantine, ING-001)
**Основание:** `docs/PRD_TEMPORAL.md` (`PRD-003`), `DATA_MODEL.md`, `ADR-001` (Accepted), `ADR-005` (Accepted)

Реализуется **только используемое ядро MVP**. Сущности стадий 2/3/F из `DATA_MODEL.md`
здесь намеренно отсутствуют и появляются со своими задачами.

---

## 1. Отклонение от карточки BACKLOG

Карточка `DB-001` указывала файлы `migrations/0001_*.sql`. `INF-001` зафиксировал
инфраструктуру миграций **Alembic** с `script_location = alembic`, поэтому миграция
создана как Alembic-ревизия `0001` в `alembic/versions/`, а SQL-инструкции
выполняются внутри неё через `op.execute`. Смысл и состав не изменены, путь
приведён к фактической инфраструктуре.

---

## 2. Слои

| Слой | Таблицы | Хранение |
|---|---|---|
| Raw | `data_source`, `ingestion_run`, `raw_payload`, `source_observation` | `payload_json` — JSONB; остальное типизировано |
| Ingestion state (ING-001) | `ingestion_cursor`, `ingestion_quarantine` | курсор — JSONB-состояние пагинации; карантин — типизированная причина + JSONB непригодной строки |
| Canonical | `team`, `player`, `tournament`, `series`, `game`, `game_team`, `game_participant` | типизированные колонки, PK/FK/индексы |
| Снимки | `model_version`, `feature_snapshot`, `prediction`, `prediction_snapshot`, `snapshot_evidence`, `prediction_evaluation` | payload/состояние — JSONB, связи — типизированные FK |

JSONB встречается **только** там, где payload по природе переменный:
`raw_payload.payload_json`, `feature_snapshot.values_json`, `coverage_json`,
`roster_evidence`, `hyperparameters`, `tier_evidence`. Ключевые canonical-поля
(имена, id, номера карт, стороны, связи) — типизированы.

---

## 3. Временной конверт

На всех версионируемых таблицах присутствуют пять полей из `docs/PRD_TEMPORAL.md`:

```
event_time            timestamptz  -- NULL допустим
source_published_at   timestamptz  -- NULL допустим
observed_at           timestamptz  NOT NULL
ingested_at           timestamptz  NOT NULL
available_at          timestamptz  NOT NULL
system_from           timestamptz  NOT NULL
system_to             timestamptz  NULL -- открытая системная версия
```

Таблица `feature_snapshot` дополнительно несёт `assumed_available_at` и
`lag_policy_version` — для режима `retrospective_reconstructed`.

### Constraint'ы на временной порядок

| Constraint | Проверка |
|---|---|
| `*_temporal_order` | `observed_at <= ingested_at AND ingested_at <= available_at` |
| `*_system_interval` | `system_to IS NULL OR system_from < system_to` |
| `ingestion_run_interval` | `finished_at IS NULL OR finished_at >= started_at` |

Это прямой запрет противоречивого порядка временных полей (AC #5).

---

## 4. Неизменяемость снимков (ADR-005)

Функция `d2intel_forbid_snapshot_mutation()` и триггеры `BEFORE UPDATE OR DELETE`
установлены на:

- `model_version`
- `feature_snapshot`
- `prediction_snapshot`
- `snapshot_evidence`

Любая попытка `UPDATE`/`DELETE` вызывает исключение с SQLSTATE `restrict_violation`.
Исправление ошибки = новая запись, старая не перезаписывается.

---

## 5. Прочие constraint'ы

| Constraint | Смысл |
|---|---|
| `raw_payload_content_unique` | дедупликация raw по `(source_id, content_hash)` |
| `ingestion_cursor_unique` | `UNIQUE (source_id, endpoint_kind)` — один watermark на endpoint |
| `ingestion_quarantine_unique` | `UNIQUE (source_id, content_hash, reason_code)` — повторный карантин не дублируется |
| `ingestion_quarantine_reason_present` | причина карантина не может быть пустой |
| `ingestion_quarantine_status` | статус только `open` / `resolved` |
| `game_map_attempt_unique` | `UNIQUE (series_id, map_number, attempt_number)` |
| `game_team_slot_unique`, `game_team_side` | слот уникален; сторона только radiant/dire |
| `game_participant_player_unique`, `*_slot_unique` | игрок и слот уникальны в карте |
| `feature_snapshot_target_xor` | ровно один из `target_game_id` / `target_series_id` |
| `feature_snapshot_mode` | только `retrospective_reconstructed` / `prospective_observed` |
| `feature_snapshot_lag_policy` | реконструкция обязана нести `lag_policy_version`; проспективный режим не использует `assumed_available_at` |
| `prediction_target_xor` | ровно один target (typed FK вместо polymorphic integer) |
| `prediction_teams_distinct` | Team A ≠ Team B |
| `prediction_request_key_unique` | стабильный ключ запроса |
| `prediction_snapshot_seq_unique` | `UNIQUE (prediction_id, snapshot_seq)` |
| `prediction_snapshot_idem_unique` | идемпотентность повторного расчёта |
| `prediction_snapshot_probability` | либо обе вероятности, либо abstention с причиной |
| `snapshot_evidence_role` | роль только `source` / `feature` / `attribution` |
| `prediction_evaluation_unique` | `UNIQUE (snapshot_id, result_revision_id, metric_definition_version)` |

---

## 6. Индексы

`raw_payload(source_id)`, `source_observation(raw_payload_id)`, `game(series_id)`,
`game_team(game_id)`, `game_participant(game_id)`, `feature_snapshot(cutoff_at)`,
`prediction_snapshot(prediction_id)`, `prediction_evaluation(snapshot_id)`,
`ingestion_cursor(source_id)`, `ingestion_quarantine(run_id)`, `ingestion_quarantine(source_id)`,
`ingestion_quarantine(reason_code)`.

---

## 7. Как применять

```bash
export DATABASE_URL=postgresql+psycopg://d2intel:d2intel_dev@localhost:5432/d2intel
alembic upgrade head     # применить
alembic downgrade base   # откатить (обратимо)
alembic current          # текущая ревизия
```

Миграции обратимы и воспроизводимы: round-trip `downgrade base -> upgrade head`
проверяется тестом `tests/test_migrations.py::test_migrations_are_reversible`.

---

## 8. Тесты

| Тест | Проверяет |
|---|---|
| `test_migrations_create_expected_tables` | миграции с нуля создают ядро |
| `test_migrations_are_reversible` | round-trip downgrade/upgrade |
| `test_temporal_envelope_present_on_versioned_tables` | пять временных полей на месте |
| `test_canonical_tables_are_typed_not_jsonb` | canonical типизирован |
| `test_snapshot_payload_is_jsonb` | payload снимков — JSONB |
| `test_no_forbidden_components_in_migrations` | нет Redis/Celery/Kafka/K8s/MLflow/Feast |
| `test_temporal_order_violation_rejected` | нарушение порядка времён отклоняется |
| `test_observed_after_ingested_rejected` | то же, вторая грань |
| `test_snapshot_update_forbidden` | UPDATE снимка запрещён |
| `test_snapshot_delete_forbidden` | DELETE снимка запрещён |
| `test_prediction_snapshot_update_forbidden` | неизменяемость prediction_snapshot |
| `test_retrospective_requires_lag_policy` | реконструкция без политики задержки запрещена |
| `test_prospective_must_not_set_assumed_availability` | проспективный режим не использует assumed |
| `test_prediction_requires_distinct_teams` | Team A ≠ Team B |
| `test_prediction_target_xor_enforced` | XOR для typed FK target |
| `test_raw_payload_deduplicated_by_content_hash` | дедупликация raw |

Тесты миграций работают с **отдельной** БД `d2intel_test`
(`D2INTEL_TEST_DATABASE_URL`), потому что `downgrade base` разрушителен.

---

## 9. Дополнение ING-001 (миграция `0002`)

Миграция `alembic/versions/0002_ingestion_cursor_and_quarantine.py` добавляет две
таблицы, требуемые механизмами `ING-001` (ARCHITECTURE.md §3, пп. 4–6). Она
аддитивная и обратимая; `0001` не изменяется.

| Таблица | Назначение | Особенности |
|---|---|---|
| `ingestion_cursor` | watermark пагинации (`cursor_value`, `cursor_payload`, `last_run_id`) | обновляется **только после** commit raw-данных; `UNIQUE (source_id, endpoint_kind)` |
| `ingestion_quarantine` | карантин непригодных строк с отдельной data-quality причиной | `reason_code` обязателен; временной конверт присутствует; сырьё остаётся в `raw_payload` |

**Почему у `ingestion_cursor` нет временного конверта.** Это operational checkpoint
(состояние обхода), а не версия факта источника: у него нет `event_time` и
`observed_at` в смысле `docs/PRD_TEMPORAL.md`. Наблюдения источника фиксируются
отдельно — в `source_observation` и `raw_payload`.

**Карантин не удаляет данные.** Строка остаётся в `raw_payload`; карантин хранит
`reason_code`, `reason_detail`, `request_fingerprint`, `content_hash` и сам
`offending_payload`, чтобы разбор не требовал повторного запроса к источнику.

Тесты: `tests/ingestion/test_raw_capture.py` (запись, идемпотентность, карантин,
watermark после commit), `tests/ingestion/test_schema_contract.py` (schema drift).
