# Dota Esports Intelligence Platform — d2intel

**Статус:** ядро `PRD-001` → `DATA-001` реализовано. На 2026-09-22 локальный FastAPI запущен на компьютере владельца, `/health` возвращает HTTP 200 и `database: up`; схема БД — `0003`. Это запуск ядра, не готовый продукт: данных, UI и прогнозирования пока нет. Оставшиеся задачи first-10 (`FEAT-001` → `UI-001`) — `Planned`, старт только по команде владельца.

**Для нового агента:** [AGENTS.md](AGENTS.md) → [актуальное состояние и блокеры](HANDOFF_PROMPT.md) → [Git и локальный деплой](REPO_SETUP.md). Передавать историю чата не нужно. Запуск не означает зелёный CI: известные ошибки проверок перечислены в передаче.

Условия владельца: solo-founder, только бесплатные источники данных, личный исследовательский инструмент. Дата пакета: 2026-09-16 (Asia/Singapore; часы инструмента). Условия API и сведения репозиториев — срез исследования, не гарантия будущей доступности.

## Начать здесь

1. [Product Vision, границы и gates](PRODUCT.md) — что строим и что считается работающим результатом.
2. [Первые 10 задач](FIRST_10_TASKS.md) — ближайший последовательный маршрут.
3. [Полный backlog](BACKLOG.md) — все EPIC 00–22, полные карточки, зависимости, критерии и DoD.
4. [Источники и reference-проекты](SOURCES.md) — OpenDota, STRATZ, Valve/Steam, Liquipedia, PandaScore, replay/expert источники, NUKI1223/dota-predictor и amarcu/dota-predictor; verified/docs/unknown различаются.

## Архитектура

| Документ | Содержание |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Модульный монолит, stack, ingestion, событийность, API/UI, эксплуатация, будущая структура repo |
| [DATA_MODEL.md](DATA_MODEL.md) | Все запрошенные сущности, дополнительные evidence/identity/time сущности, cardinalities, FK/uniqueness, snapshots |
| [FEATURES.md](FEATURES.md) | Team/Player/Patch/Draft/Tournament/Synergy и формальные определения style metrics |
| [ML.md](ML.md) | Baseline/challenger, temporal splits, leakage, calibration, evaluation и ensemble gates |
| [EXPERT_ENGINE.md](EXPERT_ENGINE.md) | Права, transcripts, extraction, экспертные claims, track record, consensus, LLM analyst |
| [LIVE.md](LIVE.md) | Live access, state/time parity, trajectory, heatmaps и spatial features |
| [BACKTEST.md](BACKTEST.md) | Market architecture, no-vig/edge/EV, simulator, ROI/CLV/drawdown, ANALYSIS-only ограничения |

## Предлагаемые ADR

- [ADR-001: database](docs/adr/ADR-001-database.md)
- [ADR-002: initial data provider](docs/adr/ADR-002-initial-data-provider.md)
- [ADR-003: ML baseline](docs/adr/ADR-003-ml-baseline.md)
- [ADR-004: temporal validation](docs/adr/ADR-004-temporal-validation.md)
- [ADR-005: prediction snapshots](docs/adr/ADR-005-prediction-snapshots.md)

`ADR-001` (database) и `ADR-005` (prediction snapshots) — **Accepted** (утверждены владельцем 2026-09-21, реализация — `DB-001`); `ADR-002`…`ADR-004` — Proposed. Product spec v0 (`docs/PRD.md`) и временная семантика (`docs/PRD_TEMPORAL.md`) утверждены владельцем. Внутренние task IDs ссылаются на BACKLOG.md; для выполненных задач пути FILES EXPECTED TO CHANGE соответствуют реально созданным файлам.

## Главные выводы

- Первый вертикальный срез — **ретроспективный** прототип на реальных game1, не выдуманный исторический live forecast.
- Полный MVP требует проверенного бесплатного upcoming-источника, фактически работающего локального автоматического ingestion, known-roster/fallback и честной prospective оценки.
- OpenDota history — основной кандидат; Liquipedia API upcoming — условный до access/rights/coverage gate; PandaScore не включён без разрешения для сценария с market-анализом.
- Prediction/Feature snapshots и temporal lineage нужны сразу; CatBoost — challenger, не обязательный победитель LR.
- Live/heatmaps/expert/market доступны только по своим gates; отсутствие данных нельзя заменить уверенными обещаниями.

## Рабочий протокол AI coding assistant

Выбрать назначенную задачу → прочитать инструкции/код → план → тесты и реализация → проверки → review → обновить передачу в Git → commit и push в согласованную ветку → локальный запуск/обновление и проверка health. Подробные правила — в `AGENTS.md`. Архитектурная проблема: STOP → объяснение → альтернативы → решение владельца. Backlog сам по себе не разрешает начинать новые задачи.

**CURRENT EPIC:** EPIC 05 — Team intelligence. **CURRENT TASK:** FEAT-001. **WHY IT MATTERS:** первый as-of датасет prior-form признаков для map1 — без него нет baseline (`ML-001`) и API/UI вертикального среза. **DEPENDENCIES:** `DATA-001` (Done). **NEXT ACTION:** команда владельца на запуск FEAT-001; затем по first-10 маршруту до UI-001.

Расписание ingestion и автозапуск приложения не настроены. Возможности среды каждого агента проверяются заново; репозиторий не создаёт автоматизации помощника.

## Локальный запуск

Работают инфраструктурный API, миграции `0001`–`0003`, raw ingestion и нормализация. Feature/model/UI-слои ещё не реализованы. Для Windows и текущей БД использовать [REPO_SETUP.md](REPO_SETUP.md); ниже — исходный Bash-вариант для новой dev-среды с Docker. Полные тесты разрешены только в отдельной тестовой БД.

```bash
# 1. Виртуальное окружение и pinned-зависимости (воспроизводимо)
python3.11 -m venv .venv && . .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt -r requirements-dev.txt
pip install -e .

# 2. Поднять PostgreSQL (локально, порт 5432 только на 127.0.0.1)
cp .env.example .env        # при необходимости переопределить DATABASE_URL
docker compose up -d
docker compose ps           # дождаться состояния db: healthy

# 3. Тесты (smoke должен быть зелёным)
pytest

# 4. API
uvicorn d2intel.app:app --reload --port 8000
curl -s http://127.0.0.1:8000/health   # {"status":"ok","database":"up",...}

# 5. Остановить
docker compose down        # без -v: сохранить данные
```

## Схема БД (DB-001)

Temporal-схема ядра создаётся миграцией `0001` (Alembic). Описание — [`docs/SCHEMA.md`](docs/SCHEMA.md),
семантика времён — [`docs/PRD_TEMPORAL.md`](docs/PRD_TEMPORAL.md) (`PRD-003`).

```bash
export DATABASE_URL=postgresql+psycopg://d2intel:d2intel_dev@localhost:5432/d2intel
alembic upgrade head     # применить
alembic downgrade base   # откатить (обратимо)
```

Миграционные тесты destructive (`downgrade base`), поэтому работают с отдельной БД
`d2intel_test`, задаваемой через `D2INTEL_TEST_DATABASE_URL`.

## Нормализация исторического ядра (DATA-001)

Поверх raw-слоя (`ING-001`) работает нормализация: серии, карты, номер карты,
участники, финальная статистика и свидетельства состава. Правила —
[`docs/NORMALIZATION.md`](docs/NORMALIZATION.md), схема — миграция `0003`.

```bash
python scripts/ingest_opendota_once.py --pages 1   # сначала raw
python scripts/normalize_once.py                   # затем canonical (идемпотентно)
```

Неоднозначный map1 не попадает в датасет: карта пишется с `map_number = NULL`
и уходит в `normalization_quarantine`.

