"""DB-001 — тесты миграций.

AC: миграции обратимо/воспроизводимо применяются локально; canonical-поля
типизированы; JSONB только в raw/snapshot/variable payload.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import Engine, inspect, text

from tests.conftest import alembic_config, get_test_database_url

VERSIONS_DIR = Path(__file__).resolve().parents[1] / "alembic" / "versions"

EXPECTED_TABLES = {
    # raw слой
    "data_source",
    "ingestion_run",
    "raw_payload",
    "source_observation",
    # canonical
    "team",
    "player",
    "tournament",
    "series",
    "game",
    "game_team",
    "game_participant",
    # DATA-001: справочники, маппинг, свидетельства состава, статистика
    "patch",
    "entity_mapping",
    "roster_membership",
    "player_performance",
    "normalization_quarantine",
    # снимки и воспроизводимость
    "model_version",
    "feature_snapshot",
    "prediction",
    "prediction_snapshot",
    "snapshot_evidence",
    "prediction_evaluation",
}

# Пять временных полей из docs/PRD_TEMPORAL.md.
TEMPORAL_FIELDS = {
    "event_time",
    "source_published_at",
    "observed_at",
    "ingested_at",
    "available_at",
}

# Таблицы, у которых временной конверт обязателен.
VERSIONED_TABLES = {
    "raw_payload",
    "source_observation",
    "team",
    "player",
    "tournament",
    "series",
    "game",
    "game_team",
    "game_participant",
    "patch",
    "entity_mapping",
    "roster_membership",
    "player_performance",
    "normalization_quarantine",
    "feature_snapshot",
    "prediction_snapshot",
}


def test_migrations_create_expected_tables(migrated_engine: Engine) -> None:
    """Миграции с нуля создают ожидаемое ядро."""
    inspector = inspect(migrated_engine)
    tables = set(inspector.get_table_names())
    assert tables >= EXPECTED_TABLES, f"missing: {sorted(EXPECTED_TABLES - tables)}"


def test_migrations_are_reversible(test_engine: Engine) -> None:
    """Round-trip: downgrade base -> upgrade head воспроизводим."""
    config = alembic_config(get_test_database_url())

    command.downgrade(config, "base")
    with test_engine.connect() as connection:
        remaining = {
            row[0]
            for row in connection.execute(
                text("select table_name from information_schema.tables where table_schema='public'")
            )
        }
    assert not (EXPECTED_TABLES & remaining), f"not dropped: {sorted(EXPECTED_TABLES & remaining)}"

    command.upgrade(config, "head")
    inspector = inspect(test_engine)
    assert set(inspector.get_table_names()) >= EXPECTED_TABLES


def test_temporal_envelope_present_on_versioned_tables(migrated_engine: Engine) -> None:
    """AC #1: все пять временных полей присутствуют."""
    inspector = inspect(migrated_engine)
    for table in VERSIONED_TABLES:
        columns = {column["name"] for column in inspector.get_columns(table)}
        missing = TEMPORAL_FIELDS - columns
        assert not missing, f"{table}: missing temporal fields {sorted(missing)}"


def test_canonical_tables_are_typed_not_jsonb(migrated_engine: Engine) -> None:
    """AC #6: canonical-поля типизированы, JSONB — только для variable payload."""
    inspector = inspect(migrated_engine)
    for table, column in (
        ("team", "canonical_name"),
        ("player", "canonical_name"),
        ("game", "map_number"),
        ("game_team", "team_id"),
        ("series", "tournament_id"),
    ):
        columns = {c["name"]: c for c in inspector.get_columns(table)}
        assert column in columns, f"{table}.{column} отсутствует"
        assert str(columns[column]["type"]).upper() != "JSONB", f"{table}.{column} не должен быть JSONB"


def test_snapshot_payload_is_jsonb(migrated_engine: Engine) -> None:
    """Снимки держат payload в JSONB."""
    inspector = inspect(migrated_engine)
    columns = {c["name"]: c for c in inspector.get_columns("feature_snapshot")}
    assert str(columns["values_json"]["type"]).upper() == "JSONB"
    assert str(columns["coverage_json"]["type"]).upper() == "JSONB"


FORBIDDEN_COMPONENTS = ("redis", "celery", "kafka", "kubernetes", "mlflow", "feast")


@pytest.mark.parametrize("component", FORBIDDEN_COMPONENTS)
def test_no_forbidden_components_in_migrations(component: str) -> None:
    """AC #4: запрещённые компоненты не вводятся миграциями."""
    for path in sorted(VERSIONS_DIR.glob("*.py")):
        content = path.read_text(encoding="utf-8").lower()
        assert component not in content, f"{path.name}: обнаружен {component}"
