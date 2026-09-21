# ML Architecture и протокол доказательств

Статус: PROPOSED. Модели не обучены; метрик проекта ещё нет. Заявления reference-репозиториев не считаются нашими результатами.

## 1. Target и прогноз

MVP: бинарный outcome первой сыгранной карты Series, Team A/B зафиксированы canonical identity, прогноз до draft. Не вероятность победы серии. Forfeit/void/no-contest не имеют обычного label. Если неизвестно, действительно ли карта первая, sample quarantined/excluded с причиной.

Первая тренировочная таблица содержит одну строку на eligible game1 и фиксированный cutoff; map2+ не подмешиваются молча. Истории всех прошлых карт разрешены для Team/Player form при соблюдении cutoff. Для будущих series/live целей создаются отдельные training cohorts, метрики и target contracts.

Side-neutral вход: дифференциалы A−B, known side только если она действительно известна на cutoff. Для симметрии тестируем P(A,B)=1−P(B,A). При необходимости применяем symmetrization `(f(A,B)+1−f(B,A))/2`, затем калибруем/проверяем итоговую процедуру; нельзя после calibration незаметно изменить probability. Минимальный LR на антисимметричных features с подходящим intercept contract упрощает проверку.

## 2. Порядок моделей

1. Constant prior и симметричный нейтральный baseline; при canonical A/B полезен именно контроль 0.5, а не идентичность алфавитного порядка.
2. Logistic Regression на небольшом Team/Player prior-form + availability features; Elo — дополнительный challenger/признак, только обновляемый после доступного результата.
3. CatBoost CPU — challenger полного MVP. Обучить и сравнить, но **не делать обязательным победителем**. Если LR лучше/надёжнее, он остаётся champion.
4. XGBoost/LightGBM — только дополнительное экспериментальное сравнение, не обязательная лестница из всех библиотек.
5. Neural/ensemble — после установленного gain, достаточного датасета и приемлемого сопровождения.

CatBoost обработка категориальных признаков не решает temporal leakage автоматически. Team/player IDs могут запоминать эпохи; нужны cold-team/roster/patch cohorts и ablation. Описание метода: [categorical features](https://catboost.ai/docs/en/features/categorical-features).

## 3. Два режима истории

**retrospective_reconstructed:** история скачана сейчас; в прошлом доступны лишь event times/предположения о lag. Future outcomes target исключены, но факт исторической доступности источника не доказан. Сохраняются actual observed_at и отдельная assumed_available_at с policy. Этот режим помогает отладить модель, не доказывает честную прибыль или реальный прошлый forecast.

**prospective_observed / observed_replay:** данные реально накоплены нашей системой; available_at для всех зависимостей ≤ cutoff. Прогноз сохранён до фактического начала draft, результат приходит позже. Это основа честного shadow validation.

Не объединять метрики этих режимов в одну цифру. Ретроспективный prediction computed_at = сейчас; UI не backdate. Для live replay per-minute состояния reconstructed и фактические наблюдения также различаются.

## 4. Temporal validation

```text
прошлое ----------------------------------------------------> будущее
[train] [tuning / rolling folds] [calibration] [frozen test]
 fit     choose features/model     fit map       report once
```

- Границы по calendar time и группам Series, не случайные строки. Все snapshots одной карты/серии в одной оценочной группе. Серия, пересекающая boundary, purge либо целиком позднее по заранее выбранной политике.
- Train labels должны уже быть доступны к training cutoff; поздно завершившиеся/исправленные серии не просачиваются.
- Scaling, imputation, encoders, feature selection и feature priors fit только train каждого fold. Hyperparameters и champion выбираются только tuning.
- Calibration block позже training/tuning, не используется для fit основной модели. Выбор метода calibration — внутри tuning, не по final test. Base-model затем не переобучать незаметно после calibration.
- Untouched test вскрывается один раз для gate, не для выбора winner. Провал → статус провал/insufficient evidence; новые изменения требуют будущего test window, а не повторного «untouched».
- Split/group manifest хранит record IDs, boundaries, exclusions, feature schema и code hash. Нерегулярные игры требуют собственного calendar/group splitter: стандартный [TimeSeriesSplit](https://scikit-learn.org/stable/modules/generated/sklearn.model_selection.TimeSeriesSplit.html) не обеспечивает grouping и документирует equally-spaced допущение для сравнимых интервалов.
- Tournament holdout/cold-team test — дополнительный stress test, не замена temporal evaluation. Совпадение команды в train/test не само по себе leakage: важно, какая информация была известна.

## 5. Обязательные leakage-тесты

1. Добавление будущих матчей/коррекций/трансферов не меняет ранее построенный strict snapshot.
2. Target final KDA/GPM/outcome/duration/actual roster не доступны pre-match feature query.
3. При неизвестном roster обучающий пример получает тот же fallback/mask, что serving; не использовать фактическую пятёрку целевой карты как будто известную заранее.
4. Текущий hero winrate/patch dictionary/expert evaluation не подставляются в старые cutoffs.
5. Feature hash повторяем; не используются latest-views без version/as-of filter.
6. Model artifact не обучен на test; обучение/cалибровка/feature extraction time manifests согласованы.
7. Live sequence не содержит future timestep, padding по финальной duration, terminal outcome или статистики события после cutoff.
8. Same series snapshots не оказываются в разных splits. Mean score считается с равным весом игр/зафиксированных horizons, а не количеством кадров.
9. Finite probability, unknown category/hero/patch, team swap, cold roster, missing source, cancelled game дают определённый результат/abstention.

## 6. Метрики и calibration

Для n допустимых независимых target instances: y_i ∈ {0,1}, p_i = P(A wins).

- **Brier** = (1/n) Σ(p_i−y_i)²; фиксируем бинарную шкалу [0,1].
- **Log loss** = −(1/n) Σ[y_i ln p_i + (1−y_i) ln(1−p_i)]; численный clipping ε фиксируется в metric version и не скрывает экстремальные raw p.
- **ECE** = Σ_b (n_b/n)·|mean(p)_b−mean(y)_b|; binning policy фиксируется, показываются n_b и uncertainty.
- Reliability diagram + histogram forecast probabilities; accuracy/AUC — вторичные.

Brier и log loss оценивают вероятностное качество в целом, не только calibration; меньше Brier не обязательно означает лучше reliability. ECE зависит от binning/sample size и не должен быть единственным gate. Основание: [scikit-learn calibration guide](https://scikit-learn.org/stable/modules/calibration.html), [Brier](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.brier_score_loss.html), [log loss](https://scikit-learn.org/stable/modules/generated/sklearn.metrics.log_loss.html).

Начальный calibrator: identity vs sigmoid на отдельном block; isotonic — только при достаточной выборке и OOS advantage. Не использовать случайную CV по умолчанию. Храним uncalibrated и calibrated outputs в evaluation report; production snapshot хранит реально показанную вероятность и calibration version.

Сравнение моделей: paired per-game loss difference, confidence intervals block bootstrap по сериям/времени с sensitivity по турнирам. Порог meaningful gain, confidence level, test precision и minimum coverage фиксируются до test в PRD-001. Недостаточно данных → insufficient evidence, не «модель не хуже» по отсутствию значимости. 30 operational fixtures из PRODUCT.md не заменяют statistical test.

Отчёт по cohorts: patch, league tier из evidence, roster certainty, time horizon, missingness, cold starts; counts и исключения обязательны. Метрики на отобранных прогнозах сопровождаются abstention/coverage.

## 7. Model registry и serving

ModelVersion: artifact checksum, algorithm, hyperparameters, training interval, dataset/split manifest, dependency lock, feature schema, seed, calibrator, promotion decision. На CPU возможны малые численные отличия — tolerance фиксируется тестом, не обещается bitwise identity любой среды.

Champion заморожен до следующего offline evaluation; новые данные не запускают автоматическое обучение/промо в MVP. Drift monitoring сообщает об изменении patch/feature distributions и quality; решение retrain/rollback принимается владельцем. Откат возвращает предыдущую связку model+features+calibrator, не только binary.

## 8. Live и ensemble — Future

Live tabular baseline по доступным minute/state features и отдельной calibration по horizons либо time-aware calibrator. Не сравнивать last-minute accuracy с pre-match accuracy. Temporal model лишь после train/serve parity и OOS выигрыша с одинаковыми срезами.

Ensemble: Team/Player/Draft/Patch/Tournament/Live/Expert outputs генерируются out-of-fold временно; meta-model видит только OOF predictions при fit. Stacking на in-sample вероятностях запрещён. Statistical/model/expert/community сигналы сохраняются раздельно. Final ensemble probability калибруется как отдельная модель.

Добавление экспертов/рынка не может менять саму формулировку «независимая модель vs рынок»: если market входит в features, это отдельный market-aware model и он не выдаётся за независимый edge estimate.
