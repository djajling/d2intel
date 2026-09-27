"""ML-003 (драфт-модель) — тесты чистых функций раннера, без БД и обучения.

Держат протокол ADR-007:

* фоллбэки «нет данных» → 0.5, а не 0 (отсутствие истории ≠ проигрыш);
* frozen test — последние по времени игры, сплит невозможен при тесной когорте;
* majority_class_accuracy считается и обязательно попадает в отчёт;
* вердикт при недостижении формулируется точно по п.4, без подгонки порога.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from scripts.run_draft_model import (
    grouped_bootstrap_ci,
    hero_winrate,
    majority_accuracy,
    mean_or_neutral,
    split_by_time,
    team_winrate,
    verdict,
)

T0 = datetime(2026, 9, 21, 12, 0, 0)


def _rows(n: int, won: bool = True, start: datetime = T0) -> list[tuple[datetime, str, bool]]:
    return [(start + timedelta(hours=i), "patch-x", won) for i in range(n)]


def test_hero_winrate_prefers_same_patch_when_enough_observations() -> None:
    same = [True, True, True, False]  # 3 из 4 → 0.75
    assert hero_winrate(same, [True] * 100) == pytest.approx(0.75)


def test_hero_winrate_falls_back_to_all_history_below_min_obs() -> None:
    # На патче всего 2 наблюдения → берём всю историю до T.
    same = [True, False]
    any_patch = [True, True, True, False]  # 0.75
    assert hero_winrate(same, any_patch) == pytest.approx(0.75)


def test_hero_winrate_without_history_is_neutral_not_zero() -> None:
    """«Нет данных» не подменяется нулём:0.5, а не 0."""
    assert hero_winrate([], []) == 0.5


def test_team_winrate_requires_min_games() -> None:
    assert team_winrate([True, False]) == 0.5  # 2 < 3 → нет информации
    assert team_winrate([True, True, False]) == pytest.approx(2 / 3)
    assert team_winrate([]) == 0.5


def test_mean_or_neutral_handles_empty_composition() -> None:
    assert mean_or_neutral([]) == 0.5
    assert mean_or_neutral([0.4, 0.6]) == pytest.approx(0.5)


def _game(event_time: datetime, y: int) -> dict:
    return {"event_time": event_time, "y": y, "series_id": "s"}


def test_split_puts_latest_games_into_test() -> None:
    rows = [_game(T0 + timedelta(hours=i), i % 2) for i in range(71)]
    train, test = split_by_time(rows, 30)
    assert len(train) == 41
    assert len(test) == 30
    # frozen test — самые поздние по времени
    assert max(r["event_time"] for r in test) > max(r["event_time"] for r in train)
    assert min(r["event_time"] for r in test) >= max(r["event_time"] for r in train)


def test_split_refuses_when_test_would_consume_everything() -> None:
    rows = [_game(T0 + timedelta(hours=i), 0) for i in range(30)]
    with pytest.raises(ValueError):
        split_by_time(rows, 30)


def test_majority_accuracy_is_mandatory_baseline() -> None:
    assert majority_accuracy([0, 1, 0, 1]) == 0.5
    assert majority_accuracy([1, 1, 1, 0]) == 0.75
    assert majority_accuracy([]) == 0.0


def test_verdict_below_threshold_reports_value_and_interval() -> None:
    text = verdict(accuracy=0.633, threshold=0.70, ci=(0.433, 0.828))
    assert "порог не достигнут" in text
    assert "0.633" in text
    assert "0.433" in text and "0.828" in text


def test_verdict_at_threshold_counts_as_reached() -> None:
    text = verdict(accuracy=0.70, threshold=0.70, ci=(0.5, 0.9))
    assert "порог достигнут" in text


def test_bootstrap_is_seeded_and_bounded() -> None:
    pairs = [("s1", 1, 1), ("s1", 0, 1), ("s2", 1, 1), ("s2", 0, 0)]
    first = grouped_bootstrap_ci(pairs, replicates=200, seed=17)
    second = grouped_bootstrap_ci(pairs, replicates=200, seed=17)
    assert first == second  # воспроизводимость
    assert 0.0 <= first[0] <= first[1] <= 1.0


def test_bootstrap_groups_by_series_not_by_example() -> None:
    """Карты одной серии не независимы — ресемплируются целыми сериями.

    Серия s1 угадана полностью, s2 — мимо. Ресемплинг серий даёт ровно
    три исхода (0.0 / 0.5 / 1.0), поэтому интервал размыт до предела —
    ровно то, чего нельзя достичь, если ресемплировать карты по отдельности.
    """
    pairs = [("s1", 1, 1)] * 10 + [("s2", 0, 1)] * 10
    low, high = grouped_bootstrap_ci(pairs, replicates=300, seed=17)
    assert (low, high) == (0.0, 1.0)
