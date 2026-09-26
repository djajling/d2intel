"""Расписание (миграция 0004) — тесты API ручного ввода и freeze-действия.

Freeze-действие тестируется с подменённым раннером (subprocess не зовётся):
проверяются связь freeze_id со статусом и честный отказ при ошибке раннера.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from d2intel.app import create_app
from d2intel.db import get_db


@pytest.fixture
def api(db_session) -> TestClient:  # noqa: ANN001
    app = create_app()

    def _override() -> Any:
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def _create(client: TestClient, **overrides) -> dict[str, Any]:
    payload = {
        "tournament_label": "PGL Wallachia S9",
        "team_a_label": "Natus Vincere",
        "team_b_label": "Aurora Gaming",
        "scheduled_at": "2026-09-28T15:00:00+03:00",
    }
    payload.update(overrides)
    response = client.post("/api/schedule", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


def test_create_and_list_schedule(api: TestClient) -> None:
    fixture = _create(api)
    assert fixture["status"] == "upcoming"
    assert fixture["tournament_label"] == "PGL Wallachia S9"

    listing = api.get("/api/schedule").json()
    assert any(item["id"] == fixture["id"] for item in listing)
    # фильтр по статусу
    upcoming = api.get("/api/schedule", params={"status": "upcoming"}).json()
    assert all(item["status"] == "upcoming" for item in upcoming)


def test_create_rejects_same_teams(api: TestClient) -> None:
    response = api.post(
        "/api/schedule",
        json={
            "tournament_label": "T",
            "team_a_label": "Same Team",
            "team_b_label": "same team",
        },
    )
    assert response.status_code == 400


def test_delete_fixture(api: TestClient) -> None:
    fixture = _create(api)
    deleted = api.delete(f"/api/schedule/{fixture['id']}")
    assert deleted.status_code == 200
    assert api.get("/api/schedule", params={"status": "upcoming"}).json() == []


def test_freeze_links_freeze_id_and_status(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Успешный раннер → статус frozen, freeze_id связан с фикстурой."""
    fixture = _create(api)

    class _Completed:
        returncode = 0
        stdout = "frozen 0f2e1111-2222-3333-4444-555555555555\n  A vs B\n  p_a 0.5"
        stderr = ""

    monkeypatch.setattr(
        "d2intel.api.schedule.subprocess.run", lambda *a, **k: _Completed()
    )
    frozen = api.post(f"/api/schedule/{fixture['id']}/freeze")
    assert frozen.status_code == 200, frozen.text
    body = frozen.json()
    assert body["status"] == "frozen"
    assert body["freeze_id"] == "0f2e1111-2222-3333-4444-555555555555"


def test_freeze_runner_failure_is_honest(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ошибка раннера → 503 с причиной, статус фикстуры не меняется."""

    class _Failed:
        returncode = 4
        stdout = ""
        stderr = "no model_version for algorithm=logreg_prior_form"

    monkeypatch.setattr(
        "d2intel.api.schedule.subprocess.run", lambda *a, **k: _Failed()
    )
    fixture = _create(api)
    failed = api.post(f"/api/schedule/{fixture['id']}/freeze")
    assert failed.status_code == 503
    assert "no model_version" in failed.json()["detail"]

    listing = api.get("/api/schedule").json()
    assert [item["status"] for item in listing if item["id"] == fixture["id"]] == [
        "upcoming"
    ]


def test_double_freeze_conflicts(
    api: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixture = _create(api)

    class _Completed:
        returncode = 0
        stdout = "frozen 0f2e1111-2222-3333-4444-555555555555\n"
        stderr = ""

    monkeypatch.setattr(
        "d2intel.api.schedule.subprocess.run", lambda *a, **k: _Completed()
    )
    assert api.post(f"/api/schedule/{fixture['id']}/freeze").status_code == 200
    second = api.post(f"/api/schedule/{fixture['id']}/freeze")
    assert second.status_code == 409


def test_draft_observation_is_data_not_model_input(api: TestClient) -> None:
    """Драфт сохраняется как evidence Gate-2; ответ явно говорит, что модель
    драфт-информированной не является."""
    fixture = _create(api)
    saved = api.post(
        f"/api/schedule/{fixture['id']}/draft",
        json={"draft": {"radiant_picks": ["axe", "cm"], "dire_picks": ["pudge"]}},
    )
    assert saved.status_code == 200
    body = saved.json()
    assert body["draft_observed"]["radiant_picks"] == ["axe", "cm"]
    assert "не является" in body["draft_note"]
