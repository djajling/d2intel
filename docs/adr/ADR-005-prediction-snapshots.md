# ADR-005 — Неизменяемые снимки с первого прототипа

**Статус:** Proposed.

**Контекст:** без evidence и model version невозможно доказать, что вероятность действительно была рассчитана на указанных данных до события. Поэтому перенос snapshots целиком в MVP 2 неприемлем для проверяемого прототипа.

**Предложение:** immutable Prediction как target contract; append-only PredictionSnapshot с cutoff/computed time, model version, FeatureSnapshot, roster/draft/expert/market state refs, режимом historical/prospective, probability/abstention и idempotency key. Минимум сразу, расширенные draft/live states позднее.

**Альтернативы:** mutable current_probability проще, но не воспроизводим. Полное event-sourcing всего приложения — лишняя сложность; достаточно версий критических фактов и prediction ledger.

**Последствия:** API читает только committed snapshots; повторный request не создаёт дубль; новый input revision — новый snapshot. Result correction создаёт новую PredictionEvaluation, старое предсказание не меняется. Юридически обязательное удаление evidence отмечается tombstone и потерей полной воспроизводимости.

**Приёмка:** DB-001 ограничения, API-001 запись/чтение, повторный расчёт, snapshot hash, evidence FK, отсутствие backdating. Gate не означает, что forecast полезен: качество проверяется отдельно ML.md.
