"""Health-эндпоинт.

Различает «процесс жив» и «БД доступна» (ARCHITECTURE.md §6): HTTP 200
только когда оба условия выполнены; 503 когда процесс жив, но БД недоступна.
Свежесть данных / пригодность forecasts — будущие задачи (API-001/MON-001),
здесь намеренно не реализуются.
"""

from __future__ import annotations

from fastapi import APIRouter, status
from fastapi.responses import JSONResponse

from d2intel.db import check_db_connection, engine

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> JSONResponse:
    """Сводка здоровья процесса и БД.

    Ответ: {"status": "ok"|"degraded", "database": "up"|"down", "app": ...}.
    """
    db_up = check_db_connection(engine)
    body = {
        "status": "ok" if db_up else "degraded",
        "app": "d2intel",
        "database": "up" if db_up else "down",
    }
    code = status.HTTP_200_OK if db_up else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(status_code=code, content=body)
