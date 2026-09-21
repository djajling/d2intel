"""ING-001 — retry-политика (ARCHITECTURE.md §3, п. 1).

Правила:

* transient (5xx, сетевые ошибки, timeout) — повтор с exponential backoff + jitter;
* 429 — повтор с уважением `Retry-After`; если провайдер просит паузу больше
  бюджета `max_retry_after_seconds`, повтор не выполняется (остановка);
* 401/403 — **остановка без повторов** (auth/permission);
* 404 — не ошибка доставки: ресурса нет (провайдер не тарифицирует 404);
* прочие 4xx — постоянная ошибка, повтор бесполезен.

Jitter детерминирован при инжектированном `random.Random`, поэтому тестируется
без ожидания реального времени.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from enum import StrEnum

import httpx


class ErrorClass(StrEnum):
    """Класс ошибки — от него зависит решение о повторе."""

    TRANSIENT = "transient"
    RATE_LIMIT = "rate_limit"
    AUTH = "auth"
    NOT_FOUND = "not_found"
    PERMANENT = "permanent"


@dataclass(frozen=True)
class RetryPolicy:
    """Ограниченный retry-бюджет."""

    max_attempts: int = 4
    base_delay_seconds: float = 0.5
    max_delay_seconds: float = 20.0
    #: Доля усечения задержки: итоговая задержка равномерна в [base*(1-r), base].
    jitter_ratio: float = 0.5
    #: Максимальная пауза, которую согласны переждать по `Retry-After`.
    max_retry_after_seconds: float = 120.0


def classify_status(status_code: int) -> ErrorClass:
    """Классификация HTTP-статуса. Вызывается только для ошибочных (>= 400)."""
    if status_code in (401, 403):
        return ErrorClass.AUTH
    if status_code == 404:
        return ErrorClass.NOT_FOUND
    if status_code == 429:
        return ErrorClass.RATE_LIMIT
    if status_code in (408, 425) or status_code >= 500:
        return ErrorClass.TRANSIENT
    if 400 <= status_code < 500:
        return ErrorClass.PERMANENT
    return ErrorClass.PERMANENT


def classify_exception(exc: BaseException) -> ErrorClass:
    """Классификация исключения транспорта."""
    if isinstance(exc, httpx.TimeoutException | httpx.NetworkError):
        return ErrorClass.TRANSIENT
    if isinstance(exc, httpx.RemoteProtocolError):
        return ErrorClass.TRANSIENT
    if isinstance(exc, httpx.HTTPError):
        return ErrorClass.PERMANENT
    return ErrorClass.PERMANENT


def should_retry(error_class: ErrorClass) -> bool:
    """Повтор осмыслен только для transient и rate limit."""
    return error_class in {ErrorClass.TRANSIENT, ErrorClass.RATE_LIMIT}


def parse_retry_after(value: str | None, *, now: datetime | None = None) -> float | None:
    """Разбирает `Retry-After` (секунды или HTTP-date). None — заголовка нет/невалиден."""
    if value is None:
        return None
    raw = value.strip()
    if not raw:
        return None
    try:
        return max(float(raw), 0.0)
    except ValueError:
        pass
    try:
        parsed = parsedate_to_datetime(raw)
    except (TypeError, ValueError):
        return None
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    reference = now or datetime.now(UTC)
    return max((parsed - reference).total_seconds(), 0.0)


def backoff_delay(attempt: int, policy: RetryPolicy, rng: random.Random) -> float:
    """Exponential backoff с усечённым jitter.

    `attempt` — номер **следующей** попытки, начиная с 1.
    Итог лежит в `[base*(1-jitter_ratio), base]`, где `base` ограничен `max_delay`.
    """
    exponent = max(attempt - 1, 0)
    base = min(policy.base_delay_seconds * (2**exponent), policy.max_delay_seconds)
    if policy.jitter_ratio <= 0:
        return base
    return base * (1.0 - policy.jitter_ratio * rng.random())


def next_delay(
    *,
    attempt: int,
    policy: RetryPolicy,
    rng: random.Random,
    retry_after_seconds: float | None,
) -> float:
    """Задержка перед повтором: `Retry-After` уважается, но не сокращает backoff."""
    computed = backoff_delay(attempt, policy, rng)
    if retry_after_seconds is None:
        return computed
    return max(computed, retry_after_seconds)


def retry_after_exceeds_budget(
    retry_after_seconds: float | None, policy: RetryPolicy
) -> bool:
    """True, если провайдер просит паузу больше согласованного бюджета."""
    return (
        retry_after_seconds is not None
        and retry_after_seconds > policy.max_retry_after_seconds
    )
