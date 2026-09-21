# Dota Esports Intelligence Platform — архитектурный пакет

**Статус: предложения для согласования. Кода приложения нет; ничего не запущено, не развёрнуто и не опубликовано.**

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

Все ADR — Proposed. Владелец ещё не одобрял ни target первой карты, ни stack, ни gates. Внутренние task IDs ссылаются на BACKLOG.md; пути FILES EXPECTED TO CHANGE — будущие файлы, не утверждение, что код уже создан.

## Главные выводы

- Первый вертикальный срез — **ретроспективный** прототип на реальных game1, не выдуманный исторический live forecast.
- Полный MVP требует проверенного бесплатного upcoming-источника, фактически работающего локального автоматического ingestion, known-roster/fallback и честной prospective оценки.
- OpenDota history — основной кандидат; Liquipedia API upcoming — условный до access/rights/coverage gate; PandaScore не включён без разрешения для сценария с market-анализом.
- Prediction/Feature snapshots и temporal lineage нужны сразу; CatBoost — challenger, не обязательный победитель LR.
- Live/heatmaps/expert/market доступны только по своим gates; отсутствие данных нельзя заменить уверенными обещаниями.

## Рабочий протокол AI coding assistant

Выбрать одну задачу → прочитать архитектуру/связанный код → объяснить план → написать тесты → реализовать → запустить тесты → review → обновить документацию → commit в согласованном репозитории. Архитектурная проблема: STOP → объяснение → альтернативы → решение владельца. Никакие шаги реализации не выполняются по этому документу автоматически.

**CURRENT EPIC:** EPIC 00 — Product specification. **CURRENT TASK:** PRD-001. **WHY IT MATTERS:** зафиксировать target первой карты, scope и измеримые gates до сбора и обучения. **DEPENDENCIES:** нет. **NEXT ACTION:** решение владельца по предложениям PRODUCT.md; затем SRC-001 только по команде.

В этой среде scheduled/recurring tasks недоступны. Пакет описывает требования будущего локального продукта, не создаёт автоматизации помощника.

## Локальный запуск (INF-001)

Минимальный воспроизводимый скелет: PostgreSQL через Docker Compose, FastAPI
health-эндпоинт, smoke-тест. Доменной логики и миграций схемы нет — они за
DB-001 / ING-001 / DATA-001 / FEAT-001 / ML-001.

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
docker compose down        # -v удалить том с данными
```

