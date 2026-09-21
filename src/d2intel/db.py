"""Подключение к PostgreSQL через SQLAlchemy 2.x + psycopg3.

Инфраструктура: engine/session. ORM-модели и миграции схемы НЕ здесь —
модели это DATA-001/DB-001, миграции это DB-001 (см. каталог alembic/).
"""

from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from d2intel.config import Settings, get_settings


def _build_engine(database_url: str) -> Engine:
    """Создаёт синхронный engine. pool_pre_ping защищает от «уснувших» соединений."""
    return create_engine(database_url, pool_pre_ping=True, future=True)


def create_engine_from_settings(settings: Settings | None = None) -> Engine:
    """Фабрика engine из настроек. Принимает settings для тестируемости."""
    settings = settings or get_settings()
    return _build_engine(settings.database_url)


# Глобальный engine/session для процесса. Импортируется api и скриптами.
engine: Engine = create_engine_from_settings()
SessionLocal: sessionmaker[Session] = sessionmaker(bind=engine, future=True)


def get_db() -> Iterator[Session]:
    """FastAPI-зависимость: открывает сессию и гарантированно закрывает её."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


def check_db_connection(engine: Engine) -> bool:
    """Проверка живости БД одним SELECT 1. True — БД доступна."""
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return True
    except Exception:
        return False
