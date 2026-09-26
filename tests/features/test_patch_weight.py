"""PATCH-002 — тесты весовой функции патчей и масок.

Покрытие по карточке `PATCH-002` (TESTS):

- fit-only-train: `PriorFormParams.fit` не подгоняет patch_decay из данных
  (это гиперпараметр, выбираемый на tuning-фолдах прогоном обучения);
- затухание по патч-расстоянию: d=0 → 1.0, дальше `patch_decay ** d`;
- различение masking vs zero: неизвестный патч цели — отдельная маска
  `target_patch_unknown`, а не «нулевой вес, притворившийся данными»;
- воспроизводимость весов;
- legacy-совместимость: `patch_decay=None` → same/other (модели до PATCH-002).
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from d2intel.features.prior_form import PriorFormParams, patch_weight


def _params(**overrides) -> PriorFormParams:
    return PriorFormParams(patch_decay=0.7, **overrides)


def test_patch_decay_by_distance() -> None:
    """Затухание: d=0 → 1.0, d=1 → decay, d=2 → decay²; порядок не важен."""
    params = _params()
    order = {"p1": 0, "p2": 1, "p3": 2}
    assert patch_weight("p1", "p1", params, order) == pytest.approx(1.0)
    assert patch_weight("p2", "p1", params, order) == pytest.approx(0.7)
    assert patch_weight("p3", "p1", params, order) == pytest.approx(0.49)
    assert patch_weight("p1", "p3", params, order) == pytest.approx(0.49)


def test_unknown_patch_uses_other_weight_with_mask() -> None:
    """Неизвестный патч цели/игры → patch_other_weight; маска — в строке ряда.

    Маскирование (нет данных) отличается от нулевого значения: вес
    `patch_other_weight` ≠ 0, а факт неизвестности фиксируется отдельным
    полем `target_patch_unknown` (`_row_to_dict`), не подменяя вес нулём.
    """
    params = _params(patch_other_weight=0.6)
    order = {"p1": 0}
    assert patch_weight(None, "p1", params, order) == pytest.approx(0.6)
    assert patch_weight("p1", None, params, order) == pytest.approx(0.6)
    assert patch_weight(uuid4(), "p1", params, order) == pytest.approx(0.6)


def test_legacy_mode_without_decay() -> None:
    """patch_decay=None → legacy same/other (совместимость с моделями до 002)."""
    params = PriorFormParams(patch_decay=None, patch_same_weight=1.0, patch_other_weight=0.6)
    order = {"p1": 0, "p2": 1, "p3": 2}
    assert patch_weight("p1", "p1", params, order) == pytest.approx(1.0)
    assert patch_weight("p2", "p1", params, order) == pytest.approx(0.6)
    assert patch_weight("p3", "p1", params, order) == pytest.approx(0.6)  # d=2 всё ещё 0.6


def test_weights_are_reproducible() -> None:
    """Одни и те же входы → один и тот же вес (воспроизводимость)."""
    params = _params()
    order = {"p1": 0, "p2": 1}
    first = patch_weight("p2", "p1", params, order)
    second = patch_weight("p2", "p1", params, order)
    assert first == second


def test_fit_does_not_fit_patch_decay_from_data() -> None:
    """AC #1: patch_decay — не данных-фит. `fit` восстанавливает только μ."""
    labels = [1, 0, 1, 1, 0]
    params = PriorFormParams.fit(train_labels=labels)
    assert params.patch_decay is None  # не «обучился» из данных
    assert params.prior_mean == pytest.approx(sum(labels) / len(labels))


def test_decay_requires_order_map() -> None:
    """Без patch_order даже с patch_decay → legacy same/other (безопасный фолбэк)."""
    params = _params()
    assert patch_weight("p2", "p1", params, None) == pytest.approx(params.patch_other_weight)
