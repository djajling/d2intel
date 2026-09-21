"""ING-001 — тесты ограниченного sync-once прогона (сквозной путь).

Проверяют связку клиент → raw capture → watermark на реальной тестовой БД.
Ответы источника замоканы: реальных запросов нет.
"""

from __future__ import annotations

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from d2intel.ingestion.contracts import EndpointKind, QuotaPolicy
from d2intel.ingestion.quota import QuotaBudget
from d2intel.ingestion.raw_capture import (
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_PARTIAL,
    RUN_QUOTA_EXHAUSTED,
    RUN_STALE,
)
from d2intel.ingestion.sync_once import dry_run_page, run_sync_once
from d2intel.ingestion.validation import QuarantineReason
from tests.ingestion.conftest import (
    FakeClock,
    FakeWallClock,
    Handler,
    RecordedRequests,
    json_response,
    make_client,
    pro_match_row,
    recording_handler,
)


def count(session: Session, table: str) -> int:
    return int(session.execute(text(f"SELECT count(*) FROM {table}")).scalar_one())


def paged_handler(
    pages: dict[int | None, list[dict[str, object]]], recorded: RecordedRequests
) -> Handler:
    """Обработчик, отдающий страницу по значению `less_than_match_id`."""

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("less_than_match_id")
        key = int(cursor) if cursor is not None else None
        return json_response(pages[key])

    return recording_handler(handler, recorded)


def test_sync_once_writes_raw_and_advances_watermark(
    db_session: Session, fake_wall_clock: FakeWallClock, recorded: RecordedRequests
) -> None:
    """Сквозной путь: страницы → raw → наблюдения → watermark."""
    pages: dict[int | None, list[dict[str, object]]] = {
        None: [pro_match_row(100), pro_match_row(90)],
        90: [],
    }
    client = make_client(paged_handler(pages, recorded), now=fake_wall_clock)

    report = run_sync_once(session=db_session, client=client, max_pages=5, overlap_pages=0)

    assert report.status == RUN_COMPLETED
    assert report.pages == 2
    assert report.records == 2
    assert report.raw_inserted == 2
    assert report.raw_deduplicated == 0
    assert report.cursor_before is None
    assert report.cursor_after == "90"
    assert count(db_session, "raw_payload") == 2
    assert count(db_session, "source_observation") == 3  # 2 матча + пустая страница
    assert count(db_session, "ingestion_cursor") == 1

    run = db_session.execute(
        text("SELECT status, cursor_before, cursor_after, quota_headers FROM ingestion_run")
    ).one()
    assert run.status == RUN_COMPLETED
    assert run.cursor_after == "90"
    assert run.quota_headers["source_id"] == "opendota"
    assert run.quota_headers["per_day"] == 3000


def test_second_identical_run_is_idempotent(
    db_session: Session, fake_wall_clock: FakeWallClock, recorded: RecordedRequests
) -> None:
    """AC #4: повторный прогон на тех же данных не создаёт дублей raw."""
    pages = {None: [pro_match_row(100), pro_match_row(90)]}
    handler = paged_handler(pages, recorded)

    first = run_sync_once(
        session=db_session, client=make_client(handler, now=fake_wall_clock), max_pages=1
    )
    raw_after_first = count(db_session, "raw_payload")

    second = run_sync_once(
        session=db_session, client=make_client(handler, now=fake_wall_clock), max_pages=1
    )

    assert first.raw_inserted == 1
    assert second.raw_inserted == 0
    assert second.raw_deduplicated == 1
    assert count(db_session, "raw_payload") == raw_after_first == 1
    # Наблюдения копятся: каждое получение — отдельное событие.
    assert count(db_session, "source_observation") == 4
    assert count(db_session, "ingestion_cursor") == 1


def test_resume_uses_watermark_and_overlap(
    db_session: Session, fake_wall_clock: FakeWallClock, recorded: RecordedRequests
) -> None:
    """Watermark переиспользуется, overlap повторно наблюдает последнюю страницу."""
    pages = {
        None: [pro_match_row(100), pro_match_row(90)],
        90: [pro_match_row(80), pro_match_row(70)],
    }
    handler = paged_handler(pages, recorded)

    first = run_sync_once(
        session=db_session, client=make_client(handler, now=fake_wall_clock), max_pages=2
    )
    assert first.cursor_after == "70"

    recorded.requests.clear()
    second = run_sync_once(
        session=db_session,
        client=make_client(handler, now=fake_wall_clock),
        max_pages=1,
        overlap_pages=1,
    )

    assert second.cursor_before == "70"
    assert recorded.requests[0].url.params.get("less_than_match_id") == "90"


def test_page_budget_marks_run_partial(
    db_session: Session, fake_wall_clock: FakeWallClock, recorded: RecordedRequests
) -> None:
    pages = {None: [pro_match_row(100)], 100: [pro_match_row(90)]}
    client = make_client(paged_handler(pages, recorded), now=fake_wall_clock)

    report = run_sync_once(session=db_session, client=client, max_pages=1, overlap_pages=0)

    assert report.status == RUN_PARTIAL
    run_status = db_session.execute(text("SELECT status FROM ingestion_run")).scalar_one()
    assert run_status == RUN_PARTIAL


def test_source_outage_marks_run_stale(
    db_session: Session, recorded: RecordedRequests, fake_clock: FakeClock
) -> None:
    """AC #9: источник недоступен → stale, данные не подменяются, raw не пишется."""
    handler = recording_handler(lambda request: httpx.Response(500, text="boom"), recorded)
    client = make_client(handler, clock=fake_clock)

    report = run_sync_once(session=db_session, client=client, max_pages=1)

    assert report.status == RUN_STALE
    assert report.error is not None
    assert "SourceUnavailableError" in report.error
    assert report.records == 0
    assert count(db_session, "raw_payload") == 0
    assert db_session.execute(text("SELECT status FROM ingestion_run")).scalar_one() == RUN_STALE


def test_auth_failure_marks_run_failed(db_session: Session, recorded: RecordedRequests) -> None:
    handler = recording_handler(lambda request: httpx.Response(401, text="nope"), recorded)
    client = make_client(handler)

    report = run_sync_once(session=db_session, client=client, max_pages=1)

    assert report.status == RUN_FAILED
    assert count(db_session, "raw_payload") == 0


def test_quota_exhaustion_marks_run(
    db_session: Session, fake_clock: FakeClock, recorded: RecordedRequests
) -> None:
    """AC #4: исчерпанный бюджет останавливает прогон явным статусом."""
    exhausted = QuotaBudget(
        QuotaPolicy(per_minute=60, per_day=0), clock=fake_clock.monotonic, sleeper=fake_clock.sleep
    )
    handler = recording_handler(lambda request: json_response([pro_match_row(1)]), recorded)
    client = make_client(handler, quota=exhausted)

    report = run_sync_once(session=db_session, client=client, max_pages=1)

    assert report.status == RUN_QUOTA_EXHAUSTED
    assert recorded.count == 0
    assert count(db_session, "raw_payload") == 0


def test_quarantined_rows_are_reported(
    db_session: Session, fake_wall_clock: FakeWallClock, recorded: RecordedRequests
) -> None:
    """Отчёт прогона показывает карантин по причинам, не теряя сырьё."""
    rows = [pro_match_row(1, radiant_team_id=None), pro_match_row(2)]
    handler = recording_handler(lambda request: json_response(rows), recorded)
    client = make_client(handler, now=fake_wall_clock)

    report = run_sync_once(session=db_session, client=client, max_pages=1)

    assert report.quarantined == 1
    assert report.quarantined_by_reason[str(QuarantineReason.NULL_TEAM_IDENTITY)] == 1
    assert count(db_session, "raw_payload") == 1
    assert count(db_session, "ingestion_quarantine") == 1


def test_sync_once_rejects_other_endpoints(
    db_session: Session, recorded: RecordedRequests
) -> None:
    client = make_client(recording_handler(lambda request: json_response([]), recorded))
    with pytest.raises(ValueError):
        run_sync_once(session=db_session, client=client, endpoint_kind=EndpointKind.MATCH_DETAIL)


def test_dry_run_does_not_write(db_session: Session, recorded: RecordedRequests) -> None:
    handler = recording_handler(lambda request: json_response([pro_match_row(1)]), recorded)

    summary = dry_run_page(make_client(handler))

    assert summary["records"] == 1
    assert summary["retrieval_status"] == "ok"
    assert count(db_session, "raw_payload") == 0
    assert count(db_session, "ingestion_run") == 0
