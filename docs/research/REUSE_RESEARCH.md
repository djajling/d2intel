# REUSE_RESEARCH.md — инструменты и reference-проекты для d2intel

**Дата:** 2026-09-21 · **Тип:** исследование (research only, не реализация)
**Статус:** справочный материал. Ничего не скопировано в код — кода ещё нет.
**Связь с бэклогом:** закрывает часть `SRC-001` (источники), информирует `INF-001` (стек) и `ML-001` (baseline).

---

## 1. Резюме

Главный вывод: ** готовых «кусков» для переиспользования меньше, чем кажется, но архитектурных образцов — достаточно.**

- Почти все найденные проекты — учебные/Kaggle-ноутбуки. Только два (`NUKI1223`, `amarcu`) — структурированные приложения, близкие к нашему плану.
- **Ни один reference-проект не реализует то, что является ядром d2intel**: immutable prediction snapshots, provenance ledger, as-of temporal semantics, явный cutoff. Это придётся писать самим — это и есть differentiator.
- Готовых Python-клиентов для OpenDota нет (все заброшены) → `ING-001` пишем сами, но лимиты API теперь известны точно.
- Upcoming-источник: Liquipedia **легально доступен**, но LiquipediaDB API требует **одобрения заявки** — это и есть `G-SRC` access gate.

---

## 2. Reference-проекты

| Проект | Язык | Лицензия | Близость к d2intel | Что можно взять |
|---|---|---|---|---|
| **[NUKI1223/dota-predictor](https://github.com/NUKI1223/dota-predictor)** | Python | **нет LICENSE** ⚠️ | ★★★★★ самая высокая | Архитектуру, подход к фичам, метрики. **Код копировать нельзя** |
| **[amarcu/dota-predictor](https://github.com/amarcu/dota-predictor)** | Python | **MIT** ✅ | ★★★★ | Отдельные компоненты после код-аудита |
| **[odota/core](https://github.com/odota/core)** (1626★) | TypeScript | — | ★★★ (ingestion/parsing) | Архитектуру ingestion, схему данных, SQL-слой |
| **[andreiapostoae/dota2-predictor](https://github.com/andreiapostoae/dota2-predictor)** (371★) | Python | — | ★★ | Простой LR/nn baseline |
| **[BCSZSZ/ti-2026-predictor](https://github.com/BCSZSZ/ti-2026-predictor)** | — | — | ★★ (исследование) | Актуальный аудит лимитов OpenDota (2026-08) |
| **[beeequeue/dota-matches-api](https://github.com/beeequeue/dota-matches-api)** | TypeScript | — | ★★★ (upcoming) | Логику извлечения upcoming-матчей из Liquipedia |

### 2.1 NUKI1223/dota-predictor — главный архитектурный образец

Стек из `pyproject.toml`: `httpx` ≥0.27, `pandas` ≥2.2, `pyarrow` ≥17, `scikit-learn` ≥1.5, `anthropic` ≥0.116, `fastapi` ≥0.115, `uvicorn`, `pytest`.

Что уже реализовано (по README):

- ingestion OpenDota: REST + bulk-выгрузки через `/explorer` SQL, кэш в `data/raw/`
- фичи: Elo, форма, драфты (винрейты героев, bag-of-heroes), мета патча/турнира, баны из `picks_bans`, составы/сыгранность/детектор стендинов
- модели: baseline → LR → CatBoost; калибровка Platt/isotonic + ECE + reliability-таблица
- временной сплит: train — прошлое, test — будущее
- метрики: accuracy / log loss / Brier; **лучший log loss 0.6465 (с Platt)**
- FastAPI: `/health`, `/teams`, `/predict`, `/preview` (LLM)
- live-трекер (`/live`) и in-game модель по золоту (163k срезов, log loss 0.49)
- сравнение с букмекерскими кэфами (снятие вилки нормализацией, симуляция флэт-ставок)

**Ключевое отличие от d2intel:** нет PostgreSQL (использует Parquet + файловый кэш), нет immutable snapshots/provenance ledger, нет явной маркировки retrospective vs live. Фичи считаются по всем матчам, обучение — по выбранным тирам.

**Вывод:** брать как **архитектурный референс и источник идей по фичам**, не как кодовую базу.

### 2.2 amarcu/dota-predictor — MIT, можно переиспользовать

Лицензия MIT (проверено в `LICENSE`, © 2025 Alexandru Marcu). Стек (`requirements.txt`): torch, numpy, pandas, scikit-learn, requests, aiohttp, pydantic, pytest, jupyter, matplotlib/seaborn.

Есть `gamestate_integration_predictor.cfg` — получение live-данных через GameState Integration (внутриигровой, для собственных/наблюдаемых матчей). Релевантно для `LIVE.md`, но **не** для pro-live без прав.

**Вывод:** точечно переиспользовать после код-аудита — как и предлагалось в `PRODUCT.md` §7.

---

## 3. Инструменты по слоям

### 3.1 Ingestion (OpenDota)

**Готовых клиентов нет.** Найденные: `pyOpenDota` (3★, 2022), `opendota-client` (0★, 2020) — оба заброшены.

→ **Пишем сами** (`ING-001`): `httpx` + rate limiter + retry с backoff/jitter + idempotence + raw capture.

Лимиты OpenDota (проверено по исходникам `odota/core` и `odota/web`, аудит 2026-08):

| Параметр | Free (без key) | Premium |
|---|---:|---:|
| API key | не нужен | нужен + привязанная карта |
| Цена | бесплатно | $0.01 / 100 вызовов |
| Дневной лимит | **3 000** | безлимит |
| Минутный лимит | **60** | 300 |
| Не тарифицируется | — | HTTP 404 / 429 / 500 |

Для личного инструмента free-tier достаточно (3 000/день). Проектировать клиент под 60 req/min, обрабатывать `429` по `Retry-After`, читать `X-Rate-Limit-Remaining-Minute` / `-Day`.

### 3.2 Upcoming-источник (Liquipedia) — условия

| Путь | Доступ | Лимиты | Требования |
|---|---|---|---|
| **LiquipediaDB API** (v3) | **по одобренной заявке** | 60 req/час | API key, не передавать третьим лицам |
| **MediaWiki API** | свободно | 1 req / 2 сек; `action=parse` 1 req / 30 сек | кастомный `User-Agent` с контактами, gzip, переиспользование HTTP-клиента |

Оба пути: контент **CC-BY-SA 3.0 → обязательна атрибуция Liquipedia**. Автоматический доступ к не-API (HTML) страницам **запрещён**.

Совместимо с правилами d2intel (без ToS-обход, без HTML-scraping). **Блокер:** LiquipediaDB требует заявки — это ручной шаг владельца, не автоматический.

Инструменты: `c00kie17/liquipediapy` (Python, 70★, но помечен `non-official`/`unsupported`), `beeequeue/dota-matches-api` (логика upcoming), `npldevfr/lpdb-ts-client` (v3, TypeScript).

### 3.3 Replay parsing (для LIVE / spatial — Future A/B)

| Парсер | Язык | ★ | Активность | Для нас |
|---|---|---|---|---|
| **gem-dota** | **Python** | 158 | обновлён今天 | ✅ лучший выбор под Python-стек |
| manta (Dotabuff) | Go | 689 | активен | альтернатива |
| clarity (skadistats) | Java | 767 | активен | самый быстрый |
| odota/parser | Java | 161 | активен | парсер OpenDota |

→ Для Python-монолита брать **`gem-dota`**. Но это Future-слой, за гейтом pro-live access.

### 3.4 Стек приложения (подтверждён практикой)

Уже выбрано в `ARCHITECTURE.md` / ADR-001, практика reference-проектов подтверждает:

- HTTP: **httpx** (NUKI1223) или requests/aiohttp (amarcu)
- Данные: **pandas + pyarrow** (Parquet для промежуточных/кэша), PostgreSQL для канонической модели
- ML: **scikit-learn** (LR baseline), **CatBoost** (challenger), калибровка Platt/isotonic
- API: **FastAPI + uvicorn**
- Валидация: **pydantic** (+ рассмотреть `pandera` для as-of валидации датасетов)
- Тесты: **pytest**
- LLM (Future D): `anthropic` SDK — только для объяснений, не как предиктор

---

## 4. Что переиспользовать / писать самим / отложить

**Переиспользовать (библиотеки):**
httpx, pandas/pyarrow, scikit-learn, CatBoost, FastAPI, pydantic, pytest, gem-dota (Future).

**Переиспользовать (компоненты, после аудита):**
точечные MIT-компоненты `amarcu` — по `PRODUCT.md` §7.

**Писать самим (ядро d2intel, нигде не готово):**
- каноническая модель данных + temporal identity/roster resolution (`DATA_MODEL.md`)
- **as-of evaluator** — вычисление признаков строго на cutoff
- **immutable prediction snapshots + provenance ledger**
- feature contracts и карантин неоднозначных данных
- властный calibration/backtest протокол
- OpenDota-клиент с rate limiting и идемпотентностью

**Отложить:**
live, spatial/heatmaps, market/backtest, expert ingestion — до своих гейтов. Redis/Kafka/Kubernetes/feature store — до измеренного bottleneck.

---

## 5. Риски и ограничения

1. **Лицензии.** `NUKI1223` без LICENSE → код копировать нельзя, только идеи/архитектура. `amarcu` = MIT ✅. Перед любым заимствованием — код-аудит и ADR.
2. **Reference ≠ корректная временная семантика.** Проекты считают фичи «по всем матчам», без as-of и без snapshot-учёта. Переносить这样的 фичи в d2intel без переработки = утечка (leakage).
3. **LiquipediaDB API требует заявки.** Без одобрения upcoming-путь закрыт → по `FIRST_10_TASKS.md` §3, случай B: остаёмся в ретроспективном прототипе.
4. **OpenDota free-tier 3 000/день.** Достаточно для личного инструмента, но bulk-историю через `/explorer` нужно планировать порциями.
5. **CC-BY-SA 3.0 атрибуция** обязательна при использовании Liquipedia-данных.

---

## 6. Следующие шаги

Этот отчёт — исследование. По протоколу проекта:

- Информация закрывает значительную часть `SRC-001` (аудит OpenDota + Liquipedia), но **официальный вердикт по гейту `G-SRC` принимает владелец вручную**.
- `PRD-001` всё ещё `Proposed` — до его утверждения ни `INF-001`, ни последующие задачи не начинаются.
- Рекомендуемая последовательность: утвердить `PRD-001` → оформить вердикт `SRC-001` (включая заявку на LiquipediaDB API, если нужен upcoming) → `INF-001` (реальный скелет репозитория).

---

_Dокумент создан как результат исследования. Не является разрешением на реализацию._
