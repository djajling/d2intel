"""CAL-001/CAL-002 — четырёхчастный протокол калибровки и калибраторы.

Части по времени (серии не пересекаются по построению: в когорте у серии
ровно одна game1-строка): train-core → tuning (ранняя valid) → calibration
(поздняя valid) → untouched test. Границы train/valid/test берутся из
замороженного сплита и не меняются; calibration вырезается из хвоста valid,
поэтому test остаётся нетронутым, а модель калибруется на данных, которые
она не видела при обучении (модель для калибровки переобучается на
train-core). Между tuning и calibration действует тот же embargo, что и
между остальными сегментами.

Метод калибровки (Platt/isotonic) выбирается 2-фолдным cross-fitting ВНУТРИ
calibration-части: фит на половине, метрика на другой, потом свап. Test в
выборе метода не участвует.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

from d2intel.evaluation.outcomes import expected_calibration_error

CAL_ECE_BINS = 10


@dataclass(frozen=True)
class CalibrationSplit:
    """Границы четырёх частей (все — моменты карт, UTC-aware)."""

    train_core_to: datetime  # train-core: event_time < train_core_to
    tuning_from: datetime  # tuning: train_core_to + embargo <= t < cal_from
    cal_from: datetime  # calibration: cal_from <= t < test_from
    test_from: datetime
    embargo: timedelta
    counts: dict[str, int] = field(default_factory=dict)

    def assign(self, event_time: datetime) -> str:
        """Часть по моменту карты; между tuning и calibration — embargo-разрыв."""
        if event_time < self.train_core_to:
            return "train_core"
        if event_time < self.tuning_from:
            return "purge_train_tuning"
        if event_time < self.cal_from:
            return "tuning"
        if event_time < self.test_from:
            return "calibration"
        return "test"

    def to_dict(self) -> dict[str, Any]:
        return {
            "train_core_to": self.train_core_to.isoformat(),
            "tuning_from": self.tuning_from.isoformat(),
            "cal_from": self.cal_from.isoformat(),
            "test_from": self.test_from.isoformat(),
            "embargo_seconds": self.embargo.total_seconds(),
            "counts": dict(self.counts),
        }


def carve_calibration_split(
    valid_from: datetime,
    test_from: datetime,
    embargo: timedelta,
    *,
    cal_frac: float = 0.5,
) -> CalibrationSplit:
    """Вырезать calibration из хвоста valid: [valid_from, test_from) → tuning+cal.

    `cal_frac` — доля длительности valid, отдаваемая под calibration
    (по умолчанию половина). Embargo между tuning и calibration — тот же,
    что между основными сегментами.
    """
    if not 0.0 < cal_frac < 1.0:
        raise ValueError("cal_frac должен быть в (0, 1)")
    span = (test_from - valid_from).total_seconds()
    cal_from = test_from - timedelta(seconds=span * cal_frac)
    tuning_from = cal_from - embargo
    return CalibrationSplit(
        train_core_to=tuning_from,
        tuning_from=tuning_from,
        cal_from=cal_from,
        test_from=test_from,
        embargo=embargo,
    )


def fit_platt(y_true: Sequence[int], y_prob: Sequence[float], seed: int = 17) -> LogisticRegression:
    """Platt-калибровка: логистическая регрессия на логитах вероятностей."""
    p = _clip_probs(y_prob)
    logits = np.log(p / (1.0 - p)).reshape(-1, 1)
    model = LogisticRegression(C=1e6, solver="lbfgs", max_iter=1000, random_state=seed)
    model.fit(logits, np.asarray(y_true, dtype=int))
    return model


def fit_isotonic(y_true: Sequence[int], y_prob: Sequence[float]) -> IsotonicRegression:
    """Изотоническая регрессия: монотонное отображение, минимум Brier на выборке."""
    iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    iso.fit(_clip_probs(y_prob), np.asarray(y_true, dtype=int))
    return iso


def apply_platt(model: LogisticRegression, y_prob: Sequence[float]) -> np.ndarray:
    p = _clip_probs(y_prob)
    return model.predict_proba(np.log(p / (1.0 - p)).reshape(-1, 1))[:, 1]


def apply_isotonic(model: IsotonicRegression, y_prob: Sequence[float]) -> np.ndarray:
    return np.asarray(model.predict(_clip_probs(y_prob)), dtype=float)


def cross_fit_select(
    y_true: Sequence[int],
    y_prob: Sequence[float],
    *,
    seed: int = 17,
) -> dict[str, Any]:
    """Выбор метода 2-фолдным cross-fitting внутри calibration-части.

    Фит на половине (по чётности индекса — детерминированный сплит без
    перемешивания), метрика log_loss на другой, затем фолды меняются местами;
    итог — средний log_loss метода по двум фолдам. Test не участвует.
    """
    from d2intel.evaluation.metrics import log_loss

    y = list(y_true)
    p = list(y_prob)
    fold_a_idx = list(range(0, len(y), 2))
    fold_b_idx = list(range(1, len(y), 2))
    if not fold_a_idx or not fold_b_idx:
        raise ValueError("calibration-часть слишком мала для cross-fitting")

    results: dict[str, Any] = {}
    for name in ("platt", "isotonic"):
        losses: list[float] = []
        for train_idx, eval_idx in ((fold_a_idx, fold_b_idx), (fold_b_idx, fold_a_idx)):
            if name == "platt":
                cal = fit_platt([y[i] for i in train_idx], [p[i] for i in train_idx], seed=seed)
                transformed = apply_platt(cal, [p[i] for i in eval_idx])
            else:
                cal = fit_isotonic([y[i] for i in train_idx], [p[i] for i in train_idx])
                transformed = apply_isotonic(cal, [p[i] for i in eval_idx])
            losses.append(
                log_loss([y[i] for i in eval_idx], [float(v) for v in transformed])
            )
        results[name] = {
            "fold_log_losses": losses,
            "mean_log_loss": float(np.mean(losses)),
        }
    best = min(results, key=lambda name: results[name]["mean_log_loss"])
    return {"methods": results, "chosen": best, "rule": "min mean cross-fit log_loss"}


def calibration_report(
    y_true: Sequence[int], probs_before: Sequence[float], probs_after: Sequence[float]
) -> dict[str, Any]:
    """Метрики до/после калибровки (без significance-заявлений)."""
    from d2intel.evaluation.metrics import brier_score, log_loss

    y = list(y_true)
    return {
        "n": len(y),
        "before": {
            "log_loss": log_loss(y, list(probs_before)),
            "brier": brier_score(y, list(probs_before)),
            "ece": expected_calibration_error(y, list(probs_before), n_bins=CAL_ECE_BINS),
        },
        "after": {
            "log_loss": log_loss(y, list(probs_after)),
            "brier": brier_score(y, list(probs_after)),
            "ece": expected_calibration_error(y, list(probs_after), n_bins=CAL_ECE_BINS),
        },
    }


def _clip_probs(values: Sequence[float], eps: float = 1e-6) -> np.ndarray:
    """Вероятности в (0, 1): логит не определён на границах."""
    return np.clip(np.asarray(values, dtype=float), eps, 1.0 - eps)
