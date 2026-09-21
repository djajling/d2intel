# Live Architecture и Heatmap Engine

Статус: PROPOSED, Future после MVP 3. Ни один live feed не подключён; sample публичных лобби не доказывает доступ к профессиональным матчам.

## 1. Gate доступа

Проверить bounded пробами: нужные профессиональные турниры действительно присутствуют; game/team/player IDs сопоставляются; поля доступны без скрытого платного контракта; известны source/game/observation clocks; права допускают использование; историческая и live схемы совместимы.

Кандидаты:
- OpenDota `/live`: только те поля и coverage, которые реально получены; observed `delay` не универсальный SLA.
- STRATZ / Valve: только после token/method/schema проверки.
- Локальный GSI: нужен разрешённый spectator/локальный клиент, доступность данных зависит от режима. Это не unattended серверный глобальный канал всех турниров.
- Replay parser: готовый OSS parser после license/compatibility проверки; replay после игры не заменяет живой поток.

Источник: [SOURCES.md](SOURCES.md), U5/U6/U12/U13. No-go live не блокирует работающий pre-match продукт. Не использовать закрытые backstage feeds или игровые преимущества участнику: инструмент для анализа профессиональной сцены, не чит.

## 2. State pipeline

```text
Live adapter → raw observation → reorder/dedup/validate
       → canonical GameState revision
       → as-of live FeatureSnapshot
       → live model + calibrator
       → PredictionSnapshot → trajectory UI
```

State содержит game_id, game_time, source_time, observed_at, available_at, sequence/revision, heroes/draft, score, gold/XP/net worth/objectives/items/positions **только при наличии**, visibility_scope, missing mask и staleness. Нет позиции — нет fabricated map control.

Late/out-of-order observation не перезаписывает показанный snapshot. Обновление current-state projection допускается новой revision; replay trajectory хранит, что действительно было показано. События start/end могут отсутствовать: не синтезировать уверенные времена. Pause/reconnect/remake проверяются отдельно.

Latency измерять по компонентам: source lag, transport lag, processing/inference lag, UI lag. `game_time` не wall clock; broadcaster delay и provider timestamp не обязаны совпадать. Без правдивого source timestamp полную end-to-end задержку назвать нельзя.

## 3. Live model

Первая модель — tabular baseline на времени и реально доступных состояниях: относительные gold/XP/net worth, kills, towers, Roshan, draft/known heroes. Базовый comparator time+gold, затем дополнительные группы. Items/positions вводятся только при historical/live parity.

- Training использует replay reconstruction ровно доступного к t состояния, не final scoreboard, final duration, future objective counts.
- Валидируем по calendar/series, все snapshots игры в одном split.
- Отчёт по заранее выбранным horizons и равновесным per-game весам. Длинные игры не получают автоматический больший вес из-за большего числа кадров.
- Terminal state не включать в оценку «полезности live предсказания»: знать победителя после разрушения Ancient не прогноз.
- Missingness при serving должна совпадать с training policy; zero-fill отсутствующих towers/Roshan может разрушить смысл — fallback/abstain.
- Temporal model (LSTM/transformer) лишь после baseline, с causal mask и контролем padding. Новые heroes/patches не ломают embedding lookup.

На update значимого state/draft — snapshot; frequency и debounce выбираются по реальному quota/latency budget, не обещаются заранее. Дедуп одинаковых входов не мешает хранить observation times.

## 4. Heatmaps как измерения

Начать с доступных event-derived heatmaps (deaths/wards/objectives), затем movement/farm/teamfight при достаточной позиции. Пользовательский rollout heatmaps идёт после live gate; разрешённый offline replay research может быть независимым. Heatmap не является live map vision.

Для каждой карты: map version, coordinate transform, Radiant/Dire orientation, bounds, region polygons, game-time window, sampling policy, visibility scope и missing fraction. Сырые координаты сохраняются отдельно от transformed grid. Изменение геометрии патча требует новой map_version; нельзя накладывать несопоставимые территории.

| Heatmap | Что считается | Нельзя подменять |
|---|---|---|
| Movement | время присутствия игрока в клетке / наблюдаемое время | частоту нерегулярных sample вместо времени |
| Farm | события получения farm/creep kills или локализованный gold, policy явная | всю occupancy в лесу за «farm» |
| Death | count/observed exposure по месту смерти | вероятность смерти из голого количества без exposure |
| Teamfight | кластеризованные боевые события/позиции в fight windows | все kills за полноценные teamfights без правила |
| Ward-related | позиции/время активности wards и обнаруженные destroy events | полную vision coverage без terrain/visibility модели |
| Objective | события/присутствие возле конкретных objectives | причинный objective pressure из статичного расстояния |

## 5. Численные spatial features

Предлагаемые формальные proxies, параметры версионируются:

- **presence_control(R):** наблюдаемые player-seconds команды в регионе R / суммарные наблюдаемые player-seconds обеих команд в R; это присутствие, не полная информация о контроле/vision.
- **rotation_frequency:** число переходов между region labels с минимальным dwell / observed_minutes.
- **farm_area:** площадь grid cells с подтверждёнными farm events в окне; зависит от grid resolution, сохранять её.
- **enemy_jungle_presence:** player-seconds в enemy-jungle polygons / все observed player-seconds команды.
- **objective_pressure:** время игроков в радиусе objective, делённое на observed exposure; радиус/длительность фиксированы; рядом damage/event features отдельно.
- **average_rotation_distance:** сумма валидных расстояний переходов / число завершённых rotations; teleports отдельно, long missing gaps не интерполировать как прогулку.
- **death_hotspots:** spatial death intensity count/exposure по клеткам, с minimum exposure и uncertainty.
- **teamfight_position:** распределение расстояния игрока до centroid собственного состава/событий в fight, роль и момент зафиксированы.

SpatialArtifact/Heatmap хранит raw input manifest, transform/binning/smoothing versions, payload hash, window и cutoff. Сглаживание для UI не должно незаметно менять ML feature. Объём raw positions оценивается пилотом до решения о parquet/partitioning; ClickHouse не нужен по умолчанию.

## 6. Тесты и остановка

Fixtures: нет позиции; перепутанная ориентация; новый patch/map; пропуск sample; out-of-order; pause; повторное событие; game ended correction; неизвестный hero; неполный draft. Golden trajectory проверяет отсутствие будущих полей. Spatial transform проверяется контрольными точками и coverage mask.

Если pro-live отсутствует или права неясны — остановить live, сохранить pre-match. Если реплеи не доступны — не обещать исторические movement heatmaps. Если spatial ablation не улучшает OOS качество, оставить визуализацию исследовательской, не объявлять ML advantage.
