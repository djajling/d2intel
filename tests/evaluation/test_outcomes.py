"""EVAL-001 — тесты оценки исходов (без БД).

Покрытие по карточке `EVAL-001` (TESTS):

- группировка bootstrap по сериям и по времени (не по картам);
- вердикт `insufficient evidence` на малой выборке и при непопадании в порог;
- отсутствие significance-заявлений в отчёте;
- ECE: совершенная калибровка → ~0, систематически самоуверенная модель → высокое.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from d2intel.evaluation.outcomes import evaluate_outcomes, expected_calibration_error

THRESHOLD = 0.70


def _inputs(
    n: int = 40, seed: int = 3
) -> tuple[list[int], list[float], list[int], list[datetime]]:
    import numpy as np

    rng = np.random.default_rng(seed)
    labels = [int(item) for item in rng.integers(0, 2, size=n)]
    probs = [round(float(item), 4) for item in rng.uniform(0.35, 0.65, size=n)]
    series = [index // 2 for index in range(n)]  # карты внутри серий зависимы
    start = datetime(2026, 6, 1, tzinfo=UTC)
    times = [start + timedelta(days=index % 30) for index in range(n)]
    return labels, probs, series, times


def test_verdict_insufficient_when_below_threshold() -> None:
    """Точность ниже порога PRD → insufficient evidence, даже при n ≥ 30."""
    labels, probs, series, times = _inputs()
    report = evaluate_outcomes(
        labels,
        probs,
        series,
        times,
        threshold_accuracy=THRESHOLD,
        prd_reference="PRD G-MODEL",
    )
    assert report["verdict"]["outcome"] == "insufficient evidence"
    assert report["verdict"]["threshold_met"] is False
    assert report["verdict"]["volume_ok"] is True


def test_verdict_sufficient_when_threshold_met() -> None:
    """Идеальный прогноз при n ≥ 30 → sufficient evidence."""
    labels, _probs, series, times = _inputs()
    report = evaluate_outcomes(
        labels,
        [float(label) for label in labels],
        series,
        times,
        threshold_accuracy=THRESHOLD,
        prd_reference="PRD G-MODEL",
    )
    assert report["verdict"]["outcome"] == "sufficient evidence"


def test_verdict_insufficient_on_small_sample() -> None:
    """Малая выборка (n < 30) → insufficient evidence при любом качестве."""
    labels, probs, series, times = _inputs(n=20)
    report = evaluate_outcomes(
        labels,
        [float(label) for label in labels],
        series,
        times,
        threshold_accuracy=THRESHOLD,
        prd_reference="PRD G-MODEL",
    )
    assert report["verdict"]["outcome"] == "insufficient evidence"
    assert report["verdict"]["volume_ok"] is False


def test_bootstrap_groups_by_series_and_time() -> None:
    """Группы фиксируются: n_series < n наблюдений, временные корзины есть."""
    labels, probs, series, times = _inputs(n=40)
    report = evaluate_outcomes(
        labels,
        probs,
        series,
        times,
        threshold_accuracy=THRESHOLD,
        prd_reference="PRD G-MODEL",
    )
    assert report["n_series"] < report["n"]
    assert report["n_time_buckets"] > 1
    assert set(report["bootstrap_log_loss_by_series"]) >= {"low", "high", "point"}
    assert set(report["bootstrap_log_loss_by_time"]) >= {"low", "high", "point"}


def test_report_contains_no_significance_claims() -> None:
    """Чек-лист карточки: секции метрик не содержат заявлений о значимости."""
    labels, probs, series, times = _inputs()
    report = evaluate_outcomes(
        labels,
        probs,
        series,
        times,
        threshold_accuracy=THRESHOLD,
        prd_reference="PRD G-MODEL",
    )
    assert report["verdict"]["no_significance_claim"]
    # Слово «значим» допустимо только в дисклеймерах вердикта, не в метриках.
    metrics_dump = str(report["metrics"]) + str(report["bootstrap_log_loss_by_series"])
    assert "значим" not in metrics_dump.lower()
    assert "significant" not in metrics_dump
    assert "p-value" not in metrics_dump


def test_ece_perfect_and_overconfident() -> None:
    """ECE: вероятности = частотам → 0; самоуверенные ошибки → высокое."""
    labels = [1, 1, 1, 1, 0, 0, 0, 0]
    calibrated = [1.0, 1.0, 1.0, 1.0, 0.0, 0.0, 0.0, 0.0]
    assert expected_calibration_error(labels, calibrated) == pytest.approx(0.0)

    overconfident_wrong = [0.99] * 4 + [0.99] * 4  # всегда 0.99 при 50% доле
    value = expected_calibration_error(labels, overconfident_wrong)
    assert value > 0.4


def test_ece_length_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        expected_calibration_error([1, 0], [0.5])
