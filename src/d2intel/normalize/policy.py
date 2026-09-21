"""DATA-001 — политики нормализации: версии, коды, правила форматов.

Модуль содержит **только объявления**: никакой сети, БД и разбора payload.
Правила вынесены сюда, потому что они версионируются: изменение правила меняет
`*_POLICY_VERSION`, а значит и содержимое производных таблиц.

Ключевое правило (карточка `DATA-001`, риск «смешение игр разных форматов в
один map1»): номер карты присваивается **только закрытой серии**. Неполная
серия получает `map_number = NULL` и уходит в карантин: при обратном обходе
истории (descending match_id) пропущенные игры серии — это её **ранние**
карты, поэтому «первая найденная запись» не обязана быть map1.
"""

from __future__ import annotations

from enum import StrEnum

#: Политика вывода номера карты. Меняется вместе с правилами `map_index.py`.
MAP_INDEX_POLICY_VERSION = "map-index.v1"

#: Политика свидетельств ростера. Меняется вместе с `roster_membership`.
ROSTER_POLICY_VERSION = "roster-evidence.v1"

#: Версия схемы метрик финальной статистики.
PERFORMANCE_METRIC_SCHEMA_VERSION = "player-performance.v1"

#: Версия правил маппинга provider → canonical.
ENTITY_MAPPING_VERSION = "entity-mapping.v1"

#: `series_type` OpenDota → число карт в серии.
#: 0 — Bo1, 1 — Bo3, 2 — Bo5 (docs/research/OPENDOTA_API_MAP.md §2.1).
SERIES_FORMAT_GAMES: dict[int, int] = {0: 1, 1: 3, 2: 5}


class JobKind(StrEnum):
    """Этап нормализации, к которому относится карантинная запись."""

    PATCHES = "patches"
    MAP_INDEX = "map_index"
    PARTICIPANTS = "participants"


class QuarantineReason(StrEnum):
    """Причина карантина нормализации.

    Значения пишутся в `normalization_quarantine.reason_code` и являются частью
    контракта: отчёт по датасету группирует исключения по этим кодам.
    """

    #: Нет идентичности одной из команд — участников карты не определить.
    MISSING_TEAM_IDENTITY = "missing_team_identity"
    #: Участник без `account_id` — игрока нельзя канонизировать.
    MISSING_PLAYER_IDENTITY = "missing_player_identity"
    #: `series_type` вне известных значений — формат серии неизвестен.
    UNKNOWN_SERIES_TYPE = "unknown_series_type"
    #: Наблюдаемых карт меньше, чем требует формат: map1 не доказуем.
    INCOMPLETE_SERIES = "incomplete_series"
    #: Карт больше, чем допускает формат — группировка серии недостоверна.
    SERIES_COUNT_EXCEEDS_FORMAT = "series_count_exceeds_format"
    #: Совпадающее время старта внутри серии — порядок карт неопределён.
    AMBIGUOUS_MAP_ORDER = "ambiguous_map_order"
    #: Внутри одной серии разные пары команд.
    INCONSISTENT_SERIES_TEAMS = "inconsistent_series_teams"
    #: Детальная запись без контекста серии (нет pro_matches по этому матчу).
    MISSING_SERIES_CONTEXT = "missing_series_context"
    #: Нет признака результата (`radiant_win` отсутствует/не булево).
    MISSING_RESULT = "missing_result"
    #: Запись не читается: нет обязательных полей или тип не тот.
    UNPARSEABLE_RECORD = "unparseable_record"


class GameStatus(StrEnum):
    """Статусы `game.status` в рамках DATA-001."""

    #: Результат известен, номер карты присвоен либо серия Bo1.
    COMPLETED = "completed"
    #: Игра записана, но номер карты неопределён → в датасет не идёт.
    MAP_INDEX_UNRESOLVED = "map_index_unresolved"
    UNKNOWN = "unknown"


class SeriesStatus(StrEnum):
    """Статусы `series.status`."""

    COMPLETED = "completed"
    INCOMPLETE = "incomplete"
    UNKNOWN = "unknown"


def expected_games(series_type: int | None) -> int | None:
    """Сколько карт требует формат серии. `None` — формат неизвестен."""
    if series_type is None:
        return None
    return SERIES_FORMAT_GAMES.get(series_type)


def series_key(series_id: int | None, match_id: int) -> str:
    """Ключ группировки карт в серию.

    `series_id = 0/None` у OpenDota означает «вне серии»: такие матчи **не**
    объединяются, каждый получает собственную серию из одной карты (иначе все
    Bo3-матчи одной пары команд с `series_id = 0` склеились бы в одну серию).
    """
    if series_id is None or series_id == 0:
        return f"standalone:{match_id}"
    return f"series:{series_id}"
