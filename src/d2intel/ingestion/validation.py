"""ING-001 — проверка формы сырых строк и причины карантина.

Модуль **не нормализует** данные: он не строит канонические сущности, не
вычисляет map index и не связывает карты в серии (`DATA-001`). Он отвечает
только на вопрос «пригодна ли строка как сырьё для downstream и, если нет, по
какой отдельной data-quality причине она уходит в карантин».

Ожидаемая форма взята из `docs/research/OPENDOTA_API_MAP.md` (проверено
запросами). Отсутствие ожидаемого поля во **всех** строках страницы — это
schema drift, и он фиксируется явно, а не молча.

Карантин не означает потерю данных: сырой payload сохраняется в `raw_payload`
всегда, карантин лишь помечает строку как непригодную.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from typing import Any

from d2intel.ingestion.contracts import ProviderRecord, QuarantineRecord

# --- словарь причин карантина ------------------------------------------------


class QuarantineReason(StrEnum):
    """Отдельная data-quality причина для каждой непригодной строки."""

    MISSING_PROVIDER_ENTITY_ID = "missing_provider_entity_id"
    NULL_TEAM_IDENTITY = "null_team_identity"
    MISSING_REQUIRED_VALUE = "missing_required_value"
    INVALID_RECORD_TYPE = "invalid_record_type"
    SCHEMA_DRIFT = "schema_drift"
    IMPLAUSIBLE_EVENT_TIME = "implausible_event_time"
    # Больше не порождается: пустой `draft_timings` — особенность источника,
    # запись сохраняется с note (см. `validate_match_detail`). Значение
    # оставлено, чтобы не ломать фильтры по старым данным карантина.
    EMPTY_DRAFT_TIMINGS = "empty_draft_timings"


# --- ожидаемая форма (OPENDOTA_API_MAP.md §2) --------------------------------

PRO_MATCH_FIELDS: tuple[str, ...] = (
    "match_id",
    "duration",
    "start_time",
    "radiant_team_id",
    "radiant_name",
    "dire_team_id",
    "dire_name",
    "leagueid",
    "league_name",
    "series_id",
    "series_type",
    "radiant_score",
    "dire_score",
    "radiant_win",
    "version",
)

MATCHES_TABLE_COLUMNS: tuple[str, ...] = (
    "match_id",
    "series_id",
    "series_type",
    "leagueid",
    "start_time",
    "radiant_win",
    "duration",
    "game_mode",
    "lobby_type",
    "cluster",
    "radiant_team_id",
    "dire_team_id",
)

PICKS_BANS_COLUMNS: tuple[str, ...] = ("match_id", "is_pick", "hero_id", "team", "ord")

MATCH_DETAIL_FIELDS: tuple[str, ...] = (
    "match_id",
    "start_time",
    "duration",
    "radiant_win",
    "game_mode",
    "lobby_type",
    "patch",
    "version",
    "cluster",
    "players",
)

PATCH_CONSTANT_FIELDS: tuple[str, ...] = ("id", "name", "date")

#: Нижняя граница правдоподобия `start_time` (Dota 2 существует с 2011 года).
MIN_EVENT_TIME = datetime(2011, 1, 1, tzinfo=UTC)
#: Насколько `start_time` может опережать наше время наблюдения.
MAX_FUTURE_SKEW = timedelta(days=7)


@dataclass(frozen=True)
class ValidationResult:
    """Результат проверки страницы: пригодные записи + карантин + drift-сигналы."""

    records: tuple[ProviderRecord, ...]
    quarantined: tuple[QuarantineRecord, ...]
    missing_fields: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()


# --- примитивы ---------------------------------------------------------------


def _is_positive_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_usable_team_id(value: Any) -> bool:
    """Team id 0/None — не сущность «Team 0» (ARCHITECTURE.md §4)."""
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _epoch_to_utc(value: Any) -> datetime | None:
    if not isinstance(value, int) or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(value, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _event_time_is_plausible(event_time: datetime | None, observed_at: datetime) -> bool:
    if event_time is None:
        return False
    return MIN_EVENT_TIME <= event_time <= observed_at + MAX_FUTURE_SKEW


def missing_fields_across_rows(
    rows: Sequence[Mapping[str, Any]], expected: Sequence[str]
) -> tuple[str, ...]:
    """Поля, отсутствующие во **всех** строках страницы (schema drift)."""
    if not rows:
        return ()
    present: set[str] = set()
    for row in rows:
        present.update(row.keys())
    return tuple(field for field in expected if field not in present)


class _QuarantineFactory:
    """Фабрика записей карантина с фиксированным временем наблюдения и типом."""

    def __init__(self, *, observed_at: datetime, provider_entity_type: str) -> None:
        self._observed_at = observed_at
        self._provider_entity_type = provider_entity_type

    def make(
        self,
        payload: Any,
        reason: QuarantineReason,
        detail: str,
        *,
        provider_entity_id: str | None = None,
    ) -> QuarantineRecord:
        offending = dict(payload) if isinstance(payload, Mapping) else {"_value": repr(payload)}
        return QuarantineRecord(
            reason_code=reason,
            reason_detail=detail,
            provider_entity_id=provider_entity_id,
            provider_entity_type=self._provider_entity_type,
            offending_payload=offending,
            observed_at=self._observed_at,
        )

    def drift(self, rows: Sequence[Mapping[str, Any]]) -> tuple[QuarantineRecord, ...]:
        """Помечает каждую строку страницы причиной schema_drift."""
        return tuple(
            self.make(
                row,
                QuarantineReason.SCHEMA_DRIFT,
                "page-level schema drift: expected fields absent in all rows",
                provider_entity_id=str(row.get("match_id")) if row.get("match_id") else None,
            )
            for row in rows
        )


# --- валидаторы по endpoint --------------------------------------------------


def validate_pro_matches(payload: Any, *, observed_at: datetime) -> ValidationResult:
    """Проверка страницы `/api/proMatches` (OPENDOTA_API_MAP.md §2.1)."""
    quarantine = _QuarantineFactory(observed_at=observed_at, provider_entity_type="match")
    if not isinstance(payload, list):
        return ValidationResult(
            records=(),
            quarantined=(
                quarantine.make(
                    payload,
                    QuarantineReason.INVALID_RECORD_TYPE,
                    "proMatches: неожиданная форма payload (ожидался массив)",
                ),
            ),
            notes=("payload_is_not_a_list",),
        )

    rows = [row for row in payload if isinstance(row, Mapping)]
    drift = missing_fields_across_rows(rows, PRO_MATCH_FIELDS)
    if drift:
        return ValidationResult(
            records=(),
            quarantined=quarantine.drift(rows),
            missing_fields=drift,
            notes=("schema_drift_page_level",),
        )

    records: list[ProviderRecord] = []
    quarantined: list[QuarantineRecord] = []
    for row in payload:
        if not isinstance(row, Mapping):
            quarantined.append(
                quarantine.make(row, QuarantineReason.INVALID_RECORD_TYPE, "row is not an object")
            )
            continue
        match_id = row.get("match_id")
        if not _is_positive_int(match_id):
            quarantined.append(
                quarantine.make(
                    row,
                    QuarantineReason.MISSING_PROVIDER_ENTITY_ID,
                    "match_id отсутствует или не положительное целое",
                )
            )
            continue
        event_time = _epoch_to_utc(row.get("start_time"))
        if not _event_time_is_plausible(event_time, observed_at):
            quarantined.append(
                quarantine.make(
                    row,
                    QuarantineReason.IMPLAUSIBLE_EVENT_TIME,
                    f"start_time={row.get('start_time')!r} вне допустимого диапазона",
                    provider_entity_id=str(match_id),
                )
            )
            continue
        if not (
            _is_usable_team_id(row.get("radiant_team_id"))
            and _is_usable_team_id(row.get("dire_team_id"))
        ):
            quarantined.append(
                quarantine.make(
                    row,
                    QuarantineReason.NULL_TEAM_IDENTITY,
                    "radiant_team_id/dire_team_id отсутствует или 0",
                    provider_entity_id=str(match_id),
                )
            )
            continue
        records.append(
            ProviderRecord(
                provider_entity_id=str(match_id),
                provider_entity_type="match",
                payload=dict(row),
                observed_at=observed_at,
                event_time=event_time,
            )
        )
    return ValidationResult(records=tuple(records), quarantined=tuple(quarantined))


def validate_explorer_matches(
    rows: Sequence[Any],
    *,
    requested_columns: Sequence[str],
    observed_at: datetime,
) -> ValidationResult:
    """Проверка строк `/api/explorer` по таблице `matches`."""
    return _validate_explorer_rows(
        rows,
        requested_columns=requested_columns,
        expected_columns=MATCHES_TABLE_COLUMNS,
        observed_at=observed_at,
        provider_entity_type="match",
    )


def validate_explorer_picks_bans(
    rows: Sequence[Any],
    *,
    requested_columns: Sequence[str],
    observed_at: datetime,
) -> ValidationResult:
    """Проверка строк `/api/explorer` по таблице `picks_bans`."""
    return _validate_explorer_rows(
        rows,
        requested_columns=requested_columns,
        expected_columns=PICKS_BANS_COLUMNS,
        observed_at=observed_at,
        provider_entity_type="picks_bans",
    )


def _validate_explorer_rows(
    rows: Sequence[Any],
    *,
    requested_columns: Sequence[str],
    expected_columns: Sequence[str],
    observed_at: datetime,
    provider_entity_type: str,
) -> ValidationResult:
    quarantine = _QuarantineFactory(
        observed_at=observed_at, provider_entity_type=provider_entity_type
    )
    expected = tuple(requested_columns) or expected_columns
    mappings = [row for row in rows if isinstance(row, Mapping)]
    drift = missing_fields_across_rows(mappings, expected)
    if drift:
        return ValidationResult(
            records=(),
            quarantined=quarantine.drift(mappings),
            missing_fields=drift,
            notes=("schema_drift_page_level",),
        )

    records: list[ProviderRecord] = []
    quarantined: list[QuarantineRecord] = []
    for row in rows:
        if not isinstance(row, Mapping):
            quarantined.append(
                quarantine.make(row, QuarantineReason.INVALID_RECORD_TYPE, "row is not an object")
            )
            continue
        match_id = row.get("match_id")
        if not _is_positive_int(match_id):
            quarantined.append(
                quarantine.make(
                    row,
                    QuarantineReason.MISSING_PROVIDER_ENTITY_ID,
                    "match_id отсутствует или не положительное целое",
                )
            )
            continue
        event_time = _epoch_to_utc(row.get("start_time")) if "start_time" in expected else None
        if "start_time" in expected and not _event_time_is_plausible(event_time, observed_at):
            quarantined.append(
                quarantine.make(
                    row,
                    QuarantineReason.IMPLAUSIBLE_EVENT_TIME,
                    f"start_time={row.get('start_time')!r} вне допустимого диапазона",
                    provider_entity_id=str(match_id),
                )
            )
            continue
        if provider_entity_type == "match":
            if not (
                _is_usable_team_id(row.get("radiant_team_id"))
                and _is_usable_team_id(row.get("dire_team_id"))
            ):
                quarantined.append(
                    quarantine.make(
                        row,
                        QuarantineReason.NULL_TEAM_IDENTITY,
                        "radiant_team_id/dire_team_id отсутствует или 0",
                        provider_entity_id=str(match_id),
                    )
                )
                continue
            if "radiant_win" in expected and not isinstance(row.get("radiant_win"), bool):
                quarantined.append(
                    quarantine.make(
                        row,
                        QuarantineReason.MISSING_REQUIRED_VALUE,
                        "radiant_win отсутствует или не boolean",
                        provider_entity_id=str(match_id),
                    )
                )
                continue
        else:
            violation = _picks_bans_type_violation(row)
            if violation is not None:
                quarantined.append(
                    quarantine.make(
                        row,
                        QuarantineReason.INVALID_RECORD_TYPE,
                        violation,
                        provider_entity_id=str(match_id),
                    )
                )
                continue
        records.append(
            ProviderRecord(
                provider_entity_id=str(match_id),
                provider_entity_type=provider_entity_type,
                payload=dict(row),
                observed_at=observed_at,
                event_time=event_time,
            )
        )
    return ValidationResult(records=tuple(records), quarantined=tuple(quarantined))


def _picks_bans_type_violation(row: Mapping[str, Any]) -> str | None:
    if not isinstance(row.get("is_pick"), bool):
        return "is_pick отсутствует или не boolean"
    if not isinstance(row.get("hero_id"), int) or isinstance(row.get("hero_id"), bool):
        return "hero_id отсутствует или не integer"
    if row.get("team") not in (0, 1):
        return "team вне допустимых значений (0/1)"
    if not isinstance(row.get("ord"), int) or isinstance(row.get("ord"), bool):
        return "ord отсутствует или не integer"
    return None


def validate_match_detail(payload: Any, *, observed_at: datetime) -> ValidationResult:
    """Проверка `/api/matches/{id}`.

    Пустой `draft_timings` — задокументированная особенность источника
    (OPENDOTA_API_MAP.md §2.2, §4.5): draft-данные для карты недоступны.
    Карантин в этом случае **не нужен**: участники, финальная статистика и
    свидетельства состава от draft не зависят (draft — отдельная стадия,
    `FEATURES.md` §5, MVP2). Факт отсутствия помечается note
    `empty_draft_timings` — он виден в completeness-флагах наблюдения, а сам
    draft не подменяется.
    """
    quarantine = _QuarantineFactory(observed_at=observed_at, provider_entity_type="match")
    if not isinstance(payload, Mapping):
        return ValidationResult(
            records=(),
            quarantined=(
                quarantine.make(
                    payload,
                    QuarantineReason.INVALID_RECORD_TYPE,
                    "matchDetail: неожиданная форма payload (ожидался объект)",
                ),
            ),
            notes=("payload_is_not_an_object",),
        )

    drift = missing_fields_across_rows([payload], MATCH_DETAIL_FIELDS)
    if drift:
        return ValidationResult(
            records=(),
            quarantined=quarantine.drift([payload]),
            missing_fields=drift,
            notes=("schema_drift_record_level",),
        )

    match_id = payload.get("match_id")
    if not _is_positive_int(match_id):
        return ValidationResult(
            records=(),
            quarantined=(
                quarantine.make(
                    payload,
                    QuarantineReason.MISSING_PROVIDER_ENTITY_ID,
                    "match_id отсутствует или не положительное целое",
                ),
            ),
        )

    event_time = _epoch_to_utc(payload.get("start_time"))
    if not _event_time_is_plausible(event_time, observed_at):
        return ValidationResult(
            records=(),
            quarantined=(
                quarantine.make(
                    payload,
                    QuarantineReason.IMPLAUSIBLE_EVENT_TIME,
                    f"start_time={payload.get('start_time')!r} вне допустимого диапазона",
                    provider_entity_id=str(match_id),
                ),
            ),
        )

    notes: list[str] = []
    draft_timings = payload.get("draft_timings")
    if isinstance(draft_timings, list) and not draft_timings:
        # Карантин записи целиком блокировал бы участников и статистику ради
        # поля, которое для них не нужно. Note — честная разметка отсутствия.
        notes.append("empty_draft_timings")

    return ValidationResult(
        records=(
            ProviderRecord(
                provider_entity_id=str(match_id),
                provider_entity_type="match",
                payload=dict(payload),
                observed_at=observed_at,
                event_time=event_time,
            ),
        ),
        quarantined=(),
        notes=tuple(notes),
    )


def validate_patch_constants(payload: Any, *, observed_at: datetime) -> ValidationResult:
    """Проверка `/api/constants/patch` (справочник, меняется редко)."""
    quarantine = _QuarantineFactory(
        observed_at=observed_at, provider_entity_type="patch_constant"
    )
    if not isinstance(payload, list):
        return ValidationResult(
            records=(),
            quarantined=(
                quarantine.make(
                    payload,
                    QuarantineReason.INVALID_RECORD_TYPE,
                    "patchConstants: неожиданная форма payload (ожидался массив)",
                ),
            ),
            notes=("payload_is_not_a_list",),
        )
    rows = [row for row in payload if isinstance(row, Mapping)]
    drift = missing_fields_across_rows(rows, PATCH_CONSTANT_FIELDS)
    if drift:
        return ValidationResult(
            records=(),
            quarantined=quarantine.drift(rows),
            missing_fields=drift,
            notes=("schema_drift_page_level",),
        )
    records: list[ProviderRecord] = []
    quarantined: list[QuarantineRecord] = []
    for row in rows:
        patch_id = row.get("id")
        if not _is_positive_int(patch_id):
            quarantined.append(
                quarantine.make(
                    row,
                    QuarantineReason.MISSING_PROVIDER_ENTITY_ID,
                    "id патча отсутствует или не положительное целое",
                )
            )
            continue
        records.append(
            ProviderRecord(
                provider_entity_id=str(patch_id),
                provider_entity_type="patch_constant",
                payload=dict(row),
                observed_at=observed_at,
            )
        )
    return ValidationResult(records=tuple(records), quarantined=tuple(quarantined))
