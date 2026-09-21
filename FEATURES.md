# Feature Engine: измерения вместо субъективных рейтингов

Статус: PROPOSED. Формулы ниже — предлагаемые определения продукта, не измеренные результаты. Все параметры фиксируются в FeatureDefinition и выбираются только на training/tuning данных.

## 1. Единый контракт

Каждый признак: name/version, subject_id, unit, numerator/denominator, source fields, window, cutoff, patch/role context, recency policy, min sample policy, missing reason, evidence refs. Никаких безымянных «aggression=82». Неизвестное ≠ 0. Сырые значения, availability mask, n и effective sample size передаются вместе.

Окна из запроса: lifetime; последние 365/90/30 дней; последние 20/10 завершённых карт; current patch; current tournament; current roster. В MVP сначала lifetime-prior, last20/last10 и current patch с shrinkage; остальные расширяются общим механизмом, не отдельными pipelines. Lifetime = вся доступная история источника, не вся карьера, если coverage не доказано. Окна заканчиваются до cutoff, по времени доступного результата, не start_time ещё не завершившейся игры.

Для допустимой прошлой игры i:

- вес w_i = exp(−ln(2)·age_i/H) · ρ(patch_i, patch_target);
- H > 0 — half-life, ρ ∈ [0,1] — политика patch-distance; текущий patch получает 1, неизвестный — отдельный mask/политика, а не автоматически «старый»;
- weighted mean = Σw_i x_i / Σw_i;
- n_eff = (Σw_i)² / Σw_i²;
- сглаженный winrate = (Σw_i y_i + αμ) / (Σw_i + α), где μ — prior из допустимого training-прошлого, α ≥ 0 фиксируется train/tuning.

Изменение патча не требует механического обнуления всей истории: сравниваем recency-only и patch-weighted подходы. Официальный patch ID игры предпочтительнее календарного вывода. Today's meta winrates запрещены в старых cutoff.

## 2. Минимум MVP

| Признак | Определение | Ограничение |
|---|---|---|
| Team recent form | smoothed weighted wins / games, last10/20; дифференциал A−B | strength of opposition пока отдельный Elo challenger, не скрытый коэффициент |
| Player form | те же past wins и historical K/D/A/GPM/XPM по prior-known roster | неизвестный состав → availability-aware fallback; actual target participants не подставлять |
| KDA | (kills+assists)/max(1,deaths) для описания, рядом K/D/A отдельно | ratio при 0 deaths условен; не «навык» |
| Death rate | deaths / played_minutes | duration > 0, короткие/аномальные карты по отдельной eligibility policy |
| Kill participation | (kills+assists)/team_kills | если team_kills=0 → missing/defined mask; не делить на 1 без обозначения |
| Hero pool | распределение прошлых picks игрока/команды, entropy = −Σ p_h ln p_h, distinct heroes, sample size | показатель breadth зависит от объёма; никакого target draft до драфта |
| Hero proficiency | smoothed past winrate/performance на герое, role/patch context | редкий герой → prior + low coverage, не уверенный «контрпик» |
| Roster continuity | overlap доли prior-known игроков с прошлой known пятёркой + games together | overlap не подтверждает отсутствие стендина |
| Patch context | patch ID evidence + age + same-patch n_eff | новый patch → cold-start warning |

Player form агрегируется по ролям, когда роль была известна, иначе mask. Не называть среднее GPM пятёрки рейтингом игроков: сравнение carry/support без role context искажает смысл. Основная первая модель может использовать только надёжное подмножество; UI поясняет, что остальные сведения ещё не влияют на вероятность.

## 3. Team DNA и Player Style: MVP 2 и далее

**Team DNA** — вектор observable statistics с единицами и coverage, не один произвольный балл. Стандартизация относительно прошлого patch/role cohort обучается на train, не на всём датасете.

| Название | Операциональное определение | Что требуется |
|---|---|---|
| Early strength | средняя доля/разность net worth или gold advantage на фиксированном game time | per-time ряды; games surviving до этого времени; отдельно сообщать survival selection |
| Mid/late strength | аналогично на заранее выбранных временных landmarks | нельзя сравнивать only-long-game cohort с общей выборкой без оговорки |
| Comeback rate | P(win | в заранее заданное время deficit ≤ −d) | d/time обучаются либо задаются до test; сообщать denominator |
| Throw rate | P(loss | advantage ≥ d в том же зафиксированном окне) | не психологический термин; не искать максимум по всему будущему матча для live feature |
| Objective participation | доля team objective events с атрибутированным участием игрока | определить участие через damage/position/time-window; final last hit — не полное участие |
| Roshan behavior | first-Roshan timing, count и доля контролируемых Roshan в доступной истории | kill attribution и unknown rights/visibility |
| Farm dependency | доля team net-worth/farm, получаемая игроком в фиксированных окнах | описывает распределение ресурсов, не причинную необходимость farm |
| Aggression proxy | hero-damage/active-minute + fights entered/active-minute как отдельные компоненты | нельзя сворачивать в score без обученной и проверенной методики |
| Farm efficiency proxy | Δgold / время в заранее размеченных farm zones | реальные позиции + earnings; покупки/пассивный gold требуют разделения |
| Map activity | distance/time и unique occupied cells/time | положение наблюдаемое, gaps/teleports отфильтрованы |
| Rotation frequency | число смен lane/region с минимальным dwell time / observed minutes | versioned region map и фиксированный dwell threshold |
| Teamfight positioning | распределение расстояния до teamfight centroid в событиях fights | clustering radius/time, роли, позиции; это proxy, не качество механики |
| Lane performance | net-worth/XP differential lane counterparts в выбранный landmark | role/lane matching с confidence и отсутствием counterpart |
| Hero flexibility | распределение ролей на герое / entropy conditional role | роли не должны восстанавливаться по финальной статистике целевой игры |

«Mechanical impact» не включается: пока нет отдельного проверенного observable определения, это недопустимый субъективный score.

## 4. Synergy

Для пары/тройки/пятёрки: sorted player IDs как set key, роли и roster version отдельно. Games/wins/losses together, duration, early advantage, fight/objective statistics и sample counts. На старте ограничиться парами и полной пятёркой; triples — только после анализа разреженности.

Сыгранность ≠ winrate сильных игроков. Synergy residual предлагается как среднее `actual_y − expected_y` относительно честного out-of-fold player/team baseline на прошлых совместных играх, со shrinkage к 0. Baseline не знает результат оцениваемой игры. Сначала описательные counts, затем residual ablation; не присваивать causal трактовку.

Stable/new roster, stand-in, role swap — evidence-backed categorical states. `stand-in=true` только по источнику или явно маркированной inference policy; низкий games-together сам по себе не доказательство стендина.

## 5. Draft и турнир

MVP 2: picks/bans/order, known roles, past player-hero proficiency, hero-pair synergy/counter counts with shrinkage, pick/ban frequencies по прошлому patch. Sparse hero combinations требуют регуляризации. Draft archetype — классификация наблюдаемого состава с versioned rule/model, а не экспертный факт.

На каждом значимом draft revision — новая availability-aware FeatureSnapshot и PredictionSnapshot; historical draft без времени публикации не превращается в настоящий pre-draft snapshot. Каждая стадия draft — отдельный contract/модель либо модель, обученная на том же pattern missingness. Не подавать неполный драфт в модель, обученную только на финальных picks.

Tournament context: format/stage/bracket/elimination, already played maps, opponent IDs, elapsed rest = cutoff − previous_known_game_end, schedule density в lookback, recent series duration. Если отдых выводится из scheduled end, пометить estimated. Никаких психологических объяснений из defeat streak.

## 6. Проверка ценности

Один feature group за раз: baseline → добавление → парные time-block OOS сравнения log loss/Brier/calibration → cost/coverage → решение. Group ablation для Team/Player/Patch/Draft/Synergy/Expert/Spatial/Market. Доступность группы оценивается на тех же матчах; улучшение только на удобном subset не считать выигрышем полного продукта.

Feature service общий для training и serving; nearest as-of join может брать будущее, поэтому только backward + cutoff + entity/version matching. Техническая справка: [pandas merge_asof](https://pandas.pydata.org/docs/reference/api/pandas.merge_asof.html).
