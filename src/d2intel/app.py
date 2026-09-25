"""Инициализация приложения: фабрика FastAPI.

Минимальный сервер с health-маршрутом (INF-001) и prediction-эндпоинтом
(API-001). Никаких фоновых задач — это локальный исследовательский
инструмент.
Запуск:
    uvicorn d2intel.app:app --reload --port 8000
"""

from __future__ import annotations

from fastapi import FastAPI

from d2intel import __version__
from d2intel.api.health import router as health_router
from d2intel.api.predict import router as predict_router


def create_app() -> FastAPI:
    """Создаёт настроенный экземпляр приложения (factory)."""
    app = FastAPI(
        title="d2intel",
        version=__version__,
        description=(
            "Dota Esports Intelligence Platform — local research tool. "
            "Prediction target is limited to game1 (map 1)."
        ),
    )
    app.include_router(health_router)
    app.include_router(predict_router)
    return app


# Объект для uvicorn d2intel.app:app.
app = create_app()
