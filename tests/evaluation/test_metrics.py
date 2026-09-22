"""Метрики: точность, log loss, ориентир большинства, grouped bootstrap."""

from __future__ import annotations

import math

import pytest

from d2intel.evaluation.metrics import (
    accuracy,
    grouped_bootstrap_interval,
    log_loss,
    majority_class_accuracy,
    sample_size_verdict,
)


def test_accuracy_counts_matches() -> None:
    assert accuracy([1, 0, 1], [1, 0, 0]) == pytest.approx(2 / 3)


def test_accuracy_on_empty_is_nan_not_zero() -> None:
    """Пустая выборка — не «0% точности», а отсутствие измерения."""
    assert math.isnan(accuracy([], []))


def test_accuracy_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError, match="разной длины"):
        accuracy([1, 0], [1])


def test_log_loss_is_finite_on_confident_wrong_answer() -> None:
    """Вероятность 0 не должна давать бесконечность — она обрезается."""
    value = log_loss([1], [0.0])
    assert math.isfinite(value)
    assert value > 0


def test_log_loss_punishes_confident_mistakes() -> None:
    wrong = log_loss([1, 0], [0.01, 0.99])
    right = log_loss([1, 0], [0.99, 0.01])
    assert wrong > right


def test_majority_baseline_is_the_floor() -> None:
    assert majority_class_accuracy([1, 1, 0]) == pytest.approx(2 / 3)
    assert majority_class_accuracy([1, 0]) == pytest.approx(0.5)


def test_bootstrap_is_deterministic_for_a_seed() -> None:
    y = [1, 0, 1, 1, 0, 0]
    p = [0.6, 0.4, 0.7, 0.8, 0.3, 0.2]
    groups = ["a", "a", "b", "c", "c", "d"]
    first = grouped_bootstrap_interval(
        y, p, groups=groups, statistic=accuracy, n_boot=200, seed=7
    )
    second = grouped_bootstrap_interval(
        y, p, groups=groups, statistic=accuracy, n_boot=200, seed=7
    )
    assert first.as_dict() == second.as_dict()


def test_bootstrap_interval_is_ordered_and_reports_groups() -> None:
    y = [1, 0, 1, 1, 0, 0, 1, 0]
    p = [0.6, 0.4, 0.7, 0.8, 0.3, 0.2, 0.55, 0.45]
    groups = ["a", "a", "b", "c", "c", "d", "d", "e"]
    interval = grouped_bootstrap_interval(
        y, p, groups=groups, statistic=accuracy, n_boot=300, seed=1
    )
    assert interval.low <= interval.high
    assert interval.n == 8
    assert interval.n_groups == 5


def test_bootstrap_rejects_length_mismatch() -> None:
    with pytest.raises(ValueError, match="разной длины"):
        grouped_bootstrap_interval([1, 0], [0.5], groups=["a", "b"], statistic=accuracy)


def test_small_sample_verdict_is_insufficient_evidence() -> None:
    assert "insufficient evidence" in sample_size_verdict(10)


def test_large_sample_still_makes_no_significance_claim() -> None:
    verdict = sample_size_verdict(500)
    assert "insufficient" not in verdict
    assert "значимость" in verdict
