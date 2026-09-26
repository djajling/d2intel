"""Tests for the read-only prediction workbench endpoints.

A small in-memory session double exercises FastAPI's response contracts without
connecting to or migrating either the working or test database.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from d2intel.api import dashboard
from d2intel.app import create_app
from d2intel.db import get_db


class FakeResult:
    def __init__(self, *, row: Any = None, rows: list[Any] | None = None, value: Any = None):
        self._row = row
        self._rows = rows or []
        self._value = value

    def first(self) -> Any:
        return self._row

    def all(self) -> list[Any]:
        return self._rows

    def scalar_one(self) -> Any:
        return self._value


class FakeSession:
    def __init__(self, results: dict[str, FakeResult]):
        self.results = results
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def execute(self, statement: Any, params: dict[str, Any] | None = None) -> FakeResult:
        sql = str(statement)
        self.calls.append((sql, params or {}))
        return self.results[sql]


def _client(session: FakeSession) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_db] = lambda: session
    return TestClient(app)


def _record(**values: Any) -> Any:
    return type("Row", (), {"_mapping": values})()


def test_overview_reports_database_counters_and_local_model_artifact(
    monkeypatch: Any, tmp_path: Path
) -> None:
    artifact = tmp_path / "lr.joblib"
    artifact.touch()
    monkeypatch.setattr(dashboard, "ARTIFACTS_DIR", tmp_path)
    row = _record(
        eligible_matches=128,
        latest_match_at=datetime(2026, 9, 20, 15, 30, tzinfo=UTC),
        saved_snapshots=24,
        observed_snapshots=2,
        evaluated_snapshots=19,
        latest_model_version_id="model-123",
        latest_feature_schema_version="prior-form.v1",
        latest_model_artifact_uri="lr.joblib",
    )
    session = FakeSession({str(dashboard.OVERVIEW_SQL): FakeResult(row=row)})

    with _client(session) as client:
        response = client.get("/api/overview")

    assert response.status_code == 200
    assert response.json() == {
        "eligible_matches": 128,
        "latest_match_at": "2026-09-20T15:30:00Z",
        "saved_snapshots": 24,
        "observed_snapshots": 2,
        "evaluated_snapshots": 19,
        "latest_model_version_id": "model-123",
        "latest_feature_schema_version": "prior-form.v1",
        "model_available": True,
    }


def test_match_search_is_bound_and_pagination_is_returned() -> None:
    match = _record(
        game_id="game-123",
        series_id="series-123",
        map_number=1,
        game_status="completed",
        event_time=datetime(2026, 9, 20, 15, 30, tzinfo=UTC),
        winner_team_id="team-a-id",
        best_of=3,
        tournament_name="Test Invitational",
        patch_label="7.40",
        team_a_id="team-a-id",
        team_b_id="team-b-id",
        team_a="Team A",
        team_b="Team B",
        winner_team="Team A",
        latest_snapshot_id="snapshot-123",
        latest_snapshot_seq=2,
        latest_p_a=0.61,
        latest_p_b=0.39,
        latest_abstention_reason=None,
        latest_evaluation_mode="retrospective_reconstructed",
    )
    session = FakeSession(
        {
            str(dashboard.MATCHES_COUNT_SQL): FakeResult(value=41),
            str(dashboard.MATCHES_SQL): FakeResult(rows=[match]),
        }
    )

    with _client(session) as client:
        response = client.get("/api/matches?search=%27%20OR%201%3D1--&limit=10&offset=20")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 41
    assert body["items"][0]["team_a"] == "Team A"
    assert body["items"][0]["winner_team"] == "Team A"
    assert body["items"][0]["latest_snapshot_id"] == "snapshot-123"
    assert [params for _, params in session.calls] == [
        {"search": "%" + "' OR 1=1--%"},
        {"search": "%" + "' OR 1=1--%", "limit": 10, "offset": 20},
    ]
    assert "g.result_type = 'played'" in dashboard.MATCHES_SQL
    assert "team_a.identity_status = 'resolved'" in dashboard.MATCHES_SQL


def test_predictions_endpoint_returns_snapshot_rows_without_large_features() -> None:
    snapshot = _record(
        snapshot_id="snapshot-1",
        prediction_id="prediction-1",
        snapshot_seq=2,
        computed_at=datetime(2026, 9, 20, 15, 35, tzinfo=UTC),
        cutoff_at=datetime(2026, 9, 20, 15, 0, tzinfo=UTC),
        p_a=0.61,
        p_b=0.39,
        abstention_reason=None,
        evaluation_mode="retrospective_reconstructed",
        feature_snapshot_id="features-1",
        target_game_id="game-123",
        phase_contract="pre_draft",
        team_a="Team A",
        team_b="Team B",
        game_event_time=datetime(2026, 9, 20, 15, 30, tzinfo=UTC),
        map_number=1,
        game_status="completed",
        tournament_name="Test Invitational",
        best_of=3,
        patch_label="7.40",
        actual_winner="Team A",
        model_version_id="model-1",
        model_algorithm="logreg_prior_form",
        feature_schema_version="prior-form.v1",
        evaluation_y=True,
        log_loss=0.494,
        brier=0.1521,
    )
    session = FakeSession({str(dashboard.PREDICTIONS_SQL): FakeResult(rows=[snapshot])})

    with _client(session) as client:
        response = client.get("/api/predictions?limit=25&offset=5")

    assert response.status_code == 200
    body = response.json()
    assert body["items"][0]["snapshot_id"] == "snapshot-1"
    assert "feature_values" not in body["items"][0]
    assert session.calls[0][1] == {"limit": 25, "offset": 5}


def test_prediction_detail_looks_up_snapshot_by_uuid() -> None:
    snapshot_id = "11111111-1111-4111-8111-111111111111"
    row = _record(snapshot_id=snapshot_id, feature_values={"d_team_wr_lifetime": 0.1})
    session = FakeSession({str(dashboard.PREDICTION_DETAIL_SQL): FakeResult(row=row)})

    with _client(session) as client:
        response = client.get(f"/api/predictions/{snapshot_id}")

    assert response.status_code == 200
    assert response.json() == {
        "snapshot_id": snapshot_id,
        "feature_values": {"d_team_wr_lifetime": 0.1},
    }
    assert session.calls[0][1] == {"snapshot_id": snapshot_id}


def test_static_workbench_is_served_from_root() -> None:
    with _client(FakeSession({})) as client:
        response = client.get("/")

    assert response.status_code == 200
    assert "D2INTEL" in response.text
    assert "match-contract-fallback" not in response.text
