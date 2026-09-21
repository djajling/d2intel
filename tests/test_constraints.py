"""DB-001 — тесты ограничений схемы.

AC: constraint, запрещающий противоречивый порядок временных полей;
снимки имеют запрет на update/delete; typed FK для target с XOR-check.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

# Временные выражения инлайнются в SQL (это константы теста, не пользовательский
# ввод): как bound-параметры они были бы восприняты как строки.
BASE_SNAPSHOT = """
    INSERT INTO feature_snapshot (
        target_type, target_game_id, cutoff_at, evaluation_mode,
        values_json, feature_schema_version, content_hash,
        assumed_available_at, lag_policy_version,
        observed_at, ingested_at, available_at
    ) VALUES (
        'game', :game_id, now(), :mode,
        '{{}}'::jsonb, 'v1', :content_hash,
        {assumed}, :lag_policy_version,
        {observed}, {ingested}, {available}
    )
"""


def _insert_feature_snapshot(
    session: Session,
    game_id: str,
    *,
    mode: str = "retrospective_reconstructed",
    observed: str = "now()",
    ingested: str = "now()",
    available: str = "now()",
    lag_policy_version: str | None = "lag-v1",
    assumed_available_at: str | None = None,
    content_hash: str | None = None,
) -> None:
    """Insert a feature snapshot with explicitly controlled temporal fields."""
    statement = BASE_SNAPSHOT.format(
        observed=observed,
        ingested=ingested,
        available=available,
        assumed="NULL" if assumed_available_at is None else assumed_available_at,
    )
    session.execute(
        text(statement),
        {
            "game_id": game_id,
            "mode": mode,
            "content_hash": content_hash or uuid.uuid4().hex,
            "lag_policy_version": lag_policy_version,
        },
    )
    session.flush()


def test_valid_snapshot_inserts(game_fixture: dict[str, str], db_session: Session) -> None:
    """Позитивный сценарий: корректный снимок вставляется."""
    _insert_feature_snapshot(db_session, game_fixture["game"])
    count = db_session.execute(text("SELECT count(*) FROM feature_snapshot")).scalar_one()
    assert count == 1


def test_temporal_order_violation_rejected(
    game_fixture: dict[str, str], db_session: Session
) -> None:
    """AC #5: запрещён противоречивый порядок временных полей.

    available_at раньше ingested_at — недопустимо.
    """
    with pytest.raises(IntegrityError):
        _insert_feature_snapshot(
            db_session,
            game_fixture["game"],
            available="now() - interval '1 hour'",
        )
    db_session.rollback()


def test_observed_after_ingested_rejected(game_fixture: dict[str, str], db_session: Session) -> None:
    """observed_at позже ingested_at — недопустимо."""
    with pytest.raises(IntegrityError):
        _insert_feature_snapshot(
            db_session,
            game_fixture["game"],
            observed="now() + interval '1 hour'",
        )
    db_session.rollback()


def test_snapshot_update_forbidden(game_fixture: dict[str, str], db_session: Session) -> None:
    """AC #2: снимок нельзя изменить."""
    _insert_feature_snapshot(db_session, game_fixture["game"])
    with pytest.raises(IntegrityError):
        db_session.execute(text("UPDATE feature_snapshot SET content_hash = 'tampered'"))
        db_session.flush()
    db_session.rollback()


def test_snapshot_delete_forbidden(game_fixture: dict[str, str], db_session: Session) -> None:
    """AC #2: снимок нельзя удалить."""
    _insert_feature_snapshot(db_session, game_fixture["game"])
    with pytest.raises(IntegrityError):
        db_session.execute(text("DELETE FROM feature_snapshot"))
        db_session.flush()
    db_session.rollback()


def test_prediction_snapshot_update_forbidden(
    game_fixture: dict[str, str], db_session: Session
) -> None:
    """Неизменяемость распространяется и на prediction_snapshot."""
    _insert_feature_snapshot(db_session, game_fixture["game"])
    feature_id = db_session.execute(text("SELECT id FROM feature_snapshot LIMIT 1")).scalar_one()

    prediction_id = db_session.execute(
        text(
            """
            INSERT INTO prediction (target_type, target_game_id, team_a_id, team_b_id, request_key)
            VALUES ('game', :game_id, :team_a, :team_b, :request_key)
            RETURNING id
            """
        ),
        {
            "game_id": game_fixture["game"],
            "team_a": game_fixture["team_a"],
            "team_b": game_fixture["team_b"],
            "request_key": uuid.uuid4().hex,
        },
    ).scalar_one()
    db_session.execute(
        text(
            """
            INSERT INTO prediction_snapshot (
                prediction_id, snapshot_seq, computed_at, cutoff_at,
                feature_snapshot_id, p_a, p_b, evaluation_mode,
                state_hash, idempotency_key, observed_at, ingested_at, available_at
            ) VALUES (
                :prediction_id, 1, now(), now(),
                :feature_id, 0.55, 0.45, 'retrospective_reconstructed',
                'state-hash-1', :idem, now(), now(), now()
            )
            """
        ),
        {
            "prediction_id": prediction_id,
            "feature_id": feature_id,
            "idem": uuid.uuid4().hex,
        },
    )
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(text("UPDATE prediction_snapshot SET p_a = 0.99"))
        db_session.flush()
    db_session.rollback()


def test_retrospective_requires_lag_policy(game_fixture: dict[str, str], db_session: Session) -> None:
    """Реконструкция обязана нести версию политики задержки."""
    with pytest.raises(IntegrityError):
        _insert_feature_snapshot(
            db_session,
            game_fixture["game"],
            mode="retrospective_reconstructed",
            lag_policy_version=None,
        )
    db_session.rollback()


def test_prospective_must_not_set_assumed_availability(
    game_fixture: dict[str, str], db_session: Session
) -> None:
    """Проспективный режим не использует assumed_available_at."""
    with pytest.raises(IntegrityError):
        _insert_feature_snapshot(
            db_session,
            game_fixture["game"],
            mode="prospective_observed",
            lag_policy_version=None,
            assumed_available_at="now()",
        )
    db_session.rollback()


def test_prediction_requires_distinct_teams(
    game_fixture: dict[str, str], db_session: Session
) -> None:
    """Team A и Team B не могут совпадать."""
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                """
                INSERT INTO prediction (target_type, target_game_id, team_a_id, team_b_id, request_key)
                VALUES ('game', :game_id, :team_a, :team_a, :request_key)
                """
            ),
            {
                "game_id": game_fixture["game"],
                "team_a": game_fixture["team_a"],
                "request_key": uuid.uuid4().hex,
            },
        )
        db_session.flush()
    db_session.rollback()


def test_prediction_target_xor_enforced(game_fixture: dict[str, str], db_session: Session) -> None:
    """Typed FK для target: ровно один из game_id / series_id."""
    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                """
                INSERT INTO prediction (target_type, target_game_id, target_series_id,
                                        team_a_id, team_b_id, request_key)
                VALUES ('game', :game_id, :series_id, :team_a, :team_b, :request_key)
                """
            ),
            {
                "game_id": game_fixture["game"],
                "series_id": game_fixture["series"],
                "team_a": game_fixture["team_a"],
                "team_b": game_fixture["team_b"],
                "request_key": uuid.uuid4().hex,
            },
        )
        db_session.flush()
    db_session.rollback()


def test_raw_payload_deduplicated_by_content_hash(db_session: Session) -> None:
    """raw: дедупликация по (source_id, content_hash)."""
    source_id = db_session.execute(
        text("INSERT INTO data_source (name) VALUES ('opendota') RETURNING id")
    ).scalar_one()
    payload = {
        "source_id": source_id,
        "observed_at": "now()",
        "ingested_at": "now()",
        "available_at": "now()",
    }
    db_session.execute(
        text(
            """
            INSERT INTO raw_payload (source_id, endpoint_kind, content_hash, schema_version,
                                     payload_json, observed_at, ingested_at, available_at)
            VALUES (:source_id, 'pro_matches', 'hash-1', 'v1', '{}'::jsonb,
                    now(), now(), now())
            """
        ),
        payload,
    )
    db_session.flush()

    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                """
                INSERT INTO raw_payload (source_id, endpoint_kind, content_hash, schema_version,
                                         payload_json, observed_at, ingested_at, available_at)
                VALUES (:source_id, 'pro_matches', 'hash-1', 'v1', '{}'::jsonb,
                        now(), now(), now())
                """
            ),
            payload,
        )
        db_session.flush()
    db_session.rollback()
