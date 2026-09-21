"""Smoke-тесты INF-001.

Проверяют ровно то, что требует Acceptance Criteria:
1. приложение импортируется;
2. подключение к БД устанавливается (SELECT 1);
3. health-эндпоинт отвечает (HTTP 200 + database:up);
4. запрещённых зависимостей нет (Redis/Celery/Kafka/K8s/feature-store/MLflow).

Тесты требуют живую БД: локально — `docker compose up -d`, в CI — postgres-service.
"""

from __future__ import annotations

import importlib.util
from collections.abc import Callable

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

FORBIDDEN_PACKAGES = {
    "redis",
    "celery",
    "kafka",
    "kafka_python",
    "kubernetes",
    "mlflow",
    "feast",
}


def test_app_imports() -> None:
    """AC #2: приложение импортируется и фабрика возвращает FastAPI."""
    from d2intel.app import create_app

    app = create_app()
    assert isinstance(app, FastAPI)


def test_db_connection() -> None:
    """AC #2: подключение к БД устанавливается."""
    from d2intel.db import check_db_connection, engine

    assert check_db_connection(engine) is True


def test_health_endpoint_responds(create_app_client: Callable[[], TestClient]) -> None:
    """AC #2: health-эндпоинт отвечает 200 и сообщает, что БД доступна."""
    client = create_app_client()
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "up"


@pytest.mark.parametrize("package", sorted(FORBIDDEN_PACKAGES))
def test_no_forbidden_dependencies(package: str) -> None:
    """AC #3 / BACKLOG-чек-лист: запрещённых компонентов в окружении нет."""
    found = importlib.util.find_spec(package) is not None
    assert not found, f"Обнаружена запрещённая зависимость: {package}"


# ---фикстуры---


@pytest.fixture
def create_app_client() -> Callable[[], TestClient]:
    def _factory() -> TestClient:
        from d2intel.app import create_app

        return TestClient(create_app())

    return _factory
