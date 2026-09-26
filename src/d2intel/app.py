"""Инициализация приложения: фабрика FastAPI.

Сервер с health-маршрутом (INF-001), prediction-эндпоинтом (API-001),
dashboard-API и статическим workbench в site/ (работа владельца), плюс
server-rendered страница матча (UI-001, /match/{game_id}). Никаких
фоновых задач — это локальный исследовательский инструмент.
Запуск:
    uvicorn d2intel.app:app --reload --port 8000
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from d2intel import __version__
from d2intel.api.dashboard import router as dashboard_router
from d2intel.api.health import router as health_router
from d2intel.api.predict import router as predict_router
from d2intel.web.views import router as web_router

SITE_DIR = Path(__file__).resolve().parents[2] / "site"


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
    app.include_router(dashboard_router)
    app.include_router(web_router)
    # Статический workbench монтируется последним: маршруты API и /match
    # имеют приоритет, всё остальное отдаёт site/ (index.html на /).
    if SITE_DIR.is_dir():
        app.mount("/", StaticFiles(directory=SITE_DIR, html=True), name="site")
    return app


# Объект для uvicorn d2intel.app:app.
app = create_app()
