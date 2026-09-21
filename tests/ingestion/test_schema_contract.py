"""ING-001 — schema drift contract tests (AC #8).

Смысл: если источник изменит форму ответа (уберёт поле, сменит тип), это должно
быть **обнаружено**, а не молча превратиться в «нет данных». Каждый ожидаемый
набор полей проверяется на удаление любого своего элемента из всех строк
страницы — именно так drift и определяется.

Ожидаемые наборы зафиксированы по `docs/research/OPENDOTA_API_MAP.md` — это
проверенная карта API, а не предположение.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest

from d2intel.ingestion.validation import (
    MATCH_DETAIL_FIELDS,
    MATCHES_TABLE_COLUMNS,
    PATCH_CONSTANT_FIELDS,
    PICKS_BANS_COLUMNS,
    PRO_MATCH_FIELDS,
    QuarantineReason,
    validate_explorer_matches,
    validate_explorer_picks_bans,
    validate_match_detail,
    validate_patch_constants,
    validate_pro_matches,
)
from tests.ingestion.conftest import (
    explorer_match_row,
    patch_constant_row,
    picks_bans_row,
    pro_match_row,
)

OBSERVED_AT = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)


def _match_detail_row() -> dict[str, Any]:
    return {
        "match_id": 9009924057,
        "start_time": 1_790_006_825,
        "duration": 1809,
        "radiant_win": True,
        "game_mode": 2,
        "lobby_type": 1,
        "patch": 60,
        "version": 22,
        "cluster": 191,
        "players": [],
        "draft_timings": [{"order": 0}],
    }


def _without_field(
    factory: Callable[[int], dict[str, Any]], field: str, count: int = 2
) -> list[dict[str, Any]]:
    """Страница, в которой ожидаемое поле отсутствует во **всех** строках."""
    rows = []
    for index in range(1, count + 1):
        row = factory(index)
        row.pop(field, None)
        rows.append(row)
    return rows


@pytest.mark.parametrize("field", PRO_MATCH_FIELDS)
def test_pro_matches_field_removal_is_detected(field: str) -> None:
    """Удаление ожидаемого поля `/proMatches` — drift, а не «нет матчей»."""
    rows = _without_field(pro_match_row, field)
    result = validate_pro_matches(rows, observed_at=OBSERVED_AT)

    assert result.records == ()
    assert field in result.missing_fields
    assert len(result.quarantined) == len(rows)
    assert all(
        record.reason_code == QuarantineReason.SCHEMA_DRIFT for record in result.quarantined
    )


@pytest.mark.parametrize("field", PICKS_BANS_COLUMNS)
def test_picks_bans_column_removal_is_detected(field: str) -> None:
    rows = _without_field(picks_bans_row, field)
    result = validate_explorer_picks_bans(
        rows, requested_columns=PICKS_BANS_COLUMNS, observed_at=OBSERVED_AT
    )

    assert result.records == ()
    assert field in result.missing_fields
    assert result.quarantined[0].reason_code == QuarantineReason.SCHEMA_DRIFT


@pytest.mark.parametrize("field", MATCHES_TABLE_COLUMNS)
def test_explorer_matches_column_removal_is_detected(field: str) -> None:
    rows = _without_field(explorer_match_row, field)
    result = validate_explorer_matches(
        rows, requested_columns=MATCHES_TABLE_COLUMNS, observed_at=OBSERVED_AT
    )

    assert result.records == ()
    assert field in result.missing_fields
    assert result.quarantined[0].reason_code == QuarantineReason.SCHEMA_DRIFT


@pytest.mark.parametrize("field", MATCH_DETAIL_FIELDS)
def test_match_detail_field_removal_is_detected(field: str) -> None:
    row = _match_detail_row()
    row.pop(field, None)
    result = validate_match_detail(row, observed_at=OBSERVED_AT)

    assert result.records == ()
    assert field in result.missing_fields
    assert result.quarantined[0].reason_code == QuarantineReason.SCHEMA_DRIFT


@pytest.mark.parametrize("field", PATCH_CONSTANT_FIELDS)
def test_patch_constant_field_removal_is_detected(field: str) -> None:
    rows = _without_field(patch_constant_row, field)
    result = validate_patch_constants(rows, observed_at=OBSERVED_AT)

    assert result.records == ()
    assert field in result.missing_fields
    assert result.quarantined[0].reason_code == QuarantineReason.SCHEMA_DRIFT


def test_expected_field_sets_match_the_api_map() -> None:
    """Наборы полей соответствуют проверенной карте API (OPENDOTA_API_MAP.md)."""
    assert set(MATCHES_TABLE_COLUMNS) == {
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
    }
    assert set(PICKS_BANS_COLUMNS) == {"match_id", "is_pick", "hero_id", "team", "ord"}
    assert "patch" not in MATCHES_TABLE_COLUMNS  # patch не колонка БД, а вычисляемое поле
    assert "series_id" in PRO_MATCH_FIELDS


def test_extra_unknown_fields_are_kept_not_dropped() -> None:
    """Новые поля источника не отбрасываются: raw сохраняется целиком."""
    row = pro_match_row(1)
    row["new_provider_field"] = {"nested": [1, 2, 3]}
    result = validate_pro_matches([row], observed_at=OBSERVED_AT)

    assert result.records[0].payload["new_provider_field"] == {"nested": [1, 2, 3]}


def test_type_change_is_not_silently_accepted() -> None:
    """Смена типа значения приводит к карантину, а не к тихому приведению."""
    row = pro_match_row(1)
    row["start_time"] = "1790006825"  # строка вместо int
    result = validate_pro_matches([row], observed_at=OBSERVED_AT)

    assert result.records == ()
    assert result.quarantined[0].reason_code == QuarantineReason.IMPLAUSIBLE_EVENT_TIME


def test_boolean_is_not_treated_as_integer_id() -> None:
    """bool не должен проходить как match_id (в Python bool — подкласс int)."""
    row = pro_match_row(1)
    row["match_id"] = True
    result = validate_pro_matches([row], observed_at=OBSERVED_AT)

    assert result.records == ()
    assert result.quarantined[0].reason_code == QuarantineReason.MISSING_PROVIDER_ENTITY_ID


def test_drift_is_reported_on_the_whole_page() -> None:
    """Drift — свойство страницы: помечается каждая строка, а не только первая."""
    rows = _without_field(pro_match_row, "series_id", count=3)
    result = validate_pro_matches(rows, observed_at=OBSERVED_AT)

    assert len(result.quarantined) == 3
    assert result.missing_fields == ("series_id",)


def test_partial_field_presence_is_not_drift() -> None:
    """Поле, присутствующее хотя бы в одной строке, — не drift, а свойство строки."""
    rows = _without_field(pro_match_row, "duration", count=1)
    rows.append(pro_match_row(2))  # вторая строка поле содержит
    result = validate_pro_matches(rows, observed_at=OBSERVED_AT)

    assert result.missing_fields == ()
    assert len(result.records) == 2
