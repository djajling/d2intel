"""Инициализация приложения: фабрика FastAPI.

Минимальный сервер с одним health-маршрутом. Никакой доменной логики,
никаких источников, никаких фоновых задач — это инфраструктура INF-001.
Запуск:
    uvicorn d2intel.app:app --reload --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI

from d2intel import __version__
from d2intel.api.health import router as health_router


def create_app() -> FastAPI:
    """Создаёт настроенный экземпляр приложения (factory)."""
    app = FastAPI(
        title="d2intel",
        version=__version__,
        description="Dota Esports Intelligence Platform — local skeleton (INF-001).",
    )
    app.include_router(health_router)
    return app


# Объект для uvicorn d2intel.app:app.
app = create_app()
