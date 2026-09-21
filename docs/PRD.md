# PRD-001 — Product Specification v0

**Статус:** Утверждён владельцем (2026-09-21)
**Следующая точка входа:** SRC-001

---

## 1. Цель прогноза

**Единица прогноза:** `P(Team A выигрывает карту N | карта N сыграна, полный драфт завершён)`

- Team A — канонический ID, фиксируется при создании fixture, не меняется.
- `P(Team B) = 1 − P(Team A)` — бинарный исход.
- **Момент расчёта:** после полного драфта (все 10 пиков + баны). Частичный драфт → abstention.

### Серийная вероятность (производная)

`P(Team A выигрывает серию)` вычисляется математически из per-game вероятностей и текущего счёта — без отдельно обученной модели.

```
BO3 (0-0): P = p² + 2p²(1−p)
BO3 (1-0): P = p + p(1−p)
BO3 (0-1): P = p²
BO5: аналогично по отрицательному биномиальному распределению

```

Per-game `p` обновляется после каждого нового драфта.

### Форматы

| Формат | Карт макс | Прогнозов |
|---|---|---|
| BO1 | 1 | 1 |
| BO3 | 3 | 1–3 |
| BO5 | 5 | 1–5 |

---

## 2. Определения

| Термин | Определение |
|---|---|
| Fixture | Запланированная встреча двух команд |
| Series | BO-исполнение fixture; 1:1 с Fixture |
| Game | Одна карта; `map_number` внутри Series |
| Team A / B | Канонические ID, slot фиксируется при создании fixture |
| Cutoff | Момент, до которого все входные данные имеют `available_at ≤ cutoff` |
| Complete draft | Все 10 пиков + все баны зафиксированы источником |
| retrospective_reconstructed | История получена сейчас, `available_at` = assumed lag policy |
| prospective_observed | Данные реально накоплены системой до cutoff |

Полная спецификация временной семантики (пять временных полей, инварианты порядка, правило cutoff,
immutability снимков, словарь меток, маски доступности) — [`docs/PRD_TEMPORAL.md`](PRD_TEMPORAL.md) (`PRD-003`, утверждена 2026-09-21).

---

## 3. Правила cutoff

1. Прогноз использует только данные с `available_at ≤ cutoff_at`.
2. `cutoff_at` = момент фиксации complete draft.
3. Финальная статистика карты (KDA, GPM, итог) **запрещена** до матча.
4. Фактический ростер целевой карты — только `prior_known_roster` с `roster_status`.
5. Hero winrate / patch meta — только с as-of фильтром.
6. Неоднозначный статус драфта → abstention.
7. Backdating запрещён.

---

## 4. Разметка исходов

| Исход | Метка |
|---|---|
| Team A выиграла | `y = 1` |
| Team B выиграла | `y = 0` |
| Forfeit / техническое поражение | `excluded` |
| Void / отмена / walkover | `excluded` |
| Remake | Отдельная Game с `attempt_number` |
| Карта не сыграна | `excluded` |
| Неизвестен `map_number` | `quarantine` |

---

## 5. Гейты

| Гейт | Условие | Провал |
|---|---|---|
| G-SRC-HIST | OpenDota history доступна, права OK, coverage измерена | STOP до INF-001 |
| G-SRC-UPC | Liquipedia API: legal + timestamps + identity mapping; не scraping | Остаться на ретроспективе |
| G-PURITY | Critical cutoff violations = 0; ambiguous identity в eval = 0 | Блокирует quality gate |
| G-ROSTER | Качество prior roster достаточно | Расширить fallback |
| G-OPS | Coverage ≥ 90% на фиксированных 30 sequential eligible game fixtures | Сузить scope |
| G-MODEL | **Accuracy ≥ 70% per-game на frozen test**; Brier/log-loss/ECE; CI по сериям | LR остаётся champion; малая выборка → insufficient evidence |
| G-FRESH | Source lag + ingestion lag измерены; SLO per field утверждён | Gate не закрыт |
| G-REL | Повторный запуск не меняет старые snapshots; crash recovery OK | Доработка |
| G-LIVE | Pro-live feed: coverage + rights + payload parity | Live не реализуется |
| G-HM | Replay data: rights + historical parity | Heatmap не реализуется |
| G-MARKET | Timestamped odds: legal + matched | Market layer не реализуется |

**Проектные пороги:**
- Critical purity violations = **0**
- Unmapped evaluation records = **0**
- Coverage ≥ **90%** на заранее фиксированном знаменателе
- Accuracy ≥ **70% per-game** на frozen test

---

## 6. Non-goals

- Redis / Celery / Kafka / Kubernetes / feature store
- HTML scraping
- Авто-ставки (market = ANALYSIS only)
- LLM как математический предиктор
- Backdated live прогнозы из retrospective данных
- Отдельная обученная модель серийной вероятности
- Series-level accuracy gate (вторичная метрика, не gate)

---

## 7. Revision log

| Версия | Дата | Изменение |
|---|---|---|
| v0 | 2026-09-21 | bo1/bo3/bo5 scope; post-draft trigger; 70% per-game gate; derived series probability |
| v0.1 | 2026-09-21 | ссылка на утверждённую спеку временной семантики `PRD-003` / `docs/PRD_TEMPORAL.md` |

---

**NEXT:** DB-001 — минимальная ядровая temporal-схема + snapshots/migrations/constraints
(зависит от `INF-001` и `PRD-003`; оба выполнены).
