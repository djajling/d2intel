"""Метрики качества и честная неопределённость.

Правила проекта:

- На 30 наблюдениях **никаких заявлений о значимости** (BACKLOG §2). Интервал
  считается, но интерпретируется как грубая неопределённость, а не как тест.
- Неопределённость — **grouped bootstrap по сериям/времени**: наблюдения одной
  серии зависимы, обычный bootstrap их занижает.
- Отчёт всегда содержит **порог отсечки** `majority_class_accuracy` — точность
  тривиального прогноза «всегда выбираем большинство». Метрика ниже него
  означает, что модель не добавила ничего.
"""

from __future__ import annotations

import math
import random
from collections.abc import Callable, Sequence
from dataclasses import dataclass

PROB_EPSILON = 1e-15


@dataclass(frozen=True)
class Interval:
    """Точечная оценка и интервал неопределённости (percentile bootstrap)."""

    point: float
    low: float
    high: float
    n: int
    n_groups: int

    def as_dict(self) -> dict[str, float | int]:
        return {
            "point": self.point,
            "low": self.low,
            "high": self.high,
            "n": self.n,
            "n_groups": self.n_groups,
        }


def accuracy(y_true: Sequence[int], y_pred: Sequence[int]) -> float:
    """Доля верных ответов. Пустая выборка — `nan` (не 0 и не 1)."""
    if not y_true:
        return math.nan
    if len(y_true) != len(y_pred):
        raise ValueError("y_true и y_pred разной длины")
    correct = sum(1 for t, p in zip(y_true, y_pred, strict=True) if t == p)
    return correct / len(y_true)


def log_loss(y_true: Sequence[int], y_prob: Sequence[float]) -> float:
    """Средняя логистическая потеря. Вероятности обрезаются по `PROB_EPSILON`."""
    if not y_true:
        return math.nan
    if len(y_true) != len(y_prob):
        raise ValueError("y_true и y_prob разной длины")
    total = 0.0
    for target, prob in zip(y_true, y_prob, strict=True):
        clipped = min(max(prob, PROB_EPSILON), 1.0 - PROB_EPSILON)
        total -= math.log(clipped) if target == 1 else math.log(1.0 - clipped)
    return total / len(y_true)


def majority_class_accuracy(y_true: Sequence[int]) -> float:
    """Точность константного прогноза «всегда большинство» — нижний ориентир."""
    if not y_true:
        return math.nan
    ones = sum(1 for value in y_true if value == 1)
    return max(ones, len(y_true) - ones) / len(y_true)


def brier_score(y_true: Sequence[int], y_prob: Sequence[float]) -> float:
    """Среднеквадратичная ошибка вероятности: mean((p - y)^2). Пусто — `nan`."""
    if not y_true:
        return math.nan
    if len(y_true) != len(y_prob):
        raise ValueError("y_true и y_prob разной длины")
    total = sum(
        (prob - target) ** 2 for target, prob in zip(y_true, y_prob, strict=True)
    )
    return total / len(y_true)


def uniform_log_loss(n: int) -> float:
    """Log loss «ничего не знаю»: p = 0.5 для всех. Равен ln 2 ~ 0.6931.

    Удобная ссылка-ориентир: любая модель, у которой log_loss хуже этого,
    добавляет отрицательную информацию.
    """
    if n <= 0:
        return math.nan
    return math.log(2.0)


def grouped_bootstrap_interval(
    y_true: Sequence[int],
    y_prob: Sequence[float],
    *,
    groups: Sequence[str],
    statistic: Callable[[Sequence[int], Sequence[float]], float],
    n_boot: int = 2000,
    confidence: float = 0.95,
    seed: int = 20260922,
) -> Interval:
    """Percentile bootstrap с пересэмплированием **групп**, не наблюдений.

    Группа — серия или временной блок: наблюдения внутри группы зависимы.
    """
    if not y_true:
        return Interval(point=math.nan, low=math.nan, high=math.nan, n=0, n_groups=0)
    if len(y_true) != len(y_prob) or len(y_true) != len(groups):
        raise ValueError("y_true, y_prob и groups разной длины")

    by_group: dict[str, list[int]] = {}
    for index, group in enumerate(groups):
        by_group.setdefault(group, []).append(index)
    group_keys = sorted(by_group)
    rng = random.Random(seed)

    point = statistic(y_true, y_prob)
    draws: list[float] = []
    for _ in range(n_boot):
        sample_indices: list[int] = []
        for _ in range(len(group_keys)):
            sample_indices.extend(by_group[rng.choice(group_keys)])
        sample_true = [y_true[i] for i in sample_indices]
        sample_prob = [y_prob[i] for i in sample_indices]
        value = statistic(sample_true, sample_prob)
        if not math.isnan(value):
            draws.append(value)
    if not draws:
        return Interval(point=point, low=math.nan, high=math.nan, n=len(y_true), n_groups=len(group_keys))

    draws.sort()
    alpha = (1.0 - confidence) / 2.0
    low_index = int(math.floor(alpha * (len(draws) - 1)))
    high_index = int(math.ceil((1.0 - alpha) * (len(draws) - 1)))
    return Interval(
        point=point,
        low=draws[low_index],
        high=draws[high_index],
        n=len(y_true),
        n_groups=len(group_keys),
    )


def sample_size_verdict(n: int, *, min_n: int = 30) -> str:
    """Вердикт о достаточности выборки. Никаких заявлений о значимости."""
    if n < min_n:
        return f"insufficient evidence: {n} < {min_n} наблюдений"
    return f"sample {n} >= {min_n}, но значимость не заявляется без отдельного решения"
