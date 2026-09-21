# Market Architecture и Backtest Engine

Статус: PROPOSED, Future, **ANALYSIS ONLY**. Источник бесплатных исторических timestamped odds не подтверждён. Реальных ставок, прибыли проекта и результатов backtest нет.

## 1. Два разных backtest

- **Prediction evaluation** входит уже в MVP: насколько вероятности соответствуют исходам, независимо от рынка.
- **Market backtest** появляется только после model gate и правомерного odds dataset: могли ли решения на доступных котировках дать результат после маржи/комиссии/ограничений.

Accuracy, calibration, prediction quality, edge и profitability — разные свойства. Положительный edge модели не доказывает прибыльность.

## 2. Source/access gate

Требования к market dataset: provider, bookmaker/venue, target game/series, market/selection, quote timestamp, actual observation timestamp, открытость/приостановка, обе стороны одной котировки, тип odds, settlement rules, исправления, разрешённое использование/хранение. Для live также synchronization/latency и доступность выполнения по цене.

Сначала оценить разрешённый бесплатный API либо предоставленный владельцем законный CSV с реальными данными. CSV — интерфейс импорта, **не существующий датасет и не предложение подставить demo**. Без источника — no-go market layer. Не собирать HTML в обход ToS; не регистрировать платные услуги. PandaScore stats free исключён до письменного подтверждения допустимости betting-related анализа — даже личный ANALYSIS не снимает ограничений (SOURCES.md).

## 3. Pipeline и разделение источников

```text
правомерные odds → raw quote → validation/market mapping
  → MarketSnapshot + selections
  → as-of join с независимым PredictionSnapshot
  → ModelMarketComparison → simulation → audit report
```

Bookmaker != market. Game winner != series winner. Map handicap/series total не сравниваются с бинарной game1 model. Разные BO/void rules/валюты/selection definitions не объединяются. Не строить «лучшую пару коэффициентов» из разных bookmakers и объявлять её маржой одного рынка.

## 4. Вероятности, маржа, edge

Для одного полного взаимоисключающего binary рынка с decimal odds o_A,o_B > 1:

- q_A = 1/o_A; q_B = 1/o_B — raw implied probabilities.
- overround = q_A + q_B − 1.
- простая пропорциональная no-vig оценка: p_market,A = q_A/(q_A+q_B); p_market,B аналогично.
- edge_A = p_model,A − p_market,A, в долях либо процентных пунктах, unit всегда указан.
- ожидаемый net return на единицу stake при отсутствии комиссий: EV_A = p_model,A·o_A − 1.

No-vig — оценка распределения маржи, не наблюдаемая «истинная вероятность рынка». Проверить sensitivity к методам de-vig позже. При неполной котировке/несогласованных timestamp честного paired no-vig нет — NULL+reason, не нормализация случайных сторон. Underround/аномалии помечаются, не автоматически «арбитраж».

Для комиссии c только с выигрыша одиночной ставки: EV = p·(o−1)·(1−c) − (1−p). Это лишь конкретная commission convention; биржевое net-market settlement моделируется отдельным rule, не этой формулой по умолчанию.

Положительный edge против no-vig не равен положительному EV по доступным odds после маржи. Модель может ошибаться; uncertainty/confidence не превращается в универсальную вероятность «ставка верна».

Справочные формулы: [implied probability](https://help.smarkets.com/hc/en-gb/articles/214058369-How-to-calculate-implied-probability-in-betting), [margins](https://help.smarkets.com/hc/en-gb/articles/214180145-How-to-calculate-betting-margins), [expected value](https://help.smarkets.com/hc/en-gb/articles/214554985-How-to-calculate-expected-value-in-betting). Это справка по математике, не одобрение доступа к данным или обещание доходности.

## 5. Исполнитель исторической симуляции

Конфигурация: date range, eligible tournaments, target/market, model version, prediction mode, minimum edge, maximum odds, minimum data-quality/uncertainty requirement, stake strategy, bankroll, maximum simultaneous exposure, fees, latency/slippage, settlement rules и closing-line definition. Каждый параметр versioned.

События обрабатываются по доступности, а не по знаниям из конца периода:

1. Подгрузить только model/feature/quote versions, доступные на decision time.
2. Проверить рынок, статус, свежесть, pre-draft target и допустимость quote. Для честного model-vs-market сравнения forecast cutoff не позже decision, quote available_at не позже decision; older forecasts помечены age.
3. Применить заранее замороженную стратегию; не брать несколько почти одинаковых snapshots одной позиции как независимые bets без стратегии увеличения позиции.
4. Зарезервировать stake из free bankroll; незавершённые одновременные события блокируют капитал. Не тратить будущий выигрыш до settlement.
5. Outcome resolver учитывает void/forfeit/remake/перенос/правила bookmaker. Corrections сохраняются revision, а не стирают аудит.
6. Сохранить decision, rejected reason, quote, model snapshot, stake и settlement. Никаких API ордеров.

Первый stake baseline — заранее фиксированный flat stake с капитал-ограничением. Kelly/оптимизация ставки не нужны для доказательства прогнозного сигнала; добавлять только как sensitivity после калибровки, без обещаний дохода. Minimum confidence — определённая заранее data-quality или interval-width policy, не само значение p и не LLM confidence.

## 6. Метрики с точными определениями

Пусть s_i — stake, π_i — net settled P&L, N — число не-void settled decisions (void count показывается отдельно).

- bets/wins/losses/void/pending/rejected — раздельно; win rate = wins/(wins+losses), не включая void.
- profit = Σπ_i после комиссий и расходов модели исполнения.
- turnover = Σs_i по settled non-void bets; ROI = profit/turnover. При 0 turnover → undefined.
- profit factor = Σmax(π_i,0) / |Σmin(π_i,0)|; при отсутствии убытков → undefined/infinite с count, не доказанная устойчивость.
- Equity E_t = initial bankroll + cumulative settled P&L; free cash и reserved stakes показываются отдельно. Peak H_t = max_{u≤t} E_u; max drawdown absolute = max_t(H_t−E_t); relative = max_t((H_t−E_t)/H_t) при H_t>0. Mark-to-market equity — другой режим, не смешивать.
- **CLV odds ratio** = o_taken/o_close − 1 для той же selection/market/settlement и принятой closing timestamp definition. Positive означает более высокий взятый decimal odds, не гарантирует прибыль.
- **CLV probability delta**, если нужна: p_close,no-vig − p_taken,no-vig; другая единица/смысл, хранить отдельно. Нет законной closing line — CLV = NULL с coverage, не substitute by result.
- Brier/log loss/calibration для всех пригодных forecasts и отдельно выбранных bets; показывать selection bias и размер обеих выборок.

Confidence intervals: блоки по времени/series/tournament, sensitivity к зависимым рынкам и correlated bets. Резкое различие ROI одного турнира и остальных — риск нестабильности, не сигнал подгонять фильтр.

## 7. Out-of-sample и gate

Strategy tuning только внутри старого training/tuning market периода; следующий test заморожен. Model selection, calibration, edge threshold и stake strategy не выбираются по итоговому ROI test. Закрывающая линия используется для диагностики после, не как доступная ранее feature. Одна удачная история недостаточна.

Раздельные режимы:
- reconstructed историческая симуляция с предположением о доступности/исполнении;
- observed shadow decisions с реально накопленными timestamped snapshots;
- actual execution здесь отсутствует и не заявляется.

Нет timestamps, market matching, условий исполнения или достаточного sample → «невозможно подтвердить», не «прибыльно». Market module может остаться исследовательским навсегда; автоматизация ставок не входит ни в текущую задачу, ни в этот план.

## 8. Тесты

Golden cases: бинарная выплата/проигрыш/void, комиссия, несогласованные стороны, stale quote, wrong map/series, suspend, missing close, repeated snapshot, concurrent bets, empty denominator, model trained after decision, late correction, timezone/DST, floating precision. Stake/money хранить в фиксированной денежной точности по currency policy; raw odds сохранять без преждевременного округления.
