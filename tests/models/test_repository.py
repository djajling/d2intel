"""Запись предсказаний: идемпотентность, seq, воздержание, неизменяемость."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from d2intel.models.registry import register_model_version
from d2intel.models.repository import (
    append_prediction_snapshot,
    prediction_request_key,
    record_evaluation,
    snapshot_idempotency_key,
    upsert_prediction,
)

WHEN = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def _ids(fixture: dict[str, str]) -> tuple[UUID, UUID, UUID]:
    return UUID(fixture["game"]), UUID(fixture["team_a"]), UUID(fixture["team_b"])


def _snapshot(
    db_session: Session,
    *,
    game_id: UUID,
    team_a_id: UUID,
    team_b_id: UUID,
    model_version_id: UUID,
    p_a: float | None = 0.51,
    abstention_reason: str | None = None,
) -> UUID:
    prediction_id = upsert_prediction(
        db_session, game_id=game_id, team_a_id=team_a_id, team_b_id=team_b_id
    )
    return append_prediction_snapshot(
        db_session,
        prediction_id=prediction_id,
        game_id=game_id,
        model_version_id=model_version_id,
        cutoff_at=WHEN,
        event_time=WHEN,
        p_a=p_a,
        abstention_reason=abstention_reason,
    )


def test_request_key_is_deterministic_per_game() -> None:
    game = UUID(int=7)
    assert prediction_request_key(game) == f"game1:pre_draft:{game}"
    assert prediction_request_key(game) == prediction_request_key(game)


def test_idempotency_key_binds_game_to_model_version() -> None:
    game, model = UUID(int=7), UUID(int=8)
    key = snapshot_idempotency_key(game, model)
    assert key == snapshot_idempotency_key(game, model)
    assert key != snapshot_idempotency_key(game, UUID(int=9))


def test_upsert_prediction_is_idempotent(
    db_session: Session, game_fixture: dict[str, str]
) -> None:
    game_id, team_a_id, team_b_id = _ids(game_fixture)
    first = upsert_prediction(
        db_session, game_id=game_id, team_a_id=team_a_id, team_b_id=team_b_id
    )
    second = upsert_prediction(
        db_session, game_id=game_id, team_a_id=team_a_id, team_b_id=team_b_id
    )
    assert first == second
    total = db_session.execute(text("SELECT count(*) FROM prediction")).scalar_one()
    assert total == 1


def test_snapshot_stores_complementary_probability(
    db_session: Session, game_fixture: dict[str, str]
) -> None:
    game_id, team_a_id, team_b_id = _ids(game_fixture)
    mv = register_model_version(
        db_session, algorithm="prior_const", feature_schema_version="none.v1", run_key="t-p"
    )
    snapshot_id = _snapshot(
        db_session,
        game_id=game_id,
        team_a_id=team_a_id,
        team_b_id=team_b_id,
        model_version_id=mv,
        p_a=0.51,
    )
    row = db_session.execute(
        text(
            "SELECT p_a, p_b, abstention_reason, evaluation_mode, state_hash"
            "  FROM prediction_snapshot WHERE id = :id"
        ),
        {"id": str(snapshot_id)},
    ).first()
    assert row is not None
    assert row[0] == pytest.approx(0.51)
    assert row[1] == pytest.approx(0.49)
    assert row[2] is None
    assert row[3] == "retrospective_reconstructed"
    assert row[4]


def test_snapshot_new_model_gets_next_seq(
    db_session: Session, game_fixture: dict[str, str]
) -> None:
    """Новая версия модели — новый snapshot_seq, а не перезапись старого."""
    game_id, team_a_id, team_b_id = _ids(game_fixture)
    first_model = register_model_version(
        db_session, algorithm="prior_const", feature_schema_version="none.v1", run_key="t-a"
    )
    second_model = register_model_version(
        db_session, algorithm="prior_const", feature_schema_version="none.v1", run_key="t-b"
    )

    first = _snapshot(
        db_session,
        game_id=game_id,
        team_a_id=team_a_id,
        team_b_id=team_b_id,
        model_version_id=first_model,
        p_a=0.51,
    )
    second = _snapshot(
        db_session,
        game_id=game_id,
        team_a_id=team_a_id,
        team_b_id=team_b_id,
        model_version_id=second_model,
        p_a=0.6,
    )
    assert first != second

    seqs = (
        db_session.execute(
            text(
                "SELECT model_version_id, snapshot_seq FROM prediction_snapshot"
                "  WHERE prediction_id = (SELECT id FROM prediction LIMIT 1)"
                "  ORDER BY snapshot_seq"
            )
        )
        .all()
    )
    assert [int(row[1]) for row in seqs] == [1, 2]


def test_repeated_snapshot_for_same_model_is_idempotent(
    db_session: Session, game_fixture: dict[str, str]
) -> None:
    game_id, team_a_id, team_b_id = _ids(game_fixture)
    mv = register_model_version(
        db_session, algorithm="prior_const", feature_schema_version="none.v1", run_key="t-c"
    )
    first = _snapshot(
        db_session,
        game_id=game_id,
        team_a_id=team_a_id,
        team_b_id=team_b_id,
        model_version_id=mv,
        p_a=0.51,
    )
    second = _snapshot(
        db_session,
        game_id=game_id,
        team_a_id=team_a_id,
        team_b_id=team_b_id,
        model_version_id=mv,
        p_a=0.51,
    )
    assert first == second
    total = db_session.execute(text("SELECT count(*) FROM prediction_snapshot")).scalar_one()
    assert total == 1


def test_abstaining_snapshot_keeps_null_probabilities(
    db_session: Session, game_fixture: dict[str, str]
) -> None:
    game_id, team_a_id, team_b_id = _ids(game_fixture)
    mv = register_model_version(
        db_session, algorithm="prior_const", feature_schema_version="none.v1", run_key="t-d"
    )
    snapshot_id = _snapshot(
        db_session,
        game_id=game_id,
        team_a_id=team_a_id,
        team_b_id=team_b_id,
        model_version_id=mv,
        p_a=None,
        abstention_reason="обучающая выборка пуста",
    )
    row = db_session.execute(
        text("SELECT p_a, p_b, abstention_reason FROM prediction_snapshot WHERE id = :id"),
        {"id": str(snapshot_id)},
    ).first()
    assert row is not None
    assert row[0] is None
    assert row[1] is None
    assert row[2] == "обучающая выборка пуста"


@pytest.mark.parametrize(
    ("p_a", "reason"),
    [
        (0.5, "нельзя одновременно"),
        (None, None),
    ],
)
def test_snapshot_rejects_ambiguous_state(
    db_session: Session,
    game_fixture: dict[str, str],
    p_a: float | None,
    reason: str | None,
) -> None:
    game_id, team_a_id, team_b_id = _ids(game_fixture)
    mv = register_model_version(
        db_session, algorithm="prior_const", feature_schema_version="none.v1", run_key="t-e"
    )
    with pytest.raises(ValueError):
        _snapshot(
            db_session,
            game_id=game_id,
            team_a_id=team_a_id,
            team_b_id=team_b_id,
            model_version_id=mv,
            p_a=p_a,
            abstention_reason=reason,
        )


def test_record_evaluation_is_idempotent(
    db_session: Session, game_fixture: dict[str, str]
) -> None:
    game_id, team_a_id, team_b_id = _ids(game_fixture)
    mv = register_model_version(
        db_session, algorithm="prior_const", feature_schema_version="none.v1", run_key="t-f"
    )
    snapshot_id = _snapshot(
        db_session,
        game_id=game_id,
        team_a_id=team_a_id,
        team_b_id=team_b_id,
        model_version_id=mv,
        p_a=0.51,
    )
    first = record_evaluation(
        db_session, snapshot_id=snapshot_id, y=True, log_loss=0.673, brier=0.2401
    )
    second = record_evaluation(
        db_session, snapshot_id=snapshot_id, y=True, log_loss=0.673, brier=0.2401
    )
    assert first == second
    total = db_session.execute(text("SELECT count(*) FROM prediction_evaluation")).scalar_one()
    assert total == 1


def test_prediction_snapshot_is_immutable(
    db_session: Session, game_fixture: dict[str, str]
) -> None:
    """ADR-005: пересчёт предсказания — новый снимок, а не правка старого."""
    game_id, team_a_id, team_b_id = _ids(game_fixture)
    mv = register_model_version(
        db_session, algorithm="prior_const", feature_schema_version="none.v1", run_key="t-g"
    )
    snapshot_id = _snapshot(
        db_session,
        game_id=game_id,
        team_a_id=team_a_id,
        team_b_id=team_b_id,
        model_version_id=mv,
        p_a=0.51,
    )
    db_session.commit()
    with pytest.raises(IntegrityError):
        db_session.execute(
            text("UPDATE prediction_snapshot SET p_a = 0.99 WHERE id = :id"),
            {"id": str(snapshot_id)},
        )
