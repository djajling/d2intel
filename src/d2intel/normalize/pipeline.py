"""DATA-001 — оркестрация нормализации исторического ядра.

Порядок этапов задан зависимостями данных:

1. **патчи** (`patch_constants`) — справочник для `game.patch_id`;
2. **`pro_matches`** — контекст серии: турнир, команды, серия, карта, номер
   карты. Здесь решается судьба map1 (карантин при неоднозначности);
3. **`match_detail`** — участники карты, финальная статистика, свидетельства
   состава. Требует уже существующей строки `game`: без контекста серии номер
   карты не определён, а значит игра не может попасть в датасет.

Идемпотентность обеспечивается детерминированными PK и `ON CONFLICT`: повторный
прогон не создаёт строк и не меняет записанное (кроме дозаполнения
`map_number`, см. `writers._GAME_CONFLICT`).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import Row, text
from sqlalchemy.orm import Session

from d2intel.ingestion.contracts import OPENDOTA_SOURCE_ID, utc_now
from d2intel.normalize import identity, writers
from d2intel.normalize.map_index import GamePlan, SeriesPlan, plan_all
from d2intel.normalize.payloads import (
    MatchDetailRecord,
    ProMatchRecord,
    find_pro_match,
    parse_match_detail,
    parse_patch_entry,
)
from d2intel.normalize.policy import JobKind, QuarantineReason
from d2intel.normalize.quarantine import QuarantineItem, record_quarantine, resolve_quarantine
from d2intel.normalize.temporal import build_envelope

#: Метка патча с буквенным суффиксом («7.41b») — hotfix.
_HOTFIX_SUFFIX = re.compile(r"[A-Za-z]$")

#: Нижняя граница времени для сортировки патчей без известной даты.
_MIN_TIME = datetime.min.replace(tzinfo=UTC)


@dataclass
class NormalizationStats:
    """Счётчики прогона.

    `created_*` — строки, реально записанные прогоном. Для `created_games`
    сюда же попадает дозаполнение `map_number` (NULL → значение): это тоже
    новая информация, а не дубль.
    """

    created_patches: int = 0
    created_tournaments: int = 0
    created_teams: int = 0
    created_players: int = 0
    created_series: int = 0
    created_games: int = 0
    created_game_teams: int = 0
    created_participants: int = 0
    created_performances: int = 0
    created_roster_memberships: int = 0
    quarantined: dict[str, int] = field(default_factory=dict)

    def bump_quarantine(self, reason: str) -> None:
        """Учесть строку карантина."""
        self.quarantined[reason] = self.quarantined.get(reason, 0) + 1

    def as_dict(self) -> dict[str, Any]:
        """Представление для отчёта/CLI."""
        return {
            "created_patches": self.created_patches,
            "created_tournaments": self.created_tournaments,
            "created_teams": self.created_teams,
            "created_players": self.created_players,
            "created_series": self.created_series,
            "created_games": self.created_games,
            "created_game_teams": self.created_game_teams,
            "created_participants": self.created_participants,
            "created_performances": self.created_performances,
            "created_roster_memberships": self.created_roster_memberships,
            "quarantined": dict(sorted(self.quarantined.items())),
        }


def normalize_once(
    session: Session,
    *,
    source_id: str = OPENDOTA_SOURCE_ID,
    clock: Callable[[], datetime] = utc_now,
) -> NormalizationStats:
    """Один прогон нормализации. Повторный прогон — не создаёт дублей."""
    stats = NormalizationStats()
    source_uuid = _find_source(session, source_id)
    if source_uuid is None:
        return stats
    ingested_at = clock()
    _normalize_patches(session, stats, source_uuid=source_uuid, ingested_at=ingested_at)
    _normalize_pro_matches(session, stats, source_uuid=source_uuid, ingested_at=ingested_at)
    _normalize_match_details(session, stats, source_uuid=source_uuid, ingested_at=ingested_at)
    session.commit()
    return stats


# --- этап 1: патчи ----------------------------------------------------------


def _normalize_patches(
    session: Session, stats: NormalizationStats, *, source_uuid: str, ingested_at: datetime
) -> None:
    """Справочник патчей. Граница патча — начало следующего."""
    rows = _fetch_observations(session, "patch_constants")
    entries: list[tuple[Any, str, datetime]] = []
    seen: set[str] = set()
    for row in rows:
        payload = _as_sequence(_decode_json(row.payload_json))
        if payload is None:
            continue
        for item in payload:
            if not isinstance(item, Mapping):
                continue
            entry = parse_patch_entry(item)
            if entry is None or entry.version_label in seen:
                continue
            seen.add(entry.version_label)
            entries.append((entry, str(row.observation_id), row.observed_at))
    if not entries:
        return

    entries.sort(key=lambda item: (item[0].effective_from or _MIN_TIME, item[0].version_label))
    for index, (entry, observation_id, observed_at) in enumerate(entries):
        next_entry = entries[index + 1][0] if index + 1 < len(entries) else None
        effective_to = next_entry.effective_from if next_entry is not None else None
        envelope = build_envelope(
            observed_at=observed_at,
            ingested_at=ingested_at,
            event_time=entry.effective_from,
        )
        if writers.insert_patch(
            session,
            source_id=source_uuid,
            version_label=entry.version_label,
            patch_type=_classify_patch(entry.version_label),
            effective_from=entry.effective_from,
            effective_to=effective_to,
            observation_id=observation_id,
            envelope=envelope,
        ):
            stats.created_patches += 1
    session.commit()


def _classify_patch(version_label: str) -> str | None:
    """Тип патча по метке версии: `7.0` — major, `7.41` — minor, `7.41b` — hotfix.

    Правило детерминированное и обратимое: тип выводится из самой метки, а не
    из внешнего справочника. Неизвестный формат → `None`, а не угаданное.
    """
    if _HOTFIX_SUFFIX.search(version_label):
        return "hotfix"
    parts = version_label.split(".")
    if len(parts) < 2 or not parts[1].isdigit():
        return None
    return "major" if parts[1] == "0" else "minor"


# --- этап 2: pro_matches (серии, карты, map index) ---------------------------


def _normalize_pro_matches(
    session: Session, stats: NormalizationStats, *, source_uuid: str, ingested_at: datetime
) -> None:
    """Серии и карты. Судьба map1 решается здесь (см. `map_index.plan_series`)."""
    rows = _fetch_observations(session, "pro_matches")
    cache: dict[str, Any] = {}
    records: list[ProMatchRecord] = []
    context: dict[int, tuple[str, datetime, dict[str, Any]]] = {}

    for row in rows:
        raw_id = str(row.raw_id)
        if raw_id not in cache:
            cache[raw_id] = _decode_json(row.payload_json)
        record = find_pro_match(cache[raw_id], row.provider_entity_id)
        if record is None:
            _quarantine(
                session,
                stats,
                source_uuid=source_uuid,
                job_kind=JobKind.MAP_INDEX,
                provider_entity_id=str(row.provider_entity_id),
                reason=QuarantineReason.UNPARSEABLE_RECORD,
                observation_id=str(row.observation_id),
                ingested_at=ingested_at,
                observed_at=row.observed_at,
                payload={"provider_entity_id": row.provider_entity_id},
            )
            continue
        if record.match_id in context:
            # overlap-страницы повторно наблюдают тот же матч: повторное
            # наблюдение не создаёт второй карты и не подменяет provenance.
            continue
        records.append(record)
        context[record.match_id] = (str(row.observation_id), row.observed_at, dict(record.__dict__))

    if not records:
        return

    for plan in plan_all(records):
        _apply_series_plan(
            session,
            stats,
            plan,
            source_uuid=source_uuid,
            ingested_at=ingested_at,
            context=context,
        )
    session.commit()


def _apply_series_plan(
    session: Session,
    stats: NormalizationStats,
    plan: SeriesPlan,
    *,
    source_uuid: str,
    ingested_at: datetime,
    context: Mapping[int, tuple[str, datetime, dict[str, Any]]],
) -> None:
    """Записать одну серию и её карты."""
    playable = [
        game
        for game in plan.games
        if game.reason is not QuarantineReason.MISSING_TEAM_IDENTITY
    ]
    if not playable:
        for game in plan.games:
            _quarantine_game(
                session,
                stats,
                game,
                source_uuid=source_uuid,
                ingested_at=ingested_at,
                context=context,
            )
        return

    first = min(
        playable,
        key=lambda game: (game.record.start_time or _MIN_TIME, game.record.match_id),
    )
    observation_id, observed_at, _ = context[first.record.match_id]
    envelope = build_envelope(
        observed_at=observed_at,
        ingested_at=ingested_at,
        event_time=first.record.start_time,
    )

    tournament_uuid: UUID | None = None
    if first.record.league_id is not None:
        tournament_uuid, created = writers.ensure_tournament(
            session,
            source_id=source_uuid,
            league_id=first.record.league_id,
            league_name=first.record.league_name,
            observation_id=observation_id,
            envelope=envelope,
        )
        stats.created_tournaments += int(created)

    series_uuid, created = writers.insert_series(
        session,
        source_id=source_uuid,
        series_key=plan.series_key,
        tournament_id=tournament_uuid,
        best_of=plan.best_of,
        status=str(plan.status),
        event_time=first.record.start_time,
        observation_id=observation_id,
        envelope=envelope,
    )
    stats.created_series += int(created)

    for game in plan.games:
        _apply_game(
            session,
            stats,
            game,
            series_uuid=series_uuid,
            source_uuid=source_uuid,
            ingested_at=ingested_at,
            context=context,
        )


def _apply_game(
    session: Session,
    stats: NormalizationStats,
    game: GamePlan,
    *,
    series_uuid: UUID,
    source_uuid: str,
    ingested_at: datetime,
    context: Mapping[int, tuple[str, datetime, dict[str, Any]]],
) -> None:
    """Записать карту (и при необходимости — строку карантина)."""
    record = game.record
    observation_id, observed_at, _ = context[record.match_id]

    if game.reason is QuarantineReason.MISSING_TEAM_IDENTITY:
        # Без идентичности команд нет ни участников, ни Team A/B — карту не пишем.
        _quarantine(
            session,
            stats,
            source_uuid=source_uuid,
            job_kind=JobKind.MAP_INDEX,
            provider_entity_id=str(record.match_id),
            reason=QuarantineReason.MISSING_TEAM_IDENTITY,
            observation_id=observation_id,
            ingested_at=ingested_at,
            observed_at=observed_at,
            payload=dict(record.__dict__),
        )
        return

    envelope = build_envelope(
        observed_at=observed_at,
        ingested_at=ingested_at,
        event_time=record.start_time,
    )
    radiant_id = record.radiant_team_id
    dire_id = record.dire_team_id
    assert radiant_id is not None and dire_id is not None  # отфильтровано планом
    radiant_uuid, created = writers.ensure_team(
        session,
        source_id=source_uuid,
        external_id=radiant_id,
        name=record.radiant_team_name,
        observation_id=observation_id,
        envelope=envelope,
    )
    stats.created_teams += int(created)
    dire_uuid, created = writers.ensure_team(
        session,
        source_id=source_uuid,
        external_id=dire_id,
        name=record.dire_team_name,
        observation_id=observation_id,
        envelope=envelope,
    )
    stats.created_teams += int(created)

    winner: UUID | None = None
    result_type = "unknown"
    if record.radiant_win is True:
        winner, result_type = radiant_uuid, "played"
    elif record.radiant_win is False:
        winner, result_type = dire_uuid, "played"

    game_uuid = identity.game_id(record.match_id, source_id=source_uuid)
    if writers.insert_game(
        session,
        source_id=source_uuid,
        match_id=record.match_id,
        series_id=series_uuid,
        map_number=game.map_number,
        status=str(game.status),
        winner_team_id=winner,
        result_type=result_type,
        patch_id=_resolve_patch(session, record.start_time),
        observation_id=observation_id,
        envelope=envelope,
    ):
        stats.created_games += 1

    for slot, (team_uuid, side) in enumerate(((radiant_uuid, "radiant"), (dire_uuid, "dire"))):
        if writers.insert_game_team(
            session,
            game_id=game_uuid,
            team_id=team_uuid,
            side=side,
            slot=slot,
            observation_id=observation_id,
            envelope=envelope,
        ):
            stats.created_game_teams += 1

    if game.reason is not None:
        _quarantine(
            session,
            stats,
            source_uuid=source_uuid,
            job_kind=JobKind.MAP_INDEX,
            provider_entity_id=str(record.match_id),
            reason=game.reason,
            observation_id=observation_id,
            ingested_at=ingested_at,
            observed_at=observed_at,
            payload=dict(record.__dict__),
        )
        return

    if record.radiant_win is None:
        # Карта есть, исхода нет: как обучающий пример она не годится.
        _quarantine(
            session,
            stats,
            source_uuid=source_uuid,
            job_kind=JobKind.MAP_INDEX,
            provider_entity_id=str(record.match_id),
            reason=QuarantineReason.MISSING_RESULT,
            observation_id=observation_id,
            ingested_at=ingested_at,
            observed_at=observed_at,
            payload=dict(record.__dict__),
        )
        return

    # Номер карты доказан — ранее незакрытые неоднозначности по ней снимаются.
    resolve_quarantine(
        session,
        job_kind=str(JobKind.MAP_INDEX),
        provider_entity_id=str(record.match_id),
        source_id=source_uuid,
    )


# --- этап 3: match_detail (участники, статистика, свидетельства состава) -----


def _normalize_match_details(
    session: Session, stats: NormalizationStats, *, source_uuid: str, ingested_at: datetime
) -> None:
    """Участники и финальная статистика карты."""
    for row in _fetch_observations(session, "match_detail"):
        detail = parse_match_detail(_decode_json(row.payload_json))
        if detail is None:
            _quarantine(
                session,
                stats,
                source_uuid=source_uuid,
                job_kind=JobKind.PARTICIPANTS,
                provider_entity_id=str(row.provider_entity_id),
                reason=QuarantineReason.UNPARSEABLE_RECORD,
                observation_id=str(row.observation_id),
                ingested_at=ingested_at,
                observed_at=row.observed_at,
                payload={"provider_entity_id": row.provider_entity_id},
            )
            continue
        _apply_match_detail(
            session,
            stats,
            detail,
            source_uuid=source_uuid,
            ingested_at=ingested_at,
            observation_id=str(row.observation_id),
            observed_at=row.observed_at,
        )
    session.commit()


def _apply_match_detail(
    session: Session,
    stats: NormalizationStats,
    detail: MatchDetailRecord,
    *,
    source_uuid: str,
    ingested_at: datetime,
    observation_id: str,
    observed_at: datetime,
) -> None:
    """Записать участников карты, статистику и свидетельства состава."""
    game_row = session.execute(
        text("SELECT id, event_time FROM game WHERE provider_match_id = :match_id"),
        {"match_id": str(detail.match_id)},
    ).one_or_none()
    if game_row is None:
        # Без контекста серии номер карты не определён → в датасет не идёт.
        _quarantine(
            session,
            stats,
            source_uuid=source_uuid,
            job_kind=JobKind.PARTICIPANTS,
            provider_entity_id=str(detail.match_id),
            reason=QuarantineReason.MISSING_SERIES_CONTEXT,
            observation_id=observation_id,
            ingested_at=ingested_at,
            observed_at=observed_at,
            payload={"match_id": detail.match_id},
        )
        return

    if not detail.players or any(entry.account_id is None for entry in detail.players):
        _quarantine(
            session,
            stats,
            source_uuid=source_uuid,
            job_kind=JobKind.PARTICIPANTS,
            provider_entity_id=str(detail.match_id),
            reason=QuarantineReason.MISSING_PLAYER_IDENTITY,
            observation_id=observation_id,
            ingested_at=ingested_at,
            observed_at=observed_at,
            payload={"match_id": detail.match_id, "players": len(detail.players)},
        )
        return

    game_uuid = UUID(str(game_row.id))
    game_time = game_row.event_time
    sides = _team_by_side(session, game_uuid)
    envelope = build_envelope(
        observed_at=observed_at,
        ingested_at=ingested_at,
        event_time=game_time or detail.start_time,
    )
    valid_from = game_time or detail.start_time
    valid_to = (
        valid_from + timedelta(seconds=detail.duration_seconds)
        if valid_from is not None and detail.duration_seconds
        else None
    )

    for index, entry in enumerate(detail.players):
        assert entry.account_id is not None  # проверено выше
        player_uuid, created = writers.ensure_player(
            session,
            source_id=source_uuid,
            account_id=entry.account_id,
            observation_id=observation_id,
            envelope=envelope,
        )
        stats.created_players += int(created)

        team_uuid = sides.get("radiant" if entry.is_radiant else "dire") if entry.is_radiant is not None else None
        participant_uuid, created = writers.insert_participant(
            session,
            game_id=game_uuid,
            player_id=player_uuid,
            team_id=team_uuid,
            hero_id=entry.hero_id,
            slot=_canonical_slot(entry.player_slot, index),
            observation_id=observation_id,
            envelope=envelope,
        )
        stats.created_participants += int(created)

        if writers.insert_performance(
            session,
            participant_id=participant_uuid,
            observation_id=observation_id,
            envelope=envelope,
            kills=entry.kills,
            deaths=entry.deaths,
            assists=entry.assists,
            net_worth=entry.net_worth,
            gold_per_min=entry.gold_per_min,
            xp_per_min=entry.xp_per_min,
            last_hits=entry.last_hits,
            denies=entry.denies,
            hero_damage=entry.hero_damage,
            duration_seconds=detail.duration_seconds,
        ):
            stats.created_performances += 1

        if team_uuid is not None and writers.insert_roster_membership(
            session,
            team_id=team_uuid,
            player_id=player_uuid,
            game_id=game_uuid,
            valid_from=valid_from,
            valid_to=valid_to,
            observation_id=observation_id,
            envelope=envelope,
        ):
            stats.created_roster_memberships += 1


# --- вспомогательное --------------------------------------------------------


def _fetch_observations(session: Session, endpoint_kind: str) -> Sequence[Row[Any]]:
    """Наблюдения источника по виду запроса, в стабильном порядке.

    Порядок «сначала ранние наблюдения» нужен для детерминированности:
    первым записавшимся считается самое раннее наблюдение.
    """
    return session.execute(
        text(
            """
            SELECT so.id AS observation_id,
                   so.provider_entity_id,
                   so.observed_at,
                   rp.id AS raw_id,
                   rp.payload_json
              FROM source_observation so
              JOIN raw_payload rp ON rp.id = so.raw_payload_id
             WHERE rp.endpoint_kind = :endpoint_kind
               AND so.provider_entity_id IS NOT NULL
             ORDER BY so.observed_at ASC, so.id ASC
            """
        ),
        {"endpoint_kind": endpoint_kind},
    ).all()


def _find_source(session: Session, name: str) -> str | None:
    """`data_source.id` по имени. `None` — источник ещё не зарегистрирован."""
    found = session.execute(
        text("SELECT id FROM data_source WHERE name = :name ORDER BY created_at LIMIT 1"),
        {"name": name},
    ).scalar()
    return str(found) if found is not None else None


def _resolve_patch(session: Session, at: datetime | None) -> UUID | None:
    """Патч, действовавший в момент `at`. `None` — справочник пуст/время неизвестно."""
    if at is None:
        return None
    found = session.execute(
        text(
            """
            SELECT id FROM patch
             WHERE effective_from <= :at
               AND (effective_to IS NULL OR effective_to > :at)
             ORDER BY effective_from DESC
             LIMIT 1
            """
        ),
        {"at": at},
    ).scalar()
    return UUID(str(found)) if found is not None else None


def _team_by_side(session: Session, game_uuid: UUID) -> dict[str, UUID]:
    """`{side: team_id}` для карты."""
    rows = session.execute(
        text("SELECT side, team_id FROM game_team WHERE game_id = :game_id"),
        {"game_id": game_uuid},
    ).all()
    return {str(row.side): UUID(str(row.team_id)) for row in rows if row.side is not None}


def _canonical_slot(player_slot: int | None, index: int) -> int:
    """Слот участника 0..9.

    OpenDota кодирует сторону в `player_slot`: 0..4 — Radiant, 128..132 — Dire.
    Приводим к сквозной нумерации 0..9, чтобы `UNIQUE (game, slot)` работал.
    """
    if player_slot is None:
        return index
    if player_slot >= 128:
        return player_slot - 128 + 5
    return player_slot


def _quarantine(
    session: Session,
    stats: NormalizationStats,
    *,
    source_uuid: str,
    job_kind: JobKind,
    provider_entity_id: str,
    reason: QuarantineReason,
    observation_id: str,
    ingested_at: datetime,
    observed_at: datetime,
    payload: Mapping[str, Any],
) -> None:
    """Записать строку карантина и учесть её в статистике."""
    item = QuarantineItem(
        job_kind=str(job_kind),
        provider_entity_id=provider_entity_id,
        reason_code=str(reason),
        observation_id=observation_id,
        envelope=build_envelope(observed_at=observed_at, ingested_at=ingested_at),
        offending_payload=_jsonable(payload),
    )
    if record_quarantine(session, item, source_id=source_uuid):
        stats.bump_quarantine(str(reason))


def _quarantine_game(
    session: Session,
    stats: NormalizationStats,
    game: GamePlan,
    *,
    source_uuid: str,
    ingested_at: datetime,
    context: Mapping[int, tuple[str, datetime, dict[str, Any]]],
) -> None:
    """Карантин карты, для которой нет контекста (нет команд)."""
    observation_id, observed_at, _ = context[game.record.match_id]
    _quarantine(
        session,
        stats,
        source_uuid=source_uuid,
        job_kind=JobKind.MAP_INDEX,
        provider_entity_id=str(game.record.match_id),
        reason=game.reason or QuarantineReason.MISSING_TEAM_IDENTITY,
        observation_id=observation_id,
        ingested_at=ingested_at,
        observed_at=observed_at,
        payload=dict(game.record.__dict__),
    )


def _decode_json(value: Any) -> Any:
    """Раскодировать payload, если драйвер вернул его строкой."""
    if isinstance(value, (str, bytes)):
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return None
    return value


def _as_sequence(payload: Any) -> Sequence[Any] | None:
    """Payload как список записей (страницы и справочники приходят массивом)."""
    if isinstance(payload, Sequence) and not isinstance(payload, (str, bytes)):
        return payload
    return None


def _jsonable(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Привести запись к JSON-совместимому виду для `offending_payload`."""
    result: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, datetime):
            result[key] = value.isoformat()
        elif isinstance(value, (str, int, float, bool)) or value is None:
            result[key] = value
        else:
            result[key] = str(value)
    return result

__all__ = ["NormalizationStats", "normalize_once"]
