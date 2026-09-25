"""API-001 — сервис предсказания: immutable snapshots + шаблонное evidence.

Цель строго ограничена **первой картой серии** (game1, map_number = 1).
Series-цель отклоняется (AC #2). На каждый вызов создаётся неизменяемый
снимок `prediction_snapshot` (AC #1) с моделью/версией/фичами/cutoff
(AC #3). Ретроспективная оценка маркируется `retrospective_reconstructed`
(AC #4) — это единственный режим, который доступен на ретро-контуре.
Объяснение — шаблонное, LLM нет (AC #5).

Чистота (AC #6): cutoff целевой карты — это её `event_time`, а история
для признаков отсекается режимом `event_asof` (`assumed_available_at =
event_time + result_lag`), поэтому данные с `available_at > cutoff` в
снимок не попадают. Проверяется явно в `_assert_purity`.

POST /predict/game/{game_id} — предсказать исход карты 1 для игры.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from joblib import load as joblib_load
from sqlalchemy import text
from sqlalchemy.orm import Session

from d2intel.api.snapshots import (
    PREDICTION_TEMPLATE_EVIDENCE_VERSION,
    PredictionResponse,
    build_template_evidence,
    write_prediction_snapshot,
)
from d2intel.db import get_db
from d2intel.features.prior_form import (
    EVENT_ASOF,
    LAG_POLICY_VERSION,
    TARGET_PHASE,
    PriorFormBuilder,
    PriorFormParams,
)

router = APIRouter(tags=["predict"])

ARTIFACTS_DIR = Path("artifacts/models")

# Поля, которые обязаны присутствовать в ответе (AC #3, TESTS: «обязательные поля»).
REQUIRED_RESPONSE_FIELDS = (
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
)

TARGET_QUERY = """
    SELECT
        g.id AS game_id,
        g.series_id AS series_id,
        g.map_number AS map_number,
        g.status AS status,
        g.winner_team_id AS winner_team_id,
        g.event_time AS event_time,
        g.patch_id AS patch_id,
        gta.team_id AS team_a_id,
        gtb.team_id AS team_b_id,
        gta.side AS team_a_side,
        gtb.side AS team_b_side
    FROM game AS g
    JOIN game_team AS gta ON gta.game_id = g.id AND gta.slot = 0
    JOIN game_team AS gtb ON gtb.game_id = g.id AND gtb.slot = 1
    WHERE g.id = CAST(:game_id AS uuid)
"""

LATEST_MODEL_SQL = """
    SELECT
        mv.id AS id,
        mv.algorithm AS algorithm,
        mv.feature_schema_version AS feature_schema_version,
        mv.artifact_uri AS artifact_uri,
        mv.artifact_hash AS artifact_hash,
        mv.hyperparameters AS hyperparameters
    FROM model_version AS mv
    WHERE mv.algorithm = :algorithm
    ORDER BY mv.computed_at DESC
    LIMIT 1
"""


class PredictionError(RuntimeError):
    """Предсказание невозможно по известной причине (кодируется в ответе)."""


def _load_model(artifact_uri: str | None) -> Any:
    """Загрузить сериализованный артефакт модели (joblib)."""
    if not artifact_uri:
        raise PredictionError("model_version has no artifact_uri")
    path = Path(artifact_uri)
    if not path.is_absolute():
        path = ARTIFACTS_DIR / path
    if not path.exists():
        raise PredictionError(f"model artifact missing: {path}")
    return joblib_load(path)


def _feature_columns(hyperparameters: dict[str, Any] | None) -> list[str]:
    """Список признаков из гиперпараметров версии модели."""
    if not hyperparameters:
        raise PredictionError("model_version has no hyperparameters")
    columns = hyperparameters.get("feature_columns")
    if not columns:
        raise PredictionError("model_version hyperparameters have no feature_columns")
    return list(columns)


def _impute(x: np.ndarray) -> np.ndarray:
    """NaN → 0: unknown ≠ 0 в признаке, но LR не принимает NaN.

    Для дифференциала 0 означает «стороны равны», что и есть «нет сигнала».
    Маски доступности возвращаются отдельно и в признак не подмешиваются.
    """
    return np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)


def _canonical_teams(
    session: Session, game_id: UUID
) -> dict[str, Any]:
    """Целевая карта в канонических координатах (team_a_id < team_b_id).

    Когорта и замороженный сплит используют каноническую идентичность, а не
    slot-0: `team_a_id < team_b_id` (см. `evaluation/cohort.py`). Модель
    обучалась в этой же системе координат, поэтому инференс обязан её
    соблюдать — иначе фичи и метка разъедутся с обучением.
    """
    row = session.execute(text(TARGET_QUERY), {"game_id": str(game_id)}).first()
    if row is None:
        raise PredictionError(f"game not found: {game_id}")
    if row.map_number != 1:
        raise PredictionError(f"target is not game1 (map_number={row.map_number})")
    if row.team_a_id is None or row.team_b_id is None:
        raise PredictionError("target has no known teams")
    if row.team_a_id == row.team_b_id:
        raise PredictionError("target teams are not distinct")
    if row.event_time is None:
        raise PredictionError("target has no event_time")
    # Канонический порядок: младший team_id — Team A.
    if row.team_a_id < row.team_b_id:
        return {
            "team_a_id": UUID(str(row.team_a_id)),
            "team_b_id": UUID(str(row.team_b_id)),
            "slot0_is_team_a": True,
            "event_time": row.event_time,
            "series_id": UUID(str(row.series_id)) if row.series_id else None,
            "winner_team_id": (
                UUID(str(row.winner_team_id)) if row.winner_team_id else None
            ),
        }
    return {
        "team_a_id": UUID(str(row.team_b_id)),
        "team_b_id": UUID(str(row.team_a_id)),
        "slot0_is_team_a": False,
        "event_time": row.event_time,
        "series_id": UUID(str(row.series_id)) if row.series_id else None,
        "winner_team_id": (
            UUID(str(row.winner_team_id)) if row.winner_team_id else None
        ),
    }


def _build_features(
    session: Session,
    target: dict[str, Any],
    params: PriorFormParams,
    feature_columns: list[str],
) -> tuple[dict[str, Any], np.ndarray]:
    """Признаки для одной серии в координатах slot-0 + разворот в канонические.

    Возвращает словарь сырых значений (для evidence) и матрицу для модели в
    **канонической** системе координат. Билдер ограничивается одной серией:
    собирать весь датасет ради одного предсказания бессмысленно.
    """
    builder = PriorFormBuilder(
        session,
        params,
        evaluation_mode=EVENT_ASOF,
        series_ids={target["series_id"]},
    )
    frame, _meta = builder.build()
    if frame.empty:
        raise PredictionError("prior-form dataset is empty")

    series_id = target["series_id"]
    if series_id is None:
        raise PredictionError("target has no series_id")
    match = frame[frame["series_id"] == series_id]
    if match.empty:
        raise PredictionError(f"no prior-form row for series {series_id}")
    if len(match) > 1:  # noqa: RET503 — защитная проверка уникальности
        raise PredictionError(f"multiple prior-form rows for series {series_id}")

    record = match.iloc[0].to_dict()
    # Разворот в каноническую систему координат, если slot-0 — не Team A.
    if not target["slot0_is_team_a"]:
        record = _flip_sides(record, feature_columns)

    # Маски доступности нужны evidence; переносятся из развёрнутой записи.
    feature_row = dict(record)
    values = {col: record.get(col) for col in feature_columns}
    x = np.array(
        [[_numeric(values[col]) for col in feature_columns]], dtype=float
    )
    return feature_row, x


def _flip_sides(record: dict[str, Any], feature_columns: list[str]) -> dict[str, Any]:
    """Переставить стороны A↔B, инвертировать дифференциалы и метку."""
    flipped = dict(record)
    pairs = [
        ("team_a_", "team_b_"),
        ("player_a_", "player_b_"),
    ]
    for prefix_a, prefix_b in pairs:
        keys_a = [k for k in record if k.startswith(prefix_a)]
        keys_b = [k for k in record if k.startswith(prefix_b)]
        for key_a, key_b in zip(keys_a, keys_b, strict=True):
            suffix = key_a[len(prefix_a):]
            flipped[key_a] = record.get(f"{prefix_b}{suffix}")
            flipped[key_b] = record.get(f"{prefix_a}{suffix}")
    for key in feature_columns:
        if key.startswith("d_"):
            value = record.get(key)
            if isinstance(value, int | float) and not (
                isinstance(value, float) and np.isnan(value)
            ):
                flipped[key] = -value
    flipped["y"] = 1 - int(record.get("y", 0))
    return flipped


def _numeric(value: Any) -> float:
    """Любое числовое значение → float; None/NaN → NaN для последующей маску."""
    if value is None:
        return float("nan")
    try:
        result = float(value)
    except (TypeError, ValueError):
        return float("nan")
    return result


def _assert_purity(
    feature_row: dict[str, Any],
    cutoff_at: datetime,
    session: Session,
    team_ids: tuple[UUID, UUID],
    params: PriorFormParams,
) -> None:
    """AC #6: ни один снимок не содержит данных с available_at > cutoff.

    На ретро-контуре cutoff = event_time целевой карты, а история отсечена
    режимом `event_asof` (`assumed_available_at = event_time + result_lag`).
    Здесь это дублируется на уровне API: независимый подсчёт завершённых
    карт обеих команд, чьи результаты **могли быть известны** к cutoff, и
    сравнение с тем, что сообщают признаки. Расхождение в большую сторону =
    будущее просочилось в признаки — критическое нарушение, лучше упасть,
    чем писать снимок.
    """
    for team_id, side in zip(team_ids, ("a", "b"), strict=True):
        n_reported = feature_row.get(f"team_{side}_n_games")
        if n_reported is None:
            continue
        available = session.execute(
            text(_PRIOR_GAMES_COUNT_SQL),
            {
                "team_id": team_id,
                "cutoff": cutoff_at,
                "lag_seconds": params.result_lag.total_seconds(),
            },
        ).scalar()
        if available is None:
            available = 0
        if int(n_reported) > int(available):
            raise PredictionError(
                f"purity violation: team {side} features report {n_reported} games "
                f"but only {available} are available at cutoff "
                f"{cutoff_at.isoformat()} (event_asof lag {params.result_lag})"
            )


_PRIOR_GAMES_COUNT_SQL = """
    SELECT count(*) AS n
      FROM game AS g
      JOIN game_team AS gt ON gt.game_id = g.id
     WHERE gt.team_id = CAST(:team_id AS uuid)
       AND g.winner_team_id IS NOT NULL
       AND g.event_time IS NOT NULL
       AND (g.event_time + make_interval(secs => :lag_seconds))
           <= CAST(:cutoff AS timestamptz)
"""


def _latest_model_version(session: Session, algorithm: str) -> dict[str, Any]:
    row = session.execute(
        text(LATEST_MODEL_SQL), {"algorithm": algorithm}
    ).first()
    if row is None:
        raise PredictionError(f"no model_version for algorithm={algorithm}")
    return {
        "id": UUID(str(row.id)),
        "algorithm": row.algorithm,
        "feature_schema_version": row.feature_schema_version,
        "artifact_uri": row.artifact_uri,
        "artifact_hash": row.artifact_hash,
        "hyperparameters": (
            json.loads(row.hyperparameters) if isinstance(row.hyperparameters, str) else row.hyperparameters
        ),
    }


@router.post("/predict/game/{game_id}")
def predict_game(game_id: UUID, db: Session = Depends(get_db)) -> JSONResponse:  # noqa: B008
    """Предсказать P(Team A выигрывает карту 1) для конкретной игры.

    Только game1 (map_number = 1). Series-цели обрабатываются другим
    эндпоинтом, которого здесь нет — задача API-001 этого не требует.
    """
    try:
        target = _canonical_teams(db, game_id)
    except PredictionError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
        ) from exc

    cutoff_at = target["event_time"]
    evaluation_mode = "retrospective_reconstructed"

    try:
        model_version = _latest_model_version(db, algorithm="logreg_prior_form")
        feature_columns = _feature_columns(model_version["hyperparameters"])
        params = _params_from_hyperparameters(model_version["hyperparameters"])
    except PredictionError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc

    try:
        feature_row, x = _build_features(db, target, params, feature_columns)
    except PredictionError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)
        ) from exc

    try:
        _assert_purity(
            feature_row,
            cutoff_at,
            db,
            (target["team_a_id"], target["team_b_id"]),
            params,
        )
    except PredictionError as exc:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)
        ) from exc

    model = _load_model(model_version["artifact_uri"])
    proba = model.predict_proba(_impute(x))[0][1]
    p_a = float(proba)

    result = write_prediction_snapshot(
        db,
        game_id=game_id,
        team_a_id=target["team_a_id"],
        team_b_id=target["team_b_id"],
        model_version=model_version,
        cutoff_at=cutoff_at,
        p_a=p_a,
        evaluation_mode=evaluation_mode,
        feature_row=feature_row,
        feature_columns=feature_columns,
    )
    db.commit()

    response = PredictionResponse(
        prediction_id=result["prediction_id"],
        snapshot_id=result["snapshot_id"],
        model_version_id=str(model_version["id"]),
        algorithm=model_version["algorithm"],
        feature_schema_version=model_version["feature_schema_version"],
        cutoff_at=cutoff_at.isoformat(),
        evaluation_mode=evaluation_mode,
        target_phase=TARGET_PHASE,
        lag_policy_version=LAG_POLICY_VERSION,
        p_a=p_a,
        p_b=1.0 - p_a,
        evidence=build_template_evidence(
            p_a=p_a,
            feature_row=feature_row,
            feature_columns=feature_columns,
            model_version=model_version,
            cutoff_at=cutoff_at.isoformat(),
        ),
        evidence_version=PREDICTION_TEMPLATE_EVIDENCE_VERSION,
    )
    return JSONResponse(
        status_code=status.HTTP_200_OK,
        content=json.loads(response.model_dump_json()),
    )


def _params_from_hyperparameters(
    hyperparameters: dict[str, Any] | None,
) -> PriorFormParams:
    """Восстановить PriorFormParams из гиперпараметров версии модели.

    μ фитится на train при обучении и сохраняется в гиперпараметрах —
    инференс обязан использовать то же значение, иначе признаки на
    обучении и сервинге разойдутся.
    """
    if not hyperparameters:
        return PriorFormParams()
    prior_mean = hyperparameters.get("prior_mean")
    overrides: dict[str, Any] = {}
    if prior_mean is not None:
        overrides["prior_mean"] = float(prior_mean)
    return PriorFormParams(**overrides)
