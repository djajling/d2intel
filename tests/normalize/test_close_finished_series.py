"""Закрытие серий по счёту Liquipedia (scripts/close_finished_series.py) — без сети и БД.

Покрывает ровно то, что решает судьбу вердикта: bo5, завершённая 3:0, раньше
висела `incomplete` вечно, потому что `map_index.py` требует карт ровно
`best_of`. Теперь серия закрывается по внешнему подтверждению — но только
при полном совпадении команд, формата, счёта и победителя. Любое
расхождение — отказ, а не «закрыть на веру»: цена ошибки — неверный номер
карты и, значит, неверный вердикт по заморозке.
"""

from __future__ import annotations

from datetime import UTC, datetime

from scripts.close_finished_series import (
    ClosureDecision,
    SeriesInfo,
    decide_closure,
    parse_score,
)

TEAMS = ("Team Yandex", "Natus Vincere")


def _info(
    *,
    games: int = 3,
    best_of: int | None = 5,
    teams: tuple[str, ...] = TEAMS,
    winners: tuple[str | None, ...] = ("Team Yandex",) * 3,
) -> SeriesInfo:
    base = datetime(2026, 9, 27, 12, 50, tzinfo=UTC)
    wins: dict[str, int] = {}
    for winner in winners[:games]:
        if winner:
            wins[winner] = wins.get(winner, 0) + 1
    return SeriesInfo(
        series_id="s-1",
        best_of=best_of,
        status="incomplete",
        event_time=base,
        teams=frozenset(teams),
        games=tuple(
            (f"game-{index}", base.replace(hour=12 + index)) for index in range(games)
        ),
        wins_by_team=wins,
    )


def _match(**overrides: object) -> dict:
    base = {
        "teams": list(TEAMS),
        "started_at": "2026-09-27T12:50:00+00:00",
        "bestof": 5,
        "finished": True,
        "score": ["3", "0"],
        "winner": "Team Yandex",
    }
    base.update(overrides)  # type: ignore[arg-type]
    return base


def test_parse_score_pair() -> None:
    assert parse_score(["3", "0"]) == (3, 0)
    assert parse_score(["2", "1"]) == (2, 1)
    # Отсутствие счёта — не ноль: закрывать серию не на чем.
    assert parse_score(None) is None
    assert parse_score(["3"]) is None
    assert parse_score(["?", "0"]) is None


def test_bo5_finished_3_0_gets_map_numbers() -> None:
    """Главный кейс: bo5 3:0 — карт три, номера 1..3 по порядку старта."""
    decision = decide_closure(_match(), _info(), observed_at="2026-09-27T18:34:00+00:00")
    assert decision.closed is True
    assert decision.ordering == ("game-0", "game-1", "game-2")
    assert decision.evidence is not None
    assert decision.evidence["score"] == [3, 0]
    assert decision.evidence["source"] == "liquipedia:matches"
    # Provenance: почему считаем полной — карт ровно по счёту.
    assert "games_in_db == sum(score)" in decision.evidence["rule"]


def test_refuses_when_game_count_differs_from_score() -> None:
    """Карт меньше, чем в счёте: значит часть карт мы не видели — номеров не даём."""
    decision = decide_closure(_match(), _info(games=2), observed_at=None)
    assert decision.closed is False
    assert "карт в БД 2" in decision.reason
    assert decision.ordering == ()


def test_refuses_when_teams_differ() -> None:
    info = _info(teams=("Team Spirit", "Natus Vincere"))
    decision = decide_closure(_match(), info, observed_at=None)
    assert decision.closed is False
    assert decision.reason.startswith("команды не совпали")


def test_refuses_when_format_differs() -> None:
    decision = decide_closure(_match(bestof=3), _info(), observed_at=None)
    assert decision.closed is False
    assert "формат не совпал" in decision.reason


def test_refuses_when_winner_disagrees_with_our_maps() -> None:
    """Счёт говорит 3:0 Yandex, а по картам БД побеждала Na'Vi — доверять нельзя."""
    info = _info(winners=("Natus Vincere",) * 3)
    decision = decide_closure(_match(), info, observed_at=None)
    assert decision.closed is False
    assert "победитель не сошёлся" in decision.reason


def test_refuses_when_win_count_disagrees() -> None:
    info = _info(winners=("Team Yandex", "Team Yandex", "Team Yandex"))
    decision = decide_closure(_match(score=["3", "1"]), info, observed_at=None)
    assert decision.closed is False
    assert "карт в БД 3" in decision.reason or "побед в БД" in decision.reason


def test_refuses_when_portal_match_not_finished() -> None:
    decision = decide_closure(_match(finished=False, score=None), _info(), observed_at=None)
    assert decision.closed is False
    assert "не завершён" in decision.reason


def test_refuses_when_start_time_far_away() -> None:
    decision = decide_closure(
        _match(started_at="2026-08-01T12:00:00+00:00"), _info(), observed_at=None
    )
    assert decision.closed is False
    assert "время старта разошлось" in decision.reason


def test_decision_is_frozen_value_object() -> None:
    decision = ClosureDecision(True, "ok")
    assert decision.evidence is None
    assert decision.ordering == ()
