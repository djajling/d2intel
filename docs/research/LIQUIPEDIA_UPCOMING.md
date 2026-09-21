# LIQUIPEDIA_UPCOMING.md — легальный путь к upcoming-матчам без заявки

**Дата:** 2026-09-21 · **Тип:** исследование (read-only probe)
**Статус:** подтверждено реальными запросами. **Пересматривает** вердикт SRC-001 по upcoming.
**Ключевое:** путь легальный — используется **MediaWiki API**, не HTML-страницы. Заявка на LiquipediaDB API **не требуется**.

---

## 1. Что изменилось

Ранее (`SRC_001_VERDICT.md`) upcoming считался недоступным: страница `Liquipedia:Matches` отдавала только вызов динамического виджета.

**Найдено:** страницы **конкретных турниров** содержат матчи как **статические `{{Match}}`-шаблоны в wikitext**, и этот wikitext доступен через MediaWiki API.

Проверено на `PGL/Wallachia/9` и `PGL/Wallachia/9/Group Stage` (турнир идёт 19–27 сентября 2026).

---

## 2. Как получать (два способа)

### Способ 1 — `prop=revisions` (рекомендуемый)

Возвращает сырой wikitext **без парсинга**. Лимит: 1 запрос / 2 сек.

```
https://liquipedia.net/dota2/api.php?action=query&prop=revisions&rvprop=content&rvslots=main&format=json&titles=PGL/Wallachia/9/Group%20Stage
```

### Способ 2 — `action=parse&prop=wikitext`

Медленнее: `action=parse` — **1 запрос / 30 сек**. Использовать только если нужен именно результат парсинга.

### Discovery страниц турнира

```
https://liquipedia.net/dota2/api.php?action=query&list=allpages&apprefix=PGL/Wallachia/9&format=json&aplimit=50
```

Возвращает подстраницы: `PGL/Wallachia/9`, `PGL/Wallachia/9/Group Stage`, `PGL/Wallachia/9/Statistics`.

Поиск страницы по названию:

```
https://liquipedia.net/dota2/api.php?action=query&list=search&srsearch=<название>&format=json
```

---

## 3. Что содержится в wikitext (реальный пример)

```text
|M2={{Match
|opponent1={{TeamOpponent|Team Yandex}}
|opponent2={{TeamOpponent|Natus Vincere}}
|date=September 21, 2026 - 19:00 {{Abbr/EEST}}
|twitch=PGL Dota2|youtube=PGL/QGOQ-8kuZvM|kick=PGL Dota2
|caster1=ODPixel|caster2=Fogged
|matchid1=9009924057
|matchid2=9010014985
|map1={{Map
|team1side=radiant
|t1h1=dark willow|t1h2=monkey king|t1h3=winter wyvern|t1h4=doom|t1h5=sven
|t1b1=kez|t1b2=dark seer|t1b3=witch doctor|t1b4=centaur warrunner|t1b5=enigma|t1b6=windranger|t1b7=lifestealer
|team2side=dire
|t2h1=hoodwink|t2h2=ember spirit|t2h3=mirana|t2h4=axe|t2h5=terrorblade
|t2b1=bounty hunter|t2b2=necrophos|t2b3=timbersaw|t2b4=lone druid|t2b5=slark|t2b6=tiny|t2b7=spectre
|length=30m09s|winner=1
}}
|map2={{Map ... }}
|map3={{Map ... }}
}}
```

### Доступные поля

| Поле | Смысл | Ценность для d2intel |
|---|---|---|
| `opponent1` / `opponent2` | `{{TeamOpponent\|Имя}}` | команды (могут быть пусты) |
| `date` | `September 21, 2026 - 19:00 {{Abbr/EEST}}` | **расписание upcoming** |
| `matchid1..5` | **ID матча OpenDota** | кросс-ссылка с OpenDota |
| `t1h1..t1h5`, `t2h1..t2h5` | пики героев по карте | драфт-данные |
| `t1b1..t1b7`, `t2b1..t2b7` | баны | баны (7 слотов) |
| `team1side` / `team2side` | radiant/dire | сторона |
| `length`, `winner` | длительность, победитель карты | результат по карте |
| `M-header` | `September 21 ‒ 2-0` | группировка раундов |
| `{{Round\|started=\|finished=}}` | флаги начала/завершения | статус раунда |

**Критично:** `matchid1=9009924057` — это тот же матч, что проверялся в OpenDota. Значит **источники кросс-ссылаются**: можно связать Liquipedia-расписание с OpenDota-статистикой по `match_id`.

---

## 4. Ограничения (честно)

1. **Команды для будущих матчей часто пусты.** В плей-офф и дальних раундахSwiss-сетки `{{TeamOpponent|}}` не заполнен — участники ещё не определены. Пример: Round 4/5 имеют даты, но пустые команды. Это **реальность источника**, а не дефект парсера. Следствие: по таким матчам система должна **воздерживаться (abstain)**, как и требует `PRODUCT.md`.
2. **Нужен парсер wikitext.** Данные — не JSON, а MediaWiki-разметка с вложенными шаблонами. Требуется грамматика парсинга `{{Match}}` / `{{Map}}` / `{{Matchlist}}`.
3. **Лимит 1 req/2 сек** (≈30/мин, 1800/час). Discovery по многим турнирам нужно планировать порциями и кэшировать.
4. **Требуется кастомный User-Agent** с идентификацией проекта и контактом. Общие UA («Python-requests») блокируются.
5. **Обязательна атрибуция** — контент CC-BY-SA 3.0.
6. **Нужен список турниров** (discovery). `allpages` по известному префиксу работает, но для автопоиска всех актуальных турниров нужно правило (категории/календарь) — отдельная задача.
7. Парсинг сделанных матчей даёт и **историю драфтов** — ценно, но для MVP target «до драфта» использовать нельзя без соблюдения cutoff.

---

## 5. Что это меняет в проекте

| Было (SRC-001 первичный) | Стало |
|---|---|
| Upcoming недоступен; Случай B; только ретроспективный прототип | **Upcoming доступен легально** через MediaWiki API |
| Заявка на LiquipediaDB обязательна для upcoming | Заявка **не обязательна** для базового сценария |
| — | Появилась **кросс-ссылка** Liquipedia ↔ OpenDota через `matchid` |
| — | Доступны **драфты и баны** (пики/баны по картам) — то, чего нет в OpenDota (`draft_timings` пуст) |

**Но:** это не отменяет ретроспективный характер первых 10 задач. Данных upcoming достаточно для **обнаружения будущих встреч**, однако:
- команды часто не определены → abstain;
- требуется парсер и discovery;
- покрытие по лигам нужно измерить (coverage gate).

Рекомендация: оставить первые 10 задач как ретроспективный срез (они уже утверждены), а **upcoming-адаптер** добавить отдельной задачей после `DATA-001`, с измерением coverage и соблюдением abstain-правил. Заявку на LiquipediaDB рассматривать как **опциональное усиление** (структурированные данные, 60 req/час), не как блокер.

---

## 6. Что осталось непроверенным

- Автоматический discovery всех актуальных турниров (категории Liquipedia, календарь).
- Покрытие: какая доля upcoming-матчей имеет заполненные команды.
- Точная грамматика всех вариантов `{{Match}}`-шаблонов (разные форматы сеток).
- Соответствие `{{Abbr/EEST}}` и других таймзон — требуется таблица соответствий для нормализации времени.

---

_Document — результат read-only probe. Использование требует соблюдения ToS Liquipedia: атрибуция, User-Agent, лимиты, без HTML-scraping._
