"""Фикстуры тестов feature-слоя.

Pure-unit тесты (`test_prior_form.py` без БД) проверяют as-of агрегаты, маски
и режимы на in-memory записях. Интеграционным тестам нужна отдельная тестовая
БД со схемой `0003` (`REPO_SETUP.md` §4): миграционные тесты разрушительны,
поэтому здесь используется **только проверка существования схемы** — без
`downgrade base`. БД нет — тест пропускается, а не падает.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_TEST_URL = "postgresql+psycopg://d2intel:d2intel_dev@localhost:5432/d2intel_test"


def get_feature_database_url() -> str:
    """URL выделенной тестовой БД (не рабочая `d2intel`)."""
    return os.getenv("D2INTEL_TEST_DATABASE_URL", DEFAULT_TEST_URL)


@pytest.fixture(scope="session")
def feature_engine() -> Iterator[Engine]:
    """Engine на тестовую БД. Skip, если БД или схема недоступны."""
    engine = create_engine(get_feature_database_url(), pool_pre_ping=True)
    try:
        with engine.connect() as connection:
            schema_ready = connection.execute(text("SELECT to_regclass('public.game')")).scalar()
        if schema_ready is None:
            engine.dispose()
            pytest.skip("тестовая БД существует, но схема не применена (нет public.game)")
    except Exception as exc:  # noqa: BLE001 — любая причина недоступности = skip
        engine.dispose()
        pytest.skip(f"тестовая БД недоступна: {exc}")
    yield engine
    engine.dispose()


@pytest.fixture
def feature_session(feature_engine: Engine) -> Iterator[Session]:
    """Session с откатом транзакции после каждого теста (неразрушающе)."""
    connection = feature_engine.connect()
    transaction = connection.begin()
    session = sessionmaker(bind=connection, expire_on_commit=False)()
    try:
        yield session
    finally:
        session.close()
        if transaction.is_active:
            transaction.rollback()
        connection.close()
