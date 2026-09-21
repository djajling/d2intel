# Data Architecture и Data Model

Статус: PROPOSED; концептуальная/логическая схема, не SQL migrations. Физически MVP реализует только используемое ядро; остальные сущности — эволюционный контракт.

## 1. Слои хранения

1. **Raw:** неизменяемый payload источника + отдельные retrieval observations, hash и rights policy. Нужен для replay нормализации и расследования.
2. **Canonical:** типизированные реляционные сущности, PK/FK, ограничения идентичности и версий. JSONB только для расширяемых payload, не вместо FK.
3. **Derived:** измерения, as-of feature snapshots, модели, predictions/evaluations. Derived можно пересчитать новой версией, опубликованный snapshot — не перезаписать.
4. **Artifacts:** model binary, dataset manifest, крупные replay/spatial файлы локально; БД содержит URI относительно разрешённого storage root, checksum, format/version/rights. Массовые позиции не загружать в JSONB одного матча.

Все времена — UTC `timestamptz`, исходная timezone и original timestamp сохраняются. Неизвестное время — NULL + причина, не фиктивная полночь. Счётчики provider IDs хранить без потери точности; наружу большие внешние IDs допустимо сериализовать строками. Служебные IDs — UUID; внешний ID уникален только внутри источника и типа сущности.

## 2. Бивременность и фактическая доступность

| Поле | Значение |
|---|---|
| event_time / valid_from, valid_to | Когда событие произошло / факт действовал в игровом мире |
| source_published_at | Когда источник заявил о публикации; NULL, если неизвестно |
| observed_at | Когда наш collector фактически получил эту версию |
| ingested_at | Когда версия записана в БД |
| available_at | Когда версия после необходимой обработки стала доступна prediction pipeline; не раньше observed_at/ingested_at и готовности зависимостей |
| system_from, system_to | Интервал знания о версии в нашей системе; новая коррекция закрывает старую системную версию |
| cutoff_at | Граница информации конкретного forecast, а не время будущего события |

Для strict prospective forecast все используемые версии имеют `available_at <= cutoff_at`; публикации с явно будущим source_published_at требуют карантина/разбора clock skew. У historical reconstructed dataset нет права выставлять observed_at в прошлое. Он хранит фактическое retrieval now и отдельный `assumed_available_at` + lag_policy_version. Оценка режима реконструкции всегда отделена от реального point-in-time replay.

Обнаруженный сейчас старый трансфер не становится известным модели вчера. Прошлый roster «последние пять сыгравших» — inference из прошлых матчей, а не confirmed roster. Справочники/patch assignments также версионируются: сегодняшняя исправленная таблица не заменяет прошлую без отметки.

## 3. Семантика соревнований

```text
Tournament 1 ── N TournamentStage 1 ── N Match
                                           | 0..1
                                         Series 1 ── N Game
Team 1 ── N Roster 1 ── N RosterMembership N ── 1 Player
Game 1 ── N GameParticipant N ── 1 Player
Game 1 ── N DraftAction / GameEvent / PlayerPerformance
Prediction 1 ── N PredictionSnapshot N ── 1 FeatureSnapshot
PredictionSnapshot N ── 1 ModelVersion
PredictionSnapshot 1 ── N PredictionEvaluation
```

**Match:** запланированная встреча, не отдельная карта; именно здесь доступны upcoming и TBD до появления игровых IDs. **Series:** соревновательное BO-исполнение fixture, связанное с одним Match; создаётся, когда известен формат/исполнение, может существовать до карт. **Game:** карта, `map_number`; provider `match_id` обычно отображается сюда, а не на наш Match. Series без сопоставленного fixture хранится как orphan с причиной; не плодить искусственные расписания.

В MVP прогнозируем game1 placeholder при условии сыгранной карты. Несыгранные будущие карты не создаются как завершённые наблюдения. Номер первой карты нельзя угадывать по первой найденной записи при неполной серии; такие строки исключаются с явной причиной. `attempt_number` позволяет хранить remake той же карты; result rules выбирают counting attempt.

## 4. Справочник сущностей: поля и ограничения

Обозначения стадий: **M** — ядро MVP, **2** — MVP 2, **3** — MVP 3, **F** — Future. PK = `id`, если не указано иначе; versioned-объекты дополнительно имеют temporal envelope из §2 и provenance.

### Источники и нормализация

| Сущность | Стадия | Основные поля / связи / ограничения |
|---|---|---|
| DataSource | M | name, adapter_version, capabilities, terms_url, terms_checked_at, allowed_purposes, retention_policy; API-token вне БД |
| IngestionRun | M | source_id FK, started_at, finished_at, status, cursor_before/after, error_summary, quota_headers |
| RawPayload | M | source_id, endpoint_kind, content_hash, payload_json, schema_version; unique(source_id, content_hash); hash включает каноническое представление |
| SourceObservation | M | run_id, raw_payload_id, provider_entity_id/type, request_fingerprint, observed_at, source_published_at; разные retrievals не дедуплицируются только по payload |
| EntityMapping | M | source_id, entity_type, external_id, canonical_id, mapping_version, status, evidence_id; unique active(source,type,external_id); type-aware FK через typed mapping tables либо registry |
| EvidenceRecord | M | observation_id, field_path/span, entity_revision_id, transformation_version, rights_policy; внутренний первоисточник объяснения |
| QuarantineRecord | M | observation_id, reason_code, details, resolved_by, resolution_revision; неоднозначные данные не входят в eval |
| ProcessingCheckpoint | M | source_id, job_kind, cursor, revision, committed_at; unique(source,job_kind) |
| DomainEvent / OutboxDelivery | 2/F | aggregate_id/type, revision, type, observed_at, payload, dedup_key; Delivery consumer/status/attempts; unique(consumer,event_id) |

### Соревнования и идентичность

| Сущность | Стадия | Основные поля / связи / ограничения |
|---|---|---|
| Tournament | M | name, organizer_source, provider_league mappings, start/end, tier_evidence; названия не PK |
| TournamentStage | M/2 | tournament_id, name, stage_type, order, format_rules_version; group/bracket/round сведения позднее |
| Match | M | stage_id nullable, tournament_id, scheduled_start, status, time_precision, best_of nullable, schedule_revision; нельзя требовать известные команды для TBD |
| MatchParticipant | M | match_id, slot A/B, team_id nullable, seed/context; unique(match,slot); две известные команды не одинаковы |
| Series | M | match_id unique nullable, best_of, score_a/b, status, result_revision_id; BO2/draw не обрабатывать бинарно без отдельного контракта |
| Game | M | series_id nullable, map_number nullable, attempt_number, status, patch_id nullable, draft_start/start/end, winner_team_id nullable, result_type; unique(series,map_number,attempt) при известных полях |
| GameTeam | M | game_id, team_id, side nullable, slot; unique(game,slot), unique(game,side) при известной стороне |
| Team | M | canonical_name, identity_status, created_at; организация ≠ roster, переименование ≠ новая сущность автоматически |
| TeamAlias | M | team_id, alias, provider, validity, evidence; только для candidate resolution |
| Player | M | account_id nullable, canonical_name, identity_status; Steam/account mapping отдельно, никакого merging по nickname |
| PlayerAlias | M | player_id, alias, validity, evidence |
| Roster | M | team_id, roster_type announced/registered/inferred/actual, scope_tournament_id nullable, version, valid/system intervals, evidence_id |
| RosterMembership | M | roster_id, player_id, role nullable, is_standin nullable, valid interval, evidence; unique(roster,player,valid_from); противоречивые свидетельства разрешаются явно |
| GameParticipant | M | game_id, player_id, team_id, hero_id nullable, slot, role nullable, roster_evidence; unique(game,player), unique(game,slot); actual состав — результат наблюдения этой карты |
| Hero | M | stable_game_id unique, name versions, active_from; deprecated/unknown IDs поддерживаются |
| Patch | M | version_label, effective_from/to, announced_at, type major/minor/hotfix, evidence; actual game patch имеет приоритет над выводом из даты |
| PatchChange | 2 | patch_id, entity_type/id, field, before/after nullable, change_text, source/span; интерпретация meta отделена от release-note факта |
| ResultRevision | M | target_type/id, result_type, winner_id nullable, score, observed/available time, supersedes_id, evidence; sporting outcome, forfeit, void, cancelled раздельно |

### Игровые и производные данные

| Сущность | Стадия | Основные поля / связи / ограничения |
|---|---|---|
| Draft | 2 | game_id, revision, completeness, observed_at, available_at, format_rules_version |
| DraftAction | 2 | draft_id, sequence, action pick/ban, team_id, hero_id, event_time, observation_id; unique(draft,sequence); порядок источника проверять |
| GameEvent | F | game_id, source_event_key, sequence, game_time, type, actor/target nullable, position nullable, payload, available_at; unique(source,game,key) |
| PlayerPerformance | M/F | game_participant_id, metric_schema_version, final K/D/A/GPM/XPM/duration; более глубокие metrics nullable + missing_reason + raw provenance; final нельзя читать как target pre-match feature |
| PlayerSynergy | 2 | unordered player-set key, role_assignment_version, context patch/roster/window, cutoff, n_games, weighted statistics, effective_n; triple не перечислять до достаточного покрытия |
| TeamStyle | 2/F | team_id, window, patch, cutoff, metric_definition_version, observables, effective_n, coverage; Team DNA — профиль значений, не мистический score |
| PlayerStyle | 2/F | player_id, role_context, тот же контракт метрик/окон; пространственные поля только при позиции |
| PositionSample | F | game_id, player_id, game_time, x/y, map_version, visibility_scope, sample_interval, observation; policy для gaps/teleports |
| SpatialArtifact | F | game_id/scope, artifact_uri/hash, map_transform_version, coordinate_frame, sample_coverage |
| Heatmap | F | artifact_id, subject, type movement/farm/death/teamfight/ward/objective, grid/binning/smoothing versions, normalization, time_window, patch_id, visibility_scope |

`PlayerPerformance` — сырые измерения сыгранной карты; `PlayerStyle`/`TeamStyle` — рассчитанные профили; `FeatureSnapshot` — именно те значения, которые вошли в конкретное решение. Не смешивать их в одной mutable таблице current_stats.

### Forecast и воспроизводимость

| Сущность | Стадия | Основные поля / связи / ограничения |
|---|---|---|
| FeatureDefinition | M | name, version, formula, source requirements, windows, availability policy, units, missing policy |
| DatasetVersion | M | manifest_uri/hash, source revision set, temporal_mode, split_manifest, excluded records/reasons, label policy, feature_schema_version |
| ModelVersion | M | algorithm, artifact/hash, code_commit, dependency_lock_hash, dataset_id, training_cutoff, hyperparams, seed, feature_schema_version, calibration_version_id nullable, evaluated_report_id, promotion status |
| CalibrationVersion | M | method, artifact/hash, base_model_id, calibration dataset interval, schema, metrics; base-model relation FK без обязательного циклического insert |
| FeatureSnapshot | M | target_type/id, cutoff_at, evaluation_mode, values_json, missing/coverage_json, evidence_refs, feature_schema_version, content_hash, assumed_availability_policy nullable |
| Prediction | M | immutable target request: target_type, target_id, team_a_id, team_b_id, horizon/phase contract; unique stable request key |
| PredictionSnapshot | M | prediction_id, computed_at, cutoff_at, snapshot_seq, model_version_id, feature_snapshot_id, p_a/p_b nullable, abstention_reason, draft_revision_id nullable, roster_state_json, expert_state_json, market_state_json, state_hash, trigger_event_id, idempotency_key unique |
| SnapshotEvidence | M | snapshot_id, evidence_id, role source/feature/attribution; фиксированные revision refs, не ссылки на mutable latest |
| PredictionEvaluation | M | snapshot_id, result_revision_id, metric_definition_version, y nullable, log_loss/brier nullable, exclusion_reason, evaluated_at; unique(snapshot,result_revision,metric_version) |
| Backtest | F | model_version(s), dataset_id, market_dataset_id, strategy_version, config/hash, cutoff_policy, date range, metrics/report artifact, mode reconstructed/observed; подробнее BACKTEST.md |

Target FK не оставлять бесконтрольным polymorphic integer: в реализации выбрать nullable typed FKs с XOR-check (game_id или series_id), а `target_type` проверить CHECK. Все служебные arbitrary JSON source refs валидируются и имеют typed FK через evidence joins.

### Experts и Market

| Сущность | Стадия | Основные поля / связи / ограничения |
|---|---|---|
| Expert | 3 | name, aliases, claimed role, verified_source_accounts; Nix/RAMZES/Solo/NS — кандидаты, не автоматически подтверждённые handles |
| MediaAsset | 3 | source_url/provider_id, author, publication_time, retrieved_at, rights_status, consent_reference, permitted_retention |
| TranscriptSegment | 3 | media_id, speaker_id nullable, start/end offset, text/hash, ASR_version nullable, language, speaker_confidence |
| ExpertOpinion | 3 | expert_id nullable, segment_id, entity_type/id, topic, original_claim, normalized_claim, sentiment, extraction_confidence, explicit_probability nullable, horizon, patch_id nullable, context, available_at, extraction_version, review_status |
| ClaimEvaluation | 3 | opinion_id, evaluation_rule_version, target_id, resolution_time, outcome, disputed/void, evidence; непроверяемая opinion не получает выдуманный score |
| ExpertSignalSnapshot | 3 | cutoff, topic, opinions/evaluations versions, method, weights, uncertainty, dependency clusters |
| CommunitySignal | F | source/entity/topic, timestamp, sentiment, volume, unique-author estimate nullable, bot/dedup policy, availability; не экспертный факт |
| Market | F | provider/bookmaker, target_type/id, market_type, map_number/line, currency, settlement_rules_version; разных рынков не объединять по team name |
| MarketSnapshot | F | market_id, source_quote_time, observed/available_at, status open/suspended/closed, odds_format, raw_payload_id, quote_group_id |
| MarketSelectionQuote | F | snapshot_id, selection_id/team_id, decimal_odds, raw_implied_probability, no_vig_probability nullable, normalization_method, liquidity/limit nullable; обе стороны одной временной группы |
| ModelMarketComparison | F | prediction_snapshot_id, market_snapshot_id, selection_id, p_model, p_market, edge, estimated_EV, validity_reason, decision_at; не изменяет model probability |
| SimulatedBet / Settlement | F | backtest_id, quote_id, selection, stake, accepted_time_assumption, bankroll_lock, result_revision, pnl/commission/void policy; ANALYSIS only, никаких ордеров |

## 5. Invariants и индексы

- FK на team/player/game/evidence/model обязательны в оценённых records; unresolved data остаются в quarantine/raw.
- Probability либо две конечные величины в [0,1] с суммой 1 в пределах заранее зафиксированной численной tolerance, либо abstention с NULL; не NaN.
- Для данного inference idempotency key повтор возвращает тот же snapshot, но новый input revision создаёт новый ключ. Probability не является частью ключа дедупликации.
- `computed_at` не выдаётся за исторический cutoff. Model artifact обучен без будущих labels относительно training cutoff; строгий serving запрещает модель, появившуюся после реального решения.
- Append-only права на snapshots; административная коррекция через supersedes/revocation event. Results могут уточняться без переписывания predictions.
- Индексы: provider lookup; game(series,map); game end/time; performance(player,game); roster(team,valid interval,system interval); snapshot(prediction,computed_at); observation(source,observed_at); source failure queue.
- Не создавать unique(team,player) для всей истории членства — игрок может вернуться. Non-overlap применяется к утверждённой непротиворечивой projection, не ко всем конкурирующим свидетельствам.
- Retention и privacy-source deletion согласуются отдельно; воспроизводимость хранит версию удалённого evidence с redacted/tombstone, а не незаконную копию.

Основания технических ограничений: [PostgreSQL constraints](https://www.postgresql.org/docs/current/ddl-constraints.html), [range types](https://www.postgresql.org/docs/current/rangetypes.html). Связанные документы: FEATURES.md, ML.md, EXPERT_ENGINE.md, LIVE.md, BACKTEST.md.
