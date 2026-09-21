# OPENDOTA_API_MAP.md — карта API для ING-001 и DATA-001

**Дата:** 2026-09-21 · **Тип:** исследование (read-only probe, без ключей)
**Статус:** подтверждено реальными запросами. Не все вопросы закрыты — см. §6.
**Связь:** `SRC-001` (история — PASS) → `ING-001` (клиент) → `DATA-001` (нормализация)

---

## 1. Лимиты и доступ

| Параметр | Значение (free, без ключа) |
|---|---:|
| Дневной лимит | 3 000 запросов |
| Минутный лимит | 60 запросов |
| API key | не требуется |
| Не тарифицируется | HTTP 404 / 429 / 500 |

Клиент `ING-001` обязан: throttle 60/мин, обрабатывать `429` по `Retry-After`, читать `X-Rate-Limit-Remaining-Minute` / `-Day`, секреты не сохранять в raw/log.

---

## 2. Подтверждённые endpoints

### 2.1 `GET /api/proMatches` — список про-матчей

Без ключа, 86 записей в ответе. Поля записи:

`match_id`, `duration`, `start_time`, `radiant_team_id`, `radiant_name`, `dire_team_id`, `dire_name`, `leagueid`, `league_name`, `series_id`, `series_type`, `radiant_score`, `dire_score`, `radiant_win`, `version`

Пример: `match_id=9009924057`, league `PGL Wallachia 2026 Season 9`, Team Yandex (9823272) vs Natus Vincere (36), `series_id=1145136`, `series_type=1`.

**Подводный камень:** часть записей имеет `null` в именах команд (стримерские/полупрофессиональные лиги) → нужна фильтрация по scope и обработка неполных identity.

### 2.2 `GET /api/matches/{match_id}` — детальная информация

Подтверждено наличие: `match_id`, `start_time`, `duration`, `radiant_win`, `game_mode`, `lobby_type`, `patch`, `version`, `cluster`, `region`, `players[]`, `teamfights[]`, `objectives[]`, `chat[]`, `radiant_gold_adv[]`, `radiant_xp_adv[]`, `draft_timings[]`, `cosmetics`.

`players[]` содержит: `account_id`, `hero_id`, `player_slot`, `team_number`, `isRadiant`, `kills`, `deaths`, `assists`, `net_worth`, `gold_per_min`, `xp_per_min`, `last_hits`, `denies`, `hero_damage`, `win`/`lose`.

**Подводные камни:**
- `draft_timings` для проверенного матча — **пустой массив**. Драфт-данные могут отсутствовать.
- Ответ очень большой (teamfights, objectives, chat) — при пакетной выгрузке это главный источник трафика и лимитов.
- `series_id`, `leagueid`, `picks_bans` в этом ответе напрямую подтвердить не удалось (ответ обрезался) — надёжнее брать из `/explorer` (см. §2.3).

### 2.3 `GET /api/explorer?sql=...` — SQL-слой (ключевой для bulk-истории)

Подтверждено существование таблиц и их колонок.

**Таблица `matches`** (проверенные колонки):

| Колонка | Тип | Пример |
|---|---|---|
| `match_id` | INT8 | 9009924057 |
| `series_id` | INT4 | 1145136 |
| `series_type` | INT4 | 1 |
| `leagueid` | INT4 | 20279 |
| `start_time` | INT8 | 1790006825 |
| `radiant_win` | BOOL | true |
| `duration` | INT4 | 1809 |
| `game_mode` | INT4 | 2 |
| `lobby_type` | INT4 | 1 |
| `cluster` | INT4 | 191 |
| `radiant_team_id` | INT4 | 9823272 |
| `dire_team_id` | INT4 | 36 |

**Таблица `picks_bans`** (проверенные колонки): `match_id`, `is_pick`, `hero_id`, `team`, `ord`.

Пример строк для 9009924057: `{is_pick:false, hero_id:145, team:0, ord:0}`, `{is_pick:false, hero_id:55, team:0, ord:1}`, …

**Важно:** `patch` **не является колонкой** таблицы `matches` — запрос `SELECT patch FROM matches` возвращает ошибку `column "patch" does not exist`. Поле `patch` в `/matches/{id}` — вычисляемое.

### 2.4 `GET /api/constants/patch` — границы патчей

Массив `{name, date, id}`. Последние записи:

| id | name | date |
|---|---|---|
| 57 | 7.38 | 2025-02-19 |
| 58 | 7.39 | 2025-05-22 |
| 59 | 7.40 | 2025-12-16 |
| 60 | 7.41 | 2026-03-24 |

**Следствие:** patch для матча вычисляется — последний патч с `date <= start_time` матча. Проверено: матч с `start_time=1790006825` (сентябрь 2026) → `patch=60` (7.41). Совпадает с `/matches/{id}`.

### 2.5 `GET /api/live` — идущие матчи

Поля: `activate_time`, `deactivate_time` (`0` = идёт), `league_id`, `lobby_type`, `game_time`, `delay`, `spectators`, `match_id`, `series_id`, `team_name_radiant/dire`, `team_id_radiant/dire`, `radiant_lead`, `radiant_score`/`dire_score`, `players[]` (`account_id`, `hero_id`, `team`, `is_pro`, `team_id`).

**Ключевое:** только идущие/недавно завершённые. **Будущих матчей нет** — это основание вердикта SRC-001 по upcoming.

---

## 3. Что НЕ хранится в источнике (придётся вычислять)

| Сущность | Статус | Как получить |
|---|---|---|
| **Номер карты в серии (map index)** | не хранится | сортировка матчей внутри `series_id` по `start_time` → ordinal |
| **patch** | не колонка БД | `start_time` + таблица `/constants/patch` |
| **upcoming-расписание** | отсутствует | недоступно (см. SRC_001_VERDICT.md) |
| **ростеры до матча** | косвенно | `players[].account_id` + `team_id` по историческим матчам; фактическая пятёрка часто известна позже →Evidence/roster versions с provenance |

---

## 4. Рекомендации для ING-001 (клиент)

1. Два режима выгрузки:
   - **лёгкий** — `/proMatches` для обнаружения (одна страница ≈ 86–100 матчей, минимум трафика);
   - **детальный** — `/explorer` SQL для выборочных колонок (`matches`, `picks_bans`), чтобы не тащить тяжёлый `/matches/{id}`.
2. `/matches/{id}` использовать **точечно** (teamfights/objectives/chat нужны только для Future-слоёв, не для MVP).
3. Throttle 60/мин, дневной бюджет 3 000 — планировать выгрузку порциями, watermark только после commit.
4. Idempotence по natural key (`match_id`), `raw hash` для дедупликации, повторные observations сохранять отдельно.
5. Карантин: `null`-идентичности команд, отсутствующие `picks_bans`, пустые `draft_timings` — отдельная причина data-quality.

## 5. Рекомендации для DATA-001 (нормализация)

1. **Map index** = порядковый номер матча внутри `series_id` по возрастанию `start_time`. Неоднозначные случаи (одинаковое время, remake) — **карантин**, не уверенное присвоение.
2. **Team A** фиксируется по канонической идентичности (`radiant_team_id`/`dire_team_id` по fixture), **не** по Radiant/Dire — иначе target «перевернётся».
3. **patch** вычисляется через `/constants/patch` и кэшируется (справочник меняется редко).
4. Исходы `forfeit`/`walkover`/`void` — отдельные статусы, не игровые победы. Пока признаков в API не обнаружено → требуется отдельное правило на DATA-001.
5. Фильтр scope по `leagueid` — по утверждённому владельцем перечню турниров (PRD-001).

---

## 6. Что осталось непроверенным

- Полный список колонок таблиц `matches` / `picks_bans` (проверены только запрошенные).
- Таблицы `player_matches`, `teams`, `leagues`, `notable_players` — не проверялись (нужны для составов и identity).
- Признаки `forfeit`/`walkover`/`void` в данных — не обнаружены, правило требуется уточнить.
- Поведение `pagination` и параметры `less_than_match_id` для `/proMatches` — не проверялось.
- Фактический объём истории, достижимый в пределах 3 000 req/день — оценивается на ING-001.

---

_Document — результат read-only probe. Не является реализацией._
