"""Временные сплиты: train/valid/test по времени, без перемешивания.

Правила:

1. Сплит **только по времени** (`event_time`). Никакого случайного
   перемешивания: случайный сплит на временных данных — это утечка.
2. Между сегментами — **embargo** (разрыв). Наблюдения, попавшие в разрыв,
   исключаются: иначе соседние по времени матчи одной серии/турнира оказываются
   по разные стороны границы и «подсказывают» друг друга.
3. Одна серия не должна расщепляться между сегментами. Проверка группировки —
   в `assert_groups_do_not_straddle`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal

SplitName = Literal["train", "valid", "test"]


@dataclass(frozen=True)
class SplitSpec:
    """Границы сегментов по времени и разрыв между ними.

    `valid_from` — начало valid-сегмента (конец train),
    `test_from` — начало test-сегмента (конец valid).
    Интервалы полуоткрытые: train = [.., valid_from), valid = [valid_from, test_from),
    test = [test_from, ..).
    """

    valid_from: datetime
    test_from: datetime
    embargo: timedelta = timedelta(0)

    def __post_init__(self) -> None:
        if self.test_from <= self.valid_from:
            raise ValueError("test_from должен быть позже valid_from")
        if self.embargo < timedelta(0):
            raise ValueError("embargo не может быть отрицательным")


def assign_split(event_time: datetime, spec: SplitSpec) -> SplitName | None:
    """Определить сегмент для наблюдения. `None` — наблюдение в разрыве (исключено)."""
    if event_time < spec.valid_from:
        return "train"
    if event_time >= spec.test_from:
        return "test"
    # Внутри valid-сегмента или в разрыве вокруг границ.
    if event_time < spec.valid_from + spec.embargo:
        return None
    if event_time >= spec.test_from - spec.embargo:
        return None
    return "valid"


def segment_bounds(spec: SplitSpec) -> dict[str, tuple[datetime | None, datetime | None]]:
    """Полуоткрытые границы сегментов с учётом embargo (для отчётов и SQL)."""
    train_end = spec.valid_from - spec.embargo
    valid_start = spec.valid_from + spec.embargo
    valid_end = spec.test_from - spec.embargo
    test_start = spec.test_from
    return {
        "train": (None, train_end),
        "valid": (valid_start, valid_end),
        "test": (test_start, None),
    }


def assert_groups_do_not_straddle(
    *, groups: list[str], splits: list[SplitName | None]
) -> None:
    """Проверить, что группа (серия/турнир) не расщепляется между сегментами.

    Исключённые наблюдения (`None`) расщеплением не считаются.
    """
    if len(groups) != len(splits):
        raise ValueError("groups и splits разной длины")
    seen: dict[str, SplitName] = {}
    for group, split in zip(groups, splits, strict=True):
        if split is None:
            continue
        previous = seen.get(group)
        if previous is not None and previous != split:
            raise ValueError(
                f"группа {group} расщеплена между {previous} и {split}: "
                "серии/турниры не должны попадать в разные сегменты"
            )
        seen[group] = split


def expanding_window_folds(
    times: list[datetime],
    *,
    n_folds: int = 3,
    embargo: timedelta = timedelta(0),
    min_train: int = 1,
) -> list[SplitSpec]:
    """Расширяющееся окно: train растёт, test — следующий блок времени.

    Возвращает `n_folds` спеки. В каждой фолде train — всё, что раньше
    valid-блока, test — последний блок. Если данных меньше `min_train + 2`,
    фолды не строятся (возвращается пустой список): на малой выборке честнее
    сказать «недостаточно данных», чем получить фолду из одного наблюдения.
    """
    if n_folds < 1:
        raise ValueError("n_folds должен быть >= 1")
    ordered = sorted(set(times))
    if len(ordered) < min_train + 2:
        return []

    # Режем упорядоченное время на (n_folds + 1) примерно равных блоков.
    n_blocks = n_folds + 1
    block_size = len(ordered) / n_blocks
    folds: list[SplitSpec] = []
    for fold in range(1, n_blocks):
        valid_index = int(round(fold * block_size))
        test_index = int(round((fold + 1) * block_size))
        if valid_index <= min_train or valid_index >= test_index:
            continue
        if test_index > len(ordered) - 1:
            test_index = len(ordered) - 1
        valid_from = ordered[valid_index]
        test_from = ordered[test_index]
        if test_from <= valid_from:
            continue
        folds.append(
            SplitSpec(valid_from=valid_from, test_from=test_from, embargo=embargo)
        )
    return folds
