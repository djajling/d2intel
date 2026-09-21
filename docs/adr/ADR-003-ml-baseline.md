# ADR-003 — Baseline прежде усложнения

**Статус:** Proposed.

**Контекст:** нужна проверяемая вероятность, а не число моделей. Мало данных и неизвестная полнота roster/patch history.

**Предложение:** первая карта, pre-draft target; constant prior → Logistic Regression → CatBoost CPU challenger. Champion выбирается на temporal tuning folds, не на final test; LR допустим как итог MVP. Calibration и metrics из ML.md обязательны до quality claim. LLM не математический предиктор.

**Альтернативы:** сразу neural/ensemble либо обязательная цепочка всех boosting libraries — откладываются из-за стоимости оценки и сопровождения. Series-win target с первого дня возможен только после отдельного решения владельца и изменения dataset/validation.

**Последствия:** нужны cohort map1, cold-start/fallback, outcome policy, feature availability masks, model/data/code manifests. CatBoost implementation не доказывает superiority.

**Основания:** [calibration](https://scikit-learn.org/stable/modules/calibration.html), [categorical features](https://catboost.ai/docs/en/features/categorical-features).

**Условия принятия:** PRD-001 утверждает target и критерии полезности; ML-001 baseline, ML-002 challenger. Пересмотр — доказанный OOS gain нового подхода на сопоставимых данных.
