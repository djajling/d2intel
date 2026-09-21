"""Shared pytest fixtures (INF-001 + DB-001)."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import IntegrityError, OperationalError
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[1]

# Отдельная БД для DB-001: миграционные тесты разрушительны (downgrade base).
DEFAULT_TEST_URL = "postgresql+psycopg://d2intel:d2intel_dev@localhost:5432/d2intel_test"


def get_test_database_url() -> str:
    """URL тестовой БД для миграционных/constraint тестов."""
    return os.getenv("D2INTEL_TEST_DATABASE_URL", DEFAULT_TEST_URL)


def alembic_config(database_url: str) -> Config:
    """Build an Alembic config bound to an explicit database URL."""
    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url)
    return config


@pytest.fixture(scope="session")
def test_engine() -> Iterator[Engine]:
    """Engine, pointing at the dedicated test database."""
    engine = create_engine(get_test_database_url(), pool_pre_ping=True)
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def migrated_engine(test_engine: Engine) -> Iterator[Engine]:
    """Test database with migrations applied from zero.

    Откатывает всё до base и применяет миграции заново — это и есть проверка
    «миграции применяются на пустой БД».
    """
    config = alembic_config(get_test_database_url())
    with contextlib.suppress(OperationalError, IntegrityError):
        # База ещё пустая — откатывать нечего.
        command.downgrade(config, "base")
    command.upgrade(config, "head")
    yield test_engine


@pytest.fixture
def db_session(migrated_engine: Engine) -> Iterator[Session]:
    """Session on the migrated test database, rolled back after each test."""
    connection = migrated_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()


@pytest.fixture
def game_fixture(db_session: Session) -> dict[str, str]:
    """Create the minimal canonical chain: two teams, series, one game.

    Возвращает id сущностей как строки. Временные поля заполняются
    в корректном порядке (observed <= ingested <= available).
    """
    team_a = db_session.execute(
        text(
            """
            INSERT INTO team (canonical_name, identity_status, observed_at, ingested_at, available_at)
            VALUES ('Team A', 'resolved', now(), now(), now())
            RETURNING id
            """
        )
    ).scalar_one()
    team_b = db_session.execute(
        text(
            """
            INSERT INTO team (canonical_name, identity_status, observed_at, ingested_at, available_at)
            VALUES ('Team B', 'resolved', now(), now(), now())
            RETURNING id
            """
        )
    ).scalar_one()
    tournament = db_session.execute(
        text(
            """
            INSERT INTO tournament (name, observed_at, ingested_at, available_at)
            VALUES ('Test Tournament', now(), now(), now())
            RETURNING id
            """
        )
    ).scalar_one()
    series = db_session.execute(
        text(
            """
            INSERT INTO series (tournament_id, best_of, status, observed_at, ingested_at, available_at)
            VALUES (:tournament_id, 3, 'scheduled', now(), now(), now())
            RETURNING id
            """
        ),
        {"tournament_id": tournament},
    ).scalar_one()
    game = db_session.execute(
        text(
            """
            INSERT INTO game (series_id, map_number, attempt_number, status,
                              event_time, observed_at, ingested_at, available_at)
            VALUES (:series_id, 1, 1, 'completed', now(), now(), now(), now())
            RETURNING id
            """
        ),
        {"series_id": series},
    ).scalar_one()
    db_session.flush()
    return {
        "team_a": str(team_a),
        "team_b": str(team_b),
        "tournament": str(tournament),
        "series": str(series),
        "game": str(game),
    }
