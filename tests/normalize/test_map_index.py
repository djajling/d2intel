"""DATA-001 — правила вывода серии и номера карты (чистые функции, без БД)."""

from __future__ import annotations

from d2intel.normalize.map_index import plan_all, plan_series
from d2intel.normalize.payloads import parse_pro_match
from d2intel.normalize.policy import GameStatus, QuarantineReason, SeriesStatus, series_key
from tests.normalize.helpers import pro_match, pro_match_at


def test_complete_bo3_gets_map_numbers_by_start_time() -> None:
    """Три карты Bo3 получают номера 1..3 по возрастанию времени старта."""
    plans = plan_all(
        [
            parse_pro_match(pro_match_at(9000000003, offset_minutes=120)),
            parse_pro_match(pro_match_at(9000000001, offset_minutes=0)),
            parse_pro_match(pro_match_at(9000000002, offset_minutes=60)),
        ]
    )
    assert len(plans) == 1
    plan = plans[0]
    assert plan.best_of == 3
    assert plan.reason is None
    assert plan.status is SeriesStatus.COMPLETED
    assert [(game.record.match_id, game.map_number) for game in plan.games] == [
        (9000000001, 1),
        (9000000002, 2),
        (9000000003, 3),
    ]


def test_bo1_outside_series_is_standalone_map_one() -> None:
    """Матч без `series_id` — отдельная серия из одной карты, map1."""
    plans = plan_all([parse_pro_match(pro_match(series_id=0, series_type=0))])
    plan = plans[0]
    assert plan.series_key.startswith("standalone:")
    assert plan.best_of == 1
    assert [game.map_number for game in plan.games] == [1]


def test_incomplete_series_is_quarantined_not_guessed() -> None:
    """Неполная Bo3: номер карты не присваивается, карты уходят в карантин."""
    plans = plan_all(
        [
            parse_pro_match(pro_match_at(9000000001, offset_minutes=0)),
            parse_pro_match(pro_match_at(9000000002, offset_minutes=60)),
        ]
    )
    plan = plans[0]
    assert plan.reason is QuarantineReason.INCOMPLETE_SERIES
    assert plan.best_of == 3
    assert [game.map_number for game in plan.games] == [None, None]
    assert all(game.status is GameStatus.MAP_INDEX_UNRESOLVED for game in plan.games)


def test_unknown_series_type_is_quarantined() -> None:
    """Формат серии неизвестен → причина `unknown_series_type`."""
    plans = plan_all([parse_pro_match(pro_match(series_type=7))])
    assert plans[0].reason is QuarantineReason.UNKNOWN_SERIES_TYPE


def test_tied_start_time_is_ambiguous() -> None:
    """Одинаковое время старта — порядок карт неопределён."""
    plans = plan_all(
        [
            parse_pro_match(pro_match_at(9000000001, offset_minutes=0)),
            parse_pro_match(pro_match_at(2, offset_minutes=0)),
            parse_pro_match(pro_match_at(3, offset_minutes=60)),
        ]
    )
    assert plans[0].reason is QuarantineReason.AMBIGUOUS_MAP_ORDER


def test_missing_start_time_is_ambiguous() -> None:
    """Неизвестное время старта — порядок карт неопределён."""
    plans = plan_all(
        [
            parse_pro_match(pro_match(match_id=1, start_time=None)),
            parse_pro_match(pro_match(match_id=2, start_time=1790006900)),
            parse_pro_match(pro_match(match_id=3, start_time=1790007000)),
        ]
    )
    assert plans[0].reason is QuarantineReason.AMBIGUOUS_MAP_ORDER


def test_inconsistent_teams_inside_series() -> None:
    """Разные пары команд внутри одной серии — серия собрана неверно."""
    plans = plan_all(
        [
            parse_pro_match(pro_match_at(9000000001, offset_minutes=0)),
            parse_pro_match(pro_match_at(9000000002, offset_minutes=60)),
            parse_pro_match(pro_match_at(3, offset_minutes=120, dire_team_id=999)),
        ]
    )
    assert plans[0].reason is QuarantineReason.INCONSISTENT_SERIES_TEAMS


def test_more_games_than_format_allows() -> None:
    """Карт больше, чем допускает формат — группировка недостоверна."""
    plans = plan_all(
        [
            parse_pro_match(pro_match_at(9000000001, offset_minutes=0)),
            parse_pro_match(pro_match_at(9000000002, offset_minutes=60)),
            parse_pro_match(pro_match_at(9000000003, offset_minutes=120)),
            parse_pro_match(pro_match_at(4, offset_minutes=180)),
        ]
    )
    assert plans[0].reason is QuarantineReason.SERIES_COUNT_EXCEEDS_FORMAT


def test_missing_team_identity_is_quarantined_per_record() -> None:
    """Нет идентичности команды — карта в карантин, серия из неё не собирается."""
    plans = plan_all([parse_pro_match(pro_match(radiant_team_id=None, series_id=0))])
    plan = plans[0]
    assert plan.games[0].reason is QuarantineReason.MISSING_TEAM_IDENTITY
    assert plan.games[0].map_number is None


def test_standalone_bo3_type_is_not_silently_map_one() -> None:
    """`series_id = 0` при заявленном Bo3 — не «первая карта», а неполная серия.

    Иначе все одиночные матчи одной пары склеились бы в ложные map1.
    """
    plans = plan_all([parse_pro_match(pro_match(series_id=0, series_type=1))])
    assert plans[0].reason is QuarantineReason.INCOMPLETE_SERIES
    assert plans[0].games[0].map_number is None


def test_series_key_groups_only_real_series() -> None:
    """Ключ серии: реальная серия — по `series_id`, иначе уникальный на матч."""
    assert series_key(1145136, 1) == "series:1145136"
    assert series_key(0, 42) == "standalone:42"
    assert series_key(None, 42) == "standalone:42"


def test_plan_series_is_deterministic() -> None:
    """Одинаковый набор записей даёт одинаковый план (порядок входа не важен)."""
    first = [parse_pro_match(pro_match_at(9000000001, offset_minutes=0)),
             parse_pro_match(pro_match_at(9000000002, offset_minutes=60)),
             parse_pro_match(pro_match_at(9000000003, offset_minutes=120))]
    second = list(reversed(first))
    assert plan_all(first) == plan_all(second)
    assert plan_series("series:1", first) == plan_series("series:1", second)
