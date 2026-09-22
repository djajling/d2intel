# Прогон на реальном срезе — 2026-09-22

Run manifest для первого реального наполнения БД. Никаких метрик качества модели
здесь нет и быть не может: модель ещё не обучена.

## Цель

Получить реальный (не синтетический) исторический срез в canonical-слое, чтобы
`FEAT-001` и последующие задачи имели данные. До прогона все таблицы были пусты
(`alembic_version = 0003`, 0 строк во всех таблицах).

## Окружение

- Python 3.13.14; venv `~/.workbuddy-ai/binaries/python/envs/d2intel`
- SQLAlchemy 2.0.54, alembic 1.20.0, psycopg 3.3.6, httpx 0.28.1, pandas 3.0.6,
  scikit-learn 1.9.1, fastapi 0.141.1, pydantic 2.13.5, pytest 9.1.1, ruff 0.16.8, mypy 2.3.1
- PostgreSQL 17.10, локально `127.0.0.1:5432`, БД `d2intel`
- `DATABASE_URL=postgresql+psycopg://d2intel:d2intel_dev@127.0.0.1:5432/d2intel`

## Шаг 1 — ingestion (ING-001)

```bash
python scripts/ingest_opendota_once.py --pages 10
```

| Поле | Значение |
|---|---|
| run_id | `eb278083-6316-4852-a330-0146c3e762ac` |
| запросов | 10 (из 3000/день, 60/мин) |
| endpoint | `/api/proMatches` |
| records | 844 |
| quarantined | 156 (причина `null_team_identity`) |
| raw_inserted | 10 |
| cursor_after | `8918779289` |
| status | `partial` (есть карантин) |

## Шаг 2 — нормализация (DATA-001)

```bash
python scripts/normalize_once.py
```

| Сущность | Создано |
|---|---|
| game | 844 |
| game_team | 1688 |
| series | 406 |
| team | 187 |
| tournament | 17 |
| patch | 0 (справочник ещё не загружен) |

Карантин: `incomplete_series` 412, `unknown_series_type` 36, `inconsistent_series_teams` 2.

## Шаг 3 — справочник патчей

```bash
python scripts/ingest_patch_constants.py     # 1 запрос /api/constants/patch
python scripts/normalize_once.py             # created_patches = 61
```

60 наблюдений записано, 1 запись в карантине (`id = 0`, патч 6.70 справочника).

## Шаг 4 — дозаполнение `game.patch_id`

```bash
python scripts/backfill_game_patch.py
```

`candidates=844, resolved=844, unresolved=0, patch_id_null_after=0`.

`patch_id` — **производный** атрибут (патч, действовавший в `event_time`), а не
наблюдаемый факт, поэтому дозаполнение NULL не переписывает наблюдение. Семантика
совпадает с `normalize.pipeline._resolve_patch`. Неизменяемые снимки не затронуты.

## Профиль среза (факты)

| Показатель | Значение |
|---|---|
| Диапазон дат игры | 2026-07-29 … 2026-09-22 (~8 недель) |
| Всего карт | 844 |
| `map_number = 1` (кандидаты в game1) | **162** |
| `map_number IS NULL` (`map_index_unresolved`) | 450 |
| `status = completed` / `map_index_unresolved` | 394 / 450 |
| `result_type` | `played` — 844 |
| Победитель известен | 844 (0 NULL) |
| Команд | 187; с ≥5 карт — 88 |
| Карт на команду (среднее) | 9.0 |

## Чего в срезе НЕТ (важно для FEAT-001/ML-001)

- **Игроки и ростеры**: `player`, `player_performance`, `roster_membership` пусты —
  `/api/proMatches` не отдаёт состав. Нужен `/api/matches/{match_id}` (отдельная задача).
- **Драфт**: `picks_bans` не загружались. Draft — стадия 2, до неё target считается
  до драфта.
- **История до окна**: срез охватывает ~8 недель, у части команд не будет наблюдений
  раньше cutoff → признаки формы обязаны отдавать `null`/маску, а не «0».

## Проверки

- `ruff check src tests scripts` → All checks passed
- `mypy src` → Success, 24 source files
- `pytest -q` → **259 passed**

## Воспроизведение

Прогон идемпотентен: повторный `normalize_once` не создаёт дублей, повторный
`ingest_patch_constants` пишет то же наблюдение. Курсор `/api/proMatches`
продвигается вперёд, поэтому следующий прогон продолжит с `8918779289`.
