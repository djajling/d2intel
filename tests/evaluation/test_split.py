"""Временные сплиты: только по времени, с разрывом и целостностью групп."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from d2intel.evaluation.split import (
    SplitSpec,
    assert_groups_do_not_straddle,
    assign_split,
    expanding_window_folds,
    segment_bounds,
)

T0 = datetime(2026, 9, 1, tzinfo=UTC)


def _spec(**kwargs: timedelta) -> SplitSpec:
    return SplitSpec(valid_from=T0, test_from=T0 + timedelta(days=10), **kwargs)


def test_earlier_is_train() -> None:
    assert assign_split(T0 - timedelta(days=1), _spec()) == "train"


def test_later_is_test() -> None:
    assert assign_split(T0 + timedelta(days=11), _spec()) == "test"


def test_middle_is_valid() -> None:
    assert assign_split(T0 + timedelta(days=5), _spec()) == "valid"


def test_embargo_excludes_observations_near_bounds() -> None:
    """Соседние по времени наблюдения исключаются, а не «подсказывают»."""
    spec = _spec(embargo=timedelta(days=2))
    assert assign_split(T0, spec) is None
    assert assign_split(T0 + timedelta(days=1), spec) is None
    assert assign_split(T0 + timedelta(days=3), spec) == "valid"
    assert assign_split(T0 + timedelta(days=9), spec) is None


def test_spec_rejects_wrong_order() -> None:
    with pytest.raises(ValueError, match="позже"):
        SplitSpec(valid_from=T0, test_from=T0)


def test_spec_rejects_negative_embargo() -> None:
    with pytest.raises(ValueError, match="отрицательным"):
        SplitSpec(valid_from=T0, test_from=T0 + timedelta(days=1), embargo=timedelta(days=-1))


def test_group_straddling_is_rejected() -> None:
    with pytest.raises(ValueError, match="расщеплена"):
        assert_groups_do_not_straddle(groups=["series-1", "series-1"], splits=["train", "test"])


def test_group_inside_one_segment_is_allowed() -> None:
    assert_groups_do_not_straddle(groups=["series-1", "series-1"], splits=["train", "train"])


def test_excluded_observations_do_not_count_as_straddling() -> None:
    assert_groups_do_not_straddle(groups=["series-1", "series-1"], splits=["train", None])


def test_folds_are_empty_on_tiny_sample() -> None:
    """На двух наблюдениях фолд не строим: честнее сказать «мало данных»."""
    assert expanding_window_folds([T0, T0 + timedelta(days=1)], n_folds=3) == []


def test_folds_expand_and_keep_order() -> None:
    times = [T0 + timedelta(days=i) for i in range(30)]
    folds = expanding_window_folds(times, n_folds=2)
    assert folds, "на 30 наблюдениях фолды должны строиться"
    for fold in folds:
        assert fold.valid_from < fold.test_from
    assert folds[-1].valid_from >= folds[0].valid_from


def test_segment_bounds_are_ordered() -> None:
    bounds = segment_bounds(_spec(embargo=timedelta(days=1)))
    assert bounds["train"][1] <= bounds["valid"][0]
    assert bounds["valid"][1] <= bounds["test"][0]
