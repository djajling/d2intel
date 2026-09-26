"""EVAL-001 — оценка исходов на frozen test с корректной неопределённостью.

Правило вердикта (карточка EVAL-001 + ADR-007): frozen test даёт вердикт
`sufficient evidence` только если измеренная точность достигает порога,
заранее выбранного в PRD (G-MODEL, 0.70), и объём достаточен для измерения
(n >= 30). Иначе — `insufficient evidence`, а не «успех». На малых выборках
заявления о статистической значимости не делаются: интервалы bootstrap —
грубая неопределённость, не тест.

Bootstrap группируется по сериям и по временным корзинам (ISO-неделя
event_time), а не по отдельным картам: карты одной серии зависимы.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

from d2intel.evaluation.metrics import (
    accuracy,
    brier_score,
    grouped_bootstrap_interval,
    log_loss,
    majority_class_accuracy,
    sample_size_verdict,
    uniform_log_loss,
)

ECE_BINS = 10


def expected_calibration_error(
    y_true: Sequence[int], y_prob: Sequence[float], *, n_bins: int = ECE_BINS
) -> float:
    """ECE: взвешенная по бинам |доля класса 1 − средняя вероятность|.

    Ровные бины по предсказанной вероятности [0, 1]. Диагностическая метрика
    калибровки, не гейт (калибровка — CAL-002/003).
    """
    if len(y_true) != len(y_prob):
        raise ValueError("длины выборок не совпадают")
    if not y_prob:
        raise ValueError("пустая выборка")
    bin_sum_acc = [0.0] * n_bins
    bin_sum_conf = [0.0] * n_bins
    bin_count = [0] * n_bins
    for label, prob in zip(y_true, y_prob, strict=True):
        index = min(int(prob * n_bins), n_bins - 1)
        bin_sum_acc[index] += float(label)
        bin_sum_conf[index] += float(prob)
        bin_count[index] += 1
    total = len(y_prob)
    return sum(
        (bin_count[index] / total)
        * abs(
            bin_sum_acc[index] / bin_count[index] - bin_sum_conf[index] / bin_count[index]
        )
        for index in range(n_bins)
        if bin_count[index] > 0
    )


def _week_bucket(moment: datetime) -> str:
    """ISO-неделя как временная корзина для grouped bootstrap."""
    iso = moment.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def evaluate_outcomes(
    labels: Sequence[int],
    probs: Sequence[float],
    series_groups: Sequence[Any],
    event_times: Sequence[datetime],
    *,
    threshold_accuracy: float,
    prd_reference: str,
    min_n: int = 30,
    n_boot: int = 2000,
    seed: int = 17,
) -> dict[str, Any]:
    """Итоговая оценка исходов на frozen test: метрики + интервалы + вердикт.

    `series_groups` — идентификаторы серий (bootstrap по сериям), `event_times`
    — моменты карт (временные корзины ISO-недели для второго bootstrap).
    Вердикт и оговорки формулируются без заявлений о статистической
    значимости.
    """
    sizes = {len(labels), len(probs), len(series_groups), len(event_times)}
    if len(sizes) != 1:
        raise ValueError("длины выборок не совпадают")
    if not labels:
        raise ValueError("пустая выборка")

    labels_list = [int(item) for item in labels]
    probs_list = [float(item) for item in probs]
    hard = [1 if p >= 0.5 else 0 for p in probs_list]
    series_list = list(series_groups)
    time_groups = [_week_bucket(moment) for moment in event_times]

    def _bootstrap(groups: list[Any], statistic: Any) -> dict[str, Any]:
        return grouped_bootstrap_interval(
            labels_list, probs_list, groups=groups, statistic=statistic, n_boot=n_boot, seed=seed
        ).as_dict()

    measured = accuracy(labels_list, hard)
    n = len(labels_list)
    volume_ok = n >= min_n
    threshold_met = measured >= threshold_accuracy
    verdict = "sufficient evidence" if (threshold_met and volume_ok) else "insufficient evidence"

    return {
        "n": n,
        "metrics": {
            "accuracy": measured,
            "log_loss": log_loss(labels_list, probs_list),
            "brier": brier_score(labels_list, probs_list),
            "expected_calibration_error": expected_calibration_error(labels_list, probs_list),
            "log_loss_uniform": uniform_log_loss(n),
            "majority_floor": majority_class_accuracy(labels_list),
        },
        "bootstrap_log_loss_by_series": _bootstrap(series_list, log_loss),
        "bootstrap_log_loss_by_time": _bootstrap(time_groups, log_loss),
        "bootstrap_brier_by_series": _bootstrap(series_list, brier_score),
        "n_series": len(set(map(str, series_list))),
        "n_time_buckets": len(set(time_groups)),
        "verdict": {
            "outcome": verdict,
            "threshold_accuracy": threshold_accuracy,
            "prd_reference": prd_reference,
            "threshold_met": threshold_met,
            "volume_ok": volume_ok,
            "sample_note": sample_size_verdict(n, min_n=min_n),
            "no_significance_claim": (
                "Заявления о статистической значимости не делаются: интервалы "
                "bootstrap — описание неопределённости, не тест гипотезы."
            ),
        },
    }
