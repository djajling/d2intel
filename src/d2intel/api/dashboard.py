"""Read-only data endpoints for the local prediction workbench.

The UI only exposes completed, identity-resolved game 1 targets. Predictions
are still created through the existing immutable `/predict/game/{game_id}`
service; this module never writes to the database.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from d2intel.db import get_db

router = APIRouter(prefix="/api", tags=["dashboard"])
ARTIFACTS_DIR = Path("artifacts/models")

_ELIGIBLE_MATCHES = """
    SELECT
        g.id AS game_id,
        g.series_id AS series_id,
        g.map_number AS map_number,
        g.status AS game_status,
        g.event_time AS event_time,
        g.winner_team_id AS winner_team_id,
        s.best_of AS best_of,
        tournament.name AS tournament_name,
        patch.version_label AS patch_label,
        CASE WHEN gta.team_id < gtb.team_id THEN gta.team_id ELSE gtb.team_id END
            AS team_a_id,
        CASE WHEN gta.team_id < gtb.team_id THEN gtb.team_id ELSE gta.team_id END
            AS team_b_id,
        CASE WHEN gta.team_id < gtb.team_id THEN team_a.canonical_name
             ELSE team_b.canonical_name END AS team_a,
        CASE WHEN gta.team_id < gtb.team_id THEN team_b.canonical_name
             ELSE team_a.canonical_name END AS team_b
    FROM game AS g
    JOIN game_team AS gta ON gta.game_id = g.id AND gta.slot = 0
    JOIN game_team AS gtb ON gtb.game_id = g.id AND gtb.slot = 1
    JOIN team AS team_a ON team_a.id = gta.team_id
    JOIN team AS team_b ON team_b.id = gtb.team_id
    JOIN series AS s ON s.id = g.series_id
    LEFT JOIN tournament ON tournament.id = s.tournament_id
    LEFT JOIN patch ON patch.id = g.patch_id
    WHERE g.map_number = 1
      AND g.status = 'completed'
      AND g.result_type = 'played'
      AND g.series_id IS NOT NULL
      AND g.event_time IS NOT NULL
      AND g.winner_team_id IN (gta.team_id, gtb.team_id)
      AND gta.team_id <> gtb.team_id
      AND team_a.identity_status = 'resolved'
      AND team_b.identity_status = 'resolved'
      AND team_a.canonical_name IS NOT NULL
      AND team_b.canonical_name IS NOT NULL
"""

MATCHES_COUNT_SQL = f"""
    WITH eligible AS ({_ELIGIBLE_MATCHES})
    SELECT count(*)
      FROM eligible
     WHERE (CAST(:search AS text) IS NULL
            OR team_a ILIKE :search
            OR team_b ILIKE :search
            OR COALESCE(tournament_name, '') ILIKE :search)
"""

MATCHES_SQL = f"""
    WITH eligible AS ({_ELIGIBLE_MATCHES})
    SELECT
        eligible.*,
        CASE WHEN winner_team_id = team_a_id THEN team_a ELSE team_b END AS winner_team,
        latest.snapshot_id AS latest_snapshot_id,
        latest.snapshot_seq AS latest_snapshot_seq,
        latest.p_a AS latest_p_a,
        latest.p_b AS latest_p_b,
        latest.abstention_reason AS latest_abstention_reason,
        latest.computed_at AS latest_computed_at,
        latest.evaluation_mode AS latest_evaluation_mode
      FROM eligible
      LEFT JOIN LATERAL (
          SELECT ps.id AS snapshot_id, ps.snapshot_seq, ps.p_a, ps.p_b,
                 ps.abstention_reason, ps.computed_at, ps.evaluation_mode
            FROM prediction AS prediction_record
            JOIN prediction_snapshot AS ps ON ps.prediction_id = prediction_record.id
           WHERE prediction_record.target_type = 'game'
             AND prediction_record.target_game_id = eligible.game_id
           ORDER BY ps.computed_at DESC, ps.snapshot_seq DESC
           LIMIT 1
      ) AS latest ON TRUE
     WHERE (CAST(:search AS text) IS NULL
            OR team_a ILIKE :search
            OR team_b ILIKE :search
            OR COALESCE(tournament_name, '') ILIKE :search)
     ORDER BY event_time DESC, game_id DESC
     LIMIT :limit OFFSET :offset
"""

OVERVIEW_SQL = f"""
    WITH eligible AS ({_ELIGIBLE_MATCHES})
    SELECT
        (SELECT count(*) FROM eligible) AS eligible_matches,
        (SELECT max(event_time) FROM eligible) AS latest_match_at,
        (SELECT count(*)
           FROM prediction_snapshot AS ps
           JOIN prediction AS p ON p.id = ps.prediction_id
          WHERE p.target_type = 'game') AS saved_snapshots,
        (SELECT count(*)
           FROM prediction_snapshot AS ps
           JOIN prediction AS p ON p.id = ps.prediction_id
          WHERE p.target_type = 'game'
            AND ps.evaluation_mode = 'prospective_observed') AS observed_snapshots,
        (SELECT count(DISTINCT pe.snapshot_id)
           FROM prediction_evaluation AS pe
           JOIN prediction_snapshot AS ps ON ps.id = pe.snapshot_id
           JOIN prediction AS p ON p.id = ps.prediction_id
          WHERE pe.y IS NOT NULL
            AND p.target_type = 'game') AS evaluated_snapshots,
        (SELECT id FROM model_version
          WHERE algorithm = 'logreg_prior_form'
          ORDER BY computed_at DESC LIMIT 1) AS latest_model_version_id,
        (SELECT feature_schema_version FROM model_version
          WHERE algorithm = 'logreg_prior_form'
          ORDER BY computed_at DESC LIMIT 1) AS latest_feature_schema_version,
        (SELECT artifact_uri FROM model_version
          WHERE algorithm = 'logreg_prior_form'
          ORDER BY computed_at DESC LIMIT 1) AS latest_model_artifact_uri
"""

PREDICTIONS_SELECT = """
    SELECT
        ps.id AS snapshot_id,
        ps.prediction_id AS prediction_id,
        ps.snapshot_seq AS snapshot_seq,
        ps.computed_at AS computed_at,
        ps.cutoff_at AS cutoff_at,
        ps.p_a AS p_a,
        ps.p_b AS p_b,
        ps.abstention_reason AS abstention_reason,
        ps.evaluation_mode AS evaluation_mode,
        ps.feature_snapshot_id AS feature_snapshot_id,
        p.target_game_id AS target_game_id,
        p.phase_contract AS phase_contract,
        team_a.canonical_name AS team_a,
        team_b.canonical_name AS team_b,
        g.event_time AS game_event_time,
        g.map_number AS map_number,
        g.status AS game_status,
        tournament.name AS tournament_name,
        s.best_of AS best_of,
        patch.version_label AS patch_label,
        CASE WHEN g.winner_team_id = p.team_a_id THEN team_a.canonical_name
             WHEN g.winner_team_id = p.team_b_id THEN team_b.canonical_name
             ELSE NULL END AS actual_winner,
        model.id AS model_version_id,
        model.algorithm AS model_algorithm,
        model.feature_schema_version AS feature_schema_version,
        evaluation.y AS evaluation_y,
        evaluation.log_loss AS log_loss,
        evaluation.brier AS brier
    FROM prediction_snapshot AS ps
    JOIN prediction AS p ON p.id = ps.prediction_id
    LEFT JOIN game AS g ON g.id = p.target_game_id
    LEFT JOIN series AS s ON s.id = g.series_id
    LEFT JOIN tournament ON tournament.id = s.tournament_id
    LEFT JOIN patch ON patch.id = g.patch_id
    LEFT JOIN team AS team_a ON team_a.id = p.team_a_id
    LEFT JOIN team AS team_b ON team_b.id = p.team_b_id
    LEFT JOIN model_version AS model ON model.id = ps.model_version_id
    LEFT JOIN LATERAL (
        SELECT pe.y, pe.log_loss, pe.brier
          FROM prediction_evaluation AS pe
         WHERE pe.snapshot_id = ps.id
         ORDER BY pe.evaluated_at DESC, pe.id DESC
         LIMIT 1
    ) AS evaluation ON TRUE
    WHERE p.target_type = 'game'
      AND p.target_game_id IS NOT NULL
"""

PREDICTIONS_SQL = f"""
    {PREDICTIONS_SELECT}
    ORDER BY ps.computed_at DESC, ps.snapshot_seq DESC
    LIMIT :limit OFFSET :offset
"""

PREDICTION_DETAIL_SQL = """
    SELECT
        ps.id AS snapshot_id,
        ps.prediction_id AS prediction_id,
        ps.snapshot_seq AS snapshot_seq,
        ps.computed_at AS computed_at,
        ps.cutoff_at AS cutoff_at,
        ps.p_a AS p_a,
        ps.p_b AS p_b,
        ps.abstention_reason AS abstention_reason,
        ps.evaluation_mode AS evaluation_mode,
        ps.feature_snapshot_id AS feature_snapshot_id,
        p.target_game_id AS target_game_id,
        p.phase_contract AS phase_contract,
        team_a.canonical_name AS team_a,
        team_b.canonical_name AS team_b,
        g.event_time AS game_event_time,
        g.map_number AS map_number,
        g.status AS game_status,
        tournament.name AS tournament_name,
        s.best_of AS best_of,
        patch.version_label AS patch_label,
        CASE WHEN g.winner_team_id = p.team_a_id THEN team_a.canonical_name
             WHEN g.winner_team_id = p.team_b_id THEN team_b.canonical_name
             ELSE NULL END AS actual_winner,
        model.id AS model_version_id,
        model.algorithm AS model_algorithm,
        model.feature_schema_version AS feature_schema_version,
        feature.values_json AS feature_values,
        feature.coverage_json AS feature_coverage,
        evaluation.y AS evaluation_y,
        evaluation.log_loss AS log_loss,
        evaluation.brier AS brier
    FROM prediction_snapshot AS ps
    JOIN prediction AS p ON p.id = ps.prediction_id
    LEFT JOIN game AS g ON g.id = p.target_game_id
    LEFT JOIN series AS s ON s.id = g.series_id
    LEFT JOIN tournament ON tournament.id = s.tournament_id
    LEFT JOIN patch ON patch.id = g.patch_id
    LEFT JOIN team AS team_a ON team_a.id = p.team_a_id
    LEFT JOIN team AS team_b ON team_b.id = p.team_b_id
    LEFT JOIN model_version AS model ON model.id = ps.model_version_id
    LEFT JOIN feature_snapshot AS feature ON feature.id = ps.feature_snapshot_id
    LEFT JOIN LATERAL (
        SELECT pe.y, pe.log_loss, pe.brier
          FROM prediction_evaluation AS pe
         WHERE pe.snapshot_id = ps.id
         ORDER BY pe.evaluated_at DESC, pe.id DESC
         LIMIT 1
    ) AS evaluation ON TRUE
    WHERE p.target_type = 'game'
      AND p.target_game_id IS NOT NULL
      AND ps.id = CAST(:snapshot_id AS uuid)
"""


def _row_dict(row: Any) -> dict[str, Any]:
    """Convert a SQLAlchemy row (or mapping) to a JSON-encodable dictionary."""
    return dict(getattr(row, "_mapping", row))


def _model_artifact_available(uri: str | None) -> bool:
    """Mirror the prediction service's relative artifact path resolution."""
    if not uri:
        return False
    path = Path(uri)
    if not path.is_absolute():
        path = ARTIFACTS_DIR / path
    try:
        return path.is_file()
    except OSError:
        return False


def _database_unavailable(exc: SQLAlchemyError, action: str) -> HTTPException:
    """Return a safe 503 without echoing SQL/connection details to the UI."""
    del exc
    return HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail=f"Не удалось {action}: база данных недоступна.",
    )


@router.get("/overview")
def get_overview(db: Session = Depends(get_db)) -> dict[str, Any]:  # noqa: B008
    """Сводные счётчики, последняя дата выборки и доступность артефакта модели."""
    try:
        row = db.execute(text(OVERVIEW_SQL)).first()
    except SQLAlchemyError as exc:
        raise _database_unavailable(exc, "загрузить сводку") from exc
    if row is None:
        return {
            "eligible_matches": 0,
            "latest_match_at": None,
            "saved_snapshots": 0,
            "observed_snapshots": 0,
            "evaluated_snapshots": 0,
            "latest_model_version_id": None,
            "latest_feature_schema_version": None,
            "model_available": False,
        }
    result = _row_dict(row)
    model_artifact_uri = result.pop("latest_model_artifact_uri", None)
    result["model_available"] = _model_artifact_available(model_artifact_uri)
    return result


@router.get("/matches")
def list_matches(
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100_000),
    search: str | None = Query(default=None, max_length=80),
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """Найти завершённые game1 цели с разрешёнными именами команд."""
    normalized_search = search.strip() if search and search.strip() else None
    params: dict[str, Any] = {
        "search": f"%{normalized_search}%" if normalized_search else None,
        "limit": limit,
        "offset": offset,
    }
    try:
        total = db.execute(
            text(MATCHES_COUNT_SQL), {"search": params["search"]}
        ).scalar_one()
        rows = db.execute(text(MATCHES_SQL), params).all()
    except SQLAlchemyError as exc:
        raise _database_unavailable(exc, "загрузить историю матчей") from exc
    return {"items": [_row_dict(row) for row in rows], "total": int(total)}


@router.get("/predictions/{snapshot_id}")
def get_prediction(
    snapshot_id: UUID,
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """Полная карточка одного снимка, включая сохранённые признаки."""
    try:
        row = db.execute(
            text(PREDICTION_DETAIL_SQL), {"snapshot_id": str(snapshot_id)}
        ).first()
    except SQLAlchemyError as exc:
        raise _database_unavailable(exc, "загрузить снимок прогноза") from exc
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Снимок прогноза не найден.",
        )
    return _row_dict(row)


@router.get("/predictions")
def list_predictions(
    limit: int = Query(default=100, ge=1, le=100),
    offset: int = Query(default=0, ge=0, le=100_000),
    db: Session = Depends(get_db),  # noqa: B008
) -> dict[str, Any]:
    """Последние неизменяемые снимки и оценки — без крупных feature JSONB."""
    try:
        rows = db.execute(
            text(PREDICTIONS_SQL), {"limit": limit, "offset": offset}
        ).all()
    except SQLAlchemyError as exc:
        raise _database_unavailable(exc, "загрузить журнал прогнозов") from exc
    return {"items": [_row_dict(row) for row in rows]}
