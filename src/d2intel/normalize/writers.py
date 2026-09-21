"""DATA-001 — идемпотентная запись canonical-строк.

Все вставки идут с **детерминированным PK** и гасятся `ON CONFLICT`: повторный
прогон нормализации не создаёт дублей и не перезаписывает уже записанное
(требование «нет перезаписи ростеров»).

Единственное допускаемое изменение существующей строки — **дозаполнение**
`game.map_number`/`game.status`/`game.patch_id`: `NULL → значение`, один раз.
Без этого серия, полученная неполной, навсегда осталась бы без номера карты
после того, как недостающие игры приехали. Любое уже установленное значение
не меняется.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

from d2intel.normalize import identity
from d2intel.normalize.policy import (
    ENTITY_MAPPING_VERSION,
    PERFORMANCE_METRIC_SCHEMA_VERSION,
    ROSTER_POLICY_VERSION,
)
from d2intel.normalize.temporal import Envelope

#: Дозаполнение номера карты: только NULL → значение, никогда наоборот.
_GAME_CONFLICT = (
    "(id) DO UPDATE SET map_number = EXCLUDED.map_number, "
    "status = EXCLUDED.status, "
    "patch_id = COALESCE(game.patch_id, EXCLUDED.patch_id) "
    "WHERE game.map_number IS NULL AND EXCLUDED.map_number IS NOT NULL"
)


def insert_row(
    session: Session,
    *,
    table: str,
    values: Mapping[str, Any],
    conflict: str = "DO NOTHING",
) -> bool:
    """Вставить строку. `True` — строка создана (или дозаполнена), `False` — была.

    Значения-словари/списки автоматически уходят в JSONB: `evidence` и другие
    переменные payload не должны сериализоваться вызывающим кодом вручную.
    """
    params: dict[str, Any] = {}
    columns: list[str] = []
    placeholders: list[str] = []
    for name, value in values.items():
        columns.append(name)
        if isinstance(value, (dict, list)):
            placeholders.append(f"CAST(:{name} AS jsonb)")
            params[name] = json.dumps(value)
        else:
            placeholders.append(f":{name}")
            params[name] = value
    statement = (
        f"INSERT INTO {table} ({', '.join(columns)}) "
        f"VALUES ({', '.join(placeholders)}) "
        f"ON CONFLICT {conflict} RETURNING id"
    )
    return session.execute(text(statement), params).scalar() is not None


# --- справочники и идентичность ---------------------------------------------


def ensure_tournament(
    session: Session,
    *,
    source_id: str,
    league_id: int,
    league_name: str | None,
    observation_id: str,
    envelope: Envelope,
) -> tuple[UUID, bool]:
    """Создать турнир по `leagueid`. Возвращает `(id, строка_новая)`."""
    tournament_uuid = identity.tournament_id(league_id, source_id=source_id)
    inserted = insert_row(
        session,
        table="tournament",
        values={
            "id": tournament_uuid,
            "name": league_name,
            "organizer_source": source_id,
            "source_observation_id": observation_id,
            **envelope.as_dict(),
        },
    )
    _ensure_mapping(
        session,
        source_id=source_id,
        entity_type="tournament",
        external_id=str(league_id),
        tournament_id=tournament_uuid,
        observation_id=observation_id,
        envelope=envelope,
    )
    return tournament_uuid, inserted


def ensure_team(
    session: Session,
    *,
    source_id: str,
    external_id: int,
    name: str | None,
    observation_id: str,
    envelope: Envelope,
) -> tuple[UUID, bool]:
    """Создать команду по `team_id` источника. Возвращает `(id, строка_новая)`.

    Имя может отсутствовать: тогда `identity_status = 'unresolved'` — схема это
    требует (`team_name_or_unresolved`), синтетическая подпись не подставляется.
    """
    team_uuid = identity.team_id(external_id, source_id=source_id)
    inserted = insert_row(
        session,
        table="team",
        values={
            "id": team_uuid,
            "canonical_name": name,
            "identity_status": "resolved" if name else "unresolved",
            "source_observation_id": observation_id,
            **envelope.as_dict(),
        },
    )
    _ensure_mapping(
        session,
        source_id=source_id,
        entity_type="team",
        external_id=str(external_id),
        team_id=team_uuid,
        observation_id=observation_id,
        envelope=envelope,
    )
    return team_uuid, inserted


def ensure_player(
    session: Session,
    *,
    source_id: str,
    account_id: int,
    observation_id: str,
    envelope: Envelope,
) -> tuple[UUID, bool]:
    """Создать игрока по `account_id`. Возвращает `(id, строка_новая)`.

    Имя намеренно не выдумывается: `identity_status = 'unresolved'`,
    `canonical_name = NULL`. Отображение прозвищ — отдельная задача.
    """
    player_uuid = identity.player_id(account_id, source_id=source_id)
    inserted = insert_row(
        session,
        table="player",
        values={
            "id": player_uuid,
            "account_id": account_id,
            "canonical_name": None,
            "identity_status": "unresolved",
            "source_observation_id": observation_id,
            **envelope.as_dict(),
        },
    )
    _ensure_mapping(
        session,
        source_id=source_id,
        entity_type="player",
        external_id=str(account_id),
        player_id=player_uuid,
        observation_id=observation_id,
        envelope=envelope,
    )
    return player_uuid, inserted


def insert_patch(
    session: Session,
    *,
    source_id: str,
    version_label: str,
    patch_type: str | None,
    effective_from: datetime | None,
    effective_to: datetime | None,
    observation_id: str,
    envelope: Envelope,
) -> bool:
    """Строка справочника патчей. Границы интервала — по соседним патчам."""
    return insert_row(
        session,
        table="patch",
        values={
            "id": identity.patch_id(version_label, source_id=source_id),
            "version_label": version_label,
            "patch_type": patch_type,
            "effective_from": effective_from,
            "effective_to": effective_to,
            "announced_at": None,
            "evidence": {"source": source_id, "policy": "constants/patch"},
            "source_observation_id": observation_id,
            **envelope.as_dict(),
        },
    )


# --- серии и карты -----------------------------------------------------------


def insert_series(
    session: Session,
    *,
    source_id: str,
    series_key: str,
    tournament_id: UUID | None,
    best_of: int | None,
    status: str,
    event_time: datetime | None,
    observation_id: str,
    envelope: Envelope,
) -> tuple[UUID, bool]:
    """Строка серии. Возвращает `(id, строка_новая)`.

    Счёт серии не заполняется: источник его не даёт (поле оставлено для
    результата, полученного из сыгранных карт отдельной задачей).
    """
    series_uuid = identity.series_id(series_key, source_id=source_id)
    inserted = insert_row(
        session,
        table="series",
        values={
            "id": series_uuid,
            "series_key": series_key,
            "tournament_id": tournament_id,
            "best_of": best_of,
            "status": status,
            "source_observation_id": observation_id,
            "event_time": event_time,
            **_without_event_time(envelope),
        },
    )
    return series_uuid, inserted


def insert_game(
    session: Session,
    *,
    source_id: str,
    match_id: int,
    series_id: UUID,
    map_number: int | None,
    status: str,
    winner_team_id: UUID | None,
    result_type: str,
    patch_id: UUID | None,
    observation_id: str,
    envelope: Envelope,
) -> bool:
    """Строка карты. `map_number` допускается только к дозаполнению."""
    return insert_row(
        session,
        table="game",
        values={
            "id": identity.game_id(match_id, source_id=source_id),
            "series_id": series_id,
            "provider_match_id": str(match_id),
            "map_number": map_number,
            "attempt_number": 1,
            "status": status,
            "winner_team_id": winner_team_id,
            "result_type": result_type,
            "patch_id": patch_id,
            "source_observation_id": observation_id,
            **envelope.as_dict(),
        },
        conflict=_GAME_CONFLICT,
    )


def insert_game_team(
    session: Session,
    *,
    game_id: UUID,
    team_id: UUID,
    side: str,
    slot: int,
    observation_id: str,
    envelope: Envelope,
) -> bool:
    """Связь «команда — карта» со стороной. Слот уникален внутри карты."""
    return insert_row(
        session,
        table="game_team",
        values={
            "id": identity.game_team_id(game_id, slot),
            "game_id": game_id,
            "team_id": team_id,
            "side": side,
            "slot": slot,
            "source_observation_id": observation_id,
            **envelope.as_dict(),
        },
    )


# --- участники, статистика, свидетельства состава ----------------------------


def insert_participant(
    session: Session,
    *,
    game_id: UUID,
    player_id: UUID,
    team_id: UUID | None,
    hero_id: int | None,
    slot: int,
    observation_id: str,
    envelope: Envelope,
) -> tuple[UUID, bool]:
    """Участник карты. Возвращает `(id, строка_новая)`."""
    participant_uuid = identity.participant_id(game_id, player_id)
    inserted = insert_row(
        session,
        table="game_participant",
        values={
            "id": participant_uuid,
            "game_id": game_id,
            "player_id": player_id,
            "team_id": team_id,
            "hero_id": hero_id,
            "slot": slot,
            "roster_evidence": {
                "policy": ROSTER_POLICY_VERSION,
                "observed_in_game": True,
                "observation_id": observation_id,
            },
            "source_observation_id": observation_id,
            **envelope.as_dict(),
        },
    )
    return participant_uuid, inserted


def insert_performance(
    session: Session,
    *,
    participant_id: UUID,
    observation_id: str,
    envelope: Envelope,
    kills: int | None,
    deaths: int | None,
    assists: int | None,
    net_worth: int | None,
    gold_per_min: int | None,
    xp_per_min: int | None,
    last_hits: int | None,
    denies: int | None,
    hero_damage: int | None,
    duration_seconds: int | None,
) -> bool:
    """Финальная статистика карты. Отдельная таблица, `data_class = 'final'`.

    Pre-match слой читает `game_participant`, не эту таблицу.
    """
    return insert_row(
        session,
        table="player_performance",
        values={
            "id": identity.performance_id(participant_id),
            "game_participant_id": participant_id,
            "metric_schema_version": PERFORMANCE_METRIC_SCHEMA_VERSION,
            "data_class": "final",
            "kills": kills,
            "deaths": deaths,
            "assists": assists,
            "net_worth": net_worth,
            "gold_per_min": gold_per_min,
            "xp_per_min": xp_per_min,
            "last_hits": last_hits,
            "denies": denies,
            "hero_damage": hero_damage,
            "duration_seconds": duration_seconds,
            "source_observation_id": observation_id,
            **envelope.as_dict(),
        },
    )


def insert_roster_membership(
    session: Session,
    *,
    team_id: UUID,
    player_id: UUID,
    game_id: UUID,
    valid_from: datetime | None,
    valid_to: datetime | None,
    observation_id: str,
    envelope: Envelope,
) -> bool:
    """Свидетельство состава: игрок наблюдался в команде **в этой карте**.

    Интервал = [начало карты, конец карты). Никакой «текущий состав»: строка
    не обновляется, объединение в подтверждённые интервалы состава требует
    источника заявленных составов и здесь не делается.
    """
    if valid_from is None:
        return False
    return insert_row(
        session,
        table="roster_membership",
        values={
            "id": identity.roster_membership_id(team_id, player_id, game_id),
            "team_id": team_id,
            "player_id": player_id,
            "game_id": game_id,
            "membership_type": "actual_observed",
            "role": None,
            "is_standin": None,
            "valid_from": valid_from,
            "valid_to": valid_to,
            "evidence": {
                "policy": ROSTER_POLICY_VERSION,
                "game_id": str(game_id),
                "observation_id": observation_id,
            },
            "source_observation_id": observation_id,
            **envelope.as_dict(),
        },
    )


# --- внутреннее --------------------------------------------------------------


def _ensure_mapping(
    session: Session,
    *,
    source_id: str,
    entity_type: str,
    external_id: str,
    observation_id: str,
    envelope: Envelope,
    team_id: UUID | None = None,
    player_id: UUID | None = None,
    tournament_id: UUID | None = None,
) -> bool:
    """`provider → canonical` для identity-сущностей (typed FK + XOR)."""
    return insert_row(
        session,
        table="entity_mapping",
        values={
            "source_id": source_id,
            "entity_type": entity_type,
            "external_id": external_id,
            "team_id": team_id,
            "player_id": player_id,
            "tournament_id": tournament_id,
            "mapping_version": ENTITY_MAPPING_VERSION,
            "status": "active",
            "source_observation_id": observation_id,
            **envelope.as_dict(),
        },
    )


def _without_event_time(envelope: Envelope) -> dict[str, datetime | None]:
    """Поля конверта без `event_time` (передаётся отдельным аргументом)."""
    values = envelope.as_dict()
    values.pop("event_time", None)
    return values
