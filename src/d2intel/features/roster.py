"""TEAM-002 — prior-known roster признаки с явной неопределённостью.

Источник — `roster_membership` (DATA-001): свидетельства «кто играл за
команду» из завершённых матчей. Фактический состав матча-цели из признаков
исключён явно (`exclude_game_id`): разрешён только prior known roster
(`G-ROSTER`, карточка TEAM-002 AC #5).

Признаки на команду, as-of cutoff:

- `days_since_last` — давность последнего ростерного свидетельства (дней);
- `changes_30d` — число игроков с первым появлением за команду в окне 30 дней
  («приток новых»);
- `standin_share_30d` — доля свидетельств в окне 30 дней с `is_standin = true`;
  малая выборка (< `min_window`) даёт `None` + `avail = False` — неизвестное
  не подменяется нулём (`FEATURES.md` §1).

Fallback при отсутствии данных: все значения `None`, маска `avail = False`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

_ROSTER_COLUMNS_SQL = """
    SELECT
        rm.team_id AS team_id,
        rm.player_id AS player_id,
        rm.game_id AS game_id,
        rm.is_standin AS is_standin,
        rm.event_time AS event_time,
        rm.available_at AS available_at
    FROM roster_membership AS rm
"""

_SECONDS_PER_DAY = 86400.0


@dataclass(frozen=True)
class RosterMembershipRow:
    """Минимальное ростерное свидетельство для признаков."""

    team_id: UUID
    player_id: UUID
    game_id: UUID
    is_standin: bool | None
    event_time: datetime
    available_at: datetime


@dataclass(frozen=True)
class RosterForm:
    """Prior-known roster as-of cutoff. `None` — данных нет (маска `False`)."""

    n_memberships: int
    days_since_last: float | None
    changes_30d: int | None
    standin_share_30d: float | None
    avail: bool


def fetch_roster_memberships(session) -> list[RosterMembershipRow]:
    """Bulk-извлечение всех ростерных свидетельств (фильтр as-of — в памяти)."""
    from sqlalchemy import text

    rows = session.execute(text(_ROSTER_COLUMNS_SQL))
    return [
        RosterMembershipRow(
            team_id=row.team_id,
            player_id=row.player_id,
            game_id=row.game_id,
            is_standin=row.is_standin,
            event_time=row.event_time,
            available_at=row.available_at,
        )
        for row in rows
    ]


def _is_eligible(
    row: RosterMembershipRow,
    *,
    cutoff: datetime,
    result_lag: timedelta,
    exclude_game_id: UUID | None,
) -> bool:
    """Свидетельство известно к cutoff: событие до cutoff и доступно (lag policy).

    Ростер целевой карты исключён явно: это фактический состав матча-цели,
    запрещённый для pre-match признаков (TEAM-002 AC #5).
    """
    if exclude_game_id is not None and row.game_id == exclude_game_id:
        return False
    if row.event_time is None or row.event_time >= cutoff:
        return False
    return (row.event_time + result_lag) <= cutoff


def roster_form(
    memberships: Sequence[RosterMembershipRow],
    *,
    team_id: UUID,
    cutoff: datetime,
    result_lag: timedelta,
    exclude_game_id: UUID | None = None,
    window_days: int = 30,
    min_window: int = 3,
) -> RosterForm:
    """Prior-known roster признаки одной команды, as-of cutoff.

    `min_window` — минимальное число свидетельств в окне для расчёта
    `standin_share_30d` (меньше — `None`, данных недостаточно).
    """
    team_rows = [
        row
        for row in memberships
        if row.team_id == team_id
        and _is_eligible(
            row, cutoff=cutoff, result_lag=result_lag, exclude_game_id=exclude_game_id
        )
    ]
    if not team_rows:
        return RosterForm(
            n_memberships=0,
            days_since_last=None,
            changes_30d=None,
            standin_share_30d=None,
            avail=False,
        )

    latest = max(row.event_time for row in team_rows)
    days_since_last = (cutoff - latest).total_seconds() / _SECONDS_PER_DAY

    window_start = cutoff - timedelta(days=window_days)
    window_rows = [row for row in team_rows if row.event_time >= window_start]

    first_seen: dict[UUID, datetime] = {}
    for row in team_rows:
        known = first_seen.get(row.player_id)
        if known is None or row.event_time < known:
            first_seen[row.player_id] = row.event_time
    changes_30d = sum(1 for first in first_seen.values() if first >= window_start)

    standin_share: float | None = None
    if len(window_rows) >= min_window:
        standin_flags = [bool(row.is_standin) for row in window_rows]
        standin_share = sum(standin_flags) / len(standin_flags)

    return RosterForm(
        n_memberships=len(team_rows),
        days_since_last=days_since_last,
        changes_30d=changes_30d,
        standin_share_30d=standin_share,
        avail=True,
    )
