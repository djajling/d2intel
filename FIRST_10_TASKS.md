# FIRST_10_TASKS.md — первые ровно 10 задач

**Тип документа:** краткий навигационный документ. **Полные карточки задач находятся только в `BACKLOG.md`** — здесь они не дублируются.
**Проект:** Dota Esports Intelligence Platform, solo-founder, только бесплатные источники, личный инструмент.
**Статус:** **10 из 10 задач выполнены** — вертикальный ретроспективный срез закрыт: `PRD-001`, `SRC-001`, `INF-001`, `DB-001`, `ING-001`, `DATA-001` (2026-09-21), `FEAT-001` (2026-09-22; в `main` с 2026-09-23), `ML-001` (2026-09-24), `API-001` (2026-09-25), `UI-001` (2026-09-26). Следующие задачи (MVP-слой: backfill покрытия, `ML-002`, `EVAL-001`, `ING-008`, гейт `G-OPS`) — по явной команде владельца.
**Основание:** `SOURCES.md`, `BACKLOG.md`.
**Смысл первых 10:** они дают **вертикальный РЕТРОСПЕКТИВНЫЙ прототип** (raw → нормализация → фичи as-of → baseline LR → immutable snapshot → простой локальный UI на реальной held-out исторической game1). Это **НЕ полноценный pre-match MVP**.

---

## 1. Список первых 10 задач (ID идентичны `BACKLOG.md`)

| № | TASK ID | TITLE | EPIC | PRIORITY | STATUS | DEPENDENCIES |
|---|---|---|---|---|---|---|
| 1 | `PRD-001` | Согласовать цель / первую карту / гейты / правила cutoff | 00 — Product specification | P0 | **Done** | — |
| 2 | `SRC-001` | Документированный bounded read-only audit: OpenDota history + Liquipedia legal/access/upcoming requirements; никакие credentials не выдумываются | 02 — Data ingestion | P0 | **Done** | `PRD-001` |
| 3 | `INF-001` | Воспроизводимый локальный скелет репозитория + smoke test (не фактическое выполнение здесь) | 01 — Repository and infrastructure | P0 | **Done** | `PRD-001`, `SRC-001` |
| 4 | `DB-001` | Минимальная ядровая temporal-схема + snapshots / migrations / constraints | 03 — Database | P0 | **Done** | `INF-001` |
| 5 | `ING-001` | OpenDota клиент + raw capture: sync-once, pagination, retry, quota, idempotence | 02 — Data ingestion | P0 | **Done** | `SRC-001`, `DB-001` |
| 6 | `DATA-001` | Нормализация исторических games / team / player / series, map index, participant stats, evidence roster versions, patch; карантин неоднозначного map1 | 03 — Database | P0 | **Done** | `ING-001` |
| 7 | `FEAT-001` | Минимальный prior-form датасет as-of для map1, **включая минимальные Team- и Player-prior-form**; coverage masks; режимы event vs observed | 05 — Team intelligence | P1 | **Done** | `DATA-001` |
| 8 | `ML-001` | Prior + Logistic Regression baseline: temporal group split, frozen heldout, Brier/logloss; research only, **CatBoost ещё нет** | 10 — Baseline ML | P1 | **Done** | `FEAT-001` |
| 9 | `API-001` | Prediction service: immutable snapshots + API + шаблонное evidence; enforcement меток historical vs real future; цель — только game1 | 12 — Prediction API | P1 | **Done** | `ML-001`, `DB-001` |
| 10 | `UI-001` | Простая локальная страница матча на реальной held-out исторической game1; явно ретроспектива (не «живой» прогноз); provenance / модель / версия / причины | 13 — Frontend MVP | P1 | **Done** | `API-001` |

**Порядок исполнения — строго по списку** (он уже топологически отсортирован: каждая задача зависит только от предыдущих).

**Что вертикальный срез доказывает, а что нет:**
- Доказывает: пайплайн способен пройти путь от сырых исторических данных до неизменяемого предсказания и показать его с провенансом, не нарушая временную семантику.
- **НЕ доказывает:** готовность к реальному pre-match прогнозу. Полноценный MVP требует легального upcoming-адаптера, свежести ростера, hero pool из истории, patch weighting + missing masks, CatBoost challenger (`ML-002`, ещё не обучен; победа над LR не обязательна), calibration freeze, оценки исходов (`EVAL-001`), **фактически работающего** автоматического обнаружения/ingestion в будущем локальном deployment (`ING-008`) и операционных/ML-гейтов (`MON-001`) (см. `BACKLOG.md`, §1 п.11 и Приложение A).

---

## 2. Текущий статус и точка решения

- **Текущий эпик:** `EPIC 13 — Frontend MVP` (first-10 закрыт).
- **Текущая задача:** prospective-контур: заморозка `ce679e76` активна (ждёт будущей game1 Na'Vi — Aurora; сегодняшний матч пары сыгран до cutoff и не связывается — см. `HANDOFF_PROMPT.md`).
- **Что уже сделано (по факту; детали и артефакты — в карточках `BACKLOG.md`):**
  - `PRD-001` — product spec v0 утверждена владельцем (`docs/PRD.md`): цель, первая карта, правила cutoff, гейты, non-goals.
  - `PRD-003` — временная семантика и снимки (`docs/PRD_TEMPORAL.md`, вариант A); `ADR-001` и `ADR-005` — Accepted.
  - `SRC-001` — вердикт гейта G-SRC (`docs/research/SRC_001_VERDICT.md`): **случай B** — история OpenDota PASS, легального бесплатного upcoming нет → работа ведётся в **ретроспективном контуре**, полноценный pre-match MVP не объявляется.
  - `INF-001` — скелет репозитория + smoke test + CI (`src/d2intel/` skeleton, `docker-compose.yml`, `.github/workflows/ci.yml`).
  - `DB-001` — ядровая temporal-схема, миграция `0001`, constraint-тесты.
  - `ING-001` — OpenDota-клиент + raw capture, миграция `0002` (`src/d2intel/ingestion/`, `scripts/ingest_opendota_once.py`).
  - `DATA-001` — нормализация исторического ядра, миграция `0003`, карантин неоднозначного map1 (`src/d2intel/normalize/`, `scripts/normalize_once.py`).
  - `FEAT-001` (2026-09-22) — prior-form датасет as-of для map1: Team/Player priors, coverage masks, режимы `event_asof`/`observed_mode_only_study` (`src/d2intel/features/prior_form.py`, контракт — `docs/FEATURE_DATASET.md`).
  - `ML-001` (2026-09-24) — prior + LR baseline: test accuracy 0.5649 (floor 0.5191), log_loss 0.6786; порог ADR-007 (0.70) не достигнут, повышение до champion — решение владельца (`scripts/run_lr_baseline.py`).
  - `API-001` (2026-09-25) — prediction service с immutable snapshots: `POST /predict/game/{game_id}`, только game1, режим `retrospective_reconstructed` (`src/d2intel/api/predict.py`, `snapshots.py`).
  - `UI-001` (2026-09-26) — server-rendered страница матча с ретро-меткой, провенансом и версией модели: `GET /match/{game_id}`, запись снимка явным `POST /match/{game_id}/predict` (`src/d2intel/web/`, Jinja2, без JS).
- **Следующее действие:** выбор следующего шага владельцем: backfill player-признаков → `ML-002` (CatBoost challenger по manifest-протоколу ADR-007) → `EVAL-001` → гейт `G-OPS`; либо `ING-008` (требует согласования расписания).
- **Далее: STOP.** Без команды владельца никакие задачи, включая `ML-001` и последующие, не начинаются. Ничего не запускается, не конфигурируется и не выполняется.

---

## 3. Блокер: если источник окажется no-go

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

## 4. Границы этого документа

- Нет кода, нет инструкций по запуску cron/recurring-задач, нет создания/конфигурирования автоматизации.
- Нет оценок сроков разработки и нет выдуманных метрик.
- Нет утверждений, что что-либо уже сделано.
- Полные карточки (GOAL / CONTEXT / INPUT / OUTPUT / ACCEPTANCE CRITERIA / TESTS / FILES EXPECTED TO CHANGE / RISKS / DEFINITION OF DONE) — **только в `BACKLOG.md`**.
- Приоритет не выводится из стадии: в `FUTURE` есть как `P2` (необходимые проверки/реализация: live, heatmaps, market, backtest, LLM, automation, deployment), так и `P3` (**только** спекулятивные направления: `SYN-004`, `DRAFT-005`).
