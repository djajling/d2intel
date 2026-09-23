"""Когорта game1: Team A по канонической идентичности, а не по стороне."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from d2intel.evaluation.cohort import Game1Row, cohort_report, select_game1_cohort

TEAM_A = UUID("00000000-0000-0000-0000-00000000000a")  # меньше → Team A
TEAM_B = UUID("00000000-0000-0000-0000-00000000000b")


def _row(*, team_a: UUID, team_b: UUID, winner: UUID, when: datetime) -> Game1Row:
    return Game1Row(
        game_id=UUID(int=1),
        series_id=UUID(int=2),
        event_time=when,
        team_a_id=team_a,
        team_b_id=team_b,
        winner_team_id=winner,
    )


def test_team_a_is_the_smaller_canonical_id() -> None:
    """Порядок задаётся идентичностью: Team A не обязана быть Radiant."""
    row = _row(team_a=TEAM_A, team_b=TEAM_B, winner=TEAM_A, when=datetime(2026, 9, 1, tzinfo=UTC))
    assert row.team_a_id < row.team_b_id
    assert row.label == 1


def test_label_zero_when_team_b_wins() -> None:
    row = _row(team_a=TEAM_A, team_b=TEAM_B, winner=TEAM_B, when=datetime(2026, 9, 1, tzinfo=UTC))
    assert row.label == 0


def test_group_is_series() -> None:
    row = _row(team_a=TEAM_A, team_b=TEAM_B, winner=TEAM_A, when=datetime(2026, 9, 1, tzinfo=UTC))
    assert row.group == str(row.series_id)


def test_report_on_empty_cohort_is_not_a_fake_measurement() -> None:
    report = cohort_report([])
    assert report["n"] == 0
    assert report["majority_class_accuracy"] is None


def test_report_counts_teams_series_and_baseline() -> None:
    base = datetime(2026, 9, 1, tzinfo=UTC)
    rows = [
        _row(team_a=TEAM_A, team_b=TEAM_B, winner=TEAM_A, when=base),
        _row(team_a=TEAM_A, team_b=TEAM_B, winner=TEAM_A, when=base + timedelta(days=1)),
        _row(team_a=TEAM_A, team_b=TEAM_B, winner=TEAM_B, when=base + timedelta(days=2)),
    ]
    report = cohort_report(rows)
    assert report["n"] == 3
    assert report["teams"] == 2
    assert report["label_balance"] == 2 / 3
    assert report["majority_class_accuracy"] == 2 / 3


def _insert_series(session: Session, observation_id: str, key: str) -> UUID:
    return UUID(
        str(
            session.execute(
                text(
                    """
                    INSERT INTO series (source_observation_id, series_key,
                                        observed_at, ingested_at, available_at)
                    VALUES (:obs, :key, now(), now(), now())
                    RETURNING id
                    """
                ),
                {"obs": observation_id, "key": key},
            ).scalar_one()
        )
    )


def _insert_team(session: Session, observation_id: str) -> UUID:
    return UUID(
        str(
            session.execute(
                text(
                    """
                    INSERT INTO team (source_observation_id, observed_at, ingested_at, available_at)
                    VALUES (:obs, now(), now(), now())
                    RETURNING id
                    """
                ),
                {"obs": observation_id},
            ).scalar_one()
        )
    )


def _insert_game(
    session: Session,
    *,
    observation_id: str,
    map_number: int | None,
    result_type: str,
    winner: UUID | None,
    event_time: datetime,
    provider_match_id: str = "fixture-match",
    series_id: UUID | None = None,
) -> UUID:
    return UUID(
        str(
            session.execute(
                text(
                    """
                    INSERT INTO game (
                        source_observation_id, status, map_number, result_type,
                        winner_team_id, event_time, provider_match_id, series_id,
                        observed_at, ingested_at, available_at
                    ) VALUES (
                        :obs, 'completed', :map_number, :result_type,
                        :winner, :event_time, :provider_match_id, :series_id,
                        now(), now(), now()
                    )
                    RETURNING id
                    """
                ),
                {
                    "obs": observation_id,
                    "map_number": map_number,
                    "result_type": result_type,
                    "winner": str(winner) if winner else None,
                    "event_time": event_time,
                    "provider_match_id": provider_match_id,
                    "series_id": str(series_id) if series_id else None,
                },
            ).scalar_one()
        )
    )


def _link_team(
    session: Session, *, game_id: UUID, team_id: UUID, observation_id: str, slot: int
) -> None:
    session.execute(
        text(
            """
            INSERT INTO game_team (game_id, team_id, slot, source_observation_id,
                                   observed_at, ingested_at, available_at)
            VALUES (:game_id, :team_id, :slot, :obs, now(), now(), now())
            """
        ),
        {"game_id": str(game_id), "team_id": str(team_id), "slot": slot, "obs": observation_id},
    )


def test_cohort_selects_only_first_map_with_known_winner(
    db_session: Session, provenance: dict[str, str]
) -> None:
    """Вторая карта, forfeit и неразобранный map_index в когорту не попадают."""
    observation = provenance["observation"]
    series = _insert_series(db_session, observation, "fixture-series-1")
    other_series = _insert_series(db_session, observation, "fixture-series-2")
    team_low = _insert_team(db_session, observation)
    team_high = _insert_team(db_session, observation)
    low, high = sorted([team_low, team_high])

    base = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

    playable = _insert_game(
        db_session,
        observation_id=observation,
        map_number=1,
        result_type="played",
        winner=low,
        event_time=base,
        provider_match_id="fixture-m1",
        series_id=series,
    )
    _link_team(db_session, game_id=playable, team_id=low, observation_id=observation, slot=0)
    _link_team(db_session, game_id=playable, team_id=high, observation_id=observation, slot=1)

    second_map = _insert_game(
        db_session,
        observation_id=observation,
        map_number=2,
        result_type="played",
        winner=high,
        event_time=base + timedelta(hours=1),
        provider_match_id="fixture-m2",
        series_id=series,
    )
    _link_team(db_session, game_id=second_map, team_id=low, observation_id=observation, slot=0)
    _link_team(db_session, game_id=second_map, team_id=high, observation_id=observation, slot=1)

    forfeit = _insert_game(
        db_session,
        observation_id=observation,
        map_number=1,
        result_type="forfeit",
        winner=low,
        event_time=base + timedelta(hours=2),
        provider_match_id="fixture-m3",
        series_id=other_series,
    )
    _link_team(db_session, game_id=forfeit, team_id=low, observation_id=observation, slot=0)
    _link_team(db_session, game_id=forfeit, team_id=high, observation_id=observation, slot=1)

    db_session.flush()
    rows = select_game1_cohort(db_session)

    assert len(rows) == 1
    assert rows[0].game_id == playable
    assert rows[0].team_a_id == low, "Team A — меньший canonical id, а не сторона"
    assert rows[0].team_b_id == high
    assert rows[0].label == 1
