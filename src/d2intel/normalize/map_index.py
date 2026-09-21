"""DATA-001 — вывод серий и номера карты (map index). Чистая функция.

Источник не хранит номер карты (`docs/research/OPENDOTA_API_MAP.md` §3):
`map_number` = порядковый номер матча внутри `series_id` по возрастанию
`start_time`. Здесь это делается **без обращения к БД**, чтобы правило было
проверяемым само по себе.

Главное решение — **когда номер карты НЕ присваивается**
(`MAP_INDEX_POLICY_VERSION`):

1. нет идентичности одной из команд → запись в карантин и исключается из серии;
2. формат серии неизвестен (`series_type` вне 0/1/2) → неоднозначность;
3. наблюдаемых карт **меньше**, чем требует формат → серия не закрыта. При
   обратном обходе истории пропущенные карты — ранние, поэтому «первая
   найденная запись» не обязана быть map1;
4. наблюдаемых карт больше, чем требует формат → группировка недостоверна;
5. совпадающее или неизвестное `start_time` внутри серии → порядок неопределён;
6. внутри одной серии разные пары команд → серия собрана неверно.

Неоднозначная карта **не удаляется**: она пишется в `game` с
`map_number = NULL` и статусом `map_index_unresolved`, плюс строка карантина.
Данные сохранены, но в датасет (map1) не попадают.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from d2intel.normalize.payloads import ProMatchRecord
from d2intel.normalize.policy import (
    GameStatus,
    QuarantineReason,
    SeriesStatus,
    expected_games,
    series_key,
)

#: Префикс ключа серии для матчей вне серии (`series_id = 0/None`).
STANDALONE_PREFIX = "standalone:"

#: Нижняя граница времени: сортировка записей с неизвестным `start_time`.
_MIN_DATETIME = datetime.min.replace(tzinfo=UTC)


@dataclass(frozen=True)
class GamePlan:
    """План записи одной карты."""

    record: ProMatchRecord
    map_number: int | None
    status: GameStatus
    reason: QuarantineReason | None = None

    @property
    def is_map_index_resolved(self) -> bool:
        """True, если номер карты доказан (игра пригодна для датасета map1)."""
        return self.map_number is not None


@dataclass(frozen=True)
class SeriesPlan:
    """План записи серии и её карт."""

    series_key: str
    best_of: int | None
    league_id: int | None
    status: SeriesStatus
    games: tuple[GamePlan, ...]
    reason: QuarantineReason | None = None

    @property
    def quarantined_games(self) -> tuple[GamePlan, ...]:
        """Карты серии, исключённые из датасета."""
        return tuple(game for game in self.games if game.reason is not None)


def group_records(records: Iterable[ProMatchRecord]) -> dict[str, list[ProMatchRecord]]:
    """Сгруппировать записи по ключу серии. Порядок групп — появления."""
    groups: dict[str, list[ProMatchRecord]] = {}
    for record in records:
        key = series_key(record.series_id, record.match_id)
        groups.setdefault(key, []).append(record)
    return groups


def plan_all(records: Iterable[ProMatchRecord]) -> tuple[SeriesPlan, ...]:
    """Распланировать все серии. Детерминированно: порядок по ключу серии."""
    groups = group_records(records)
    return tuple(plan_series(key, groups[key]) for key in sorted(groups))


def plan_series(key: str, records: Sequence[ProMatchRecord]) -> SeriesPlan:
    """Распланировать одну серию: номер карт + причина неоднозначности.

    Возвращает план **для всех** записей группы, включая исключённые: вызывающий
    код пишет и строки `game`, и строки карантина.
    """
    usable: list[ProMatchRecord] = []
    excluded: list[GamePlan] = []
    for record in records:
        if record.radiant_team_id is None or record.dire_team_id is None:
            excluded.append(
                GamePlan(
                    record=record,
                    map_number=None,
                    status=GameStatus.MAP_INDEX_UNRESOLVED,
                    reason=QuarantineReason.MISSING_TEAM_IDENTITY,
                )
            )
        else:
            usable.append(record)

    best_of = _best_of(key, records)
    reason = _group_reason(key, usable, best_of)
    ordered = _ordered(usable)

    games: list[GamePlan] = list(excluded)
    if reason is None:
        games.extend(
            GamePlan(
                record=record,
                map_number=index,
                status=GameStatus.COMPLETED,
                reason=None,
            )
            for index, record in enumerate(ordered, start=1)
        )
    else:
        games.extend(
            GamePlan(
                record=record,
                map_number=None,
                status=GameStatus.MAP_INDEX_UNRESOLVED,
                reason=reason,
            )
            for record in _ordered_for_quarantine(usable)
        )

    return SeriesPlan(
        series_key=key,
        best_of=best_of,
        league_id=usable[0].league_id if usable else None,
        status=_series_status(reason),
        games=tuple(sorted(games, key=lambda game: game.record.match_id)),
        reason=reason,
    )


# --- внутреннее -------------------------------------------------------------


def _best_of(key: str, records: Sequence[ProMatchRecord]) -> int | None:
    """Формат серии. Для одиночных матчей — 1, если источник не заявлял Bo3+.

    `series_id = 0/None` означает «вне серии». Если при этом заявлен формат
    Bo3/Bo5, группировать не на чем: формат оставляем как заявленный, и серия
    окажется неполной (одна карта вместо трёх) → карантин, а не три ложных map1.
    """
    if key.startswith(STANDALONE_PREFIX):
        types = {record.series_type for record in records if record.series_type is not None}
        if not types or types == {0}:
            return 1
        return expected_games(sorted(types)[0])
    for record in records:
        best_of = expected_games(record.series_type)
        if best_of is not None:
            return best_of
    return None


def _group_reason(
    key: str, usable: Sequence[ProMatchRecord], best_of: int | None
) -> QuarantineReason | None:
    """Причина, по которой серия целиком не получает номера карт."""
    if not usable:
        # Все записи исключены по идентичности — причина уже в самих записях.
        return None
    if best_of is None:
        return QuarantineReason.UNKNOWN_SERIES_TYPE
    if _has_tied_or_missing_start(usable):
        return QuarantineReason.AMBIGUOUS_MAP_ORDER
    if _has_inconsistent_teams(usable):
        return QuarantineReason.INCONSISTENT_SERIES_TEAMS
    if len(usable) > best_of:
        return QuarantineReason.SERIES_COUNT_EXCEEDS_FORMAT
    if len(usable) < best_of:
        return QuarantineReason.INCOMPLETE_SERIES
    return None


def _has_tied_or_missing_start(records: Sequence[ProMatchRecord]) -> bool:
    """Порядок карт неопределён: совпадающее или неизвестное время старта."""
    times = [record.start_time for record in records]
    if any(time is None for time in times):
        return True
    return len(set(times)) != len(times)


def _has_inconsistent_teams(records: Sequence[ProMatchRecord]) -> bool:
    """Внутри одной серии должна быть одна и та же пара команд.

    Стороны между картами меняются, поэтому пара берётся неупорядоченной.
    """
    pairs = {
        frozenset({record.radiant_team_id, record.dire_team_id})
        for record in records
        if record.radiant_team_id is not None and record.dire_team_id is not None
    }
    return len(pairs) > 1


def _ordered(records: Sequence[ProMatchRecord]) -> list[ProMatchRecord]:
    """Карты в порядке возрастания времени старта."""
    return sorted(records, key=lambda record: (record.start_time or _MIN_DATETIME, record.match_id))


def _ordered_for_quarantine(records: Sequence[ProMatchRecord]) -> list[ProMatchRecord]:
    """Порядок записей при карантине — по match_id (время может совпадать)."""
    return sorted(records, key=lambda record: record.match_id)


def _series_status(reason: QuarantineReason | None) -> SeriesStatus:
    if reason is None:
        return SeriesStatus.COMPLETED
    if reason is QuarantineReason.INCOMPLETE_SERIES:
        return SeriesStatus.INCOMPLETE
    return SeriesStatus.UNKNOWN
