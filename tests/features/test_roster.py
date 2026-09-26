"""TEAM-002 — тесты prior-known roster признаков (без БД).

Покрытие по карточке `TEAM-002` (TESTS):

- отсутствие данных → fallback (все значения None, маска `False`);
- целевой ростер не читается: свидетельства матча-цели исключены явно;
- as-of: будущее/поздно-доступное свидетельство не учитывается;
- математика окон: changes_30d, standin_share_30d, min_window;
- воспроизводимость.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from d2intel.features.roster import (
    RosterMembershipRow,
    roster_form,
)

CUTOFF = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
LAG = timedelta(hours=4)


def _row(
    *,
    team=None,
    player=None,
    game=None,
    days_ago: float = 10.0,
    standin: bool | None = False,
    available_lag: timedelta = LAG,
) -> RosterMembershipRow:
    moment = CUTOFF - timedelta(days=days_ago)
    return RosterMembershipRow(
        team_id=team or uuid4(),
        player_id=player or uuid4(),
        game_id=game or uuid4(),
        is_standin=standin,
        event_time=moment,
        available_at=moment + available_lag,
    )


def test_no_data_falls_back_to_none_and_mask_false() -> None:
    """AC #2: нет ростерных свидетельств → fallback, не нули."""
    form = roster_form([], team_id=uuid4(), cutoff=CUTOFF, result_lag=LAG)
    assert form.avail is False
    assert form.days_since_last is None
    assert form.changes_30d is None
    assert form.standin_share_30d is None


def test_target_roster_is_not_read() -> None:
    """AC #5: свидетельства матча-цели исключены — prior known roster only."""
    team = uuid4()
    target_game = uuid4()
    rows = [
        _row(team=team, game=target_game, days_ago=1.0, standin=False),
        _row(team=team, game=uuid4(), days_ago=10.0, standin=False),
    ]
    form = roster_form(
        rows, team_id=team, cutoff=CUTOFF, result_lag=LAG, exclude_game_id=target_game
    )
    # без исключения последним свидетельством был бы целевой матч (1 день)
    assert form.days_since_last == pytest.approx(10.0)


def test_future_and_not_yet_available_rows_excluded() -> None:
    """as-of (event_asof): событие после cutoff или с assumed-доступностью
    позже cutoff (свежее result_lag) — не признаки; фактический available_at
    в реконструкции не используется (политика lag-policy.v1)."""
    team = uuid4()
    rows = [
        _row(team=team, days_ago=-2.0),  # событие в будущем относительно cutoff
        _row(team=team, days_ago=2 / 24),  # 2 часа назад: +4ч лага > cutoff
        _row(team=team, days_ago=7.0, available_lag=timedelta(days=5)),  # assumed-политика
    ]
    form = roster_form(rows, team_id=team, cutoff=CUTOFF, result_lag=LAG)
    assert form.days_since_last == pytest.approx(7.0)


def test_changes_30d_counts_first_appearances() -> None:
    """«Приток новых»: игроки с первым появлением в окне 30 дней."""
    team = uuid4()
    veteran = uuid4()  # первое появление 90 дней назад — не в окне
    newcomer_a = uuid4()  # первое появление 5 дней назад
    newcomer_b = uuid4()  # первое появение 2 дня назад
    rows = [
        _row(team=team, player=veteran, days_ago=90.0),
        _row(team=team, player=veteran, days_ago=5.0),
        _row(team=team, player=newcomer_a, days_ago=5.0),
        _row(team=team, player=newcomer_a, days_ago=3.0),
        _row(team=team, player=newcomer_b, days_ago=2.0),
    ]
    form = roster_form(rows, team_id=team, cutoff=CUTOFF, result_lag=LAG)
    assert form.changes_30d == 2


def test_standin_share_uses_window_and_min_sample() -> None:
    """Доля стендинов по окну; при малой выборке — None (не ноль)."""
    team = uuid4()
    rows = [
        _row(team=team, player=uuid4(), days_ago=d, standin=flag)
        for d, flag in ((5.0, True), (4.0, False), (3.0, False), (2.0, True))
    ]
    form = roster_form(rows, team_id=team, cutoff=CUTOFF, result_lag=LAG)
    assert form.standin_share_30d == pytest.approx(0.5)

    # 2 свидетельства в окне < min_window=3 → None
    sparse = [
        _row(team=team, player=uuid4(), days_ago=5.0, standin=True),
        _row(team=team, player=uuid4(), days_ago=4.0, standin=True),
        _row(team=team, player=uuid4(), days_ago=90.0, standin=False),
    ]
    sparse_form = roster_form(sparse, team_id=team, cutoff=CUTOFF, result_lag=LAG)
    assert sparse_form.standin_share_30d is None
    assert sparse_form.avail is True  # давность/изменения посчитаны


def test_reproducible() -> None:
    team = uuid4()
    rows = [_row(team=team, days_ago=d, standin=(d == 5.0)) for d in (5.0, 4.0, 3.0)]
    a = roster_form(rows, team_id=team, cutoff=CUTOFF, result_lag=LAG)
    b = roster_form(rows, team_id=team, cutoff=CUTOFF, result_lag=LAG)
    assert a == b
