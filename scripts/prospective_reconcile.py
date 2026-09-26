#!/usr/bin/env python
"""PROSPECTIVE — связывание замороженного предсказания с доигранной игрой.

Для каждого незамороженного freeze-файла (`prospective_freeze.py`) ищет
завершённую game1 серию между замороженными командами, которая началась
**после** cutoff заморозки, и записывает canonical-снимок в режиме
`prospective_observed`.

Гарантии честности:

* freeze остаётся immutable — скрипт не перезаписывает его прогноз;
* запись canonical-снимка возможна только если игра доиграна
  (`winner_team_id IS NOT NULL`);
* cutoff в снимке — момент заморозки, а не event_time: именно тогда было
  сделано предсказание;
* метка `y` берётся из фактического исхода и кладётся в
  `prediction_evaluation` — обучение на prospective-данных запрещено
  (`OBSERVED_MODE_ONLY_STUDY`), это только оценка.

Пример:

    python scripts/prospective_reconcile.py --all

    python scripts/prospective_reconcile.py --freeze-id <uuid>

Коды возврата: 0 reconciled (или нечего связывать), 3 freeze не найден,
4 нет подходящей игры, 5 уже связано, 64 bad args.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from d2intel.api.snapshots import PROSPECTIVE_MODE, write_prediction_snapshot
from d2intel.db import SessionLocal
from d2intel.models.repository import record_evaluation

FREEZE_DIR = Path("artifacts/prospective")

CANDIDATE_SQL = """
    SELECT
        g.id AS game_id,
        g.series_id AS series_id,
        g.event_time AS event_time,
        g.winner_team_id AS winner_team_id,
        gta.team_id AS slot0_team_id,
        gtb.team_id AS slot1_team_id
    FROM game AS g
    JOIN game_team AS gta ON gta.game_id = g.id AND gta.slot = 0
    JOIN game_team AS gtb ON gtb.game_id = g.id AND gtb.slot = 1
    WHERE g.map_number = 1
      AND g.status = 'completed'
      AND g.winner_team_id IS NOT NULL
      AND g.event_time IS NOT NULL
      AND gta.team_id IN (CAST(:team_a AS uuid), CAST(:team_b AS uuid))
      AND gtb.team_id IN (CAST(:team_a AS uuid), CAST(:team_b AS uuid))
      AND gta.team_id <> gtb.team_id
      AND g.event_time > CAST(:cutoff AS timestamptz)
    ORDER BY g.event_time
"""

#: Диагностика: игра после cutoff есть, но map index не доказан.
PENDING_SQL = """
    SELECT g.status, g.map_number, g.event_time
      FROM game AS g
      JOIN game_team AS gta ON gta.game_id = g.id AND gta.slot = 0
      JOIN game_team AS gtb ON gtb.game_id = g.id AND gtb.slot = 1
     WHERE gta.team_id IN (CAST(:team_a AS uuid), CAST(:team_b AS uuid))
       AND gtb.team_id IN (CAST(:team_a AS uuid), CAST(:team_b AS uuid))
       AND gta.team_id <> gtb.team_id
       AND g.event_time > CAST(:cutoff AS timestamptz)
     ORDER BY g.event_time
     LIMIT 1
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Связать prospective-заморозки с доигранными играми."
    )
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Обработать все незамороженные freeze-файлы.")
    group.add_argument("--freeze-id", help="Конкретный freeze_id.")
    return parser.parse_args(argv)


def _load_freeze(path: Path) -> dict[str, Any]:
    with path.open(encoding="utf-8") as handle:
        return json.load(handle)


def _find_candidate(session: Session, freeze: dict[str, Any]) -> dict[str, Any] | None:
    team_a = freeze["team_a"]
    team_b = freeze["team_b"]
    cutoff = datetime.fromisoformat(str(freeze["cutoff_at"]))
    rows = session.execute(
        text(CANDIDATE_SQL),
        {
            "team_a": team_a["id"],
            "team_b": team_b["id"],
            "cutoff": cutoff,
        },
    ).all()
    if not rows:
        return None
    row = rows[0]
    return {
        "game_id": str(row.game_id),
        "series_id": str(row.series_id) if row.series_id else None,
        "event_time": row.event_time,
        "winner_team_id": str(row.winner_team_id),
        "slot0_team_id": str(row.slot0_team_id),
        "slot1_team_id": str(row.slot1_team_id),
    }


def _pending_reason(session: Session, freeze: dict[str, Any]) -> str:
    """Почему связать нельзя: игры нет вовсе или map index не доказан."""
    row = session.execute(
        text(PENDING_SQL),
        {
            "team_a": freeze["team_a"]["id"],
            "team_b": freeze["team_b"]["id"],
            "cutoff": datetime.fromisoformat(str(freeze["cutoff_at"])),
        },
    ).first()
    if row is None:
        return "игра после cutoff пока не появилась в источнике"
    if row.map_number is None:
        return (
            f"игра от {row.event_time} есть, но map index не доказан "
            f"(status={row.status}) — ждём полную серию"
        )
    return f"игра от {row.event_time} найдена, но не проходит фильтр map1"


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    paths: list[Path] = []
    if args.all:
        paths = sorted(FREEZE_DIR.glob("*.json"))
    else:
        path = FREEZE_DIR / f"{args.freeze_id}.json"
        if not path.exists():
            print(f"freeze not found: {path}", file=sys.stderr)
            return 3
        paths = [path]

    if not paths:
        print("no freeze files to reconcile")
        return 0

    reconciled = 0
    for path in paths:
        freeze = _load_freeze(path)
        if freeze.get("reconciled"):
            print(f"skip {path.name}: already reconciled")
            continue

        session = SessionLocal()
        try:
            candidate = _find_candidate(session, freeze)
            if candidate is None:
                reason = _pending_reason(session, freeze)
                print(f"pending {path.name}: {reason}")
                continue
            result = _write_canonical(session, freeze, candidate)
        finally:
            session.close()

        freeze["reconciled"] = True
        freeze["reconciled_with"] = {
            "game_id": candidate["game_id"],
            "series_id": candidate["series_id"],
            "event_time": candidate["event_time"].isoformat(),
            "snapshot_id": result["snapshot_id"],
        }
        with path.open("w", encoding="utf-8") as handle:
            json.dump(freeze, handle, ensure_ascii=False, indent=2)
            handle.write("\n")

        print(
            f"reconciled {path.name}\n"
            f"  game {candidate['game_id']} ({candidate['event_time'].isoformat()})\n"
            f"  snapshot {result['snapshot_id']}  y={result['y']}  "
            f"log_loss={result['log_loss']:.4f}  brier={result['brier']:.4f}"
        )
        reconciled += 1

    if reconciled == 0:
        print("nothing to reconcile yet")
    return 0


def _write_canonical(
    session: Session, freeze: dict[str, Any], candidate: dict[str, Any]
) -> dict[str, Any]:
    """Записать canonical-снимок prospective_observed + оценку по исходу."""
    team_a_id = UUID(str(freeze["team_a"]["id"]))
    team_b_id = UUID(str(freeze["team_b"]["id"]))
    cutoff = datetime.fromisoformat(str(freeze["cutoff_at"]))

    # Канонический исход в координатах Team A: выиграла ли команда A.
    winner = UUID(candidate["winner_team_id"])
    y = 1 if winner == team_a_id else 0

    p_a = float(freeze["p_a"])
    p_b = float(freeze["p_b"])
    # log_loss/brier по фактическому исходу; p — с замершей заморозки.
    p_true = max(p_a, 1e-12) if y == 1 else max(p_b, 1e-12)
    log_loss = -math.log(p_true)
    brier = (p_a - y) ** 2

    feature_row = dict(freeze["features"])
    model = dict(freeze["model"])
    model["lag_policy_version"] = freeze["lag_policy_version"]

    result = write_prediction_snapshot(
        session,
        game_id=UUID(candidate["game_id"]),
        team_a_id=team_a_id,
        team_b_id=team_b_id,
        model_version=model,
        cutoff_at=cutoff,
        p_a=p_a,
        evaluation_mode=PROSPECTIVE_MODE,
        feature_row=feature_row,
        feature_columns=list(freeze["feature_columns"]),
        assumed_available_at=None,
        event_time=candidate["event_time"],
    )

    record_evaluation(
        session,
        snapshot_id=UUID(result["snapshot_id"]),
        y=bool(y),
        log_loss=log_loss,
        brier=brier,
    )
    session.commit()
    return {
        "snapshot_id": result["snapshot_id"],
        "y": y,
        "log_loss": log_loss,
        "brier": brier,
    }


if __name__ == "__main__":
    raise SystemExit(main())
