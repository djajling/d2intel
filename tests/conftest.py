"""Shared pytest fixtures (INF-001 + DB-001)."""

from __future__ import annotations

import contextlib
import os
from collections.abc import Iterator
from pathlib import Path
from uuid import uuid4

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
def provenance(db_session: Session) -> dict[str, str]:
    """Минимальная цепочка raw: источник → прогон → payload → наблюдение.

    Появилась вместе с `DATA-001`: canonical-запись обязана иметь ссылку на
    наблюдение источника (`source_observation_id NOT NULL`), поэтому фикстура
    канонической цепочки начинается с raw.
    """
    source = db_session.execute(
        text(
            """
            INSERT INTO data_source (name, adapter_version, capabilities, created_at)
            VALUES (:name, 'test-fixture', CAST('{}' AS jsonb), now())
            RETURNING id
            """
        ),
        {"name": f"test-source-{uuid4().hex[:8]}"},
    ).scalar_one()
    run = db_session.execute(
        text(
            """
            INSERT INTO ingestion_run (source_id, started_at, status)
            VALUES (:source_id, now(), 'completed')
            RETURNING id
            """
        ),
        {"source_id": source},
    ).scalar_one()
    raw = db_session.execute(
        text(
            """
            INSERT INTO raw_payload (
                source_id, endpoint_kind, content_hash, schema_version, payload_json,
                observed_at, ingested_at, available_at
            ) VALUES (
                :source_id, 'fixture', :content_hash, 'fixture.v1', CAST('{}' AS jsonb),
                now(), now(), now()
            )
            RETURNING id
            """
        ),
        {"source_id": source, "content_hash": f"fixture-{uuid4().hex}"},
    ).scalar_one()
    observation = db_session.execute(
        text(
            """
            INSERT INTO source_observation (
                run_id, raw_payload_id, provider_entity_id, provider_entity_type,
                observed_at, ingested_at, available_at
            ) VALUES (
                :run_id, :raw_payload_id, 'fixture-entity', 'fixture',
                now(), now(), now()
            )
            RETURNING id
            """
        ),
        {"run_id": run, "raw_payload_id": raw},
    ).scalar_one()
    db_session.flush()
    return {
        "source": str(source),
        "run": str(run),
        "raw_payload": str(raw),
        "observation": str(observation),
    }


@pytest.fixture
def game_fixture(db_session: Session, provenance: dict[str, str]) -> dict[str, str]:
    """Create the minimal canonical chain: two teams, series, one game.

    Возвращает id сущностей как строки. Временные поля заполняются
    в корректном порядке (observed <= ingested <= available).
    """
    observation_id = provenance["observation"]
    team_a = db_session.execute(
        text(
            """
            INSERT INTO team (canonical_name, identity_status, source_observation_id,
                              observed_at, ingested_at, available_at)
            VALUES ('Team A', 'resolved', :observation_id, now(), now(), now())
            RETURNING id
            """
        ),
        {"observation_id": observation_id},
    ).scalar_one()
    team_b = db_session.execute(
        text(
            """
            INSERT INTO team (canonical_name, identity_status, source_observation_id,
                              observed_at, ingested_at, available_at)
            VALUES ('Team B', 'resolved', :observation_id, now(), now(), now())
            RETURNING id
            """
        ),
        {"observation_id": observation_id},
    ).scalar_one()
    tournament = db_session.execute(
        text(
            """
            INSERT INTO tournament (name, source_observation_id, observed_at, ingested_at, available_at)
            VALUES ('Test Tournament', :observation_id, now(), now(), now())
            RETURNING id
            """
        ),
        {"observation_id": observation_id},
    ).scalar_one()
    series = db_session.execute(
        text(
            """
            INSERT INTO series (tournament_id, best_of, status, series_key, source_observation_id,
                                observed_at, ingested_at, available_at)
            VALUES (:tournament_id, 3, 'scheduled', 'fixture-series', :observation_id,
                    now(), now(), now())
            RETURNING id
            """
        ),
        {"tournament_id": tournament, "observation_id": observation_id},
    ).scalar_one()
    game = db_session.execute(
        text(
            """
            INSERT INTO game (series_id, map_number, attempt_number, status, provider_match_id,
                              source_observation_id, event_time, observed_at, ingested_at, available_at)
            VALUES (:series_id, 1, 1, 'completed', 'fixture-match', :observation_id,
                    now(), now(), now(), now())
            RETURNING id
            """
        ),
        {"series_id": series, "observation_id": observation_id},
    ).scalar_one()
    db_session.flush()
    return {
        "team_a": str(team_a),
        "team_b": str(team_b),
        "tournament": str(tournament),
        "series": str(series),
        "game": str(game),
        "observation": observation_id,
    }
