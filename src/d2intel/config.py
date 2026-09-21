"""Конфигурация приложения из переменных окружения.

Без внешних config-фреймворков: только стандартная библиотека + dataclass.
Секреты не хранятся и не выдумываются. Ключи источников зарезервированы под
INF-002 / ING-001 и здесь намеренно отсутствуют.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    """Набор настроек, читаемых один раз при запуске."""

    database_url: str
    app_name: str
    debug: bool

    @property
    def is_test_env(self) -> bool:
        """True, если запущено под pytest (маркер для smoke-тестов)."""
        return _env_bool("PYTEST_CURRENT_TEST", default=False) or bool(
            os.getenv("PYTEST_CURRENT_TEST")
        )


def _default_database_url() -> str:
    """Значение по умолчанию совпадает с docker-compose.yml."""
    return "postgresql+psycopg://d2intel:d2intel_dev@localhost:5432/d2intel"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Читает окружение один раз; кешируется для детерминизма процесса."""
    return Settings(
        database_url=os.getenv("DATABASE_URL", default=_default_database_url()),
        app_name=os.getenv("APP_NAME", default="d2intel"),
        debug=_env_bool("DEBUG", default=False),
    )
