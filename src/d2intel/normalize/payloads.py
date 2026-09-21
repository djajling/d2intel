"""DATA-001 — разбор сырых payload источника в типизированные записи.

Слой отвечает за одно: превратить JSONB `raw_payload` в структуру, с которой
можно работать. Здесь нет БД и нет решений о качестве данных — только приведение
типов. Нечитаемая запись возвращает `None`, решение «карантин или нет»
принимает вызывающий код (`pipeline.py`).

Отсутствующие значения остаются `None`. Никаких «значений по умолчанию по
смыслу»: неизвестное поле — `None`, а не ноль и не фиктивная дата.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

MIN_PLAUSIBLE_EPOCH = 1_200_000_000  # 2008-01-10: раньше Dota 2 не существовало.


@dataclass(frozen=True)
class ProMatchRecord:
    """Запись `/api/proMatches` (обнаружение матча + контекст серии)."""

    match_id: int
    start_time: datetime | None
    duration_seconds: int | None
    league_id: int | None
    league_name: str | None
    radiant_team_id: int | None
    radiant_team_name: str | None
    dire_team_id: int | None
    dire_team_name: str | None
    series_id: int | None
    series_type: int | None
    radiant_win: bool | None


@dataclass(frozen=True)
class PlayerEntry:
    """Участник карты из `players[]` детального ответа."""

    account_id: int | None
    hero_id: int | None
    player_slot: int | None
    is_radiant: bool | None
    kills: int | None = None
    deaths: int | None = None
    assists: int | None = None
    net_worth: int | None = None
    gold_per_min: int | None = None
    xp_per_min: int | None = None
    last_hits: int | None = None
    denies: int | None = None
    hero_damage: int | None = None


@dataclass(frozen=True)
class MatchDetailRecord:
    """Детальная запись матча: участники и итог карты."""

    match_id: int
    start_time: datetime | None
    duration_seconds: int | None
    radiant_win: bool | None
    players: tuple[PlayerEntry, ...] = field(default=())


@dataclass(frozen=True)
class PatchEntry:
    """Запись справочника патчей `/api/constants/patch`."""

    version_label: str
    effective_from: datetime | None
    provider_id: int | None = None


def parse_pro_match(row: Mapping[str, Any]) -> ProMatchRecord | None:
    """Разобрать одну запись `/api/proMatches`. `None` — запись нечитаема."""
    match_id = _as_int(row.get("match_id"))
    if match_id is None or match_id <= 0:
        return None
    return ProMatchRecord(
        match_id=match_id,
        start_time=_epoch_to_utc(row.get("start_time")),
        duration_seconds=_as_int(row.get("duration")),
        league_id=_as_int(row.get("leagueid")),
        league_name=_as_text(row.get("league_name")),
        radiant_team_id=_as_int(row.get("radiant_team_id")),
        radiant_team_name=_as_text(row.get("radiant_name")),
        dire_team_id=_as_int(row.get("dire_team_id")),
        dire_team_name=_as_text(row.get("dire_name")),
        series_id=_as_int(row.get("series_id")),
        series_type=_as_int(row.get("series_type")),
        radiant_win=_as_bool(row.get("radiant_win")),
    )


def parse_match_detail(payload: Mapping[str, Any]) -> MatchDetailRecord | None:
    """Разобрать `/api/matches/{id}`. `None` — нет `match_id`."""
    match_id = _as_int(payload.get("match_id"))
    if match_id is None or match_id <= 0:
        return None
    raw_players = payload.get("players")
    players: tuple[PlayerEntry, ...] = ()
    if isinstance(raw_players, Sequence) and not isinstance(raw_players, (str, bytes)):
        players = tuple(
            entry
            for entry in (_parse_player(item) for item in raw_players if isinstance(item, Mapping))
            if entry is not None
        )
    return MatchDetailRecord(
        match_id=match_id,
        start_time=_epoch_to_utc(payload.get("start_time")),
        duration_seconds=_as_int(payload.get("duration")),
        radiant_win=_as_bool(payload.get("radiant_win")),
        players=players,
    )


def parse_patch_entry(row: Mapping[str, Any]) -> PatchEntry | None:
    """Разобрать запись справочника патчей. `None` — нет версии."""
    label = _as_text(row.get("name"))
    if label is None:
        return None
    return PatchEntry(
        version_label=label,
        effective_from=_parse_datetime(row.get("date")),
        provider_id=_as_int(row.get("id")),
    )


def _parse_datetime(value: Any) -> datetime | None:
    """Время из epoch-секунд **или** ISO-строки.

    `/constants/patch` отдаёт `date` строкой (`2026-03-24`), а `start_time`
    матчей — epoch. Оба формата реальны, оба разбираются; неизвестный формат
    даёт `None`, а не «полночь» и не текущее время.
    """
    seconds = _as_int(value)
    if seconds is not None:
        if seconds < MIN_PLAUSIBLE_EPOCH:
            return None
        return datetime.fromtimestamp(seconds, tz=UTC)
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = f"{text[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def find_pro_match(payload: Any, match_id: str | int) -> ProMatchRecord | None:
    """Найти запись с данным `match_id` в payload страницы (`pro_matches`).

    Страница хранится целиком (один `content_hash` на страницу), а наблюдения —
    по записям, поэтому привязка идёт по `provider_entity_id` наблюдения.
    """
    if not isinstance(payload, Sequence) or isinstance(payload, (str, bytes)):
        return None
    wanted = str(match_id)
    for item in payload:
        if not isinstance(item, Mapping):
            continue
        if str(item.get("match_id")) != wanted:
            continue
        return parse_pro_match(item)
    return None


def _parse_player(row: Mapping[str, Any]) -> PlayerEntry | None:
    """Разобрать элемент `players[]`. `None` — элемент не является участником."""
    has_any = any(
        key in row for key in ("account_id", "hero_id", "player_slot", "isRadiant", "team_number")
    )
    if not has_any:
        return None
    is_radiant = _as_bool(row.get("isRadiant"))
    if is_radiant is None:
        team_number = _as_int(row.get("team_number"))
        if team_number is not None:
            # team_number: 0 — radiant, 1 — dire (OpenDota).
            is_radiant = team_number == 0
    return PlayerEntry(
        account_id=_as_int(row.get("account_id")),
        hero_id=_as_int(row.get("hero_id")),
        player_slot=_as_int(row.get("player_slot")),
        is_radiant=is_radiant,
        kills=_as_int(row.get("kills")),
        deaths=_as_int(row.get("deaths")),
        assists=_as_int(row.get("assists")),
        net_worth=_as_int(row.get("net_worth")),
        gold_per_min=_as_int(row.get("gold_per_min")),
        xp_per_min=_as_int(row.get("xp_per_min")),
        last_hits=_as_int(row.get("last_hits")),
        denies=_as_int(row.get("denies")),
        hero_damage=_as_int(row.get("hero_damage")),
    )


def _as_int(value: Any) -> int | None:
    """Целое без потери точности. bool не считается числом."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if text.lstrip("-").isdigit():
            return int(text)
    return None


def _as_bool(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        lowered = value.strip().lower()
        if lowered in {"true", "1"}:
            return True
        if lowered in {"false", "0"}:
            return False
    return None


def _as_text(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _epoch_to_utc(value: Any) -> datetime | None:
    """Unix-epoch (секунды) → UTC. Неправдоподобные значения отбрасываются."""
    seconds = _as_int(value)
    if seconds is None or seconds < MIN_PLAUSIBLE_EPOCH:
        return None
    return datetime.fromtimestamp(seconds, tz=UTC)
