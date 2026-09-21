"""ING-001 — тесты retry-политики (AC #3).

Проверяется: exponential backoff с jitter, уважение `Retry-After`, остановка на
auth/permission-ошибках без повторов, исчерпание retry-бюджета.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from d2intel.ingestion.retry import (
    ErrorClass,
    RetryPolicy,
    backoff_delay,
    classify_exception,
    classify_status,
    next_delay,
    parse_retry_after,
    retry_after_exceeds_budget,
    should_retry,
)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, ErrorClass.AUTH),
        (403, ErrorClass.AUTH),
        (404, ErrorClass.NOT_FOUND),
        (408, ErrorClass.TRANSIENT),
        (425, ErrorClass.TRANSIENT),
        (429, ErrorClass.RATE_LIMIT),
        (500, ErrorClass.TRANSIENT),
        (502, ErrorClass.TRANSIENT),
        (503, ErrorClass.TRANSIENT),
        (400, ErrorClass.PERMANENT),
        (422, ErrorClass.PERMANENT),
    ],
)
def test_classify_status(status: int, expected: ErrorClass) -> None:
    """Классификация вызывается только для ошибочных статусов (>= 400)."""
    assert classify_status(status) == expected


@pytest.mark.parametrize(
    "exc",
    [
        httpx.ConnectTimeout("timeout"),
        httpx.ReadTimeout("timeout"),
        httpx.ConnectError("connect"),
        httpx.ReadError("read"),
        httpx.RemoteProtocolError("protocol"),
    ],
)
def test_classify_transient_exceptions(exc: Exception) -> None:
    assert classify_exception(exc) == ErrorClass.TRANSIENT


def test_classify_unexpected_exception_is_permanent() -> None:
    assert classify_exception(ValueError("boom")) == ErrorClass.PERMANENT


def test_only_transient_and_rate_limit_are_retried() -> None:
    assert should_retry(ErrorClass.TRANSIENT) is True
    assert should_retry(ErrorClass.RATE_LIMIT) is True
    assert should_retry(ErrorClass.AUTH) is False
    assert should_retry(ErrorClass.PERMANENT) is False
    assert should_retry(ErrorClass.NOT_FOUND) is False


def test_parse_retry_after_seconds() -> None:
    assert parse_retry_after("7") == pytest.approx(7.0)
    assert parse_retry_after(" 3.5 ") == pytest.approx(3.5)
    assert parse_retry_after("0") == pytest.approx(0.0)
    assert parse_retry_after("-5") == pytest.approx(0.0)


def test_parse_retry_after_http_date() -> None:
    now = datetime(2026, 9, 21, 12, 0, tzinfo=UTC)
    value = (now + timedelta(seconds=30)).strftime("%a, %d %b %Y %H:%M:%S GMT")
    assert parse_retry_after(value, now=now) == pytest.approx(30.0, abs=1.0)


def test_parse_retry_after_invalid_returns_none() -> None:
    assert parse_retry_after(None) is None
    assert parse_retry_after("") is None
    assert parse_retry_after("soon") is None


def test_backoff_grows_exponentially_within_jitter_bounds() -> None:
    """Backoff ограничен max_delay, jitter усекает задержку, но не увеличивает её."""
    policy = RetryPolicy(base_delay_seconds=1.0, max_delay_seconds=10.0, jitter_ratio=0.5)
    rng = random.Random(7)

    for failures in (1, 2, 3):
        base = min(1.0 * (2 ** (failures - 1)), 10.0)
        for _ in range(20):
            delay = backoff_delay(failures, policy, rng)
            assert base * 0.5 <= delay <= base

    assert backoff_delay(10, policy, rng) <= 10.0


def test_backoff_is_deterministic_for_fixed_seed() -> None:
    policy = RetryPolicy()
    first = [backoff_delay(2, policy, random.Random(99)) for _ in range(3)]
    second = [backoff_delay(2, policy, random.Random(99)) for _ in range(3)]
    assert first == second


def test_backoff_without_jitter_is_pure_exponential() -> None:
    policy = RetryPolicy(base_delay_seconds=0.5, max_delay_seconds=100.0, jitter_ratio=0.0)
    rng = random.Random(1)
    assert backoff_delay(1, policy, rng) == pytest.approx(0.5)
    assert backoff_delay(2, policy, rng) == pytest.approx(1.0)
    assert backoff_delay(3, policy, rng) == pytest.approx(2.0)


def test_next_delay_respects_retry_after_over_backoff() -> None:
    """`Retry-After` уважается: пауза не короче запрошенной провайдером."""
    policy = RetryPolicy(base_delay_seconds=0.5, jitter_ratio=0.0)
    delay = next_delay(attempt=1, policy=policy, rng=random.Random(1), retry_after_seconds=12.0)
    assert delay == pytest.approx(12.0)


def test_next_delay_uses_backoff_when_retry_after_is_smaller() -> None:
    policy = RetryPolicy(base_delay_seconds=5.0, jitter_ratio=0.0)
    delay = next_delay(attempt=1, policy=policy, rng=random.Random(1), retry_after_seconds=1.0)
    assert delay == pytest.approx(5.0)


def test_retry_after_beyond_budget_is_detected() -> None:
    policy = RetryPolicy(max_retry_after_seconds=60.0)
    assert retry_after_exceeds_budget(61.0, policy) is True
    assert retry_after_exceeds_budget(60.0, policy) is False
    assert retry_after_exceeds_budget(None, policy) is False
