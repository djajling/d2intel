"""UI-001 — рендер-тесты страницы матча.

Покрытие по карточке `UI-001` (TESTS):

- метка ретроспективы видна явно (`retrospective_reconstructed` + баннер);
- провенанс и версия модели отображены (источник, cutoff, версия, hash);
- нет элементов, имитирующих live (никаких `<script>`, websocket, «live»);
- страница работает на реальном снимке из тестовой БД.

Тесты идут на выделенной тестовой БД (`tests/conftest.py`); фикстуры
`app_client`/`lr_model_version` повторяют паттерн `tests/api/test_predict.py`
(инференс требует зарегистрированной LR с артефактом во временном каталоге).
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from joblib import dump as joblib_dump
from sqlalchemy import text
from sqlalchemy.orm import Session

from d2intel.app import create_app
from d2intel.db import get_db

FEATURE_COLUMNS_API = [
    "d_team_wr_lifetime",
    "d_team_wr_last_long",
    "d_team_wr_last_short",
    "d_team_n_eff",
    "d_team_days_since_last",
    "d_player_wr",
    "d_player_kda",
    "d_player_gpm",
    "d_player_xpm",
]


@pytest.fixture
def app_client(db_session: Session) -> TestClient:
    """TestClient с переопределённой зависимостью БД на тестовую сессию."""
    app = create_app()

    def _override_get_db() -> Any:
        try:
            yield db_session
        finally:
            pass

    app.dependency_overrides[get_db] = _override_get_db
    return TestClient(app)


@pytest.fixture
def lr_model_version(db_session: Session, tmp_path: Path) -> dict[str, Any]:
    """Минимальная версия LR с сериализованным артефактом (как в API-тестах)."""
    from sklearn.linear_model import LogisticRegression

    model = LogisticRegression(C=1.0, max_iter=100, random_state=17)
    rng = np.random.default_rng(17)
    x_train = rng.normal(size=(20, len(FEATURE_COLUMNS_API)))
    y_train = (x_train[:, 0] > 0).astype(int)
    model.fit(x_train, y_train)

    artifacts_dir = tmp_path / "models"
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    artifact_name = "test_lr.joblib"
    joblib_dump(model, artifacts_dir / artifact_name)

    row = db_session.execute(
        text(
            """
            INSERT INTO model_version (
                algorithm, feature_schema_version, seed, hyperparameters,
                artifact_uri, artifact_hash, promotion_status, computed_at
            ) VALUES (
                'logreg_prior_form', 'prior-form.v1', 17,
                CAST(:hyperparameters AS jsonb), :artifact_uri, 'test-hash',
                'candidate', now()
            ) RETURNING id
            """
        ),
        {
            "hyperparameters": json.dumps(
                {
                    "c": 1.0,
                    "run_key": "test-run",
                    "feature_columns": FEATURE_COLUMNS_API,
                    "prior_mean": 0.51,
                }
            ),
            "artifact_uri": artifact_name,
        },
    ).scalar_one()
    db_session.flush()
    return {
        "id": UUID(str(row)),
        "artifact_dir": str(artifacts_dir),
        "artifact_uri": artifact_name,
    }


def _make_game1(db_session: Session, game_fixture: dict[str, str]) -> UUID:
    """Зафиксировать game_fixture как завершённую map1 с известным исходом."""
    db_session.execute(
        text(
            """
            UPDATE game SET map_number = 1, status = 'completed',
                            winner_team_id = CAST(:winner AS uuid),
                            event_time = :event_time
            WHERE id = CAST(:game_id AS uuid)
            """
        ),
        {
            "winner": game_fixture["team_a"],
            "event_time": datetime(2026, 8, 1, 12, 0),
            "game_id": game_fixture["game"],
        },
    )
    db_session.execute(
        text(
            """
            INSERT INTO game_team (game_id, team_id, slot, side, source_observation_id,
                                   observed_at, ingested_at, available_at)
            VALUES (CAST(:game_id AS uuid), CAST(:team_a AS uuid), 0, 'radiant',
                    CAST(:observation AS uuid), now(), now(), now())
            ON CONFLICT (game_id, slot) DO UPDATE SET team_id = EXCLUDED.team_id
            """
        ),
        {
            "game_id": game_fixture["game"],
            "team_a": game_fixture["team_a"],
            "observation": game_fixture["observation"],
        },
    )
    db_session.execute(
        text(
            """
            INSERT INTO game_team (game_id, team_id, slot, side, source_observation_id,
                                   observed_at, ingested_at, available_at)
            VALUES (CAST(:game_id AS uuid), CAST(:team_b AS uuid), 1, 'dire',
                    CAST(:observation AS uuid), now(), now(), now())
            ON CONFLICT (game_id, slot) DO UPDATE SET team_id = EXCLUDED.team_id
            """
        ),
        {
            "game_id": game_fixture["game"],
            "team_b": game_fixture["team_b"],
            "observation": game_fixture["observation"],
        },
    )
    db_session.flush()
    return UUID(game_fixture["game"])


def _set_artifacts_dir(monkeypatch: pytest.MonkeyPatch, path: str) -> None:
    monkeypatch.setattr("d2intel.api.predict.ARTIFACTS_DIR", Path(path))


def _with_prediction(
    app_client: TestClient,
    db_session: Session,
    game_fixture: dict[str, str],
    lr_model_version: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> UUID:
    """Игра map1 + созданный через API снимок прогноза."""
    _set_artifacts_dir(monkeypatch, lr_model_version["artifact_dir"])
    game_id = _make_game1(db_session, game_fixture)
    response = app_client.post(f"/predict/game/{game_id}")
    assert response.status_code == 200, response.text
    return game_id


def test_match_page_shows_retrospective_label_provenance_and_model(
    app_client: TestClient,
    db_session: Session,
    game_fixture: dict[str, str],
    lr_model_version: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC #1 + #2: метка ретроспективы, провенанс и версия модели на странице."""
    game_id = _with_prediction(app_client, db_session, game_fixture, lr_model_version, monkeypatch)

    response = app_client.get(f"/match/{game_id}")
    html = response.text

    assert response.status_code == 200
    # AC #1: явная метка ретроспективы.
    assert "РЕТРОСПЕКТИВА" in html
    assert "retrospective_reconstructed" in html
    assert "не живой прогноз" in html
    # AC #2: провенанс (источник/время/cutoff/снимок) и версия модели.
    assert "test-source-" in html  # имя data_source из фикстуры provenance
    assert "2026-08-01" in html  # event_time
    assert "Cutoff прогноза" in html
    assert "logreg_prior_form" in html
    assert str(lr_model_version["id"]) in html
    assert "prior-form.v1" in html


def test_match_page_shows_prediction_and_teams(
    app_client: TestClient,
    db_session: Session,
    game_fixture: dict[str, str],
    lr_model_version: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Команды и вероятность отображены; итог снабжён ретро-оговоркой."""
    game_id = _with_prediction(app_client, db_session, game_fixture, lr_model_version, monkeypatch)

    response = app_client.get(f"/match/{game_id}")
    html = response.text

    assert "Team A" in html and "Team B" in html
    assert "%" in html  # вероятность отрисована
    assert "Фактический результат" in html  # исход помечен как известный post-hoc
    assert "не метрика качества" in html  # честная оговорка про один исход


def test_match_page_has_no_live_elements(
    app_client: TestClient,
    db_session: Session,
    game_fixture: dict[str, str],
    lr_model_version: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC #3: нет элементов, имитирующих live (скриптов, сокетов, «live»)."""
    game_id = _with_prediction(app_client, db_session, game_fixture, lr_model_version, monkeypatch)

    html = app_client.get(f"/match/{game_id}").text.lower()

    assert "<script" not in html
    assert "websocket" not in html
    assert "live" not in html
    assert "прямой эфир" not in html
    assert "setInterval" not in html


def test_match_page_empty_state_offers_explicit_action(
    app_client: TestClient,
    db_session: Session,
    game_fixture: dict[str, str],
) -> None:
    """Без снимка страница не падает и предлагает явное действие (form POST)."""
    game_id = _make_game1(db_session, game_fixture)

    response = app_client.get(f"/match/{game_id}")
    html = response.text

    assert response.status_code == 200
    assert "Снимка прогноза ещё нет" in html
    assert f"/match/{game_id}/predict" in html
    assert 'method="post"' in html


def test_match_predict_creates_snapshot_and_redirects(
    app_client: TestClient,
    db_session: Session,
    game_fixture: dict[str, str],
    lr_model_version: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POST-действие создаёт снимок и возвращает на страницу матча."""
    _set_artifacts_dir(monkeypatch, lr_model_version["artifact_dir"])
    game_id = _make_game1(db_session, game_fixture)

    response = app_client.post(f"/match/{game_id}/predict", follow_redirects=False)

    assert response.status_code == 303, response.text
    assert response.headers["location"] == f"/match/{game_id}"

    page = app_client.get(f"/match/{game_id}")
    assert page.status_code == 200
    assert "%" in page.text

    count = db_session.execute(
        text(
            "SELECT count(*) FROM prediction_snapshot ps "
            "JOIN prediction p ON p.id = ps.prediction_id "
            "WHERE p.target_game_id = CAST(:id AS uuid)"
        ),
        {"id": str(game_id)},
    ).scalar_one()
    assert count >= 1


def test_match_page_unknown_game_returns_404(
    app_client: TestClient,
) -> None:
    """Несуществующая игра — 404, а не пустая страница."""
    response = app_client.get(f"/match/{uuid4()}")
    assert response.status_code == 404


def test_index_redirects_to_latest_match(
    app_client: TestClient,
    db_session: Session,
    game_fixture: dict[str, str],
    lr_model_version: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`GET /` ведёт на страницу последнего рассчитанного снимка."""
    game_id = _with_prediction(app_client, db_session, game_fixture, lr_model_version, monkeypatch)

    response = app_client.get("/", follow_redirects=False)
    assert response.status_code == 307
    assert f"/match/{game_id}" in response.headers["location"]

    followed = app_client.get("/", follow_redirects=True)
    assert followed.status_code == 200
    assert "Team A" in followed.text
