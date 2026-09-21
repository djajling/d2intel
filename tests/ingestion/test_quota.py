"""ING-001 — тесты throttle и дневного бюджета квоты.

AC #2: throttle соблюдает 60/мин и дневной бюджет 3 000.
AC #4: счётчик квоты не позволяет исчерпать суточный лимит.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from d2intel.ingestion.contracts import QuotaPolicy
from d2intel.ingestion.errors import QuotaExhaustedError
from d2intel.ingestion.quota import MAX_JOURNAL_ENTRIES, QuotaBudget
from tests.ingestion.conftest import FakeClock, FakeWallClock


def make_budget(
    clock: FakeClock,
    wall_clock: FakeWallClock,
    *,
    per_minute: int = 3,
    per_day: int = 10,
    max_wait_seconds: float = 60.0,
) -> QuotaBudget:
    return QuotaBudget(
        QuotaPolicy(per_minute=per_minute, per_day=per_day),
        clock=clock.monotonic,
        wall_clock=wall_clock,
        sleeper=clock.sleep,
        max_wait_seconds=max_wait_seconds,
    )


def test_minute_window_allows_exactly_the_limit() -> None:
    """В пределах минуты проходит ровно per_minute запросов, без ожидания."""
    clock, wall = FakeClock(), FakeWallClock()
    budget = make_budget(clock, wall, per_minute=3, per_day=100)

    for _ in range(3):
        budget.acquire()

    assert clock.sleeps == []
    snapshot = budget.snapshot()
    assert snapshot.minute_used == 3
    assert snapshot.minute_remaining == 0


def test_minute_window_throttles_next_request() -> None:
    """Четвёртый запрос ждёт освобождения окна, а не уходит в 429."""
    clock, wall = FakeClock(), FakeWallClock()
    budget = make_budget(clock, wall, per_minute=3, per_day=100)

    for _ in range(3):
        budget.acquire()
    budget.acquire()

    assert clock.sleeps == [pytest.approx(60.0)]
    assert budget.snapshot().minute_used == 1


def test_minute_window_refuses_to_wait_longer_than_budget() -> None:
    """Если окно не освобождается в пределах бюджета ожидания — явная ошибка."""
    clock, wall = FakeClock(), FakeWallClock()
    budget = make_budget(clock, wall, per_minute=1, per_day=100, max_wait_seconds=5.0)

    budget.acquire()
    with pytest.raises(QuotaExhaustedError) as excinfo:
        budget.acquire()

    assert excinfo.value.scope == "minute"
    assert excinfo.value.retry_after_seconds == pytest.approx(60.0)
    assert clock.sleeps == []


def test_day_budget_stops_requests() -> None:
    """Суточный лимит исчерпан — запрос не отправляется, ожидания нет."""
    clock, wall = FakeClock(), FakeWallClock()
    budget = make_budget(clock, wall, per_minute=60, per_day=2)

    budget.acquire()
    budget.acquire()
    with pytest.raises(QuotaExhaustedError) as excinfo:
        budget.acquire()

    assert excinfo.value.scope == "day"
    assert excinfo.value.retry_after_seconds is None
    assert clock.sleeps == []


def test_day_budget_resets_on_utc_date_change() -> None:
    """Смена UTC-даты сбрасывает суточный счётчик."""
    clock, wall = FakeClock(), FakeWallClock()
    budget = make_budget(clock, wall, per_minute=60, per_day=1)

    budget.acquire()
    with pytest.raises(QuotaExhaustedError):
        budget.acquire()

    wall.advance(timedelta(days=1))
    budget.acquire()  # новые сутки — бюджет снова доступен
    assert budget.snapshot().day_used == 1


def test_provider_headers_tighten_daily_budget() -> None:
    """Провайдер сообщил нулевой суточный остаток — локальный бюджет ужесточается."""
    clock, wall = FakeClock(), FakeWallClock()
    budget = make_budget(clock, wall, per_minute=60, per_day=3000)

    budget.acquire()
    budget.record_headers({"X-Rate-Limit-Remaining-Day": "0"})

    with pytest.raises(QuotaExhaustedError) as excinfo:
        budget.acquire()
    assert excinfo.value.scope == "day"


def test_provider_headers_tighten_minute_budget() -> None:
    """Нулевой минутный остаток от провайдера останавливает запросы."""
    clock, wall = FakeClock(), FakeWallClock()
    budget = make_budget(clock, wall, per_minute=60, per_day=3000)

    budget.record_headers({"X-Rate-Limit-Remaining-Minute": "0"})

    with pytest.raises(QuotaExhaustedError) as excinfo:
        budget.acquire()
    assert excinfo.value.scope == "minute"


def test_provider_headers_are_journalled() -> None:
    """Заголовки квоты читаются и попадают в журнал (AC: журнал headers)."""
    clock, wall = FakeClock(), FakeWallClock()
    budget = make_budget(clock, wall)

    budget.acquire()
    budget.record_headers(
        {"X-Rate-Limit-Remaining-Minute": "59", "X-Rate-Limit-Remaining-Day": "2999"},
        endpoint_kind="pro_matches",
        http_status=200,
    )

    journal = budget.journal()
    assert len(journal) == 2
    response_entry = journal[-1]
    assert response_entry["endpoint_kind"] == "pro_matches"
    assert response_entry["http_status"] == 200
    assert response_entry["remaining_minute"] == 59
    assert response_entry["remaining_day"] == 2999

    payload = budget.journal_payload(source_id="opendota")
    assert payload["source_id"] == "opendota"
    assert payload["per_minute"] == 3
    assert payload["per_day"] == 10
    assert payload["provider_day_remaining"] == 2999
    assert len(payload["entries"]) == 2


def test_journal_is_bounded_in_memory() -> None:
    """Журнал не растёт бесконечно (диагностика, а не архив)."""
    clock, wall = FakeClock(), FakeWallClock()
    budget = make_budget(clock, wall, per_minute=10_000, per_day=100_000)

    for _ in range(MAX_JOURNAL_ENTRIES + 50):
        budget.acquire()

    assert len(budget.journal()) == MAX_JOURNAL_ENTRIES


def test_default_free_tier_budget_allows_full_minute() -> None:
    """Реальные лимиты free-tier: 60 запросов проходят без ожидания."""
    clock, wall = FakeClock(), FakeWallClock()
    budget = make_budget(clock, wall, per_minute=60, per_day=3000)

    for _ in range(60):
        budget.acquire()

    assert clock.sleeps == []
    assert budget.snapshot().minute_remaining == 0
    assert budget.snapshot().day_used == 60
