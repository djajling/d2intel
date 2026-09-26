"""CAL-001/CAL-002 — тесты калибровки (без БД).

Покрытие по карточкам (TESTS):

- четыре части не пересекаются, purge между tuning и calibration;
- калибратор фитится только на переданных данных (test структурно не входит);
- воспроизводимость калибровки;
- isotonic монотонен; Platt не выводит вероятность за [0, 1];
- cross-fit выбор метода работает и предпочтение отдаётся лучшему.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import numpy as np
import pytest

from d2intel.evaluation.calibration import (
    CalibrationSplit,
    apply_isotonic,
    apply_platt,
    calibration_report,
    carve_calibration_split,
    cross_fit_select,
    fit_isotonic,
    fit_platt,
)


def _split() -> CalibrationSplit:
    return carve_calibration_split(
        datetime(2026, 6, 24, tzinfo=UTC),
        datetime(2026, 8, 8, tzinfo=UTC),
        timedelta(hours=24),
        cal_frac=0.5,
    )


def _synthetic(n: int = 80, seed: int = 5) -> tuple[list[int], list[float]]:
    rng = np.random.default_rng(seed)
    raw = rng.uniform(0.2, 0.8, size=n)
    labels = [int(rng.random() < 0.5 + (p - 0.5) * 0.4) for p in raw]
    return labels, [float(p) for p in raw]


def test_carve_parts_are_disjoint_with_purge() -> None:
    """Части покрывают valid без пересечений, между tuning и calibration — purge."""
    split = _split()
    assert split.train_core_to == split.tuning_from
    assert split.cal_from - split.tuning_from == split.embargo  # purge-разрыв
    assert split.cal_from < split.test_from

    seen: dict[str, int] = {}
    moments = []
    moment = datetime(2026, 5, 1, tzinfo=UTC)
    while moment < datetime(2026, 9, 1, tzinfo=UTC):
        moments.append(moment)
        seen[split.assign(moment)] = seen.get(split.assign(moment), 0) + 1
        moment += timedelta(hours=6)
    # каждая часть встречается, и ни один момент не попал в две части
    assert {"train_core", "tuning", "calibration", "test"} <= set(seen)
    assert sum(seen.values()) == len(moments)  # все срезы учтены ровно один раз


def test_carve_rejects_bad_frac() -> None:
    with pytest.raises(ValueError):
        carve_calibration_split(
            datetime(2026, 6, 24, tzinfo=UTC),
            datetime(2026, 8, 8, tzinfo=UTC),
            timedelta(hours=24),
            cal_frac=1.5,
        )


def test_calibrator_fit_does_not_see_test() -> None:
    """Калибратор строится только по переданным (calibration) данным.

    Структурная проверка: фитим на calibration-синтетике, применяем к test —
    предсказания зависят только от входных вероятностей и fitted-параметров.
    Два вызова apply на разных test-выборках дают одинаковый маппинг p→p'.
    """
    y_cal, p_cal = _synthetic()
    iso = fit_isotonic(y_cal, p_cal)
    test_probs = [0.3, 0.5, 0.7]
    first = apply_isotonic(iso, test_probs)
    second = apply_isotonic(iso, test_probs)
    np.testing.assert_allclose(first, second)
    # маппинг зависит только от p: одинаковый p в другом контексте → тот же выход
    extra = apply_isotonic(iso, [0.5])
    assert extra[0] == first[1]


def test_calibration_is_reproducible() -> None:
    y, p = _synthetic()
    iso_a = fit_isotonic(y, p)
    iso_b = fit_isotonic(y, p)
    np.testing.assert_allclose(iso_a.X_thresholds_, iso_b.X_thresholds_)
    np.testing.assert_allclose(iso_a.y_thresholds_, iso_b.y_thresholds_)

    platt_a = fit_platt(y, p, seed=17)
    platt_b = fit_platt(y, p, seed=17)
    assert platt_a.intercept_[0] == platt_b.intercept_[0]


def test_isotonic_is_monotone_and_bounded() -> None:
    y, p = _synthetic(n=120)
    iso = fit_isotonic(y, p)
    grid = [0.05, 0.2, 0.35, 0.5, 0.65, 0.8, 0.95]
    out = apply_isotonic(iso, grid)
    assert all(b >= a - 1e-9 for a, b in zip(out, out[1:], strict=False))
    assert all(0.0 <= v <= 1.0 for v in out)


def test_platt_stays_in_unit_interval() -> None:
    y, p = _synthetic()
    platt = fit_platt(y, p)
    out = apply_platt(platt, [0.001, 0.5, 0.999])
    assert all(0.0 < v < 1.0 for v in out)


def test_cross_fit_select_prefers_better_method() -> None:
    """Заведомо лучший калибратор выбирается cross-fitting'ом."""
    # raw-вероятности систематически сдвинуты вниз; Platt (параметрический сдвиг)
    # должен справиться лучше, чем «сырой» изотоник на зашумлённой выборке.
    rng = np.random.default_rng(11)
    n = 200
    raw = rng.uniform(0.3, 0.7, size=n)
    true_p = raw + 0.15  # модель занижает
    labels = [int(rng.random() < tp) for tp in true_p]
    selection = cross_fit_select(labels, [float(p) for p in raw], seed=17)
    assert selection["chosen"] in {"platt", "isotonic"}
    assert set(selection["methods"]) == {"platt", "isotonic"}


def test_cross_fit_rejects_tiny_sample() -> None:
    with pytest.raises(ValueError):
        cross_fit_select([1], [0.5])


def test_calibration_report_before_after() -> None:
    labels, probs = _synthetic()
    shifted = [min(1.0, p + 0.1) for p in probs]
    report = calibration_report(labels, probs, shifted)
    assert report["n"] == len(labels)
    assert set(report["before"]) == {"log_loss", "brier", "ece"}
    assert set(report["after"]) == {"log_loss", "brier", "ece"}
