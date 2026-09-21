"""DATA-001 — ограничения схемы нормализованного ядра."""

from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from tests.normalize.helpers import ensure_source


def _team(session: Session, observation_id: str) -> str:
    created = session.execute(
        text(
            """
            INSERT INTO team (canonical_name, identity_status, source_observation_id,
                              observed_at, ingested_at, available_at)
            VALUES ('Team', 'resolved', :observation_id, now(), now(), now())
            RETURNING id
            """
        ),
        {"observation_id": observation_id},
    ).scalar_one()
    return str(created)


def _player(session: Session, observation_id: str) -> str:
    created = session.execute(
        text(
            """
            INSERT INTO player (account_id, canonical_name, identity_status, source_observation_id,
                                observed_at, ingested_at, available_at)
            VALUES (100, 'Player', 'resolved', :observation_id, now(), now(), now())
            RETURNING id
            """
        ),
        {"observation_id": observation_id},
    ).scalar_one()
    return str(created)


def test_entity_mapping_rejects_two_targets(provenance: dict[str, str], db_session: Session) -> None:
    """XOR: ровно один typed target, polymorphic-ссылка без типа запрещена."""
    team = _team(db_session, provenance["observation"])
    player = _player(db_session, provenance["observation"])
    source = ensure_source(db_session, "test-mapping")
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                """
                INSERT INTO entity_mapping (
                    source_id, entity_type, external_id, team_id, player_id,
                    mapping_version, source_observation_id, observed_at, ingested_at, available_at
                ) VALUES (
                    :source_id, 'team', '36', :team_id, :player_id,
                    'v1', :observation_id, now(), now(), now()
                )
                """
            ),
            {
                "source_id": source,
                "team_id": team,
                "player_id": player,
                "observation_id": provenance["observation"],
            },
        )


def test_entity_mapping_rejects_type_mismatch(
    provenance: dict[str, str], db_session: Session
) -> None:
    """Тип сущности обязан соответствовать заполненному typed FK."""
    team = _team(db_session, provenance["observation"])
    source = ensure_source(db_session, "test-mapping")
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                """
                INSERT INTO entity_mapping (
                    source_id, entity_type, external_id, team_id,
                    mapping_version, source_observation_id, observed_at, ingested_at, available_at
                ) VALUES (
                    :source_id, 'player', '100', :team_id,
                    'v1', :observation_id, now(), now(), now()
                )
                """
            ),
            {
                "source_id": source,
                "team_id": team,
                "observation_id": provenance["observation"],
            },
        )


def test_entity_mapping_allows_one_active_mapping_per_key(
    provenance: dict[str, str], db_session: Session
) -> None:
    """Активный маппинг на (источник, тип, внешний id) — ровно один.

    Версионирование не отменяет единственность: новая версия приходит со
    статусом `superseded`, иначе активных маппингов стало бы два.
    """
    team = _team(db_session, provenance["observation"])
    source = ensure_source(db_session, "test-mapping")
    statement = text(
        """
        INSERT INTO entity_mapping (
            source_id, entity_type, external_id, team_id, status,
            mapping_version, source_observation_id, observed_at, ingested_at, available_at
        ) VALUES (
            :source_id, 'team', '36', :team_id, :status,
            :version, :observation_id, now(), now(), now()
        )
        """
    )
    params = {
        "source_id": source,
        "team_id": team,
        "observation_id": provenance["observation"],
        "version": "v1",
        "status": "active",
    }
    db_session.execute(statement, params)
    db_session.execute(statement, {**params, "version": "v2", "status": "superseded"})
    db_session.flush()
    with pytest.raises(IntegrityError):
        db_session.execute(statement, {**params, "version": "v3", "status": "active"})


def test_roster_membership_rejects_inverted_interval(
    provenance: dict[str, str], db_session: Session, game_fixture: dict[str, str]
) -> None:
    """Интервал свидетельства состава не может быть вывернут."""
    player = _player(db_session, provenance["observation"])
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                """
                INSERT INTO roster_membership (
                    team_id, player_id, game_id, membership_type, valid_from, valid_to,
                    source_observation_id, observed_at, ingested_at, available_at
                ) VALUES (
                    :team_id, :player_id, :game_id, 'actual_observed',
                    now(), now() - interval '1 hour',
                    :observation_id, now(), now(), now()
                )
                """
            ),
            {
                "team_id": game_fixture["team_a"],
                "player_id": player,
                "game_id": game_fixture["game"],
                "observation_id": provenance["observation"],
            },
        )


def test_player_performance_rejects_unknown_data_class(
    provenance: dict[str, str], db_session: Session, game_fixture: dict[str, str]
) -> None:
    """Класс данных фиксирован: только `final` или `partial`."""
    player = _player(db_session, provenance["observation"])
    participant = db_session.execute(
        text(
            """
            INSERT INTO game_participant (
                game_id, player_id, team_id, slot, source_observation_id,
                observed_at, ingested_at, available_at
            ) VALUES (
                :game_id, :player_id, :team_id, 0, :observation_id,
                now(), now(), now()
            )
            RETURNING id
            """
        ),
        {
            "game_id": game_fixture["game"],
            "player_id": player,
            "team_id": game_fixture["team_a"],
            "observation_id": provenance["observation"],
        },
    ).scalar_one()
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                """
                INSERT INTO player_performance (
                    game_participant_id, metric_schema_version, data_class,
                    source_observation_id, observed_at, ingested_at, available_at
                ) VALUES (
                    :participant_id, 'v1', 'pre_match',
                    :observation_id, now(), now(), now()
                )
                """
            ),
            {
                "participant_id": participant,
                "observation_id": provenance["observation"],
            },
        )


def test_team_name_null_requires_unresolved(provenance: dict[str, str], db_session: Session) -> None:
    """NULL-имя допустимо только при `unresolved`."""
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                """
                INSERT INTO team (canonical_name, identity_status, source_observation_id,
                                  observed_at, ingested_at, available_at)
                VALUES (NULL, 'resolved', :observation_id, now(), now(), now())
                """
            ),
            {"observation_id": provenance["observation"]},
        )


def test_normalization_quarantine_requires_reason(
    provenance: dict[str, str], db_session: Session
) -> None:
    """Причина карантина обязательна и не бывает пустой."""
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                """
                INSERT INTO normalization_quarantine (
                    job_kind, source_id, provider_entity_id, reason_code,
                    observed_at, ingested_at, available_at
                ) VALUES ('map_index', :source_id, '1', '   ', now(), now(), now())
                """
            ),
            {"source_id": provenance["source"]},
        )
