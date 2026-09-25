"""API-001 — тесты prediction-эндпоинта.

Покрытие по карточке `API-001` (TESTS):

- иммутабельность снапшота: повторный вызов не перезаписывает, а создаёт
  новый `snapshot_seq`;
- отказ на series-цель: эндпоинт принимает только game_id, не series;
- обязательные поля ответа (модель/версия/фичи/cutoff);
- метка `retrospective_reconstructed` на ретро-оценке;
- шаблонное evidence без LLM.

Тесты идут на выделенной тестовой БД (`tests/conftest.py`: `db_session` +
`game_fixture`). Без неё — пропуск, как в `tests/features/conftest.py`.
Инференс требует обученной LR в БД: фикстура `lr_model_version` регистрирует
минимальную версию с сериализованным артефактом во временном каталоге.
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

from d2intel.api.predict import (
    _assert_purity,
    _feature_columns,
    _flip_sides,
    _params_from_hyperparameters,
)
from d2intel.app import create_app
from d2intel.db import get_db
from d2intel.features.prior_form import PriorFormParams

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
    """TestClient с переопределённой зависимостью БД на тестовую сессию.

    Без override эндпоинт ходил бы в рабочую БД через `SessionLocal`, а
    тестовые данные лежат в транзакции выделенной тестовой БД.
    """
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
    """Зарегистрировать минимальную версию LR с сериализованным артефактом.

    Модель-заглушка: случайные веса, детерминированный seed. Тестируется
    контракт API, а не sklearn-математика (ей доверяем).
    """
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


# --------------------------------------------------------------------------- #
# Цель: только game1, отказ на series
# --------------------------------------------------------------------------- #


def test_predict_rejects_non_game1(
    app_client: TestClient,
    db_session: Session,
    game_fixture: dict[str, str],
    lr_model_version: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC #2: цель не map1 — отказ 400."""
    _set_artifacts_dir(monkeypatch, lr_model_version["artifact_dir"])
    game_id = _make_game1(db_session, game_fixture)
    db_session.execute(
        text("UPDATE game SET map_number = 2 WHERE id = CAST(:id AS uuid)"),
        {"id": game_id},
    )
    db_session.flush()

    response = app_client.post(f"/predict/game/{game_id}")

    assert response.status_code == 400
    assert "game1" in response.json()["detail"]


def test_predict_rejects_missing_game(
    app_client: TestClient,
    db_session: Session,
    lr_model_version: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Несуществующая игра — отказ."""
    _set_artifacts_dir(monkeypatch, lr_model_version["artifact_dir"])
    response = app_client.post(f"/predict/game/{uuid4()}")

    assert response.status_code == 400


# --------------------------------------------------------------------------- #
# Иммутабельность и обязательные поля
# --------------------------------------------------------------------------- #


def test_predict_writes_snapshot_and_is_immutable(
    app_client: TestClient,
    db_session: Session,
    game_fixture: dict[str, str],
    lr_model_version: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC #1: повторный вызов создаёт новый snapshot_seq, не перезаписывает."""
    _set_artifacts_dir(monkeypatch, lr_model_version["artifact_dir"])
    game_id = _make_game1(db_session, game_fixture)

    first = app_client.post(f"/predict/game/{game_id}")
    second = app_client.post(f"/predict/game/{game_id}")

    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text

    prediction_id = first.json()["prediction_id"]
    rows = db_session.execute(
        text(
            "SELECT snapshot_seq FROM prediction_snapshot "
            "WHERE prediction_id = CAST(:id AS uuid) ORDER BY snapshot_seq"
        ),
        {"id": prediction_id},
    ).all()
    assert len(rows) >= 2
    assert [row.snapshot_seq for row in rows] == [1, 2]


def test_predict_response_has_required_fields(
    app_client: TestClient,
    db_session: Session,
    game_fixture: dict[str, str],
    lr_model_version: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC #3: модель/версия/фичи/cutoff — все обязательные поля на месте."""
    _set_artifacts_dir(monkeypatch, lr_model_version["artifact_dir"])
    game_id = _make_game1(db_session, game_fixture)

    response = app_client.post(f"/predict/game/{game_id}")
    body = response.json()

    assert response.status_code == 200, body
    required = {
        "prediction_id",
        "snapshot_id",
        "model_version_id",
        "algorithm",
        "feature_schema_version",
        "cutoff_at",
        "evaluation_mode",
        "target_phase",
        "p_a",
        "p_b",
        "evidence",
    }
    assert required <= set(body)
    assert body["model_version_id"] == str(lr_model_version["id"])
    assert body["algorithm"] == "logreg_prior_form"
    assert body["p_a"] + body["p_b"] == pytest.approx(1.0)
    assert body["target_phase"] == "map1_pre_draft"


def test_predict_marks_retrospective(
    app_client: TestClient,
    db_session: Session,
    game_fixture: dict[str, str],
    lr_model_version: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC #4: ретроспективная оценка помечена retrospective_reconstructed."""
    _set_artifacts_dir(monkeypatch, lr_model_version["artifact_dir"])
    game_id = _make_game1(db_session, game_fixture)

    response = app_client.post(f"/predict/game/{game_id}")
    body = response.json()

    assert response.status_code == 200, body
    assert body["evaluation_mode"] == "retrospective_reconstructed"

    snapshot_row = db_session.execute(
        text(
            "SELECT evaluation_mode, feature_snapshot_id, cutoff_at "
            "FROM prediction_snapshot WHERE id = CAST(:id AS uuid)"
        ),
        {"id": body["snapshot_id"]},
    ).first()
    assert snapshot_row is not None
    assert snapshot_row.evaluation_mode == "retrospective_reconstructed"
    # AC #3: снапшот содержит фичи — ссылка на feature_snapshot.
    assert snapshot_row.feature_snapshot_id is not None
    assert snapshot_row.cutoff_at is not None


def test_snapshot_db_row_cannot_be_mutated(
    app_client: TestClient,
    db_session: Session,
    game_fixture: dict[str, str],
    lr_model_version: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Триггер prediction_snapshot_no_mutation действительно запрещает UPDATE."""
    _set_artifacts_dir(monkeypatch, lr_model_version["artifact_dir"])
    game_id = _make_game1(db_session, game_fixture)
    response = app_client.post(f"/predict/game/{game_id}")
    snapshot_id = response.json()["snapshot_id"]

    with pytest.raises(Exception):  # noqa: B017, PT011 — триггер БД
        db_session.execute(
            text(
                "UPDATE prediction_snapshot SET p_a = 0.99 "
                "WHERE id = CAST(:id AS uuid)"
            ),
            {"id": snapshot_id},
        )
        db_session.flush()


# --------------------------------------------------------------------------- #
# Evidence — шаблонное, не LLM
# --------------------------------------------------------------------------- #


def test_evidence_is_templated(
    app_client: TestClient,
    db_session: Session,
    game_fixture: dict[str, str],
    lr_model_version: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """AC #5: каждый пункт evidence имеет template-id и ссылку на поле."""
    _set_artifacts_dir(monkeypatch, lr_model_version["artifact_dir"])
    game_id = _make_game1(db_session, game_fixture)

    response = app_client.post(f"/predict/game/{game_id}")
    evidence = response.json()["evidence"]

    assert evidence, "evidence не пусто"
    for item in evidence:
        assert "template" in item
        assert "field" in item
        assert "text" in item
        assert isinstance(item["text"], str)
        # Не свободная генерация — текст пришёл из шаблона.
        assert item["template"]


def test_evidence_avoids_causal_and_profit_claims(
    app_client: TestClient,
    db_session: Session,
    game_fixture: dict[str, str],
    lr_model_version: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """API-003 AC #3: никаких утверждений о причинности и прибыльности."""
    _set_artifacts_dir(monkeypatch, lr_model_version["artifact_dir"])
    game_id = _make_game1(db_session, game_fixture)

    response = app_client.post(f"/predict/game/{game_id}")
    forbidden = ("потому что", "из-за", "гарантир", "прибыл", "выиграет точно")

    for item in response.json()["evidence"]:
        lowered = item["text"].lower()
        for word in forbidden:
            assert word not in lowered, f"запрещённая формулировка: {word}"


# --------------------------------------------------------------------------- #
# Чистота: нет данных с available_at > cutoff
# --------------------------------------------------------------------------- #


def test_purity_check_detects_future_leak(db_session: Session) -> None:
    """AC #6: счётчик признаков выше доступных игр — нарушение."""
    team_id = uuid4()
    cutoff = datetime(2026, 8, 1, 12, 0)
    params = PriorFormParams()

    # Фиктивная строка признаков: команды «видели» 5 карт, а в БД их нет.
    feature_row = {"team_a_n_games": 5, "team_b_n_games": 0}
    with pytest.raises(Exception):  # noqa: B017, PT011
        _assert_purity(
            feature_row,
            cutoff,
            db_session,
            (team_id, uuid4()),
            params,
        )


def test_purity_check_passes_when_no_history(db_session: Session) -> None:
    """Нет истории — нет нарушения: признаки говорят 0, и доступно 0."""
    feature_row = {"team_a_n_games": 0, "team_b_n_games": 0}
    _assert_purity(
        feature_row,
        datetime(2026, 8, 1, 12, 0),
        db_session,
        (uuid4(), uuid4()),
        PriorFormParams(),
    )


# --------------------------------------------------------------------------- #
# Вспомогательные функции
# --------------------------------------------------------------------------- #


def test_feature_columns_require_hyperparameters() -> None:
    """Нет hyperparameters — нет инференса, а не fallback на угадывание."""
    from d2intel.api.predict import PredictionError

    with pytest.raises(PredictionError):
        _feature_columns(None)
    with pytest.raises(PredictionError):
        _feature_columns({})


def test_params_from_hyperparameters_restores_prior_mean() -> None:
    """μ восстанавливается из гиперпараметров версии модели."""
    params = _params_from_hyperparameters({"prior_mean": 0.42})
    assert params.prior_mean == pytest.approx(0.42)

    empty = _params_from_hyperparameters(None)
    assert empty.prior_mean == pytest.approx(0.5)


def test_flip_sides_inverts_differentials_and_label() -> None:
    """Разворот сторон: дифференциалы ×(−1), метка инвертируется."""
    record: dict[str, Any] = {
        "team_a_wr_lifetime": 0.6,
        "team_b_wr_lifetime": 0.4,
        "player_a_wr": 0.55,
        "player_b_wr": 0.45,
        "d_team_wr_lifetime": 0.2,
        "d_player_kda": 0.1,
        "y": 1,
    }

    flipped = _flip_sides(record, ["d_team_wr_lifetime", "d_player_kda"])

    assert flipped["team_a_wr_lifetime"] == pytest.approx(0.4)
    assert flipped["team_b_wr_lifetime"] == pytest.approx(0.6)
    assert flipped["player_a_wr"] == pytest.approx(0.45)
    assert flipped["player_b_wr"] == pytest.approx(0.55)
    assert flipped["d_team_wr_lifetime"] == pytest.approx(-0.2)
    assert flipped["d_player_kda"] == pytest.approx(-0.1)
    assert flipped["y"] == 0


def test_flip_sides_keeps_nan_differential() -> None:
    """NaN в дифференциале остаётся NaN, не превращается в −0.0."""
    record: dict[str, Any] = {
        "d_player_kda": float("nan"),
        "y": 0,
        "team_a_wr_lifetime": 0.5,
        "team_b_wr_lifetime": 0.5,
    }

    flipped = _flip_sides(record, ["d_player_kda"])

    assert np.isnan(flipped["d_player_kda"])
