"""ING-001 — тесты raw capture: идемпотентность, наблюдения, карантин, watermark.

Работают на реальной тестовой БД `d2intel_test` (миграции 0001 + 0002).
HTTP по-прежнему замокан: реальных запросов к OpenDota нет.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from d2intel.ingestion.contracts import OPENDOTA_CONTRACT, EndpointKind, FetchBatch
from d2intel.ingestion.raw_capture import (
    RUN_COMPLETED,
    RUN_STALE,
    CursorState,
    RawCapture,
)
from d2intel.ingestion.validation import QuarantineReason
from tests.ingestion.conftest import (
    FakeWallClock,
    RecordedRequests,
    json_response,
    make_client,
    pro_match_row,
    recording_handler,
)


def fetch_batch(
    rows: list[dict[str, object]],
    *,
    now: FakeWallClock | None = None,
    recorded: RecordedRequests | None = None,
) -> FetchBatch:
    """Batch из замоканного ответа OpenDota (реальная сеть не используется)."""
    recorder = recorded or RecordedRequests()
    handler = recording_handler(lambda request: json_response(rows), recorder)
    client = make_client(handler, now=now)
    return client.fetch_pro_matches()


def count(session: Session, table: str) -> int:
    return int(session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


# --- идемпотентность raw -----------------------------------------------------


def test_repeat_ingest_does_not_duplicate_raw(db_session: Session) -> None:
    """AC #4: повторный прогон не создаёт дублей raw_payload."""
    batch = fetch_batch([pro_match_row(1), pro_match_row(2)])
    capture = RawCapture(db_session, OPENDOTA_CONTRACT)
    run_id = capture.start_run()

    first = capture.ingest_batch(batch, run_id)
    second = capture.ingest_batch(batch, run_id)

    assert first.raw_inserted is True
    assert second.raw_inserted is False
    assert first.raw_payload_id == second.raw_payload_id
    assert count(db_session, "raw_payload") == 1


def test_repeated_retrieval_records_new_observation(db_session: Session) -> None:
    """Одинаковое содержимое на разных retrievals ≠ одно событие получения."""
    wall = FakeWallClock()
    batch_first = fetch_batch([pro_match_row(1)], now=wall)
    wall.advance(timedelta(hours=3))
    batch_second = fetch_batch([pro_match_row(1)], now=wall)

    assert batch_first.content_hash == batch_second.content_hash
    assert batch_first.observed_at != batch_second.observed_at

    capture = RawCapture(db_session, OPENDOTA_CONTRACT)
    run_id = capture.start_run()
    capture.ingest_batch(batch_first, run_id)
    capture.ingest_batch(batch_second, run_id)

    assert count(db_session, "raw_payload") == 1
    observations = db_session.execute(
        text("SELECT observed_at FROM source_observation ORDER BY observed_at")
    ).scalars().all()
    assert len(observations) == 2
    assert observations[0] < observations[1]


def test_observation_keeps_request_fingerprint(db_session: Session) -> None:
    batch = fetch_batch([pro_match_row(1)])
    capture = RawCapture(db_session, OPENDOTA_CONTRACT)
    run_id = capture.start_run()
    capture.ingest_batch(batch, run_id)

    fingerprint = db_session.execute(
        text("SELECT request_fingerprint FROM source_observation")
    ).scalar_one()
    assert fingerprint == batch.request.fingerprint


def test_empty_page_is_recorded_as_retrieval_event(db_session: Session) -> None:
    """Пустая страница — тоже событие получения, и оно видно в наблюдениях."""
    batch = fetch_batch([])
    capture = RawCapture(db_session, OPENDOTA_CONTRACT)
    run_id = capture.start_run()

    result = capture.ingest_batch(batch, run_id)

    assert result.observations_inserted == 1
    provider_id = db_session.execute(
        text("SELECT provider_entity_id FROM source_observation")
    ).scalar_one()
    assert provider_id is None


# --- временной конверт -------------------------------------------------------


def test_raw_payload_temporal_envelope_is_ordered(db_session: Session) -> None:
    """Инвариант PRD-003: observed_at <= ingested_at <= available_at."""
    batch = fetch_batch([pro_match_row(1)])
    capture = RawCapture(db_session, OPENDOTA_CONTRACT)
    run_id = capture.start_run()
    capture.ingest_batch(batch, run_id)

    row = db_session.execute(
        text(
            """
            SELECT observed_at, ingested_at, available_at, event_time,
                   schema_version, endpoint_kind, source_published_at
              FROM raw_payload
            """
        )
    ).one()
    assert row.observed_at <= row.ingested_at <= row.available_at
    assert row.schema_version == OPENDOTA_CONTRACT.schema_version
    assert row.endpoint_kind == str(EndpointKind.PRO_MATCHES)
    assert row.event_time is not None
    # Источник не сообщает время публикации: NULL, а не выдуманное значение.
    assert row.source_published_at is None


def test_raw_payload_stores_payload_verbatim(db_session: Session) -> None:
    """Raw сохраняется без нормализации и без потерь."""
    rows = [pro_match_row(9009924057)]
    batch = fetch_batch(rows)
    capture = RawCapture(db_session, OPENDOTA_CONTRACT)
    run_id = capture.start_run()
    capture.ingest_batch(batch, run_id)

    stored = db_session.execute(text("SELECT payload_json FROM raw_payload")).scalar_one()
    assert stored == rows


# --- watermark ---------------------------------------------------------------


def test_watermark_advanced_after_commit(db_session: Session) -> None:
    """AC #4/#6: watermark двигается и хранит курсор последней страницы."""
    batch = fetch_batch([pro_match_row(100), pro_match_row(90)])
    capture = RawCapture(db_session, OPENDOTA_CONTRACT)

    assert capture.load_cursor(str(EndpointKind.PRO_MATCHES)) is None

    run_id = capture.start_run()
    result = capture.ingest_batch(batch, run_id)

    assert result.cursor_advanced is True
    assert result.cursor_value == "90"
    cursor = capture.load_cursor(str(EndpointKind.PRO_MATCHES))
    assert isinstance(cursor, CursorState)
    assert cursor.cursor_value == "90"
    assert cursor.cursor_payload["page_end"] == 90
    assert cursor.last_run_id == run_id


def test_watermark_not_advanced_when_commit_fails(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Watermark продвигается только после успешного commit данных."""
    batch = fetch_batch([pro_match_row(100)])
    capture = RawCapture(db_session, OPENDOTA_CONTRACT)
    run_id = capture.start_run()
    original_commit = db_session.commit

    def failing_commit() -> None:
        raise RuntimeError("commit failed")

    monkeypatch.setattr(db_session, "commit", failing_commit)
    with pytest.raises(RuntimeError):
        capture.ingest_batch(batch, run_id)
    monkeypatch.setattr(db_session, "commit", original_commit)
    db_session.rollback()

    assert count(db_session, "ingestion_cursor") == 0
    assert count(db_session, "raw_payload") == 0


def test_watermark_survives_second_page(db_session: Session) -> None:
    batch_first = fetch_batch([pro_match_row(100), pro_match_row(90)])
    batch_second = fetch_batch([pro_match_row(80), pro_match_row(70)])
    capture = RawCapture(db_session, OPENDOTA_CONTRACT)
    run_id = capture.start_run()

    capture.ingest_batch(batch_first, run_id)
    result = capture.ingest_batch(batch_second, run_id)

    assert result.cursor_value == "70"
    assert count(db_session, "ingestion_cursor") == 1


# --- карантин ----------------------------------------------------------------


def test_quarantine_records_reason_and_payload(db_session: Session) -> None:
    """AC #5: проблемная строка попадает в карантин с отдельной причиной."""
    batch = fetch_batch([pro_match_row(1, radiant_team_id=None)])
    capture = RawCapture(db_session, OPENDOTA_CONTRACT)
    run_id = capture.start_run()

    result = capture.ingest_batch(batch, run_id)

    assert result.quarantined_inserted == 1
    row = db_session.execute(
        text(
            """
            SELECT reason_code, reason_detail, provider_entity_id, status,
                   endpoint_kind, offending_payload, observed_at, ingested_at, available_at
              FROM ingestion_quarantine
            """
        )
    ).one()
    assert row.reason_code == str(QuarantineReason.NULL_TEAM_IDENTITY)
    assert row.provider_entity_id == "1"
    assert row.status == "open"
    assert row.endpoint_kind == str(EndpointKind.PRO_MATCHES)
    assert row.offending_payload["match_id"] == 1
    assert row.observed_at <= row.ingested_at <= row.available_at
    # Сырой payload сохранён: карантин не означает потерю данных.
    assert count(db_session, "raw_payload") == 1


def test_quarantine_is_not_duplicated_on_repeat(db_session: Session) -> None:
    batch = fetch_batch([pro_match_row(1, dire_team_id=0)])
    capture = RawCapture(db_session, OPENDOTA_CONTRACT)
    run_id = capture.start_run()

    first = capture.ingest_batch(batch, run_id)
    second = capture.ingest_batch(batch, run_id)

    assert first.quarantined_inserted == 1
    assert second.quarantined_inserted == 0
    assert count(db_session, "ingestion_quarantine") == 1


def test_quarantine_reason_is_required(db_session: Session) -> None:
    """Пустая причина карантина отклоняется схемой."""
    from sqlalchemy.exc import IntegrityError

    source_id = RawCapture(db_session, OPENDOTA_CONTRACT).ensure_data_source()

    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                """
                INSERT INTO ingestion_quarantine (
                    source_id, endpoint_kind, reason_code, content_hash,
                    observed_at, ingested_at, available_at
                ) VALUES (
                    :source_id, 'pro_matches', '   ', 'hash',
                    now(), now(), now()
                )
                """
            ),
            {"source_id": source_id},
        )
    db_session.rollback()


# --- источник и прогон -------------------------------------------------------


def test_data_source_registered_from_contract(db_session: Session) -> None:
    """`data_source` заполняется из объявленного контракта."""
    capture = RawCapture(db_session, OPENDOTA_CONTRACT)
    source_id = capture.ensure_data_source()
    again = capture.ensure_data_source()
    assert source_id == again

    row = db_session.execute(
        text(
            """
            SELECT name, adapter_version, capabilities, terms_url,
                   allowed_purposes, retention_policy
              FROM data_source
            """
        )
    ).one()
    assert row.name == "opendota"
    assert row.adapter_version == OPENDOTA_CONTRACT.adapter_version
    assert row.capabilities["supports_upcoming"] is False
    assert row.capabilities["auth_required"] is False
    assert list(row.allowed_purposes) == list(OPENDOTA_CONTRACT.allowed_purposes)
    assert row.retention_policy
    # Публичного ToS-URL не найдено — значение не выдумывается.
    assert row.terms_url is None


def test_run_lifecycle_records_status_and_quota_headers(db_session: Session) -> None:
    batch = fetch_batch([pro_match_row(1)])
    capture = RawCapture(db_session, OPENDOTA_CONTRACT)
    run_id = capture.start_run()

    started = db_session.execute(
        text("SELECT status, started_at, finished_at FROM ingestion_run WHERE id = :id"),
        {"id": run_id},
    ).one()
    assert started.status == "running"
    assert started.finished_at is None

    capture.ingest_batch(batch, run_id)
    capture.finish_run(
        run_id,
        status=RUN_COMPLETED,
        quota_headers={"source_id": "opendota", "entries": []},
        cursor_after="90",
    )

    finished = db_session.execute(
        text(
            """
            SELECT status, finished_at, started_at, quota_headers, cursor_after
              FROM ingestion_run WHERE id = :id
            """
        ),
        {"id": run_id},
    ).one()
    assert finished.status == RUN_COMPLETED
    assert finished.finished_at >= finished.started_at
    assert finished.quota_headers["source_id"] == "opendota"
    assert finished.cursor_after == "90"


def test_source_outage_marks_run_stale(db_session: Session) -> None:
    """AC #9: source outage → прогон помечается stale, без тихого fallback."""
    capture = RawCapture(db_session, OPENDOTA_CONTRACT)
    run_id = capture.start_run()

    capture.mark_stale(run_id, "SourceUnavailableError: HTTP 500")

    row = db_session.execute(
        text("SELECT status, error_summary FROM ingestion_run WHERE id = :id"), {"id": run_id}
    ).one()
    assert row.status == RUN_STALE
    assert "SourceUnavailableError" in row.error_summary
    assert count(db_session, "raw_payload") == 0
