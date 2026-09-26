# Актуальная передача проекта между агентами

**Обновлено: 2026-09-27.** Это состояние репозитория `djajling/d2intel`, а не промпт для ручного переноса из чата. Начать с [AGENTS.md](AGENTS.md), затем читать этот файл. `HANDOFF.md` — архив, не источник текущих назначений.

---

## Что это за проект

Dota Esports Intelligence Platform — solo-founder проект: локальная исследовательская система для воспроизводимой аналитики профессиональной Dota 2. Центральный продуктовый слой — вероятность исхода с сохранением того, что было известно на cutoff, версии модели и последующей проверкой.

**Ограничения владельца:** только бесплатные источники; личный исследовательский инструмент; LLM не является математическим предиктором; модель не обещает прибыль. Бесплатного легального источника upcoming-расписания для автоматического предматчевого продукта не подтверждено.

## Актуальный код и локальный UI

Runtime-контур в репозитории включает ingestion, canonical normalization, as-of prior-form features, Logistic Regression baseline, immutable prediction service и локальную UI-рабочую область в `site/`.

- FastAPI раздаёт рабочую область на `/`; `GET /health`, `/docs`, `/predict/game/{game_id}` и `/api/*` остаются доступны отдельно.
- Dashboard API read-only: `GET /api/overview`, `GET /api/matches`, `GET /api/predictions`, `GET /api/predictions/{snapshot_id}`. Из UI новый расчёт отправляется только в существующий prediction service.
- В таблицу матча попадают только завершённые **сыгранные** game1 с известным победителем и resolved/distinct teams; фальсифицированного future/upcoming календаря нет.
- «Новый расчёт» требует существующего локального model artifact и явного подтверждения. Каждый вызов создаёт новый immutable snapshot; старые не перезаписываются.
- Режим расчёта по исторической игре всегда подписан `retrospective_reconstructed`. Он **не** был сделан до игры. `prospective_observed` показывается отдельно.
- Журнал отображает последние 100 snapshots, режимы, результат/оценку; полные признаки загружаются отдельным endpoint при открытии карточки. Неизвестные признаки остаются неизвестными.
- Адаптивная навигация/таблицы, поиск команды/турнира, pagination, обновление, confirmation/detail dialogs, keyboard shortcut `/`, reduced-motion и явные состояния недоступного API/model.

## Последнее изменение (2026-09-27): API-backed workbench + prediction journal

Продолжение 2026-09-27 в локальной рабочей копии `main` от `69b4e23`: целевой проект подтверждён владельцем как `djajling/d2intel` (не первоначальная ссылка `svoya`). Остальные незакоммиченные изменения в checkout уже существовали к началу текущего продолжения; работа шла поверх них, без reset/commit/push.

- `site/index.html`, `site/app.js`, `site/styles.css`: журнал получил поиск по команде/турниру/ID, фильтры по режиму, оценке и abstention, CSV-экспорт с защитой от spreadsheet formula injection, метрики log loss/Brier только по снапшотам с метриками и отдельно для retrospective/prospective когорт, отображение явных abstention без ложных 0% и mobile-полировку контролов.
- `src/d2intel/api/dashboard.py`: список матчей возвращает причину abstention последнего снимка для честного preview; `tests/api/test_dashboard.py` покрывает query response.
- `tests/test_workbench_assets.py`: безопасные статические regression-проверки контрактов controls, разделения когорт и CSV-полей.
- `site/README.md`: актуализированы возможности и безопасные проверки.
- Уточнение метрик: оценённые исходы без конкретного `log_loss`/`brier` входят в `n` исходов, но не в размер соответствующего среднего; небольшая selectable-журнальная выборка не является frozen model benchmark.

Проверки продолжения: `pytest tests/api/test_dashboard.py tests/test_workbench_assets.py tests/test_smoke.py` — 18 passed; targeted `ruff check src/d2intel/api/dashboard.py tests/api/test_dashboard.py tests/test_workbench_assets.py` — clean; `mypy src/d2intel/api/dashboard.py` — clean; `node --check site/app.js` и `git diff --check` — clean. `tests/test_workbench_assets.py` — новый untracked файл (статус `??`, поэтому `git diff --numstat` его не отображает). DB integration / actual browser preview / real local server не выполнены. Из-за токена, случайно попавшего в командный вывод `git remote -v`, GitHub credential нужно считать раскрытым, отозвать и заменить; не повторять значение и не использовать remote для push.

Статус Git всё ещё `main...origin/main [ahead 34]`, изменённые/новые файлы перечислены в `git status`; ничего не закоммичено/не опубликовано. Прямой URL preview tool не был корректно доступен в этом host; статический UI визуально не подтверждён.

---

## Последнее изменение (2026-09-27): API-backed workbench

Текущая сессия изменила:

- `src/d2intel/api/dashboard.py` — read-only overview, filtered/paginated match list, recent snapshot journal/detail; доступность артефакта baseline проверяется локально.
- `src/d2intel/app.py` — подключён dashboard router и раздача `site/` с `/`, если каталог существует.
- `site/index.html`, `site/app.js`, `site/styles.css` — новый адаптивный интерфейс без mock data: обзор, подходящие матчи, новый расчёт с подтверждением, append-only журнал и подробный provenance/feature view.
- `tests/api/test_dashboard.py` — API/UI contracts через in-memory session double без PostgreSQL/migrations.
- `site/README.md`, `REPO_SETUP.md`, `README.md` — назначение, API, запуск и актуальный product-status.

**В этой сессии:** схема БД/миграции, рабочая БД, ingest/normalization/обучение, model artifact и работающий runtime-процесс не изменялись. Real DB integration, браузерный прогон на реальных данных и обновление сервера владельца здесь **не выполнялись**.

**Проверки:** после исправления API test suite `tests/api/test_dashboard.py` и smoke `tests/test_smoke.py` запускаются локально; targeted Ruff и mypy проверяются отдельно. Полный suite по общей тестовой БД не запускать без проверки `D2INTEL_TEST_DATABASE_URL`: migration/constraint fixtures выполняют разрушительный `downgrade base`.

**Оставшийся ранее изменённый файл:** `HANDOFF_PROMPT.md` был modified до начала этой сессии. Его существующий блок с мониторингом prospective freeze от 2026-09-26 сохранён; текущая запись добавлена отдельно. Не откатывать чужую правку.

## Исторический/prospective контекст

### API-001 / LR

LR использует 9 prior-form дифференциалов. Model gate и метрики, обучающий pipeline, freeze/reconcile описаны в предыдущих разделах ниже. Ретроспективный сервис принимает target game1, проверяет as-of purity и на каждый вызов создаёт immutable снимок с model/feature version, cutoff и шаблонным evidence.

### Wallachia prospective вариант C (2026-09-26)

Выполнены head-sync и immutable freeze → reconcile скрипты. Текущая историческая запись для Na'Vi vs Aurora не обновляется UI автоматически, пока не добавлен reconcile-snapshot в БД, а заморозка ждёт появления доказанной game1 после cutoff. Файл freeze остаётся immutable; если нужная игра отсутствует в источнике/не имеет доказанного map index, reconciliation ждёт.

### Независимые продуктовые риски

- Схема `0003`; full pre-match scope заблокирован отсутствием проверенного free upcoming source.
- Замороженный тест LR остаётся малым (`n=131` по handoff 2026-09-23); точность и прибыль не обещать.
- PRD/корневые файлы расходятся относительно фазы прогноза: `docs/PRD.md` против ADR/корневой формулировки map1 pre-draft — проверять ADR-006 перед новым target contract.
- Нормализация не инкрементальна; регулярное ingestion/auto-start не настроены.

## Проверки, запуск, публикация

Сначала безопасные локальные тесты и targeted lint/typecheck; `ruff src tests scripts`, `mypy src` могут иметь заранее записанные ошибки в `normalize/` и `scripts/build_prior_form_dataset.py`, описанные в исторических handoff-разделах. Не выдавать эти проблемы за новые UI failures без дифференциальной проверки.

UI открывается на `http://127.0.0.1:8000/` после запуска FastAPI из `.venv`; полный запуск/health проверять с осторожностью: на компьютере владельца может уже слушаться локальный сервер, а реальная модель требует локального игнорируемого artifact в `artifacts/models/`. Не останавливать существующие процессы и не обучать/восстанавливать артефакт автоматически.

Эта сессия не делала commit/push/deploy. По AGENTS.md handoff/PR публикация и реальный запуск на компьютере владельца остаются отдельным подтверждённым шагом; не считать их выполненными по наличию файлов.

Дальше: проверить текущее состояние Git и принадлежность runtime процесса → выбрать тестовое окружение согласно `REPO_SETUP.md` → просмотреть изменения → только затем согласовать запуск UI/DB integration/deploy с владельцем.
