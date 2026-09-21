# Структура репозитория (REPO_LAYOUT)

**Статус:** действующее описание. Дата: 2026-09-21. Владелец: solo-founder.
**Связано:** `ARCHITECTURE.md` §7 (целевая структура), `BACKLOG.md` → `INF-001`, `REPO_SETUP.md`.

Этот документ закрывает acceptance criterion #1 карточки `INF-001` («структура покрывает
ingestion/storage/features/models/api/frontend/docs») **документом**, а не созданием пустых
каталогов. Правило зафиксировано ниже и обязательно для всех последующих задач.

---

## 1. Базовое правило

> **Каталог создаётся только тогда, когда в нём появляется код.**
> Пустые каталоги, `README`-заглушки и абстракции под будущие слои **не создаются заранее**.

Основание: `ARCHITECTURE.md` §7 — «Не создавать пустые сервисы и абстракции Future заранее.
Границы модулей — возможность замены источников и контроля leakage, не микросервисы».

Следствия:

- Future-слои (`experts/`, `live/`, `market/`, `backtest/`, `frontend/`) появятся только **после
  прохождения своих гейтов** (`G-LIVE`, `G-HM`, `G-MARKET`, `UI-001`) и только с кодом внутри.
- Миграции схемы БД пишет `DB-001`; до неё `alembic/versions/` **намеренно пуст**.
- Модуль считается существующим, когда в нём есть импортируемый модуль и тест, а не когда
  создана папка.

---

## 2. Текущая структура (после `INF-001`)

```text
d2intel/
  README.md  PRODUCT.md  ARCHITECTURE.md  DATA_MODEL.md
  FEATURES.md  ML.md  EXPERT_ENGINE.md  LIVE.md  BACKTEST.md
  SOURCES.md  BACKLOG.md  FIRST_10_TASKS.md  REPO_SETUP.md
  AGENT_INF001.md  AGENT_ING001.md          # пакеты задач для агентов-исполнителей
  .env.example                              # дефолты, секретов нет
  .github/workflows/ci.yml                  # ruff + mypy + pytest, postgres как service
  docker-compose.yml                        # локальный PostgreSQL 17.4, порт только 127.0.0.1
  pyproject.toml                            # конфиги ruff/mypy/pytest; зависимости — в requirements.txt
  requirements.txt  requirements-dev.txt    # pinned
  alembic.ini  alembic/                     # инфраструктура миграций; версий пока нет (DB-001)
  scripts/                                  # одноразовые entrypoints
  src/d2intel/                              # пакет приложения (см. §3)
    __init__.py  app.py  config.py  db.py
    api/
      __init__.py  health.py
  tests/
    test_smoke.py
  docs/
    REPO_LAYOUT.md        # этот файл
    research/             # SRC-001, карты API
    agent/                # формат делегирования
```

Доменной логики (ingestion / normalization / features / models / prediction) в `src/` **нет** —
это задачи `DB-001`, `ING-001`, `DATA-001`, `FEAT-001`, `ML-001`.

---

## 3. Решение по раскладке кода (зафиксировано владельцем 2026-09-21)

`ARCHITECTURE.md` §7 показывает плоскую схему `src/{ingestion,normalization,features,models,prediction,api}`.
Реализация `INF-001` использует **src-layout с корневым пакетом проекта** `src/d2intel/`:

```text
src/d2intel/
  config.py  db.py  app.py                  # инфраструктура
  api/                                      # HTTP-слой
  ingestion/  normalization/  features/     # появятся в ING-001 / DATA-001 / FEAT-001
  models/  prediction/                      # появятся в ML-001 / API-001
```

Причины: изолирует код от корня репозитория, даёт один импортируемый пакет (`import d2intel.*`),
упрощает `mypy`/`pytest` (`pythonpath = ["src"]`) и исключает случайный импорт из рабочего
каталога. Отклонение от §7 **обратимо** (переезд — это перемещение одного каталога) и не влияет
на временную семантику.

**Статус:** принято. Текст `ARCHITECTURE.md` §7 остаётся исторической целью и будет приведён к
факту отдельной правкой по решению владельца; до этой правки действует настоящий документ.

---

## 4. Целевая структура (когда появятся соответствующие задачи)

| Каталог | Задача-владелец | Гейт |
|---|---|---|
| `src/d2intel/ingestion/` | `ING-001` и далее | `G-SRC` пройден |
| `src/d2intel/normalization/` | `DATA-001` | — |
| `src/d2intel/features/` | `FEAT-001` | — |
| `src/d2intel/models/` | `ML-001` | `G-MODEL` |
| `src/d2intel/prediction/` | `API-001` | — |
| `src/d2intel/experts/` | EPIC 14 | — |
| `src/d2intel/live/` | EPIC 16 | `G-LIVE` |
| `src/d2intel/market/` | EPIC 17 | `G-MARKET` |
| `src/d2intel/backtest/` | EPIC 18 | — |
| `frontend/` | `UI-001` | — |
| `alembic/versions/` | `DB-001` | — |

Пока задача не начата — каталога нет. Это нормальное состояние, а не «недоделка».

---

## 5. Инварианты, которые нельзя нарушать при росте структуры

1. **Временная семантика.** Ни один признак не использует данные с `available_at > cutoff`.
   Ни один модуль не читает финальные статистики и фактический ростер до матча.
2. **Снапшоты и провенанс.** Prediction/feature snapshots неизменяемы; у каждого артефакта —
   версия, вход и cutoff.
3. **Запрещённые компоненты.** Redis, Celery, Kafka, Kubernetes, feature store, MLflow не входят
   в critical path (`ARCHITECTURE.md` §2). Проверяется тестом `tests/test_smoke.py`.
4. **Только бесплатные источники.** Никакого HTML-scraping; лицензии и атрибуция (CC-BY-SA 3.0
   для Liquipedia) соблюдаются.
5. **Секреты не коммитятся.** Ключи появляются только через `.env` (в `.gitignore`); файлы
   `.env.example` содержат пустые или локальные дефолты.
6. **Доменная логика не заходит в инфраструктурные модули** (`config.py`, `db.py`) и наоборот.
