"""UI-001 — страница матча на реальной held-out исторической game1.

Требования карточки UI-001: явная метка ретроспективы, провенанс и версия
модели, отсутствие элементов, имитирующих live, локальная работа. Отрисовка
серверная (Jinja2), без JS и клиентских фреймворков.

Чтение — только существующие снимки (`GET /match/{game_id}`), запись —
явным действием (`POST /match/{game_id}/predict`), как и в API-001: каждый
вызов сервиса создаёт новый immutable `prediction_snapshot`. Пользователь
попадает на последний рассчитанный снимок через `GET /`.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from fastapi.templating import Jinja2Templates
from sqlalchemy import text
from sqlalchemy.orm import Session
from starlette.requests import Request

from d2intel.api.predict import PredictionError, compute_prediction
from d2intel.db import get_db

router = APIRouter(tags=["web"], include_in_schema=False)

templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))

GAME_VIEW_SQL = """
    SELECT
        g.id AS game_id,
        g.event_time AS event_time,
        g.status AS game_status,
        g.winner_team_id AS winner_team_id,
        gt0.team_id AS slot0_team_id,
        gt1.team_id AS slot1_team_id,
        t0.canonical_name AS slot0_name,
        t1.canonical_name AS slot1_name,
        tor.name AS tournament_name,
        src.name AS source_name
    FROM game AS g
    JOIN game_team AS gt0 ON gt0.game_id = g.id AND gt0.slot = 0
    JOIN game_team AS gt1 ON gt1.game_id = g.id AND gt1.slot = 1
    JOIN team AS t0 ON t0.id = gt0.team_id
    JOIN team AS t1 ON t1.id = gt1.team_id
    LEFT JOIN series AS s ON s.id = g.series_id
    LEFT JOIN tournament AS tor ON tor.id = s.tournament_id
    LEFT JOIN source_observation AS so ON so.id = g.source_observation_id
    LEFT JOIN ingestion_run AS ir ON ir.id = so.run_id
    LEFT JOIN data_source AS src ON src.id = ir.source_id
    WHERE g.id = CAST(:game_id AS uuid)
"""

LATEST_SNAPSHOT_SQL = """
    SELECT
        ps.id AS snapshot_id,
        ps.snapshot_seq AS snapshot_seq,
        ps.computed_at AS computed_at,
        ps.cutoff_at AS cutoff_at,
        ps.p_a AS p_a,
        ps.p_b AS p_b,
        ps.evaluation_mode AS evaluation_mode,
        ps.abstention_reason AS abstention_reason,
        ps.state_hash AS state_hash,
        p.id AS prediction_id,
        mv.algorithm AS algorithm,
        mv.id AS model_version_id,
        mv.feature_schema_version AS feature_schema_version,
        mv.artifact_hash AS artifact_hash,
        mv.hyperparameters AS hyperparameters,
        fs.values_json AS values_json,
        fs.coverage_json AS coverage_json,
        fs.assumed_available_at AS assumed_available_at,
        fs.lag_policy_version AS lag_policy_version
    FROM prediction AS p
    JOIN prediction_snapshot AS ps ON ps.prediction_id = p.id
    LEFT JOIN model_version AS mv ON mv.id = ps.model_version_id
    LEFT JOIN feature_snapshot AS fs ON fs.id = ps.feature_snapshot_id
    WHERE p.target_game_id = CAST(:game_id AS uuid)
    ORDER BY ps.snapshot_seq DESC
    LIMIT 1
"""


@router.get("/", response_class=HTMLResponse)
def index(db: Session = Depends(get_db)) -> Response:  # noqa: B008
    """Открыть последний рассчитанный снимок; если снимков нет — подсказка."""
    row = db.execute(
        text(
            "SELECT p.target_game_id FROM prediction AS p "
            "JOIN prediction_snapshot AS ps ON ps.prediction_id = p.id "
            "ORDER BY ps.computed_at DESC, ps.snapshot_seq DESC LIMIT 1"
        )
    ).first()
    if row is None or row.target_game_id is None:
        return HTMLResponse(
            "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
            "<title>d2intel</title></head><body><h1>d2intel</h1>"
            "<p>Снимков прогнозов ещё нет. Создайте первый: POST"
            " /predict/game/{game_id}, затем откройте /match/{game_id}.</p>"
            "</body></html>",
            status_code=status.HTTP_200_OK,
        )
    return RedirectResponse(f"/match/{row.target_game_id}", status_code=307)


@router.get("/match/{game_id}", response_class=HTMLResponse)
def match_page(
    game_id: UUID, request: Request, db: Session = Depends(get_db)  # noqa: B008
) -> Response:
    """Страница матча: ретроспективное предсказание с провенансом."""
    game_row = db.execute(text(GAME_VIEW_SQL), {"game_id": str(game_id)}).first()
    if game_row is None:
        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context={"message": f"Игра не найдена: {game_id}"},
            status_code=status.HTTP_404_NOT_FOUND,
        )
    snapshot = _load_latest_snapshot(db, game_id)
    context = _build_match_context(game_row, snapshot)
    return templates.TemplateResponse(
        request=request, name="match.html", context=context
    )


@router.post("/match/{game_id}/predict")
def match_predict(
    game_id: UUID, request: Request, db: Session = Depends(get_db)  # noqa: B008
) -> Response:
    """Явное действие: рассчитать и записать новый immutable снимок."""
    try:
        compute_prediction(db, game_id)
        db.commit()
    except PredictionError as exc:
        db.rollback()
        return templates.TemplateResponse(
            request=request,
            name="error.html",
            context={"message": f"Прогноз невозможен: {exc}"},
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    return RedirectResponse(f"/match/{game_id}", status_code=303)


def _load_latest_snapshot(db: Session, game_id: UUID) -> dict[str, Any] | None:
    """Последний снимок прогноза игры или None — страница честно это покажет."""
    row = db.execute(text(LATEST_SNAPSHOT_SQL), {"game_id": str(game_id)}).first()
    if row is None:
        return None
    data = dict(row._mapping)
    data["values"] = _as_dict(data["values_json"])
    data["coverage"] = _as_dict(data["coverage_json"])
    data["hyperparameters"] = _as_dict(data["hyperparameters"])
    return data


def _as_dict(raw: Any) -> dict[str, Any]:
    """jsonb-значение (строка от psycopg или dict) в dict, None → {}."""
    if isinstance(raw, str):
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    return raw if isinstance(raw, dict) else {}


def _build_match_context(
    game_row: Any, snapshot: dict[str, Any] | None
) -> dict[str, Any]:
    """Собрать контекст шаблона из канонических координат (team_a < team_b)."""
    slot0_id, slot1_id = (
        UUID(str(game_row.slot0_team_id)),
        UUID(str(game_row.slot1_team_id)),
    )
    if slot0_id < slot1_id:
        team_a = {"id": str(slot0_id), "name": game_row.slot0_name}
        team_b = {"id": str(slot1_id), "name": game_row.slot1_name}
    else:
        team_a = {"id": str(slot1_id), "name": game_row.slot1_name}
        team_b = {"id": str(slot0_id), "name": game_row.slot0_name}

    context: dict[str, Any] = {
        "game_id": str(game_row.game_id),
        "event_time": game_row.event_time.isoformat() if game_row.event_time else None,
        "game_status": game_row.game_status,
        "tournament_name": game_row.tournament_name,
        "source_name": game_row.source_name,
        "team_a": team_a,
        "team_b": team_b,
        "snapshot": None,
        "outcome": None,
    }

    if snapshot is None:
        return context

    values: dict[str, Any] = snapshot["values"]
    coverage: dict[str, Any] = snapshot["coverage"]
    hyper: dict[str, Any] = snapshot["hyperparameters"]
    p_a = float(snapshot["p_a"]) if snapshot["p_a"] is not None else None

    feature_rows = [
        {
            "name": name,
            "value": ("неизвестно" if values.get(name) is None else f"{values[name]:+.4f}"),
            "known": values.get(name) is not None,
        }
        for name in sorted(values)
    ]
    unknown_features = [name for name in sorted(values) if values.get(name) is None]

    winner_id = UUID(str(game_row.winner_team_id)) if game_row.winner_team_id else None
    outcome = None
    if winner_id is not None and p_a is not None:
        winner = team_a if winner_id == UUID(team_a["id"]) else team_b
        outcome = {
            "winner_name": winner["name"],
            "correct": (winner_id == UUID(team_a["id"])) == (p_a >= 0.5),
        }

    context["snapshot"] = {
        "snapshot_id": str(snapshot["snapshot_id"]),
        "snapshot_seq": snapshot["snapshot_seq"],
        "prediction_id": str(snapshot["prediction_id"]),
        "computed_at": (
            snapshot["computed_at"].isoformat() if snapshot["computed_at"] else None
        ),
        "cutoff_at": snapshot["cutoff_at"].isoformat() if snapshot["cutoff_at"] else None,
        "evaluation_mode": snapshot["evaluation_mode"],
        "abstention_reason": snapshot["abstention_reason"],
        "state_hash": str(snapshot["state_hash"])[:16],
        "lag_policy_version": snapshot["lag_policy_version"],
        "assumed_available_at": (
            snapshot["assumed_available_at"].isoformat()
            if snapshot["assumed_available_at"]
            else None
        ),
        "algorithm": snapshot["algorithm"],
        "model_version_id": str(snapshot["model_version_id"])
        if snapshot["model_version_id"]
        else None,
        "feature_schema_version": snapshot["feature_schema_version"],
        "artifact_hash": str(snapshot["artifact_hash"] or "")[:16],
        "run_key": hyper.get("run_key"),
        "c": hyper.get("c"),
        "n_train": hyper.get("n_train"),
        "prior_mean": hyper.get("prior_mean"),
        "p_a": p_a,
        "p_b": float(snapshot["p_b"]) if snapshot["p_b"] is not None else None,
        "feature_rows": feature_rows,
        "unknown_features": unknown_features,
        "team_a_avail": bool(coverage.get("team_a_avail")),
        "team_b_avail": bool(coverage.get("team_b_avail")),
        "player_avail": bool(coverage.get("player_a_avail"))
        and bool(coverage.get("player_b_avail")),
    }
    context["outcome"] = outcome
    return context
