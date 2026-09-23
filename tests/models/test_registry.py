"""Регистрация версии модели: candidate по умолчанию, идемпотентность по run_key."""

from __future__ import annotations

from uuid import UUID

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from d2intel.models.registry import register_model_version


def _fetch(db_session: Session, model_version_id: UUID) -> tuple[str, str, str | None]:
    row = db_session.execute(
        text(
            """
            SELECT algorithm, promotion_status, hyperparameters->>'run_key'
              FROM model_version WHERE id = :id
            """
        ),
        {"id": str(model_version_id)},
    ).first()
    assert row is not None
    return str(row[0]), str(row[1]), None if row[2] is None else str(row[2])


def test_register_creates_candidate(db_session: Session) -> None:
    mv = register_model_version(
        db_session,
        algorithm="prior_const",
        feature_schema_version="none.v1",
        hyperparameters={"p_a": 0.51, "fitted_n": 3212},
        seed=20260922,
    )
    algorithm, status, run_key = _fetch(db_session, mv)
    assert algorithm == "prior_const"
    assert status == "candidate", "промоушен — отдельное решение владельца, не при регистрации"
    assert run_key is None


def test_run_key_makes_re_registration_idempotent(db_session: Session) -> None:
    first = register_model_version(
        db_session, algorithm="prior_const", feature_schema_version="none.v1", run_key="run-1"
    )
    second = register_model_version(
        db_session, algorithm="prior_const", feature_schema_version="none.v1", run_key="run-1"
    )
    assert first == second
    other = register_model_version(
        db_session, algorithm="prior_const", feature_schema_version="none.v1", run_key="run-2"
    )
    assert other != first
    total = db_session.execute(text("SELECT count(*) FROM model_version")).scalar_one()
    assert total == 2


def test_model_version_is_immutable(db_session: Session) -> None:
    """Триггер ADR-005 запрещает UPDATE/DELETE — история версий не переписывается."""
    from sqlalchemy.exc import IntegrityError

    mv = register_model_version(
        db_session, algorithm="prior_const", feature_schema_version="none.v1"
    )
    db_session.commit()
    with pytest.raises(IntegrityError):
        db_session.execute(
            text("UPDATE model_version SET promotion_status = 'champion' WHERE id = :id"),
            {"id": str(mv)},
        )
