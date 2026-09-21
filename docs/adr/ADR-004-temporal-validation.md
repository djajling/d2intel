# ADR-004 — Временная валидация и доступность данных

**Статус:** Proposed, обязательное условие честной оценки после принятия.

**Предложение:** отдельно хранить event/source-publication/observed/ingested/available times. Strict feature <= cutoff по фактической доступности. Историю, полученную сейчас, считать retrospective_reconstructed с отдельной assumed-availability policy, без backdating observed_at.

**Split:** calendar/series train → tuning → calibration → untouched test; crossing series purge; все transforms внутри train fold; model selection до test; calibration не на train. Final test используется один раз. Поздние outcomes/roster corrections не переписывают прошлые feature snapshots.

**Альтернативы:** random split и latest-views проще, но не соответствуют будущему serving и не принимаются как доказательство качества.

**Последствия:** потребуется больше audit metadata и честный статус insufficient evidence на малой выборке. Отсутствие leakage в коде не доказывает historical availability, если источник её не архивировал.

**Основания:** [TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html), [calibration guide](https://scikit-learn.org/stable/modules/calibration.html). Group/calendar splitter проектируется отдельно.

**Приёмка:** tests из ML.md, критерии PRD-001, проверка DATA-001/FEAT-001/ML-001. Любая критическая утечка блокирует переход этапа.
