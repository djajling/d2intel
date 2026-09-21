"""Конфигурация окружения Alembic.

Инфраструктура только. Миграции схемы НЕ создаются (это DB-001).
target_metadata = None: autogenerate отключён, потому что ORM-моделей
пока нет (DATA-001 / DB-001). URL берётся из настроек приложения
(DATABASE_URL), а не из alembic.ini — секретов в файле нет.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from d2intel.config import get_settings

# alembic.ini лежит в корне репозитория рядом с этим env.py? Нет —
# config.config_args подаёт alembic.ini. fileConfig здесь обязателен для логов.
config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Подменяем url в config на значение из настроек приложения (окружение).
settings = get_settings()
config.set_main_option("sqlalchemy.url", settings.database_url)

# Нет ORM-моделей — target_metadata = None. Autogenerate не используется.
target_metadata = None


def run_migrations_offline() -> None:
    """Режим без соединения: генерирует SQL (offline)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Режим с соединением: применяет миграции к БД."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
