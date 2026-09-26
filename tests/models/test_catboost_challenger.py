"""ML-002 — тесты challenger'а CatBoost (без БД, на синтетике).

Покрытие по карточке `ML-002` (TESTS):

- выбор параметров идёт только по valid (test в выбор не входит);
- воспроизводимость обучения (фиксированный seed → одинаковые вероятности);
- CatBoost обучается на NaN нативно (зафиксированная политика manifest);
- парный grouped bootstrap: идентичные модели → CI содержит 0, лучшая модель
  → отрицательная разница.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest
from scripts.run_catboost_challenger import (
    paired_log_loss_diff_bootstrap,
    select_best,
    train_catboost,
)

CATBOOST_PARAMS: dict[str, Any] = {
    "iterations": 20,
    "depth": 3,
    "learning_rate": 0.1,
    "l2_leaf_reg": 3.0,
    "loss_function": "Logloss",
    "task_type": "CPU",
    "allow_writing_files": False,
    "verbose": False,
}


def _synthetic(
    n: int = 60, seed: int = 17, with_nan: bool = False
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    x = rng.normal(size=(n, 9))
    if with_nan:
        x[rng.random(size=x.shape) < 0.15] = np.nan
    y = (x[:, 0] + 0.5 * np.nan_to_num(x[:, 5]) > 0).astype(int)
    return x, y


def test_select_best_uses_only_valid_log_loss() -> None:
    """Выбор по valid: лучший на test, но худший на valid не выбирается."""
    results = [
        {
            "depth": 3,
            "valid_log_loss": 0.70,
            "test_accuracy": 0.99,  # заманчиво, но test не участвует в выборе
        },
        {
            "depth": 5,
            "valid_log_loss": 0.65,
            "test_accuracy": 0.10,
        },
    ]
    chosen = select_best(results)
    assert chosen["depth"] == 5


def test_select_best_rejects_empty_grid() -> None:
    with pytest.raises(ValueError):
        select_best([])


def test_catboost_training_is_reproducible() -> None:
    """Фиксированный seed → идентичные вероятности на повторном обучении."""
    x, y = _synthetic()
    first = train_catboost(x, y, CATBOOST_PARAMS, seed=17).predict_proba(x)[:, 1]
    second = train_catboost(x, y, CATBOOST_PARAMS, seed=17).predict_proba(x)[:, 1]
    np.testing.assert_allclose(first, second)


def test_catboost_handles_nan_natively() -> None:
    """Политика manifest: NaN не импутируются, обучение и предикт работают."""
    x, y = _synthetic(with_nan=True)
    assert np.isnan(x).any()
    model = train_catboost(x, y, CATBOOST_PARAMS, seed=17)
    proba = model.predict_proba(x)[:, 1]
    assert np.isfinite(proba).all()


def test_paired_bootstrap_identical_models_contains_zero() -> None:
    """Идентичные вероятности → парная разница 0, CI содержит 0."""
    x, y = _synthetic()
    probs = train_catboost(x, y, CATBOOST_PARAMS, seed=17).predict_proba(x)[:, 1].tolist()
    labels = y.tolist()
    groups = [index % 10 for index in range(len(labels))]
    result = paired_log_loss_diff_bootstrap(labels, probs, probs, groups, n_boot=200)
    assert result["ci95_lower"] <= 0.0 <= result["ci95_upper"]


def test_paired_bootstrap_better_model_gives_negative_diff() -> None:
    """Заведомо лучшая модель → отрицательная парная разница."""
    x, y = _synthetic(n=200, seed=5)
    labels = y.tolist()
    groups = [index % 20 for index in range(len(labels))]
    good = [0.9 if label == 1 else 0.1 for label in labels]
    bad = [0.1 if label == 1 else 0.9 for label in labels]
    result = paired_log_loss_diff_bootstrap(
        labels, good, bad, groups, n_boot=200  # challenger=good, baseline=bad
    )
    assert result["mean_diff"] < 0
    assert result["ci95_upper"] < 0


def test_paired_bootstrap_length_mismatch_raises() -> None:
    with pytest.raises(ValueError):
        paired_log_loss_diff_bootstrap([1, 0], [0.5], [0.5], [1, 2])


def test_feature_matrix_segments_align_with_protocol() -> None:
    """Матрица признаков: только FEATURE_COLUMNS в порядке manifest, метка int."""
    from scripts.run_catboost_challenger import FEATURE_COLUMNS, _feature_matrix

    frame = pd.DataFrame(
        {
            **{name: [0.1, -0.2] for name in FEATURE_COLUMNS},
            "y": [1, 0],
            "series_id": ["s1", "s2"],
        }
    )
    x, y = _feature_matrix(frame, FEATURE_COLUMNS)
    assert x.shape == (2, len(FEATURE_COLUMNS))
    assert y.tolist() == [1, 0]
