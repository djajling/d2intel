"""Когорта для target «первая карта серии» (game1).

## Как фиксируется Team A

Target — `P(Team A выигрывает карту 1 | карта сыграна)`. **Team A определяется
канонической идентичностью, а не стороной Radiant/Dire**: из двух участников
карты Team A — тот, чей canonical `team_id` меньше (`team_a_id < team_b_id`).
Правило детерминировано, не зависит от стороны и от порядка в ответе источника.

Метка: `label = 1`, если победитель — Team A, иначе `0`.

## Кого включаем

- `map_number = 1` — первая карта серии;
- обе команды известны и различны;
- победитель известен;
- `result_type = 'played'` — технические результаты (forfeit/walkover/void)
  в обучение не идут, это отдельные статусы, а не «победы».

Сознательно не сделано: детект remake (в DATA-001 не реализован) — такие карты
пока попадают в когорту и должны быть отдельной задачей.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from d2intel.evaluation.metrics import majority_class_accuracy

COHORT_SQL = """
    SELECT g.id            AS game_id,
           g.series_id     AS series_id,
           g.event_time    AS event_time,
           gt_a.team_id    AS team_a_id,
           gt_b.team_id    AS team_b_id,
           g.winner_team_id AS winner_team_id
      FROM game g
      JOIN game_team gt_a ON gt_a.game_id = g.id
      JOIN game_team gt_b ON gt_b.game_id = g.id
     WHERE g.map_number = 1
       AND g.series_id IS NOT NULL
       AND g.result_type = 'played'
       AND g.winner_team_id IS NOT NULL
       AND gt_a.team_id < gt_b.team_id
       AND (CAST(:since AS timestamptz) IS NULL OR g.event_time >= CAST(:since AS timestamptz))
       AND (CAST(:until AS timestamptz) IS NULL OR g.event_time <  CAST(:until AS timestamptz))
     ORDER BY g.event_time, g.id
"""


@dataclass(frozen=True)
class Game1Row:
    """Одно наблюдение когорты: первая карта серии с известным исходом."""

    game_id: UUID
    series_id: UUID
    event_time: datetime
    team_a_id: UUID
    team_b_id: UUID
    winner_team_id: UUID

    @property
    def label(self) -> int:
        """1 — выиграла Team A, 0 — Team B."""
        return 1 if self.winner_team_id == self.team_a_id else 0

    @property
    def group(self) -> str:
        """Группа для grouped bootstrap — серия."""
        return str(self.series_id)


def select_game1_cohort(
    session: Session, *, since: datetime | None = None, until: datetime | None = None
) -> list[Game1Row]:
    """Прочитать когорту game1 из canonical-слоя. Порядок — по времени."""
    rows = session.execute(text(COHORT_SQL), {"since": since, "until": until}).all()
    return [
        Game1Row(
            game_id=UUID(str(row.game_id)),
            series_id=UUID(str(row.series_id)),
            event_time=row.event_time,
            team_a_id=UUID(str(row.team_a_id)),
            team_b_id=UUID(str(row.team_b_id)),
            winner_team_id=UUID(str(row.winner_team_id)),
        )
        for row in rows
    ]


def cohort_report(rows: list[Game1Row]) -> dict[str, Any]:
    """Сводка по когорте без выдуманных метрик качества модели."""
    if not rows:
        return {
            "n": 0,
            "date_from": None,
            "date_to": None,
            "series": 0,
            "teams": 0,
            "label_balance": None,
            "majority_class_accuracy": None,
        }
    labels = [row.label for row in rows]
    teams = {row.team_a_id for row in rows} | {row.team_b_id for row in rows}
    return {
        "n": len(rows),
        "date_from": rows[0].event_time.isoformat(),
        "date_to": rows[-1].event_time.isoformat(),
        "series": len({row.series_id for row in rows}),
        "teams": len(teams),
        "label_balance": sum(labels) / len(labels),
        "majority_class_accuracy": majority_class_accuracy(labels),
    }
