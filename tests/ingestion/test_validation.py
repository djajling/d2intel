"""ING-001 — тесты проверки формы строк и причин карантина (AC #5).

Проверяется, что непригодные строки получают **отдельную** data-quality причину,
а пригодные сохраняются как сырьё без изменений (нормализации здесь нет).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from d2intel.ingestion.validation import (
    MATCH_DETAIL_FIELDS,
    QuarantineReason,
    missing_fields_across_rows,
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


def test_valid_pro_match_becomes_record_with_event_time() -> None:
    """Пригодная строка → запись с provider id, event_time и сырым payload."""
    payload = [pro_match_row(9009924057)]
    result = validate_pro_matches(payload, observed_at=OBSERVED_AT)

    assert result.quarantined == ()
    assert len(result.records) == 1
    record = result.records[0]
    assert record.provider_entity_id == "9009924057"
    assert record.provider_entity_type == "match"
    assert record.event_time == datetime.fromtimestamp(1_790_006_825, tz=UTC)
    # Сырьё сохраняется без нормализации: те же ключи и значения.
    assert dict(record.payload) == payload[0]


def test_null_team_identity_goes_to_quarantine() -> None:
    """null/0 в team id — отдельная причина: это не сущность «Team 0»."""
    payload = [pro_match_row(1, radiant_team_id=None), pro_match_row(2, dire_team_id=0)]
    result = validate_pro_matches(payload, observed_at=OBSERVED_AT)

    assert result.records == ()
    assert [row.reason_code for row in result.quarantined] == [
        QuarantineReason.NULL_TEAM_IDENTITY,
        QuarantineReason.NULL_TEAM_IDENTITY,
    ]
    assert [row.provider_entity_id for row in result.quarantined] == ["1", "2"]


def test_missing_match_id_goes_to_quarantine() -> None:
    """Ключ есть, значение непригодно → причина missing_provider_entity_id."""
    row = pro_match_row(1)
    row["match_id"] = None
    result = validate_pro_matches([row], observed_at=OBSERVED_AT)

    assert result.records == ()
    assert result.quarantined[0].reason_code == QuarantineReason.MISSING_PROVIDER_ENTITY_ID


def test_absent_match_id_key_is_schema_drift() -> None:
    """Ключ отсутствует во всех строках → drift, а не «одна плохая строка»."""
    row = pro_match_row(1)
    row.pop("match_id")
    result = validate_pro_matches([row], observed_at=OBSERVED_AT)

    assert result.records == ()
    assert result.quarantined[0].reason_code == QuarantineReason.SCHEMA_DRIFT
    assert "match_id" in result.missing_fields


@pytest.mark.parametrize("bad_start_time", [0, -5, 1_900_000_000])
def test_implausible_event_time_goes_to_quarantine(bad_start_time: int) -> None:
    """start_time вне правдоподобного диапазона — отдельная причина."""
    payload = [pro_match_row(1, start_time=bad_start_time)]
    result = validate_pro_matches(payload, observed_at=OBSERVED_AT)

    assert result.records == ()
    assert result.quarantined[0].reason_code == QuarantineReason.IMPLAUSIBLE_EVENT_TIME


def test_future_start_time_within_skew_is_accepted() -> None:
    """Небольшое опережение часов источника допустимо."""
    soon = int((OBSERVED_AT + timedelta(hours=2)).timestamp())
    result = validate_pro_matches([pro_match_row(1, start_time=soon)], observed_at=OBSERVED_AT)
    assert len(result.records) == 1


def test_non_mapping_row_goes_to_quarantine() -> None:
    result = validate_pro_matches(["not-an-object"], observed_at=OBSERVED_AT)
    assert result.quarantined[0].reason_code == QuarantineReason.INVALID_RECORD_TYPE


def test_non_list_payload_goes_to_quarantine() -> None:
    result = validate_pro_matches({"error": "boom"}, observed_at=OBSERVED_AT)
    assert result.records == ()
    assert result.quarantined[0].reason_code == QuarantineReason.INVALID_RECORD_TYPE
    assert "payload_is_not_a_list" in result.notes


def test_explorer_match_row_without_outcome_is_quarantined() -> None:
    result = validate_explorer_matches(
        [explorer_match_row(1, radiant_win=None)],
        requested_columns=tuple(explorer_match_row(1).keys()),
        observed_at=OBSERVED_AT,
    )
    assert result.quarantined[0].reason_code == QuarantineReason.MISSING_REQUIRED_VALUE


def test_explorer_match_row_with_null_team_identity_is_quarantined() -> None:
    result = validate_explorer_matches(
        [explorer_match_row(1, dire_team_id=None)],
        requested_columns=tuple(explorer_match_row(1).keys()),
        observed_at=OBSERVED_AT,
    )
    assert result.quarantined[0].reason_code == QuarantineReason.NULL_TEAM_IDENTITY


def test_picks_bans_rows_are_validated_by_type() -> None:
    """picks_bans: is_pick/hero_id/team/ord проверяются по типу."""
    good = picks_bans_row(1, is_pick=False, ord_=0)
    bad = picks_bans_row(1, is_pick="yes")  # type: ignore[arg-type]
    result = validate_explorer_picks_bans(
        [good, bad],
        requested_columns=tuple(good.keys()),
        observed_at=OBSERVED_AT,
    )
    assert len(result.records) == 1
    assert result.records[0].provider_entity_type == "picks_bans"
    assert result.quarantined[0].reason_code == QuarantineReason.INVALID_RECORD_TYPE


def test_picks_bans_invalid_team_is_quarantined() -> None:
    bad = picks_bans_row(1)
    bad["team"] = 5
    result = validate_explorer_picks_bans(
        [bad], requested_columns=tuple(bad.keys()), observed_at=OBSERVED_AT
    )
    assert result.quarantined[0].reason_code == QuarantineReason.INVALID_RECORD_TYPE


def test_match_detail_with_empty_draft_timings_is_recorded_with_note() -> None:
    """Пустой draft_timings — особенность источника: запись сохраняется.

    Карантин блокировал бы участников и статистику ради поля, которое для них
    не нужно; отсутствие помечается note, а не терей данных.
    """
    payload = {
        "match_id": 9009924057,
        "start_time": 1_790_006_825,
        "duration": 1809,
        "radiant_win": True,
        "game_mode": 2,
        "lobby_type": 1,
        "patch": 60,
        "version": 22,
        "cluster": 191,
        "players": [{"account_id": 1, "hero_id": 145}],
        "draft_timings": [],
    }
    result = validate_match_detail(payload, observed_at=OBSERVED_AT)

    assert len(result.records) == 1
    assert result.records[0].provider_entity_id == "9009924057"
    assert result.quarantined == ()
    assert "empty_draft_timings" in result.notes


def test_match_detail_with_draft_timings_is_accepted() -> None:
    payload = {
        "match_id": 9009924057,
        "start_time": 1_790_006_825,
        "duration": 1809,
        "radiant_win": True,
        "game_mode": 2,
        "lobby_type": 1,
        "patch": 60,
        "version": 22,
        "cluster": 191,
        "players": [{"account_id": 1, "hero_id": 145}],
        "draft_timings": [{"order": 0, "pick": True}],
    }
    result = validate_match_detail(payload, observed_at=OBSERVED_AT)
    assert len(result.records) == 1
    assert result.notes == ()


def test_patch_constants_are_validated() -> None:
    result = validate_patch_constants(
        [patch_constant_row(60), {"name": "no-id", "date": "2026-01-01"}],
        observed_at=OBSERVED_AT,
    )
    assert len(result.records) == 1
    assert result.records[0].provider_entity_type == "patch_constant"
    assert result.quarantined[0].reason_code == QuarantineReason.MISSING_PROVIDER_ENTITY_ID


def test_missing_fields_across_rows_requires_absence_in_every_row() -> None:
    """Поле считается отсутствующим только если его нет во всех строках."""
    rows = [{"a": 1, "b": 2}, {"a": 3, "c": 4}]
    assert missing_fields_across_rows(rows, ("a", "b", "c", "d")) == ("d",)
    assert missing_fields_across_rows([], ("a",)) == ()


def test_quarantine_payload_is_preserved_for_diagnostics() -> None:
    """Карантин хранит саму непригодную строку — разбор возможен без повторного fetch."""
    bad = pro_match_row(7, radiant_team_id=None)
    result = validate_pro_matches([bad], observed_at=OBSERVED_AT)
    assert dict(result.quarantined[0].offending_payload) == bad


def test_validator_does_not_compute_map_index_or_series_links() -> None:
    """Никакой нормализации: в payload не появляется вычисленных полей."""
    payload = [pro_match_row(1), pro_match_row(2)]
    result = validate_pro_matches(payload, observed_at=OBSERVED_AT)
    for record in result.records:
        assert "map_number" not in record.payload
        assert "patch" not in record.payload
        assert "game_number" not in record.payload
    assert MATCH_DETAIL_FIELDS  # набор ожидаемых полей объявлен явно
