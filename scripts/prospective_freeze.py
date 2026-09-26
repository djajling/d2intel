#!/usr/bin/env python
"""PROSPECTIVE — заморозка предсказания на будущую фиксue (вариант C).

Владелец называет две команды каноническими именами. Скрипт строит
prior-form признаки с `cutoff = now` (только то, что реально известно в
момент запуска), применяет текущую модель и сериализует результат в
immutable-файл под `artifacts/prospective/`.

Файл — это провенанс «до матча»: после того как фиксue доиграют и она
появится в БД, `prospective_reconcile.py` связывает заморозку с реальной
игрой и записывает canonical-снимок в режиме `prospective_observed`.

Immutable: файл пишется один раз. Перезапись существующего freeze_id
запрещена — предсказание нельзя подправить задним числом.

Пример:

    python scripts/prospective_freeze.py --team-a "Aurora Gaming" --team-b "Natus Vincere"

Секреты не выводятся. Коды возврата: 0 frozen, 3 unknown team, 4 model
error, 6 already exists, 64 bad args.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

from d2intel.api.predict import (
    _feature_columns,
    _impute,
    _load_model,
    _numeric,
)
from d2intel.db import SessionLocal
from d2intel.features.prior_form import (
    EVENT_ASOF,
    FEATURE_SCHEMA_VERSION,
    LAG_POLICY_VERSION,
    TARGET_PHASE,
    PriorFormParams,
    fetch_participants,
    fetch_prior_games,
    player_form,
    team_form,
)

FREEZE_DIR = Path("artifacts/prospective")
FREEZE_SCHEMA_VERSION = "prospective-freeze.v1"
PROSPECTIVE_MODE = "prospective_observed"
ALGORITHM = "logreg_prior_form"

TEAM_SQL = """
    SELECT id, canonical_name
      FROM team
     WHERE canonical_name = :name
     ORDER BY id
     LIMIT 1
"""

LATEST_MODEL_SQL = """
    SELECT
        mv.id AS id,
        mv.algorithm AS algorithm,
        mv.feature_schema_version AS feature_schema_version,
        mv.artifact_uri AS artifact_uri,
        mv.hyperparameters AS hyperparameters
    FROM model_version AS mv
    WHERE mv.algorithm = :algorithm
    ORDER BY mv.computed_at DESC
    LIMIT 1
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Заморозить prospective-предсказание на будущую фиксue (вариант C)."
    )
    parser.add_argument("--team-a", required=True, help="Каноническое имя Team A.")
    parser.add_argument("--team-b", required=True, help="Каноническое имя Team B.")
    parser.add_argument(
        "--note",
        default="",
        help="Произвольная пометка владельца (фиксue, дата, источник названия).",
    )
    return parser.parse_args(argv)


def _resolve_team(session: Session, name: str) -> tuple[UUID, str]:
    row = session.execute(text(TEAM_SQL), {"name": name}).first()
    if row is None:
        raise SystemExit(3)
    return UUID(str(row.id)), str(row.canonical_name)


def _build_row(
    session: Session,
    team_a: UUID,
    team_b: UUID,
    cutoff: datetime,
    params: PriorFormParams,
) -> dict[str, object]:
    """Признаки для пары команд в момент cutoff — без целевой игры.

    В отличие от ретро-пути здесь нет TargetRow: целевая карта ещё не
    доиграна, поэтому `exclude_game_id` не нужен, а `y` неизвестен и
    остается None до reconcile.
    """
    prior_games = fetch_prior_games(session)
    participants = fetch_participants(session)

    form_a = team_form(
        prior_games,
        team_id=team_a,
        cutoff=cutoff,
        target_patch=None,
        params=params,
        evaluation_mode=EVENT_ASOF,
    )
    form_b = team_form(
        prior_games,
        team_id=team_b,
        cutoff=cutoff,
        target_patch=None,
        params=params,
        evaluation_mode=EVENT_ASOF,
    )
    players_a = player_form(
        participants,
        team_id=team_a,
        cutoff=cutoff,
        params=params,
        evaluation_mode=EVENT_ASOF,
    )
    players_b = player_form(
        participants,
        team_id=team_b,
        cutoff=cutoff,
        params=params,
        evaluation_mode=EVENT_ASOF,
    )

    row: dict[str, object] = {
        "cutoff_at": cutoff,
        "team_a_id": team_a,
        "team_b_id": team_b,
        "target_patch_unknown": True,
        "y": None,
    }
    for side, form in (("a", form_a), ("b", form_b)):
        prefix = f"team_{side}_"
        row[prefix + "n_games"] = form.n_games
        row[prefix + "n_eff"] = form.n_eff if form.avail else float("nan")
        row[prefix + "wr_lifetime"] = form.wr_lifetime if form.avail else float("nan")
        row[prefix + "n_last_long"] = form.n_last_long
        row[prefix + "wr_last_long"] = (
            form.wr_last_long if form.n_last_long > 0 else float("nan")
        )
        row[prefix + "n_last_short"] = form.n_last_short
        row[prefix + "wr_last_short"] = (
            form.wr_last_short if form.n_last_short > 0 else float("nan")
        )
        row[prefix + "days_since_last"] = (
            form.days_since_last if form.days_since_last is not None else float("nan")
        )
        row[prefix + "same_patch_n"] = form.same_patch_n
        row[prefix + "avail"] = form.avail
        row[prefix + "low_coverage"] = form.low_coverage
    for side, form in (("a", players_a), ("b", players_b)):
        prefix = f"player_{side}_"
        row[prefix + "n_known"] = form.n_known_players
        row[prefix + "n_games"] = form.n_games
        row[prefix + "wr"] = form.wr if form.avail else float("nan")
        row[prefix + "kda"] = form.kda if form.avail else float("nan")
        row[prefix + "gpm"] = form.gpm if form.avail else float("nan")
        row[prefix + "xpm"] = form.xpm if form.avail else float("nan")
        row[prefix + "avail"] = form.avail

    for name, left, right in _DIFFERENTIALS:
        row[name] = _diff(row, left, right)
    return row


# A−B дифференциалы; имена и порядок совпадают с `prior_form._put_differentials`,
# чтобы замороженные признаки были сопоставимы с обучающей когортой.
_DIFFERENTIALS = (
    ("d_team_wr_lifetime", "team_a_wr_lifetime", "team_b_wr_lifetime"),
    ("d_team_wr_last_long", "team_a_wr_last_long", "team_b_wr_last_long"),
    ("d_team_wr_last_short", "team_a_wr_last_short", "team_b_wr_last_short"),
    ("d_team_n_eff", "team_a_n_eff", "team_b_n_eff"),
    ("d_team_days_since_last", "team_a_days_since_last", "team_b_days_since_last"),
    ("d_player_wr", "player_a_wr", "player_b_wr"),
    ("d_player_kda", "player_a_kda", "player_b_kda"),
    ("d_player_gpm", "player_a_gpm", "player_b_gpm"),
    ("d_player_xpm", "player_a_xpm", "player_b_xpm"),
)


def _diff(row: dict[str, Any], left: str, right: str) -> float:
    """A − B. None/NaN распространяется — неизвестное не подменяется нулём."""
    left_v: Any = row.get(left)
    right_v: Any = row.get(right)
    if left_v is None or right_v is None:
        return float("nan")
    try:
        left_f = float(left_v)
        right_f = float(right_v)
    except (TypeError, ValueError):
        return float("nan")
    return left_f - right_f


def _latest_model(session: Session) -> dict[str, object]:
    row = session.execute(
        text(LATEST_MODEL_SQL), {"algorithm": ALGORITHM}
    ).first()
    if row is None:
        raise SystemExit(4)
    return {
        "id": str(row.id),
        "algorithm": str(row.algorithm),
        "feature_schema_version": str(row.feature_schema_version),
        "artifact_uri": row.artifact_uri,
        "hyperparameters": dict(row.hyperparameters or {}),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.team_a == args.team_b:
        print("--team-a и --team-b должны различаться", file=sys.stderr)
        return 64

    cutoff = datetime.now(UTC)
    freeze_id = str(uuid4())
    path = FREEZE_DIR / f"{freeze_id}.json"

    session = SessionLocal()
    try:
        team_a_id, team_a_name = _resolve_team(session, args.team_a)
        team_b_id, team_b_name = _resolve_team(session, args.team_b)
        # Канонические координаты когорты: team_a_id < team_b_id.
        if team_a_id > team_b_id:
            team_a_id, team_b_id = team_b_id, team_a_id
            team_a_name, team_b_name = team_b_name, team_a_name
        model = _latest_model(session)
        feature_columns = _feature_columns(model["hyperparameters"])

        params = PriorFormParams()
        row = _build_row(session, team_a_id, team_b_id, cutoff, params)

        loaded = _load_model(model["artifact_uri"])
        x = np.array([[_numeric(row.get(col)) for col in feature_columns]], dtype=float)
        proba = loaded.predict_proba(_impute(x))[0]
        # Канонические координаты уже применены к командам и признакам:
        # индекс 1 — это P(Team A).
        p_a = float(proba[1])
        p_b = float(proba[0])
    finally:
        session.close()

    payload = {
        "freeze_schema_version": FREEZE_SCHEMA_VERSION,
        "freeze_id": freeze_id,
        "frozen_at": datetime.now(UTC).isoformat(),
        "evaluation_mode": PROSPECTIVE_MODE,
        "target_phase": TARGET_PHASE,
        "cutoff_at": cutoff.isoformat(),
        "feature_schema_version": FEATURE_SCHEMA_VERSION,
        "lag_policy_version": LAG_POLICY_VERSION,
        "model": model,
        "feature_columns": feature_columns,
        "team_a": {"id": str(team_a_id), "canonical_name": team_a_name},
        "team_b": {"id": str(team_b_id), "canonical_name": team_b_name},
        "p_a": p_a,
        "p_b": p_b,
        "features": {k: _jsonable(v) for k, v in row.items()},
        "note": args.note,
        "reconciled": False,
    }
    content_hash = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()
    payload["content_hash"] = content_hash

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        print(f"freeze already exists: {path}", file=sys.stderr)
        return 6
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    print(
        f"frozen {freeze_id}\n"
        f"  {team_a_name} vs {team_b_name}\n"
        f"  cutoff {cutoff.isoformat()}\n"
        f"  p_a {p_a:.4f}  p_b {p_b:.4f}\n"
        f"  file {path}"
    )
    return 0


def _jsonable(value: object) -> object:
    """None/NaN → None, UUID → str: jsonb-совместимое представление."""
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float | int | bool):
        if isinstance(value, float) and np.isnan(value):
            return None
        return value
    if value is None:
        return None
    return value


if __name__ == "__main__":
    raise SystemExit(main())
