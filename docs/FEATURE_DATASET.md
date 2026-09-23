# FEATURE_DATASET — prior-form датасет as-of для map1 (FEAT-001)

**Статус:** реализовано (FEAT-001). Модуль `src/d2intel/features/prior_form.py`,
тесты `tests/features/test_prior_form.py` (pure-unit + интеграционные).
**Основание:** карточка `FEAT-001` в `BACKLOG.md`, `docs/PRD_TEMPORAL.md`,
`FEATURES.md` §1–2, `ML.md` §1, §5.

Здесь — контракт датасета: что считается примером, какие признаки доступны,
что значит «as-of», как работают маски и режимы. Формулы — в `FEATURES.md`,
временная семантика — в `docs/PRD_TEMPORAL.md`; этот документ их не
переопределяет.

---

## 1. Что такое пример

Одна строка датасета — **одна серия с доказанным `map_number = 1`** (status
`completed`, победитель известен, `event_time` известен). Соответствие «один
пример на серию» гарантируется запросом (`ROW_NUMBER() PARTITION BY series_id`
— при переигровке серии берётся самая ранняя попытка) и проверяется тестом.

- **target:** исход первой карты для **Team A** — `y = 1`, если выиграла
  команда на `slot = 0` (radiant). Team A/B — canonical identity из `game_team`
  (`ML.md` §1: прогноз до draft, не исход серии).
- **cutoff:** `game.event_time` целевой map1. Это граница реконструкции: всё,
  что после, не может попасть в признаки.
- `target_phase = "map1_pre_draft"` — фаза прогноза.

В датасет не попадают: серии без доказанного map1 (`map_number = NULL` →
`normalization_quarantine` по правилам DATA-001), карты без результата и карты
с победителем вне пары канонических команд (противоречие — защита, а не
молчаливое исключение).

---

## 2. Источники данных

| Таблица | Назначение в датасете |
|---|---|
| `game`, `game_team` | целевые map1 и вся прошлая история команд; `winner_team_id` → `won` |
| `game.patch_id`, `patch` | patch-контекст (вес ρ, same-patch counts) |
| `game_participant` | prior-known roster: игроки, замеченные в составе команды в прошлых картах |
| `player_performance` | финальная статистика **прошлых** карт (KDA/GPM/XPM) |

**Граница «до матча»** (`PRD_TEMPORAL.md` §3.3, `ML.md` §5.2): финальная
статистика и фактический состав **целевой** карты не читаются. Конкретно:
признаки целевой игры исключаются двумя независимыми механизмами —
`event_time + result_lag <= cutoff` (карта, начавшаяся непосредственно до
cutoff, ещё не доиграна) и явное исключение `game_id` целевой карты в
`team_form`/`player_form`. `player_performance` читается только для прошлых
карт — для целевой карты это было бы подменой знания фактом.

История для Team/Player form — **все завершённые карты** до cutoff, а не
только map1 (`ML.md` §1).

---

## 3. Режимы (event vs observed)

Каждый пример несёт `evaluation_mode` — метка обязательна, без неё пример не
входит в eval-когорту (`PRD_TEMPORAL.md` §6).

| Режим | Допустимость истории | Соответствие `PRD_TEMPORAL.md` | Обучение |
|---|---|---|---|
| `event_asof` | по времени события с учётом политики задержки: `assumed_available_at = event_time + result_lag` (`LAG_POLICY_VERSION = "lag-policy.v1"`, по умолчанию 4 часа) | `retrospective_reconstructed` | да |
| `observed_mode_only_study` | по фактическому `observed_at <= cutoff` | `prospective_observed` | **нет** — `train_eligible = False`, `exclusion_reason = "observed_mode_only_study"` |

`event_asof` — режим реконструкции: реальные `observed_at` в историческом
датасете — «сейчас», поэтому честная допустимость по факту наблюдения
недостижима (см. `PRD_TEMPORAL.md` §3.2). Политика задержки — единственное,
что отличает «событие было» от «результат был известен». Она
версионирована: изменение `result_lag` или правил — новая версия политики и
пересборка датасета.

`observed_mode_only_study` существует, чтобы проспективно наблюдённые данные
не смешивались с реконструированными в одну цифру качества. В текущем
датасете таких примеров нет: все `observed_at` — после cutoff.

---

## 4. Признаки

Схема — `FEATURE_SCHEMA_VERSION = "prior-form.v1"`. Все сглаженные значения
считаются из **переданных параметров** — построитель ничего не фитит на
датасете (см. §6).

Формулы (`FEATURES.md` §1): вес `w_i = exp(−ln2 · age_i / H) · ρ(patch_i)`,
сглаженный winrate `(Σw_i y_i + αμ) / (Σw_i + α)`, `n_eff = (Σw_i)² / Σw_i²`.

**Team (на сторону, `a`/`b`):**

| Признак | Определение |
|---|---|
| `team_*_n_games` | число допустимых прошлых карт |
| `team_*_n_eff` | эффективный объём взвешенной выборки |
| `team_*_wr_lifetime` | сглаженный winrate по всей истории до cutoff |
| `team_*_wr_last_long` / `_n_last_long` | то же по последним 20 картам |
| `team_*_wr_last_short` / `_n_last_short` | то же по последним 10 картам |
| `team_*_days_since_last` | дни от cutoff до последней прошлой карты |
| `team_*_same_patch_n` | число прошлых карт на патче целевой игры |
| `team_*_avail` | маска: есть ли хоть одна прошлой карта |
| `team_*_low_coverage` | `n_eff < min_eff_games` — мало данных |

**Player (минимальный набор FEAT-001, на сторону):**

| Признак | Определение |
|---|---|
| `player_*_n_known` | размер prior-known roster |
| `player_*_n_games` | суммарное число прошлых карт известных игроков |
| `player_*_wr` | средний сглаженный winrate известных игроков |
| `player_*_kda` | среднее `(K + A) / max(1, D)` по прошлым картам |
| `player_*_gpm`, `player_*_xpm` | средние GPM/XPM |
| `player_*_avail` | маска: есть ли prior-known roster |

prior-known roster — игроки, игравшие за команду в прошлых картах (inference
из истории, не confirmed roster — `PRD_TEMPORAL.md` §3.2). Индивидуальная
статистика игрока — по всем его прошлым картам, включая другие команды
(`FEATURES.md` §2). Расширенные player-агрегаты (EPIC 06) — MVP2-надстройка,
здесь не реализуются.

**Дифференциалы (side-neutral, `ML.md` §1):** `d_team_wr_lifetime`,
`d_team_wr_last_long`, `d_team_wr_last_short`, `d_team_n_eff`,
`d_team_days_since_last`, `d_player_wr`, `d_player_kda`, `d_player_gpm`,
`d_player_xpm` — всё вида A − B.

---

## 5. Маски доступности

Неизвестное — это `NaN` + `avail = False`, а не `0` (`FEATURES.md` §1). Если
истории нет: `wr_*` = `NaN`, `n_games` = 0, `avail` = `False`, а дифференциал
распространяет `NaN` — отсутствие данных не маскируется нулём. Если
признак всё же используется, низкое покрытие отмечается `low_coverage` при
`n_eff < min_eff_games`.

`target_patch_unknown` — патч целевой игры неизвестен. В этом случае патч-вес
ρ берётся из `patch_other_weight`, а неизвестный патч не считается
автоматически «старым» (`FEATURES.md` §1).

---

## 6. Параметры и train-only fit

`PriorFormParams` (`src/d2intel/features/prior_form.py`): `half_life_days`,
`alpha`, `prior_mean`, `patch_same_weight`, `patch_other_weight`,
`min_eff_games`, `last_n_long`, `last_n_short`, `result_lag`.

- `prior_mean` (μ) — единственный обучаемый параметр — вычисляется
  **только по train-меткам** через `PriorFormParams.fit(train_labels)`
  (AC #5: никаких трансформаций, обученных на всём датасете). Построитель
  принимает параметры снаружи и не вычисляет μ по датасету.
- Прочие параметры — задокументированные значения по умолчанию; их tuning —
  задача `ML-001` (через `dataclasses.replace`).
- Каждая строка строится только из своей истории до cutoff и переданных
  параметров — никаких глобальных статистик по датасету.

---

## 7. Как собрать

```python
from sqlalchemy.orm import Session
from d2intel.features.prior_form import PriorFormBuilder, PriorFormParams

params = PriorFormParams.fit(train_labels)          # μ только из train
builder = PriorFormBuilder(session, params=params)  # mode: event_asof
frame, meta = builder.build()                       # DataFrame + покрытие
```

`meta` (`DatasetMeta`) — версии схемы и политики задержки, режим, параметры
и покрытие: `n_examples`, `n_train_eligible`, `n_excluded`, `*_avail`,
`target_patch_known`. Это отчёт пригодности датасета, а не сырых данных.

Тесты: `tests/features/test_prior_form.py` — pure-unit (as-of, маски,
shrinkage, режимы, fit) + интеграционные на canonical-слое (один пример на
серию, отсутствие утечки целевой карты, observed-режим). Интеграционным
нужна выделенная тестовая БД со схемой `0003`; без неё они пропускаются
(`REPO_SETUP.md` §4).

---

## 8. Фактическое состояние на реальных данных

Проверка сборки read-only на рабочей БД (срез на момент проверки, не
обещание будущей воспроизводимости):

- 3455 примеров (серии с доказанным map1), все `train_eligible` в режиме
  `event_asof`;
- team-покрытие: `team_a_avail` ≈ 0.84, `team_b_avail` ≈ 0.81;
- `days_since_last` min = 4 часа — граница `result_lag`, ни одна карта ближе
  к cutoff в признаки не попала (leakage-граница работает);
- `y` ≈ 0.53 — первая карта чаще выигрывается командой на slot 0 (side-эффект
  ожидаем, не прогноз);
- player-признаки на этом срезе отсутствовали (`game_participant` пуст на
  момент проверки): маски `False`, значения `NaN` — fallback отработан как
  availability-aware, данные не подменяются. После наполнения участники
  учитываются тем же кодом.

Это **ретроспективный** датасет: он доказывает, что пайплайн проходит
raw → canonical → as-of фичи без утечки, и **не** является настоящим
pre-match прогнозом (`FIRST_10_TASKS.md` §2).

---

## 9. Границы документа

- Нет модели, метрик и calibration — это `ML.md`, `ML-001`.
- Нет immutable snapshot в `feature_snapshot` — это `API-001`: датасет —
  таблица примеров, снимки прогноза пишутся отдельной задачей.
- Нет hero pool/draft/турнирных признаков — MVP2+ (`FEATURES.md` §3, §5).
- Любые оценки качества — только после `ML-001` на временном split; здесь
  покрытие и структура, не метрики.
