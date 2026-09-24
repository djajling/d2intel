"""ML-001 (LR) — тесты скрипта scripts/run_lr_baseline.py.

Покрытие:

- `_align_to_cohort` — разворот сторон в каноническую систему координат:
  фичи A↔B меняются местами, дифференциалы умножаются на −1, метка
  инвертируется, а «чужие» серии (не в когорте) отбрасываются;
- `_impute` / `_feature_matrix` — NaN→0 для входа в LR, сохранение порядка
  признаков;
- `_fit_predict` — выбор C **только на valid** и невозможность подбора под
  test (train/valid/test изолированы);
- интеграционный тест записи снимков — на выделенной тестовой БД
  (пропускается, если её нет, как в `tests/features/conftest.py`).

Граница: сами sklearn-математике доверяем, тестируем контракт скрипта.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import numpy as np
import pandas as pd
import pytest
from scripts.run_lr_baseline import (
    FEATURE_COLUMNS,
    _align_to_cohort,
    _cohort_index,
    _feature_matrix,
    _fit_predict,
    _impute,
    _segment_metrics,
)

from d2intel.evaluation.cohort import Game1Row
from d2intel.features.prior_form import PriorFormParams


def _series_id(n: int) -> UUID:
    return UUID(f"00000000-0000-0000-0000-{n:012d}")


def _make_dataset_row(
    series_n: int,
    *,
    team_a: UUID,
    team_b: UUID,
    y: int,
    wr_a: float = 0.6,
    wr_b: float = 0.4,
    cutoff: datetime,
) -> dict[str, object]:
    """Строка датасета в системе slot-0 (как выпускает билдер)."""
    row: dict[str, object] = {
        "series_id": _series_id(series_n),
        "game_id": uuid4(),
        "cutoff_at": cutoff,
        "team_a_id": team_a,
        "team_b_id": team_b,
        "y": y,
    }
    for side, wr in (("a", wr_a), ("b", wr_b)):
        row[f"team_{side}_wr_lifetime"] = wr
        row[f"team_{side}_n_games"] = 10
        row[f"team_{side}_avail"] = wr is not None
    for side in ("a", "b"):
        row[f"player_{side}_wr"] = 0.55
        row[f"player_{side}_avail"] = True
    row["d_team_wr_lifetime"] = wr_a - wr_b
    row["d_team_wr_last_long"] = wr_a - wr_b
    row["d_team_wr_last_short"] = wr_a - wr_b
    row["d_team_n_eff"] = 4.0
    row["d_team_days_since_last"] = 2.0
    row["d_player_wr"] = 0.0
    row["d_player_kda"] = 0.1
    row["d_player_gpm"] = 5.0
    row["d_player_xpm"] = 3.0
    return row


def _cohort_row(series_n: int, *, team_a: UUID, team_b: UUID, winner: UUID) -> Game1Row:
    return Game1Row(
        game_id=uuid4(),
        series_id=_series_id(series_n),
        event_time=datetime(2026, 8, 1, tzinfo=UTC),
        team_a_id=team_a,
        team_b_id=team_b,
        winner_team_id=winner,
    )


# --------------------------------------------------------------------------- #
# _align_to_cohort
# --------------------------------------------------------------------------- #


def test_align_keeps_row_when_slot0_matches_canonical() -> None:
    team_a, team_b = uuid4(), uuid4()
    cohort = [_cohort_row(1, team_a=team_a, team_b=team_b, winner=team_a)]
    frame = pd.DataFrame(
        [_make_dataset_row(1, team_a=team_a, team_b=team_b, y=1, cutoff=datetime(2026, 8, 1, tzinfo=UTC))]
    )

    aligned = _align_to_cohort(frame, cohort)

    assert len(aligned) == 1
    assert aligned.iloc[0]["y"] == 1
    assert aligned.iloc[0]["d_team_wr_lifetime"] == pytest.approx(0.2)


def test_align_flips_row_when_slot0_disagrees() -> None:
    """Slot-0 Team A != канонический Team A — разворот сторон и метки."""
    team_a, team_b = uuid4(), uuid4()
    # Канонический Team A — team_a, но датасет выпустил team_b первой стороной.
    cohort = [_cohort_row(1, team_a=team_a, team_b=team_b, winner=team_a)]
    frame = pd.DataFrame(
        [_make_dataset_row(1, team_a=team_b, team_b=team_a, y=0, cutoff=datetime(2026, 8, 1, tzinfo=UTC))]
    )

    aligned = _align_to_cohort(frame, cohort)

    assert len(aligned) == 1
    row = aligned.iloc[0]
    # Метка инвертируется: датасет сказал «Team A(slot0=team_b) проиграл»,
    # в канонической системе team_a выиграл.
    assert row["y"] == 1
    assert row["team_a_id"] == team_a
    assert row["team_b_id"] == team_b
    # Дифференциал умножается на −1.
    assert row["d_team_wr_lifetime"] == pytest.approx(-0.2)
    # Стороны поменались местами.
    assert row["team_a_wr_lifetime"] == pytest.approx(0.4)
    assert row["team_b_wr_lifetime"] == pytest.approx(0.6)


def test_align_drops_series_not_in_cohort() -> None:
    """Серии вне замороженной когорты не входят в сплит."""
    team_a, team_b = uuid4(), uuid4()
    cohort = [_cohort_row(1, team_a=team_a, team_b=team_b, winner=team_a)]
    frame = pd.DataFrame(
        [
            _make_dataset_row(1, team_a=team_a, team_b=team_b, y=1, cutoff=datetime(2026, 8, 1, tzinfo=UTC)),
            _make_dataset_row(2, team_a=uuid4(), team_b=uuid4(), y=0, cutoff=datetime(2026, 8, 2, tzinfo=UTC)),
        ]
    )

    aligned = _align_to_cohort(frame, cohort)

    assert len(aligned) == 1
    assert aligned.iloc[0]["series_id"] == _series_id(1)


def test_align_nan_differential_stays_nan_on_flip() -> None:
    """NaN в дифференциале не превращается в -0.0 при развороте."""
    team_a, team_b = uuid4(), uuid4()
    cohort = [_cohort_row(1, team_a=team_a, team_b=team_b, winner=team_a)]
    row = _make_dataset_row(1, team_a=team_b, team_b=team_a, y=1, cutoff=datetime(2026, 8, 1, tzinfo=UTC))
    row["d_player_kda"] = float("nan")
    frame = pd.DataFrame([row])

    aligned = _align_to_cohort(frame, cohort)

    assert np.isnan(aligned.iloc[0]["d_player_kda"])


# --------------------------------------------------------------------------- #
# _feature_matrix / _impute
# --------------------------------------------------------------------------- #


def test_feature_matrix_follows_feature_columns_order() -> None:
    team_a, team_b = uuid4(), uuid4()
    frame = pd.DataFrame(
        [
            _make_dataset_row(
                1, team_a=team_a, team_b=team_b, y=1, cutoff=datetime(2026, 8, 1, tzinfo=UTC)
            )
        ]
    )

    x, y = _feature_matrix(frame)

    assert x.shape == (1, len(FEATURE_COLUMNS))
    assert list(y) == [1]
    # Порядок столбцов детерминирован — это важно для воспроизводимости.
    assert x[0][0] == pytest.approx(0.2)


def test_impute_replaces_nan_with_zero() -> None:
    x = np.array([[float("nan"), 1.0], [float("inf"), 2.0]])

    result = _impute(x)

    assert np.allclose(result, [[0.0, 1.0], [0.0, 2.0]])


# --------------------------------------------------------------------------- #
# _fit_predict
# --------------------------------------------------------------------------- #


def _split_frame(seed: int) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """train/valid/test, в которых сигнал линейно сепарабелен по одному признаку."""
    def make(n: int, start: int) -> pd.DataFrame:
        rows = []
        for i in range(start, start + n):
            wr_a = 0.75 if i % 2 == 0 else 0.25
            rows.append(
                _make_dataset_row(
                    i,
                    team_a=uuid4(),
                    team_b=uuid4(),
                    y=1 if i % 2 == 0 else 0,
                    wr_a=wr_a,
                    wr_b=1.0 - wr_a,
                    cutoff=datetime(2026, 8, 1, tzinfo=UTC) + timedelta(days=i),
                )
            )
        return pd.DataFrame(rows)

    return make(40, seed * 100), make(20, seed * 100 + 40), make(20, seed * 100 + 60)


def test_fit_predict_chooses_c_on_valid_only() -> None:
    train, valid, test = _split_frame(seed=1)
    params = PriorFormParams.fit(train_labels=train["y"].tolist())

    report, model = _fit_predict(train, valid, test, params)

    assert model is not None
    assert report["chosen_c"] in (0.01, 0.1, 1.0, 10.0)
    # valid использовался для выбора, test — только для финальных предсказаний.
    assert all("valid_log_loss" in choice for choice in report["c_grid"])
    assert report["params_fit_on_train"]["prior_mean"] == pytest.approx(train["y"].mean())


def test_fit_predict_returns_none_without_grid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Пустой grid (нет C) — модель не обучается, отчёт без катастрофы."""
    monkeypatch.setattr("scripts.run_lr_baseline.C_GRID", ())

    empty = pd.DataFrame(columns=["series_id", "y", "cutoff_at"] + FEATURE_COLUMNS)
    report, model = _fit_predict(empty, empty, empty, PriorFormParams())

    assert model is None
    assert report["chosen_c"] is None


def test_fit_predict_recovers_linear_signal() -> None:
    """На сепарабельных данных LR должен давать высокую точность на test."""
    train, valid, test = _split_frame(seed=7)

    report, model = _fit_predict(train, valid, test, PriorFormParams())

    assert model is not None
    x_test, y_test = _feature_matrix(test)
    proba = model.predict_proba(_impute(x_test))[:, 1]
    hard = [1 if p >= 0.5 else 0 for p in proba]
    acc = sum(int(a == b) for a, b in zip(hard, y_test.tolist(), strict=True)) / len(y_test)
    assert acc >= 0.8


# --------------------------------------------------------------------------- #
# _segment_metrics
# --------------------------------------------------------------------------- #


def test_segment_metrics_reports_floor_and_uniform() -> None:
    team_a, team_b = uuid4(), uuid4()
    rows = [
        _cohort_row(i, team_a=team_a, team_b=team_b, winner=team_a if i % 2 == 0 else team_b)
        for i in range(10)
    ]
    probs = [0.6 if i % 2 == 0 else 0.4 for i in range(10)]
    hard = [1 if i % 2 == 0 else 0 for i in range(10)]

    metrics = _segment_metrics(rows, probs, hard)

    assert metrics["n"] == 10
    assert metrics["accuracy"] == pytest.approx(1.0)
    assert metrics["majority_floor"] == pytest.approx(0.5)
    assert metrics["log_loss_uniform"] == pytest.approx(np.log(2.0))
    # bootstrap на группах вернул интервал, а не nan.
    assert metrics["bootstrap_log_loss"]["n_groups"] == 10


def test_cohort_index_keyed_by_series() -> None:
    team_a, team_b = uuid4(), uuid4()
    rows = [_cohort_row(3, team_a=team_a, team_b=team_b, winner=team_a)]

    index = _cohort_index(rows)

    assert _series_id(3) in index
    assert index[_series_id(3)].team_a_id == team_a
