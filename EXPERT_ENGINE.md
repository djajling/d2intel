# Expert Architecture

Статус: PROPOSED, MVP 3. Это самостоятельный слой свидетельств, не замена статистической модели.

## 1. Разделить четыре вида информации

- **Observed data:** игровые факты, подтверждённые источником.
- **Model signal:** расчёт на определённом feature snapshot.
- **Expert opinion:** утверждение конкретного человека с контекстом и датой.
- **Community signal:** измерение дискуссии; не факт и не экспертный консенсус.

Nix, RAMZES, Solo, NS и другие pro players/coaches/analysts/casters — кандидаты в Expert registry. Имена не означают найденные официальные каналы, разрешение на использование или качество мнений. Verified accounts и право на корпус проверяются отдельной задачей.

## 2. Права прежде автоматизации

Первый корпус: предоставленные владельцем/экспертом либо явно разрешённые текстовые интервью/транскрипты. Сохранять author/source, право обработки, допустимые цитаты, retention и attribution. Публично просматриваемый ролик не означает право скачать, транскрибировать и хранить его целиком.

[YouTube captions.download](https://developers.google.com/youtube/v3/docs/captions/download) требует надлежащей авторизации; API metadata не является универсальным API чужих транскриптов. [Twitch API guide](https://dev.twitch.tv/docs/api/guide/) описывает metadata/access/quotas, а не автоматическое предоставление прав на контент. Условия и найденные ограничения — SOURCES.md. Если бесплатного правомерного корпуса нет — gate no-go; не обходить доступ и не обещать извлечение всех стримов.

LLM/ASR adapters: локальный вариант при достаточных ресурсах или уже доступный разрешённый бесплатный endpoint. Выбор лицензии, требований к памяти и качества — отдельный benchmark. Платный API не закладывается. «Локально» не означает нулевую стоимость CPU/GPU и сопровождения.

## 3. Pipeline

```text
MediaAsset + rights policy
          ↓
разрешённый Transcript / ASR
          ↓
speaker attribution + segmentation
          ↓
LLM extraction в строгую schema
          ↓
entity linking / temporal checks / validation
          ↓
review / quarantine
          ↓
ExpertOpinion → проверяемый claim → ClaimEvaluation
```

Начать с текстового корпуса без speaker diarization, затем добавить ASR. Повторный extraction одного segment/version имеет dedup key; изменение prompt/model создаёт новую revision, не переписывает прошлое мнение.

### Поля opinion

expert_id (nullable при неизвестном speaker), segment_id, original_claim, normalized_claim, entity_type/id, topic, sentiment, extraction_confidence, explicit_probability (только явно произнесённая), source_url, publication_time, segment_start/end, observed_at, available_at, patch_id (nullable), match/series context, horizon, conditions, extraction_version, review_status, evidence span/hash.

`extraction_confidence` оценивает уверенность извлечения/атрибуции, **не** вероятность истинности и не доверие эксперту. Число из LLM по умолчанию не калибровано: либо заменить review status, либо проверить на размеченном корпусе. «Команда выглядит лучше» не превращается в 0.7 win probability. Чужая цитата, сарказм, условное предсказание и пересказ отделяются от собственного утверждения speaker.

Темы: player skill, current form, hero pool/strength, draft, team strength/weakness, meta, patch, strategy, lane, teamfight, synergy, roster, tournament, match prediction. Multi-label разрешён; неизвестная тема — other/uncertain, а не насильственная классификация.

## 4. QA извлечения

Размеченный вручную небольшой корпус с редкими/отрицательными случаями, отдельные train/development/test по источнику и времени. Проверки: precision/recall обнаружения opinion, topic F1, entity-link accuracy, speaker attribution, faithful claim rate, точность time offsets, доля unsupported extractions и duplicate rate. Порог допуска фиксируется до просмотра held-out корпуса.

LLM не имеет доступа к записывающим инструментам/секретам и не исполняет инструкции внутри транскрипта. Только bounded input → schema output; отклонение malformed JSON и hallucinated entity IDs. Утверждения без точного source span не публикуются.

## 5. Track record

Claim score допустим лишь если до события определены target, horizon, settlement rule и проверяемый outcome. ClaimEvaluation хранит result evidence, unresolved/disputed/void и версию правила. Постфактум выбирать удобную интерпретацию нельзя.

- Explicit probabilistic claims: Brier/log loss на сопоставимых бинарных событиях, counts, uncertainty; сравнение с baseline той же темы/горизонта.
- Categorical predictions: accuracy и coverage, не выдумывать исходную probability. Не смешивать с probabilistic score.
- Качественные утверждения: unscored либо заранее согласованный observable criterion; «талантливый» не получает автоматическое true/false.
- Разрезы topic/patch/role/horizon только с sample size, shrinkage и широкими интервалами при редкости. Не назначать «рейтинг доверия 9/10».

Оценка эксперта, использованная в cutoff t, включает только resolved claims, доступные до t. Результат сегодняшнего прогноза эксперта не влияет на его вчерашний вес. Пересказы одного источника кластеризуются: десять копий не десять независимых мнений.

## 6. Consensus и ML

Первый consensus — доли/число независимых мнений по теме, freshness и coverage, не вероятность исхода. Если есть численные probabilistic forecasts на одном target, исследовать recency-weighted aggregation со shrinkage. Performance weights либо прозрачны и фиксированы заранее, либо обучены на past OOF claims; не подгонять на исходах той же серии.

Экспертный слой сначала **только отдельная панель**. Интеграция в модель — после достаточного корпуса, temporal availability test, ablation и OOS gain. Сохранять ExpertSignalSnapshot с точными claim/evaluation versions; не подавать сегодняшние резюме стримеров в исторические forecasts.

## 7. LLM analyst — позже

На вход: только структурированные evidence-backed profiles, model output/attributions, cutoff, evidence IDs и обозначенные мнения. На выход: explanation claims с `evidence_refs`, типом data/model/opinion и confidence/limitations. Версионировать prompt, schema, generation engine и исходный bundle.

Генератор не пересчитывает probability и не придумывает statistics. Validator сверяет числа/units/entities/source refs; unsupported claim отклоняется. Fallback — шаблонное объяснение. Feature attribution не является доказательством причинности.

## 8. Community — Future

Twitch chat, YouTube comments, Reddit, Telegram и social media только после отдельного rights/access gate. Aggregate sentiment/volume с source/time/topic/entity и dedup/bot-policy. Не сохранять лишние персональные данные. API-доступ, получение удалённых публикаций и легальность хранения не предполагаются автоматически.
