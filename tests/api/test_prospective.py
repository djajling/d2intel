"""PROSPECTIVE — тесты честной фиксации прогноза до результата (вариант C).

Покрывает то, чем отличается prospective от ретроспективной реконструкции:

* `prospective_observed` **запрещает** `assumed_available_at` — задержка не
  реконструируется, признаки были реально известны в момент cutoff
  (constraint `feature_snapshot_lag_policy`);
* записанный снимок несёт режим prospective и `assumed_available_at IS NULL`;
* `prospective_reconcile` находит доигранную **game1** после cutoff и честно
  сообщает причину, когда связать нельзя (игры нет / map index не доказан).
"""

from __future__ import annotations

import importlib.util
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from d2intel.api.snapshots import (
    PROSPECTIVE_MODE,
    RETROSPECTIVE_MODE,
    write_feature_snapshot,
    write_prediction_snapshot,
)

FEATURE_COLUMNS = [
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

SCRIPTS_DIR = Path(__file__).resolve().parents[2] / "scripts"


def _load_reconcile() -> Any:
    """Импортировать reconcile-скрипт как модуль (он не часть пакета)."""
    spec = importlib.util.spec_from_file_location(
        "prospective_reconcile", SCRIPTS_DIR / "prospective_reconcile.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def model_version(db_session: Session) -> dict[str, Any]:
    """Минимальная версия модели для записи снимка."""
    row = db_session.execute(
        text(
            """
            INSERT INTO model_version (
                algorithm, feature_schema_version, seed, hyperparameters,
                artifact_uri, artifact_hash, promotion_status, computed_at
            ) VALUES (
                'logreg_prior_form', 'prior-form.v1', 17,
                CAST(:hyperparameters AS jsonb), 'test.joblib', 'test-hash',
                'candidate', now()
            ) RETURNING id
            """
        ),
        {
            "hyperparameters": json.dumps(
                {"c": 1.0, "feature_columns": FEATURE_COLUMNS, "prior_mean": 0.51}
            )
        },
    ).scalar_one()
    db_session.flush()
    return {
        "id": str(row),
        "feature_schema_version": "prior-form.v1",
        "lag_policy_version": "lag-policy.v1",
    }


def _link_teams(db_session: Session, game_fixture: dict[str, str]) -> None:
    """Привязать команды к карте по слотам: 0 — radiant, 1 — dire.

    `reconcile` ищет пару именно через `game_team`, поэтому без этих строк
    игра для него просто не существует.
    """
    for slot, (team_key, side) in enumerate(
        (("team_a", "radiant"), ("team_b", "dire"))
    ):
        db_session.execute(
            text(
                """
                INSERT INTO game_team (
                    game_id, team_id, side, slot, source_observation_id,
                    observed_at, ingested_at, available_at
                ) VALUES (
                    CAST(:game_id AS uuid), CAST(:team_id AS uuid), :side, :slot,
                    CAST(:observation AS uuid), now(), now(), now()
                )
                """
            ),
            {
                "game_id": game_fixture["game"],
                "team_id": game_fixture[team_key],
                "side": side,
                "slot": slot,
                "observation": game_fixture["observation"],
            },
        )
    db_session.flush()


@pytest.fixture
def played_game1(db_session: Session, game_fixture: dict[str, str]) -> dict[str, str]:
    """game1 с известным победителем — то, с чем reconcile и связывает."""
    _link_teams(db_session, game_fixture)
    game_id = game_fixture["game"]
    db_session.execute(
        text(
            """
            UPDATE game
               SET winner_team_id = CAST(:winner AS uuid),
                   result_type = 'played',
                   event_time = now()
             WHERE id = CAST(:game_id AS uuid)
            """
        ),
        {"winner": game_fixture["team_a"], "game_id": game_id},
    )
    db_session.flush()
    return game_fixture


def _feature_row() -> dict[str, Any]:
    return dict.fromkeys(FEATURE_COLUMNS, 0.1)


def test_prospective_mode_forbids_assumed_availability(
    db_session: Session, game_fixture: dict[str, str]
) -> None:
    """Prospective не реконструирует задержку → assumed-время запрещено."""
    with pytest.raises(ValueError, match="assumed_available_at"):
        write_feature_snapshot(
            db_session,
            game_id=UUID(game_fixture["game"]),
            cutoff_at=datetime.now(UTC),
            feature_row=_feature_row(),
            feature_columns=FEATURE_COLUMNS,
            feature_schema_version="prior-form.v1",
            lag_policy_version="lag-policy.v1",
            assumed_available_at=datetime.now(UTC),
            evaluation_mode=PROSPECTIVE_MODE,
        )


def test_prospective_snapshot_is_written_without_assumed_availability(
    db_session: Session, played_game1: dict[str, str], model_version: dict[str, Any]
) -> None:
    """Снимок prospective: режим в обеих таблицах, assumed IS NULL."""
    cutoff = datetime.now(UTC) - timedelta(hours=1)
    result = write_prediction_snapshot(
        db_session,
        game_id=UUID(played_game1["game"]),
        team_a_id=UUID(played_game1["team_a"]),
        team_b_id=UUID(played_game1["team_b"]),
        model_version=model_version,
        cutoff_at=cutoff,
        p_a=0.47,
        evaluation_mode=PROSPECTIVE_MODE,
        feature_row=_feature_row(),
        feature_columns=FEATURE_COLUMNS,
        assumed_available_at=None,
    )

    feature = db_session.execute(
        text(
            """
            SELECT evaluation_mode, assumed_available_at, lag_policy_version
              FROM feature_snapshot
             WHERE id = CAST(:id AS uuid)
            """
        ),
        {"id": result["feature_snapshot_id"]},
    ).one()
    assert feature.evaluation_mode == PROSPECTIVE_MODE
    assert feature.assumed_available_at is None
    assert feature.lag_policy_version is not None

    snapshot = db_session.execute(
        text(
            """
            SELECT evaluation_mode, cutoff_at
              FROM prediction_snapshot
             WHERE id = CAST(:id AS uuid)
            """
        ),
        {"id": result["snapshot_id"]},
    ).one()
    assert snapshot.evaluation_mode == PROSPECTIVE_MODE
    # cutoff — момент заморозки, а не время игры.
    assert snapshot.cutoff_at == cutoff


def test_retrospective_still_uses_assumed_availability(
    db_session: Session, played_game1: dict[str, str], model_version: dict[str, Any]
) -> None:
    """Ретро-режим не сломан: assumed подставляется из cutoff по умолчанию."""
    cutoff = datetime.now(UTC) - timedelta(hours=1)
    result = write_prediction_snapshot(
        db_session,
        game_id=UUID(played_game1["game"]),
        team_a_id=UUID(played_game1["team_a"]),
        team_b_id=UUID(played_game1["team_b"]),
        model_version=model_version,
        cutoff_at=cutoff,
        p_a=0.5,
        evaluation_mode=RETROSPECTIVE_MODE,
        feature_row=_feature_row(),
        feature_columns=FEATURE_COLUMNS,
    )
    feature = db_session.execute(
        text(
            """
            SELECT evaluation_mode, assumed_available_at
              FROM feature_snapshot
             WHERE id = CAST(:id AS uuid)
            """
        ),
        {"id": result["feature_snapshot_id"]},
    ).one()
    assert feature.evaluation_mode == RETROSPECTIVE_MODE
    assert feature.assumed_available_at is not None


def test_reconcile_finds_played_game1_after_cutoff(
    db_session: Session, played_game1: dict[str, str]
) -> None:
    """Reconcile находит завершённую game1, начавшуюся после cutoff."""
    module = _load_reconcile()
    freeze = {
        "freeze_id": str(uuid4()),
        "cutoff_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
        "team_a": {"id": played_game1["team_a"]},
        "team_b": {"id": played_game1["team_b"]},
        "p_a": 0.47,
        "p_b": 0.53,
    }
    candidate = module._find_candidate(db_session, freeze)
    assert candidate is not None
    assert candidate["game_id"] == played_game1["game"]
    assert candidate["winner_team_id"] == played_game1["team_a"]


def test_reconcile_reports_pending_when_game_is_absent(
    db_session: Session, played_game1: dict[str, str]
) -> None:
    """Игры после cutoff нет — скрипт честно говорит «pending», а не молчит."""
    module = _load_reconcile()
    freeze = {
        "cutoff_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "team_a": {"id": played_game1["team_a"]},
        "team_b": {"id": played_game1["team_b"]},
    }
    assert module._find_candidate(db_session, freeze) is None
    assert "не появилась" in module._pending_reason(db_session, freeze)


def test_reconcile_refuses_unproven_map_index(
    db_session: Session, game_fixture: dict[str, str]
) -> None:
    """Карта без доказанного map1 не связывается: это не игра 1 серии."""
    module = _load_reconcile()
    _link_teams(db_session, game_fixture)
    db_session.execute(
        text(
            """
            UPDATE game
               SET map_number = NULL,
                   status = 'map_index_unresolved',
                   winner_team_id = CAST(:winner AS uuid),
                   event_time = now()
             WHERE id = CAST(:game_id AS uuid)
            """
        ),
        {"winner": game_fixture["team_a"], "game_id": game_fixture["game"]},
    )
    db_session.flush()

    freeze = {
        "cutoff_at": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
        "team_a": {"id": game_fixture["team_a"]},
        "team_b": {"id": game_fixture["team_b"]},
    }
    assert module._find_candidate(db_session, freeze) is None
    assert "map index не доказан" in module._pending_reason(db_session, freeze)
